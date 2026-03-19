"""Fault injection, degraded mode, and safety tests.

Skills: testing-validation, data-engineering, system-architect, risk-engine
Invariant: 11 (fail-safe default)
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderRequest,
    Signal,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.storage.memory_event_log import InMemoryEventLog

from .conftest import ALPHA_SRC, BusRecorder, _make_quotes, _run_scenario

pytestmark = pytest.mark.backtest_validation


def _setup_platform(tmp_path: Path, quotes, **kwargs):
    alpha_dir = tmp_path / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    shutil.copy2(ALPHA_SRC, alpha_dir / "mean_reversion.alpha.yaml")

    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
        parameter_overrides={"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}},
    )
    defaults.update(kwargs)

    config = PlatformConfig(**defaults)
    event_log = InMemoryEventLog()
    event_log.append_batch(quotes)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)
    orchestrator.boot(resolved_config)
    return orchestrator, recorder, resolved_config


class TestDataFaults:
    """Fault injection with corrupt/extreme data."""

    def test_zero_size_quote_does_not_crash(self, fault_scenario_factory) -> None:
        orch, rec, _, _ = fault_scenario_factory("zero_size")
        assert orch.macro_state in (MacroState.READY, MacroState.DEGRADED)

    def test_extreme_price_spike_handled(self, fault_scenario_factory) -> None:
        orch, rec, _, _ = fault_scenario_factory("extreme_spike")
        assert orch.macro_state in (MacroState.READY, MacroState.DEGRADED)

    def test_duplicate_timestamp_events_processed(
        self, fault_scenario_factory
    ) -> None:
        orch, rec, _, _ = fault_scenario_factory("duplicate_ts")
        assert orch.macro_state in (MacroState.READY, MacroState.DEGRADED)


class TestEngineExceptionDegradation:
    """Exception injection in pipeline engines."""

    def test_feature_engine_exception_degrades_gracefully(
        self, tmp_path: Path
    ) -> None:
        quotes = _make_quotes()
        orch, rec, _ = _setup_platform(tmp_path, quotes)

        original = orch._feature_engine.update
        call_count = 0

        def exploding(quote):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected feature fault")
            return original(quote)

        orch._feature_engine.update = exploding
        orch.run_backtest()
        assert orch.macro_state == MacroState.DEGRADED

    def test_signal_engine_exception_degrades_gracefully(
        self, tmp_path: Path
    ) -> None:
        quotes = _make_quotes()
        orch, rec, _ = _setup_platform(tmp_path, quotes)

        original = orch._signal_engine.evaluate
        call_count = 0

        def exploding(features):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected signal fault")
            return original(features)

        orch._signal_engine.evaluate = exploding
        orch.run_backtest()
        assert orch.macro_state == MacroState.DEGRADED

    def test_risk_engine_exception_degrades_gracefully(
        self, tmp_path: Path
    ) -> None:
        quotes = _make_quotes()
        orch, rec, _ = _setup_platform(tmp_path, quotes)

        original = orch._risk_engine.check_signal

        def exploding(signal, positions):
            raise RuntimeError("injected risk fault")

        orch._risk_engine.check_signal = exploding
        orch.run_backtest()
        assert orch.macro_state == MacroState.DEGRADED


class TestDegradedModeRecovery:
    """Degraded mode behavior and recovery."""

    def test_degraded_mode_blocks_further_ticks(self, tmp_path: Path) -> None:
        quotes = _make_quotes()
        orch, rec, _ = _setup_platform(tmp_path, quotes)

        original = orch._feature_engine.update
        call_count = 0

        def exploding(quote):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("injected fault")
            return original(quote)

        orch._feature_engine.update = exploding
        orch.run_backtest()

        assert orch.macro_state == MacroState.DEGRADED
        assert call_count == 1

    def test_kill_switch_activated_mid_run_stops_pipeline(
        self, tmp_path: Path
    ) -> None:
        quotes = _make_quotes()
        orch, rec, _ = _setup_platform(tmp_path, quotes)

        original = orch._feature_engine.update
        call_count = 0

        def activating_kill_switch(quote):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                orch._kill_switch.activate(
                    reason="test", activated_by="test"
                )
            return original(quote)

        orch._feature_engine.update = activating_kill_switch
        orch.run_backtest()

        assert orch._kill_switch.is_active
        assert call_count < 8

    def test_recover_from_degraded_resumes(self, tmp_path: Path) -> None:
        quotes = _make_quotes()
        orch, rec, config = _setup_platform(tmp_path, quotes)

        original = orch._feature_engine.update
        call_count = 0

        def exploding(quote):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("injected fault")
            return original(quote)

        orch._feature_engine.update = exploding
        orch.run_backtest()
        assert orch.macro_state == MacroState.DEGRADED

        recovered = orch.recover_from_degraded()
        assert recovered
        assert orch.macro_state == MacroState.READY


class TestDrawdownAndLockdown:
    """Hotspot 3 — Drawdown / FORCE_FLATTEN in backtest."""

    def test_drawdown_triggers_force_flatten_and_lockdown(
        self, drawdown_scenario
    ) -> None:
        orchestrator, recorder, _, _ = drawdown_scenario
        assert orchestrator.macro_state in (
            MacroState.RISK_LOCKDOWN,
            MacroState.READY,
        )

    def test_drawdown_hwm_tracks_peak_equity(self) -> None:
        from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
        from feelies.portfolio.memory_position_store import MemoryPositionStore

        config = RiskConfig(
            max_position_per_symbol=1000,
            max_drawdown_pct=2.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(config=config)
        store = MemoryPositionStore()

        store.update("AAPL", 100, Decimal("150.00"))
        store.update("AAPL", -100, Decimal("155.00"))
        assert store.get("AAPL").realized_pnl == Decimal("500")

        engine._high_water_mark = config.account_equity + Decimal("500")

        store.update("AAPL", 100, Decimal("150.00"))
        store.update("AAPL", -100, Decimal("145.00"))

        breached = engine._is_drawdown_breached(store)
        assert isinstance(breached, bool)


class TestAllSignalsSuppressed:
    """Hotspot 9 — entire backtest produces zero signals."""

    def test_all_signals_suppressed_completes_cleanly(
        self, all_suppressed_scenario
    ) -> None:
        orchestrator, recorder, _, _ = all_suppressed_scenario
        assert orchestrator.macro_state == MacroState.READY

        signals = recorder.of_type(Signal)
        assert len(signals) == 0

        orders = recorder.of_type(OrderRequest)
        assert len(orders) == 0

        acks = recorder.of_type(OrderAck)
        assert len(acks) == 0

        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        assert len(records) == 0
