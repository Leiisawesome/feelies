"""End-to-end backtest verification — full layer-by-layer assertion suite.

Exercises the complete backtest pipe using a synthetic inline alpha
(pipeline_test_smr) with a synthetic 8-tick dataset designed to exercise
warm-up suppression, signal generation, risk gating, fills, position
reversal, and deterministic replay.

Observation mechanism: a BusRecorder subscribes to all events via
``bus.subscribe_all()``, capturing the full causal tape.  Every assertion
is made against this tape or end-state snapshots — no production code is
modified.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import pytest

pytestmark = pytest.mark.backtest_validation

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
    Side,
    StateTransition,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

PIPELINE_TEST_ALPHA_ID = "pipeline_test_smr"

PIPELINE_TEST_ALPHA_SPEC = """\
schema_version: "1.1"
layer: LEGACY_SIGNAL
alpha_id: pipeline_test_smr
version: "1.0.0"
description: "Minimal EWMA z-score alpha for pipeline integration testing"
hypothesis: "Mid-price deviation from EWMA generates mean reversion signals"
falsification_criteria:
  - "Test fixture only"
symbols:
  - AAPL
  - MSFT
parameters:
  ewma_span:
    type: float
    default: 5.0
  zscore_entry:
    type: float
    default: 1.0
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 10.0
  max_drawdown_pct: 2.0
  capital_allocation_pct: 20.0
features:
  - feature_id: mid_price
    version: "1.0"
    description: Mid price from NBBO
    depends_on: []
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
  - feature_id: ewma_mid
    version: "1.0"
    description: EWMA of mid price
    depends_on: [mid_price]
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {"ema": None}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          span = params.get("ewma_span", 5.0)
          a = 2.0 / (span + 1.0)
          if state["ema"] is None:
              state["ema"] = mid
          else:
              state["ema"] = a * mid + (1 - a) * state["ema"]
          return state["ema"]
  - feature_id: spread
    version: "1.0"
    description: Bid-ask spread
    depends_on: []
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float(quote.ask - quote.bid)
  - feature_id: mid_zscore
    version: "1.0"
    description: Z-score of mid relative to EWMA
    depends_on: [mid_price, ewma_mid]
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {"ema": None, "var": 0.0}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          span = params.get("ewma_span", 5.0)
          a = 2.0 / (span + 1.0)
          if state["ema"] is None:
              state["ema"] = mid
              return 0.0
          dev = mid - state["ema"]
          state["ema"] = a * mid + (1 - a) * state["ema"]
          state["var"] = a * dev * dev + (1 - a) * state["var"]
          if state["var"] < 1e-20:
              return 0.0
          return (mid - state["ema"]) / (state["var"] ** 0.5)
signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      zscore = features.values.get("mid_zscore", 0.0)
      spread = features.values.get("spread", 0.0)
      threshold = params.get("zscore_entry", 1.0)
      if spread > 0.5:
          return None
      if abs(zscore) < threshold:
          return None
      direction = SHORT if zscore > 0 else LONG
      strength = min(abs(zscore) / 5.0, 1.0)
      return Signal(
          timestamp_ns=features.timestamp_ns,
          correlation_id=features.correlation_id,
          sequence=features.sequence,
          symbol=features.symbol,
          strategy_id=alpha_id,
          direction=direction,
          strength=strength,
          edge_estimate_bps=2.5,
      )
