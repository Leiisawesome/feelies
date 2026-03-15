"""Tests for the macro (global stack) state machine."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition
from feelies.kernel.macro import (
    TRADING_MODES,
    MacroState,
    create_macro_state_machine,
)


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=0)


def _advance_to_ready(sm, clock: SimulatedClock) -> None:
    """Helper: INIT → DATA_SYNC → READY."""
    sm.transition(MacroState.DATA_SYNC, trigger="CONFIG_VALIDATED")
    sm.transition(MacroState.READY, trigger="DATA_INTEGRITY_OK")


class TestMacroInitialState:
    def test_starts_in_init(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        assert sm.state == MacroState.INIT

    def test_machine_name(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        assert sm.name == "global_stack"


class TestMacroHappyPaths:
    def test_init_to_data_sync(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.DATA_SYNC, trigger="CONFIG_VALIDATED")
        assert sm.state == MacroState.DATA_SYNC

    def test_data_sync_to_ready(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.DATA_SYNC, trigger="CONFIG_VALIDATED")
        sm.transition(MacroState.READY, trigger="DATA_INTEGRITY_OK")
        assert sm.state == MacroState.READY

    def test_full_backtest_lifecycle(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)

        sm.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        assert sm.state == MacroState.BACKTEST_MODE

        sm.transition(MacroState.READY, trigger="BACKTEST_COMPLETE")
        assert sm.state == MacroState.READY

        sm.transition(MacroState.SHUTDOWN, trigger="CMD_SHUTDOWN")
        assert sm.state == MacroState.SHUTDOWN

    def test_ready_to_research_and_back(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)

        sm.transition(MacroState.RESEARCH_MODE, trigger="CMD_RESEARCH")
        assert sm.state == MacroState.RESEARCH_MODE

        sm.transition(MacroState.READY, trigger="JOB_COMPLETE")
        assert sm.state == MacroState.READY

    def test_ready_to_paper_trading(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER_DEPLOY")
        assert sm.state == MacroState.PAPER_TRADING_MODE

    def test_ready_to_live_trading(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        assert sm.state == MacroState.LIVE_TRADING_MODE

    def test_paper_to_ready(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER_DEPLOY")
        sm.transition(MacroState.READY, trigger="CMD_STOP")
        assert sm.state == MacroState.READY

    def test_live_to_ready(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        sm.transition(MacroState.READY, trigger="CMD_STOP")
        assert sm.state == MacroState.READY


class TestMacroConfigFailure:
    def test_init_to_shutdown_on_config_error(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.SHUTDOWN, trigger="CONFIG_ERROR")
        assert sm.state == MacroState.SHUTDOWN


class TestMacroDegradedPaths:
    def test_data_sync_to_degraded(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.DATA_SYNC, trigger="CONFIG_VALIDATED")
        sm.transition(MacroState.DEGRADED, trigger="DATA_GAP_DETECTED")
        assert sm.state == MacroState.DEGRADED

    def test_backtest_to_degraded(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        sm.transition(MacroState.DEGRADED, trigger="INTEGRITY_VIOLATION")
        assert sm.state == MacroState.DEGRADED

    def test_research_to_degraded(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.RESEARCH_MODE, trigger="CMD_RESEARCH")
        sm.transition(MacroState.DEGRADED, trigger="CRITICAL_ERROR")
        assert sm.state == MacroState.DEGRADED

    def test_paper_to_degraded(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER_DEPLOY")
        sm.transition(MacroState.DEGRADED, trigger="EXECUTION_DRIFT")
        assert sm.state == MacroState.DEGRADED

    def test_live_to_degraded(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        sm.transition(MacroState.DEGRADED, trigger="DATA_DRIFT")
        assert sm.state == MacroState.DEGRADED

    def test_degraded_to_ready_recovery(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        sm.transition(MacroState.DEGRADED, trigger="INTEGRITY_VIOLATION")
        sm.transition(MacroState.READY, trigger="RECOVERY_VALIDATED")
        assert sm.state == MacroState.READY

    def test_degraded_to_shutdown(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        sm.transition(MacroState.DEGRADED, trigger="INTEGRITY_VIOLATION")
        sm.transition(MacroState.SHUTDOWN, trigger="CRITICAL_FAILURE")
        assert sm.state == MacroState.SHUTDOWN


class TestMacroRiskLockdown:
    def test_paper_to_risk_lockdown(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER_DEPLOY")
        sm.transition(MacroState.RISK_LOCKDOWN, trigger="RISK_BREACH")
        assert sm.state == MacroState.RISK_LOCKDOWN

    def test_live_to_risk_lockdown(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        sm.transition(MacroState.RISK_LOCKDOWN, trigger="RISK_BREACH")
        assert sm.state == MacroState.RISK_LOCKDOWN

    def test_lockdown_to_ready_human_unlock(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        sm.transition(MacroState.RISK_LOCKDOWN, trigger="RISK_BREACH")
        sm.transition(MacroState.READY, trigger="FORCED_FLATTEN_COMPLETE")
        assert sm.state == MacroState.READY


class TestMacroIllegalTransitions:
    def test_init_to_ready_illegal(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        with pytest.raises(IllegalTransition):
            sm.transition(MacroState.READY, trigger="SKIP_AHEAD")

    def test_init_to_backtest_illegal(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        with pytest.raises(IllegalTransition):
            sm.transition(MacroState.BACKTEST_MODE, trigger="SKIP")

    def test_shutdown_is_terminal(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.SHUTDOWN, trigger="CONFIG_ERROR")
        with pytest.raises(IllegalTransition):
            sm.transition(MacroState.READY, trigger="REVIVE")

    def test_shutdown_has_no_outbound_edges(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.SHUTDOWN, trigger="CONFIG_ERROR")
        for target in MacroState:
            assert not sm.can_transition(target)

    def test_backtest_to_live_illegal(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        _advance_to_ready(sm, clock)
        sm.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        with pytest.raises(IllegalTransition):
            sm.transition(MacroState.LIVE_TRADING_MODE, trigger="JUMP")


class TestMacroTradingModes:
    def test_trading_modes_frozenset(self) -> None:
        assert MacroState.BACKTEST_MODE in TRADING_MODES
        assert MacroState.PAPER_TRADING_MODE in TRADING_MODES
        assert MacroState.LIVE_TRADING_MODE in TRADING_MODES
        assert MacroState.READY not in TRADING_MODES
        assert MacroState.INIT not in TRADING_MODES


class TestMacroHistory:
    def test_history_records_transitions(self, clock: SimulatedClock) -> None:
        sm = create_macro_state_machine(clock)
        sm.transition(MacroState.DATA_SYNC, trigger="CONFIG_VALIDATED")
        sm.transition(MacroState.READY, trigger="DATA_INTEGRITY_OK")
        assert len(sm.history) == 2
        assert sm.history[0].from_state == "INIT"
        assert sm.history[0].to_state == "DATA_SYNC"
        assert sm.history[0].trigger == "CONFIG_VALIDATED"
        assert sm.history[1].from_state == "DATA_SYNC"
        assert sm.history[1].to_state == "READY"
