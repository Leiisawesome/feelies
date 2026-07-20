"""Execution-realism configuration tests.

Covers the additive, default-neutral fill-model knobs:

* within-L1 participation impact (``cost_within_l1_impact_factor``)
* permanent square-root impact (``cost_permanent_impact_coefficient``)
* forced-exit depth depletion (``cost_stop_depth_depletion_factor``)
* passive through-fill size cap (``passive_through_fill_size_cap_enabled``)
* volume-gated passive level fill (``passive_require_trade_for_level_fill``)
* MOC closing-auction penalty (``cost_moc_penalty_bps``)

Each knob's default value reproduces the prior trade path; these tests pin
both the no-op default and the enabled behaviour.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.identifiers import SequenceGenerator
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
    Trade,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.moc_fill import MocFillController
from feelies.execution.moc_session import resolve_moc_session_bounds
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


def _quote(
    *,
    bid: str = "100.00",
    ask: str = "100.10",
    bid_size: int = 500,
    ask_size: int = 500,
    ts: int = 1000,
    seq: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
        sequence_number=seq,
    )


def _market(
    side: Side,
    *,
    qty: int = 100,
    reason: str = "",
    order_id: str = "o1",
    seq: int = 1,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=seq,
        order_id=order_id,
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        reason=reason,
    )


def _fills(acks: list) -> list:
    return [a for a in acks if a.status == OrderAckStatus.FILLED]


# Within-L1 participation impact.


class TestWithinL1Impact:
    def test_default_factor_zero_fills_at_cross(self) -> None:
        router = BacktestOrderRouter(SimulatedClock(start_ns=0), cost_model=ZeroCostModel())
        router.on_quote(_quote())
        router.submit(_market(Side.BUY, qty=100))
        fills = _fills(router.poll_acks())
        # Depth 500, qty 100 ≤ L1 → pure cross (the lifted ask).
        assert fills[0].fill_price == Decimal("100.10")

    def test_positive_factor_worsens_buy_fill_price(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            within_l1_impact_factor=Decimal("1.0"),
        )
        router.on_quote(_quote())
        router.submit(_market(Side.BUY, qty=100))
        fills = _fills(router.poll_acks())
        # premium = 1.0 × (100/500) × half_spread(0.05) = 0.01 → 100.11.
        assert fills[0].fill_price == Decimal("100.11")

    def test_positive_factor_worsens_sell_fill_price(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            within_l1_impact_factor=Decimal("1.0"),
        )
        router.on_quote(_quote())
        router.submit(_market(Side.SELL, qty=100))
        fills = _fills(router.poll_acks())
        # SELL receives less: 100.00 − 0.01 = 99.99.
        assert fills[0].fill_price == Decimal("99.99")


# Permanent square-root impact.


class TestPermanentImpact:
    def test_default_coefficient_zero_no_impact(self) -> None:
        router = BacktestOrderRouter(SimulatedClock(start_ns=0), cost_model=ZeroCostModel())
        router.on_quote(_quote())
        router.submit(_market(Side.BUY, qty=100))
        assert _fills(router.poll_acks())[0].fill_price == Decimal("100.10")

    def test_sqrt_impact_worsens_buy_price(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            permanent_impact_coefficient=Decimal("2.0"),
        )
        router.on_quote(_quote())
        router.submit(_market(Side.BUY, qty=100))
        fills = _fills(router.poll_acks())
        # premium = 2.0 × sqrt(0.2) × 0.05 ≈ 0.0447 → 100.1447 → ceil 100.15.
        assert fills[0].fill_price == Decimal("100.15")


# Forced-exit depth depletion.


class TestStopDepthDepletion:
    def test_default_factor_one_single_fill_at_bid(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            stop_slippage_half_spreads=Decimal("1.0"),
        )
        router.on_quote(_quote())
        router.submit(_market(Side.SELL, qty=100, reason="STOP_EXIT"))
        fills = _fills(router.poll_acks())
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("100.00")

    def test_depletion_walks_the_book_on_stop(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            stop_slippage_half_spreads=Decimal("1.0"),
            stop_depth_depletion_factor=Decimal("10"),
        )
        router.on_quote(_quote())  # bid_size 500 → effective 50.
        router.submit(_market(Side.SELL, qty=100, reason="STOP_EXIT"))
        acks = router.poll_acks()
        statuses = [a.status for a in acks]
        # qty 100 > effective depth 50 → partial(50) + excess(50) walk-book.
        assert OrderAckStatus.PARTIALLY_FILLED in statuses
        assert OrderAckStatus.FILLED in statuses
        excess = [a for a in acks if a.status == OrderAckStatus.FILLED][0]
        # The excess leg fills below the bid (worse for a seller).
        assert excess.fill_price < Decimal("100.00")

    def test_depletion_ignored_for_non_forced_exit(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            stop_depth_depletion_factor=Decimal("10"),
        )
        router.on_quote(_quote())
        router.submit(_market(Side.SELL, qty=100, reason=""))  # not a stop
        fills = _fills(router.poll_acks())
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("100.00")


# Passive through-fill size cap.


def _buy_limit(order_id: str = "p1") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=1,
        order_id=order_id,
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("100.05"),
    )


class TestPassiveThroughFillCap:
    def test_default_fills_whole_order_on_through(self) -> None:
        router = PassiveLimitOrderRouter(SimulatedClock(start_ns=0), cost_model=ZeroCostModel())
        router.on_quote(_quote())
        router.submit(_buy_limit())
        router.poll_acks()  # drain ACKNOWLEDGED
        # ask gaps through the resting BUY limit (ask 100.04 < limit 100.05).
        router.on_quote(_quote(ask="100.04", ask_size=30, ts=2000, seq=2))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.FILLED]
        assert acks[0].filled_quantity == 100

    def test_cap_partial_fills_and_rests_remainder(self) -> None:
        router = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            through_fill_size_cap_enabled=True,
        )
        router.on_quote(_quote())
        router.submit(_buy_limit())
        router.poll_acks()
        router.on_quote(_quote(ask="100.04", ask_size=30, ts=2000, seq=2))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.PARTIALLY_FILLED]
        assert acks[0].filled_quantity == 30
        # Remainder still resting → a second through fills the rest.
        router.on_quote(_quote(ask="100.04", ask_size=1000, ts=3000, seq=3))
        acks2 = router.poll_acks()
        assert [a.status for a in acks2] == [OrderAckStatus.FILLED]
        assert acks2[0].filled_quantity == 70


# Volume-gated passive level fill.


class TestVolumeGatedLevelFill:
    @staticmethod
    def _run_level_quotes(router: PassiveLimitOrderRouter, *, with_trade: bool) -> list:
        # BUY limit at 100.05; book tilted hard against us (huge ask) so the
        # quote-imbalance hazard is at the cap.
        router.on_quote(_quote(bid="100.05", bid_size=50, ask="100.10", ask_size=5000, ts=1000))
        router.submit(_buy_limit())
        router.poll_acks()
        out: list = []
        for k in range(2, 25):
            ts = k * 1000
            if with_trade:
                router.on_trade(
                    Trade(
                        timestamp_ns=ts,
                        correlation_id="t",
                        sequence=k,
                        symbol="AAPL",
                        price=Decimal("100.05"),
                        size=100,
                        exchange_timestamp_ns=ts,
                    )
                )
            router.on_quote(
                _quote(bid="100.05", bid_size=50, ask="100.10", ask_size=5000, ts=ts, seq=k)
            )
            out.extend(router.poll_acks())
        return out

    def test_default_gate_off_can_fill_without_volume(self) -> None:
        router = PassiveLimitOrderRouter(SimulatedClock(start_ns=0), cost_model=ZeroCostModel())
        assert router.requires_trade_feed is False
        acks = self._run_level_quotes(router, with_trade=False)
        assert any(a.status == OrderAckStatus.FILLED for a in acks)

    def test_gate_on_suppresses_fill_without_volume(self) -> None:
        router = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            require_trade_for_level_fill=True,
        )
        assert router.requires_trade_feed is True
        acks = self._run_level_quotes(router, with_trade=False)
        assert not any(a.status == OrderAckStatus.FILLED for a in acks)

    def test_gate_on_allows_fill_with_volume(self) -> None:
        router = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
            require_trade_for_level_fill=True,
        )
        acks = self._run_level_quotes(router, with_trade=True)
        assert any(a.status == OrderAckStatus.FILLED for a in acks)


# MOC closing-auction penalty.


def _moc_order() -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=1,
        order_id="moc1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
        is_moc=True,
    )


class TestMocPenalty:
    def _fill_moc(self, penalty_bps: Decimal):
        session = resolve_moc_session_bounds(date(2026, 3, 24))
        submit_ts = session.moc_cutoff_ns - 3_600_000_000_000
        pending: list = []
        ctrl = MocFillController(
            session,
            SimulatedClock(start_ns=submit_ts),
            cost_model=ZeroCostModel(),
            ack_seq=SequenceGenerator(),
            pending_acks=pending,
            moc_penalty_bps=penalty_bps,
        )
        ctrl.submit(_moc_order(), exchange_timestamp_ns=submit_ts, reject_fn=lambda *a, **k: None)
        pending.clear()
        q = NBBOQuote(
            timestamp_ns=session.official_close_ns,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100.00"),
            ask=Decimal("100.02"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=session.official_close_ns,
        )
        ctrl.on_quote(q)
        return [a for a in pending if a.status == OrderAckStatus.FILLED][0]

    def test_default_penalty_zero_no_fees(self) -> None:
        ack = self._fill_moc(Decimal("0"))
        assert ack.fees == Decimal("0")

    def test_penalty_charges_fee(self) -> None:
        ack = self._fill_moc(Decimal("5"))
        # notional = 100.01 × 100 = 10001; penalty = 10001 × 5 / 10000 = 5.00.
        assert ack.fees == Decimal("5.00")
        assert ack.cost_bps == Decimal("5.00")
