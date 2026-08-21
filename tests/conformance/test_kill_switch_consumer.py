"""X9 — KillSwitchActivation is fail-closed, durable, and observable.

G28: the event is published so all layers can react, but it has zero
subscribers. The consumer is additive: an observer that records and
alerts. The four direct kill-switch reads on the orchestrator are the
control; they must still refuse without bus delivery of this event.
"""

from __future__ import annotations

from feelies.bootstrap import build_platform
from feelies.core.errors import SessionEntryBlockedError
from feelies.core.events import KillSwitchActivation
from feelies.monitoring.in_memory import InMemoryKillSwitch
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.integration.test_phase4_e2e import (
    _make_phase4_config,
    _synth_multi_symbol_events,
)


def _platform():
    config = _make_phase4_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_multi_symbol_events())
    orchestrator, resolved = build_platform(config, event_log=event_log)
    return orchestrator, resolved


def test_x9_kill_switch_activation_has_a_consumer() -> None:
    orchestrator, _cfg = _platform()
    handlers = orchestrator._bus._handlers.get(KillSwitchActivation, ())
    assert handlers, (
        "KillSwitchActivation has no subscriber; G28 is still inert"
    )


def test_x9_kill_switch_is_fail_closed_without_bus_delivery() -> None:
    """Direct reads still halt; the observer is not the control path."""
    orchestrator, config = _platform()
    orchestrator.boot(config)
    ks = orchestrator.kill_switch
    assert ks is not None
    ks.activate("x9-fail-closed", activated_by="conformance")
    # No KillSwitchActivation is published. Session entry must still refuse.
    assert ks.is_active
    try:
        orchestrator.run_backtest()
    except SessionEntryBlockedError as exc:
        assert "kill switch" in str(exc).lower()
        return
    raise AssertionError(
        "kill switch did not fail-closed on the direct read "
        "(session started without KillSwitchActivation on the bus)"
    )


def test_x9_kill_switch_activation_is_durable() -> None:
    ks = InMemoryKillSwitch()
    ks.activate("x9-durable", activated_by="conformance")
    assert ks.is_active
    assert ks.history, "kill switch activation left no durable audit record"
    rec = ks.history[-1]
    assert rec.action == "activate"
    assert rec.reason == "x9-durable"
    assert rec.actor == "conformance"


def test_x9_kill_switch_activation_is_observable() -> None:
    orchestrator, _cfg = _platform()
    seen: list[KillSwitchActivation] = []
    handlers = list(orchestrator._bus._handlers.get(KillSwitchActivation, ()))
    assert handlers, "KillSwitchActivation has no subscriber; not observable"

    def _tap(event: KillSwitchActivation) -> None:
        seen.append(event)

    # The production consumer must run; the tap only witnesses delivery.
    orchestrator._bus.subscribe(KillSwitchActivation, _tap)
    event = KillSwitchActivation(
        timestamp_ns=1,
        correlation_id="x9-obs",
        sequence=1,
        reason="x9-observable",
        activated_by="conformance",
    )
    orchestrator._bus.publish(event)
    assert seen == [event], (
        "KillSwitchActivation was published but the consumer did not observe it"
    )
