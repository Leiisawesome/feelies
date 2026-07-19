"""Property tests for the G-7 sizing tilt (position-mgmt audit 2026-07-02 P2).

``tests/risk/test_edge_weighted_sizer.py`` pins the tilt-bounds contract
with fixed examples (``test_recapped_at_budget``, ``test_combined_tilt_clamped``).
This module complements them with randomized ``SizerTiltConfig`` /
``apply_tilt`` inputs, asserting the invariant that must hold regardless of
how aggressively an operator configures the tilt factors: the sized
quantity is never negative and never exceeds the alpha's declared
``max_position_per_symbol`` (Inv-11 — amplification is deliberate for G-7,
but always structurally bounded).
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings, strategies as st

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import Signal, SignalDirection
from feelies.risk.edge_weighted_sizer import EdgeWeightedSizer, SizerTiltConfig, apply_tilt
from feelies.risk.position_sizer import BudgetBasedSizer

# ── apply_tilt: the low-level clamp itself ──────────────────────────────


@given(
    base_target=st.integers(min_value=0, max_value=1_000_000),
    tilt=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    max_position=st.integers(min_value=1, max_value=1_000_000),
)
@settings(max_examples=200)
def test_apply_tilt_always_within_bounds(base_target: int, tilt: float, max_position: int) -> None:
    result = apply_tilt(base_target, tilt, max_position)
    assert 0 <= result <= max_position


# ── EdgeWeightedSizer: the composed pipeline an operator actually drives ─

_tilt_configs = st.builds(
    SizerTiltConfig,
    edge_enabled=st.booleans(),
    edge_ref_bps=st.floats(min_value=0.1, max_value=200.0, allow_nan=False, allow_infinity=False),
    edge_floor=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    edge_cap=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    vol_enabled=st.booleans(),
    vol_target_bps=st.floats(
        min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    vol_floor=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    vol_cap=st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    inventory_enabled=st.booleans(),
    inventory_floor=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    tilt_floor=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    tilt_cap=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
)


@given(
    config=_tilt_configs,
    edge_bps=st.floats(min_value=-50.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    realized_vol_bps=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    ),
    inventory_qty=st.integers(min_value=-1000, max_value=1000),
    strength=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    max_position_per_symbol=st.integers(min_value=1, max_value=2_000),
    direction=st.sampled_from([SignalDirection.LONG, SignalDirection.SHORT]),
)
@settings(max_examples=200)
def test_edge_weighted_sizer_never_exceeds_budget(
    config: SizerTiltConfig,
    edge_bps: float,
    realized_vol_bps: float | None,
    inventory_qty: int,
    strength: float,
    max_position_per_symbol: int,
    direction: SignalDirection,
) -> None:
    budget = AlphaRiskBudget(
        max_position_per_symbol=max_position_per_symbol,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=10.0,
    )
    signal = Signal(
        timestamp_ns=1_000,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="prop_alpha",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )
    sizer = EdgeWeightedSizer(
        BudgetBasedSizer(),
        config,
        realized_vol_provider=lambda _sym: realized_vol_bps,
        inventory_provider=lambda _sym: inventory_qty,
    )
    target = sizer.compute_target_quantity(
        signal=signal,
        risk_budget=budget,
        symbol_price=Decimal("100"),
        account_equity=Decimal("1000000"),
    )
    assert 0 <= target <= max_position_per_symbol
