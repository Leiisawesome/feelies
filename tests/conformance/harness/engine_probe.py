"""HARN-1 — engine probe.

Observes engine state at every event of a replay rather than only at the
end.  A closing-book assertion cannot see a position that opens and closes
inside the run; conformance tests that assert an identity "at every event"
need a per-event record to assert over.

The probe reads through the bus's global handler chain, which
:meth:`feelies.bus.event_bus.EventBus.publish` dispatches *after* the
type-specific handlers.  Each sample is therefore the engine's state as of
that event having been processed, not before it.

Read-only by construction: the probe subscribes and records, and never
publishes, mutates engine state, or reads a clock.  Attaching it to a
replay must not change the replay.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from feelies.bus.event_bus import EventBus, EventHandler
from feelies.core.events import Event
from feelies.portfolio.position_store import PositionStore


@dataclass(frozen=True)
class BookSample:
    """One symbol's book state as of one event."""

    event_index: int
    event_type: str
    symbol: str
    quantity: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class FactRead:
    """One instrumented engine read of a bus fact during a replay."""

    engine: str
    kind: str
    fact: str
    event_index: int


class EngineProbe:
    """Records the book for each watched symbol at every published event.

    Symbols are watched explicitly rather than taken from
    :meth:`PositionStore.all_positions`, which reports only symbols that
    have been touched.  A test asserting that nothing moved would otherwise
    iterate an empty mapping and pass without observing anything.

    When ``engine_modules`` is non-empty, attach also wraps each type-specific
    bus handler whose owner lives in one of those packages and records the
    (engine, event-type) read.  Wrappers call the original handler unchanged.
    """

    def __init__(
        self,
        *,
        positions: PositionStore,
        symbols: Sequence[str],
        engine_modules: Sequence[str] = (),
    ) -> None:
        self._positions = positions
        self._symbols = tuple(symbols)
        self._engine_modules = tuple(engine_modules)
        self._samples: list[BookSample] = []
        self._fact_reads: list[FactRead] = []
        self._event_count = 0

    def attach(self, bus: EventBus) -> None:
        if self._engine_modules:
            self._instrument_read_surface(bus)
        bus.subscribe_all(self._on_event)

    @property
    def samples(self) -> tuple[BookSample, ...]:
        return tuple(self._samples)

    @property
    def fact_reads(self) -> tuple[FactRead, ...]:
        return tuple(self._fact_reads)

    @property
    def event_count(self) -> int:
        """Events seen since attach — distinguishes "nothing moved" from "nothing ran"."""
        return self._event_count

    def _engine_for(self, handler: Callable[..., object]) -> str | None:
        owner = getattr(handler, "__self__", None)
        if owner is None:
            return None
        mod = type(owner).__module__
        for engine in self._engine_modules:
            if mod == engine or mod.startswith(engine + "."):
                return engine
        return None

    def _wrap_handler(
        self, event_type: type[Event], handler: EventHandler
    ) -> EventHandler:
        engine = self._engine_for(handler)
        fact = event_type.__name__

        def wrapped(event: Event) -> None:
            if engine is not None:
                self._fact_reads.append(
                    FactRead(
                        engine=engine,
                        kind="event",
                        fact=fact,
                        event_index=self._event_count,
                    )
                )
            handler(event)

        return wrapped

    def _instrument_read_surface(self, bus: EventBus) -> None:
        for event_type, handlers in list(bus._handlers.items()):
            bus._handlers[event_type] = [
                self._wrap_handler(event_type, handler) for handler in handlers
            ]

    def _on_event(self, event: Event) -> None:
        index = self._event_count
        self._event_count += 1
        event_type = type(event).__name__
        for symbol in self._symbols:
            position = self._positions.get(symbol)
            self._samples.append(
                BookSample(
                    event_index=index,
                    event_type=event_type,
                    symbol=symbol,
                    quantity=position.quantity,
                    realized_pnl=position.realized_pnl,
                    unrealized_pnl=position.unrealized_pnl,
                )
            )
