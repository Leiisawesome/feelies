"""Closes G-A and G-B from the Acceptance Sweep gap inventory.

Two acceptance lines from §18.2 are mechanically asserted here:

* **G-A** — §18.2 #6: "Reference SIGNAL alpha (`pofi_benign_midcap_v1`)
  runs end-to-end with `margin_ratio ≥ 1.5` verified at load."
  Generalised to **all five** v0.2/v0.3 reference SIGNAL alphas to
  catch silent regressions across the family rather than a single
  baseline.  Each YAML is loaded through :class:`AlphaLoader`; the
  resulting :class:`LoadedSignalLayerModule` exposes a validated
  :class:`CostArithmetic` instance whose ``margin_ratio`` is the
  number this test guards.

* **G-B** — §18.2 #7: "Reference PORTFOLIO alpha runs end-to-end with
  factor exposures within tolerance."  Loads
  ``pofi_xsect_v1`` (the canonical PORTFOLIO reference) and runs the
  declared factor model through :class:`FactorNeutralizer`, primed
  from ``storage/reference/factor_loadings/loadings.json``.  Asserts
  every post-neutralization residual factor exposure is within
  ``1e-9`` of zero on a non-trivial weight vector across the symbols
  for which loadings exist.

The cost-arithmetic loader (``CostArithmetic.from_spec``) already
rejects any ``margin_ratio < 1.5`` at load time, so a regression
where someone lowers the floor in the YAML would be caught
immediately on import.  Asserting at this layer is therefore
*defence-in-depth* against accidental relaxations of the validator
itself — if a future PR weakens ``CostArithmetic.from_spec``, the
test still pins the >= 1.5 contract per reference alpha.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.composition.factor_neutralizer import FactorNeutralizer


_ALPHAS_ROOT = Path("alphas")
_FACTOR_LOADINGS_DIR = Path("storage/reference/factor_loadings")


# G-A — every reference SIGNAL alpha must clear the 1.5 floor at load
# time.  Adding a new reference SIGNAL alpha?  Add it here so the
# acceptance matrix's #6 row stays accurate.
_REFERENCE_SIGNAL_ALPHAS: tuple[str, ...] = (
    "pofi_benign_midcap_v1",
    "pofi_moc_imbalance_v1",
    "pofi_kyle_drift_v1",
    "pofi_inventory_revert_v1",
    "pofi_hawkes_burst_v1",
)


_MARGIN_RATIO_FLOOR: float = 1.5


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_margin_ratio_floor(alpha_id: str) -> None:
    spec_path = _ALPHAS_ROOT / alpha_id / f"{alpha_id}.alpha.yaml"
    assert spec_path.exists(), (
        f"reference SIGNAL alpha YAML missing at {spec_path}; "
        "acceptance matrix row §18.2 #6 cannot be verified for "
        f"{alpha_id!r} until the file is restored or the matrix is "
        "updated."
    )

    loader = AlphaLoader()
    module = loader.load(spec_path)

    assert isinstance(module, LoadedSignalLayerModule), (
        f"{alpha_id!r} loaded as {type(module).__name__}; expected "
        "LoadedSignalLayerModule.  Acceptance matrix row §18.2 #6 "
        "tracks SIGNAL-layer alphas only — update the reference list "
        "if the YAML's layer changed."
    )

    cost = module.cost
    assert cost.margin_ratio >= _MARGIN_RATIO_FLOOR, (
        f"{alpha_id!r}: declared cost_arithmetic.margin_ratio = "
        f"{cost.margin_ratio}, below the §18.2 #6 floor of "
        f"{_MARGIN_RATIO_FLOOR}.  CostArithmetic.from_spec should have "
        "rejected this at load time — if the load succeeded, the "
        "validator was likely weakened in the same PR.  Either restore "
        "the floor or update docs/acceptance/v02_v03_matrix.md to "
        "explicitly reflect the change."
    )

    # Defence in depth: the disclosed margin_ratio must agree with the
    # value implied by the declared component breakdown to the same
    # tolerance the validator uses (1%).  If they ever drift, the
    # validator's cross-check would have caught it — but if a future
    # refactor relaxes that cross-check, this assertion is the
    # backstop.
    computed = cost.computed_margin_ratio
    declared = cost.margin_ratio
    rel_diff = abs(computed - declared) / max(declared, 1e-9)
    assert rel_diff <= 0.01, (
        f"{alpha_id!r}: declared margin_ratio={declared}, computed="
        f"{computed:.4f} (relative drift {rel_diff:.4%}).  The Phase-3a "
        "CostArithmetic validator enforces a 1% tolerance — a value "
        "outside it indicates the validator itself was weakened."
    )


# G-B — reference PORTFOLIO alpha factor exposures.
_PORTFOLIO_REFERENCE_ALPHA = "pofi_xsect_v1"
_FACTOR_EXPOSURE_TOLERANCE: float = 1e-9


def _loaded_factor_symbols() -> tuple[str, ...]:
    """Return the universe of symbols for which reference loadings exist."""
    path = _FACTOR_LOADINGS_DIR / "loadings.json"
    assert path.exists(), (
        f"factor loadings reference file missing at {path}; "
        "acceptance matrix row §18.2 #7 cannot be verified."
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict) and raw, (
        f"{path}: must be a non-empty JSON object of "
        "{symbol: {factor: loading}}"
    )
    return tuple(sorted(raw.keys()))


def test_portfolio_factor_exposure_within_tolerance() -> None:
    pytest.importorskip(
        "numpy",
        reason=(
            "FactorNeutralizer requires numpy; install the [portfolio] "
            "extra to enable G-B coverage."
        ),
    )

    spec_path = (
        _ALPHAS_ROOT
        / _PORTFOLIO_REFERENCE_ALPHA
        / f"{_PORTFOLIO_REFERENCE_ALPHA}.alpha.yaml"
    )
    assert spec_path.exists(), (
        f"reference PORTFOLIO alpha YAML missing at {spec_path}"
    )

    # Loading is part of the acceptance criterion (the alpha must
    # *load* end-to-end before its factor neutralization can be tested).
    loader = AlphaLoader()
    module = loader.load(spec_path)
    assert module.manifest.alpha_id == _PORTFOLIO_REFERENCE_ALPHA

    universe = _loaded_factor_symbols()
    assert len(universe) >= 5, (
        "expected at least 5 reference symbols in loadings.json to "
        "exercise factor neutralization meaningfully"
    )

    # Build a deliberately non-degenerate weight vector so that each
    # factor has a non-trivial pre-neutralization exposure.  A flat
    # vector or alternating signs can accidentally land in the null
    # space of the loadings matrix and pass for the wrong reason.
    weights: dict[str, float] = {
        sym: ((-1.0) ** i) * (1.0 + 0.1 * i)
        for i, sym in enumerate(universe)
    }

    neutralizer = FactorNeutralizer(loadings_dir=_FACTOR_LOADINGS_DIR)
    neutralized, post_exposure = neutralizer.neutralize(weights, universe)

    assert set(neutralized.keys()) == set(universe), (
        "FactorNeutralizer must return one weight per universe symbol"
    )
    assert post_exposure, (
        "FactorNeutralizer returned no factor exposures — confirm the "
        "loadings file declares the same factors as the model declared "
        "by the reference PORTFOLIO alpha."
    )

    for factor, exposure in post_exposure.items():
        assert abs(exposure) <= _FACTOR_EXPOSURE_TOLERANCE, (
            f"factor {factor!r}: post-neutralization exposure "
            f"{exposure:.3e} exceeds tolerance "
            f"{_FACTOR_EXPOSURE_TOLERANCE:.0e}.  Either the "
            "FactorNeutralizer projection regressed, or the loadings "
            "matrix became rank-deficient (B^T B singular)."
        )
