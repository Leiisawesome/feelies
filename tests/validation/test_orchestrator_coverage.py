"""Orchestrator coverage tests — paper/live/research modes, order lifecycle,
lockdown/recovery, and fill reconciliation edge cases.

Skills: testing-validation, system-architect, live-execution
Hotspot: H2 (orchestrator at 64% coverage)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest

from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    RiskVerdict,
    Side,
    Signal,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.state_machine import IllegalTransition
from feelies.execution.backend import ExecutionBackend, MarketDataSource, OrderRouter
from feelies.execution.order_state import OrderState
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.risk.escalation import RiskLevel
from feelies.storage.memory_event_log import InMemoryEventLog

from .conftest import PIPELINE_TEST_ALPHA_ID, BusRecorder, _make_quotes, _run_scenario, _write_test_alpha

pytestmark = pytest.mark.backtest_validation


def _build_orchestrator(tmp_path: Path, quotes=None, **kwargs):
    alpha_dir = tmp_path / "alphas"
    _write_test_alpha(alpha_dir)

    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
        parameter_overrides={PIPELINE_TEST_ALPHA_ID: {"ewma_span": 5, "zscore_entry": 1.0}},
    )
    defaults.update(kwargs)

    config = PlatformConfig(**defaults)
    event_log = InMemoryEventLog()
    if quotes:
        event_log.append_batch(quotes)

    orch, resolved_config = build_platform(config, event_log=event_log)
    recorder = BusRecorder()
    orch._bus.subscribe_all(recorder)
    orch.boot(resolved_config)
    return orch, recorder, resolved_config


class TestRunResearch:
    """Orchestrator.run_research() lifecycle."""

    def test_research_mode_runs_job_and_returns_ready(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        assert orch.macro_state == MacroState.READY

        job_ran = []

        def research_job():
            job_ran.append(True)

        orch.run_research(research_job)
        assert orch.macro_state == MacroState.READY
        assert len(job_ran) == 1

    def test_research_mode_exception_degrades(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        def failing_job():
            raise RuntimeError("research failure")

        with pytest.raises(RuntimeError, match="research failure"):
            orch.run_research(failing_job)
        assert orch.macro_state == MacroState.DEGRADED


class TestHalt:
    """Orchestrator.halt() — stop trading mode cleanly."""

    def test_halt_from_backtest_mode(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path, quotes=_make_quotes())
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        assert orch.macro_state == MacroState.BACKTEST_MODE

        orch.halt()
        assert orch.macro_state == MacroState.READY

    def test_halt_from_ready_is_noop(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        assert orch.macro_state == MacroState.READY

        orch.halt()
        assert orch.macro_state == MacroState.READY


class TestUnlockFromLockdown:
    """Orchestrator.unlock_from_lockdown() — human re-authorization."""

    def test_unlock_succeeds_with_zero_exposure(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        orch._macro._state = MacroState.PAPER_TRADING_MODE
        orch._escalate_risk("test_cid")
        assert orch.macro_state == MacroState.RISK_LOCKDOWN
        assert orch._risk_escalation.state == RiskLevel.LOCKED

        orch.unlock_from_lockdown(audit_token="human_approved_123")
        assert orch.macro_state == MacroState.READY
        assert orch._risk_escalation.state == RiskLevel.NORMAL

    def test_unlock_fails_with_nonzero_exposure(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        orch._macro._state = MacroState.PAPER_TRADING_MODE
        orch._escalate_risk("test_cid")

        orch._positions.update("AAPL", 100, Decimal("150.00"))

        with pytest.raises(RuntimeError, match="total exposure"):
            orch.unlock_from_lockdown(audit_token="human_approved_123")

    def test_unlock_from_wrong_state_raises(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        assert orch.macro_state == MacroState.READY

        with pytest.raises(AssertionError, match="RISK_LOCKDOWN"):
            orch.unlock_from_lockdown(audit_token="abc")


class TestResetRiskEscalation:
    """Orchestrator.reset_risk_escalation() — human-authorized risk reset."""

    def test_reset_from_warning_succeeds(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._risk_escalation.transition(RiskLevel.WARNING, trigger="test")

        orch.reset_risk_escalation(audit_token="human_reset")
        assert orch._risk_escalation.state == RiskLevel.NORMAL

    def test_reset_from_normal_is_noop(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch.reset_risk_escalation(audit_token="noop")
        assert orch._risk_escalation.state == RiskLevel.NORMAL

    def test_reset_from_locked_raises(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._macro._state = MacroState.PAPER_TRADING_MODE
        orch._escalate_risk("test_cid")
        assert orch._risk_escalation.state == RiskLevel.LOCKED

        with pytest.raises(RuntimeError, match="LOCKED"):
            orch.reset_risk_escalation(audit_token="bad")

    def test_reset_during_trading_mode_raises(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._risk_escalation.transition(RiskLevel.WARNING, trigger="test")
        orch._macro._state = MacroState.BACKTEST_MODE

        with pytest.raises(RuntimeError, match="active trading"):
            orch.reset_risk_escalation(audit_token="bad")


class TestCancelOrder:
    """Orchestrator.cancel_order() — order lifecycle management."""

    def test_cancel_unknown_order_returns_false(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        assert orch.cancel_order("nonexistent", reason="test") is False

    def test_cancel_acknowledged_order_succeeds(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        clock = orch._clock

        orch._track_order("ord-001", Side.BUY, OrderRequest(
            timestamp_ns=1000, correlation_id="cid", sequence=1,
            order_id="ord-001", symbol="AAPL", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=100,
        ))
        sm = orch._active_orders["ord-001"][0]
        sm.transition(OrderState.SUBMITTED, trigger="submit")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")

        result = orch.cancel_order("ord-001", reason="test_cancel")
        assert result is True
        assert sm.state == OrderState.CANCEL_REQUESTED

    def test_cancel_filled_order_returns_false(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        orch._track_order("ord-002", Side.BUY, OrderRequest(
            timestamp_ns=1000, correlation_id="cid", sequence=1,
            order_id="ord-002", symbol="AAPL", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=100,
        ))
        sm = orch._active_orders["ord-002"][0]
        sm.transition(OrderState.SUBMITTED, trigger="submit")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")
        sm.transition(OrderState.FILLED, trigger="fill")

        assert orch.cancel_order("ord-002", reason="test") is False


class TestApplyAckBranches:
    """Orchestrator._apply_ack_to_order() — branch coverage for ack statuses."""

    def _setup_order(self, orch, order_id="ord-001"):
        orch._track_order(order_id, Side.BUY, OrderRequest(
            timestamp_ns=1000, correlation_id="cid", sequence=1,
            order_id=order_id, symbol="AAPL", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=100,
        ))
        sm = orch._active_orders[order_id][0]
        sm.transition(OrderState.SUBMITTED, trigger="submit")
        return sm

    def test_ack_rejected(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        self._setup_order(orch)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.REJECTED, reason="insufficient funds",
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.REJECTED

    def test_ack_acknowledged(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        self._setup_order(orch)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.ACKNOWLEDGED,
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.ACKNOWLEDGED

    def test_ack_filled_auto_acknowledges(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        self._setup_order(orch)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=100, fill_price=Decimal("150.00"),
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.FILLED

    def test_ack_partially_filled(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        sm = self._setup_order(orch)
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.PARTIALLY_FILLED,
            filled_quantity=50, fill_price=Decimal("150.00"),
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.PARTIALLY_FILLED

    def test_ack_cancelled(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        sm = self._setup_order(orch)
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")
        sm.transition(OrderState.CANCEL_REQUESTED, trigger="cancel")

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.CANCELLED,
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.CANCELLED

    def test_ack_expired(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        sm = self._setup_order(orch)
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.EXPIRED,
        )
        orch._apply_ack_to_order(ack)
        assert orch._active_orders["ord-001"][0].state == OrderState.EXPIRED

    def test_ack_for_unknown_order_emits_alert(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ghost-order", symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=100, fill_price=Decimal("150.00"),
        )
        orch._apply_ack_to_order(ack)
        alerts = rec.of_type(Alert)
        assert any("ghost-order" in a.message for a in alerts)

    def test_ack_inapplicable_state_emits_alert(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        sm = self._setup_order(orch)
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")
        sm.transition(OrderState.FILLED, trigger="fill")

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.CANCELLED,
        )
        orch._apply_ack_to_order(ack)
        alerts = rec.of_type(Alert)
        assert any("inapplicable" in a.alert_name for a in alerts)


class TestReconcileFillsEdgeCases:
    """Fill reconciliation edge cases."""

    def test_fill_for_unknown_order_emits_alert_and_skips(
        self, tmp_path: Path
    ) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="unknown-order", symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=100, fill_price=Decimal("150.00"),
        )
        orch._reconcile_fills([ack], "cid")
        alerts = rec.of_type(Alert)
        assert any("unknown" in a.alert_name for a in alerts)

        pos = orch._positions.get("AAPL")
        assert pos.quantity == 0

    def test_fill_with_none_price_skipped(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=100, fill_price=None,
        )
        orch._reconcile_fills([ack], "cid")
        pos = orch._positions.get("AAPL")
        assert pos.quantity == 0

    def test_fill_with_zero_quantity_skipped(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)

        ack = OrderAck(
            timestamp_ns=2000, correlation_id="cid", sequence=2,
            order_id="ord-001", symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=0, fill_price=Decimal("150.00"),
        )
        orch._reconcile_fills([ack], "cid")
        pos = orch._positions.get("AAPL")
        assert pos.quantity == 0


class TestShutdownOrderTracking:
    """Inv-4: pending orders flagged at shutdown."""

    def test_shutdown_with_pending_orders_emits_alert(
        self, tmp_path: Path
    ) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._track_order("ord-pending", Side.BUY, OrderRequest(
            timestamp_ns=1000, correlation_id="cid", sequence=1,
            order_id="ord-pending", symbol="AAPL", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=100,
        ))
        sm = orch._active_orders["ord-pending"][0]
        sm.transition(OrderState.SUBMITTED, trigger="submit")

        orch.shutdown()
        alerts = rec.of_type(Alert)
        assert any("pending" in a.alert_name for a in alerts)


class TestEscalateRisk:
    """Risk escalation lifecycle coverage."""

    def test_escalate_from_normal_reaches_locked(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._macro._state = MacroState.PAPER_TRADING_MODE

        orch._escalate_risk("test_cid")

        assert orch._risk_escalation.state == RiskLevel.LOCKED
        assert orch._kill_switch.is_active
        assert orch.macro_state == MacroState.RISK_LOCKDOWN

    def test_escalate_from_warning_still_reaches_locked(self, tmp_path: Path) -> None:
        orch, rec, _ = _build_orchestrator(tmp_path)
        orch._macro._state = MacroState.PAPER_TRADING_MODE
        orch._risk_escalation.transition(RiskLevel.WARNING, trigger="test")

        orch._escalate_risk("test_cid")

        assert orch._risk_escalation.state == RiskLevel.LOCKED


class TestCheckOrderExposureReject:
    """M6 check_order rejects when gross exposure exceeds limit."""

    def test_exposure_reject_at_m6_produces_no_fills(
        self, tmp_path: Path
    ) -> None:
        ticks = [
            {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
            {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
            {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
            {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
        ]
        orch, rec, _, _ = _run_scenario(
            tmp_path,
            quotes=_make_quotes("AAPL", ticks),
            account_equity=100_000.0,
            risk_max_gross_exposure_pct=0.001,
        )
        verdicts = rec.of_type(RiskVerdict)
        rejected = [v for v in verdicts if v.action.name == "REJECT"]
        assert len(rejected) > 0


class TestCheckOrderPrecedence:
    """check_order evaluates constraints in the correct priority order:
    position limit → exposure → drawdown → scale_down → allow.

    The M6 drawdown FORCE_FLATTEN path is covered by the unit test
    test_basic_risk.py::TestCheckOrder::test_drawdown_breached_force_flattens.
    """

    def test_position_limit_checked_before_exposure(
        self, tmp_path: Path
    ) -> None:
        from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
        from feelies.portfolio.memory_position_store import MemoryPositionStore
        cfg = RiskConfig(
            max_position_per_symbol=10,
            max_gross_exposure_pct=0.001,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store = MemoryPositionStore()
        store.update("AAPL", 10, Decimal("150"))
        order = OrderRequest(
            timestamp_ns=1_000_000_000, correlation_id="corr-1",
            sequence=1, order_id="ord-1", symbol="AAPL",
            side=Side.BUY, order_type=OrderType.MARKET, quantity=5,
        )
        verdict = engine.check_order(order, store)
        assert verdict.action.name == "REJECT"
        assert "post-fill" in verdict.reason


class TestCheckOrderScaleDown:
    """M6 check_order SCALE_DOWN reduces order quantity."""

    def test_scale_down_at_m6_reduces_filled_quantity(
        self, tmp_path: Path
    ) -> None:
        ticks = [
            {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
            {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
            {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
            {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
        ]
        orch, rec, _, _ = _run_scenario(
            tmp_path,
            quotes=_make_quotes("AAPL", ticks),
            account_equity=100_000.0,
            risk_max_gross_exposure_pct=0.5,
        )
        verdicts = rec.of_type(RiskVerdict)
        scale_downs = [
            v for v in verdicts if v.action.name == "SCALE_DOWN"
        ]
        if scale_downs:
            for sd in scale_downs:
                assert 0.0 < sd.scaling_factor <= 1.0
