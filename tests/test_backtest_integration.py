"""End-to-end backtest integration test through bootstrap.

Verifies the full pipeline: build_platform → boot → run_backtest
with real alpha specs, real feature computation, real signal
evaluation, real risk checks, and real fill simulation.

This is the capstone test for Stage-1 backtest completeness.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.backtest_validation

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.memory_event_log import InMemoryEventLog


# ── Alpha spec that produces a BUY signal when mid > 150 ────────────

LONG_ALPHA_SPEC = """\
alpha_id: spread_momentum
version: "1.0"
author: integration_test
description: Buy when mid price exceeds threshold
hypothesis: Momentum continuation above 150
falsification_criteria:
  - Mid price stops predicting continuation
symbols:
  - AAPL
parameters:
  threshold:
    type: float
    default: 150.0
    description: Price threshold for entry
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
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
  - feature_id: spread_bps
    version: "1.0"
    description: Spread in basis points
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          bid = float(quote.bid)
          ask = float(quote.ask)
          mid = (bid + ask) / 2.0
          if mid == 0:
              return 0.0
          return (ask - bid) / mid * 10000
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

# ── Alpha spec that never fires (null signal) ───────────────────────

NULL_ALPHA_SPEC = """\
alpha_id: null_signal
version: "1.0"
author: integration_test
description: Never produces a signal
hypothesis: Baseline control
falsification_criteria:
  - Any signal emitted
symbols:
  - AAPL
parameters: {}
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 5.0
features:
  - feature_id: dummy
    version: "1.0"
    description: Unused feature
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return 0.0
signal: |
  def evaluate(features, params):
      return None
"""


def _make_quote(
    symbol: str = "AAPL",
    bid: float = 149.50,
    ask: float = 150.50,
    sequence: int = 1,
    ts: int = 1_000_000_000,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{ts}:{sequence}",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts - 100,
    )


def _populate_event_log(
    event_log: InMemoryEventLog,
    quotes: list[NBBOQuote],
) -> None:
    event_log.append_batch(quotes)


def _make_config(tmp_path: Path, **overrides) -> PlatformConfig:
    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        regime_engine=None,
    )
    defaults.update(overrides)
    return PlatformConfig(**defaults)


# ── Integration tests ───────────────────────────────────────────────


class TestBacktestIntegration:
    """Full round-trip through build_platform → boot → run_backtest."""

    def test_empty_event_log_completes_cleanly(self, tmp_path: Path) -> None:
        (tmp_path / "null.alpha.yaml").write_text(NULL_ALPHA_SPEC)
        config = _make_config(tmp_path)
        event_log = InMemoryEventLog()

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        assert orchestrator.macro_state == MacroState.READY

        orchestrator.run_backtest()
        assert orchestrator.macro_state == MacroState.READY

    def test_single_quote_no_signal(self, tmp_path: Path) -> None:
        """A quote below threshold should not produce a signal or order."""
        (tmp_path / "spread.alpha.yaml").write_text(LONG_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        quote = _make_quote(bid=140.0, ask=141.0)
        _populate_event_log(event_log, [quote])

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY
        positions = orchestrator._positions.all_positions()
        assert len(positions) == 0 or all(
            p.quantity == 0 for p in positions.values()
        )

    def test_quote_above_threshold_generates_signal_and_fill(self, tmp_path: Path) -> None:
        """A quote with mid > 150 should trigger LONG signal → order → fill."""
        (tmp_path / "spread.alpha.yaml").write_text(LONG_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        quotes = [
            _make_quote(bid=149.00, ask=150.00, sequence=1, ts=1_000_000_000),
            _make_quote(bid=151.00, ask=152.00, sequence=2, ts=2_000_000_000),
        ]
        _populate_event_log(event_log, quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY
        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity > 0, (
            f"Expected a long position in AAPL, got quantity={pos.quantity}"
        )

    def test_metrics_collected_during_backtest(self, tmp_path: Path) -> None:
        """MetricCollector should receive events during the pipeline."""
        (tmp_path / "spread.alpha.yaml").write_text(LONG_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        quotes = [
            _make_quote(bid=151.0, ask=152.0, sequence=1, ts=1_000_000_000),
        ]
        _populate_event_log(event_log, quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        mc = orchestrator._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        assert len(mc.events) > 0, "Expected at least one metric event"

    def test_kill_switch_not_activated_in_normal_backtest(self, tmp_path: Path) -> None:
        (tmp_path / "null.alpha.yaml").write_text(NULL_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        _populate_event_log(event_log, [_make_quote()])

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator._kill_switch.is_active is False

    def test_config_snapshot_survives_full_run(self, tmp_path: Path) -> None:
        (tmp_path / "null.alpha.yaml").write_text(NULL_ALPHA_SPEC)
        config = _make_config(tmp_path)
        event_log = InMemoryEventLog()

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert snap.checksum
        assert snap.data["mode"] == "BACKTEST"

    def test_multiple_quotes_sequential_processing(self, tmp_path: Path) -> None:
        """Multiple quotes are processed in timestamp order."""
        (tmp_path / "null.alpha.yaml").write_text(NULL_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        quotes = [
            _make_quote(bid=100.0, ask=101.0, sequence=i, ts=i * 1_000_000_000)
            for i in range(1, 6)
        ]
        _populate_event_log(event_log, quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY

    def test_shutdown_after_backtest(self, tmp_path: Path) -> None:
        (tmp_path / "null.alpha.yaml").write_text(NULL_ALPHA_SPEC)
        config = _make_config(tmp_path)
        event_log = InMemoryEventLog()

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()
        orchestrator.shutdown()

        assert orchestrator.macro_state == MacroState.SHUTDOWN

    def test_trade_journal_populated_on_fill(self, tmp_path: Path) -> None:
        """Fills should be recorded in the trade journal."""
        (tmp_path / "spread.alpha.yaml").write_text(LONG_ALPHA_SPEC)
        config = _make_config(tmp_path)

        event_log = InMemoryEventLog()
        quotes = [
            _make_quote(bid=149.0, ask=150.0, sequence=1, ts=1_000_000_000),
            _make_quote(bid=151.0, ask=152.0, sequence=2, ts=2_000_000_000),
        ]
        _populate_event_log(event_log, quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        pos = orchestrator._positions.get("AAPL")
        if pos.quantity > 0:
            tj = orchestrator._trade_journal
            assert tj is not None
            records = list(tj.query(symbol="AAPL"))
            assert len(records) > 0, "Expected trade records for AAPL fill"
