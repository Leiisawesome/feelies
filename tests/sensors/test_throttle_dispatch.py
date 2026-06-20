"""Stateful vs non-stateful throttle dispatch semantics (external-review follow-up).

The ``SensorSpec.stateful`` flag changes how the registry behaves *inside* a
throttle window:

- ``stateful=True``  — ``update()`` is called on **every** event (so an
  accumulator's state stays unbiased) while emission is rate-limited.
- ``stateful=False`` — ``update()`` is **skipped** entirely inside the window
  (cheap; correct only for a truly stateless sensor).

No active spec sets ``throttled_ms`` today, so this contract was previously
exercised only indirectly.  These golden tests lock both branches.
"""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, SensorReading
from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from tests.sensors._helpers import CountingSensor, make_quote

_MS = 1_000_000  # ns
_THROTTLE_MS = 100


def _run(*, stateful: bool) -> tuple[int, list[SensorReading]]:
    """Drive 5 quotes 10 ms apart through a throttled CountingSensor.

    Returns ``(update_call_count, emitted_readings)``.  ``CountingSensor``
    increments ``state["count"]`` once per ``update()`` call, so the registry's
    per-symbol state exposes how many times ``update()` actually ran.
    """
    bus = EventBus()
    readings: list[SensorReading] = []
    bus.subscribe(SensorReading, readings.append)
    reg = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({"AAPL"})
    )
    reg.register(
        SensorSpec(
            sensor_id="counting",
            sensor_version="1.0.0",
            cls=CountingSensor,
            subscribes_to=(NBBOQuote,),
            throttled_ms=_THROTTLE_MS,
            stateful=stateful,
        )
    )
    # 5 quotes at t = 0, 10, 20, 30, 40 ms — all within one 100 ms window.
    for i in range(5):
        bus.publish(make_quote(ts_ns=i * 10 * _MS))
    update_count = reg._state[("counting", "1.0.0", "AAPL")]["count"]
    return update_count, readings


def test_stateful_throttle_updates_every_event_emits_sparsely() -> None:
    update_count, readings = _run(stateful=True)
    # Accumulator must advance on every event so it stays unbiased ...
    assert update_count == 5
    # ... but only the first event in the window is published.
    assert len(readings) == 1
    assert readings[0].value == 1.0


def test_stateless_throttle_skips_update_inside_window() -> None:
    update_count, readings = _run(stateful=False)
    # Stateless sensor: update() is skipped entirely inside the window, so it
    # ran exactly once (the emitting event).
    assert update_count == 1
    assert len(readings) == 1
    assert readings[0].value == 1.0
