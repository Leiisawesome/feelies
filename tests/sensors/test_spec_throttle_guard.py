"""SensorSpec throttle/stateful guard (audit P1-D).

A non-null ``throttled_ms`` on a sensor NOT marked ``stateful`` is the
documented "undefined behaviour" combination: the registry skips ``update()``
inside the throttle window, which biases any accumulator (EWMA/Hawkes/Kyle/
rolling-window).  The spec cannot detect whether ``cls`` is an accumulator, so
it cannot reject the combination outright (a truly stateless sensor is safe to
throttle) — but it must surface it loudly unless the operator affirms
non-accumulator semantics via ``stateless_throttle_ok`` (YAML: explicit
``stateful: false`` beside ``throttled_ms``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

from feelies.core.events import NBBOQuote
from feelies.core.platform_config import PlatformConfig
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


def test_throttled_stateless_acknowledged_does_not_warn(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="feelies.sensors.spec"):
        SensorSpec(
            sensor_id="dummy",
            sensor_version="1.0.0",
            cls=_DummySensor,
            subscribes_to=(NBBOQuote,),
            throttled_ms=100,
            stateful=False,
            stateless_throttle_ok=True,
        )
    assert not any("throttled_ms" in r.message for r in caplog.records)


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


def test_yaml_explicit_stateful_false_with_throttle_is_quiet(
    tmp_path: Path, caplog
) -> None:
    """platform.yaml's scheduled_flow_window pattern must not warn."""
    yaml_text = dedent(
        """
        symbols: [APP]
        mode: BACKTEST
        alpha_specs: ["dummy.alpha.yaml"]
        horizons_seconds: [30, 120]
        sensor_specs:
          - sensor_id: scheduled_flow_window
            sensor_version: "1.2.0"
            cls: feelies.sensors.impl.scheduled_flow_window.ScheduledFlowWindowSensor
            params: {}
            subscribes_to: [NBBOQuote]
            throttled_ms: 1000
            stateful: false
        """
    ).strip()
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = PlatformConfig.from_yaml(path)
    spec = cfg.sensor_specs[0]
    assert spec.throttled_ms == 1000
    assert spec.stateful is False
    assert spec.stateless_throttle_ok is True
    assert not any("throttled_ms" in r.message for r in caplog.records)


def test_yaml_omitted_stateful_with_throttle_still_warns(tmp_path: Path, caplog) -> None:
    yaml_text = dedent(
        """
        symbols: [APP]
        mode: BACKTEST
        alpha_specs: ["dummy.alpha.yaml"]
        horizons_seconds: [30, 120]
        sensor_specs:
          - sensor_id: ofi_ewma
            sensor_version: "1.1.0"
            cls: feelies.sensors.impl.ofi_ewma.OFIEwmaSensor
            params: {alpha: 0.1}
            subscribes_to: [NBBOQuote]
            throttled_ms: 100
        """
    ).strip()
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="feelies.sensors.spec"):
        cfg = PlatformConfig.from_yaml(path)
    assert cfg.sensor_specs[0].stateless_throttle_ok is False
    assert any(
        "throttled_ms" in r.message and "stateful=False" in r.message for r in caplog.records
    )
