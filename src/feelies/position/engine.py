"""Stage-B position skeleton. contracts.md §2 and §8. Birth formula is P-50."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.events import (
    Event,
    DeRiskRequirement,
    GateDecision,
    MarkRailUpdate,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    PositionSnapshot,
    RailOrientation,
    Signal,
    SignalDirection,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import ExitPolicy
from feelies.core.identifiers import SequenceGenerator

# Integer stand-in for formula fields P-50 evaluates. Never NaN. AS-17.
_FORMULA_PLACEHOLDER = 0
_CONTRACT_GATE_ORDER = ("ADVERSE", "FAVORABLE")


@dataclass(frozen=True, slots=True)
class _Cell:
    """One open episode. Replaced on update; the engine stores the new value."""

    cell_id: str
    symbol: str
    strategy_id: str
    side: str
    archetype: str
    order_id: str
    uncalibrated: bool
    size: int = 0
    entry_cost_cents: int = 0
    entry_fills: tuple[PositionFillLeg, ...] = ()
    exit_fills: tuple[PositionFillLeg, ...] = ()
    best: PositionExtreme | None = None
    worst: PositionExtreme | None = None
    best_clean: PositionExtreme | None = None
    invalidation_sequence: int | None = None
    lived_through_feed_gap: bool = False
    correlation_id: str = ""


def _cents(price: Decimal) -> int:
    """D-78. A fractional cent is corrupt and raises."""
    scaled = price * 100
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ValueError(f"fractional cent {price}")
    return int(integral)


def _sign(side: str) -> int:
    return 1 if side == "LONG" else -1


def _move(sign: int, mark: int | None, size: int, entry_cost_cents: int) -> int | None:
    """D-99. None exactly when the mark is None."""
    if mark is None:
        return None
    return sign * (mark * size - entry_cost_cents)


def _extreme(cents: int, rail: MarkRailUpdate, orient: RailOrientation) -> PositionExtreme:
    return PositionExtreme(
        cents=cents,
        sequence=rail.quote_sequence,
        valuation_age_ns=orient.valuation_age_ns,
        valuation_side_absent=orient.valuation_side_absent,
        crossed=rail.crossed,
        feed_gap_before=rail.feed_gap_before,
    )


def _clean(rail: MarkRailUpdate, orient: RailOrientation) -> bool:
    return (
        orient.valuation_side_absent is False
        and rail.crossed is False
        and rail.feed_gap_before is False
    )


def _leg(event: SlicePositionUpdate, quantity: int) -> PositionFillLeg:
    return PositionFillLeg(
        price_cents=_cents(event.fill_price),
        quantity=quantity,
        timestamp_ns=event.fill_timestamp_ns,
        sequence=event.fill_ack_sequence,
    )


class PositionEngine:
    """Stub cell, stub gates, two-phase step. No DeRiskRequirement."""

    PUBLICATIONS = (PositionSnapshot, GateDecision, PositionClosed, DeRiskRequirement)

    def __init__(
        self,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        policies: Mapping[str, ExitPolicy] | None = None,
        *,
        clock: Clock,
        gate_order: tuple[str, ...] = _CONTRACT_GATE_ORDER,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._clock = clock
        self.policies: dict[str, ExitPolicy] = dict(policies or {})
        self._gate_order = gate_order
        self._open: dict[tuple[str, str], _Cell] = {}
        self._born: dict[tuple[str, str, int], int] = {}

    def attach(self) -> None:
        self._bus.subscribe(MarkRailUpdate, self._on_mark_rail)
        self._bus.subscribe(SlicePositionUpdate, self._on_slice_update)
        self._bus.subscribe(Signal, self._on_signal)

    def _on_signal(self, event: Signal) -> None:
        cell = self._open.get((event.strategy_id, event.symbol))
        if cell is None:
            return
        opposite = (
            event.direction is SignalDirection.FLAT
            or (cell.side == "LONG" and event.direction is SignalDirection.SHORT)
            or (cell.side == "SHORT" and event.direction is SignalDirection.LONG)
        )
        if opposite:
            self._put(replace(cell, invalidation_sequence=event.sequence))

    def _on_slice_update(self, event: SlicePositionUpdate) -> None:
        policy = self.policies.get(event.strategy_id)
        if policy is None or event.fill_quantity == 0:
            return
        key = (event.strategy_id, event.symbol)
        cell = self._open.get(key)
        incoming = "LONG" if event.fill_quantity > 0 else "SHORT"
        shares = abs(event.fill_quantity)
        if cell is None:
            if event.quantity == 0:
                return
            self._birth(event, policy, incoming, shares)
            return
        if incoming == cell.side:
            if event.order_id == cell.order_id:
                self._put(self._extend(cell, event, shares))
            return
        overlap = shares if shares < cell.size else cell.size
        excess = shares - overlap
        if overlap > 0:
            cell = replace(
                cell,
                exit_fills=(*cell.exit_fills, _leg(event, overlap)),
                size=cell.size - overlap,
            )
        if cell.size == 0:
            self._open.pop(key, None)
            self._publish_closed(cell, "EXTERNAL:SIGN_FLIP")
        elif overlap > 0:
            self._put(cell)
        if excess > 0:
            self._birth(event, policy, incoming, excess)

    def _on_mark_rail(self, event: MarkRailUpdate) -> None:
        cells = [cell for cell in self._open.values() if cell.symbol == event.symbol]
        for cell in sorted(cells, key=lambda item: item.cell_id):
            if event.feed_gap_before:
                cell = replace(cell, lived_through_feed_gap=True)
            snapshot = self._snapshot(cell, event)
            cell = self._note_extremes(cell, snapshot, event)
            frozen = self._with_extremes(snapshot, cell)
            self._publish(frozen)
            outcomes = {name: self._gate_outcome(name) for name in self._gate_order}
            for name in _CONTRACT_GATE_ORDER:
                outcome = outcomes.get(name)
                if outcome is not None:
                    self._publish(self._gate(name, cell, frozen, event, outcome))
            self._put(replace(cell, invalidation_sequence=None))

    def _birth(
        self,
        event: SlicePositionUpdate,
        policy: ExitPolicy,
        side: str,
        shares: int,
    ) -> None:
        stamp = event.fill_timestamp_ns
        key = (event.symbol, event.strategy_id, stamp)
        ordinal = self._born.get(key, 0)
        self._born[key] = ordinal + 1
        cell_id = f"{event.symbol}|{event.strategy_id}|{stamp}|{side}"
        if ordinal >= 1:
            cell_id = f"{cell_id}|{ordinal}"
        cell = _Cell(
            cell_id=cell_id,
            symbol=event.symbol,
            strategy_id=event.strategy_id,
            side=side,
            archetype=policy.archetype,
            order_id=event.order_id,
            uncalibrated=policy.curve_ref == "ARBITRARY_NOT_CALIBRATED",
        )
        self._put(self._extend(cell, event, shares))

    def _put(self, cell: _Cell) -> None:
        self._open[(cell.strategy_id, cell.symbol)] = cell

    def _extend(self, cell: _Cell, event: SlicePositionUpdate, shares: int) -> _Cell:
        return replace(
            cell,
            entry_fills=(*cell.entry_fills, _leg(event, shares)),
            size=cell.size + shares,
            entry_cost_cents=cell.entry_cost_cents + _cents(event.fill_price) * shares,
            correlation_id=event.correlation_id,
        )

    def _snapshot(self, cell: _Cell, event: MarkRailUpdate) -> PositionSnapshot:
        orient = event.long if cell.side == "LONG" else event.short
        sign = _sign(cell.side)
        return PositionSnapshot(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=event.correlation_id,
            sequence=self._seq.next(),
            source_layer="position",
            cell_id=cell.cell_id,
            symbol=cell.symbol,
            strategy_id=cell.strategy_id,
            state="OPEN",
            side=cell.side,
            declared_archetype=cell.archetype,
            rail_sequence=event.quote_sequence,
            size=cell.size,
            entry_cost_cents=cell.entry_cost_cents,
            entry_spread_ticks=_FORMULA_PLACEHOLDER,
            horizon_deadline_ns=_FORMULA_PLACEHOLDER,
            move_now_cents=_move(
                sign, orient.valuation_mark_cents, cell.size, cell.entry_cost_cents
            ),
            move_worst_cents=_move(
                sign, orient.worst_side_mark_cents, cell.size, cell.entry_cost_cents
            ),
            move_forced_cents=_move(
                sign, orient.forced_exit_mark_cents, cell.size, cell.entry_cost_cents
            ),
            best=cell.best,
            worst=cell.worst,
            best_clean=cell.best_clean,
            rail=orient,
            symbol_quiet_ns=event.symbol_quiet_ns,
            locked=event.locked,
            crossed=event.crossed,
            feed_gap_before=event.feed_gap_before,
            warmed_up=event.warmed_up,
        )

    def _note_extremes(
        self,
        cell: _Cell,
        snapshot: PositionSnapshot,
        event: MarkRailUpdate,
    ) -> _Cell:
        """Seed on the first clean non-zero move. Never seed at zero (D-79, D-100)."""
        orient = snapshot.rail
        move = snapshot.move_now_cents
        if cell.best is None or cell.worst is None or cell.best_clean is None:
            if not _clean(event, orient) or move is None or move == 0:
                return cell
            seeded = _extreme(move, event, orient)
            return replace(cell, best=seeded, worst=seeded, best_clean=seeded)
        if move is None:
            return cell
        best = cell.best
        worst = cell.worst
        best_clean = cell.best_clean
        if best is None or worst is None or best_clean is None:
            return cell
        if move > best.cents:
            best = _extreme(move, event, orient)
        if move < worst.cents:
            worst = _extreme(move, event, orient)
        if _clean(event, orient) and move > best_clean.cents:
            best_clean = _extreme(move, event, orient)
        return replace(cell, best=best, worst=worst, best_clean=best_clean)

    def _with_extremes(self, snapshot: PositionSnapshot, cell: _Cell) -> PositionSnapshot:
        if (
            snapshot.best is cell.best
            and snapshot.worst is cell.worst
            and snapshot.best_clean is cell.best_clean
        ):
            return snapshot
        return PositionSnapshot(
            timestamp_ns=snapshot.timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=snapshot.sequence,
            source_layer=snapshot.source_layer,
            cell_id=snapshot.cell_id,
            symbol=snapshot.symbol,
            strategy_id=snapshot.strategy_id,
            state=snapshot.state,
            side=snapshot.side,
            declared_archetype=snapshot.declared_archetype,
            rail_sequence=snapshot.rail_sequence,
            size=snapshot.size,
            entry_cost_cents=snapshot.entry_cost_cents,
            entry_spread_ticks=snapshot.entry_spread_ticks,
            horizon_deadline_ns=snapshot.horizon_deadline_ns,
            move_now_cents=snapshot.move_now_cents,
            move_worst_cents=snapshot.move_worst_cents,
            move_forced_cents=snapshot.move_forced_cents,
            best=cell.best,
            worst=cell.worst,
            best_clean=cell.best_clean,
            rail=snapshot.rail,
            symbol_quiet_ns=snapshot.symbol_quiet_ns,
            locked=snapshot.locked,
            crossed=snapshot.crossed,
            feed_gap_before=snapshot.feed_gap_before,
            warmed_up=snapshot.warmed_up,
        )

    def _gate_outcome(self, name: str) -> str:
        """Non-acting stub. Evaluation order follows gate_order; publication does not."""
        if name == "ADVERSE":
            return "hold"
        return "none"

    def _gate(
        self,
        name: str,
        cell: _Cell,
        snapshot: PositionSnapshot,
        event: MarkRailUpdate,
        outcome: str,
    ) -> GateDecision:
        orient = snapshot.rail
        if name == "ADVERSE":
            mark = orient.forced_exit_mark_cents
            form = ""
        else:
            mark = orient.dwelled_exit_mark_cents
            policy = self.policies.get(cell.strategy_id)
            form = "" if policy is None else policy.favorable.form
        return GateDecision(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=event.correlation_id,
            sequence=self._seq.next(),
            source_layer="position",
            cell_id=cell.cell_id,
            rail_sequence=event.quote_sequence,
            gate=name,
            outcome=outcome,
            reason="",
            form=form,
            proposed_price_cents=mark if mark is not None else _FORMULA_PLACEHOLDER,
            reference_ticks=_FORMULA_PLACEHOLDER,
            reference_sequence=_FORMULA_PLACEHOLDER,
            drawn_level_ticks=_FORMULA_PLACEHOLDER,
        )

    def _publish(self, event: Event) -> None:
        self._bus.publish(event)

    def _publish_closed(self, cell: _Cell, reason: str) -> None:
        self._bus.publish(
            PositionClosed(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cell.correlation_id,
                sequence=self._seq.next(),
                source_layer="position",
                cell_id=cell.cell_id,
                symbol=cell.symbol,
                strategy_id=cell.strategy_id,
                side=cell.side,
                declared_archetype=cell.archetype,
                entry_fills=tuple(cell.entry_fills),
                exit_fills=tuple(cell.exit_fills),
                entry_spread_ticks=_FORMULA_PLACEHOLDER,
                horizon_deadline_ns=_FORMULA_PLACEHOLDER,
                drawn_level_ticks=_FORMULA_PLACEHOLDER,
                exit_reason=reason,
                triggered_paths=(),
                proposed_price_cents=None,
                best=cell.best,
                worst=cell.worst,
                best_clean=cell.best_clean,
                closed_on_stale_data=False,
                exited_on_unusable_data=False,
                lived_through_feed_gap=cell.lived_through_feed_gap,
                first_event_exit=False,
                stop_inside_round_trip=False,
                target_inside_round_trip=False,
                uncalibrated=cell.uncalibrated,
                supersedes="",
            )
        )


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
