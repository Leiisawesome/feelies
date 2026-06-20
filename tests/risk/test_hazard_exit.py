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
_STRATEGY_ID = "pro_xsect_v1"


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
    bus.publish(
        RegimeHazardSpike(
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
        )
    )
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
    bus2.publish(
        RegimeHazardSpike(
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
        )
    )
    assert received == []


def test_min_age_safeguard_allows_exit_at_exact_threshold():
    bus = EventBus()
    store = MemoryPositionStore()
    store.update("AAPL", 100, Decimal("100"), timestamp_ns=2_000_000_000)
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
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

    bus.publish(
        RegimeHazardSpike(
            timestamp_ns=2_000_000_000 + 60 * 1_000_000_000,
            sequence=3,
            correlation_id="cid:spike4",
            source_layer="REGIME",
            symbol="AAPL",
            engine_name="hmm_3state_fractional",
            departing_state="normal",
            departing_posterior_prev=0.95,
            departing_posterior_now=0.10,
            incoming_state="vol_breakout",
            hazard_score=0.9,
        )
    )

    assert len(received) == 1
    assert received[0].reason == "HAZARD_SPIKE"


def test_hard_exit_age_emits_on_trade_after_cap():
    _, store, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 1_000_000_000)},
    )
    # Trade arrives 700s later — exceeds hard_exit_age_seconds=600.
    bus.publish(
        Trade(
            timestamp_ns=1_000_000_000 + 700 * 1_000_000_000,
            sequence=99,
            correlation_id="cid:trade1",
            source_layer="DATA",
            symbol="AAPL",
            price=Decimal("101"),
            size=10,
            exchange_timestamp_ns=1_000_000_000 + 700 * 1_000_000_000,
        )
    )
    assert len(out) == 1
    assert out[0].reason == "HARD_EXIT_AGE"


def test_hard_exit_age_emits_on_trade_at_exact_cap():
    _, _, bus, out = _build_controller(
        seed_positions={"AAPL": (100, 1_000_000_000)},
    )
    bus.publish(
        Trade(
            timestamp_ns=1_000_000_000 + 600 * 1_000_000_000,
            sequence=100,
            correlation_id="cid:trade-exact-cap",
            source_layer="DATA",
            symbol="AAPL",
            price=Decimal("101"),
            size=10,
            exchange_timestamp_ns=1_000_000_000 + 600 * 1_000_000_000,
        )
    )

    assert len(out) == 1
    assert out[0].reason == "HARD_EXIT_AGE"


def test_hard_exit_age_uses_new_open_episode_after_sign_flip():
    bus = EventBus()
    store = MemoryPositionStore()
    store.update("AAPL", 100, Decimal("100"), timestamp_ns=0)
    reverse_ts_ns = 700 * 1_000_000_000
    store.update("AAPL", -200, Decimal("99"), timestamp_ns=reverse_ts_ns)

    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
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

    bus.publish(
        Trade(
            timestamp_ns=800 * 1_000_000_000,
            sequence=101,
            correlation_id="cid:trade-too-early-after-flip",
            source_layer="DATA",
            symbol="AAPL",
            price=Decimal("98"),
            size=10,
            exchange_timestamp_ns=800 * 1_000_000_000,
        )
    )
    bus.publish(
        Trade(
            timestamp_ns=reverse_ts_ns + 600 * 1_000_000_000,
            sequence=102,
            correlation_id="cid:trade-at-cap-after-flip",
            source_layer="DATA",
            symbol="AAPL",
            price=Decimal("97"),
            size=10,
            exchange_timestamp_ns=reverse_ts_ns + 600 * 1_000_000_000,
        )
    )

    assert store.opened_at_ns("AAPL") == reverse_ts_ns
    assert len(received) == 1
    assert received[0].reason == "HARD_EXIT_AGE"
    assert received[0].timestamp_ns == reverse_ts_ns + 600 * 1_000_000_000
    assert received[0].side.name == "BUY"
    assert received[0].quantity == 100


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
                bus.publish(
                    RegimeHazardSpike(
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
                    )
                )
            else:
                bus.publish(
                    Trade(
                        timestamp_ns=ts,
                        sequence=ts,
                        correlation_id=f"cid:{ts}",
                        source_layer="DATA",
                        symbol=sym,
                        price=Decimal("100"),
                        size=1,
                        exchange_timestamp_ns=ts,
                    )
                )
        return _serialize(out)

    assert run() == run()


# ── applies_to_regimes departing-state filter (§20.5.3 / §20.7.1) ─────────

from feelies.risk.hazard_exit import _spike_matches_regimes  # noqa: E402


def _spike(departing: str, incoming: str | None, *, score: float = 0.9, symbol: str = "AAPL"):
    return RegimeHazardSpike(
        timestamp_ns=2_000_000_000,
        sequence=1,
        correlation_id="cid:flt",
        source_layer="REGIME",
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        departing_state=departing,
        departing_posterior_prev=0.95,
        departing_posterior_now=0.10,
        incoming_state=incoming,
        hazard_score=score,
    )


def _controller_with_regimes(applies, seed=("AAPL", 100, 1_000_000_000)):
    bus = EventBus()
    store = MemoryPositionStore()
    if seed:
        store.update(seed[0], seed[1], Decimal("100"), timestamp_ns=seed[2])
    out: list[OrderRequest] = []
    bus.subscribe(OrderRequest, out.append)  # type: ignore[arg-type]
    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(start=10_000),
        position_store=store,
        policies={
            _STRATEGY_ID: HazardPolicy(
                strategy_id=_STRATEGY_ID,
                hazard_score_threshold=0.5,
                min_age_seconds=0,
                universe=_UNIVERSE,
                applies_to_regimes=applies,
            )
        },
    )
    controller.attach()
    return bus, out


def test_spike_matches_regimes_helper():
    # Empty filter ⇒ matches everything (backward compatible).
    assert _spike_matches_regimes("normal", "vol_breakout", ()) is True
    # Transition match / non-match.
    assert _spike_matches_regimes("normal", "vol_breakout", ("normal -> vol_breakout",)) is True
    assert _spike_matches_regimes("normal", "compression_clustering", ("normal -> vol_breakout",)) is False
    # Bare departing-state match (any incoming, incl. None/tied).
    assert _spike_matches_regimes("normal", None, ("normal",)) is True
    assert _spike_matches_regimes("compression_clustering", "normal", ("normal",)) is False
    # A tied/None incoming only matches a bare entry, never a transition.
    assert _spike_matches_regimes("normal", None, ("normal -> vol_breakout",)) is False


def test_exit_fires_only_on_listed_transition():
    bus, out = _controller_with_regimes(("normal -> vol_breakout",))
    bus.publish(_spike("normal", "vol_breakout"))  # listed → exit
    assert len(out) == 1 and out[0].reason == "HAZARD_SPIKE"


def test_exit_suppressed_for_unlisted_transition():
    bus, out = _controller_with_regimes(("normal -> vol_breakout",))
    # Same symbol/score, but a departure to compression is not in the filter.
    bus.publish(_spike("normal", "compression_clustering"))
    assert out == []


def test_bare_departing_state_filter_matches_any_incoming():
    bus, out = _controller_with_regimes(("normal",))
    bus.publish(_spike("normal", "compression_clustering"))
    assert len(out) == 1


def test_empty_applies_to_regimes_preserves_all_departures():
    bus, out = _controller_with_regimes(())
    bus.publish(_spike("compression_clustering", "vol_breakout"))
    assert len(out) == 1
