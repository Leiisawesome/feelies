"""SensorSpec throttle/stateful guard (audit P1-D).

A non-null ``throttled_ms`` on a sensor NOT marked ``stateful`` is the
documented "undefined behaviour" combination: the registry skips ``update()``
inside the throttle window, which biases any accumulator (EWMA/Hawkes/Kyle/
rolling-window).  The spec cannot detect whether ``cls`` is an accumulator, so
it cannot reject the combination outright (a truly stateless sensor is safe to
throttle) — but it must surface it loudly.
"""

from __future__ import annotations

import logging

from feelies.core.events import NBBOQuote
from feelies.sensors.spec import SensorSpec


class _DummySensor:
    sensor_id = "dummy"
    sensor_version = "1.0.0"

    def initial_state(self) -> dict:
        return {}

    def update(self, event, state, params):  # pragma: no cover - not invoked here
        return None


def test_throttled_stateless_spec_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="feelies.sensors.spec"):
        SensorSpec(
            sensor_id="dummy",
            sensor_version="1.0.0",
            cls=_DummySensor,
            subscribes_to=(NBBOQuote,),
            throttled_ms=100,
            stateful=False,
        )
    assert any(
        "throttled_ms" in r.message and "stateful=False" in r.message for r in caplog.records
    )


def test_throttled_stateful_spec_does_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="feelies.sensors.spec"):
        SensorSpec(
            sensor_id="dummy",
            sensor_version="1.0.0",
            cls=_DummySensor,
            subscribes_to=(NBBOQuote,),
            throttled_ms=100,
            stateful=True,
        )
    assert not any("throttled_ms" in r.message for r in caplog.records)


def test_unthrottled_spec_does_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="feelies.sensors.spec"):
        SensorSpec(
            sensor_id="dummy",
            sensor_version="1.0.0",
            cls=_DummySensor,
            subscribes_to=(NBBOQuote,),
            throttled_ms=None,
            stateful=False,
        )
    assert not any("throttled_ms" in r.message for r in caplog.records)
