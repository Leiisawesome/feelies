"""Tests for :mod:`feelies.risk.hazard_exit`.

Phase-4-finalize replay byte-identity property test:

  Replaying the same ordered ``(RegimeHazardSpike | Trade)`` event
  stream through two independent ``HazardExitController`` instances
  must produce **byte-identical** ``OrderRequest`` streams (Inv-5 /
  Level-1 parity).  The Hypothesis strategy generates random ordered
  event sequences over a small universe and asserts that two parallel
  replays agree on every emitted order field.
"""

from __future__ import annotations

import json
from decimal import Decimal

from hypothesis import given, settings, strategies as st

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    RegimeHazardSpike,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy


_UNIVERSE = ("AAPL", "MSFT", "TSLA")
_STRATEGY_ID = "pofi_xsect_v1"


def _build_controller(
    seed_positions: dict[str, tuple[int, int]] | None = None,
) -> tuple[
    HazardExitController,
    MemoryPositionStore,
    EventBus,
    list[OrderRequest],
]:
    bus = EventBus()
    store = MemoryPositionStore()
    if seed_positions:
        for symbol, (qty, opened_at_ns) in seed_positions.items():
            store.update(
                symbol,
                quantity_delta=qty,
                fill_price=Decimal("100"),
                timestamp_ns=opened_at_ns,
            )

    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]

    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(start=10_000),
        position_store=store,
        policies={
            _STRATEGY_ID: HazardPolicy(
                strategy_id=_STRATEGY_ID,
                hazard_score_threshold=0.5,
                min_age_seconds=0,
                hard_exit_age_seconds=600,
                universe=_UNIVERSE,
            ),
        },
    )
    controller.attach()
    return controller, store, bus, received


def _serialize(orders: list[OrderRequest]) -> str:
    rows = []
    for o in orders:
        d = {
            "timestamp_ns": o.timestamp_ns,
            "sequence": o.sequence,
            "symbol": o.symbol,
            "side": o.side.name,
            "quantity": o.quantity,
            "strategy_id": o.strategy_id,
            "reason": o.reason,
            "order_id": o.order_id,
        }
        rows.append(d)
    return json.dumps(rows, sort_keys=True)


def test_emits_exit_on_spike_above_threshold():
    _, store, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 1_000_000_000)},
    )
    spike = RegimeHazardSpike(
        timestamp_ns=2_000_000_000,
        sequence=1,
        correlation_id="cid:spike1",
        source_layer="REGIME",
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        departing_state="normal",
        departing_posterior_prev=0.95,
        departing_posterior_now=0.10,
        incoming_state="vol_breakout",
        hazard_score=0.9,
    )
    bus.publish(spike)

    assert len(out) == 1
    order = out[0]
    assert order.symbol == "AAPL"
    assert order.reason == "HAZARD_SPIKE"
    assert order.quantity == 100
    assert order.side.name == "SELL"


def test_no_exit_when_position_flat():
    _, _, bus, out = _build_controller(seed_positions={})
    bus.publish(RegimeHazardSpike(
        timestamp_ns=2_000_000_000,
        sequence=1,
        correlation_id="cid:spike2",
        source_layer="REGIME",
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        departing_state="normal",
        departing_posterior_prev=0.99,
        departing_posterior_now=0.05,
        incoming_state="vol_breakout",
        hazard_score=0.99,
    ))
    assert out == []