"""


def _write_test_alpha(alpha_dir: Path) -> None:
    """Write the pipeline test alpha spec to the given directory."""
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / f"{PIPELINE_TEST_ALPHA_ID}.alpha.yaml").write_text(
        PIPELINE_TEST_ALPHA_SPEC
    )

# ── Synthetic quote data (plan §Synthetic Dataset Design) ────────────

TICK_DATA: list[dict] = [
    {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
    {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
]


# ── BusRecorder (plan §BusRecorder) ──────────────────────────────────


@dataclass
class BusRecorder:
    events: list[Event] = field(default_factory=list)
    by_type: dict[type, list[Event]] = field(default_factory=lambda: defaultdict(list))

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


# ── Helpers ──────────────────────────────────────────────────────────


def _make_quotes() -> list[NBBOQuote]:
    quotes = []
    for i, td in enumerate(TICK_DATA, start=1):
        ts = td["ts"]
        quotes.append(NBBOQuote(
            timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:{i}",
            sequence=i,
            symbol="AAPL",
            bid=Decimal(td["bid"]),
            ask=Decimal(td["ask"]),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=ts,
        ))
    return quotes


def _run_scenario(
    tmp_path: Path,
    quotes: list[NBBOQuote] | None = None,
    parameter_overrides: dict | None = None,
) -> tuple:
    """Build platform, wire recorder, boot, run backtest, return results."""
    alpha_dir = tmp_path / "alphas"
    _write_test_alpha(alpha_dir)

    if parameter_overrides is None:
        parameter_overrides = {PIPELINE_TEST_ALPHA_ID: {"ewma_span": 5, "zscore_entry": 1.0}}

    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
        parameter_overrides=parameter_overrides,
    )

    event_log = InMemoryEventLog()
    if quotes is None:
        quotes = _make_quotes()
    if quotes:
        event_log.append_batch(quotes)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)

    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)

    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    return orchestrator, recorder, resolved_config


# ── Class-scoped fixture (plan §Test Structure) ─────────────────────


@pytest.fixture(scope="class")
def scenario(tmp_path_factory: pytest.TempPathFactory):
    """Run the 8-tick scenario once per class; share results across tests."""
    tmp = tmp_path_factory.mktemp("e2e_backtest")
    orchestrator, recorder, config = _run_scenario(tmp)
    return orchestrator, recorder, config


# ── Layer-by-layer assertions ────────────────────────────────────────


class TestLayerIngestion:
    """Layer 1 — Ingestion / Replay: 8 NBBOQuote events."""

    def test_quote_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(NBBOQuote)) == 8

    def test_all_symbols_aapl(self, scenario) -> None:
        _, recorder, _ = scenario
        for q in recorder.of_type(NBBOQuote):
            assert q.symbol == "AAPL"

    def test_timestamps_monotonic(self, scenario) -> None:
        _, recorder, _ = scenario
        quotes = recorder.of_type(NBBOQuote)
        for i in range(len(quotes) - 1):
            assert quotes[i].timestamp_ns < quotes[i + 1].timestamp_ns


class TestLayerFeatures:
    """Layer 2 — Feature Engine: 8 FeatureVector events with EWMA/zscore."""

    def test_feature_vector_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(FeatureVector)) == 8

    def test_warmup_gate(self, scenario) -> None:
        _, recorder, _ = scenario
        fvs = recorder.of_type(FeatureVector)
        for fv in fvs[:4]:
            assert fv.warm is False
        for fv in fvs[4:]:
            assert fv.warm is True

    def test_mid_price_values(self, scenario) -> None:
        _, recorder, _ = scenario
        fvs = recorder.of_type(FeatureVector)
        expected_mids = [150.005] * 5 + [160.005, 160.005, 140.005]
        for fv, expected in zip(fvs, expected_mids):
            assert fv.values["mid_price"] == pytest.approx(expected, abs=1e-6)

    def test_spread_values(self, scenario) -> None:
        _, recorder, _ = scenario
        for fv in recorder.of_type(FeatureVector):
            assert fv.values["spread"] == pytest.approx(0.01, abs=1e-6)

    def test_zscore_tick6_exceeds_threshold(self, scenario) -> None:
        _, recorder, _ = scenario
        fv = recorder.of_type(FeatureVector)[5]
        assert fv.values["mid_zscore"] == pytest.approx(1.15470, abs=1e-4)

    def test_zscore_tick7_below_threshold(self, scenario) -> None:
        _, recorder, _ = scenario
        fv = recorder.of_type(FeatureVector)[6]
        assert fv.values["mid_zscore"] == pytest.approx(0.73030, abs=1e-4)

    def test_zscore_tick8_exceeds_negative_threshold(self, scenario) -> None:
        _, recorder, _ = scenario
        fv = recorder.of_type(FeatureVector)[7]
        assert fv.values["mid_zscore"] == pytest.approx(-1.01036, abs=1e-4)


class TestLayerSignals:
    """Layer 3 — Signal Engine: exactly 2 Signal events (SHORT + LONG)."""

    def test_signal_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(Signal)) == 2

    def test_signal_0_short(self, scenario) -> None:
        _, recorder, _ = scenario
        sig = recorder.of_type(Signal)[0]
        assert sig.direction == SignalDirection.SHORT
        assert sig.strength == pytest.approx(0.23094, abs=1e-4)
        assert sig.correlation_id == "AAPL:6000000000:6"
        assert sig.strategy_id == PIPELINE_TEST_ALPHA_ID
        assert sig.edge_estimate_bps == 2.5

    def test_signal_1_long(self, scenario) -> None:
        _, recorder, _ = scenario
        sig = recorder.of_type(Signal)[1]
        assert sig.direction == SignalDirection.LONG
        assert sig.strength == pytest.approx(0.20207, abs=1e-4)
        assert sig.correlation_id == "AAPL:8000000000:8"
        assert sig.strategy_id == PIPELINE_TEST_ALPHA_ID
        assert sig.edge_estimate_bps == 2.5


class TestLayerRisk:
    """Layer 4 — Risk Engine: 5 RiskVerdict events, all ALLOW.

    REVERSE decomposition (H2/H3/H7) produces two check_order calls
    (exit + entry legs) instead of one combined call.
    """

    def test_verdict_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(RiskVerdict)) == 5

    def test_all_allow(self, scenario) -> None:
        _, recorder, _ = scenario
        for v in recorder.of_type(RiskVerdict):
            assert v.action == RiskAction.ALLOW

    def test_all_scaling_factor_one(self, scenario) -> None:
        _, recorder, _ = scenario
        for v in recorder.of_type(RiskVerdict):
            assert v.scaling_factor == 1.0

    def test_no_force_flatten_or_reject(self, scenario) -> None:
        _, recorder, _ = scenario
        for v in recorder.of_type(RiskVerdict):
            assert v.action not in (RiskAction.FORCE_FLATTEN, RiskAction.REJECT)


class TestLayerExecution:
    """Layer 5 — Execution: 3 OrderRequest + 3 OrderAck (FILLED at mid).

    REVERSE decomposition (H2/H3/H7) splits the reversal into an
    EXIT leg (BUY 28 MARKET) + ENTRY leg (BUY 28 MARKET), producing
    3 orders instead of 2.
    """

    def test_order_request_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(OrderRequest)) == 3

    def test_order_0_sell_28(self, scenario) -> None:
        _, recorder, _ = scenario
        order = recorder.of_type(OrderRequest)[0]
        assert order.side == Side.SELL
        assert order.quantity == 28

    def test_order_1_exit_buy_28(self, scenario) -> None:
        """EXIT leg of REVERSE: close the -28 short position."""
        _, recorder, _ = scenario
        order = recorder.of_type(OrderRequest)[1]
        assert order.side == Side.BUY
        assert order.quantity == 28

    def test_order_2_entry_buy_28(self, scenario) -> None:
        """ENTRY leg of REVERSE: open +28 long position."""
        _, recorder, _ = scenario
        order = recorder.of_type(OrderRequest)[2]
        assert order.side == Side.BUY
        assert order.quantity == 28

    def test_ack_count(self, scenario) -> None:
        _, recorder, _ = scenario
        fills = [a for a in recorder.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 3

    def test_ack_0_filled_at_mid(self, scenario) -> None:
        _, recorder, _ = scenario
        fills = [a for a in recorder.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
        ack = fills[0]
        assert ack.filled_quantity == 28
        assert ack.fill_price == Decimal("160.005")

    def test_ack_1_exit_filled_at_mid(self, scenario) -> None:
        _, recorder, _ = scenario
        fills = [a for a in recorder.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
        ack = fills[1]
        assert ack.filled_quantity == 28
        assert ack.fill_price == Decimal("140.005")

    def test_ack_2_entry_filled_at_mid(self, scenario) -> None:
        _, recorder, _ = scenario
        fills = [a for a in recorder.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
        ack = fills[2]
        assert ack.filled_quantity == 28
        assert ack.fill_price == Decimal("140.005")


class TestLayerPortfolio:
    """Layer 6 — Portfolio: 3 PositionUpdate events.

    REVERSE decomposition produces separate updates for the exit
    (close to flat) and entry (open new direction) legs.
    """

    def test_position_update_count(self, scenario) -> None:
        _, recorder, _ = scenario
        assert len(recorder.of_type(PositionUpdate)) == 3

    def test_pu_0_short_28(self, scenario) -> None:
        _, recorder, _ = scenario
        pu = recorder.of_type(PositionUpdate)[0]
        assert pu.quantity == -28
        assert pu.realized_pnl == Decimal("0")

    def test_pu_1_flat_with_pnl(self, scenario) -> None:
        """EXIT leg closes -28 short → flat, realizing PnL."""
        _, recorder, _ = scenario
        pu = recorder.of_type(PositionUpdate)[1]
        assert pu.quantity == 0
        assert pu.realized_pnl == Decimal("560.000")

    def test_pu_2_long_28(self, scenario) -> None:
        """ENTRY leg opens +28 long from flat."""
        _, recorder, _ = scenario
        pu = recorder.of_type(PositionUpdate)[2]
        assert pu.quantity == 28
        assert pu.realized_pnl == Decimal("560.000")

    def test_end_state_position_store(self, scenario) -> None:
        orchestrator, _, _ = scenario
        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity == 28
        assert pos.avg_entry_price == Decimal("140.005")
        assert pos.realized_pnl == Decimal("560.000")


class TestLayerTradeJournal:
    """Layer 7 — Trade Journal: 3 TradeRecord entries.

    REVERSE decomposition produces separate records for exit and
    entry legs.
    """

    def test_record_count(self, scenario) -> None:
        orchestrator, _, _ = scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        assert len(records) == 3

    def test_record_0_sell_28(self, scenario) -> None:
        orchestrator, _, _ = scenario
        rec = list(orchestrator._trade_journal.query(symbol="AAPL"))[0]
        assert rec.side == Side.SELL
        assert rec.filled_quantity == 28
        assert rec.fill_price == Decimal("160.005")
        assert rec.strategy_id == PIPELINE_TEST_ALPHA_ID

    def test_record_1_exit_buy_28_with_pnl(self, scenario) -> None:
        """EXIT leg: close short, realizes PnL."""
        orchestrator, _, _ = scenario
        rec = list(orchestrator._trade_journal.query(symbol="AAPL"))[1]
        assert rec.side == Side.BUY
        assert rec.filled_quantity == 28
        assert rec.fill_price == Decimal("140.005")
        assert rec.realized_pnl == Decimal("560.000")
        assert rec.strategy_id == PIPELINE_TEST_ALPHA_ID

    def test_record_2_entry_buy_28(self, scenario) -> None:
        """ENTRY leg: open long, no PnL."""
        orchestrator, _, _ = scenario
        rec = list(orchestrator._trade_journal.query(symbol="AAPL"))[2]
        assert rec.side == Side.BUY
        assert rec.filled_quantity == 28
        assert rec.fill_price == Decimal("140.005")
        assert rec.realized_pnl == Decimal("0.000")
        assert rec.strategy_id == PIPELINE_TEST_ALPHA_ID


class TestLayerProvenance:
    """Layer 8 — Provenance (Invariant 13): unbroken correlation_id chain."""

    def test_signal_traces_to_quote(self, scenario) -> None:
        _, recorder, _ = scenario
        quote_cids = {q.correlation_id for q in recorder.of_type(NBBOQuote)}
        for sig in recorder.of_type(Signal):
            assert sig.correlation_id in quote_cids

    def test_order_traces_to_signal(self, scenario) -> None:
        _, recorder, _ = scenario
        signal_cids = {s.correlation_id for s in recorder.of_type(Signal)}
        for order in recorder.of_type(OrderRequest):
            assert order.correlation_id in signal_cids

    def test_ack_traces_to_order(self, scenario) -> None:
        _, recorder, _ = scenario
        order_ids = {o.order_id for o in recorder.of_type(OrderRequest)}
        for ack in recorder.of_type(OrderAck):
            assert ack.order_id in order_ids

    def test_position_update_traces_to_order(self, scenario) -> None:
        _, recorder, _ = scenario
        order_cids = {o.correlation_id for o in recorder.of_type(OrderRequest)}
        for pu in recorder.of_type(PositionUpdate):
            assert pu.correlation_id in order_cids

    def test_tick6_full_chain(self, scenario) -> None:
        _, recorder, _ = scenario
        cid = "AAPL:6000000000:6"
        assert any(q.correlation_id == cid for q in recorder.of_type(NBBOQuote))
        assert any(fv.correlation_id == cid for fv in recorder.of_type(FeatureVector))
        assert any(s.correlation_id == cid for s in recorder.of_type(Signal))
        assert any(v.correlation_id == cid for v in recorder.of_type(RiskVerdict))
        assert any(o.correlation_id == cid for o in recorder.of_type(OrderRequest))
        assert any(pu.correlation_id == cid for pu in recorder.of_type(PositionUpdate))

    def test_tick8_full_chain(self, scenario) -> None:
        _, recorder, _ = scenario
        cid = "AAPL:8000000000:8"
        assert any(q.correlation_id == cid for q in recorder.of_type(NBBOQuote))
        assert any(fv.correlation_id == cid for fv in recorder.of_type(FeatureVector))
        assert any(s.correlation_id == cid for s in recorder.of_type(Signal))
        assert any(v.correlation_id == cid for v in recorder.of_type(RiskVerdict))
        assert any(o.correlation_id == cid for o in recorder.of_type(OrderRequest))
        assert any(pu.correlation_id == cid for pu in recorder.of_type(PositionUpdate))


class TestLayerMetrics:
    """Layer 9 — Metrics: timing histograms with exact counts."""

    def test_metric_collector_has_events(self, scenario) -> None:
        orchestrator, _, _ = scenario
        mc = orchestrator._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        assert len(mc.events) >= 8

    def test_tick_to_decision_count(self, scenario) -> None:
        orchestrator, _, _ = scenario
        mc = orchestrator._metrics
        summary = mc.get_summary("kernel", "tick_to_decision_latency_ns")
        assert summary is not None
        assert summary.count == 8

    def test_feature_compute_count(self, scenario) -> None:
        orchestrator, _, _ = scenario
        summary = orchestrator._metrics.get_summary("kernel", "feature_compute_ns")
        assert summary is not None
        assert summary.count == 8

    def test_signal_evaluate_count(self, scenario) -> None:
        orchestrator, _, _ = scenario
        summary = orchestrator._metrics.get_summary("kernel", "signal_evaluate_ns")
        assert summary is not None
        assert summary.count == 8

    def test_risk_check_count(self, scenario) -> None:
        orchestrator, _, _ = scenario
        summary = orchestrator._metrics.get_summary("kernel", "risk_check_ns")
        assert summary is not None
        assert summary.count == 2

    def test_all_latency_values_non_negative(self, scenario) -> None:
        orchestrator, _, _ = scenario
        mc = orchestrator._metrics
        for evt in mc.events:
            assert evt.value >= 0


class TestLayerStateMachines:
    """Layer 10 — State Machines: macro lifecycle and micro pipeline."""

    def test_macro_transitions_in_order(self, scenario) -> None:
        _, recorder, _ = scenario
        macro_transitions = [
            st for st in recorder.of_type(StateTransition)
            if st.machine_name == "global_stack"
        ]
        expected = [
            ("INIT", "DATA_SYNC", "CONFIG_VALIDATED"),
            ("DATA_SYNC", "READY", "DATA_INTEGRITY_OK"),
            ("READY", "BACKTEST_MODE", "CMD_BACKTEST"),
            ("BACKTEST_MODE", "READY", "BACKTEST_COMPLETE"),
        ]
        assert len(macro_transitions) == len(expected)
        for st, (from_s, to_s, trigger) in zip(macro_transitions, expected):
            assert st.from_state == from_s
            assert st.to_state == to_s
            assert st.trigger == trigger

    def test_macro_state_ready_after_run(self, scenario) -> None:
        orchestrator, _, _ = scenario
        assert orchestrator.macro_state == MacroState.READY

    def test_kill_switch_not_active(self, scenario) -> None:
        orchestrator, _, _ = scenario
        assert orchestrator._kill_switch.is_active is False

    def test_micro_signal_tick_includes_full_pipeline(self, scenario) -> None:
        """Signal-producing ticks traverse M5-M9 in the tick_pipeline."""
        _, recorder, _ = scenario
        micro_transitions = [
            st for st in recorder.of_type(StateTransition)
            if st.machine_name == "tick_pipeline"
        ]
        micro_states_reached = {st.to_state for st in micro_transitions}
        for expected_state in [
            "RISK_CHECK", "ORDER_DECISION", "ORDER_SUBMIT",
            "ORDER_ACK", "POSITION_UPDATE",
        ]:
            assert expected_state in micro_states_reached, (
                f"Expected micro state {expected_state} not reached"
            )


class TestLayerConfigSnapshot:
    """Layer 11 — Config Snapshot: mode, overrides, regime_engine."""

    def test_checksum_present(self, scenario) -> None:
        orchestrator, _, _ = scenario
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert len(snap.checksum) > 0

    def test_mode_backtest(self, scenario) -> None:
        orchestrator, _, _ = scenario
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert snap.data["mode"] == "BACKTEST"

    def test_parameter_overrides(self, scenario) -> None:
        orchestrator, _, _ = scenario
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert snap.data["parameter_overrides"] == {
            PIPELINE_TEST_ALPHA_ID: {"ewma_span": 5, "zscore_entry": 1.0},
        }

    def test_regime_engine_none(self, scenario) -> None:
        orchestrator, _, _ = scenario
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert snap.data["regime_engine"] is None


class TestLayerPnLPerformance:
    """Layer 12 — Final P&L and Performance Summary."""

    def test_realized_pnl(self, scenario) -> None:
        orchestrator, _, _ = scenario
        pos = orchestrator._positions.get("AAPL")
        assert pos.realized_pnl == Decimal("560.000")

    def test_final_equity(self, scenario) -> None:
        orchestrator, _, _ = scenario
        pos = orchestrator._positions.get("AAPL")
        final_equity = Decimal("100000") + pos.realized_pnl
        assert final_equity == Decimal("100560.000")

    def test_unrealized_pnl_zero(self, scenario) -> None:
        orchestrator, _, _ = scenario
        pos = orchestrator._positions.get("AAPL")
        assert pos.unrealized_pnl == Decimal("0")

    def test_total_fees_positive(self, scenario) -> None:
        orchestrator, _, _ = scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        total_fees = sum(r.fees for r in records)
        assert total_fees > Decimal("0"), "Cost model should produce positive fees"
        for r in records:
            assert r.fees >= Decimal("0"), "Individual fees must be non-negative"

    def test_total_shares_traded(self, scenario) -> None:
        orchestrator, _, _ = scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        assert sum(r.filled_quantity for r in records) == 84

    def test_total_exposure(self, scenario) -> None:
        orchestrator, _, _ = scenario
        assert orchestrator._positions.total_exposure() == Decimal("3920.140")

    def test_return_pct(self, scenario) -> None:
        orchestrator, _, _ = scenario
        pos = orchestrator._positions.get("AAPL")
        return_pct = float(pos.realized_pnl) / 100_000
        assert return_pct == pytest.approx(0.0056)

    def test_win_rate(self, scenario) -> None:
        orchestrator, _, _ = scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        winners = [r for r in records if r.realized_pnl > 0]
        closed = [r for r in records if r.realized_pnl != 0]
        assert len(winners) == 1
        assert len(closed) == 1

    def test_tick_to_decision_uses_wall_clock(self, scenario) -> None:
        orchestrator, _, _ = scenario
        mc = orchestrator._metrics
        summary = mc.get_summary("kernel", "tick_to_decision_latency_ns")
        assert summary is not None
        for evt in mc.events:
            if evt.name == "tick_to_decision_latency_ns":
                assert evt.value >= 0.0, "Wall-clock latency must be non-negative"


# ── Deterministic Replay Test ────────────────────────────────────────


class TestDeterministicReplay:
    """Run the 8-tick scenario 3× independently; all must be bit-identical."""

    def test_three_runs_identical(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        results = []
        for i in range(3):
            tmp = tmp_path_factory.mktemp(f"replay_{i}")
            orchestrator, recorder, _ = _run_scenario(tmp)
            results.append((orchestrator, recorder))

        for i in range(1, 3):
            orch_a, rec_a = results[0]
            orch_b, rec_b = results[i]

            sigs_a = rec_a.of_type(Signal)
            sigs_b = rec_b.of_type(Signal)
            assert len(sigs_a) == len(sigs_b) == 2

            assert sigs_a[0].direction == sigs_b[0].direction == SignalDirection.SHORT
            assert sigs_a[1].direction == sigs_b[1].direction == SignalDirection.LONG
            assert sigs_a[0].strength == sigs_b[0].strength
            assert sigs_a[1].strength == sigs_b[1].strength

            fills_a = [a for a in rec_a.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
            fills_b = [a for a in rec_b.of_type(OrderAck) if a.status == OrderAckStatus.FILLED]
            assert fills_a[0].fill_price == fills_b[0].fill_price == Decimal("160.005")
            # REVERSE decomposition: exit leg at 140.005, entry leg at 140.005
            assert fills_a[1].fill_price == fills_b[1].fill_price == Decimal("140.005")
            assert fills_a[2].fill_price == fills_b[2].fill_price == Decimal("140.005")

            pos_a = orch_a._positions.get("AAPL")
            pos_b = orch_b._positions.get("AAPL")
            assert pos_a.quantity == pos_b.quantity == 28
            assert pos_a.realized_pnl == pos_b.realized_pnl == Decimal("560.000")

            records_a = list(orch_a._trade_journal.query(symbol="AAPL"))
            records_b = list(orch_b._trade_journal.query(symbol="AAPL"))
            assert len(records_a) == len(records_b) == 3
            for ra, rb in zip(records_a, records_b):
                assert ra.filled_quantity == rb.filled_quantity

            assert len(rec_a.events) == len(rec_b.events)


# ── Boundary Condition Tests ─────────────────────────────────────────


class TestBoundarySpreadGate:
    """Spread gate suppression: $1.00 spread blocks all signals."""

    def test_no_signals_or_orders(self, tmp_path: Path) -> None:
        wide_quotes = []
        bids = [150, 150, 150, 150, 150, 160, 160, 140]
        for i, (bid, td) in enumerate(zip(bids, TICK_DATA), start=1):
            ts = td["ts"]
            wide_quotes.append(NBBOQuote(
                timestamp_ns=ts,
                correlation_id=f"AAPL:{ts}:{i}",
                sequence=i,
                symbol="AAPL",
                bid=Decimal(str(bid)),
                ask=Decimal(str(bid + 1)),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=ts,
            ))

        orchestrator, recorder, _ = _run_scenario(tmp_path, quotes=wide_quotes)
        assert len(recorder.of_type(Signal)) == 0
        assert len(recorder.of_type(OrderRequest)) == 0
        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity == 0


class TestBoundaryEmptyEventLog:
    """Empty event log: boot + run completes with no events."""

    def test_empty_log_completes(self, tmp_path: Path) -> None:
        orchestrator, recorder, _ = _run_scenario(tmp_path, quotes=[])
        assert orchestrator.macro_state == MacroState.READY
        assert len(recorder.of_type(Signal)) == 0
        assert len(recorder.of_type(OrderRequest)) == 0
        assert len(recorder.of_type(PositionUpdate)) == 0
        assert orchestrator._kill_switch.is_active is False


class TestBoundaryWarmupOnly:
    """All warm-up ticks only: 4 ticks, event_count < min_events=5."""

    def test_no_signals_during_warmup(self, tmp_path: Path) -> None:
        warmup_quotes = _make_quotes()[:4]
        orchestrator, recorder, _ = _run_scenario(tmp_path, quotes=warmup_quotes)

        fvs = recorder.of_type(FeatureVector)
        assert len(fvs) == 4
        assert all(fv.warm is False for fv in fvs)
        assert len(recorder.of_type(Signal)) == 0
        assert len(recorder.of_type(OrderRequest)) == 0
        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity == 0
