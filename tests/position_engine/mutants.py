"""Broken engines B1–B11. Selected by FEELIES_ENGINE or FEELIES_RAIL (P-22b).

Each class subclasses the reference and overrides the smallest method that
contains the defect. No process-global monkeypatch.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import NamedTuple

from feelies.core.events import MarkRailUpdate, NBBOQuote, RailOrientation
from tests.position_engine.reference import engine as ref
from tests.position_engine.reference.engine import Cell, Decision, PositionEngine
from tests.position_engine.reference.rail import (
    QuoteQuality,
    ReferenceRail,
    _Book,
    _cents,
    _extreme,
    _orientation,
    classify,
)


class Mutant(NamedTuple):
    """One broken engine and the catcher the kill runner executes."""

    bid: str
    seam: str
    dotted: str
    tests: tuple[str, ...]
    prefix: str
    shard: str


_M1 = "tests/position_engine/test_battery_m1_reproducibility.py"
_M4 = "tests/position_engine/test_battery_m4_side_correctness.py"
_M5 = (
    "tests/position_engine/test_battery_m5_precedence.py::test_m5_invalidation_at_take_profit",
    "tests/position_engine/test_battery_m5_precedence.py::test_m5_deadline_beyond_stop",
    "tests/position_engine/test_battery_m5_precedence.py::test_m5_gap_through_trail_and_stop",
)
_M6 = "tests/position_engine/test_battery_m6_injection_syn.py"
_M11 = "tests/position_engine/test_battery_m11_audit.py::test_m11_synthetic"


class MidRail(ReferenceRail):
    """B1. Paying and valuation marks are the integer midpoint.

    Battery row: member 4.
    Diff against ReferenceRail.on_quote, both orientations:
        mid = (paying + valuation) // 2
        paying = valuation = mid
    """

    def on_quote(self, quote: NBBOQuote) -> MarkRailUpdate:
        update = super().on_quote(quote)
        return replace(update, long=_mid(update.long), short=_mid(update.short))


def _mid(side: RailOrientation) -> RailOrientation:
    paying = side.paying_mark_cents
    valuation = side.valuation_mark_cents
    if paying is None or valuation is None:
        return side
    mid = (paying + valuation) // 2
    return replace(side, paying_mark_cents=mid, valuation_mark_cents=mid)


class FavorableWins(PositionEngine):
    """B2. A FAVORABLE path wins even when a higher path also fired.

    Battery row: member 5 (the tie constructions).
    Diff against PositionEngine._resolve, after the paths are recorded:
        if any path is FAVORABLE:
            winner = "FAVORABLE"
    """

    def _resolve(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        adverse: Decision,
        favorable: Decision,
    ) -> None:
        super()._resolve(cell, rail, orient, adverse, favorable)
        if any(path.path == "FAVORABLE" for path in cell.close_paths):
            cell.exit_reason = "FAVORABLE"
            cell.requirement_reason = ref._REQUIREMENT["FAVORABLE"]


class LevelPricedAdverse(PositionEngine):
    """B3. ADVERSE proposes the barrier level instead of the forced mark.

    Battery row: member 11, test_m11_gap_through.
    Diff against PositionEngine._resolve, the ADVERSE path price:
        - adverse.proposed
        + entry_cost // open_qty - adverse.drawn * sign
    """

    def _resolve(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        adverse: Decision,
        favorable: Decision,
    ) -> None:
        if adverse.outcome == "fire" and cell.open_qty >= 1:
            entry = cell.entry_cost() // cell.open_qty
            adverse = adverse._replace(proposed=entry - adverse.drawn * cell.sign)
        super()._resolve(cell, rail, orient, adverse, favorable)


class WallClockDeadline(PositionEngine):
    """B4. The horizon deadline is the wall clock plus T.

    Battery row: member 1.
    Diff against PositionEngine._birth:
        - deadline_ns = fill_timestamp_ns + T_ns
        + deadline_ns = time.time_ns() + T_ns
    """

    def _birth(
        self,
        event: object,
        policy: object,
        price: int,
        quantity: int,
        sequence: int,
    ) -> None:
        super()._birth(event, policy, price, quantity, sequence)  # type: ignore[arg-type]
        cell = self._open[(event.strategy_id, event.symbol)]  # type: ignore[attr-defined]
        horizon = policy.horizon  # type: ignore[attr-defined]
        cell.deadline_ns = time.time_ns() + horizon.T_ns


class AccumulatedMoves(PositionEngine):
    """B5. Snapshot moves are the running sum, not the current move.

    Battery row: member 11.
    Diff against PositionEngine._publish_snapshot:
        move_now += previous move_now (same for worst and forced)
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._move_sums: dict[str, list[int]] = {}

    def _publish_snapshot(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
        move_worst: int | None,
        move_forced: int | None,
    ) -> None:
        bucket = self._move_sums.setdefault(cell.cell_id, [0, 0, 0])
        summed: list[int | None] = []
        for index, value in enumerate((move_now, move_worst, move_forced)):
            if value is None:
                summed.append(None)
                continue
            bucket[index] += value
            summed.append(bucket[index])
        super()._publish_snapshot(cell, rail, orient, summed[0], summed[1], summed[2])


