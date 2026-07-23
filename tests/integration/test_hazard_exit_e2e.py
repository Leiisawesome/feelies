"""End-to-end: a regime hazard spike actually closes an open position.

This integration locks the full regime-to-hazard behavior:

    regime-flip RegimeState pair
      → RegimeHazardDetector.detect()
      → RegimeHazardSpike on the bus
      → HazardExitController._on_spike()
      → OrderRequest(reason="HAZARD_SPIKE") on the bus

The fixture reuses the synthetic 7-tick regime-flip sequence from
``tests/determinism/test_regime_hazard_replay.py`` so the spike
stream is the same one the Level-5 hazard-replay parity hash locks.
A position is pre-seeded into :class:`MemoryPositionStore` long
enough to clear the controller's ``min_age_seconds`` guard, and we
assert that the controller emits exactly one ``OrderRequest`` per
detected spike (modulo episode-suppression), with the right side
(``SELL`` for the long), the right quantity (the full position), and
the right reason tag.
"""

from __future__ import annotations

from decimal import Decimal


from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    RegimeState,
    Side,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy
from feelies.services.regime_hazard_detector import RegimeHazardDetector


_STATE_NAMES = ("compression", "normal", "vol_breakout")
_ENGINE = "HMM3StateFractional"
_SYMBOL = "AAPL"
_STRATEGY = "sig_hawkes_burst_v1"


def _state(
    *,
    posteriors: tuple[float, float, float],
    dominant_idx: int,
    sequence: int,
    timestamp_ns: int,
) -> RegimeState:
    return RegimeState(
        timestamp_ns=timestamp_ns,
        correlation_id=f"corr-{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        engine_name=_ENGINE,
        state_names=_STATE_NAMES,
        posteriors=posteriors,
        dominant_state=dominant_idx,
        dominant_name=_STATE_NAMES[dominant_idx],
    )


def _fixture_states() -> list[RegimeState]:
    """Canonical 7-tick regime-flip fixture from the L5 hazard-replay
    determinism test — keeps this integration's spike stream in lock-
    step with the parity-hashed reference (Inv-5)."""
    return [
        _state(
            posteriors=(0.05, 0.95, 0.00), dominant_idx=1, sequence=0, timestamp_ns=1_000_000_000
        ),
        # Quiet decay below the floor — spike(1) fires.
        _state(
            posteriors=(0.40, 0.60, 0.00), dominant_idx=1, sequence=1, timestamp_ns=2_000_000_000
        ),
        # Same departure episode — suppressed.
        _state(
            posteriors=(0.50, 0.50, 0.00), dominant_idx=1, sequence=2, timestamp_ns=3_000_000_000
        ),
        # ``normal`` recovers above the floor — re-arm.
        _state(
            posteriors=(0.10, 0.85, 0.05), dominant_idx=1, sequence=3, timestamp_ns=4_000_000_000
        ),
        # Hard flip to vol_breakout — spike(2) fires.
        _state(
            posteriors=(0.05, 0.20, 0.75), dominant_idx=2, sequence=4, timestamp_ns=5_000_000_000
        ),
        # vol_breakout decays below floor — spike(3) fires.
        _state(
            posteriors=(0.30, 0.45, 0.25), dominant_idx=1, sequence=5, timestamp_ns=6_000_000_000
        ),
        # Quiet — no new spike.
        _state(
            posteriors=(0.05, 0.95, 0.00), dominant_idx=1, sequence=6, timestamp_ns=7_000_000_000
        ),
    ]


def _wire(
    *,
    bus: EventBus,
    position_store: MemoryPositionStore,
    policies: list[HazardPolicy],
) -> tuple[RegimeHazardDetector, HazardExitController, list[OrderRequest]]:
    """Build a detector + controller pair attached to ``bus`` and
    return them along with a captured list of OrderRequest events."""
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]

    detector = RegimeHazardDetector(hysteresis_threshold=0.30)

    seq = SequenceGenerator()
    controller = HazardExitController(
        bus=bus,
        sequence_generator=seq,
        position_store=position_store,
    )
    for p in policies:
        controller.register_policy(p)
    controller.attach()

    return detector, controller, captured


def _drive(
    detector: RegimeHazardDetector,
    bus: EventBus,
    states: list[RegimeState],
) -> int:
    """Replay the regime sequence through the detector, publishing any
    emitted spikes on ``bus``.  Returns the spike count for sanity."""
    n = 0
    prev: RegimeState | None = None
    for curr in states:
        spike = detector.detect(prev, curr)
        if spike is not None:
            bus.publish(spike)
            n += 1
        prev = curr
    return n


def _seed_long_position(
    store: MemoryPositionStore,
    *,
    symbol: str,
    quantity: int,
    price: Decimal,
    opened_at_ns: int,
) -> None:
    """Pre-seed an open long position on ``store`` with a timestamp
    old enough to clear any reasonable ``min_age_seconds`` guard."""
    store.update(
        symbol=symbol,
        quantity_delta=quantity,
        fill_price=price,
        timestamp_ns=opened_at_ns,
    )


# ── Tests ──────────────────────────────────────────────────────────


def test_hazard_spike_closes_an_open_position() -> None:
    """Headline behavior: an open position aged past ``min_age_seconds``
    is closed by an emitted ``OrderRequest(reason="HAZARD_SPIKE")``
    the first time a spike clears the per-alpha threshold."""
    bus = EventBus()
    store = MemoryPositionStore()

    # Opened well before the first spike (which fires at t = 2e9 ns,
    # i.e. 2 s into the fixture).
    _seed_long_position(
        store,
        symbol=_SYMBOL,
        quantity=100,
        price=Decimal("150.00"),
        opened_at_ns=0,
    )

    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=0.30,  # The alpha's declared threshold.
        min_age_seconds=1,  # Well below the spike-1 age.
        universe=(_SYMBOL,),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )

    spike_count = _drive(detector, bus, _fixture_states())
    # L5-locked: the fixture produces exactly three spikes.
    assert spike_count == 3

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert len(hazard_orders) == 1, (
        "Exactly one HAZARD_SPIKE order is expected — the controller "
        "must suppress further spikes for the same open position via "
        "its (strategy_id, symbol, reason) key until the position "
        "returns to flat."
    )

    order = hazard_orders[0]
    assert order.symbol == _SYMBOL
    assert order.side == Side.SELL, "long position must close via SELL"
    assert order.quantity == 100, "must close the full position"
    assert order.strategy_id == _STRATEGY


def test_hazard_spike_below_threshold_does_not_exit() -> None:
    """When the controller's ``hazard_score_threshold`` is above every
    spike's score, no OrderRequest is emitted.  This is the
    contrapositive that proves the threshold gate is wired."""
    bus = EventBus()
    store = MemoryPositionStore()
    _seed_long_position(
        store,
        symbol=_SYMBOL,
        quantity=100,
        price=Decimal("150.00"),
        opened_at_ns=0,
    )

    # Set the threshold above the maximum hazard score the fixture
    # produces (the largest decay yields a score < 1.0; using 1.5
    # guarantees no spike clears).
    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=1.5,
        min_age_seconds=0,
        universe=(_SYMBOL,),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )
    _drive(detector, bus, _fixture_states())

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert hazard_orders == []


def test_min_age_blocks_exit_until_position_seasons() -> None:
    """The ``min_age_seconds`` guard must block exits on positions
    that haven't seasoned yet — a freshly-opened position should
    NOT be closed even if a spike's score exceeds the threshold."""
    bus = EventBus()
    store = MemoryPositionStore()

    # Open the position AFTER the spike timestamps so age is
    # effectively negative when the spike fires.
    _seed_long_position(
        store,
        symbol=_SYMBOL,
        quantity=100,
        price=Decimal("150.00"),
        opened_at_ns=10_000_000_000,  # 10 s — after the last fixture tick.
    )

    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=0.30,
        min_age_seconds=30,
        universe=(_SYMBOL,),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )
    _drive(detector, bus, _fixture_states())

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert hazard_orders == [], (
        "Position that hasn't aged past min_age_seconds must NOT be closed by a hazard spike"
    )


def test_no_open_position_does_not_emit_order() -> None:
    """A spike for a flat symbol must not synthesize an exit order
    (Inv-11: hazard exits are exit-only — never open a position).
    """
    bus = EventBus()
    store = MemoryPositionStore()
    # No position seeded.

    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=0.30,
        min_age_seconds=0,
        universe=(_SYMBOL,),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )
    _drive(detector, bus, _fixture_states())

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert hazard_orders == []


def test_short_position_exits_via_buy_side() -> None:
    """The exit order must reverse the position's sign: a short
    closes via BUY, mirroring the long-case SELL.  Verifying both
    directions guarantees the side-derivation logic is exercised."""
    bus = EventBus()
    store = MemoryPositionStore()
    _seed_long_position(
        store,
        symbol=_SYMBOL,
        quantity=-100,  # short
        price=Decimal("150.00"),
        opened_at_ns=0,
    )

    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=0.30,
        min_age_seconds=1,
        universe=(_SYMBOL,),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )
    _drive(detector, bus, _fixture_states())

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert len(hazard_orders) == 1
    order = hazard_orders[0]
    assert order.side == Side.BUY
    assert order.quantity == 100  # unsigned size


def test_universe_filter_excludes_off_universe_symbols() -> None:
    """A spike for a symbol outside the policy's ``universe`` must
    not emit an order — proving the per-policy symbol filter is
    wired and the controller doesn't blindly chase every spike on
    the bus."""
    bus = EventBus()
    store = MemoryPositionStore()
    _seed_long_position(
        store,
        symbol=_SYMBOL,
        quantity=100,
        price=Decimal("150.00"),
        opened_at_ns=0,
    )

    # Policy universe is MSFT only — AAPL spikes must be ignored.
    policy = HazardPolicy(
        strategy_id=_STRATEGY,
        hazard_score_threshold=0.30,
        min_age_seconds=1,
        universe=("MSFT",),
    )
    detector, _controller, captured = _wire(
        bus=bus,
        position_store=store,
        policies=[policy],
    )
    _drive(detector, bus, _fixture_states())  # AAPL spikes only.

    hazard_orders = [
        o for o in captured if isinstance(o, OrderRequest) and o.reason == "HAZARD_SPIKE"
    ]
    assert hazard_orders == [], (
        "Spike on AAPL must not trigger an exit when the policy's universe is MSFT-only"
    )
