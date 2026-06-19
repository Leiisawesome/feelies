"""Inv-12 PnL-survival CI gate (audit P1.4).

The pre-existing ``test_inv12_stress_gate`` exercises only the stress
*helpers* (``apply_inv12_stress`` / disclosure arithmetic).  This module
adds the missing teeth: it runs a **known-edge round trip through the real
aggressive fill path** under the baseline cost model and under the Inv-12
1.5× cost stress, and asserts the edge still nets positive after stress —
i.e. realized PnL survives, not just the disclosed margin.

The fixture is deterministic and data-free (synthetic quotes), so it runs
in the standard suite.  The full data-backed survival run is exercised
separately by the APP backtest under ``--inv12-stress`` (functional).
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    stressed_fill_latency_ns,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig


def _quote(bid: str, ask: str, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=10_000,
        ask_size=10_000,
        exchange_timestamp_ns=ts,
        sequence_number=ts,
    )


def _order(side: Side, oid: str, seq: int) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=seq,
        order_id=oid,
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=1_000,
    )


def _net_pnl_and_fees(stress_multiplier: Decimal) -> tuple[Decimal, Decimal]:
    """Run a 1000-share buy → sell round trip with a +$0.50/share edge."""
    cost_model = DefaultCostModel(
        DefaultCostModelConfig(stress_multiplier=stress_multiplier)
    )
    router = BacktestOrderRouter(SimulatedClock(start_ns=0), cost_model=cost_model)

    # Entry: buy lifts the ask at 100.05.
    router.on_quote(_quote("100.00", "100.05", 1000))
    router.submit(_order(Side.BUY, "buy", 1))
    # Exit: price has moved up $0.50; sell hits the bid at 100.50.
    router.on_quote(_quote("100.50", "100.55", 2000))
    router.submit(_order(Side.SELL, "sell", 2))

    acks: list[OrderAck] = router.poll_acks()
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]

    net = Decimal("0")
    fees = Decimal("0")
    for a in fills:
        assert a.fill_price is not None and a.fees is not None
        notional = a.fill_price * Decimal(a.filled_quantity)
        if a.order_id == "buy":
            net -= notional + a.fees
        else:
            net += notional - a.fees
        fees += a.fees
    return net, fees


def test_known_edge_survives_inv12_cost_stress() -> None:
    base_net, base_fees = _net_pnl_and_fees(Decimal("1.0"))
    stressed_net, stressed_fees = _net_pnl_and_fees(
        Decimal(str(INV12_COST_STRESS_MULTIPLIER))
    )

    # The +$0.50/share edge clears costs in both regimes (survival).
    assert base_net > 0
    assert stressed_net > 0
    # Stress is real: it costs more and shaves PnL, never the reverse.
    assert stressed_fees >= base_fees
    assert stressed_net <= base_net


def test_inv12_cost_stress_scales_variable_fees() -> None:
    """Variable cost lines scale ~1.5× (fixed floors damp the exact ratio)."""
    _, base_fees = _net_pnl_and_fees(Decimal("1.0"))
    _, stressed_fees = _net_pnl_and_fees(Decimal(str(INV12_COST_STRESS_MULTIPLIER)))
    assert stressed_fees > base_fees
    # At 1000 shares the per-share commission clears the fixed floor, so every
    # cost line is variable and scales ~1.5× (within per-leg cent rounding).
    ratio = stressed_fees / base_fees
    assert Decimal("1.49") <= ratio <= Decimal("1.51")


def test_inv12_latency_leg_doubles() -> None:
    assert stressed_fill_latency_ns(50_000_000) == 100_000_000
    assert stressed_fill_latency_ns(0) == 0
