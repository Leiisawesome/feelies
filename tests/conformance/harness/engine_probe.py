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

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from feelies.bus.event_bus import EventBus
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


class EngineProbe:
    """Records the book for each watched symbol at every published event.

    Symbols are watched explicitly rather than taken from
    :meth:`PositionStore.all_positions`, which reports only symbols that
    have been touched.  A test asserting that nothing moved would otherwise
    iterate an empty mapping and pass without observing anything.
    """

    def __init__(self, *, positions: PositionStore, symbols: Sequence[str]) -> None:
        self._positions = positions
        self._symbols = tuple(symbols)
        self._samples: list[BookSample] = []
        self._event_count = 0

    def attach(self, bus: EventBus) -> None:
        bus.subscribe_all(self._on_event)

    @property
    def samples(self) -> tuple[BookSample, ...]:
        return tuple(self._samples)

    @property
    def event_count(self) -> int:
        """Events seen since attach — distinguishes "nothing moved" from "nothing ran"."""
        return self._event_count

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
