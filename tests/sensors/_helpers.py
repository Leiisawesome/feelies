"""Shared sensor-test helpers.

A minimal in-test ``Sensor`` implementation reused across registry,
scheduler, and orchestrator tests.  Lives outside the ``tests/sensors``
namespace package so pytest does not collect it as a test module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, SensorReading, Trade


class CountingSensor:
    """Trivial sensor: returns the running event count as a float.

    Used to verify dispatch ordering, throttling, and provenance
    propagation without coupling to any real sensor implementation.
    """

    sensor_id: str = "counting"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        warm_after: int = 0,
    ) -> None:
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self.warm_after = warm_after

    def initial_state(self) -> dict[str, Any]:
        return {"count": 0}

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorReading | None:
        state["count"] += 1
        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",  # registry overwrites
            sequence=-1,                   # registry overwrites
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=float(state["count"]),
            warm=state["count"] >= self.warm_after,
        )


def make_quote(*, symbol: str = "AAPL", ts_ns: int = 1_000_000_000) -> NBBOQuote:
    """Helper: build a minimal ``NBBOQuote`` for tests."""
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{symbol}-{ts_ns}",
        sequence=ts_ns,
        symbol=symbol,
        bid=Decimal("100.00"),
        ask=Decimal("100.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def make_trade(*, symbol: str = "AAPL", ts_ns: int = 1_000_000_001) -> Trade:
    """Helper: build a minimal ``Trade`` for tests."""
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{symbol}-{ts_ns}",
        sequence=ts_ns,
        symbol=symbol,
        price=Decimal("100.00"),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )
