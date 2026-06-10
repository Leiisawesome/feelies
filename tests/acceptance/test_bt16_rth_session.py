"""BT-16 acceptance: RTH session gating + overnight buying-power flip."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    OrderType,
    RiskAction,
    Side,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.moc_session import (
    build_moc_bounds_from_platform,
    et_clock_to_ns,
    resolve_moc_session_bounds,
)
from feelies.execution.moc_fill import MocFillController
from feelies.execution.trading_session import (
    RTH_ENTRY_SUPPRESSED,
    resolve_trading_session_bounds,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.buying_power import (
    BuyingPowerConfig,
    BuyingPowerPhase,
    buying_power_limit,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_SESSION = date(2026, 1, 15)


def _bounds() -> object:
    return resolve_trading_session_bounds(_SESSION)


def _after_close_ns() -> int:
    return et_clock_to_ns(_SESSION, "16:00:01")


def _engine(*, max_position: int = 100_000) -> BasicRiskEngine:
    return BasicRiskEngine(
        RiskConfig(
            account_equity=Decimal("50000"),
            max_gross_exposure_pct=2000.0,
            max_position_per_symbol=max_position,
        ),
        trading_session_bounds=_bounds(),  # type: ignore[arg-type]
        buying_power_config=BuyingPowerConfig(account_type="margin_25k"),
    )


def _order(ts_ns: int, qty: int, *, side: Side = Side.BUY) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=ts_ns,
        correlation_id="c1",
        sequence=1,
        order_id="ord-rth",
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


def test_entry_rejected_after_rth_close() -> None:
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("100"))
    verdict = _engine().check_order(_order(_after_close_ns(), 10), store)
    assert verdict.action == RiskAction.REJECT
    assert verdict.reason == RTH_ENTRY_SUPPRESSED


def test_exit_allowed_after_rth_close() -> None:
    store = MemoryPositionStore()
    store.update("AAPL", 100, Decimal("100"))
    store.update_mark("AAPL", Decimal("100"))
    verdict = _engine().check_order(
        _order(_after_close_ns(), 50, side=Side.SELL),
        store,
    )
    assert verdict.action == RiskAction.ALLOW


def test_router_entry_rejected_after_close_with_position_binding() -> None:
    bounds = _bounds()
    after_close = _after_close_ns()
    clock = SimulatedClock(start_ns=after_close)
    router = BacktestOrderRouter(
        clock,
        cost_model=ZeroCostModel(),
        trading_session_bounds=bounds,  # type: ignore[arg-type]
    )
    router.bind_position_qty(lambda _s: 0)
    router.on_quote(
        NBBOQuote(
            timestamp_ns=after_close,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("100.01"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=after_close - 1,
        )
    )
    router.submit(_order(after_close, 10))
    acks = router.poll_acks()
    assert any(a.status.name == "REJECTED" for a in acks)
    assert any(a.reason == RTH_ENTRY_SUPPRESSED for a in acks)


def test_buying_power_flips_to_overnight_at_close() -> None:
    bounds = _bounds()
    close_ns = bounds.rth_close_ns  # type: ignore[attr-defined]
    engine = _engine()
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("100"))
    intraday_cap = buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.INTRADAY,
        BuyingPowerConfig(account_type="margin_25k"),
    )
    intraday_qty = int((intraday_cap / Decimal("100")).to_integral_value()) - 1
    assert (
        engine.check_order(
            _order(close_ns - 1, intraday_qty),
            store,
        ).action
        == RiskAction.ALLOW
    )

    engine.set_buying_power_phase(BuyingPowerPhase.OVERNIGHT)
    overnight_cap = buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.OVERNIGHT,
        BuyingPowerConfig(account_type="margin_25k"),
    )
    overnight_qty = int((overnight_cap / Decimal("100")).to_integral_value()) + 1
    verdict = engine.check_order(_order(close_ns - 1, overnight_qty), store)
    assert verdict.action == RiskAction.REJECT
    assert verdict.reason == "INSUFFICIENT_BUYING_POWER"


def test_early_close_moc_cutoff_is_1250_et() -> None:
    d = date(2026, 11, 27)
    bounds = build_moc_bounds_from_platform(
        moc_session_date=d.isoformat(),
        event_calendar_path=None,
        moc_cutoff_et="15:50",
        official_close_et="16:00",
        early_close_dates=(d.isoformat(),),
        early_close_moc_cutoff_et="12:50",
        early_close_official_close_et="13:00",
    )
    assert bounds is not None
    cutoff_1250 = et_clock_to_ns(d, "12:50")
    cutoff_1251 = et_clock_to_ns(d, "12:51")
    assert bounds.moc_cutoff_ns == cutoff_1250
    clock = SimulatedClock(start_ns=cutoff_1251)
    pending: list = []
    ctrl = MocFillController(
        bounds,
        clock,
        ZeroCostModel(),
        __import__(
            "feelies.core.identifiers",
            fromlist=["SequenceGenerator"],
        ).SequenceGenerator(),
        pending,
    )
    rejected: list[str] = []

    def reject(req: OrderRequest, reason: str, **kwargs: object) -> None:
        rejected.append(reason)

    req = OrderRequest(
        timestamp_ns=cutoff_1251,
        correlation_id="c",
        sequence=1,
        order_id="moc-ec",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=1,
        is_moc=True,
    )
    assert ctrl.submit(
        req,
        exchange_timestamp_ns=cutoff_1251,
        reject_fn=reject,
    )
    assert "MOC_CUTOFF_MISSED" in rejected
