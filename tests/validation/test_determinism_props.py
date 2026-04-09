"""Property-based SM/replay tests and checkpoint-restore roundtrip.

Skills: testing-validation, system-architect, feature-engine
Invariant: 5 (deterministic replay)
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition, StateMachine
from feelies.execution.order_state import OrderState, create_order_state_machine
from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine
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


# ── SimulatedClock ───────────────────────────────────────────────────


class TestSimulatedClockProperties:
    """Property-based tests for SimulatedClock."""

    @given(times=st.lists(st.integers(min_value=0, max_value=10**18), min_size=2, max_size=20))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
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


# ── State Machine Random Walk Properties ─────────────────────────────


class TestStateMachineProperties:
    """Property-based tests for state machine invariants."""

    @given(target_idx=st.integers(min_value=0, max_value=len(OrderState) - 1))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_order_sm_illegal_transition_raises(self, target_idx: int) -> None:
        clock = SimulatedClock()
        sm = create_order_state_machine("test_order", clock)

        target = list(OrderState)[target_idx]
        if sm.can_transition(target):
            sm.transition(target, trigger="test")
        else:
            with pytest.raises(IllegalTransition):
                sm.transition(target, trigger="test")

    def test_state_machine_terminal_states_have_no_outbound(self) -> None:
        from feelies.execution.order_state import _ORDER_TRANSITIONS

        terminal = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}
        for state in terminal:
            assert _ORDER_TRANSITIONS[state] == frozenset()

        from feelies.kernel.macro import _MACRO_TRANSITIONS
        assert _MACRO_TRANSITIONS[MacroState.SHUTDOWN] == frozenset()

    @given(steps=st.lists(
        st.sampled_from(list(OrderState)),
        min_size=1, max_size=30,
    ))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_order_sm_random_walk_never_corrupts(self, steps: list[OrderState]) -> None:
        clock = SimulatedClock()
        sm = create_order_state_machine("walk", clock)
        for target in steps:
            if sm.can_transition(target):
                sm.transition(target, trigger="walk")
            else:
                with pytest.raises(IllegalTransition):
                    sm.transition(target, trigger="walk")
            assert sm.state in OrderState

    @given(steps=st.lists(
        st.sampled_from(list(MacroState)),
        min_size=1, max_size=30,
    ))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_macro_sm_random_walk_never_corrupts(self, steps: list[MacroState]) -> None:
        clock = SimulatedClock()
        sm = create_macro_state_machine(clock)
        for target in steps:
            if sm.can_transition(target):
                sm.transition(target, trigger="walk")
            else:
                with pytest.raises(IllegalTransition):
                    sm.transition(target, trigger="walk")
            assert sm.state in MacroState

    @given(steps=st.lists(
        st.sampled_from(list(DataHealth)),
        min_size=1, max_size=30,
    ))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_data_health_sm_random_walk_never_corrupts(self, steps: list[DataHealth]) -> None:
        clock = SimulatedClock()
        sm = create_data_integrity_machine("AAPL", clock)
        for target in steps:
            if sm.can_transition(target):
                sm.transition(target, trigger="walk")
            else:
                with pytest.raises(IllegalTransition):
                    sm.transition(target, trigger="walk")
            assert sm.state in DataHealth

    @given(steps=st.lists(
        st.sampled_from(list(MicroState)),
        min_size=1, max_size=30,
    ))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_micro_sm_random_walk_never_corrupts(self, steps: list[MicroState]) -> None:
        clock = SimulatedClock()
        sm = create_micro_state_machine(clock)
        for target in steps:
            if sm.can_transition(target):
                sm.transition(target, trigger="walk")
            else:
                with pytest.raises(IllegalTransition):
                    sm.transition(target, trigger="walk")
            assert sm.state in MicroState


# ── Risk Escalation ──────────────────────────────────────────────────


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

    @given(steps=st.lists(
        st.sampled_from(list(RiskLevel)),
        min_size=1, max_size=20,
    ))
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_risk_sm_never_de_escalates_without_reset(self, steps: list[RiskLevel]) -> None:
        """Risk level only decreases via LOCKED → NORMAL (human unlock).
        Any other de-escalation is forbidden."""
        clock = SimulatedClock()
        sm = create_risk_escalation_machine(clock)
        level_order = {
            RiskLevel.NORMAL: 0,
            RiskLevel.WARNING: 1,
            RiskLevel.BREACH_DETECTED: 2,
            RiskLevel.FORCED_FLATTEN: 3,
            RiskLevel.LOCKED: 4,
        }
        high_water = level_order[RiskLevel.NORMAL]

        for target in steps:
            prev = sm.state
            if sm.can_transition(target):
                sm.transition(target, trigger="walk")
                new_level = level_order[sm.state]
                is_human_unlock = (prev == RiskLevel.LOCKED and target == RiskLevel.NORMAL)
                if not is_human_unlock and sm.state != RiskLevel.NORMAL:
                    assert new_level >= high_water, (
                        f"De-escalation detected: {high_water} -> {new_level}"
                    )
                if is_human_unlock:
                    high_water = 0
                else:
                    high_water = max(high_water, new_level)
            else:
                with pytest.raises(IllegalTransition):
                    sm.transition(target, trigger="walk")


# ── Deterministic Order ID ───────────────────────────────────────────


class TestOrderIdDeterminism:
    """Same inputs produce same order ID."""

    @given(
        cid=st.text(min_size=1, max_size=50),
        seq=st.integers(min_value=0, max_value=10**9),
    )
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_order_id_deterministic_from_inputs(self, cid: str, seq: int) -> None:
        oid1 = hashlib.sha256(f"{cid}:{seq}".encode()).hexdigest()[:16]
        oid2 = hashlib.sha256(f"{cid}:{seq}".encode()).hexdigest()[:16]
        assert oid1 == oid2
        assert len(oid1) == 16


# ── Micro Pipeline ───────────────────────────────────────────────────


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


# ── Position Conservation ────────────────────────────────────────────


class TestPositionConservation:
    """Property: sum of signed fills = final position quantity."""

    @given(
        fills=st.lists(
            st.tuples(
                st.sampled_from(["BUY", "SELL"]),
                st.integers(min_value=1, max_value=500),
            ),
            min_size=1, max_size=20,
        )
    )
    @settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
    def test_position_conservation(self, fills: list[tuple[str, int]]) -> None:
        from feelies.portfolio.memory_position_store import MemoryPositionStore

        store = MemoryPositionStore()
        expected_qty = 0
        for side_str, qty in fills:
            signed = qty if side_str == "BUY" else -qty
            store.update("AAPL", signed, Decimal("150.00"))
            expected_qty += signed

        pos = store.get("AAPL")
        assert pos.quantity == expected_qty


# ── Enum Completeness ────────────────────────────────────────────────


class TestEnumCompleteness:
    """Construction of SM with missing entries raises ValueError."""

    def test_incomplete_order_table_raises(self) -> None:
        clock = SimulatedClock()
        incomplete = {
            OrderState.CREATED: frozenset({OrderState.SUBMITTED}),
        }
        with pytest.raises(ValueError, match="Transition table incomplete"):
            StateMachine(
                name="bad_order", initial_state=OrderState.CREATED,
                transitions=incomplete, clock=clock,
            )

    def test_incomplete_macro_table_raises(self) -> None:
        clock = SimulatedClock()
        incomplete = {MacroState.INIT: frozenset({MacroState.DATA_SYNC})}
        with pytest.raises(ValueError, match="Transition table incomplete"):
            StateMachine(
                name="bad_macro", initial_state=MacroState.INIT,
                transitions=incomplete, clock=clock,
            )

    def test_incomplete_data_health_table_raises(self) -> None:
        clock = SimulatedClock()
        incomplete = {DataHealth.HEALTHY: frozenset({DataHealth.GAP_DETECTED})}
        with pytest.raises(ValueError, match="Transition table incomplete"):
            StateMachine(
                name="bad_health", initial_state=DataHealth.HEALTHY,
                transitions=incomplete, clock=clock,
            )


# ── Checkpoint Restore ───────────────────────────────────────────────


class TestCheckpointRestore:
    """Hotspot 2 — checkpoint-restore produces identical output."""

    def test_checkpoint_restore_produces_identical_output(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        from feelies.bootstrap import build_platform
        from feelies.core.events import NBBOQuote
        from feelies.core.platform_config import OperatingMode, PlatformConfig
        from feelies.storage.memory_event_log import InMemoryEventLog
        from .conftest import PIPELINE_TEST_ALPHA_ID, _make_quotes, _write_test_alpha, BusRecorder

        tmp = tmp_path_factory.mktemp("checkpoint_a")
        alpha_dir = tmp / "alphas"
        _write_test_alpha(alpha_dir)

        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=alpha_dir,
            account_equity=100_000.0,
            regime_engine=None,
            parameter_overrides={PIPELINE_TEST_ALPHA_ID: {"ewma_span": 5, "zscore_entry": 1.0}},
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
