"""Pin load-time invariants for reference alphas.

Every reference signal alpha must expose a validated cost margin of at least
1.5. The reference portfolio alpha must neutralize bundled factor exposures to
within ``1e-9``. These checks also protect against validator relaxation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.storage.reference.paths import FACTOR_LOADINGS_DIR as _FACTOR_LOADINGS_DIR


_ALPHAS_ROOT = Path("alphas")


# Every reference signal alpha must clear the 1.5 load-time floor.
_REFERENCE_SIGNAL_ALPHAS: tuple[str, ...] = (
    "sig_benign_midcap_v1",
    "sig_moc_imbalance_v1",
    "sig_kyle_drift_v1",
    "sig_inventory_revert_v1",
    "sig_hawkes_burst_v1",
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
_PORTFOLIO_REFERENCE_ALPHA = "pro_burst_revert_v1"
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
        f"{path}: must be a non-empty JSON object of {{symbol: {{factor: loading}}}}"
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
        / "research"
        / _PORTFOLIO_REFERENCE_ALPHA
        / f"{_PORTFOLIO_REFERENCE_ALPHA}.alpha.yaml"
    )
    assert spec_path.exists(), f"reference PORTFOLIO alpha YAML missing at {spec_path}"

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
        sym: ((-1.0) ** i) * (1.0 + 0.1 * i) for i, sym in enumerate(universe)
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
