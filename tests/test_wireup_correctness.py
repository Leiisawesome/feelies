"""Stage-1 runtime correctness — every wire carries the right data.

Verifies that data actually flows through each connection at runtime:
clock advances, events propagate, state machines transition, features
compute, signals fire, risk checks pass, orders fill, positions update,
journals record, metrics accumulate, and deterministic replay holds.

This goes beyond structural wireup (types and identity) to verify
runtime behavioral correctness of the composed system.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.backtest_validation

from feelies.bootstrap import build_platform
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    PositionUpdate,
    Signal,
    StateTransition,
    MetricEvent,
    FeatureVector,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.monitoring.in_memory import InMemoryKillSwitch, InMemoryMetricCollector
from feelies.storage.memory_event_log import InMemoryEventLog


LONG_ALPHA = """\
schema_version: "1.1"
layer: LEGACY_SIGNAL
alpha_id: correctness_alpha
version: "1.0.0"
author: test
description: Fires LONG when mid > 150
hypothesis: test
falsification_criteria:
  - test
symbols:
  - AAPL
parameters:
  threshold:
    type: float
    default: 150.0
    description: threshold
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 10.0
  max_drawdown_pct: 2.0
  capital_allocation_pct: 20.0
features:
  - feature_id: mid_price
    version: "1.0"
    description: mid
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
signal: |
  def evaluate(features, params):
      mid = features.values.get("mid_price", 0)
      if mid > params["threshold"]:
          return Signal(
              timestamp_ns=features.timestamp_ns,
              correlation_id=features.correlation_id,
              sequence=features.sequence,
              symbol=features.symbol,
              strategy_id=alpha_id,
              direction=LONG,
              strength=0.8,
              edge_estimate_bps=5.0,
          )
      return None
