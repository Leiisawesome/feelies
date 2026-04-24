"""Tests for the Sensor Protocol contract."""

from __future__ import annotations

from feelies.sensors.protocol import Sensor
from tests.sensors._helpers import CountingSensor


def test_counting_sensor_satisfies_sensor_protocol() -> None:
    sensor = CountingSensor()
    assert isinstance(sensor, Sensor)


def test_sensor_required_attrs_present() -> None:
    sensor = CountingSensor(sensor_id="foo", sensor_version="2.0.0")
    assert sensor.sensor_id == "foo"
    assert sensor.sensor_version == "2.0.0"


def test_sensor_initial_state_returns_independent_dict() -> None:
    sensor = CountingSensor()
    s1 = sensor.initial_state()
    s2 = sensor.initial_state()
    s1["count"] = 99
    assert s2["count"] == 0
