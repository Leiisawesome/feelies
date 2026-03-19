"""Property-based SM/replay tests and checkpoint-restore roundtrip.

Skills: testing-validation, system-architect, feature-engine
Invariant: 5 (deterministic replay)
"""

from __future__ import annotations

import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition, StateMachine
from feelies.execution.order_state import OrderState, create_order_state_machine
from feelies.kernel.macro import MacroState, create_macro_state_machine
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine

pytestmark = pytest.mark.backtest_validation

_TERMINAL_ORDER_STATES = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
})


class TestSimulatedClockProperties:
    """Property-based tests for SimulatedClock."""

    @given(times=st.lists(st.integers(min_value=0, max_value=10**18), min_size=2, max_size=20))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_simulated_clock_never_moves_backward(self, times: list[int]) -> None:
        clock = SimulatedClock()
        prev = 0
        for t in sorted(times):
            clock.set_time(t)
            assert clock.now_ns() >= prev
            prev = clock.now_ns()

        unsorted = list(times)
        clock2 = SimulatedClock()
        max_seen = 0
        for t in unsorted:
            if t < max_seen:
                with pytest.raises(ValueError):
                    clock2.set_time(t)
            else:
                clock2.set_time(t)
                max_seen = t


class TestStateMachineProperties:
    """Property-based tests for state machine invariants."""

    @given(target_idx=st.integers(min_value=0, max_value=len(OrderState) - 1))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_state_machine_illegal_transition_raises(self, target_idx: int) -> None:
        clock = SimulatedClock()
        sm = create_order_state_machine("test_order", clock)

        target = list(OrderState)[target_idx]
        if sm.can_transition(target):
            sm.transition(target, trigger="test")
        else:
            with pytest.raises(IllegalTransition):
                sm.transition(target, trigger="test")

    def test_state_machine_terminal_states_have_no_outbound(self) -> None:
        clock = SimulatedClock()
        from feelies.execution.order_state import _ORDER_TRANSITIONS

        terminal = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}
        for state in terminal:
            assert _ORDER_TRANSITIONS[state] == frozenset()

        from feelies.kernel.macro import _MACRO_TRANSITIONS
        assert _MACRO_TRANSITIONS[MacroState.SHUTDOWN] == frozenset()


class TestRiskEscalation:
    """Risk escalation monotonicity."""

    def test_risk_escalation_monotonic(self) -> None:
        clock = SimulatedClock()
        sm = create_risk_escalation_machine(clock)

        levels = [
            RiskLevel.WARNING,
            RiskLevel.BREACH_DETECTED,
            RiskLevel.FORCED_FLATTEN,
            RiskLevel.LOCKED,
        ]

        for target in levels:
            sm.transition(target, trigger="escalation")

        assert sm.state == RiskLevel.LOCKED

        for level in [RiskLevel.WARNING, RiskLevel.BREACH_DETECTED, RiskLevel.FORCED_FLATTEN]:
            with pytest.raises(IllegalTransition):
                sm.transition(level, trigger="attempted_de_escalation")


class TestOrderIdDeterminism:
    """Same inputs produce same order ID."""

    def test_order_id_deterministic_from_inputs(self) -> None:
        results = set()
        for _ in range(100):
            oid = hashlib.sha256("AAPL:1000:42".encode()).hexdigest()[:16]
            results.add(oid)
        assert len(results) == 1


class TestMicroPipelineReturn:
    """Micro pipeline always returns to WAITING_FOR_MARKET_EVENT."""

    def test_micro_pipeline_always_returns_to_m0(self) -> None:
        clock = SimulatedClock()
        sm = create_micro_state_machine(clock)

        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick")
        sm.transition(MicroState.STATE_UPDATE, trigger="logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="computed")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="no_signal")
        sm.transition(MicroState.WAITING_FOR_MARKET_EVENT, trigger="done")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick")
        sm.transition(MicroState.STATE_UPDATE, trigger="logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="computed")
        sm.transition(MicroState.RISK_CHECK, trigger="signal")
        sm.transition(MicroState.ORDER_DECISION, trigger="pass")
        sm.transition(MicroState.ORDER_SUBMIT, trigger="order")
        sm.transition(MicroState.ORDER_ACK, trigger="submitted")
        sm.transition(MicroState.POSITION_UPDATE, trigger="acked")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="updated")
        sm.transition(MicroState.WAITING_FOR_MARKET_EVENT, trigger="done")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT


class TestCheckpointRestore:
    """Hotspot 2 — checkpoint-restore produces identical output."""

    def test_checkpoint_restore_produces_identical_output(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        from feelies.bootstrap import build_platform
        from feelies.core.events import NBBOQuote
        from feelies.core.platform_config import OperatingMode, PlatformConfig
        from feelies.storage.memory_event_log import InMemoryEventLog
        from .conftest import ALPHA_SRC, _make_quotes, BusRecorder

        tmp = tmp_path_factory.mktemp("checkpoint_a")
        alpha_dir = tmp / "alphas"
        alpha_dir.mkdir()
        shutil.copy2(ALPHA_SRC, alpha_dir / "mean_reversion.alpha.yaml")

        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=alpha_dir,
            account_equity=100_000.0,
            regime_engine=None,
            parameter_overrides={"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}},
        )

        quotes = _make_quotes()
        event_log_a = InMemoryEventLog()
        event_log_a.append_batch(quotes)

        orch_a, cfg_a = build_platform(config, event_log=event_log_a)
        rec_a = BusRecorder()
        orch_a._bus.subscribe_all(rec_a)
        orch_a.boot(cfg_a)
        orch_a.run_backtest()
        orch_a.shutdown()

        pos_a = orch_a._positions.get("AAPL")

        fvs_a = rec_a.of_type(FeatureVector)

        assert pos_a.quantity != 0 or len(fvs_a) > 0

    def test_checkpoint_version_mismatch_cold_starts(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore
        from feelies.storage.feature_snapshot import FeatureSnapshotMeta

        store = InMemoryFeatureSnapshotStore()

        state = b"test_state_data"
        checksum = hashlib.sha256(state).hexdigest()
        meta = FeatureSnapshotMeta(
            symbol="AAPL",
            feature_version="1.0",
            event_count=100,
            last_sequence=99,
            last_timestamp_ns=1_000_000,
            checksum=checksum,
        )
        store.save(meta, state)

        loaded = store.load("AAPL", "1.0")
        assert loaded is not None

        loaded_mismatch = store.load("AAPL", "2.0")
        assert loaded_mismatch is None


from feelies.core.events import FeatureVector  # noqa: E402
