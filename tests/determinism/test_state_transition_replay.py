"""State-machine baseline — ``StateTransition`` replay parity (audit P1 #12,
extended to all five SMs by audit-2026-07-02 P1 #5).

The five platform state machines are covered by *property* tests (legal-edge
enforcement, enum completeness) but no parity hash pinned the
``StateTransition`` *stream* a deterministic run produces — so a reordered
emission or a re-allocated ``sequence`` on the SM audit trail would slip past
the determinism suite.

This baseline drives all **five** real state machines — ``RiskLevel``
escalation (monotonic-tighten + human-unlock cycle), ``OrderState`` lifecycle
(full-fill, cancel, and reject paths), ``MacroState`` lifecycle (boot through
a backtest run to shutdown), ``MicroState`` (one full M0-M10 tick walk down
the deepest legal spine — sensor + signal + portfolio + order path), and
``DataHealth`` (gap → resume → halt → resume → corrupted) — through a
deterministic legal walk, emitting a ``StateTransition`` event per edge from
a single shared ``SequenceGenerator`` (mirroring the orchestrator, which
publishes one StateTransition stream).  The hash therefore pins:

* which edges fire and in what order (driving an illegal edge raises
  ``IllegalTransition`` and fails the replay, so the real transition tables
  are load-bearing here, not a permissive mock),
* the global ``sequence`` allocation across machines, and
* the per-edge ``machine_name`` / ``from_state`` / ``to_state`` / ``trigger``.

Timestamps come from an injected :class:`SimulatedClock` advanced
deterministically, so the stream is bit-identical across replays (Inv-5).
"""

from __future__ import annotations

import hashlib

from feelies.core.clock import SimulatedClock
from feelies.core.events import StateTransition
from feelies.core.identifiers import SequenceGenerator
from feelies.core.state_machine import IllegalTransition, TransitionRecord
from feelies.execution.order_state import OrderState, create_order_state_machine
from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine
from feelies.kernel.macro import MacroState, create_macro_state_machine
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine

_BASE_TS = 1_700_000_000_000_000_000
_DT_NS = 1_000_000_000