class ZeroSeed(PositionEngine):
    """B6. Extremes seed at zero on the first clean non-zero move.

    Battery row: member 11.
    Diff against Cell.update_extremes, called from _step (the cell is slotted):
        - seed = _extreme(move_now, ...)
        + seed = _extreme(0, ...)
    """

    def _step(self, cell: Cell, rail: MarkRailUpdate) -> None:
        orient = ref._orientation(cell, rail)
        cell.note_rail(rail, orient)
        now = ref.move_cents(
            cell.sign, orient.valuation_mark_cents, cell.open_qty, cell.entry_cost()
        )
        worst = ref.move_cents(
            cell.sign, orient.worst_side_mark_cents, cell.open_qty, cell.entry_cost()
        )
        forced = ref.move_cents(
            cell.sign, orient.forced_exit_mark_cents, cell.open_qty, cell.entry_cost()
        )
        self._seed_or_update(cell, rail, orient, now)
        self._publish_snapshot(cell, rail, orient, now, worst, forced)
        adverse, favorable = self._evaluate(cell, rail, orient, now, worst)
        if cell.state == "EXITING":
            adverse, favorable = ref._escalate(cell, adverse, favorable)
        self._publish_gate(cell, rail, adverse)
        self._publish_gate(cell, rail, favorable)
        if cell.state == "OPEN":
            self._resolve(cell, rail, orient, adverse, favorable)
        elif cell.pending_reemit and ref._exit_side_usable(orient):
            self._emit_requirement(cell, rail)

    def _seed_or_update(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
    ) -> None:
        if cell.seeded:
            cell.update_extremes(move_now, rail, orient)
            return
        clean = (
            move_now is not None
            and move_now != 0
            and not orient.valuation_side_absent
            and orient.valuation_mark_cents is not None
            and not rail.crossed
            and not rail.feed_gap_before
        )
        if not clean:
            return
        zero = ref._extreme(0, rail.quote_sequence, orient, rail, clean_peak=True)
        cell.best = zero
        cell.worst = zero
        cell.best_clean = zero
        cell.seeded = True


class HoldWhenAbsent(PositionEngine):
    """B7. An absent side holds ADVERSE instead of firing BLIND.

    Battery row: member 6.
    Diff against evaluate_adverse, applied in _evaluate (the caller):
        if a side is absent:
            adverse.outcome = "hold"
    """

    def _evaluate(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
        move_worst: int | None,
    ) -> tuple[Decision, Decision]:
        adverse, favorable = super()._evaluate(cell, rail, orient, move_now, move_worst)
        if orient.paying_side_absent or orient.valuation_side_absent:
            adverse = adverse._replace(outcome="hold", reason="", trigger="")
        return adverse, favorable


