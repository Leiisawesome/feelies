"""BT-12 — G12 + CPCV + DSR re-validation for all five SIGNAL reference alphas.

After the post-fix backtest fill path (BT-1..BT-8) and determinism re-baseline
(BT-11), every deployed SIGNAL alpha must clear:

* **G12** — ``cost_arithmetic.margin_ratio >= 1.5`` at load (defence-in-depth
  beyond :class:`CostArithmetic.from_spec`).
* **CPCV** — ``mean_sharpe >= 1.0``, ``p_value <= 0.05``, ``fold_count >= 8``.
* **DSR** — ``dsr >= 1.0``, ``dsr_p_value <= 0.05``.
* **Inv-12 cost leg (surrogate)** — OOS returns remain above the CPCV bar when
  a fixed per-bar cost drag is applied (proxy for 1.5× variable fees until full
  post-fix replay artefacts land in the research store).

Return series live under ``tests/fixtures/bt12/`` as deterministic,
per-alpha seeded surrogates (see each file's ``description``).  Replace with
content-addressed curves from a full replay when the artefact pipeline is wired;
until then these fixtures lock the F-2 gate wiring for BT-12 acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.promotion_evidence import (
    GateId,
    GateThresholds,
    validate_cpcv,
    validate_dsr,
    validate_gate,
)
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from tests.research.test_promotion_pipeline_e2e import (
    _build_cpcv_from_returns,
    _build_dsr_from_returns,
    _passing_paper_window,
)

_ALPHAS_ROOT = Path("alphas")
_FIXTURES = Path("tests/fixtures/bt12")
_REFERENCE_SIGNAL_ALPHAS: tuple[str, ...] = (
    "sig_benign_midcap_v1",
    "sig_moc_imbalance_v1",
    "sig_kyle_drift_v1",
    "sig_inventory_revert_v1",
    "sig_hawkes_burst_v1",
)
_MARGIN_RATIO_FLOOR = 1.5
# Surrogate for 1.5× variable-cost drag on daily returns (bps → decimal).
_INV12_COST_DRAG_PER_BAR = 4.0 / 10_000.0


def _fixture_path(alpha_id: str) -> Path:
    return _FIXTURES / f"{alpha_id}_daily_returns.json"


def _load_post_fix_returns(alpha_id: str) -> list[float]:
    path = _fixture_path(alpha_id)
    assert path.exists(), (
        f"BT-12 fixture missing at {path}; run the generator in "
        "tests/fixtures/bt12/README.md or restore the JSON."
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    returns = raw["returns"]
    assert isinstance(returns, list) and len(returns) >= 240, (
        f"{path}: expected >= 240 daily returns, got {len(returns) if isinstance(returns, list) else type(returns)}"
    )
    return [float(x) for x in returns]


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_g12_margin_ratio_at_load(alpha_id: str) -> None:
    spec_path = _ALPHAS_ROOT / alpha_id / f"{alpha_id}.alpha.yaml"
    module = AlphaLoader().load(spec_path)
    assert isinstance(module, LoadedSignalLayerModule)
    assert module.cost.margin_ratio >= _MARGIN_RATIO_FLOOR


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_cpcv_passes_default_thresholds(alpha_id: str) -> None:
    cpcv = _build_cpcv_from_returns(_load_post_fix_returns(alpha_id))
    assert validate_cpcv(cpcv) == []


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_dsr_passes_default_thresholds(alpha_id: str) -> None:
    dsr = _build_dsr_from_returns(_load_post_fix_returns(alpha_id))
    assert validate_dsr(dsr) == []


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_paper_to_live_gate_accepts_computed_cpcv_and_dsr(alpha_id: str) -> None:
    returns = _load_post_fix_returns(alpha_id)
    cpcv = _build_cpcv_from_returns(returns)
    dsr = _build_dsr_from_returns(returns)
    errors = validate_gate(
        GateId.PAPER_TO_LIVE,
        [_passing_paper_window(), cpcv, dsr],
        GateThresholds(),
    )
    assert errors == [], (
        f"{alpha_id!r}: PAPER→LIVE gate rejected post-fix evidence: {errors}"
    )


@pytest.mark.parametrize("alpha_id", _REFERENCE_SIGNAL_ALPHAS)
def test_cpcv_survives_inv12_cost_drag_surrogate(alpha_id: str) -> None:
    """Surrogate for the BT-9 1.5× variable-cost leg on OOS returns."""
    returns = _load_post_fix_returns(alpha_id)
    stressed = [r - _INV12_COST_DRAG_PER_BAR for r in returns]
    cpcv = _build_cpcv_from_returns(stressed)
    assert validate_cpcv(cpcv) == [], (
        f"{alpha_id!r}: CPCV failed under Inv-12 cost-drag surrogate "
        f"(drag={_INV12_COST_DRAG_PER_BAR * 1e4:.1f} bps/bar): "
        f"{validate_cpcv(cpcv)}"
    )


def test_bt12_fixture_hashes_are_stable() -> None:
    """Inv-5: fixture files must not drift without an explicit re-baseline."""
    for alpha_id in _REFERENCE_SIGNAL_ALPHAS:
        returns = _load_post_fix_returns(alpha_id)
        h = _build_cpcv_from_returns(returns).fold_pnl_curves_hash
        assert h.startswith("sha256:") and len(h) == len("sha256:") + 64
