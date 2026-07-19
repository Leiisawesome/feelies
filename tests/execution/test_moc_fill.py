"""BT-8: MOC session bounds and closing-auction fill controller."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


from feelies.core.clock import SimulatedClock
from feelies.core.identifiers import SequenceGenerator
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.moc_fill import MocFillController
from feelies.execution.moc_session import (
    build_moc_bounds_from_platform,
    resolve_moc_session_bounds,
    session_date_from_calendar_path,
)


def _moc_order(
    *,
    order_id: str = "moc1",
    is_moc: bool = True,
    ts: int = 0,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=ts,
        correlation_id="c1",
        sequence=1,
        order_id=order_id,
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        is_moc=is_moc,
    )


def _quote(symbol: str, bid: str, ask: str, exchange_ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts,
        correlation_id="q",
        sequence=1,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts,
    )


class TestMocSessionBounds:
    def test_regular_session_cutoff_and_close(self) -> None:
        d = date(2026, 3, 24)
        bounds = resolve_moc_session_bounds(d)
        assert bounds.moc_cutoff_ns < bounds.official_close_ns

    def test_early_close_session(self) -> None:
        d = date(2026, 11, 27)
        reg = resolve_moc_session_bounds(d)
        early = resolve_moc_session_bounds(d, early_close=True)
        assert early.moc_cutoff_ns < reg.moc_cutoff_ns
        assert early.official_close_ns < reg.official_close_ns

    def test_calendar_path_extracts_date(self) -> None:
        p = "src/feelies/storage/reference/event_calendar/2026-03-24.yaml"
        assert session_date_from_calendar_path(p) == date(2026, 3, 24)

    def test_build_from_platform(self) -> None:
        bounds = build_moc_bounds_from_platform(
            moc_session_date="2026-03-24",
            event_calendar_path=None,
            moc_cutoff_et="15:50",
            official_close_et="16:00",
            early_close_dates=(),
            early_close_moc_cutoff_et="12:50",
            early_close_official_close_et="13:00",
        )
        assert bounds is not None
        assert bounds.session_date == date(2026, 3, 24)


class TestMocFillController:
    def test_cutoff_missed_rejects(self) -> None:
        session = resolve_moc_session_bounds(date(2026, 3, 24))
        clock = SimulatedClock(start_ns=session.moc_cutoff_ns)
        pending: list = []
        ctrl = MocFillController(
            session,
            clock,
            cost_model=ZeroCostModel(),
            ack_seq=SequenceGenerator(),
            pending_acks=pending,
        )
        rejects: list[tuple[str, str]] = []

        def reject(req: OrderRequest, reason: str, **kwargs: object) -> None:
            rejects.append((req.order_id, reason))

        ctrl.submit(
            _moc_order(),
            exchange_timestamp_ns=session.moc_cutoff_ns,
            reject_fn=reject,
        )
        assert rejects == [("moc1", "MOC_CUTOFF_MISSED")]
        assert pending == []

    def test_fill_at_close_mid_only(self) -> None:
        session = resolve_moc_session_bounds(date(2026, 3, 24))
        submit_ts = session.moc_cutoff_ns - 3_600_000_000_000
        clock = SimulatedClock(start_ns=submit_ts)
        router = BacktestOrderRouter(clock, moc_bounds=session)
        router.on_quote(_quote("AAPL", "100.00", "100.02", submit_ts))
        router.submit(_moc_order(ts=submit_ts))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.ACKNOWLEDGED]
        assert router.poll_acks() == []

        router.on_quote(_quote("AAPL", "100.00", "100.04", session.official_close_ns))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("100.02")

    def test_non_moc_fills_immediately(self) -> None:
        session = resolve_moc_session_bounds(date(2026, 3, 24))
        clock = SimulatedClock(start_ns=1000)
        router = BacktestOrderRouter(clock, moc_bounds=session)
        router.on_quote(_quote("AAPL", "100.00", "100.02", 1000))
        router.submit(_moc_order(is_moc=False))
        acks = router.poll_acks()
        assert OrderAckStatus.FILLED in [a.status for a in acks]
