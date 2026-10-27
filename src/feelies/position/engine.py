"""Stage-D position cell. contracts.md §2. Gates stay stubs; HORIZON resolves."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.events import (
    Event,
    DeRiskRequirement,
    ExitTriggeredPath,
    GateDecision,
    MarkRailUpdate,
    OrderAck,
    OrderAckStatus,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    PositionSnapshot,
    RailOrientation,
    Side,
    Signal,
    SignalDirection,
    SlicePositionUpdate,
)
from feelies.core.exit_policy import ExitPolicy
from feelies.core.identifiers import SequenceGenerator
from feelies.core.trading_session import TradingSessionBounds

# Integer stand-in for formula fields the gates do not evaluate. Never NaN. AS-17.
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
    lots: tuple[PositionFillLeg, ...] = ()
    exit_fills: tuple[PositionFillLeg, ...] = ()
    best: PositionExtreme | None = None
    worst: PositionExtreme | None = None
    best_clean: PositionExtreme | None = None
    invalidation_sequence: int | None = None
    lived_through_feed_gap: bool = False
    correlation_id: str = ""
    entry_spread_ticks: int = 0
    horizon_deadline_ns: int = 0
    quiet_limit_ns: int = 0
    state: str = "OPEN"
    exit_attempt: int = 0
    live_order_id: str | None = None
    reemit: bool = False
    rails_seen: int = 0
    deciding_rail: MarkRailUpdate | None = None
    deciding_first: bool = False
    last_rail: MarkRailUpdate | None = None
    last_present_rail: MarkRailUpdate | None = None
    last_present_was_first: bool = False


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


def _orientation(cell: _Cell, rail: MarkRailUpdate) -> RailOrientation:
    return rail.long if cell.side == "LONG" else rail.short


def _spread(side: str, orient: RailOrientation) -> int:
    """D-215. s × (paying − valuation) on the cell side. Absent marks stay 0."""
    paying = orient.paying_mark_cents
    valuation = orient.valuation_mark_cents
    if paying is None or valuation is None:
        return 0
    return _sign(side) * (paying - valuation)


def _stale(cell: _Cell, rail: MarkRailUpdate) -> bool:
    """§9. Q is favorable.quiet_limit_ns."""
    orient = _orientation(cell, rail)
    return orient.valuation_side_absent or rail.symbol_quiet_ns > cell.quiet_limit_ns


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


def _lot_sums(lots: tuple[PositionFillLeg, ...]) -> tuple[int, int]:
    """D-196. Size and entry cost are exact sums over the lots that remain."""
    size = 0
    cost = 0
    for lot in lots:
        size += lot.quantity
        cost += lot.price_cents * lot.quantity
    return size, cost


def _consume(lots: tuple[PositionFillLeg, ...], shares: int) -> tuple[PositionFillLeg, ...]:
    """D-196. Oldest entry-fill sequence first. Split the lot that is only partly filled."""
    left = shares
    kept: list[PositionFillLeg] = []
    for lot in sorted(lots, key=lambda item: item.sequence):
        if left <= 0:
            kept.append(lot)
            continue
        if lot.quantity <= left:
            left -= lot.quantity
            continue
        kept.append(replace(lot, quantity=lot.quantity - left))
        left = 0
    return tuple(kept)


class PositionEngine:
    """Cell, stub gates, two-phase step. HORIZON emits one live requirement."""

    PUBLICATIONS = (PositionSnapshot, GateDecision, PositionClosed, DeRiskRequirement)

    def __init__(
        self,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        policies: Mapping[str, ExitPolicy] | None = None,
        *,
        clock: Clock,
        gate_order: tuple[str, ...] = _CONTRACT_GATE_ORDER,
        session_bounds: TradingSessionBounds | None = None,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._clock = clock
        self._session_bounds = session_bounds
        self.policies: dict[str, ExitPolicy] = dict(policies or {})
        self._gate_order = gate_order
        self._open: dict[tuple[str, str], _Cell] = {}
        self._born: dict[tuple[str, str, int], int] = {}

    def attach(self) -> None:
        self._bus.subscribe(MarkRailUpdate, self._on_mark_rail)
        self._bus.subscribe(SlicePositionUpdate, self._on_slice_update)
        self._bus.subscribe(Signal, self._on_signal)
        self._bus.subscribe(OrderAck, self._on_ack)

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

    def _on_ack(self, event: OrderAck) -> None:
        """D-217. REJECTED on the live exit order re-arms the next present-side rail."""
        if event.status is not OrderAckStatus.REJECTED:
            return
        for cell in self._open.values():
            if cell.live_order_id != event.order_id:
                continue
            self._put(replace(cell, live_order_id=None, reemit=True))
            return

    def _on_slice_update(self, event: SlicePositionUpdate) -> None:
        policy = self.policies.get(event.strategy_id)
        if policy is None or event.fill_quantity == 0:
            return
        key = (event.strategy_id, event.symbol)
        cell = self._open.get(key)
        incoming = "LONG" if event.fill_quantity > 0 else "SHORT"
        shares = abs(event.fill_quantity)
        if cell is not None and event.order_id.startswith(f"{cell.cell_id}|EXIT|"):
            self._apply_exit_fill(key, cell, event, shares)
            return
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
            lots = _consume(cell.lots, overlap)
            size, cost = _lot_sums(lots)
            cell = replace(
                cell,
                exit_fills=(*cell.exit_fills, _leg(event, overlap)),
                lots=lots,
                size=size,
                entry_cost_cents=cost,
            )
        if cell.size == 0:
            self._open.pop(key, None)
            # D-215. A close before any rail has spread 0 and stale data.
            self._publish_closed(
                cell,
                "EXTERNAL:SIGN_FLIP",
                event.correlation_id,
                closed_on_stale_data=cell.rails_seen == 0,
            )
        elif overlap > 0:
            self._put(cell)
        if excess > 0:
            self._birth(event, policy, incoming, excess)

    def _on_mark_rail(self, event: MarkRailUpdate) -> None:
        cells = [cell for cell in self._open.values() if cell.symbol == event.symbol]
        for prior in sorted(cells, key=lambda item: item.cell_id):
            key = (prior.strategy_id, prior.symbol)
            cell = self._current(key, prior.cell_id)
            if cell is None or cell.state not in ("OPEN", "EXITING"):
                continue
            rails_seen = cell.rails_seen + 1
            was_first = rails_seen == 1
            orient = _orientation(cell, event)
            cell = replace(
                cell,
                rails_seen=rails_seen,
                last_rail=event,
                lived_through_feed_gap=cell.lived_through_feed_gap or event.feed_gap_before,
            )
            if was_first:
                # D-215. Freeze the spread on this rail, before the first snapshot.
                cell = replace(cell, entry_spread_ticks=_spread(cell.side, orient))
            if orient.valuation_side_absent is False:
                cell = replace(
                    cell,
                    last_present_rail=event,
                    last_present_was_first=was_first,
                )
            snapshot = self._snapshot(cell, event)
            cell = self._note_extremes(cell, snapshot, event)
            frozen = self._with_extremes(snapshot, cell)
            self._put(cell)
            self._publish(frozen)
            if self._current(key, cell.cell_id) is None:
                continue
            outcomes = {name: self._gate_outcome(name) for name in self._gate_order}
            for name in _CONTRACT_GATE_ORDER:
                outcome = outcomes.get(name)
                if outcome is not None:
                    self._publish(self._gate(name, cell, frozen, event, outcome))
            cell = self._current(key, prior.cell_id)
            if cell is None:
                continue
            cell = self._resolve(cell, event)
            if cell is None:
                continue
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
            horizon_deadline_ns=self._deadline(stamp, policy),
            quiet_limit_ns=policy.favorable.quiet_limit_ns,
        )
        self._put(self._extend(cell, event, shares))

    def _put(self, cell: _Cell) -> None:
        self._open[(cell.strategy_id, cell.symbol)] = cell

    def _extend(self, cell: _Cell, event: SlicePositionUpdate, shares: int) -> _Cell:
        leg = _leg(event, shares)
        return replace(
            cell,
            entry_fills=(*cell.entry_fills, leg),
            lots=(*cell.lots, leg),
            size=cell.size + shares,
            entry_cost_cents=cell.entry_cost_cents + leg.price_cents * shares,
            correlation_id=event.correlation_id,
        )

    def _snapshot(self, cell: _Cell, event: MarkRailUpdate) -> PositionSnapshot:
        orient = _orientation(cell, event)
        sign = _sign(cell.side)
        return PositionSnapshot(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=event.correlation_id,
            sequence=self._seq.next(),
            source_layer="position",
            cell_id=cell.cell_id,
            symbol=cell.symbol,
            strategy_id=cell.strategy_id,
            state=cell.state,
            side=cell.side,
            declared_archetype=cell.archetype,
            rail_sequence=event.quote_sequence,
            size=cell.size,
            entry_cost_cents=cell.entry_cost_cents,
            entry_spread_ticks=cell.entry_spread_ticks,
            horizon_deadline_ns=cell.horizon_deadline_ns,
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
        """F-P50-3. Seed at the first CLEAN rail after birth, whatever the move."""
        orient = snapshot.rail
        move = snapshot.move_now_cents
        if cell.best is None or cell.worst is None or cell.best_clean is None:
            if not _clean(event, orient) or move is None:
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

    def _publish_closed(
        self,
        cell: _Cell,
        reason: str,
        correlation_id: str,
        *,
        triggered: tuple[ExitTriggeredPath, ...] = (),
        proposed: int | None = None,
        closed_on_stale_data: bool = False,
        first_event_exit: bool = False,
    ) -> None:
        self._bus.publish(
            PositionClosed(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                source_layer="position",
                cell_id=cell.cell_id,
                symbol=cell.symbol,
                strategy_id=cell.strategy_id,
                side=cell.side,
                declared_archetype=cell.archetype,
                entry_fills=tuple(cell.entry_fills),
                exit_fills=tuple(cell.exit_fills),
                entry_spread_ticks=cell.entry_spread_ticks,
                horizon_deadline_ns=cell.horizon_deadline_ns,
                drawn_level_ticks=_FORMULA_PLACEHOLDER,
                exit_reason=reason,
                triggered_paths=triggered,
                proposed_price_cents=proposed,
                best=cell.best,
                worst=cell.worst,
                best_clean=cell.best_clean,
                closed_on_stale_data=closed_on_stale_data,
                exited_on_unusable_data=False,
                lived_through_feed_gap=cell.lived_through_feed_gap,
                first_event_exit=first_event_exit,
                stop_inside_round_trip=False,
                target_inside_round_trip=False,
                uncalibrated=cell.uncalibrated,
                supersedes="",
            )
        )

    def finalize(self) -> None:
        """D-219. OPEN and EXITING cells close END_OF_TAPE. No requirement."""
        pending = [cell for cell in self._open.values() if cell.state in ("OPEN", "EXITING")]
        for prior in sorted(pending, key=lambda item: item.cell_id):
            key = (prior.strategy_id, prior.symbol)
            cell = self._current(key, prior.cell_id)
            if cell is None or cell.state not in ("OPEN", "EXITING"):
                continue
            self._open.pop(key, None)
            self._publish_end_of_tape(cell)

    def _apply_exit_fill(
        self,
        key: tuple[str, str],
        cell: _Cell,
        event: SlicePositionUpdate,
        shares: int,
    ) -> None:
        """D-76. An exit-order fill is an exit leg, never SIGN_FLIP. Size 0 closes HORIZON."""
        overlap = shares if shares < cell.size else cell.size
        if overlap <= 0:
            return
        lots = _consume(cell.lots, overlap)
        size, cost = _lot_sums(lots)
        cell = replace(
            cell,
            exit_fills=(*cell.exit_fills, _leg(event, overlap)),
            lots=lots,
            size=size,
            entry_cost_cents=cost,
        )
        if cell.size != 0:
            self._put(cell)
            return
        triggered, proposed, stale, first = self._horizon_close_facts(cell)
        self._open.pop(key, None)
        self._publish_closed(
            cell,
            "HORIZON",
            event.correlation_id,
            triggered=triggered,
            proposed=proposed,
            closed_on_stale_data=stale,
            first_event_exit=first,
        )

    def _resolve(self, cell: _Cell, event: MarkRailUpdate) -> _Cell | None:
        """D-216. HORIZON only. Gates stay stubs; a latched invalidation never acts."""
        orient = _orientation(cell, event)
        if cell.state == "OPEN" and event.event_timestamp_ns >= cell.horizon_deadline_ns:
            armed = replace(
                cell,
                deciding_rail=event,
                deciding_first=cell.rails_seen == 1,
            )
            return self._emit_exit(armed, event, 1)
        if (
            cell.state == "EXITING"
            and cell.reemit
            and cell.live_order_id is None
            and orient.valuation_side_absent is False
        ):
            return self._emit_exit(cell, event, cell.exit_attempt + 1)
        return cell

    def _emit_exit(self, cell: _Cell, event: MarkRailUpdate, attempt: int) -> _Cell | None:
        """D-217. One live requirement. order_id is cell_id|EXIT|attempt from 1."""
        order_id = f"{cell.cell_id}|EXIT|{attempt}"
        side = Side.SELL if cell.side == "LONG" else Side.BUY
        armed = replace(
            cell,
            state="EXITING",
            exit_attempt=attempt,
            live_order_id=order_id,
            reemit=False,
        )
        self._put(armed)
        self._publish(
            DeRiskRequirement(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=event.correlation_id,
                sequence=self._seq.next(),
                source_layer="POSITION",
                order_id=order_id,
                symbol=cell.symbol,
                side=side,
                quantity=cell.size,
                strategy_id=cell.strategy_id,
                reason="HORIZON",
            )
        )
        return self._current((cell.strategy_id, cell.symbol), cell.cell_id)

    def _publish_end_of_tape(self, cell: _Cell) -> None:
        """D-219. Price and flags from the last rail whose valuation side is present."""
        rail = cell.last_present_rail
        if rail is not None:
            self._publish_closed(
                cell,
                "END_OF_TAPE",
                rail.correlation_id,
                proposed=_orientation(cell, rail).valuation_mark_cents,
                closed_on_stale_data=_stale(cell, rail),
                first_event_exit=cell.last_present_was_first,
            )
            return
        last = cell.last_rail
        self._publish_closed(
            cell,
            "END_OF_TAPE",
            "" if last is None else last.correlation_id,
            closed_on_stale_data=True,
        )

    def _horizon_close_facts(
        self,
        cell: _Cell,
    ) -> tuple[tuple[ExitTriggeredPath, ...], int | None, bool, bool]:
        """D-218. Path, price, stale and first-event are taken at the deciding rail."""
        rail = cell.deciding_rail
        if rail is None:
            return (), None, cell.rails_seen == 0, False
        mark = _orientation(cell, rail).forced_exit_mark_cents
        stale = _stale(cell, rail)
        if mark is None:
            return (), None, stale, cell.deciding_first
        path = ExitTriggeredPath(path="HORIZON", proposed_price_cents=mark, trigger="DEADLINE")
        return (path,), mark, stale, cell.deciding_first

    def _deadline(self, fill_ts: int, policy: ExitPolicy) -> int:
        """D-214. No session close resolves to fill_ts + T."""
        horizon = fill_ts + policy.horizon.T_ns
        bounds = self._session_bounds
        if bounds is None:
            return horizon
        close = bounds.resolve_for_timestamp(fill_ts).rth_close_ns
        return min(horizon, close - policy.horizon.cutoff_before_close_ns)

    def _current(self, key: tuple[str, str], cell_id: str) -> _Cell | None:
        cell = self._open.get(key)
        if cell is None or cell.cell_id != cell_id:
            return None
        return cell


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
