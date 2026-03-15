from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.events import Event, NBBOQuote


@dataclass(frozen=True, kw_only=True)
class AlphaEvent(Event):
    value: float


@dataclass(frozen=True, kw_only=True)
class BetaEvent(Event):
    label: str


def _make_alpha(value: float = 1.0) -> AlphaEvent:
    return AlphaEvent(timestamp_ns=1000, correlation_id="c1", sequence=1, value=value)


def _make_beta(label: str = "b") -> BetaEvent:
    return BetaEvent(timestamp_ns=2000, correlation_id="c2", sequence=2, label=label)


class TestEventBus:
    def test_subscribe_and_publish_routes_to_correct_handler(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(AlphaEvent, received.append)

        event = _make_alpha()
        bus.publish(event)

        assert received == [event]

    def test_multiple_handlers_called_in_registration_order(self):
        bus = EventBus()
        order: list[int] = []

        bus.subscribe(AlphaEvent, lambda _: order.append(1))
        bus.subscribe(AlphaEvent, lambda _: order.append(2))
        bus.subscribe(AlphaEvent, lambda _: order.append(3))

        bus.publish(_make_alpha())
        assert order == [1, 2, 3]

    def test_subscribe_all_receives_all_event_types(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe_all(received.append)

        alpha = _make_alpha()
        beta = _make_beta()
        bus.publish(alpha)
        bus.publish(beta)

        assert received == [alpha, beta]

    def test_type_specific_handlers_before_global_handlers(self):
        bus = EventBus()
        order: list[str] = []

        bus.subscribe(AlphaEvent, lambda _: order.append("typed"))
        bus.subscribe_all(lambda _: order.append("global"))

        bus.publish(_make_alpha())
        assert order == ["typed", "global"]

    def test_publish_with_no_subscribers_is_noop(self):
        bus = EventBus()
        bus.publish(_make_alpha())

    def test_handler_exception_propagates_to_caller(self):
        bus = EventBus()
        bus.subscribe(AlphaEvent, lambda _: (_ for _ in ()).throw(ValueError("boom")))

        def boom(_: Event) -> None:
            raise ValueError("boom")

        bus.subscribe(AlphaEvent, boom)

        with pytest.raises(ValueError, match="boom"):
            bus.publish(_make_alpha())

    def test_different_event_types_routed_independently(self):
        bus = EventBus()
        alphas: list[Event] = []
        betas: list[Event] = []

        bus.subscribe(AlphaEvent, alphas.append)
        bus.subscribe(BetaEvent, betas.append)

        alpha = _make_alpha()
        beta = _make_beta()
        bus.publish(alpha)
        bus.publish(beta)

        assert alphas == [alpha]
        assert betas == [beta]

    def test_global_handler_receives_nbbo_quote(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe_all(received.append)

        quote = NBBOQuote(
            timestamp_ns=100,
            correlation_id="q1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("149.99"),
            ask=Decimal("150.01"),
            bid_size=100,
            ask_size=200,
            exchange_timestamp_ns=99,
        )
        bus.publish(quote)

        assert len(received) == 1
        assert received[0] is quote
