"""Reference position engine. contracts.md §§0–9. Advance, then gates, then resolve."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from typing import NamedTuple

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
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

_REQUIREMENT = {
    "ADVERSE": "ADVERSE_EXCURSION",
    "HORIZON": "HORIZON",
    "INVALIDATION": "INVALIDATION",
    "FAVORABLE": "FAVORABLE_EXCURSION",
}


class PositionEngine:
    """Cell, both gates, and precedence. Subscribes in ``attach``."""

    def __init__(
        self,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        policies: Mapping[str, ExitPolicy] | None = None,
        gate_order: tuple[str, ...] = ("ADVERSE", "FAVORABLE"),
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self.policies: dict[str, ExitPolicy] = dict(policies or {})
        self.gate_order = gate_order
        self._open: dict[tuple[str, str], Cell] = {}
        self._last_rail: dict[str, MarkRailUpdate] = {}

    def attach(self) -> None:
        self._bus.subscribe(MarkRailUpdate, self._on_mark_rail)
        self._bus.subscribe(SlicePositionUpdate, self._on_slice)
        self._bus.subscribe(Signal, self._on_signal)
        self._bus.subscribe(OrderAck, self._on_ack)

    def finalize(self) -> None:
        """§2:172-180 and §8:415-417. END_OF_TAPE after the last replay event."""
        pending = sorted(self._open.values(), key=lambda cell: cell.cell_id)
        for cell in pending:
            self._close_end(cell)

    def _on_signal(self, event: Signal) -> None:
        """§2:241-245. FLAT or opposite latches; same-direction entry does not."""
        cell = self._open.get((event.strategy_id, event.symbol))
        if cell is None or cell.state != "OPEN":
            return
        if event.direction is SignalDirection.FLAT:
            cell.invalidation = True
            return
        if event.direction is SignalDirection.LONG and cell.side == "SHORT":
            cell.invalidation = True
        elif event.direction is SignalDirection.SHORT and cell.side == "LONG":
            cell.invalidation = True

    def _on_mark_rail(self, event: MarkRailUpdate) -> None:
        """§2:247-256. One step per open cell, in ``cell_id`` order."""
        self._last_rail[event.symbol] = event
        cells = [cell for cell in self._open.values() if cell.symbol == event.symbol]
        cells.sort(key=lambda cell: cell.cell_id)
        for cell in cells:
            if (cell.strategy_id, cell.symbol) not in self._open:
                continue
            self._step(cell, event)

    def _step(self, cell: Cell, rail: MarkRailUpdate) -> None:
        orient = _orientation(cell, rail)
        cell.note_rail(rail, orient)
        now = move_cents(cell.sign, orient.valuation_mark_cents, cell.open_qty, cell.entry_cost())
        worst = move_cents(cell.sign, orient.worst_side_mark_cents, cell.open_qty, cell.entry_cost())
        forced = move_cents(cell.sign, orient.forced_exit_mark_cents, cell.open_qty, cell.entry_cost())
        cell.update_extremes(now, rail, orient)
        self._publish_snapshot(cell, rail, orient, now, worst, forced)
        adverse, favorable = self._evaluate(cell, rail, orient, now, worst)
        if cell.state == "EXITING":
            adverse, favorable = _escalate(cell, adverse, favorable)
        self._publish_gate(cell, rail, adverse)
        self._publish_gate(cell, rail, favorable)
        if cell.state == "OPEN":
            self._resolve(cell, rail, orient, adverse, favorable)
        elif cell.pending_reemit and _exit_side_usable(orient):
            self._emit_requirement(cell, rail)

    def _evaluate(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
        move_worst: int | None,
    ) -> tuple[Decision, Decision]:
        policy = cell.policy
        tokens = suppression_tokens(
            valuation_mark=orient.valuation_mark_cents,
            valuation_absent=orient.valuation_side_absent,
            crossed=rail.crossed,
            feed_gap=rail.feed_gap_before,
            dwell_clean=orient.dwell_window_clean,
            warmed=rail.warmed_up,
            quiet_ns=rail.symbol_quiet_ns,
            quiet_limit_ns=policy.favorable.quiet_limit_ns,
        )
        peak = cell.best_clean.cents if cell.best_clean is not None else None
        peak_sequence = cell.best_clean.sequence if cell.best_clean is not None else 0
        found: dict[str, Decision] = {}
        for name in self.gate_order:
            if name == "ADVERSE":
                found[name] = evaluate_adverse(
                    cell_id=cell.cell_id,
                    centre=policy.adverse.centre_ticks,
                    band=policy.adverse.band_ticks,
                    blind_limit_ns=policy.adverse.blind_limit_ns,
                    move_worst=move_worst,
                    size=cell.open_qty,
                    forced=orient.forced_exit_mark_cents,
                    paying_absent_ns=orient.paying_absent_for_ns,
                    valuation_absent_ns=orient.valuation_absent_for_ns,
                    quiet_ns=rail.symbol_quiet_ns,
                )
            elif name == "FAVORABLE":
                found[name] = evaluate_favorable(
                    form=policy.favorable.form,
                    target_ticks=policy.favorable.target_ticks,
                    giveback=policy.favorable.giveback_spread_multiple,
                    spread=cell.spread,
                    fee_ticks=policy.fee_round_trip_ticks,
                    size=cell.open_qty,
                    move_now=move_now,
                    best_clean_cents=peak,
                    best_clean_sequence=peak_sequence,
                    dwelled=orient.dwelled_exit_mark_cents,
                    tokens=tokens,
                )
        return found["ADVERSE"], found["FAVORABLE"]

    def _resolve(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        adverse: Decision,
        favorable: Decision,
    ) -> None:
        paths: list[tuple[str, int | None, str]] = []
        if adverse.outcome == "fire":
            paths.append(("ADVERSE", adverse.proposed, adverse.trigger))
        if rail.event_timestamp_ns >= cell.deadline_ns:
            paths.append(("HORIZON", orient.forced_exit_mark_cents, "HORIZON"))
        if cell.invalidation:
            paths.append(("INVALIDATION", orient.forced_exit_mark_cents, "INVALIDATION"))
        if favorable.outcome == "fire":
            paths.append(("FAVORABLE", favorable.proposed, favorable.trigger))
        cell.invalidation = False
        if not paths:
            return
        paths.sort(key=lambda item: path_rank(item[0]))
        winner = paths[0][0]
        prices = [price for _name, price, _trigger in paths if price is not None]
        cell.exit_reason = winner
        cell.requirement_reason = _REQUIREMENT[winner]
        cell.close_proposed = worst_price(cell.side, prices)
        cell.close_paths = tuple(
            ExitTriggeredPath(path=name, proposed_price_cents=price, trigger=trigger)
            for name, price, trigger in paths
            if price is not None
        )
        cell.close_blind = any(trigger == "BLIND" for _name, _price, trigger in paths)
        quiet_limit = cell.policy.favorable.quiet_limit_ns
        cell.close_stale = orient.valuation_side_absent or rail.symbol_quiet_ns > quiet_limit
        cell.close_first = cell.rail_count == 1
        if cell.open_qty < 1:
            return
        cell.state = "EXITING"
        self._emit_requirement(cell, rail)

    def _emit_requirement(self, cell: Cell, rail: MarkRailUpdate) -> None:
        """§2:157-161 and §2:286-291. One live requirement; attempts count from 1."""
        if cell.live_requirement or cell.open_qty < 1:
            return
        cell.attempt += 1
        order_id = f"{cell.cell_id}|EXIT|{cell.attempt}"
        cell.exit_order_id = order_id
        cell.attempts.append(order_id)
        cell.live_requirement = True
        cell.pending_reemit = False
        side = Side.SELL if cell.side == "LONG" else Side.BUY
        self._bus.publish(
            DeRiskRequirement(
                timestamp_ns=rail.timestamp_ns,
                correlation_id=rail.correlation_id,
                sequence=self._seq.next(),
                source_layer="POSITION",
                order_id=order_id,
                symbol=cell.symbol,
                side=side,
                quantity=cell.open_qty,
                strategy_id=cell.strategy_id,
                reason=cell.requirement_reason,
            )
        )

    def _on_ack(self, event: OrderAck) -> None:
        """§2:157-161. A REJECTED live exit waits for the next usable rail (D-106)."""
        if event.status is not OrderAckStatus.REJECTED:
            return
        for cell in self._open.values():
            if cell.live_requirement and cell.exit_order_id == event.order_id:
                cell.live_requirement = False
                cell.pending_reemit = True
                return

    def _tape_sequence(self, event: SlicePositionUpdate) -> int:
        """The quote the fill crossed. Entry and exit acks settle on that quote."""
        rail = self._last_rail.get(event.symbol)
        if rail is None:
            return event.fill_ack_sequence
        return rail.quote_sequence

    def _on_slice(self, event: SlicePositionUpdate) -> None:
        price = whole_cents(event.symbol, event.fill_price)
        if event.fill_quantity == 0:
            return
        policy = self.policies.get(event.strategy_id)
        sequence = self._tape_sequence(event)
        cell = self._open.get((event.strategy_id, event.symbol))
        if cell is None:
            if policy is None or event.quantity == 0:
                return
            self._birth(event, policy, price, abs(event.fill_quantity), sequence)
            return
        if event.order_id == cell.exit_order_id:
            self._reduce(cell, event, price, abs(event.fill_quantity), sequence)
            return
        same = (event.fill_quantity > 0 and cell.side == "LONG") or (
            event.fill_quantity < 0 and cell.side == "SHORT"
        )
        if same:
            if cell.state == "OPEN" and event.order_id == cell.entry_order_id:
                leg = _leg(event, price, sequence)
                cell.extend(price, abs(event.fill_quantity), leg)
            return
        filled = abs(event.fill_quantity)
        overlap = cell.open_qty if cell.open_qty < filled else filled
        excess = filled - overlap
        if event.quantity == 0:
            reason = "EXTERNAL:SAFETY"
        elif excess > 0:
            reason = "EXTERNAL:SIGN_FLIP"
        else:
            self._reduce(cell, event, price, overlap, sequence)
            return
        self._reduce(cell, event, price, overlap, sequence, reason=reason)
        if excess > 0 and policy is not None:
            self._birth(event, policy, price, excess, sequence)

    def _birth(
        self,
        event: SlicePositionUpdate,
        policy: ExitPolicy,
        price: int,
        quantity: int,
        sequence: int,
    ) -> None:
        side = "LONG" if event.fill_quantity > 0 else "SHORT"
        if event.quantity < 0 or (event.quantity == 0 and event.fill_quantity < 0):
            side = "SHORT"
        if event.quantity > 0 or (event.quantity == 0 and event.fill_quantity > 0):
            side = "LONG"
        rail = self._last_rail.get(event.symbol)
        orient = None if rail is None else _side_orient(side, rail)
        paying = None if orient is None else orient.paying_mark_cents
        valuation = None if orient is None else orient.valuation_mark_cents
        cell = Cell(
            cell_id=cell_id_for(event.symbol, event.strategy_id, sequence, side),
            symbol=event.symbol,
            strategy_id=event.strategy_id,
            side=side,
            policy=policy,
            entry_order_id=event.order_id,
            spread=entry_spread_ticks(paying, valuation),
            deadline_ns=event.fill_timestamp_ns + policy.horizon.T_ns,
            price_cents=price,
            quantity=quantity,
            leg=_leg(event, price, sequence, quantity=quantity),
        )
        if rail is not None and orient is not None:
            if orient.valuation_mark_cents is not None and not orient.valuation_side_absent:
                cell.last_usable = rail
        self._open[(event.strategy_id, event.symbol)] = cell

    def _reduce(
        self,
        cell: Cell,
        event: SlicePositionUpdate,
        price: int,
        quantity: int,
        sequence: int,
        *,
        reason: str = "",
    ) -> None:
        take = cell.open_qty if quantity > cell.open_qty else quantity
        if take < 1:
            return
        cell.exit_legs.append(_leg(event, price, sequence, quantity=take))
        cell.consume(take)
        if cell.open_qty > 0:
            return
        if reason and not cell.exit_reason:
            cell.exit_reason = reason
        self._emit_close(cell, event.fill_timestamp_ns, event.correlation_id)

    def _close_end(self, cell: Cell) -> None:
        usable = cell.last_usable
        if usable is None:
            cell.exit_reason = "END_OF_TAPE"
            cell.close_proposed = None
            cell.close_paths = ()
            cell.close_blind = False
            cell.close_stale = True
            cell.close_first = False
            self._emit_close(cell, 0, "EOT")
            return
        orient = _orientation(cell, usable)
        cell.exit_reason = "END_OF_TAPE"
        cell.close_proposed = orient.valuation_mark_cents
        cell.close_paths = ()
        cell.close_blind = False
        cell.close_stale = (
            orient.valuation_side_absent
            or usable.symbol_quiet_ns > cell.policy.favorable.quiet_limit_ns
        )
        cell.close_first = usable.quote_sequence == cell.first_rail_sequence
        self._emit_close(cell, usable.timestamp_ns, usable.correlation_id)

    def _emit_close(self, cell: Cell, timestamp_ns: int, correlation_id: str) -> None:
        policy = cell.policy
        round_trip = cell.spread + policy.fee_round_trip_ticks
        target = policy.favorable.target_ticks
        disarmed = (
            policy.favorable.form == "fixed" and target is not None and target <= round_trip
        )
        level = band_level(cell.cell_id, policy.adverse.centre_ticks, policy.adverse.band_ticks)
        self._open.pop((cell.strategy_id, cell.symbol), None)
        cell.state = "CLOSED"
        self._bus.publish(
            PositionClosed(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                source_layer="POSITION",
                cell_id=cell.cell_id,
                symbol=cell.symbol,
                strategy_id=cell.strategy_id,
                side=cell.side,
                declared_archetype=policy.archetype,
                entry_fills=tuple(cell.entry_legs),
                exit_fills=tuple(cell.exit_legs),
                entry_spread_ticks=cell.spread,
                horizon_deadline_ns=cell.deadline_ns,
                drawn_level_ticks=level,
                exit_reason=cell.exit_reason,
                triggered_paths=cell.close_paths,
                proposed_price_cents=cell.close_proposed,
                best=cell.best,
                worst=cell.worst,
                best_clean=cell.best_clean,
                closed_on_stale_data=cell.close_stale,
                exited_on_unusable_data=cell.close_blind,
                lived_through_feed_gap=cell.saw_feed_gap,
                first_event_exit=cell.close_first,
                stop_inside_round_trip=level <= round_trip,
                target_inside_round_trip=disarmed,
                uncalibrated=policy.curve_ref == "ARBITRARY_NOT_CALIBRATED",
                supersedes="",
            )
        )

    def _publish_snapshot(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
        move_worst: int | None,
        move_forced: int | None,
    ) -> None:
        self._bus.publish(
            PositionSnapshot(
                timestamp_ns=rail.timestamp_ns,
                correlation_id=rail.correlation_id,
                sequence=self._seq.next(),
                source_layer="POSITION",
                cell_id=cell.cell_id,
                symbol=cell.symbol,
                strategy_id=cell.strategy_id,
                state=cell.state,
                side=cell.side,
                declared_archetype=cell.policy.archetype,
                rail_sequence=rail.quote_sequence,
                size=cell.open_qty,
                entry_cost_cents=cell.entry_cost(),
                entry_spread_ticks=cell.spread,
                horizon_deadline_ns=cell.deadline_ns,
                move_now_cents=move_now,
                move_worst_cents=move_worst,
                move_forced_cents=move_forced,
                best=cell.best,
                worst=cell.worst,
                best_clean=cell.best_clean,
                rail=orient,
                symbol_quiet_ns=rail.symbol_quiet_ns,
                locked=rail.locked,
                crossed=rail.crossed,
                feed_gap_before=rail.feed_gap_before,
                warmed_up=rail.warmed_up,
            )
        )

    def _publish_gate(self, cell: Cell, rail: MarkRailUpdate, decision: Decision) -> None:
        proposed = decision.proposed if decision.proposed is not None else 0
        self._bus.publish(
            GateDecision(
                timestamp_ns=rail.timestamp_ns,
                correlation_id=rail.correlation_id,
                sequence=self._seq.next(),
                source_layer="POSITION",
                cell_id=cell.cell_id,
                rail_sequence=rail.quote_sequence,
                gate=decision.gate,
                outcome=decision.outcome,
                reason=decision.reason,
                form=decision.form,
                proposed_price_cents=proposed,
                reference_ticks=decision.reference_ticks,
                reference_sequence=decision.reference_sequence,
                drawn_level_ticks=decision.drawn,
                suppressions=decision.suppressions,
            )
        )


def _exit_side_usable(orient: RailOrientation) -> bool:
    """§2:159. The executable exit side is present (D-62)."""
    return orient.valuation_mark_cents is not None and not orient.valuation_side_absent


def _orientation(cell: Cell, rail: MarkRailUpdate) -> RailOrientation:
    return _side_orient(cell.side, rail)


def _side_orient(side: str, rail: MarkRailUpdate) -> RailOrientation:
    if side == "LONG":
        return rail.long
    return rail.short


def _leg(
    event: SlicePositionUpdate,
    price: int,
    sequence: int,
    *,
    quantity: int | None = None,
) -> PositionFillLeg:
    """Fill leg keyed by the quote the fill crossed, not the ack sequence."""
    return PositionFillLeg(
        price_cents=price,
        quantity=abs(event.fill_quantity) if quantity is None else quantity,
        timestamp_ns=event.fill_timestamp_ns,
        sequence=sequence,
    )


def _escalate(cell: Cell, adverse: Decision, favorable: Decision) -> tuple[Decision, Decision]:
    """§2:157-163. A live MARKET exit is not re-ordered. Triggers stay on the record."""
    if adverse.outcome == "fire":
        adverse = adverse._replace(outcome="ESCALATION_NOOP")
    if favorable.outcome == "fire":
        favorable = favorable._replace(outcome="ESCALATION_NOOP")
    return adverse, favorable


def whole_cents(symbol: str, price: Decimal) -> int:
    """§9:480-482. A fractional cent raises."""
    scaled = price * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(symbol)
    return int(scaled)


def move_cents(sign: int, mark: int | None, size: int, entry_cost: int) -> int | None:
    """§2:210-217. None exactly when the mark is None."""
    if mark is None:
        return None
    return sign * (mark * size - entry_cost)


def cell_id_for(symbol: str, strategy_id: str, birth_sequence: int, side: str) -> str:
    """§2:191. ``symbol|strategy_id|birth_fill_sequence|side``."""
    return f"{symbol}|{strategy_id}|{birth_sequence}|{side}"


def entry_spread_ticks(paying: int | None, valuation: int | None) -> int:
    """§2:192-193. Positive ticks between the two sides; 0 when a side is missing."""
    if paying is None or valuation is None:
        return 0
    if paying >= valuation:
        return paying - valuation
    return valuation - paying


class Cell:
    """Open episode. Extremes stay None until the first clean non-zero move."""

    __slots__ = (
        "cell_id",
        "symbol",
        "strategy_id",
        "side",
        "sign",
        "policy",
        "entry_order_id",
        "exit_order_id",
        "attempt",
        "attempts",
        "live_requirement",
        "pending_reemit",
        "entry_legs",
        "exit_legs",
        "lots",
        "open_qty",
        "spread",
        "deadline_ns",
        "state",
        "best",
        "worst",
        "best_clean",
        "seeded",
        "rail_count",
        "first_rail_sequence",
        "saw_feed_gap",
        "last_usable",
        "invalidation",
        "requirement_reason",
        "exit_reason",
        "close_paths",
        "close_proposed",
        "close_blind",
        "close_stale",
        "close_first",
    )

    def __init__(
        self,
        *,
        cell_id: str,
        symbol: str,
        strategy_id: str,
        side: str,
        policy: ExitPolicy,
        entry_order_id: str,
        spread: int,
        deadline_ns: int,
        price_cents: int,
        quantity: int,
        leg: PositionFillLeg,
    ) -> None:
        self.cell_id = cell_id
        self.symbol = symbol
        self.strategy_id = strategy_id
        self.side = side
        self.sign = 1 if side == "LONG" else -1
        self.policy = policy
        self.entry_order_id = entry_order_id
        self.exit_order_id = ""
        self.attempt = 0
        self.attempts: list[str] = []
        self.live_requirement = False
        self.pending_reemit = False
        self.entry_legs: list[PositionFillLeg] = [leg]
        self.exit_legs: list[PositionFillLeg] = []
        self.lots: list[list[int]] = [[price_cents, quantity]]
        self.open_qty = quantity
        self.spread = spread
        self.deadline_ns = deadline_ns
        self.state = "OPEN"
        self.best: PositionExtreme | None = None
        self.worst: PositionExtreme | None = None
        self.best_clean: PositionExtreme | None = None
        self.seeded = False
        self.rail_count = 0
        self.first_rail_sequence: int | None = None
        self.saw_feed_gap = False
        self.last_usable: MarkRailUpdate | None = None
        self.invalidation = False
        self.requirement_reason = ""
        self.exit_reason = ""
        self.close_paths: tuple[ExitTriggeredPath, ...] = ()
        self.close_proposed: int | None = None
        self.close_blind = False
        self.close_stale = False
        self.close_first = False

    def entry_cost(self) -> int:
        return sum(price * qty for price, qty in self.lots)

    def extend(self, price_cents: int, quantity: int, leg: PositionFillLeg) -> None:
        """§2:198-199. Same entry order: size and cost accumulate."""
        self.entry_legs.append(leg)
        self.lots.append([price_cents, quantity])
        self.open_qty += quantity

    def consume(self, quantity: int) -> None:
        """§2:164-166. Exit quantity leaves the open lots."""
        left = quantity
        while left > 0 and self.lots:
            price, have = self.lots[0]
            take = have if have < left else left
            if take == have:
                self.lots.pop(0)
            else:
                self.lots[0] = [price, have - take]
            left -= take
        self.open_qty -= quantity

    def note_rail(self, rail: MarkRailUpdate, orient: RailOrientation) -> None:
        self.rail_count += 1
        if self.first_rail_sequence is None:
            self.first_rail_sequence = rail.quote_sequence
        if rail.feed_gap_before:
            self.saw_feed_gap = True
        if orient.valuation_mark_cents is not None and not orient.valuation_side_absent:
            self.last_usable = rail

    def update_extremes(
        self,
        move_now: int | None,
        rail: MarkRailUpdate,
        orient: RailOrientation,
    ) -> None:
        """§2:225-235. Seed on the first clean non-zero move; never at zero."""
        clean = (
            move_now is not None
            and not orient.valuation_side_absent
            and orient.valuation_mark_cents is not None
            and not rail.crossed
            and not rail.feed_gap_before
        )
        if not self.seeded:
            if not clean or move_now is None or move_now == 0:
                return
            seeded = _extreme(move_now, rail.quote_sequence, orient, rail, clean_peak=True)
            self.best = seeded
            self.worst = seeded
            self.best_clean = seeded
            self.seeded = True
            return
        if move_now is None or self.best is None or self.worst is None or self.best_clean is None:
            return
        if move_now > self.best.cents:
            self.best = _extreme(move_now, rail.quote_sequence, orient, rail, clean_peak=False)
        if move_now < self.worst.cents:
            self.worst = _extreme(move_now, rail.quote_sequence, orient, rail, clean_peak=False)
        if clean and move_now > self.best_clean.cents:
            self.best_clean = _extreme(move_now, rail.quote_sequence, orient, rail, clean_peak=True)


def _extreme(
    cents: int,
    sequence: int,
    orient: RailOrientation,
    rail: MarkRailUpdate,
    *,
    clean_peak: bool,
) -> PositionExtreme:
    if clean_peak:
        absent = False
        crossed = False
        gap = False
    else:
        absent = orient.valuation_side_absent
        crossed = rail.crossed
        gap = rail.feed_gap_before
    return PositionExtreme(
        cents=cents,
        sequence=sequence,
        valuation_age_ns=orient.valuation_age_ns,
        valuation_side_absent=absent,
        crossed=crossed,
        feed_gap_before=gap,
    )


_TOKENS = (
    "VALUATION_SIDE_ABSENT",
    "CROSSED",
    "FEED_GAP",
    "DWELL_NOT_CLEAN",
    "NOT_WARMED_UP",
    "SYMBOL_QUIET",
)
_RANK = {"ADVERSE": 0, "HORIZON": 1, "INVALIDATION": 2, "FAVORABLE": 3}


class Decision(NamedTuple):
    gate: str
    outcome: str
    reason: str
    form: str
    proposed: int | None
    reference_ticks: int
    reference_sequence: int
    drawn: int
    suppressions: tuple[str, ...]
    trigger: str


def band_level(cell_id: str, centre: int, band: int) -> int:
    """§9:433-437. Recomputed from ``cell_id``; never stored."""
    digest = hashlib.sha256(cell_id.encode("utf-8")).digest()[:8]
    offset = int.from_bytes(digest, "big") % (band + 1)
    return (centre - (band // 2)) + offset


def giveback_r(multiple: float, spread: int) -> int:
    """§9:438-440. ``k = Fraction(repr(multiple))``; floor via integers; at least 1."""
    ratio = Fraction(repr(multiple))
    floored = (ratio.numerator * spread) // ratio.denominator
    if floored < 1:
        return 1
    return floored


def suppression_tokens(
    *,
    valuation_mark: int | None,
    valuation_absent: bool,
    crossed: bool,
    feed_gap: bool,
    dwell_clean: bool,
    warmed: bool,
    quiet_ns: int,
    quiet_limit_ns: int,
) -> tuple[str, ...]:
    """§9:430-432. Every failing token, in the stated order."""
    failed: list[str] = []
    if valuation_absent or valuation_mark is None:
        failed.append(_TOKENS[0])
    if crossed:
        failed.append(_TOKENS[1])
    if feed_gap:
        failed.append(_TOKENS[2])
    if not dwell_clean:
        failed.append(_TOKENS[3])
    if not warmed:
        failed.append(_TOKENS[4])
    if quiet_ns > quiet_limit_ns:
        failed.append(_TOKENS[5])
    return tuple(failed)


def evaluate_adverse(
    *,
    cell_id: str,
    centre: int,
    band: int,
    blind_limit_ns: int,
    move_worst: int | None,
    size: int,
    forced: int | None,
    paying_absent_ns: int,
    valuation_absent_ns: int,
    quiet_ns: int,
) -> Decision:
    """§4 and §9:427-429. Fires on the level or, strictly above A, on BLIND."""
    level = band_level(cell_id, centre, band)
    blind = (
        paying_absent_ns > blind_limit_ns
        or valuation_absent_ns > blind_limit_ns
        or quiet_ns > blind_limit_ns
    )
    if blind:
        outcome, reason, trigger = "fire", "BLIND", "BLIND"
    elif move_worst is not None and move_worst <= -level * size:
        outcome, reason, trigger = "fire", "LEVEL", "LEVEL"
    else:
        outcome, reason, trigger = "hold", "", ""
    return Decision(
        "ADVERSE",
        outcome,
        reason,
        "",
        forced,
        level,
        0,
        level,
        (),
        trigger,
    )


def evaluate_favorable(
    *,
    form: str,
    target_ticks: int | None,
    giveback: float | None,
    spread: int,
    fee_ticks: int,
    size: int,
    move_now: int | None,
    best_clean_cents: int | None,
    best_clean_sequence: int,
    dwelled: int | None,
    tokens: tuple[str, ...],
) -> Decision:
    """§3. Hard blocks first; fixed compares ``X * size``; trailing gives back ``R``."""
    level = 0
    if tokens:
        reference = target_ticks if target_ticks is not None else 0
        if form == "trailing" and giveback is not None:
            reference = giveback_r(giveback, spread)
        return Decision(
            "FAVORABLE",
            "suppressed",
            tokens[0],
            form,
            dwelled,
            reference,
            best_clean_sequence,
            level,
            tokens,
            "",
        )
    round_trip = spread + fee_ticks
    if form == "trailing" and giveback is not None:
        giveback_ticks = giveback_r(giveback, spread)
        armed = (
            best_clean_cents is not None
            and move_now is not None
            and best_clean_cents > (giveback_ticks + round_trip) * size
        )
        fire = (
            armed
            and best_clean_cents is not None
            and move_now is not None
            and move_now <= best_clean_cents - giveback_ticks * size
        )
        return Decision(
            "FAVORABLE",
            "fire" if fire else "none",
            "",
            form,
            dwelled,
            giveback_ticks,
            best_clean_sequence,
            level,
            (),
            "TRAIL" if fire else "",
        )
    disarmed = target_ticks is not None and target_ticks <= round_trip
    fire = (
        not disarmed
        and target_ticks is not None
        and move_now is not None
        and move_now >= target_ticks * size
    )
    return Decision(
        "FAVORABLE",
        "fire" if fire else "none",
        "",
        form,
        dwelled,
        target_ticks if target_ticks is not None else 0,
        0,
        level,
        (),
        "TARGET" if fire else "",
    )


def worst_price(side: str, prices: list[int]) -> int | None:
    """§2:270-273. Long takes the min; short takes the max."""
    if not prices:
        return None
    if side == "LONG":
        return min(prices)
    return max(prices)


def path_rank(path: str) -> int:
    return _RANK[path]
