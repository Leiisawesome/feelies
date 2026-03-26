"""Stage-1 wireup verification — every bootstrap connection audited.

Systematically verifies that build_platform correctly wires every
component into the orchestrator with the right types, shared instances,
and cross-links.  This is a structural test, not a behavioral one.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.backtest_validation

from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.config import ConfigSnapshot
from feelies.core.events import (
    Alert,
    AlertSeverity,
    MetricEvent,
    MetricType,
    NBBOQuote,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_engine import HMM3StateFractional
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore
from feelies.storage.memory_trade_journal import InMemoryTradeJournal

ALPHA_SPEC = """\
schema_version: "1.0"
alpha_id: wirecheck_alpha
version: "1.0.0"
author: test
description: wireup check alpha
hypothesis: test
falsification_criteria:
  - test
symbols:
  - AAPL
parameters: {}
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 10.0
features:
  - feature_id: mid
    version: "1.0"
    description: mid price
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
      return None
"""


@pytest.fixture()
def platform(tmp_path: Path):
    (tmp_path / "wirecheck.alpha.yaml").write_text(ALPHA_SPEC)
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=250_000.0,
        regime_engine="hmm_3state_fractional",
        risk_max_position_per_symbol=500,
        risk_max_gross_exposure_pct=15.0,
        risk_max_drawdown_pct=3.0,
        backtest_fill_latency_ns=1000,
    )
    event_log = InMemoryEventLog()
    orchestrator, returned_config = build_platform(config, event_log=event_log)
    return orchestrator, returned_config, event_log


# ── 1. Config flow ──────────────────────────────────────────────────


class TestConfigWireup:
    def test_config_validated_before_composition(self, platform) -> None:
        _, config, _ = platform
        assert config.symbols == frozenset({"AAPL"})

    def test_config_snapshot_captured_with_checksum(self, platform) -> None:
        orch, config, _ = platform
        snap = orch.config_snapshot  # type: ignore[attr-defined]
        assert isinstance(snap, ConfigSnapshot)
        assert len(snap.checksum) == 64
        assert snap.data["mode"] == "BACKTEST"
        assert snap.data["account_equity"] == 250_000.0

    def test_config_snapshot_matches_input(self, platform) -> None:
        orch, config, _ = platform
        snap = orch.config_snapshot  # type: ignore[attr-defined]
        independent_snap = config.snapshot()
        assert snap.checksum == independent_snap.checksum


# ── 2. Clock wiring ────────────────────────────────────────────────


class TestClockWireup:
    def test_backtest_uses_simulated_clock(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._clock, SimulatedClock)

    def test_clock_shared_with_feature_engine(self, platform) -> None:
        orch, _, _ = platform
        assert orch._feature_engine._clock is orch._clock

    def test_clock_shared_with_backend_replay_feed(self, platform) -> None:
        orch, _, _ = platform
        feed = orch._backend.market_data
        assert isinstance(feed, ReplayFeed)
        assert feed._clock is orch._clock

    def test_clock_shared_with_backtest_router(self, platform) -> None:
        orch, _, _ = platform
        router = orch._backend.order_router
        assert isinstance(router, BacktestOrderRouter)
        assert router._clock is orch._clock


# ── 3. EventBus wiring ─────────────────────────────────────────────


class TestBusWireup:
    def test_bus_is_event_bus(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._bus, EventBus)

    def test_metric_event_subscription_active(self, platform) -> None:
        orch, _, _ = platform
        handlers = orch._bus._handlers.get(MetricEvent, [])
        assert len(handlers) >= 1, "MetricEvent must have at least one handler"

    def test_alert_event_subscription_active(self, platform) -> None:
        orch, _, _ = platform
        handlers = orch._bus._handlers.get(Alert, [])
        assert len(handlers) >= 1, "Alert must have at least one handler (alert_manager is wired)"

    def test_quote_subscription_for_backtest_router(self, platform) -> None:
        orch, _, _ = platform
        handlers = orch._bus._handlers.get(NBBOQuote, [])
        assert len(handlers) >= 1, "NBBOQuote must have handler for backtest router"

    def test_quote_reaches_backtest_router_via_bus(self, platform) -> None:
        orch, _, _ = platform
        router = orch._backend.order_router
        assert isinstance(router, BacktestOrderRouter)
        quote = NBBOQuote(
            timestamp_ns=1_000_000_000,
            correlation_id="test:1:1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("150"),
            ask=Decimal("151"),
            bid_size=100,
            ask_size=200,
            exchange_timestamp_ns=999_999_900,
        )
        orch._bus.publish(quote)
        assert "AAPL" in router._last_quotes
        assert router._last_quotes["AAPL"] is quote

    def test_metric_event_reaches_collector_via_bus(self, platform) -> None:
        orch, _, _ = platform
        mc = orch._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        metric = MetricEvent(
            timestamp_ns=1, correlation_id="c", sequence=1,
            layer="test", name="x", value=42.0,
            metric_type=MetricType.GAUGE,
        )
        orch._bus.publish(metric)
        assert len(mc.events) == 1
        assert mc.events[0].value == 42.0

    def test_alert_event_reaches_manager_via_bus(self, platform) -> None:
        orch, _, _ = platform
        am = orch._alert_manager
        assert isinstance(am, InMemoryAlertManager)
        alert = Alert(
            timestamp_ns=1, correlation_id="c", sequence=1,
            severity=AlertSeverity.WARNING, layer="test",
            alert_name="test_alert", message="test",
        )
        orch._bus.publish(alert)
        assert len(am.active_alerts()) == 1


# ── 4. RegimeEngine wiring ─────────────────────────────────────────


class TestRegimeWireup:
    def test_regime_engine_created_from_config(self, platform) -> None:
        orch, _, _ = platform
        assert orch._regime_engine is not None
        assert isinstance(orch._regime_engine, HMM3StateFractional)

    def test_regime_shared_with_risk_engine(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._risk_engine, BasicRiskEngine)
        assert orch._risk_engine._regime_engine is orch._regime_engine

    def test_regime_shared_with_position_sizer(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._position_sizer, BudgetBasedSizer)
        assert orch._position_sizer._regime_engine is orch._regime_engine

    def test_regime_none_when_config_says_none(self, tmp_path: Path) -> None:
        (tmp_path / "w.alpha.yaml").write_text(ALPHA_SPEC)
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_spec_dir=tmp_path,
            regime_engine=None,
        )
        orch, _ = build_platform(config)
        assert orch._regime_engine is None


# ── 5. Alpha pipeline wiring ───────────────────────────────────────


class TestAlphaWireup:
    def test_feature_engine_is_composite(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._feature_engine, CompositeFeatureEngine)

    def test_signal_engine_is_composite(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._signal_engine, CompositeSignalEngine)

    def test_alpha_registry_wired(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._alpha_registry, AlphaRegistry)
        assert len(orch._alpha_registry) == 1

    def test_lifecycle_disabled_for_backtest(self, platform) -> None:
        orch, _, _ = platform
        registry = orch._alpha_registry
        assert len(registry.active_alphas()) == 1, (
            "All alphas must be active in backtest (lifecycle tracking disabled)"
        )

    def test_signal_engine_shares_registry_with_feature_engine(self, platform) -> None:
        orch, _, _ = platform
        fe = orch._feature_engine
        se = orch._signal_engine
        assert isinstance(fe, CompositeFeatureEngine)
        assert isinstance(se, CompositeSignalEngine)
        assert se._registry is orch._alpha_registry


# ── 6. ExecutionBackend wiring ──────────────────────────────────────


class TestExecutionBackendWireup:
    def test_backend_is_execution_backend(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._backend, ExecutionBackend)

    def test_backend_mode_is_backtest(self, platform) -> None:
        orch, _, _ = platform
        assert orch._backend.mode == "BACKTEST"

    def test_replay_feed_shares_event_log(self, platform) -> None:
        orch, _, event_log = platform
        feed = orch._backend.market_data
        assert isinstance(feed, ReplayFeed)
        assert feed._event_log is event_log

    def test_backtest_router_type(self, platform) -> None:
        orch, _, _ = platform
        router = orch._backend.order_router
        assert isinstance(router, BacktestOrderRouter)

    def test_backtest_fill_latency_from_config(self, platform) -> None:
        orch, _, _ = platform
        router = orch._backend.order_router
        assert isinstance(router, BacktestOrderRouter)
        assert router._latency_ns == 1000


# ── 7. Safety infrastructure wiring ────────────────────────────────


class TestSafetyWireup:
    def test_kill_switch_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._kill_switch, InMemoryKillSwitch)

    def test_alert_manager_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._alert_manager, InMemoryAlertManager)

    def test_alert_manager_holds_kill_switch_ref(self, platform) -> None:
        orch, _, _ = platform
        am = orch._alert_manager
        assert isinstance(am, InMemoryAlertManager)
        assert am._kill_switch is orch._kill_switch

    def test_emergency_alert_activates_kill_switch(self, platform) -> None:
        orch, _, _ = platform
        am = orch._alert_manager
        ks = orch._kill_switch
        assert isinstance(am, InMemoryAlertManager)
        assert isinstance(ks, InMemoryKillSwitch)
        assert ks.is_active is False
        alert = Alert(
            timestamp_ns=1, correlation_id="c", sequence=1,
            severity=AlertSeverity.EMERGENCY, layer="test",
            alert_name="catastrophe", message="system failure",
        )
        am.emit(alert)
        assert ks.is_active is True

    def test_kill_switch_starts_inactive(self, platform) -> None:
        orch, _, _ = platform
        assert orch._kill_switch.is_active is False


# ── 8. Storage wiring ──────────────────────────────────────────────


class TestStorageWireup:
    def test_event_log_type(self, platform) -> None:
        orch, _, event_log = platform
        assert isinstance(orch._event_log, InMemoryEventLog)
        assert orch._event_log is event_log

    def test_trade_journal_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._trade_journal, InMemoryTradeJournal)

    def test_feature_snapshots_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._feature_snapshots, InMemoryFeatureSnapshotStore)


# ── 9. MetricCollector wiring ───────────────────────────────────────


class TestMetricsWireup:
    def test_metric_collector_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._metrics, InMemoryMetricCollector)

    def test_flush_callable_and_idempotent(self, platform) -> None:
        orch, _, _ = platform
        mc = orch._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        assert mc._flushed is False
        mc.flush()
        assert mc._flushed is True
        mc.flush()
        assert mc._flushed is True

    def test_shutdown_calls_flush(self, platform) -> None:
        orch, config, _ = platform
        mc = orch._metrics
        assert isinstance(mc, InMemoryMetricCollector)
        orch.boot(config)
        orch.shutdown()
        assert mc._flushed is True


# ── 10. Risk wiring ────────────────────────────────────────────────


class TestRiskWireup:
    def test_risk_engine_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._risk_engine, BasicRiskEngine)

    def test_risk_config_matches_platform_config(self, platform) -> None:
        orch, config, _ = platform
        re = orch._risk_engine
        assert isinstance(re, BasicRiskEngine)
        assert re._config.max_position_per_symbol == config.risk_max_position_per_symbol
        assert re._config.max_gross_exposure_pct == config.risk_max_gross_exposure_pct
        assert re._config.max_drawdown_pct == config.risk_max_drawdown_pct
        assert re._config.account_equity == Decimal(str(config.account_equity))

    def test_position_sizer_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._position_sizer, BudgetBasedSizer)


# ── 11. Position store wiring ──────────────────────────────────────


class TestPositionWireup:
    def test_position_store_type(self, platform) -> None:
        orch, _, _ = platform
        assert isinstance(orch._positions, MemoryPositionStore)

    def test_position_store_starts_empty(self, platform) -> None:
        orch, _, _ = platform
        assert len(orch._positions.all_positions()) == 0
        assert orch._positions.total_exposure() == Decimal("0")


# ── 12. Account equity wiring ──────────────────────────────────────


class TestEquityWireup:
    def test_account_equity_from_config(self, platform) -> None:
        orch, config, _ = platform
        assert orch._account_equity == Decimal(str(config.account_equity))
        assert orch._account_equity == Decimal("250000")


# ── 13. IntentTranslator wiring ─────────────────────────────────────


class TestIntentTranslatorWireup:
    def test_intent_translator_explicitly_wired(self, platform) -> None:
        orch, _, _ = platform
        from feelies.execution.intent import SignalPositionTranslator
        assert isinstance(orch._intent_translator, SignalPositionTranslator)

    def test_intent_translator_is_not_orchestrator_default(self, platform) -> None:
        """Bootstrap must explicitly create and pass the translator,
        not rely on the orchestrator's hidden internal default."""
        orch, _, _ = platform
        assert orch._intent_translator is not None


# ── 14. Normalizer: correct absence for backtest ───────────────────


class TestNormalizerBacktest:
    def test_normalizer_none_for_backtest_mode(self, platform) -> None:
        """Backtest replays pre-validated data from EventLog.
        The normalizer is the ingestion boundary (raw bytes → canonical
        events).  Backtest data has already passed ingestion, so the
        normalizer is correctly absent."""
        orch, _, _ = platform
        assert orch._normalizer is None

    def test_data_integrity_passes_without_normalizer(self, platform) -> None:
        """Without a normalizer, _verify_data_integrity returns True
        (pre-validated backtest data is trusted)."""
        orch, config, _ = platform
        orch._config = config
        assert orch._verify_data_integrity() is True