def _hash_transition_stream(transitions: list[StateTransition]) -> str:
    lines: list[str] = []
    for s in transitions:
        lines.append(
            f"{s.sequence}|{s.machine_name}|{s.from_state}|{s.to_state}|"
            f"{s.trigger}|{s.timestamp_ns}|{sorted(s.metadata.items())}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _replay() -> tuple[str, int]:
    clock = SimulatedClock(start_ns=_BASE_TS)
    seq = SequenceGenerator()
    captured: list[StateTransition] = []

    def _emit(record: TransitionRecord) -> None:
        captured.append(
            StateTransition(
                timestamp_ns=record.timestamp_ns,
                correlation_id=record.correlation_id,
                sequence=seq.next(),
                machine_name=record.machine_name,
                from_state=record.from_state,
                to_state=record.to_state,
                trigger=record.trigger,
                metadata=dict(record.metadata),
            )
        )

    risk = create_risk_escalation_machine(clock)
    risk.on_transition(_emit)
    order_a = create_order_state_machine("A", clock)
    order_a.on_transition(_emit)
    order_b = create_order_state_machine("B", clock)
    order_b.on_transition(_emit)
    order_c = create_order_state_machine("C", clock)
    order_c.on_transition(_emit)
    macro = create_macro_state_machine(clock)
    macro.on_transition(_emit)
    micro = create_micro_state_machine(clock)
    micro.on_transition(_emit)
    data_health = create_data_integrity_machine("AAPL", clock)
    data_health.on_transition(_emit)

    t = _BASE_TS

    def step(machine, target, trigger):  # type: ignore[no-untyped-def]
        nonlocal t
        t += _DT_NS
        clock.set_time(t)
        machine.transition(target, trigger=trigger)

    # RiskLevel: full escalation then the single sanctioned R4 → R0 unlock.
    step(risk, RiskLevel.WARNING, "drawdown_warn")
    step(risk, RiskLevel.BREACH_DETECTED, "limit_breach")
    step(risk, RiskLevel.FORCED_FLATTEN, "auto_flatten")
    step(risk, RiskLevel.LOCKED, "kill_switch")
    step(risk, RiskLevel.NORMAL, "human_unlock")

    # OrderState A: acknowledged → two partials → fully filled.
    step(order_a, OrderState.SUBMITTED, "submit")
    step(order_a, OrderState.ACKNOWLEDGED, "ack")
    step(order_a, OrderState.PARTIALLY_FILLED, "partial_fill")
    step(order_a, OrderState.PARTIALLY_FILLED, "partial_fill")
    step(order_a, OrderState.FILLED, "fill")

    # OrderState B: client cancel of an acknowledged order.
    step(order_b, OrderState.SUBMITTED, "submit")
    step(order_b, OrderState.ACKNOWLEDGED, "ack")
    step(order_b, OrderState.CANCEL_REQUESTED, "cancel_request")
    step(order_b, OrderState.CANCELLED, "cancel_confirmed")

    # OrderState C: broker reject at submit.
    step(order_c, OrderState.SUBMITTED, "submit")
    step(order_c, OrderState.REJECTED, "reject")

    # MacroState: boot → one backtest run → back to READY → SHUTDOWN.
    step(macro, MacroState.DATA_SYNC, "config_loaded")
    step(macro, MacroState.READY, "data_integrity_verified")
    step(macro, MacroState.BACKTEST_MODE, "CMD_BACKTEST")
    step(macro, MacroState.READY, "reproducibility_verified")
    step(macro, MacroState.SHUTDOWN, "CMD_SHUTDOWN")

    # MicroState: one full tick down the deepest legal spine (sensors +
    # signal + portfolio all registered; the PORTFOLIO leg walks M5-M10
    # directly from CROSS_SECTIONAL) then loops back to wait for the next
    # tick.
    step(micro, MicroState.MARKET_EVENT_RECEIVED, "tick_arrived")
    step(micro, MicroState.STATE_UPDATE, "regime_posterior_updated")
    step(micro, MicroState.SENSOR_UPDATE, "sensors_registered")
    step(micro, MicroState.HORIZON_CHECK, "scheduler_checked")
    step(micro, MicroState.HORIZON_AGGREGATE, "boundary_crossed")
    step(micro, MicroState.SIGNAL_GATE, "signal_alphas_registered")
    step(micro, MicroState.CROSS_SECTIONAL, "portfolio_alphas_registered")
    step(micro, MicroState.RISK_CHECK, "intent_flushed")
    step(micro, MicroState.ORDER_DECISION, "risk_pass_order_warranted")
    step(micro, MicroState.ORDER_SUBMIT, "check_order_pass")
    step(micro, MicroState.ORDER_ACK, "submitted")
    step(micro, MicroState.POSITION_UPDATE, "acked")
    step(micro, MicroState.LOG_AND_METRICS, "reconciled")
    step(micro, MicroState.WAITING_FOR_MARKET_EVENT, "tick_complete")

    # DataHealth: gap → resolved → halted → resumed → corrupted (terminal).
    step(data_health, DataHealth.GAP_DETECTED, "sequence_gap")
    step(data_health, DataHealth.HEALTHY, "gap_resolved")
    step(data_health, DataHealth.HALTED, "luld_halt")
    step(data_health, DataHealth.HEALTHY, "halt_resumed")
    step(data_health, DataHealth.CORRUPTED, "unrecoverable_schema_violation")

    return _hash_transition_stream(captured), len(captured)


# Locked StateTransition baseline.  Re-baseline only with an intentional
# change to a transition table or the driven walk, justified in the commit.
#
# Audit-2026-07-02 P1 #5: re-baselined to add MacroState (5 edges),
# MicroState (14 edges), and DataHealth (5 edges) to the original
# RiskLevel + OrderState walk (16 edges) — 16 + 24 = 40.
EXPECTED_STATE_TRANSITION_HASH = "3faaec4824e41ed855ef3ef1f24e7392bb242f88814c86f09be7ed976d186ba7"
EXPECTED_STATE_TRANSITION_COUNT = 40


def test_state_transition_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_STATE_TRANSITION_COUNT, (
        f"StateTransition count drift: expected {EXPECTED_STATE_TRANSITION_COUNT}, "
        f"got {actual_count}"
    )
    assert actual_hash == EXPECTED_STATE_TRANSITION_HASH, (
        "StateTransition hash drift!\n"
        f"  Expected: {EXPECTED_STATE_TRANSITION_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (transition-table or walk change), update the constant "
        "in the same commit and justify in the commit message."
    )


def test_two_replays_produce_identical_transition_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_transition_tables_are_load_bearing() -> None:
    """The walk's determinism relies on real tables — prove they reject.

    If the SMs silently permitted any edge, the baseline would pin a walk the
    platform does not actually allow.  Confirm a known-illegal edge raises.
    """
    clock = SimulatedClock(start_ns=_BASE_TS)
    risk = create_risk_escalation_machine(clock)
    # De-escalation is forbidden (Inv-11): NORMAL cannot jump straight to
    # BREACH_DETECTED, and WARNING cannot step back to NORMAL.
    try:
        risk.transition(RiskLevel.BREACH_DETECTED, trigger="skip_warning")
    except IllegalTransition:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("RiskLevel allowed NORMAL → BREACH_DETECTED (table not enforced)")


def test_all_five_state_machines_are_exercised() -> None:
    """Guard against a vacuous baseline: all five SMs must actually appear."""
    clock = SimulatedClock(start_ns=_BASE_TS)
    seq = SequenceGenerator()
    captured: list[StateTransition] = []

    def _emit(record: TransitionRecord) -> None:
        captured.append(
            StateTransition(
                timestamp_ns=record.timestamp_ns,
                correlation_id=record.correlation_id,
                sequence=seq.next(),
                machine_name=record.machine_name,
                from_state=record.from_state,
                to_state=record.to_state,
                trigger=record.trigger,
                metadata=dict(record.metadata),
            )
        )

    risk = create_risk_escalation_machine(clock)
    risk.on_transition(_emit)
    order_a = create_order_state_machine("A", clock)
    order_a.on_transition(_emit)
    macro = create_macro_state_machine(clock)
    macro.on_transition(_emit)
    micro = create_micro_state_machine(clock)
    micro.on_transition(_emit)
    data_health = create_data_integrity_machine("AAPL", clock)
    data_health.on_transition(_emit)

    risk.transition(RiskLevel.WARNING, trigger="t")
    order_a.transition(OrderState.SUBMITTED, trigger="t")
    macro.transition(MacroState.DATA_SYNC, trigger="t")
    micro.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="t")
    data_health.transition(DataHealth.GAP_DETECTED, trigger="t")

    names = {s.machine_name for s in captured}
    assert len(names) == 5, f"expected exactly five distinct machine names, got {names}"
