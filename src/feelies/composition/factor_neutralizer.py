"""Residualize cross-sectional weights against static factor loadings.

For weights ``w`` and loadings matrix ``B``:

    w_neutral = w - B @ ((BᵀB)⁻¹ @ Bᵀ @ w)

Normal equations use ``numpy.linalg.solve`` and fall back to least squares for
rank-deficient loadings. Symbols are sorted before float64 linear algebra so
replays use a stable reduction order.
"""

from __future__ import annotations

import hashlib
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


# Missing factors in the selected model receive zero loadings.
_DEFAULT_FACTORS_BY_MODEL: dict[str, tuple[str, ...]] = {
    "FF5_momentum_STR": (
        "MKT",  # market excess return
        "SMB",  # size
        "HML",  # value
        "RMW",  # profitability
        "CMA",  # investment
        "MOM",  # momentum (12-1)
        "STR",  # short-term reversal (1-month)
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
        self._factors = _DEFAULT_FACTORS_BY_MODEL.get(factor_model, ())
        self._loadings: dict[str, dict[str, float]] = {}
        if loadings_dir is not None and self._factors:
            self._loadings = self._load_loadings(loadings_dir)

    @property
    def factors(self) -> tuple[str, ...]:
        return self._factors

    @property
    def factor_model(self) -> str:
        return self._model

    def provenance_digest(self) -> str:
        """Stable digest of the neutralizer's decision-affecting state.

        Folds the factor-model identity and the loaded β matrix into the
        composition-layer ``decision_basis_hash`` so the digest changes
        with the model or loadings. An empty table still yields a
        stable model-only digest.
        """
        parts = [f"model={self._model}"]
        for sym in sorted(self._loadings):
            row = self._loadings[sym]
            cells = ",".join(f"{f}={row[f]:.10g}" for f in sorted(row))
            parts.append(f"{sym}:{cells}")
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

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
            return dict(weights), self.compute_exposures(weights, universe)

        n = len(universe)
        if n == 0:
            return {}, {}

        w = np.asarray(
            [weights.get(s, 0.0) for s in universe],
            dtype=np.float64,
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
        out_exposures = {f: float(post_exposure[i]) for i, f in enumerate(self._factors)}
        return out_weights, out_exposures

    # ── Internals ────────────────────────────────────────────────────

    def _build_b_matrix(self, universe: tuple[str, ...]) -> NDArray[np.float64]:
        """Stack per-symbol loadings into an ``(N, K)`` matrix."""
        rows: list[list[float]] = []
        for s in universe:
            sym_load = self._loadings.get(s, {})
            rows.append([float(sym_load.get(f, 0.0)) for f in self._factors])
        return np.asarray(rows, dtype=np.float64)

    def compute_exposures(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
    ) -> dict[str, float]:
        """Compute factor exposure of *weights* (for reporting).

        Public so the composition engine can report the carried exposure
        of an alpha that opted out of neutralization (``factor_neutralization:
        false``) without residualizing it. Returns ``{}`` when
        no loadings are configured.
        """
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
            raise MissingFactorLoadingsError(f"FactorNeutralizer: {path} is not a JSON object")
        out: dict[str, dict[str, float]] = {}
        for sym, loadings in data.items():
            # _meta is provenance, not a symbol row.
            if sym == "_meta":
                continue
            if not isinstance(loadings, dict):
                raise MissingFactorLoadingsError(
                    f"FactorNeutralizer: loadings for {sym!r} must be an object"
                )
            out[str(sym)] = {str(k): float(v) for k, v in loadings.items()}
        return out


__all__ = ["FactorNeutralizer", "MissingFactorLoadingsError"]