class QuotePeak(PositionEngine):
    """B8. The clean peak reads the raw NBBOQuote on an unusable rail event.

    Battery row: member 6, A2 on the V5 construction (J3).
    Under D-62 a rail-only drop of ``not rail.crossed`` matches the reference,
    because a crossed quote is absent. This class also subscribes to NBBOQuote.
    Diff against the reference, which does not subscribe to NBBOQuote:
        on a rail event whose valuation side is absent or crossed:
            best_clean <- raw valuation-side price
    """

    def attach(self) -> None:
        super().attach()
        self._bus.subscribe(NBBOQuote, self._on_raw_quote)

    def _on_raw_quote(self, quote: NBBOQuote) -> None:
        rail = self._last_rail.get(quote.symbol)
        if rail is None or rail.quote_sequence != quote.sequence:
            return
        if not (rail.crossed or _valuation_absent(quote, rail)):
            return
        for cell in list(self._open.values()):
            if cell.symbol != quote.symbol or cell.state != "OPEN":
                continue
            self._feed_raw_peak(cell, quote, rail)

    def _feed_raw_peak(self, cell: Cell, quote: NBBOQuote, rail: MarkRailUpdate) -> None:
        orient = ref._orientation(cell, rail)
        if not (orient.valuation_side_absent or rail.crossed):
            return
        raw_price = quote.bid if cell.side == "LONG" else quote.ask
        raw = ref.whole_cents(quote.symbol, raw_price)
        move = ref.move_cents(cell.sign, raw, cell.open_qty, cell.entry_cost())
        if move is None:
            return
        peak = ref._extreme(move, rail.quote_sequence, orient, rail, clean_peak=True)
        if not cell.seeded:
            cell.best = peak
            cell.worst = peak
            cell.best_clean = peak
            cell.seeded = True
            return
        if cell.best_clean is None or move > cell.best_clean.cents:
            cell.best_clean = peak


def _valuation_absent(quote: NBBOQuote, rail: MarkRailUpdate) -> bool:
    return rail.long.valuation_side_absent or rail.short.valuation_side_absent


class DoubleRequirement(PositionEngine):
    """B9. The first exit requirement is emitted twice, with no REJECTED ack.

    Battery row: member 5.
    Diff against PositionEngine._emit_requirement, after the first emit:
        if attempt == 1 and the cell is EXITING:
            clear live_requirement and emit again
    """

    def _emit_requirement(self, cell: Cell, rail: MarkRailUpdate) -> None:
        super()._emit_requirement(cell, rail)
        if cell.state == "EXITING" and cell.open_qty >= 1 and cell.attempt == 1:
            if cell.live_requirement:
                cell.live_requirement = False
                super()._emit_requirement(cell, rail)


class SecondSnapshot(PositionEngine):
    """B10. Resolve publishes a second snapshot for the same rail (D-103, J4).

    Battery row: member 1, the immutability clause.
    Diff against PositionEngine._resolve, after the reference resolve:
        publish a second PositionSnapshot at the same rail_sequence
    """

    def _publish_snapshot(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        move_now: int | None,
        move_worst: int | None,
        move_forced: int | None,
    ) -> None:
        self._last_snap = (cell, rail, orient, move_now, move_worst, move_forced)
        super()._publish_snapshot(cell, rail, orient, move_now, move_worst, move_forced)

    def _resolve(
        self,
        cell: Cell,
        rail: MarkRailUpdate,
        orient: RailOrientation,
        adverse: Decision,
        favorable: Decision,
    ) -> None:
        super()._resolve(cell, rail, orient, adverse, favorable)
        saved = getattr(self, "_last_snap", None)
        if saved is None or saved[0] is not cell:
            return
        _cell, saved_rail, saved_orient, now, worst, forced = saved
        bumped = None if now is None else now + 1
        PositionEngine._publish_snapshot(
            self, cell, saved_rail, saved_orient, bumped, worst, forced
        )