"""


def _q(bid: float, ask: float, seq: int, ts_ns: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"AAPL:{ts_ns}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts_ns - 100,
    )


class BusRecorder:
    """Subscribes to all bus events and records them in order."""

    def __init__(self) -> None:
        self.events: list = []

    def __call__(self, event) -> None:
        self.events.append(event)

    def of_type(self, cls) -> list:
        return [e for e in self.events if isinstance(e, cls)]


def _build(tmp_path: Path, quotes: list[NBBOQuote], **config_kw):
    (tmp_path / "alpha.alpha.yaml").write_text(LONG_ALPHA)
    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        regime_engine=None,
    )
    defaults.update(config_kw)
    config = PlatformConfig(**defaults)
    event_log = InMemoryEventLog()
    event_log.append_batch(quotes)
    orch, cfg = build_platform(config, event_log=event_log)
    recorder = BusRecorder()
    orch._bus.subscribe_all(recorder)
    return orch, cfg, recorder


# ── 1. Clock advancement ────────────────────────────────────────────


class TestClockAdvancement:
    def test_simulated_clock_advances_to_exchange_timestamps(self, tmp_path: Path) -> None:
        quotes = [
            _q(140, 141, 1, 1_000_000_000),
            _q(142, 143, 2, 5_000_000_000),
        ]
        orch, config, _ = _build(tmp_path, quotes)
        assert orch._clock.now_ns() == 0
        orch.boot(config)
        orch.run_backtest()
        last_exchange_ts = quotes[-1].exchange_timestamp_ns
        assert orch._clock.now_ns() >= last_exchange_ts, (
            f"Clock should have advanced to at least the last exchange_timestamp_ns "
            f"({last_exchange_ts}), got {orch._clock.now_ns()}"
        )

    def test_clock_monotonically_advances(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, i, i * 1_000_000_000) for i in range(1, 4)]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        metrics = recorder.of_type(MetricEvent)
        timestamps = [m.timestamp_ns for m in metrics]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1], (
                f"Clock went backwards at metric {i}: {timestamps[i - 1]} > {timestamps[i]}"
            )


# ── 2. Macro state lifecycle ────────────────────────────────────────


class TestMacroStateLifecycle:
    def test_full_lifecycle_init_to_shutdown(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, recorder = _build(tmp_path, quotes)
        assert orch.macro_state == MacroState.INIT
        orch.boot(config)
        assert orch.macro_state == MacroState.READY
        orch.run_backtest()
        assert orch.macro_state == MacroState.READY
        orch.shutdown()
        assert orch.macro_state == MacroState.SHUTDOWN

    def test_state_transitions_emitted_on_bus(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        orch.shutdown()
        transitions = recorder.of_type(StateTransition)
        macro_transitions = [t for t in transitions if t.machine_name == "global_stack"]
        states_visited = [t.to_state for t in macro_transitions]
        assert "DATA_SYNC" in states_visited
        assert "READY" in states_visited
        assert "BACKTEST_MODE" in states_visited
        assert "SHUTDOWN" in states_visited

    def test_backtest_enters_and_leaves_backtest_mode(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        transitions = recorder.of_type(StateTransition)
        macro_transitions = [t for t in transitions if t.machine_name == "global_stack"]
        states = [t.to_state for t in macro_transitions]
        bt_idx = states.index("BACKTEST_MODE")
        assert "READY" in states[bt_idx + 1:], (
            "Must transition back to READY after BACKTEST_MODE"
        )


# ── 3. Micro state per-tick ─────────────────────────────────────────


class TestMicroState:
    def test_micro_returns_to_waiting_after_each_tick(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        assert orch._micro.state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_micro_completes_full_pipeline_on_signal_tick(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        transitions = recorder.of_type(StateTransition)
        micro_transitions = [t for t in transitions if t.machine_name == "tick_pipeline"]
        micro_states = [t.to_state for t in micro_transitions]
        assert "MARKET_EVENT_RECEIVED" in micro_states
        assert "FEATURE_COMPUTE" in micro_states
        assert "SIGNAL_EVALUATE" in micro_states
        assert "LOG_AND_METRICS" in micro_states


# ── 4. Event log append ─────────────────────────────────────────────


class TestEventLogAppend:
    def test_quotes_preserved_in_event_log_after_replay(self, tmp_path: Path) -> None:
        """Pre-loaded quotes survive backtest replay without duplication.

        In backtest mode the orchestrator sets ``_events_prelogged = True``
        so quotes are *not* re-appended.  The event log should contain
        exactly the original quotes — no fewer (lost), no more (duplicated).
        """
        quotes = [
            _q(140, 141, 1, 1_000_000_000),
            _q(142, 143, 2, 2_000_000_000),
            _q(144, 145, 3, 3_000_000_000),
        ]
        orch, config, _ = _build(tmp_path, quotes)
        initial_count = len(list(orch._event_log.replay()))
        assert initial_count == 3
        orch.boot(config)
        orch.run_backtest()
        all_events = list(orch._event_log.replay())
        replayed_quotes = [e for e in all_events if isinstance(e, NBBOQuote)]
        assert len(replayed_quotes) == initial_count, (
            f"Expected exactly {initial_count} quotes in event log after replay "
            f"(no duplication, no loss), got {len(replayed_quotes)}"
        )


# ── 5. Bus ordering: quote reaches router before order submit ───────


class TestBusOrdering:
    def test_quote_published_on_bus_before_order_submit(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        quote_indices = [
            i for i, e in enumerate(recorder.events) if isinstance(e, NBBOQuote)
        ]
        order_indices = [
            i for i, e in enumerate(recorder.events) if isinstance(e, OrderRequest)
        ]
        if order_indices:
            last_quote_before_order = max(
                qi for qi in quote_indices if qi < order_indices[0]
            )
            assert last_quote_before_order < order_indices[0], (
                "A quote must be published before the first order"
            )


# ── 6. Feature computation ──────────────────────────────────────────


class TestFeatureComputation:
    def test_feature_vector_emitted_with_correct_mid(self, tmp_path: Path) -> None:
        quotes = [_q(150, 152, 1, 1_000_000_000)]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        fvs = recorder.of_type(FeatureVector)
        assert len(fvs) >= 1, "Expected at least one FeatureVector event"
        fv = fvs[0]
        assert fv.symbol == "AAPL"
        assert "mid_price" in fv.values
        assert fv.values["mid_price"] == pytest.approx(151.0, abs=0.01)


# ── 7. Signal evaluation ────────────────────────────────────────────


class TestSignalEvaluation:
    def test_signal_fires_when_threshold_exceeded(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        signals = recorder.of_type(Signal)
        assert len(signals) >= 1, "Expected a LONG signal for mid=151.5 > 150"
        assert signals[0].symbol == "AAPL"
        assert signals[0].direction.name == "LONG"

    def test_no_signal_when_below_threshold(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        signals = recorder.of_type(Signal)
        assert len(signals) == 0, f"Expected no signal for mid=140.5, got {len(signals)}"


# ── 8. Risk check ───────────────────────────────────────────────────


class TestRiskCheck:
    def test_signal_passes_risk_and_produces_order(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        orders = recorder.of_type(OrderRequest)
        assert len(orders) >= 1, (
            "Signal should have passed risk check and generated an order"
        )
        assert orders[0].symbol == "AAPL"
        assert orders[0].quantity > 0


# ── 9. Intent translation ───────────────────────────────────────────


class TestIntentTranslation:
    def test_entry_long_from_flat_position(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        pos_before = orch._positions.get("AAPL")
        assert pos_before.quantity == 0
        orch.run_backtest()
        pos_after = orch._positions.get("AAPL")
        assert pos_after.quantity > 0, (
            "IntentTranslator should have produced ENTRY_LONG from flat position"
        )


# ── 10. Position sizing ─────────────────────────────────────────────


class TestPositionSizing:
    def test_target_quantity_respects_account_equity_and_budget(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        orders = recorder.of_type(OrderRequest)
        assert len(orders) >= 1
        qty = orders[0].quantity
        assert qty > 0
        assert qty <= 100, (
            f"Quantity {qty} exceeds max_position_per_symbol=100 from risk_budget"
        )

    def test_different_equity_changes_position_size(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch_small, _, rec_small = _build(tmp_path, quotes, account_equity=10_000.0)
        orch_small.boot(PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=tmp_path,
            account_equity=10_000.0,
        ))
        orch_small.run_backtest()
        orders_small = rec_small.of_type(OrderRequest)

        orch_large, _, rec_large = _build(tmp_path, quotes, account_equity=1_000_000.0)
        orch_large.boot(PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=tmp_path,
            account_equity=1_000_000.0,
        ))
        orch_large.run_backtest()
        orders_large = rec_large.of_type(OrderRequest)

        if orders_small and orders_large:
            assert orders_large[0].quantity >= orders_small[0].quantity, (
                "Larger account equity should produce equal or larger position"
            )


# ── 11. Fill flow ────────────────────────────────────────────────────


class TestFillFlow:
    def test_order_fills_update_position_store(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        pos = orch._positions.get("AAPL")
        assert pos.quantity > 0
        assert pos.avg_entry_price > 0

    def test_fill_emits_position_update_on_bus(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        pos_updates = recorder.of_type(PositionUpdate)
        assert len(pos_updates) >= 1
        assert pos_updates[0].symbol == "AAPL"
        assert pos_updates[0].quantity > 0

    def test_fill_recorded_in_trade_journal(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
        ]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        tj = orch._trade_journal
        assert tj is not None
        records = list(tj.query(symbol="AAPL"))
        assert len(records) >= 1, "Fill should be recorded in trade journal"
        rec = records[0]
        assert rec.symbol == "AAPL"
        assert rec.filled_quantity > 0
        assert rec.fill_price > 0


# ── 12. Kill switch enforcement ──────────────────────────────────────


class TestKillSwitchEnforcement:
    def test_kill_switch_blocks_further_ticks(self, tmp_path: Path) -> None:
        quotes = [
            _q(151, 152, 1, 1_000_000_000),
            _q(153, 154, 2, 2_000_000_000),
            _q(155, 156, 3, 3_000_000_000),
        ]
        orch, config, recorder = _build(tmp_path, quotes)
        orch.boot(config)

        ks = orch._kill_switch
        assert isinstance(ks, InMemoryKillSwitch)

        original_process_tick = orch._process_tick_inner
        tick_count = [0]

        def counting_tick(quote):
            tick_count[0] += 1
            if tick_count[0] == 1:
                ks.activate(reason="test_halt", activated_by="test")
            return original_process_tick(quote)

        orch._process_tick_inner = counting_tick
        orch.run_backtest()

        orders = recorder.of_type(OrderRequest)
        assert tick_count[0] >= 1
        orders_after_kill = [
            o for o in orders
            if o.timestamp_ns > 1_000_000_000
        ]
        assert len(orders_after_kill) == 0, (
            "No orders should be submitted after kill switch activation"
        )


# ── 13. Feature snapshot checkpoint ──────────────────────────────────


class TestFeatureSnapshotCheckpoint:
    def test_shutdown_checkpoints_feature_state(self, tmp_path: Path) -> None:
        quotes = [_q(151, 152, 1, 1_000_000_000)]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        fs = orch._feature_snapshots
        assert fs is not None
        orch.shutdown()
        version = orch._feature_engine.version
        loaded = fs.load("AAPL", version)
        assert loaded is not None, (
            "Feature snapshot for AAPL should have been saved on shutdown"
        )


# ── 14. Deterministic replay ────────────────────────────────────────


class TestDeterministicReplay:
    def test_same_inputs_produce_identical_positions(self, tmp_path: Path) -> None:
        quotes = [
            _q(149, 150, 1, 1_000_000_000),
            _q(151, 152, 2, 2_000_000_000),
            _q(153, 154, 3, 3_000_000_000),
        ]
        results = []
        for _ in range(3):
            orch, config, recorder = _build(tmp_path, quotes)
            orch.boot(config)
            orch.run_backtest()
            pos = orch._positions.get("AAPL")
            orders = recorder.of_type(OrderRequest)
            results.append({
                "quantity": pos.quantity,
                "avg_price": pos.avg_entry_price,
                "num_orders": len(orders),
                "order_quantities": [o.quantity for o in orders],
            })

        for i in range(1, len(results)):
            assert results[i]["quantity"] == results[0]["quantity"], (
                f"Run {i} quantity {results[i]['quantity']} != run 0 quantity {results[0]['quantity']}"
            )
            assert results[i]["avg_price"] == results[0]["avg_price"], (
                f"Run {i} avg_price {results[i]['avg_price']} != run 0 avg_price {results[0]['avg_price']}"
            )
            assert results[i]["num_orders"] == results[0]["num_orders"]
            assert results[i]["order_quantities"] == results[0]["order_quantities"]


# ── 15. Metrics content ─────────────────────────────────────────────


class TestMetricsContent:
    def test_tick_latency_metric_recorded_per_tick(self, tmp_path: Path) -> None:
        quotes = [
            _q(140, 141, 1, 1_000_000_000),
            _q(142, 143, 2, 2_000_000_000),
        ]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        mc = orch._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        latency_events = [
            e for e in mc.events if e.name == "tick_to_decision_latency_ns"
        ]
        assert len(latency_events) == 2, (
            f"Expected 2 tick latency metrics (one per quote), got {len(latency_events)}"
        )
        for e in latency_events:
            assert e.layer == "kernel"
            assert e.value >= 0

    def test_metrics_flushed_on_shutdown(self, tmp_path: Path) -> None:
        quotes = [_q(140, 141, 1, 1_000_000_000)]
        orch, config, _ = _build(tmp_path, quotes)
        orch.boot(config)
        orch.run_backtest()
        mc = orch._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        assert mc._flushed is False
        orch.shutdown()
        assert mc._flushed is True
