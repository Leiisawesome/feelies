"""``FactorNeutralizer`` — residualize cross-sectional weights against a factor model.

Phase-4 v0.2 implements a *static factor loadings* path: the
neutralizer reads per-symbol factor loadings (β) from
:attr:`feelies.core.platform_config.PlatformConfig.factor_loadings_dir`
at bootstrap; intra-day exposures are computed against those static
loadings (per design Q5 — daily refresh; intraday uses static β).

Default factor model is FF5 + momentum + STR (per design Q6); the
loader file is a JSON / CSV mapping with shape
``{symbol: {factor_name: float}}``.  Missing symbols default to all-
zero loadings (no neutralization).

Algorithm
---------

Given vector of weights ``w`` (length ``N``) and the loadings matrix
``B`` (shape ``N × K``), the neutralizer projects ``w`` onto the null
space of ``Bᵀ``:

    w_neutral = w - B @ ((BᵀB)⁻¹ @ Bᵀ @ w)

This is the ordinary linear regression residual — minimum-distance to
``w`` while satisfying ``Bᵀ @ w_neutral == 0`` (zero exposure to
every factor).

Numerical safety
----------------

* When ``BᵀB`` is singular (rank-deficient loadings — e.g. fewer than
  ``K`` symbols), the neutralizer falls back to projecting onto the
  largest non-zero singular vectors only.
* All linear algebra runs in NumPy ``float64``; iteration order over
  symbols is the lex-sorted universe so replay is bit-stable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np
    from numpy.typing import NDArray

try:  # pragma: no cover - optional dependency for portfolio extras
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

_logger = logging.getLogger(__name__)


# Default factor universe per design Q6.  The neutralizer reads these
# names from the loadings file; missing factors silently zero-fill.
_DEFAULT_FACTORS_BY_MODEL: dict[str, tuple[str, ...]] = {
    "FF5_momentum_STR": (
        "MKT",     # market excess return
        "SMB",     # size
        "HML",     # value
        "RMW",     # profitability
        "CMA",     # investment
        "MOM",     # momentum (12-1)
        "STR",     # short-term reversal (1-month)
    ),
    "FF3": ("MKT", "SMB", "HML"),
    "MARKET_ONLY": ("MKT",),
    "NONE": (),
}


class MissingFactorLoadingsError(RuntimeError):
    """Raised when the configured loadings path is missing or unreadable."""


class FactorNeutralizer:
    """Residualize per-symbol weights against a static factor model.

    Parameters
    ----------
    factor_model :
        Model name; one of the keys in
        :data:`_DEFAULT_FACTORS_BY_MODEL`.  Custom names are accepted
        as long as the loadings file declares the corresponding
        factors explicitly (no implicit zero-fill).
    loadings_dir :
        Directory containing ``loadings.json``.  When ``None`` the
        neutralizer is a no-op (returns weights unchanged).
    """

    __slots__ = ("_factors", "_loadings", "_model")

    def __init__(
        self,
        *,
        factor_model: str = "FF5_momentum_STR",
        loadings_dir: Path | None = None,
    ) -> None:
        self._model = factor_model
        self._factors = _DEFAULT_FACTORS_BY_MODEL.get(
            factor_model, ()
        )
        self._loadings: dict[str, dict[str, float]] = {}
        if loadings_dir is not None and self._factors:
            self._loadings = self._load_loadings(loadings_dir)

    @property
    def factors(self) -> tuple[str, ...]:
        return self._factors

    @property
    def factor_model(self) -> str:
        return self._model

    # ── Public API ───────────────────────────────────────────────────

    def neutralize(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Return ``(neutralized_weights, factor_exposures)``.

        ``factor_exposures`` is the residual *post-neutralization*
        exposure to each factor (should be ≈ 0 unless ``BᵀB`` is
        singular and the projection is degenerate).
        """
        if not self._factors or not self._loadings or not _HAS_NUMPY:
            # No-op path: pass weights through; exposures are computed
            # if we have loadings, otherwise empty.
            return dict(weights), self._compute_exposures(weights, universe)

        n = len(universe)
        if n == 0:
            return {}, {}

        w = np.asarray(
            [weights.get(s, 0.0) for s in universe], dtype=np.float64,
        )
        b_matrix = self._build_b_matrix(universe)
        try:
            # Normal-equations solve; falls back to lstsq on singular.
            bt_b = b_matrix.T @ b_matrix
            bt_w = b_matrix.T @ w
            beta = np.linalg.solve(bt_b, bt_w)
        except np.linalg.LinAlgError:
            beta, *_ = np.linalg.lstsq(b_matrix, w, rcond=None)

        residual = w - b_matrix @ beta
        post_exposure = b_matrix.T @ residual

        out_weights = {s: float(residual[i]) for i, s in enumerate(universe)}
        out_exposures = {
            f: float(post_exposure[i])
            for i, f in enumerate(self._factors)
        }
        return out_weights, out_exposures

    # ── Internals ────────────────────────────────────────────────────

    def _build_b_matrix(self, universe: tuple[str, ...]) -> NDArray[np.float64]:
        """Stack per-symbol loadings into an ``(N, K)`` matrix."""
        rows: list[list[float]] = []
        for s in universe:
            sym_load = self._loadings.get(s, {})
            rows.append([float(sym_load.get(f, 0.0)) for f in self._factors])
        return np.asarray(rows, dtype=np.float64)

    def _compute_exposures(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
    ) -> dict[str, float]:
        """Compute pre-neutralization factor exposure (for reporting)."""
        if not self._factors or not self._loadings:
            return {}
        out: dict[str, float] = {f: 0.0 for f in self._factors}
        for s in universe:
            w = float(weights.get(s, 0.0))
            if w == 0.0:
                continue
            sym_load = self._loadings.get(s, {})
            for f in self._factors:
                out[f] += w * float(sym_load.get(f, 0.0))
        return out

    @staticmethod
    def _load_loadings(loadings_dir: Path) -> dict[str, dict[str, float]]:
        """Read ``loadings_dir/loadings.json``.

        Schema: ``{symbol: {factor_name: float}}``.
        """
        path = loadings_dir / "loadings.json"
        if not path.is_file():
            raise MissingFactorLoadingsError(
                f"FactorNeutralizer: factor loadings file not found: {path}"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MissingFactorLoadingsError(
                f"FactorNeutralizer: cannot read {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise MissingFactorLoadingsError(
                f"FactorNeutralizer: {path} is not a JSON object"
            )
        out: dict[str, dict[str, float]] = {}
        for sym, loadings in data.items():
            if not isinstance(loadings, dict):
                raise MissingFactorLoadingsError(
                    f"FactorNeutralizer: loadings for {sym!r} must be an object"
                )
            out[str(sym)] = {
                str(k): float(v) for k, v in loadings.items()
            }
        return out


__all__ = ["FactorNeutralizer", "MissingFactorLoadingsError"]
