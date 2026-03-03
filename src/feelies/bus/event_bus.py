"""Synchronous, deterministic event bus (invariant 7).

All inter-layer communication flows through typed events on this bus.
Synchronous delivery guarantees deterministic ordering for replay.

Tradeoff: synchronous dispatch sacrifices throughput for determinism.
The critical tick-to-trade path uses direct method calls through the
orchestrator for maximum performance; the bus carries cross-cutting
events (metrics, state transitions, alerts) and serves as the audit
spine for observability.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from feelies.core.events import Event

EventHandler = Callable[[Event], None]


class EventBus:
    """Central event routing with deterministic delivery order.

    Handlers for a given event type are called in registration order.
    No parallel dispatch.  No event reordering.  Exceptions in handlers
    propagate immediately — fail-fast, not fail-silent.
    """

    __slots__ = ("_handlers", "_global_handlers")

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def subscribe(
        self,
        event_type: type[Event],
        handler: EventHandler,
    ) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives every event (logging, metrics)."""
        self._global_handlers.append(handler)

    def publish(self, event: Event) -> None:
        """Dispatch event to all registered handlers synchronously.

        Order: type-specific handlers (registration order),
        then global handlers (registration order).
        """
        for handler in self._handlers.get(type(event), []):
            handler(event)
        for handler in self._global_handlers:
            handler(event)
