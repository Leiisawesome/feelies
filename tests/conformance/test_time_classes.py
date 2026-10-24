"""Every bus event declares TIME_CLASS, and the declaration is not a field."""

from __future__ import annotations

import inspect
from decimal import Decimal

from feelies.core.events import Event, NBBOQuote, OrderAck, OrderAckStatus
import feelies.core.events as events
from tests.position_engine.scenarios import canonical

_MARKET = frozenset(
    {
        "NBBOQuote",
        "Trade",
        "SymbolHalted",
        "Signal",
        "SafetyStateChange",
        "SensorReading",
        "HorizonTick",
        "HorizonFeatureSnapshot",
        "CrossSectionalContext",
        "SizedPositionIntent",
        "MarkRailUpdate",
    }
)
_ACTION = frozenset(
    {
        "RegimeState",
        "RiskVerdict",
        "OrderRequest",
        "DeRiskRequirement",
        "OrderAck",
        "PositionUpdate",
        "StateTransition",
        "MetricEvent",
        "Alert",
        "KillSwitchActivation",
        "LatencyBreach",
        "RegimeHazardSpike",
        "SlicePositionUpdate",
        "PositionSnapshot",
        "GateDecision",
        "PositionClosed",
    }
)


def _bus_types() -> list[type[Event]]:
    found: list[type[Event]] = []
    for name, obj in inspect.getmembers(events, inspect.isclass):
        if obj.__module__ != events.__name__:
            continue
        if issubclass(obj, Event) and obj is not Event:
            found.append(obj)
            assert name == obj.__name__
    return found


def test_every_bus_event_declares_time_class() -> None:
    """T1. Market events carry exchange time. Action events carry the clock."""
    found = {cls.__name__: cls for cls in _bus_types()}
    assert set(found) == _MARKET | _ACTION
    for name, cls in sorted(found.items()):
        expected = "market" if name in _MARKET else "action"
        assert cls.TIME_CLASS == expected, name
        assert cls.TIME_CLASS in {"market", "action"}


def test_time_class_is_not_a_field_and_canonical_omits_it() -> None:
    """TIME_CLASS is a ClassVar, so canonical() and frozen slots stay put."""
    for cls in _bus_types():
        assert "TIME_CLASS" not in cls.__dataclass_fields__, cls.__name__
        params = cls.__dataclass_params__
        assert params.frozen, cls.__name__
        assert params.slots, cls.__name__
        assert cls.TIME_CLASS in {"market", "action"}

    quote = NBBOQuote(
        timestamp_ns=1,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("1"),
        ask=Decimal("2"),
        bid_size=1,
        ask_size=1,
        exchange_timestamp_ns=1,
    )
    ack = OrderAck(
        timestamp_ns=1,
        correlation_id="a",
        sequence=1,
        order_id="o",
        symbol="AAPL",
        status=OrderAckStatus.ACKNOWLEDGED,
    )
    for event in (quote, ack):
        text = canonical(event)
        assert "TIME_CLASS" not in text
        assert "timestamp_ns" in text