def test_min_age_safeguard_blocks_premature_exit():
    _, _, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 2_000_000_000)},
    )
    # min_age_seconds=0 → reset for this test by re-registering policy
    # instead we'll create a controller with a stricter min_age.
    bus2 = EventBus()
    store2 = MemoryPositionStore()
    store2.update("AAPL", 100, Decimal("100"), timestamp_ns=2_000_000_000)
    received: list[OrderRequest] = []
    bus2.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    controller = HazardExitController(
        bus=bus2,
        sequence_generator=SequenceGenerator(),
        position_store=store2,
        policies={
            _STRATEGY_ID: HazardPolicy(
                strategy_id=_STRATEGY_ID,
                hazard_score_threshold=0.5,
                min_age_seconds=60,
                universe=_UNIVERSE,
            ),
        },
    )
    controller.attach()
    bus2.publish(RegimeHazardSpike(
        timestamp_ns=2_010_000_000,  # 10ms later, < 60s
        sequence=2,
        correlation_id="cid:spike3",
        source_layer="REGIME",
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        departing_state="normal",
        departing_posterior_prev=0.95,
        departing_posterior_now=0.10,
        incoming_state="vol_breakout",
        hazard_score=0.9,
    ))
    assert received == []


def test_hard_exit_age_emits_on_trade_after_cap():
    _, store, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 1_000_000_000)},
    )
    # Trade arrives 700s later — exceeds hard_exit_age_seconds=600.
    bus.publish(Trade(
        timestamp_ns=1_000_000_000 + 700 * 1_000_000_000,
        sequence=99,
        correlation_id="cid:trade1",
        source_layer="DATA",
        symbol="AAPL",
        price=Decimal("101"),
        size=10,
        exchange_timestamp_ns=1_000_000_000 + 700 * 1_000_000_000,
    ))
    assert len(out) == 1
    assert out[0].reason == "HARD_EXIT_AGE"


def test_episode_suppression_prevents_double_fire():
    _, _, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 1_000_000_000)},
    )
    spike1 = RegimeHazardSpike(
        timestamp_ns=2_000_000_000,
        sequence=1,
        correlation_id="cid:s1",
        source_layer="REGIME",
        symbol="AAPL",
        engine_name="hmm",
        departing_state="normal",
        departing_posterior_prev=0.95,
        departing_posterior_now=0.10,
        incoming_state="vol_breakout",
        hazard_score=0.9,
    )
    spike2 = RegimeHazardSpike(
        timestamp_ns=3_000_000_000,
        sequence=2,
        correlation_id="cid:s2",
        source_layer="REGIME",
        symbol="AAPL",
        engine_name="hmm",
        departing_state="normal",
        departing_posterior_prev=0.95,
        departing_posterior_now=0.05,
        incoming_state="vol_breakout",
        hazard_score=0.95,
    )
    bus.publish(spike1)
    bus.publish(spike2)
    assert len(out) == 1


@settings(max_examples=20, deadline=None)
@given(
    events=st.lists(
        st.tuples(
            st.sampled_from(["spike", "trade"]),
            st.sampled_from(_UNIVERSE),
            st.integers(min_value=1, max_value=1_000_000_000),
            st.floats(min_value=0.0, max_value=1.0),
        ),
        min_size=0,
        max_size=20,
    ),
)
def test_replay_byte_identical(events):
    """Two parallel replays of the same event stream emit identical bytes."""

    def run() -> str:
        _, store, bus, out = _build_controller(
            seed_positions={
                "AAPL": (100, 0),
                "MSFT": (-50, 0),
            },
        )
        ts = 1
        for kind, sym, dt, score in events:
            ts += dt
            if kind == "spike":
                bus.publish(RegimeHazardSpike(
                    timestamp_ns=ts,
                    sequence=ts,
                    correlation_id=f"cid:{ts}",
                    source_layer="REGIME",
                    symbol=sym,
                    engine_name="hmm",
                    departing_state="normal",
                    departing_posterior_prev=0.95,
                    departing_posterior_now=0.10,
                    incoming_state="vol_breakout",
                    hazard_score=score,
                ))
            else:
                bus.publish(Trade(
                    timestamp_ns=ts,
                    sequence=ts,
                    correlation_id=f"cid:{ts}",
                    source_layer="DATA",
                    symbol=sym,
                    price=Decimal("100"),
                    size=1,
                    exchange_timestamp_ns=ts,
                ))
        return _serialize(out)

    assert run() == run()