class LazyTrimRail(ReferenceRail):
    """B11. The dwell window is never trimmed.

    Battery row: member 2, the D>0 clause.
    Diff against ReferenceRail.on_quote:
        - cutoff = timestamp - self.dwell_ns
        - book.window = [row for row in book.window if row[0] > cutoff or row[0] == timestamp]
    ``dwell_ns`` still feeds the dwelled mark and ``warmed_up``.
    """

    def on_quote(self, quote: NBBOQuote) -> MarkRailUpdate:
        timestamp = quote.exchange_timestamp_ns
        bid_cents = _cents(quote.symbol, quote.bid)
        ask_cents = _cents(quote.symbol, quote.ask)
        book = self._books.get(quote.symbol)
        if book is None:
            book = _Book()
            self._books[quote.symbol] = book
        if book.first_ns is None:
            book.first_ns = timestamp
        usable = (
            classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID
        )
        if usable:
            if book.bid != bid_cents:
                book.bid = bid_cents
                book.bid_changed_ns = timestamp
            if book.ask != ask_cents:
                book.ask = ask_cents
                book.ask_changed_ns = timestamp
            book.last_usable_ns = timestamp
        quiet = 0 if book.prev_ns is None else timestamp - book.prev_ns
        book.prev_ns = timestamp
        if usable:
            absent_for = 0
        elif book.last_usable_ns is not None:
            absent_for = timestamp - book.last_usable_ns
        else:
            absent_for = timestamp - book.first_ns
        book.window.append((timestamp, book.bid, book.ask, usable))
        bid_age = 0 if book.bid_changed_ns is None else timestamp - book.bid_changed_ns
        ask_age = 0 if book.ask_changed_ns is None else timestamp - book.ask_changed_ns
        if book.bid is None or book.ask is None:
            long_worst = None
            short_worst = None
        else:
            long_worst = min(book.bid, book.ask)
            short_worst = max(book.bid, book.ask)
        slip = self.slippage_ticks
        long_forced = None if long_worst is None else long_worst - slip
        short_forced = None if short_worst is None else short_worst + slip
        long_dwelled = _extreme(book.window, index=1, pick=min)
        short_dwelled = _extreme(book.window, index=2, pick=max)
        clean = all(row[3] for row in book.window)
        warmed = self.dwell_ns == 0 or timestamp - book.first_ns >= self.dwell_ns
        absent = not usable
        long_side = _orientation(
            paying=book.ask,
            valuation=book.bid,
            paying_size=quote.ask_size,
            valuation_size=quote.bid_size,
            paying_age=ask_age,
            valuation_age=bid_age,
            absent=absent,
            absent_for=absent_for,
            worst=long_worst,
            forced=long_forced,
            dwelled=long_dwelled,
            clean=clean,
        )
        short_side = _orientation(
            paying=book.bid,
            valuation=book.ask,
            paying_size=quote.bid_size,
            valuation_size=quote.ask_size,
            paying_age=bid_age,
            valuation_age=ask_age,
            absent=absent,
            absent_for=absent_for,
            worst=short_worst,
            forced=short_forced,
            dwelled=short_dwelled,
            clean=clean,
        )
        return MarkRailUpdate(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._seq.next(),
            source_layer="PORTFOLIO",
            symbol=quote.symbol,
            quote_sequence=quote.sequence,
            event_timestamp_ns=timestamp,
            long=long_side,
            short=short_side,
            symbol_quiet_ns=quiet,
            locked=bid_cents == ask_cents,
            crossed=bid_cents > ask_cents,
            feed_gap_before=False,
            warmed_up=warmed,
        )


REGISTRY: dict[str, Mutant] = {
    "B1": Mutant("B1", "rail", f"{__name__}.MidRail", (_M4,), "assert", "A"),
    "B2": Mutant("B2", "engine", f"{__name__}.FavorableWins", _M5, "exit reason", "B"),
    "B3": Mutant(
        "B3",
        "engine",
        f"{__name__}.LevelPricedAdverse",
        ("tests/position_engine/test_battery_m11_audit.py::test_m11_gap_through",),
        "M11: proposed",
        "B",
    ),
    "B4": Mutant("B4", "engine", f"{__name__}.WallClockDeadline", (_M1,), "assert", "A"),
    "B5": Mutant(
        "B5", "engine", f"{__name__}.AccumulatedMoves", (_M11,), "M11: move_now_cents", "B"
    ),
    "B6": Mutant("B6", "engine", f"{__name__}.ZeroSeed", (_M11,), "M11: extreme seeded", "B"),
    "B7": Mutant("B7", "engine", f"{__name__}.HoldWhenAbsent", (_M6,), "A5:", "B"),
    "B8": Mutant(
        "B8",
        "engine",
        f"{__name__}.QuotePeak",
        ("tests/position_engine/test_battery_m6_injection_syn.py::test_m6_a2_v5",),
        "A2:",
        "B",
    ),
    "B9": Mutant(
        "B9",
        "engine",
        f"{__name__}.DoubleRequirement",
        _M5,
        "requirement re-emitted without REJECTED",
        "B",
    ),
    "B10": Mutant(
        "B10",
        "engine",
        f"{__name__}.SecondSnapshot",
        (_M1,),
        "duplicate PositionSnapshot",
        "A",
    ),
    "B11": Mutant(
        "B11",
        "rail",
        f"{__name__}.LazyTrimRail",
        (
            "tests/position_engine/test_battery_m2_no_lookahead.py"
            "::test_m2_dwell_favorable_ignores_stale_cross",
        ),
        "M2:",
        "B",
    ),
}
