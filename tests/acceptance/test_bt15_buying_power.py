"""Test Reg-T buying power on ``margin_25k`` accounts."""

from __future__ import annotations

from decimal import Decimal


from feelies.core.events import OrderRequest, OrderType, RiskAction, Side
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.buying_power import (
    INSUFFICIENT_BUYING_POWER,
    BuyingPowerConfig,
    BuyingPowerPhase,
    buying_power_limit,
)


def _engine(
    *,
    equity: Decimal = Decimal("50000"),
    gross_pct: float = 2000.0,
) -> BasicRiskEngine:
    """Gross cap intentionally loose so buying power is the binding gate."""
    return BasicRiskEngine(
        RiskConfig(
            account_equity=equity,
            max_gross_exposure_pct=gross_pct,
            max_position_per_symbol=100_000,
        ),
        buying_power_config=BuyingPowerConfig(account_type="margin_25k"),
    )


def _order(symbol: str, qty: int, *, side: Side = Side.BUY) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2_000_000_000,
        correlation_id="o1",
        sequence=1,
        order_id="ord-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


def test_entry_within_intraday_buying_power_allowed() -> None:
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("100"))
    engine = _engine()
    limit = buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.INTRADAY,
        BuyingPowerConfig(account_type="margin_25k"),
    )
    assert limit == Decimal("200000")  # 4× equity
    # 1500 sh × $100 = $150k gross < $200k (4× $50k)
    verdict = engine.check_order(_order("AAPL", 1500), store)
    assert verdict.action == RiskAction.ALLOW


def test_entry_beyond_intraday_buying_power_rejected() -> None:
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("100"))
    engine = _engine()
    # 2500 sh × $100 = $250k > $200k intraday cap
    verdict = engine.check_order(_order("AAPL", 2500), store)
    assert verdict.action == RiskAction.REJECT
    assert verdict.reason == INSUFFICIENT_BUYING_POWER


def test_exit_not_blocked_by_buying_power() -> None:
    store = MemoryPositionStore()
    store.update("AAPL", 3000, Decimal("100"))
    store.update_mark("AAPL", Decimal("100"))
    engine = _engine()
    verdict = engine.check_order(
        _order("AAPL", 1000, side=Side.SELL),
        store,
    )
    assert verdict.action == RiskAction.ALLOW


def test_overnight_phase_uses_two_x_limit() -> None:
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("100"))
    engine = _engine()
    engine.set_buying_power_phase(BuyingPowerPhase.OVERNIGHT)
    # 1500 sh × $100 = $150k > $100k overnight (2× $50k)
    verdict = engine.check_order(_order("AAPL", 1500), store)
    assert verdict.action == RiskAction.REJECT
    assert verdict.reason == INSUFFICIENT_BUYING_POWER

    engine.set_buying_power_phase(BuyingPowerPhase.INTRADAY)
    verdict_intraday = engine.check_order(_order("AAPL", 1500), store)
    assert verdict_intraday.action == RiskAction.ALLOW


def test_position_trajectory_respects_funded_equity_not_one_million() -> None:
    """Absolute gross stays within 4× the configured $50k equity."""
    store = MemoryPositionStore()
    store.update_mark("AAPL", Decimal("50"))
    engine = _engine(equity=Decimal("50000"))
    cap = buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.INTRADAY,
        BuyingPowerConfig(account_type="margin_25k"),
    )
    allowed_qty = int((cap / Decimal("50")).to_integral_value())
    verdict = engine.check_order(_order("AAPL", allowed_qty), store)
    assert verdict.action == RiskAction.ALLOW
    store.update("AAPL", allowed_qty, Decimal("50"))
    store.update_mark("AAPL", Decimal("50"))
    assert store.total_exposure() <= cap
