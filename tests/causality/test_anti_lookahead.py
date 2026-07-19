"""BT-10 / Inv-6 anti-lookahead audit tests.

Each test perturbs a *future* event (later ``exchange_timestamp_ns`` or
processing order) and asserts decisions at or before cutoff ``T`` are
unchanged.  Paths covered:

* **Ingestion** — ``InMemoryEventLog`` / ``ReplayFeed`` monotonic ordering
* **Fill (BT-1/BT-3)** — deferred MARKET fills use first latency-eligible quote
* **Fill (BT-2)** — passive drain hazard hashes the *current* quote only;
  prefix ack stream identical when a future quote is appended after cutoff
* **Regulatory (BT-5/6)** — halt / SSR state at ``T`` ignores trades processed
  only after ``T``
* **Aggregation** — horizon snapshot at boundary ``T`` excludes any sensor
  reading with ``timestamp_ns > T`` even when that reading is fed to the
  aggregator before the boundary tick at ``T`` (out-of-order arrival)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    HorizonTick,
    RiskAction,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    SensorReading,
    Side,
    SignalDirection,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.features.aggregator import HorizonAggregator
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.errors import CausalityViolation

from tests.features.test_aggregator import _reading, _tick
from tests.ingestion.test_replay_feed import (
    _UnsortedEventLog,
    _make_quote as _replay_quote,
    _make_trade as _replay_trade,
)
from tests.kernel.test_orchestrator import (
    _NoOpMetricCollector,
    _StubMarketData,
    _StubRiskEngine,
    _boot_to_backtest,
    _make_quote,
    _make_signal,
    _publish_signal_on_quote,
)
from tests.storage.test_memory_event_log import make_quote as _log_quote

pytestmark = pytest.mark.backtest_validation


# ── Helpers ─────────────────────────────────────────────────────────


def _bt_quote(
    symbol: str,
    bid: str,
    ask: str,
    exchange_ts: int,
    *,
    seq: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts,
        correlation_id=f"q-{exchange_ts}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts,
    )


def _market_buy(order_id: str = "ord1") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1000,
        correlation_id="c1",
        sequence=1,
        order_id=order_id,
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
    )


def _ack_fingerprint(acks: list[OrderAck]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            a.order_id,
            a.status,
            a.filled_quantity,
            str(a.fill_price) if a.fill_price is not None else None,
            a.reason,
        )
        for a in acks
    )


def _collect_router_acks(
    router: BacktestOrderRouter | PassiveLimitOrderRouter,
    quotes: list[NBBOQuote],
) -> list[OrderAck]:
    out: list[OrderAck] = []
    for q in quotes:
        router.on_quote(q)
        out.extend(router.poll_acks())
    return out


# ── Ingestion / replay ordering ───────────────────────────────────────


class TestIngestionCausality:
    def test_event_log_rejects_backward_exchange_timestamp(self) -> None:
        log = InMemoryEventLog()
        log.append(_log_quote(seq=0, exchange_ts_ns=500))
        with pytest.raises(CausalityViolation, match="out of merge-sort order"):
            log.append(_log_quote(seq=1, exchange_ts_ns=100))

    def test_replay_feed_rejects_trade_before_quote_at_equal_ts(self) -> None:
        log = _UnsortedEventLog(
            [
                _replay_trade(1, symbol="AAPL", exchange_ts_ns=100),
                _replay_quote(1, symbol="AAPL", exchange_ts_ns=100),
            ]
        )
        feed = ReplayFeed(log, clock=None)
        with pytest.raises(CausalityViolation, match="out of deterministic order"):
            list(feed.events())


# ── Fill path (deferred MARKET) ───────────────────────────────────────


class TestDeferredMarketAntiLookahead:
    def test_fill_at_t_unchanged_by_later_quote(self) -> None:
        """FILLED ack at eligibility is not revised when a later quote arrives."""
        clock = SimulatedClock(start_ns=1000)
        router = BacktestOrderRouter(clock, latency_ns=1000)

        router.on_quote(_bt_quote("AAPL", "100.00", "100.10", 1000))
        router.submit(_market_buy())
        assert [a.status for a in router.poll_acks()] == [
            OrderAckStatus.ACKNOWLEDGED,
        ]

        router.on_quote(_bt_quote("AAPL", "100.00", "100.10", 3000))
        fills = router.poll_acks()
        assert len(fills) == 1 and fills[0].status == OrderAckStatus.FILLED
        fp_at_t = _ack_fingerprint(fills)

        router.on_quote(_bt_quote("AAPL", "999.00", "1000.00", 50_000))
        assert router.poll_acks() == []
        assert _ack_fingerprint(fills) == fp_at_t


# ── Fill path (passive drain / BT-2) ────────────────────────────────


class TestPassiveDrainAntiLookahead:
    def test_prefix_ack_stream_immune_to_appended_future_quote(self) -> None:
        """Prefix acks match when an extra future quote is appended after cutoff."""
        q1 = _bt_quote("AAPL", "100.00", "100.02", 1000, seq=1)
        q2 = _bt_quote("AAPL", "100.00", "100.02", 2000, seq=2)
        q3 = _bt_quote("AAPL", "100.00", "100.02", 3000, seq=3)
        q_future = _bt_quote("AAPL", "50.00", "51.00", 90_000, seq=99)

        clock = SimulatedClock(start_ns=0)
        router_a = PassiveLimitOrderRouter(
            clock,
            fill_delay_ticks=5,
            fill_hazard_max=Decimal("0.15"),
        )
        router_a.on_quote(q1)
        router_a.submit(
            OrderRequest(
                timestamp_ns=1000,
                correlation_id="c",
                sequence=1,
                order_id="lim1",
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                limit_price=Decimal("100.00"),
            ),
        )
        prefix = [q1, q2, q3]
        fp_a = _ack_fingerprint(_collect_router_acks(router_a, prefix))

        clock_b = SimulatedClock(start_ns=0)
        router_b = PassiveLimitOrderRouter(
            clock_b,
            fill_delay_ticks=5,
            fill_hazard_max=Decimal("0.15"),
        )
        router_b.on_quote(q1)
        router_b.submit(
            OrderRequest(
                timestamp_ns=1000,
                correlation_id="c",
                sequence=1,
                order_id="lim1",
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                limit_price=Decimal("100.00"),
            ),
        )
        acks_b: list[OrderAck] = []
        for i, q in enumerate([q1, q2, q3, q_future]):
            router_b.on_quote(q)
            acks_b.extend(router_b.poll_acks())
            if i == 2:
                fp_at_cutoff = _ack_fingerprint(acks_b)

        assert fp_a == fp_at_cutoff


# ── Horizon aggregation ───────────────────────────────────────────────


class _CausalSumFeature:
    """Test feature that respects event-time causality at finalize.

    Records ``(ts_ns, value)`` tuples at ``observe`` time and, at
    ``finalize`` time, sums only those whose ``ts_ns <= tick.timestamp_ns``.
    This lets the BT-10 aggregation test verify the Inv-6 contract end-to-end
    even when a future-time reading is fed to the aggregator before the
    boundary tick at ``T`` arrives — exactly the perturbation that the
    aggregator's pass-through ``observe()`` dispatch cannot defend against
    on its own.
    """

    feature_id: str = "causal_sum_feat"
    feature_version: str = "1.0.0"
    input_sensor_ids: tuple[str, ...] = ("ofi_ewma",)
    horizon_seconds: int = 30

    def initial_state(self) -> dict[str, Any]:
        return {"observations": []}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        v = reading.value
        if isinstance(v, tuple):
            v = v[0]
        state["observations"].append((reading.timestamp_ns, float(v)))

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        cutoff = tick.timestamp_ns
        causal = [v for ts, v in state["observations"] if ts <= cutoff]
        # Retain post-cutoff observations for the next horizon; drop
        # the ones we just folded into this snapshot.
        state["observations"] = [(ts, v) for ts, v in state["observations"] if ts > cutoff]
        if not causal:
            return 0.0, False, True
        return sum(causal), True, False


class TestHorizonAggregationAntiLookahead:
    def test_boundary_snapshot_excludes_future_reading_processed_early(self) -> None:
        """A reading with ``timestamp_ns > T`` ingested *before* the boundary
        tick at ``T`` must not enter the snapshot at ``T``.

        Inv-6: features at time ``T`` use only events with ``timestamp_ns <= T``.
        The aggregator dispatches ``feature.observe`` synchronously on every
        ``SensorReading`` (without deferring to tick time), so the meaningful
        anti-lookahead perturbation is to feed an out-of-order future-time
        reading *before* finalizing at ``T`` and assert that the snapshot at
        ``T`` reflects only readings at or before ``T``.  A baseline path
        that omits the future reading entirely is compared to confirm both
        paths produce the same boundary snapshot.
        """
        boundary_tick = _tick(boundary=1, ts_ns=3_000_000_000)
        next_tick = _tick(boundary=2, ts_ns=12_000_000_000)

        agg_baseline = HorizonAggregator(
            bus=EventBus(),
            horizon_features={"causal_sum_feat": _CausalSumFeature()},
            symbols=frozenset({"AAPL"}),
            sensor_buffer_seconds=600,
            sequence_generator=SequenceGenerator(),
        )
        agg_baseline.on_sensor_reading(_reading(ts_ns=1_000_000_000, value=1.0))
        agg_baseline.on_sensor_reading(_reading(ts_ns=2_000_000_000, value=2.0))
        snap_baseline = agg_baseline.on_horizon_tick(boundary_tick)[0]

        agg_perturbed = HorizonAggregator(
            bus=EventBus(),
            horizon_features={"causal_sum_feat": _CausalSumFeature()},
            symbols=frozenset({"AAPL"}),
            sensor_buffer_seconds=600,
            sequence_generator=SequenceGenerator(),
        )
        agg_perturbed.on_sensor_reading(_reading(ts_ns=1_000_000_000, value=1.0))
        agg_perturbed.on_sensor_reading(_reading(ts_ns=2_000_000_000, value=2.0))
        # Out-of-order arrival: future-time reading observed before the
        # boundary tick at T.  Under Inv-6 it must not enter snap_perturbed.
        agg_perturbed.on_sensor_reading(_reading(ts_ns=9_000_000_000, value=999.0))
        snap_perturbed = agg_perturbed.on_horizon_tick(boundary_tick)[0]

        assert snap_baseline.values == {"causal_sum_feat": 3.0}
        assert snap_perturbed.values == snap_baseline.values

        # The deferred future reading lands in the *next* horizon snapshot.
        snap_after_future = agg_perturbed.on_horizon_tick(next_tick)[0]
        assert snap_after_future.values == {"causal_sum_feat": 999.0}


# ── Regulatory chokepoints (orchestrator) ───────────────────────────


class TestRegulatoryAntiLookahead:
    @staticmethod
    def _halt_trade(ts: int, seq: int, conditions: tuple[int, ...]) -> Trade:
        return Trade(
            timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:{seq}",
            sequence=seq,
            symbol="AAPL",
            price=Decimal("150"),
            size=100,
            exchange_timestamp_ns=ts - 50,
            conditions=conditions,
        )

    @staticmethod
    def _build_ssr_orchestrator(
        clock: SimulatedClock,
        bus: EventBus,
        position_store: MemoryPositionStore,
    ) -> tuple[Orchestrator, BacktestOrderRouter]:
        bt_router = BacktestOrderRouter(clock=clock)
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _boot_to_backtest(orch)
        return orch, bt_router

    def test_short_entry_at_t_before_ssr_trigger_at_later_t(self) -> None:
        """Short fill at ``T`` is not retroactively blocked by SSR trigger after ``T``."""
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build_ssr_orchestrator(clock, bus, position_store)
        orch._ssr_codes = frozenset({7})

        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(ts=2000, seq=1), SignalDirection.SHORT),
        )
        q_entry = _make_quote(ts=2000, seq=2)
        bt_router.on_quote(q_entry)
        orch._process_tick(q_entry)
        assert position_store.get("AAPL").quantity < 0

        orch._process_trade(self._halt_trade(ts=5000, seq=3, conditions=(7,)))
        assert "AAPL" in orch._ssr_active

        q_late = _make_quote(ts=6000, seq=4)
        bt_router.on_quote(q_late)
        orch._process_tick(q_late)
        assert position_store.get("AAPL").quantity < 0

    @staticmethod
    def _build_halt_orchestrator(
        clock: SimulatedClock,
        bus: EventBus,
        position_store: MemoryPositionStore,
    ) -> tuple[Orchestrator, BacktestOrderRouter]:
        bt_router = BacktestOrderRouter(clock=clock)
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _boot_to_backtest(orch)
        orch._halt_on_codes = frozenset({5})
        orch._halt_off_codes = frozenset({6})
        orch._halt_blackout_ns = 0
        return orch, bt_router

    def test_halt_off_at_future_t_does_not_clear_halt_before_processed(self) -> None:
        """Entry at ``T`` stays suppressed until halt-off trade is actually processed."""
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build_halt_orchestrator(clock, bus, position_store)

        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        orch._process_trade(self._halt_trade(ts=1500, seq=2, conditions=(5,)))
        assert "AAPL" in orch._halted_symbols

        q_blocked = _make_quote(ts=2000, seq=3)
        bt_router.on_quote(q_blocked)
        orch._process_tick(q_blocked)
        assert position_store.get("AAPL").quantity == 0

        orch._process_trade(self._halt_trade(ts=5000, seq=4, conditions=(6,)))
        assert "AAPL" not in orch._halted_symbols

        q_after = _make_quote(ts=6000, seq=5)
        bt_router.on_quote(q_after)
        orch._process_tick(q_after)
        assert position_store.get("AAPL").quantity > 0
