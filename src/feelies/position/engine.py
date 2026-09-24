"""P-10 STUB. Cell advance and gates land in P-50/P-60. contracts.md §2."""

from __future__ import annotations

from collections.abc import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.exit_policy import ExitPolicy
from feelies.core.events import (
    GateDecision,
    MarkRailUpdate,
    PositionClosed,
    PositionSnapshot,
    SlicePositionUpdate,
)
from feelies.core.identifiers import SequenceGenerator


class PositionEngine:
    """Subscribes the rail and the slice stream. Handlers are no-ops until P-50/P-60."""

    def __init__(
        self,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        policies: Mapping[str, ExitPolicy] | None = None,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self.policies: dict[str, ExitPolicy] = dict(policies or {})

    def attach(self) -> None:
        self._bus.subscribe(MarkRailUpdate, self._on_mark_rail)
        self._bus.subscribe(SlicePositionUpdate, self._on_slice_update)

    def _on_mark_rail(self, event: MarkRailUpdate) -> None:
        """P-50/P-60. P-10 stub."""
        del event

    def _on_slice_update(self, event: SlicePositionUpdate) -> None:
        """P-50/P-60. P-10 stub."""
        del event


class PositionRecordSink:
    """Records snapshot, gate, and close events. Holds no bus publish path."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.snapshots: list[PositionSnapshot] = []
        self.gate_decisions: list[GateDecision] = []
        self.closed: list[PositionClosed] = []

    def attach(self) -> None:
        self._bus.subscribe(PositionSnapshot, self._on_snapshot)
        self._bus.subscribe(GateDecision, self._on_gate_decision)
        self._bus.subscribe(PositionClosed, self._on_closed)

    def _on_snapshot(self, event: PositionSnapshot) -> None:
        self.snapshots.append(event)

    def _on_gate_decision(self, event: GateDecision) -> None:
        self.gate_decisions.append(event)

    def _on_closed(self, event: PositionClosed) -> None:
        self.closed.append(event)
