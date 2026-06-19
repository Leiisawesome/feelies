"""Institutional-grade robustness guards (audit 3P-1, 3P-2)."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, SensorReading, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.impl.liquidity_stress_score import LiquidityStressScoreSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.ofi_raw import OFIRawSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

_NS = 1_000_000_000


def _quote(bid: float, ask: float, *, ts: int = _NS, bid_sz: int = 100, ask_sz: int = 100) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=bid_sz,
        ask_size=ask_sz,
        exchange_timestamp_ns=ts,
    )


# ── 3P-1: registry suppresses non-finite emissions ──────────────────────────


class _BadSensor:
    """Sensor that emits a configurable non-finite value."""

    sensor_id = "bad"
    sensor_version = "1.0.0"

    def __init__(self, *, value: Any = float("nan")) -> None:
        self._value = value

    def initial_state(self) -> dict[str, Any]:
        return {}

    def update(
        self, event: NBBOQuote | Trade, state: dict[str, Any], params: Mapping[str, Any]
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None
        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=self._value,
            warm=True,
        )


def _registry_with(value: Any) -> tuple[EventBus, list[SensorReading]]:
    bus = EventBus()
    readings: list[SensorReading] = []
    bus.subscribe(SensorReading, readings.append)
    reg = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({"AAPL"})
    )
    reg.register(
        SensorSpec(
            sensor_id="bad",
            sensor_version="1.0.0",
            cls=_BadSensor,
            params={"value": value},
            subscribes_to=(NBBOQuote,),
        )
    )
    return bus, readings


def test_registry_suppresses_nan_scalar() -> None:
    bus, readings = _registry_with(float("nan"))
    bus.publish(_quote(100.00, 100.01))
    assert readings == []  # poison never reaches the bus


def test_registry_suppresses_inf_scalar() -> None:
    bus, readings = _registry_with(float("inf"))
    bus.publish(_quote(100.00, 100.01))
    assert readings == []


def test_registry_suppresses_nan_tuple_component() -> None:
    bus, readings = _registry_with((1.0, float("nan"), 0.5))
    bus.publish(_quote(100.00, 100.01))
    assert readings == []


def test_registry_publishes_finite_value() -> None:
    bus, readings = _registry_with(0.42)
    bus.publish(_quote(100.00, 100.01))
    assert len(readings) == 1 and readings[0].value == 0.42


# ── 3P-2: crossed-book rejection ────────────────────────────────────────────


def test_price_sensors_reject_crossed_book() -> None:
    crossed = _quote(100.05, 100.01)  # bid > ask
    for sensor in (
        SpreadZScoreSensor(window=4),
        MicroPriceSensor(),
        LiquidityStressScoreSensor(window=4),
        OFIEwmaSensor(),
        OFIRawSensor(),
    ):
        st = sensor.initial_state()
        # Seed a valid quote first so the sensor has prior state to protect.
        sensor.update(_quote(100.00, 100.01, ts=_NS), st, {})
        out = sensor.update(crossed, st, {"ts": 2 * _NS})
        assert out is None, f"{type(sensor).__name__} did not reject a crossed book"


def test_locked_book_is_allowed() -> None:
    # Locked (bid == ask) is not crossed; spread-z still processes it.
    s = SpreadZScoreSensor(window=4, warm_after=1)
    st = s.initial_state()
    s.update(_quote(100.00, 100.01), st, {})
    out = s.update(_quote(100.01, 100.01, ts=2 * _NS), st, {})  # locked, spread 0
    assert out is not None and math.isfinite(out.value)
