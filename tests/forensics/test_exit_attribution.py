"""Fail-first expectations for the P-95 attribution diff (D-249)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
)
from feelies.forensics.exit_attribution import (
    ArmEpisode,
    ArmEvents,
    AttributionError,
    AttributionReport,
    ClassTotals,
    EpisodeDiff,
    Fill,
    attribute,
)

_ALPHA = "alpha"


def _sig(
    ts: int,
    seq: int,
    direction: SignalDirection,
    cid: str,
    *,
    symbol: str = "SYN",
) -> Signal:
    return Signal(
        timestamp_ns=ts,
        correlation_id=cid,
        sequence=seq,
        symbol=symbol,
        strategy_id=_ALPHA,
        direction=direction,
        strength=1.0,
        edge_estimate_bps=9.0,
    )


def _ord(
    ts: int,
    seq: int,
    oid: str,
    side: Side,
    qty: int,
    cid: str,
    *,
    reason: str = "",
    symbol: str = "SYN",
    is_short: bool = False,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=ts,
        correlation_id=cid,
        sequence=seq,
        order_id=oid,
        symbol=symbol,
        strategy_id=_ALPHA,
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        reason=reason,
        is_short=is_short,
    )


def _ack(
    ts: int,
    seq: int,
    oid: str,
    qty: int,
    price: str,
    fee: str,
    *,
    symbol: str = "SYN",
) -> OrderAck:
    return OrderAck(
        timestamp_ns=ts,
        correlation_id=oid,
        sequence=seq,
        order_id=oid,
        symbol=symbol,
        status=OrderAckStatus.FILLED,
        filled_quantity=qty,
        fill_price=Decimal(price),
        fees=Decimal(fee),
    )


def _fill(price: str, qty: int, ts: int, fee: str, seq: int) -> Fill:
    return Fill(
        fill_price=Decimal(price),
        filled_quantity=qty,
        timestamp_ns=ts,
        fees=Decimal(fee),
        sequence=seq,
    )


def _trade(
    ts_order: int,
    ts_fill: int,
    seq_order: int,
    seq_fill: int,
    oid: str,
    side: Side,
    qty: int,
    price: str,
    fee: str,
    cid: str,
    *,
    reason: str = "",
    symbol: str = "SYN",
    is_short: bool = False,
) -> tuple[OrderRequest, OrderAck, Fill]:
    return (
        _ord(
            ts_order,
            seq_order,
            oid,
            side,
            qty,
            cid,
            reason=reason,
            symbol=symbol,
            is_short=is_short,
        ),
        _ack(ts_fill, seq_fill, oid, qty, price, fee, symbol=symbol),
        _fill(price, qty, ts_fill, fee, seq_fill),
    )


def _quote(ts: int, seq: int, bid: str, ask: str, *, symbol: str = "SYN") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        exchange_timestamp_ns=ts,
        correlation_id=f"q-{symbol}-{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
    )


def _legs(fills: tuple[Fill, ...]) -> tuple[PositionFillLeg, ...]:
    return tuple(
        PositionFillLeg(
            price_cents=int(item.fill_price * 100),
            quantity=item.filled_quantity,
            timestamp_ns=item.timestamp_ns,
            sequence=item.sequence,
        )
        for item in fills
    )


def _pc(
    entries: tuple[Fill, ...],
    exits: tuple[Fill, ...],
    reason: str,
    *,
    side: str = "LONG",
    worst: PositionExtreme | None = None,
    symbol: str = "SYN",
    ts: int = 1,
    seq: int = 1,
) -> PositionClosed:
    return PositionClosed(
        timestamp_ns=ts,
        correlation_id=f"close-{symbol}-{seq}",
        sequence=seq,
        symbol=symbol,
        strategy_id=_ALPHA,
        cell_id=f"{symbol}|{_ALPHA}|{seq}",
        side=side,
        declared_archetype="test",
        entry_fills=_legs(entries),
        exit_fills=_legs(exits),
        entry_spread_ticks=1,
        horizon_deadline_ns=0,
        drawn_level_ticks=0,
        exit_reason=reason,
        triggered_paths=(),
        worst=worst,
        closed_on_stale_data=False,
        exited_on_unusable_data=False,
        lived_through_feed_gap=False,
        first_event_exit=False,
        stop_inside_round_trip=False,
        target_inside_round_trip=False,
        uncalibrated=True,
        supersedes="",
    )


def _arm(
    signals: tuple[Signal, ...],
    orders: tuple[OrderRequest, ...],
    acks: tuple[OrderAck, ...],
    quotes: tuple[NBBOQuote, ...],
    verdicts: tuple[RiskVerdict, ...] = (),
    closed: tuple[PositionClosed, ...] = (),
) -> ArmEvents:
    return ArmEvents(
        signals=signals,
        order_requests=orders,
        order_acks=acks,
        risk_verdicts=verdicts,
        quotes=quotes,
        position_closed=closed,
    )


def _episode(
    signal: Signal,
    side: str,
    entries: tuple[Fill, ...],
    exits: tuple[Fill, ...],
    net: str,
    holding: int,
) -> ArmEpisode:
    return ArmEpisode(
        symbol=signal.symbol,
        strategy_id=signal.strategy_id,
        entry_signal=signal,
        side=side,
        entry_fills=entries,
        exit_fills=exits,
        net_after_fees=Decimal(net),
        holding_time_ns=holding,
    )


def _diff(
    kind: str,
    legacy_reason: str,
    engine_reason: str,
    explanation: str,
    legacy: ArmEpisode | None,
    engine: ArmEpisode | None,
    legacy_mae: str | None,
    engine_mae: str | None,
    worst: PositionExtreme | None,
) -> EpisodeDiff:
    return EpisodeDiff(
        episode_class=kind,
        legacy_reason=legacy_reason,
        engine_reason=engine_reason,
        explanation=explanation,
        legacy=legacy,
        engine=engine,
        legacy_mae=None if legacy_mae is None else Decimal(legacy_mae),
        engine_mae=None if engine_mae is None else Decimal(engine_mae),
        engine_worst=worst,
    )


def _report(
    diffs: tuple[EpisodeDiff, ...],
    totals: tuple[tuple[str, int, str, str], ...],
) -> AttributionReport:
    return AttributionReport(
        diffs=diffs,
        totals=tuple(
            ClassTotals(
                episode_class=name,
                count=count,
                legacy_net=Decimal(legacy_net),
                engine_net=Decimal(engine_net),
            )
            for name, count, legacy_net, engine_net in totals
        ),
        day_count=1,
        label="descriptive",
    )


def _check(legacy: ArmEvents, engine: ArmEvents, expected: AttributionReport) -> None:
    assert attribute(legacy, engine, day_count=1) == expected


def _verdict(ts: int, seq: int, cid: str, action: RiskAction, reason: str) -> RiskVerdict:
    return RiskVerdict(
        timestamp_ns=ts,
        correlation_id=cid,
        sequence=seq,
        symbol="SYN",
        action=action,
        reason=reason,
    )


def test_same() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.50", "0.05", "x1", reason="TARGET"
    )
    zero = OrderAck(
        timestamp_ns=950,
        correlation_id="e1",
        sequence=0,
        order_id="e1",
        symbol="SYN",
        status=OrderAckStatus.ACKNOWLEDGED,
        filled_quantity=0,
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "9.90", "9.91"),
        _quote(1500, 3, "9.80", "9.81"),
        _quote(2000, 4, "9.95", "9.96"),
    )
    orders = (entry_order, exit_order)
    acks = (zero, entry_ack, exit_ack)
    episode = _episode(sig, "LONG", (entry,), (exit_fill,), "4.90", 1000)
    _check(
        _arm((sig, sig), orders, acks, quotes),
        _arm((sig,), orders, acks, quotes, closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),)),
        _report(
            (_diff("SAME", "TARGET", "FAVORABLE", "", episode, episode, "0.20", "0.20", None),),
            (("SAME", 1, "4.90", "4.90"),),
        ),
    )


def test_exit_changed() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    legacy_order, legacy_ack, legacy_exit = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.50", "0.05", "x1", reason="OPERATOR"
    )
    engine_order, engine_ack, engine_exit = _trade(
        1700,
        1800,
        2,
        2,
        "x2",
        Side.SELL,
        10,
        "10.40",
        "0.04",
        "x2",
        reason="FAVORABLE_EXCURSION",
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "9.90", "9.91"),
        _quote(1500, 3, "9.85", "9.86"),
        _quote(1900, 4, "9.70", "9.71"),
        _quote(2000, 5, "9.95", "9.96"),
    )
    worst = PositionExtreme(
        cents=-15,
        sequence=9,
        valuation_age_ns=50,
        valuation_side_absent=False,
        crossed=False,
        feed_gap_before=False,
    )
    legacy_ep = _episode(sig, "LONG", (entry,), (legacy_exit,), "4.90", 1000)
    engine_ep = _episode(sig, "LONG", (entry,), (engine_exit,), "3.91", 800)
    _check(
        _arm((sig,), (entry_order, legacy_order), (entry_ack, legacy_ack), quotes),
        _arm(
            (sig,),
            (entry_order, engine_order),
            (entry_ack, engine_ack),
            quotes,
            closed=(_pc((entry,), (engine_exit,), "FAVORABLE", worst=worst),),
        ),
        _report(
            (
                _diff(
                    "EXIT_CHANGED",
                    "OPERATOR",
                    "FAVORABLE",
                    "",
                    legacy_ep,
                    engine_ep,
                    "0.30",
                    "0.15",
                    worst,
                ),
            ),
            (("EXIT_CHANGED", 1, "4.90", "3.91"),),
        ),
    )


def test_entry_changed() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    legacy_entry_order, legacy_entry_ack, legacy_entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    engine_entry_order, engine_entry_ack, engine_entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.05", "0.05", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.50", "0.05", "x1", reason="OUT"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "9.80", "9.81"),
        _quote(2000, 3, "9.90", "9.91"),
    )
    legacy_ep = _episode(sig, "LONG", (legacy_entry,), (exit_fill,), "4.90", 1000)
    engine_ep = _episode(sig, "LONG", (engine_entry,), (exit_fill,), "4.40", 1000)
    _check(
        _arm((sig,), (legacy_entry_order, exit_order), (legacy_entry_ack, exit_ack), quotes),
        _arm(
            (sig,),
            (engine_entry_order, exit_order),
            (engine_entry_ack, exit_ack),
            quotes,
            closed=(_pc((engine_entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (
                _diff(
                    "ENTRY_CHANGED",
                    "OUT",
                    "FAVORABLE",
                    "",
                    legacy_ep,
                    engine_ep,
                    "0.20",
                    "0.25",
                    None,
                ),
            ),
            (("ENTRY_CHANGED", 1, "4.90", "4.40"),),
        ),
    )


def test_legacy_only_engine_in_position() -> None:
    first = _sig(1000, 1, SignalDirection.LONG, "s1")
    second = _sig(3000, 2, SignalDirection.LONG, "s2")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    legacy_exit_order, legacy_exit_ack, legacy_exit = _trade(
        2000, 2100, 2, 2, "x1", Side.SELL, 10, "10.10", "0.01", "none1", reason="FLAT_NOW"
    )
    second_order, second_ack, second_entry = _trade(
        3050, 3100, 3, 3, "e2", Side.BUY, 10, "10.20", "0.01", "s2"
    )
    done_order, done_ack, done_exit = _trade(
        3900, 4100, 4, 4, "x2", Side.SELL, 10, "10.30", "0.01", "none2", reason="DONE"
    )
    engine_exit_order, engine_exit_ack, engine_exit = _trade(
        5000,
        5100,
        5,
        5,
        "x3",
        Side.SELL,
        10,
        "10.40",
        "0.02",
        "none3",
        reason="FAVORABLE_EXCURSION",
    )
    quotes = (
        _quote(900, 1, "8.00", "8.01"),
        _quote(1100, 2, "9.90", "9.91"),
        _quote(2100, 3, "9.90", "9.91"),
        _quote(3100, 4, "10.00", "10.01"),
        _quote(4100, 5, "10.10", "10.11"),
        _quote(5100, 6, "10.20", "10.21"),
    )
    worst = PositionExtreme(
        cents=-10,
        sequence=2,
        valuation_age_ns=200,
        valuation_side_absent=False,
        crossed=False,
        feed_gap_before=False,
    )
    shared = _episode(first, "LONG", (entry,), (legacy_exit,), "0.98", 1000)
    engine_shared = _episode(first, "LONG", (entry,), (engine_exit,), "3.97", 4000)
    only = _episode(second, "LONG", (second_entry,), (done_exit,), "0.98", 1000)
    _check(
        _arm(
            (first, second),
            (entry_order, legacy_exit_order, second_order, done_order),
            (entry_ack, legacy_exit_ack, second_ack, done_ack),
            quotes,
        ),
        _arm(
            (first, second),
            (entry_order, engine_exit_order),
            (entry_ack, engine_exit_ack),
            quotes,
            closed=(_pc((entry,), (engine_exit,), "FAVORABLE", worst=worst),),
        ),
        _report(
            (
                _diff(
                    "EXIT_CHANGED",
                    "FLAT_NOW",
                    "FAVORABLE",
                    "",
                    shared,
                    engine_shared,
                    "0.10",
                    "0.10",
                    worst,
                ),
                _diff(
                    "LEGACY_ONLY",
                    "DONE",
                    "",
                    "ENGINE_IN_POSITION",
                    only,
                    None,
                    "0.20",
                    None,
                    None,
                ),
            ),
            (
                ("EXIT_CHANGED", 1, "0.98", "3.97"),
                ("LEGACY_ONLY", 1, "0.98", "0.00"),
            ),
        ),
    )


def test_legacy_only_risk_reject() -> None:
    sig = _sig(1000, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.20", "0.05", "x1", reason="OUT"
    )
    quotes = (
        _quote(500, 1, "8.00", "8.01"),
        _quote(1100, 2, "9.50", "9.51"),
        _quote(2000, 3, "9.50", "9.51"),
    )
    episode = _episode(sig, "LONG", (entry,), (exit_fill,), "1.90", 900)
    rejected = _verdict(1000, 1, "s1", RiskAction.REJECT, "too big")
    _check(
        _arm((sig,), (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm((sig,), (), (), quotes, verdicts=(rejected,)),
        _report(
            (
                _diff(
                    "LEGACY_ONLY",
                    "OUT",
                    "",
                    "RISK:too big",
                    episode,
                    None,
                    "0.50",
                    None,
                    None,
                ),
            ),
            (("LEGACY_ONLY", 1, "1.90", "0.00"),),
        ),
    )


def test_engine_only_legacy_in_position() -> None:
    first = _sig(1000, 1, SignalDirection.LONG, "s1")
    second = _sig(4000, 2, SignalDirection.LONG, "s2")
    other = _sig(100, 1, SignalDirection.LONG, "z", symbol="ZZZ")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "b1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.10", "0.01", "x1", reason="OUT"
    )
    again_order, again_ack, again = _trade(
        4050, 4100, 3, 3, "b2", Side.BUY, 10, "10.20", "0.01", "s2"
    )
    done_order, done_ack, done = _trade(
        4900, 5000, 4, 4, "x2", Side.SELL, 10, "10.30", "0.01", "x2", reason="OUT2"
    )
    z_entry_order, z_entry_ack, z_entry = _trade(
        150, 200, 11, 11, "zb", Side.BUY, 5, "20.00", "0.01", "z", symbol="ZZZ"
    )
    z_exit_order, z_exit_ack, z_exit = _trade(
        250,
        300,
        12,
        12,
        "zx",
        Side.SELL,
        5,
        "20.40",
        "0.01",
        "zx",
        reason="TARGET",
        symbol="ZZZ",
    )
    quotes = (
        _quote(100, 1, "9.00", "9.01"),
        _quote(1100, 2, "9.90", "9.91"),
        _quote(2000, 3, "9.80", "9.81"),
        _quote(4100, 4, "10.00", "10.01"),
        _quote(5000, 5, "10.10", "10.11"),
        _quote(6000, 6, "10.00", "10.01"),
        _quote(50, 10, "19.00", "19.01", symbol="ZZZ"),
        _quote(200, 11, "19.50", "19.51", symbol="ZZZ"),
        _quote(300, 12, "19.50", "19.51", symbol="ZZZ"),
        _quote(1500, 13, "1.00", "1.01", symbol="ZZZ"),
        _quote(9000, 14, "19.00", "19.01", symbol="ZZZ"),
    )
    signals = (first, second, other)
    z_orders = (z_entry_order, z_exit_order)
    z_acks = (z_entry_ack, z_exit_ack)
    worst = PositionExtreme(
        cents=-20,
        sequence=3,
        valuation_age_ns=900,
        valuation_side_absent=False,
        crossed=False,
        feed_gap_before=False,
    )
    legacy_open = _episode(first, "LONG", (entry,), (), "-0.01", 4900)
    engine_closed = _episode(first, "LONG", (entry,), (exit_fill,), "0.98", 900)
    engine_only = _episode(second, "LONG", (again,), (done,), "0.98", 900)
    same = _episode(other, "LONG", (z_entry,), (z_exit,), "1.98", 100)
    closed = (
        _pc((again,), (done,), "FAVORABLE", seq=2),
        _pc((z_entry,), (z_exit,), "FAVORABLE", symbol="ZZZ", seq=3),
        _pc((entry,), (exit_fill,), "HORIZON", worst=worst, seq=1),
    )
    _check(
        _arm(signals, (entry_order, *z_orders), (entry_ack, *z_acks), quotes),
        _arm(
            signals,
            (entry_order, exit_order, again_order, done_order, *z_orders),
            (entry_ack, exit_ack, again_ack, done_ack, *z_acks),
            quotes,
            closed=closed,
        ),
        _report(
            (
                _diff(
                    "EXIT_CHANGED",
                    "END_OF_TAPE",
                    "HORIZON",
                    "",
                    legacy_open,
                    engine_closed,
                    "0.20",
                    "0.20",
                    worst,
                ),
                _diff(
                    "ENGINE_ONLY",
                    "",
                    "FAVORABLE",
                    "LEGACY_IN_POSITION",
                    None,
                    engine_only,
                    None,
                    "0.20",
                    None,
                ),
                _diff("SAME", "TARGET", "FAVORABLE", "", same, same, "0.50", "0.50", None),
            ),
            (
                ("SAME", 1, "1.98", "1.98"),
                ("EXIT_CHANGED", 1, "-0.01", "0.98"),
                ("ENGINE_ONLY", 1, "0.00", "0.98"),
            ),
        ),
    )


def test_unexplained() -> None:
    sig = _sig(1000, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "11.00", "0.05", "x1", reason="OUT"
    )
    quotes = (
        _quote(500, 1, "8.00", "8.01"),
        _quote(1100, 2, "9.00", "9.01"),
        _quote(2000, 3, "9.50", "9.51"),
    )
    episode = _episode(sig, "LONG", (entry,), (exit_fill,), "9.90", 900)
    allowed = _verdict(1000, 1, "s1", RiskAction.ALLOW, "within limits")
    _check(
        _arm((sig,), (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm((sig,), (), (), quotes, verdicts=(allowed,)),
        _report(
            (_diff("UNEXPLAINED", "OUT", "", "", episode, None, "1.00", None, None),),
            (("UNEXPLAINED", 1, "9.90", "0.00"),),
        ),
    )


def test_legacy_reason_order_reason() -> None:
    entered = _sig(1000, 1, SignalDirection.LONG, "s1")
    flat = _sig(1800, 2, SignalDirection.FLAT, "flat1")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900,
        2000,
        2,
        2,
        "x1",
        Side.SELL,
        10,
        "10.00",
        "0.01",
        "flat1",
        reason="HAZARD_SPIKE",
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1100, 2, "10.00", "10.01"),
        _quote(2000, 3, "10.00", "10.01"),
    )
    episode = _episode(entered, "LONG", (entry,), (exit_fill,), "-0.02", 900)
    signals = (entered, flat)
    _check(
        _arm(signals, (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm(
            signals,
            (entry_order, exit_order),
            (entry_ack, exit_ack),
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "HAZARD_SPIKE",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "-0.02", "-0.02"),),
        ),
    )


def test_legacy_reason_signal_flat() -> None:
    entered = _sig(1000, 1, SignalDirection.LONG, "s1")
    flat = _sig(1800, 2, SignalDirection.FLAT, "flat1")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.00", "0.01", "flat1"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1100, 2, "10.00", "10.01"),
        _quote(2000, 3, "10.00", "10.01"),
    )
    episode = _episode(entered, "LONG", (entry,), (exit_fill,), "-0.02", 900)
    signals = (entered, flat)
    _check(
        _arm(signals, (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm(
            signals,
            (entry_order, exit_order),
            (entry_ack, exit_ack),
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "SIGNAL_FLAT",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "-0.02", "-0.02"),),
        ),
    )


def test_legacy_reason_signal_reverse() -> None:
    entered = _sig(1000, 1, SignalDirection.LONG, "s1")
    short = _sig(1800, 2, SignalDirection.SHORT, "s2")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.00", "0.01", "s2"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1100, 2, "10.00", "10.01"),
        _quote(2000, 3, "10.00", "10.01"),
    )
    episode = _episode(entered, "LONG", (entry,), (exit_fill,), "-0.02", 900)
    signals = (entered, short)
    _check(
        _arm(signals, (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm(
            signals,
            (entry_order, exit_order),
            (entry_ack, exit_ack),
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "SIGNAL_REVERSE",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "-0.02", "-0.02"),),
        ),
    )


def test_legacy_reason_unattributed() -> None:
    entered = _sig(1000, 1, SignalDirection.LONG, "s1")
    flat = _sig(1800, 2, SignalDirection.FLAT, "flat1")
    entry_order, entry_ack, entry = _trade(
        1050, 1100, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.00", "0.01", "ghost"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1100, 2, "10.00", "10.01"),
        _quote(2000, 3, "10.00", "10.01"),
    )
    episode = _episode(entered, "LONG", (entry,), (exit_fill,), "-0.02", 900)
    signals = (entered, flat)
    _check(
        _arm(signals, (entry_order, exit_order), (entry_ack, exit_ack), quotes),
        _arm(
            signals,
            (entry_order, exit_order),
            (entry_ack, exit_ack),
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "UNATTRIBUTED",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "-0.02", "-0.02"),),
        ),
    )


def test_legacy_reason_end_of_tape() -> None:
    entered = _sig(900, 1, SignalDirection.LONG, "s1")
    flat = _sig(1800, 2, SignalDirection.FLAT, "flat1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.25", "s1"
    )
    quotes = (
        _quote(100, 1, "8.00", "8.01"),
        _quote(1000, 2, "9.50", "9.51"),
        _quote(5000, 3, "9.60", "9.61"),
    )
    episode = _episode(entered, "LONG", (entry,), (), "-0.25", 4000)
    signals = (entered, flat)
    _check(
        _arm(signals, (entry_order,), (entry_ack,), quotes),
        _arm(
            signals,
            (entry_order,),
            (entry_ack,),
            quotes,
            closed=(_pc((entry,), (), "END_OF_TAPE"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "END_OF_TAPE",
                    "END_OF_TAPE",
                    "",
                    episode,
                    episode,
                    "0.50",
                    "0.50",
                    None,
                ),
            ),
            (("SAME", 1, "-0.25", "-0.25"),),
        ),
    )


def test_zero_crossing_split() -> None:
    # The 150-share fee 0.15 is split 100:50 into 0.10 and 0.05.
    first = _sig(1000, 1, SignalDirection.LONG, "s1")
    second = _sig(2000, 2, SignalDirection.SHORT, "s2")
    third = _sig(3000, 3, SignalDirection.FLAT, "s3")
    buy_order, buy_ack, buy = _trade(1050, 1100, 1, 1, "b1", Side.BUY, 100, "10.00", "0.01", "s1")
    sell_order = _ord(2050, 2, "s1o", Side.SELL, 150, "s2", reason="CROSS")
    sell_ack = _ack(2100, 2, "s1o", 150, "12.00", "0.15")
    cover_order, cover_ack, cover = _trade(
        3050, 3100, 3, 3, "b2", Side.BUY, 50, "11.00", "0.01", "s3"
    )
    close_long = _fill("12.00", 100, 2100, "0.10", 2)
    open_short = _fill("12.00", 50, 2100, "0.05", 2)
    quotes = (
        _quote(1000, 1, "8.00", "13.50"),
        _quote(1100, 2, "9.50", "13.00"),
        _quote(1500, 3, "9.00", "12.00"),
        _quote(2100, 4, "9.80", "12.10"),
        _quote(2500, 5, "10.00", "12.40"),
        _quote(3100, 6, "10.00", "12.00"),
        _quote(4000, 7, "10.00", "13.00"),
    )
    worst = PositionExtreme(
        cents=-100,
        sequence=3,
        valuation_age_ns=400,
        valuation_side_absent=False,
        crossed=False,
        feed_gap_before=False,
    )
    long_ep = _episode(first, "LONG", (buy,), (close_long,), "199.89", 1000)
    short_ep = _episode(second, "SHORT", (open_short,), (cover,), "49.94", 1000)
    signals = (first, second, third)
    orders = (buy_order, sell_order, cover_order)
    acks = (buy_ack, sell_ack, cover_ack)
    closed = (
        _pc((open_short,), (cover,), "FAVORABLE", side="SHORT", seq=2),
        _pc((buy,), (close_long,), "EXTERNAL:SIGN_FLIP", worst=worst, seq=1),
    )
    _check(
        _arm(signals, orders, acks, quotes),
        _arm(signals, orders, acks, quotes, closed=closed),
        _report(
            (
                _diff(
                    "SAME",
                    "CROSS",
                    "EXTERNAL:SIGN_FLIP",
                    "",
                    long_ep,
                    long_ep,
                    "1.00",
                    "1.00",
                    worst,
                ),
                _diff(
                    "SAME",
                    "SIGNAL_FLAT",
                    "FAVORABLE",
                    "",
                    short_ep,
                    short_ep,
                    "0.40",
                    "0.40",
                    None,
                ),
            ),
            (("SAME", 2, "249.83", "249.83"),),
        ),
    )


def test_mae_long() -> None:
    sig = _sig(1900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        1950, 2000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        3900, 4000, 2, 2, "x1", Side.SELL, 10, "10.10", "0.01", "x1", reason="TARGET"
    )
    quotes = (
        _quote(1000, 1, "8.00", "8.01"),
        _quote(2000, 2, "9.70", "9.71"),
        _quote(3000, 3, "9.40", "9.41"),
        _quote(4000, 4, "9.90", "9.91"),
        _quote(5000, 5, "9.00", "9.01"),
    )
    episode = _episode(sig, "LONG", (entry,), (exit_fill,), "0.98", 2000)
    orders = (entry_order, exit_order)
    acks = (entry_ack, exit_ack)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm(
            (sig,),
            orders,
            acks,
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (_diff("SAME", "TARGET", "FAVORABLE", "", episode, episode, "0.60", "0.60", None),),
            (("SAME", 1, "0.98", "0.98"),),
        ),
    )


def test_mae_short() -> None:
    sig = _sig(1900, 1, SignalDirection.SHORT, "s1")
    entry_order, entry_ack, entry = _trade(
        1950,
        2000,
        1,
        1,
        "e1",
        Side.SELL,
        10,
        "10.00",
        "0.01",
        "s1",
        is_short=True,
    )
    exit_order, exit_ack, exit_fill = _trade(
        3900, 4000, 2, 2, "x1", Side.BUY, 10, "9.80", "0.01", "x1", reason="COVER"
    )
    quotes = (
        _quote(1000, 1, "9.00", "12.00"),
        _quote(2000, 2, "9.90", "10.10"),
        _quote(3000, 3, "9.70", "10.50"),
        _quote(4000, 4, "9.60", "10.20"),
        _quote(5000, 5, "9.00", "11.00"),
    )
    episode = _episode(sig, "SHORT", (entry,), (exit_fill,), "1.98", 2000)
    orders = (entry_order, exit_order)
    acks = (entry_ack, exit_ack)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm(
            (sig,),
            orders,
            acks,
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE", side="SHORT"),),
        ),
        _report(
            (_diff("SAME", "COVER", "FAVORABLE", "", episode, episode, "0.50", "0.50", None),),
            (("SAME", 1, "1.98", "1.98"),),
        ),
    )


def test_net_after_fees() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 100, "10.00", "1.00", "s1"
    )
    exit_order, exit_ack, exit_fill = _trade(
        2400, 2500, 2, 2, "x1", Side.SELL, 100, "10.25", "1.50", "x1", reason="TARGET"
    )
    quotes = (
        _quote(100, 1, "9.00", "9.01"),
        _quote(1000, 2, "10.00", "10.01"),
        _quote(2500, 3, "10.00", "10.01"),
    )
    episode = _episode(sig, "LONG", (entry,), (exit_fill,), "22.50", 1500)
    orders = (entry_order, exit_order)
    acks = (entry_ack, exit_ack)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm(
            (sig,),
            orders,
            acks,
            quotes,
            closed=(_pc((entry,), (exit_fill,), "FAVORABLE"),),
        ),
        _report(
            (_diff("SAME", "TARGET", "FAVORABLE", "", episode, episode, "0.00", "0.00", None),),
            (("SAME", 1, "22.50", "22.50"),),
        ),
    )


def _one_fill_arms(
    *,
    legacy_signals: tuple[Signal, ...],
    engine_signals: tuple[Signal, ...],
    cid: str,
    closed: tuple[PositionClosed, ...] | None = None,
) -> tuple[ArmEvents, ArmEvents]:
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", cid
    )
    exit_order, exit_ack, exit_fill = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.50", "0.05", "x1", reason="TARGET"
    )
    quotes = (_quote(1000, 1, "10.00", "10.01"), _quote(2000, 2, "10.00", "10.01"))
    orders = (entry_order, exit_order)
    acks = (entry_ack, exit_ack)
    if closed is None:
        closed = (_pc((entry,), (exit_fill,), "FAVORABLE"),)
    return (
        _arm(legacy_signals, orders, acks, quotes),
        _arm(engine_signals, orders, acks, quotes, closed=closed),
    )


def test_manifest_hash_difference_matches() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    other = dataclasses.replace(sig, metadata={"manifest_hash": "engine"})
    legacy, engine = _one_fill_arms(legacy_signals=(sig,), engine_signals=(other,), cid="s1")
    entry = _fill("10.00", 10, 1000, "0.05", 1)
    exit_fill = _fill("10.50", 10, 2000, "0.05", 2)
    legacy_episode = _episode(sig, "LONG", (entry,), (exit_fill,), "4.90", 1000)
    engine_episode = _episode(other, "LONG", (entry,), (exit_fill,), "4.90", 1000)
    _check(
        legacy,
        engine,
        _report(
            (
                _diff(
                    "SAME",
                    "TARGET",
                    "FAVORABLE",
                    "",
                    legacy_episode,
                    engine_episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "4.90", "4.90"),),
        ),
    )


def test_refuses_signal_metadata_other_than_manifest_hash() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    other = dataclasses.replace(sig, metadata={"note": "x"})
    legacy, engine = _one_fill_arms(legacy_signals=(sig,), engine_signals=(other,), cid="s1")
    with pytest.raises(AttributionError):
        attribute(legacy, engine, day_count=1)


def test_refuses_signal_streams_differ() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    extra = _sig(50, 9, SignalDirection.LONG, "extra")
    legacy, engine = _one_fill_arms(legacy_signals=(sig,), engine_signals=(sig, extra), cid="s1")
    with pytest.raises(AttributionError):
        attribute(legacy, engine, day_count=1)


def test_refuses_opening_order_with_zero_signals() -> None:
    other = _sig(900, 1, SignalDirection.LONG, "other")
    legacy, engine = _one_fill_arms(
        legacy_signals=(other,),
        engine_signals=(other,),
        cid="missing",
    )
    with pytest.raises(AttributionError):
        attribute(legacy, engine, day_count=1)


def test_refuses_opening_order_with_two_signals() -> None:
    first = _sig(800, 1, SignalDirection.LONG, "s1")
    second = _sig(900, 2, SignalDirection.LONG, "s1")
    legacy, engine = _one_fill_arms(
        legacy_signals=(first, second),
        engine_signals=(first, second),
        cid="s1",
    )
    with pytest.raises(AttributionError):
        attribute(legacy, engine, day_count=1)


def test_refuses_engine_cross_check_mismatch() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry = _fill("10.00", 10, 1000, "0.05", 1)
    exit_fill = _fill("10.50", 10, 2000, "0.05", 2)
    bad = _pc((entry,), (exit_fill,), "FAVORABLE")
    bad = PositionClosed(
        timestamp_ns=bad.timestamp_ns,
        correlation_id=bad.correlation_id,
        sequence=bad.sequence,
        symbol=bad.symbol,
        strategy_id=bad.strategy_id,
        cell_id=bad.cell_id,
        side=bad.side,
        declared_archetype=bad.declared_archetype,
        entry_fills=bad.entry_fills,
        exit_fills=(PositionFillLeg(price_cents=1, quantity=10, timestamp_ns=2000, sequence=2),),
        entry_spread_ticks=bad.entry_spread_ticks,
        horizon_deadline_ns=bad.horizon_deadline_ns,
        drawn_level_ticks=bad.drawn_level_ticks,
        exit_reason=bad.exit_reason,
        triggered_paths=bad.triggered_paths,
        worst=bad.worst,
        closed_on_stale_data=bad.closed_on_stale_data,
        exited_on_unusable_data=bad.exited_on_unusable_data,
        lived_through_feed_gap=bad.lived_through_feed_gap,
        first_event_exit=bad.first_event_exit,
        stop_inside_round_trip=bad.stop_inside_round_trip,
        target_inside_round_trip=bad.target_inside_round_trip,
        uncalibrated=bad.uncalibrated,
        supersedes=bad.supersedes,
    )
    legacy, engine = _one_fill_arms(
        legacy_signals=(sig,),
        engine_signals=(sig,),
        cid="s1",
        closed=(bad,),
    )
    with pytest.raises(AttributionError):
        attribute(legacy, engine, day_count=1)


def test_partial_exit_open_long() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.05", "s1"
    )
    trim_order, trim_ack, trim = _trade(
        1400, 1500, 2, 2, "t1", Side.SELL, 4, "10.50", "0.02", "t1", reason="TRIM"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "10.00", "10.01"),
        _quote(1500, 3, "10.40", "10.41"),
        _quote(2500, 4, "9.70", "9.71"),
        _quote(3000, 5, "9.90", "9.91"),
    )
    orders = (entry_order, trim_order)
    acks = (entry_ack, trim_ack)
    episode = _episode(sig, "LONG", (entry,), (trim,), "1.93", 2000)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm((sig,), orders, acks, quotes, closed=(_pc((entry,), (trim,), "END_OF_TAPE"),)),
        _report(
            (
                _diff(
                    "SAME",
                    "END_OF_TAPE",
                    "END_OF_TAPE",
                    "",
                    episode,
                    episode,
                    "0.30",
                    "0.30",
                    None,
                ),
            ),
            (("SAME", 1, "1.93", "1.93"),),
        ),
    )


def test_partial_exit_open_short() -> None:
    sig = _sig(900, 1, SignalDirection.SHORT, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.SELL, 10, "20.00", "0.05", "s1", is_short=True
    )
    cover_order, cover_ack, cover = _trade(
        1400, 1500, 2, 2, "c1", Side.BUY, 6, "19.00", "0.03", "c1", reason="COVER_PART"
    )
    quotes = (
        _quote(500, 1, "19.99", "20.00"),
        _quote(1000, 2, "19.99", "20.00"),
        _quote(1500, 3, "18.99", "19.00"),
        _quote(2500, 4, "19.59", "20.40"),
        _quote(3000, 5, "19.49", "19.50"),
    )
    orders = (entry_order, cover_order)
    acks = (entry_ack, cover_ack)
    episode = _episode(sig, "SHORT", (entry,), (cover,), "5.92", 2000)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm(
            (sig,),
            orders,
            acks,
            quotes,
            closed=(_pc((entry,), (cover,), "END_OF_TAPE", side="SHORT"),),
        ),
        _report(
            (
                _diff(
                    "SAME",
                    "END_OF_TAPE",
                    "END_OF_TAPE",
                    "",
                    episode,
                    episode,
                    "0.40",
                    "0.40",
                    None,
                ),
            ),
            (("SAME", 1, "5.92", "5.92"),),
        ),
    )


def test_partial_exit_open_average_cost() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    e1_order, e1_ack, e1 = _trade(950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1")
    e2_order, e2_ack, e2 = _trade(1150, 1200, 2, 2, "e2", Side.BUY, 10, "11.00", "0.01", "s1")
    t1_order, t1_ack, t1 = _trade(
        1400, 1500, 3, 3, "t1", Side.SELL, 5, "12.00", "0.01", "t1", reason="TRIM"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "10.60", "10.61"),
        _quote(1200, 3, "10.90", "10.91"),
        _quote(1500, 4, "11.90", "11.91"),
        _quote(3000, 5, "11.00", "11.01"),
    )
    orders = (e1_order, e2_order, t1_order)
    acks = (e1_ack, e2_ack, t1_ack)
    episode = _episode(sig, "LONG", (e1, e2), (t1,), "7.47", 2000)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm((sig,), orders, acks, quotes, closed=(_pc((e1, e2), (t1,), "END_OF_TAPE"),)),
        _report(
            (
                _diff(
                    "SAME",
                    "END_OF_TAPE",
                    "END_OF_TAPE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "7.47", "7.47"),),
        ),
    )


def test_mae_running_average_cost() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    e1_order, e1_ack, e1 = _trade(950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1")
    e2_order, e2_ack, e2 = _trade(1150, 1200, 2, 2, "e2", Side.BUY, 10, "11.00", "0.01", "s1")
    x_order, x_ack, x = _trade(
        1900, 2000, 3, 3, "x1", Side.SELL, 20, "11.50", "0.02", "x1", reason="OUT"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "9.80", "9.81"),
        _quote(1200, 3, "10.40", "10.41"),
        _quote(1500, 4, "10.10", "10.11"),
        _quote(2000, 5, "11.40", "11.41"),
    )
    orders = (e1_order, e2_order, x_order)
    acks = (e1_ack, e2_ack, x_ack)
    episode = _episode(sig, "LONG", (e1, e2), (x,), "19.96", 1000)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm((sig,), orders, acks, quotes, closed=(_pc((e1, e2), (x,), "FAVORABLE"),)),
        _report(
            (
                _diff(
                    "SAME",
                    "OUT",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.40",
                    "0.40",
                    None,
                ),
            ),
            (("SAME", 1, "19.96", "19.96"),),
        ),
    )


def test_mae_floor_zero() -> None:
    sig = _sig(900, 1, SignalDirection.LONG, "s1")
    entry_order, entry_ack, entry = _trade(
        950, 1000, 1, 1, "e1", Side.BUY, 10, "10.00", "0.01", "s1"
    )
    x_order, x_ack, x = _trade(
        1900, 2000, 2, 2, "x1", Side.SELL, 10, "10.20", "0.01", "x1", reason="OUT"
    )
    quotes = (
        _quote(500, 1, "9.00", "9.01"),
        _quote(1000, 2, "10.05", "10.06"),
        _quote(1500, 3, "10.10", "10.11"),
        _quote(2000, 4, "10.20", "10.21"),
    )
    orders = (entry_order, x_order)
    acks = (entry_ack, x_ack)
    episode = _episode(sig, "LONG", (entry,), (x,), "1.98", 1000)
    _check(
        _arm((sig,), orders, acks, quotes),
        _arm((sig,), orders, acks, quotes, closed=(_pc((entry,), (x,), "FAVORABLE"),)),
        _report(
            (
                _diff(
                    "SAME",
                    "OUT",
                    "FAVORABLE",
                    "",
                    episode,
                    episode,
                    "0.00",
                    "0.00",
                    None,
                ),
            ),
            (("SAME", 1, "1.98", "1.98"),),
        ),
    )
