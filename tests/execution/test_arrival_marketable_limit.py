"""Marketable-on-arrival limits use the submit-time taker on q_p.

S1–S6 are the census books (platform.yaml factors, clock equal to
exchange time). A limit that locks or crosses the quote prevailing at
go-live is handed to ``_execute_market_fill`` on that book. The flush
quote is only the trigger.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.platform_config import PlatformConfig
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation

_CFG = PlatformConfig.from_yaml(Path("platform.yaml"))
_L = int(_CFG.backtest_fill_latency_ns)


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def _cost() -> DefaultCostModel:
    return DefaultCostModel(
        DefaultCostModelConfig(
            min_spread_cost_bps=_d(_CFG.cost_min_spread_bps),
            commission_per_share=_d(_CFG.cost_commission_per_share),
            taker_exchange_per_share=_d(_CFG.cost_taker_exchange_per_share),
            maker_exchange_per_share=_d(_CFG.cost_maker_exchange_per_share),
            passive_adverse_selection_bps=_d(_CFG.cost_passive_adverse_selection_bps),
            through_fill_adverse_selection_bps=_d(_CFG.cost_through_fill_adverse_selection_bps),
            sell_regulatory_bps=_d(_CFG.cost_sell_regulatory_bps),
            stress_multiplier=_d(_CFG.cost_stress_multiplier),
            min_commission=_d(_CFG.cost_min_commission),
            max_commission_pct=_d(_CFG.cost_max_commission_pct),
            htb_borrow_annual_bps=_d(_CFG.cost_htb_borrow_annual_bps),
            finra_taf_per_share=_d(_CFG.cost_finra_taf_per_share),
            finra_taf_max_per_order=_d(_CFG.cost_finra_taf_max_per_order),
            min_commission_applies_to_per_share_only=(
                _CFG.cost_min_commission_applies_to_per_share_only
            ),
            spread_floor_taker_only=_CFG.cost_spread_floor_taker_only,
        )
    )


def _router(clock: SimulatedClock, *, hazard: Decimal | None = None) -> PassiveLimitOrderRouter:
    return PassiveLimitOrderRouter(
        clock,
        latency_ns=_L,
        market_impact_factor=_CFG.cost_market_impact_factor,
        max_impact_half_spreads=_CFG.cost_max_impact_half_spreads,
        cost_model=_cost(),
        fill_delay_ticks=_CFG.passive_fill_delay_ticks,
        max_resting_ticks=_CFG.passive_max_resting_ticks,
        queue_position_shares=_CFG.passive_queue_position_shares,
        fill_hazard_max=_CFG.passive_fill_hazard_max if hazard is None else hazard,
        within_l1_impact_factor=_CFG.cost_within_l1_impact_factor,
        permanent_impact_coefficient=_CFG.cost_permanent_impact_coefficient,
        stop_depth_depletion_factor=_CFG.cost_stop_depth_depletion_factor,
        through_fill_size_cap_enabled=_CFG.passive_through_fill_size_cap_enabled,
        require_trade_for_level_fill=_CFG.passive_require_trade_for_level_fill,
    )


def _quote(
    bid: str,
    ask: str,
    ts: int,
    *,
    bid_size: int = 80,
    ask_size: int = 80,
    symbol: str = "AAPL",
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}-{bid}-{ask}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _order(side: Side, qty: int, limit: str, oid: str) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="o1",
        sequence=1,
        order_id=oid,
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=Decimal(limit),
    )


def _play(
    quotes: list[NBBOQuote],
    order: OrderRequest,
    *,
    hazard: Decimal | None = None,
) -> tuple[list[OrderAck], int]:
    """Feed ``quotes`` in order. Submit on the first quote."""
    clock = SimulatedClock(start_ns=0)
    router = _router(clock, hazard=hazard)
    acks: list[OrderAck] = []
    for index, quote in enumerate(quotes):
        clock.set_time(quote.exchange_timestamp_ns)
        router.on_quote(quote)
        acks.extend(router.poll_acks())
        if index == 0:
            router.submit(order)
            acks.extend(router.poll_acks())
    return acks, router.resting_order_count


def _fills(acks: list[OrderAck]) -> list[OrderAck]:
    return [
        ack
        for ack in acks
        if ack.status in (OrderAckStatus.FILLED, OrderAckStatus.PARTIALLY_FILLED)
    ]


def _leg(ack: OrderAck) -> tuple[OrderAckStatus, Decimal | None, int, Decimal, str]:
    return (ack.status, ack.fill_price, ack.filled_quantity, ack.fees, ack.reason)


def _assert_legs(arrival: list[OrderAck], submit: list[OrderAck]) -> None:
    got = [_leg(ack) for ack in _fills(arrival)]
    exp = [_leg(ack) for ack in _fills(submit)]
    assert got == exp


def test_s1_full_take_prices_with_submit_taker() -> None:
    """Full take on q_p matches a submit-time taker on that book.

    The flush book is 398.00/398.10. q_p is the in-window 399.80/399.90.
    Pricing off the flush quote is a different fill.
    """
    order = _order(Side.BUY, 30, "400.20", "s1")
    arrival, resting = _play(
        [
            _quote("400.40", "400.50", 0, ask_size=80),
            _quote("399.80", "399.90", _L // 2, ask_size=80),
            _quote("398.00", "398.10", _L + 1_000_000, ask_size=80),
        ],
        order,
    )
    submit, _submit_rest = _play(
        [
            _quote("399.80", "399.90", 0, ask_size=80),
            _quote("399.80", "399.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 30, "400.20", "s1-submit"),
    )
    assert resting == 0
    _assert_legs(arrival, submit)
    filled = _fills(arrival)
    assert len(filled) == 1
    assert filled[0].status == OrderAckStatus.FILLED
    assert filled[0].fill_price == Decimal("399.91")
    assert filled[0].filled_quantity == 30
    assert filled[0].fees == Decimal("0.80")
    assert filled[0].reason == ""


def test_s2_remainder_matches_submit_walk() -> None:
    """Size above the displayed ask walks; it does not rest."""
    arrival, resting = _play(
        [
            _quote("100.40", "100.50", 0),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 200, "100.20", "s2"),
    )
    submit, _rest = _play(
        [
            _quote("99.80", "99.90", 0, ask_size=80),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 200, "100.20", "s2-submit"),
    )
    assert resting == 0
    _assert_legs(arrival, submit)
    legs = _fills(arrival)
    assert [(ack.filled_quantity, ack.fill_price) for ack in legs] == [
        (80, Decimal("99.92")),
        (120, Decimal("99.96")),
    ]


def test_s3_lock_clamps_to_limit() -> None:
    """A lock is marketable. The walked price clamps to the limit."""
    arrival, resting = _play(
        [
            _quote("100.00", "100.10", 0),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 30, "99.90", "s3"),
    )
    submit, _rest = _play(
        [
            _quote("99.80", "99.90", 0, ask_size=80),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 30, "99.90", "s3-submit"),
    )
    assert resting == 0
    _assert_legs(arrival, submit)
    filled = _fills(arrival)
    assert len(filled) == 1
    assert filled[0].fill_price == Decimal("99.90")
    assert filled[0].fees == Decimal("0.53")
    assert filled[0].reason == ""


def test_s4_revert_qp_does_not_fill() -> None:
    """A cross that reverts before go-live is not q_p, so nothing fills.

    Passes on the pre-change tree as well: the eligible book does not
    cross. A mutant that takes that book anyway rejects on the mid
    check and is no longer resting.
    """
    acks, resting = _play(
        [
            _quote("100.40", "100.50", 0),
            _quote("99.80", "99.90", _L // 2, ask_size=80),
            _quote("100.20", "100.30", _L - 10_000_000),
            _quote("100.20", "100.30", _L + 10_000_000),
        ],
        _order(Side.BUY, 200, "100.20", "s4"),
    )
    assert _fills(acks) == []
    assert resting == 1


def test_s5_arrival_equals_submit_marketable() -> None:
    """Arrival legs equal the submit-time marketable legs field by field."""
    arrival, resting = _play(
        [
            _quote("100.40", "100.50", 0),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 200, "100.20", "s5-arrival"),
    )
    submit, submit_rest = _play(
        [
            _quote("99.80", "99.90", 0, ask_size=80),
            _quote("99.80", "99.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 200, "100.20", "s5-submit"),
    )
    assert resting == submit_rest == 0
    got = _fills(arrival)
    exp = _fills(submit)
    assert len(got) == len(exp) == 2
    for left, right in zip(got, exp, strict=True):
        assert left.status == right.status
        assert left.fill_price == right.fill_price
        assert left.filled_quantity == right.filled_quantity
        assert left.fees == right.fees
        assert left.reason == right.reason


def test_s6_sell_walk_matches_submit() -> None:
    """A sell that locks or crosses q_p walks the bid like a submit."""
    arrival, resting = _play(
        [
            _quote("99.40", "99.50", 0),
            _quote("99.80", "99.90", _L, bid_size=80),
        ],
        _order(Side.SELL, 200, "99.50", "s6"),
    )
    submit, _rest = _play(
        [
            _quote("99.80", "99.90", 0, bid_size=80),
            _quote("99.80", "99.90", _L, bid_size=80),
        ],
        _order(Side.SELL, 200, "99.50", "s6-submit"),
    )
    assert resting == 0
    _assert_legs(arrival, submit)
    legs = _fills(arrival)
    assert [(ack.filled_quantity, ack.fill_price, ack.fees) for ack in legs] == [
        (80, Decimal("99.78"), Decimal("1.24")),
        (120, Decimal("99.74"), Decimal("1.76")),
    ]


def test_crossed_or_empty_arrival_book_rejects_as_submit() -> None:
    """Crossed and zero-depth arrival books reject with the submit reason."""
    cases = [
        ("crossed", Side.BUY, "100.20", "100.00", "99.90", 80, 80, "100.40", "100.50", 80, 80),
        ("zero-ask", Side.BUY, "100.20", "99.80", "99.90", 80, 0, "100.40", "100.50", 80, 80),
        ("zero-bid", Side.SELL, "99.50", "99.80", "99.90", 0, 80, "99.40", "99.50", 80, 80),
    ]
    for name, side, limit, bid, ask, bid_sz, ask_sz, obid, oask, obsz, osz in cases:
        arrival, _rest = _play(
            [
                _quote(obid, oask, 0, bid_size=obsz, ask_size=osz),
                _quote(bid, ask, _L, bid_size=bid_sz, ask_size=ask_sz),
            ],
            _order(side, 30, limit, f"arr-{name}"),
        )
        submit, _submit_rest = _play(
            [
                _quote(bid, ask, 0, bid_size=bid_sz, ask_size=ask_sz),
                _quote(bid, ask, _L, bid_size=bid_sz, ask_size=ask_sz),
            ],
            _order(side, 30, limit, f"sub-{name}"),
        )
        arr_rej = [ack for ack in arrival if ack.status == OrderAckStatus.REJECTED]
        sub_rej = [ack for ack in submit if ack.status == OrderAckStatus.REJECTED]
        assert len(arr_rej) == len(sub_rej) == 1, name
        assert arr_rej[0].reason == sub_rej[0].reason, name
        assert _fills(arrival) == []
        assert _fills(submit) == []


_BOOKS = (
    ("100.00", "100.10"),
    ("100.07", "100.08"),
    ("0.50", "0.51"),
    ("0.99", "1.00"),
)
_OFFSETS = (
    "-0.009",
    "-0.004",
    "-0.001",
    "-0.0001",
    "0",
    "0.0001",
    "0.001",
    "0.004",
    "0.009",
)


def _submit_rests(side: Side, limit: str, bid: str, ask: str) -> bool:
    """True when the pre-snap check leaves the order resting on this book."""
    clock = SimulatedClock(start_ns=0)
    router = _router(clock, hazard=Decimal("0"))
    clock.set_time(0)
    router.on_quote(_quote(bid, ask, 0, bid_size=100, ask_size=100))
    router.submit(_order(side, 10, limit, "grid-s"))
    router.poll_acks()
    return router.resting_order_count == 1


def _arrival_kind(side: Side, limit: str, bid: str, ask: str) -> str:
    """Class of the go-live quote: taker, reject, maker, or rest."""
    if side == Side.BUY:
        opening = _quote("499.90", "500.00", 0, bid_size=100, ask_size=100)
    else:
        opening = _quote("0.10", "0.20", 0, bid_size=100, ask_size=100)
    acks, resting = _play(
        [opening, _quote(bid, ask, _L, bid_size=100, ask_size=100)],
        _order(side, 10, limit, "grid-a"),
        hazard=Decimal("0"),
    )
    if any(ack.status == OrderAckStatus.REJECTED for ack in acks):
        return "reject"
    fills = _fills(acks)
    if fills and fills[0].reason == "":
        return "taker"
    if fills:
        return "maker"
    if resting:
        return "rest"
    return "flat"


def test_subtick_limit_arrival_classification_matches_submit() -> None:
    """On-grid quotes: arrival class equals the pre-snap submit class.

    Submit class is whether the order rests after the pre-snap check.
    Arrival class is taker or reject versus still resting. Hazard is off.
    A reversed snap stores a different limit and can flip only the arrival.
    """
    misses: list[str] = []
    for bid, ask in _BOOKS:
        for offset in _OFFSETS:
            delta = Decimal(offset)
            buy_limit = Decimal(ask) + delta
            sell_limit = Decimal(bid) + delta
            for side, limit in ((Side.BUY, buy_limit), (Side.SELL, sell_limit)):
                if limit <= 0:
                    continue
                limit_s = format(limit, "f")
                submit_rests = _submit_rests(side, limit_s, bid, ask)
                arrival = _arrival_kind(side, limit_s, bid, ask)
                arrival_rests = arrival == "rest"
                if submit_rests != arrival_rests or (
                    not arrival_rests and arrival not in ("taker", "reject")
                ):
                    misses.append(
                        f"{side.name} limit={limit_s} bid={bid} ask={ask} "
                        f"submit_rests={submit_rests} arrival={arrival}"
                    )
    assert misses == []


def test_arrival_take_emits_single_acknowledged() -> None:
    """The resting ack is the only ACKNOWLEDGED. The take does not ack again."""
    acks, resting = _play(
        [
            _quote("400.40", "400.50", 0, ask_size=80),
            _quote("399.80", "399.90", _L, ask_size=80),
        ],
        _order(Side.BUY, 30, "400.20", "s1-ack"),
    )
    acknowledged = [ack for ack in acks if ack.status == OrderAckStatus.ACKNOWLEDGED]
    assert len(acknowledged) == 1
    assert resting == 0
    filled = _fills(acks)
    assert len(filled) == 1
    assert filled[0].reason == ""
