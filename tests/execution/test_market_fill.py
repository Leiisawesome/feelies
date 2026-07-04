"""Direct unit tests for ``market_fill.py`` — the shared aggressive-fill
chokepoint both ``BacktestOrderRouter`` and ``PassiveLimitOrderRouter``
delegate to (audit execution_fills_audit_2026-07-02, P2 backlog: this module
previously had no isolated test file — coverage was embedded only in the two
router test files, ``test_router_latency.py``, and the determinism golden
replay).
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import NBBOQuote, OrderAckStatus, OrderRequest, OrderType, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.market_fill import append_market_fill_acks, base_impact_premium


def _quote(bid: str, ask: str, *, bid_size: int = 100, ask_size: int = 100) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_000,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=1_000,
    )


def _order(
    side: Side,
    quantity: int,
    *,
    reason: str = "",
    limit_price: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1_000,
        correlation_id="o",
        sequence=1,
        order_id="ord1",
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        reason=reason,
        limit_price=Decimal(limit_price) if limit_price is not None else None,
    )


class TestBaseImpactPremium:
    def test_zero_when_depth_or_quantity_non_positive(self) -> None:
        common = dict(
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0.5"),
            permanent_impact_coefficient=Decimal("0.5"),
        )
        assert base_impact_premium(quantity=100, available_depth=0, **common) == Decimal("0")
        assert base_impact_premium(quantity=0, available_depth=100, **common) == Decimal("0")

    def test_zero_when_both_factors_disabled(self) -> None:
        premium = base_impact_premium(
            quantity=100,
            available_depth=200,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0"),
            permanent_impact_coefficient=Decimal("0"),
        )
        assert premium == Decimal("0")

    def test_temporary_component_linear_in_participation(self) -> None:
        # participation = 50/200 = 0.25; temporary = 0.5 * 0.25 * 0.05 = 0.00625
        premium = base_impact_premium(
            quantity=50,
            available_depth=200,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0.5"),
            permanent_impact_coefficient=Decimal("0"),
        )
        assert premium == Decimal("0.00625")

    def test_temporary_component_capped_at_full_participation(self) -> None:
        # quantity > available_depth -> participation capped at 1.
        premium = base_impact_premium(
            quantity=400,
            available_depth=200,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0.5"),
            permanent_impact_coefficient=Decimal("0"),
        )
        assert premium == Decimal("0.025")  # 0.5 * 1 * 0.05

    def test_permanent_component_uses_sqrt_of_participation(self) -> None:
        # participation = 100/400 = 0.25; sqrt(0.25) = 0.5.
        # permanent = 0.2 * 0.5 * 0.05 = 0.005
        premium = base_impact_premium(
            quantity=100,
            available_depth=400,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0"),
            permanent_impact_coefficient=Decimal("0.2"),
        )
        assert premium == Decimal("0.005")

    def test_temporary_and_permanent_are_additive(self) -> None:
        temp_only = base_impact_premium(
            quantity=100,
            available_depth=400,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0.5"),
            permanent_impact_coefficient=Decimal("0"),
        )
        perm_only = base_impact_premium(
            quantity=100,
            available_depth=400,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0"),
            permanent_impact_coefficient=Decimal("0.2"),
        )
        combined = base_impact_premium(
            quantity=100,
            available_depth=400,
            raw_half_spread=Decimal("0.05"),
            within_l1_impact_factor=Decimal("0.5"),
            permanent_impact_coefficient=Decimal("0.2"),
        )
        assert combined == temp_only + perm_only


class TestAppendMarketFillAcks:
    def test_buy_fills_at_ask_within_depth(self) -> None:
        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.BUY, 50),
            _quote("100.00", "100.05", ask_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("100.05")
        assert acks[0].filled_quantity == 50

    def test_sell_fills_at_bid_within_depth(self) -> None:
        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.SELL, 50),
            _quote("100.00", "100.05", bid_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )
        assert len(acks) == 1
        assert acks[0].fill_price == Decimal("100.00")

    def test_quantity_exceeding_depth_splits_partial_and_impact_legs(self) -> None:
        """D14: excess over displayed depth fills at an impact-adjusted price,
        strictly worse than the cross, in a separate FILLED ack."""
        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.BUY, 150),
            _quote("100.00", "100.05", ask_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )
        assert [a.status for a in acks] == [
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        ]
        assert acks[0].filled_quantity == 100
        assert acks[0].fill_price == Decimal("100.05")
        assert acks[1].filled_quantity == 50
        assert acks[1].fill_price > Decimal("100.05")  # walked worse than the cross

    def test_zero_impact_factor_keeps_excess_leg_at_cross_price(self) -> None:
        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.BUY, 150),
            _quote("100.00", "100.05", ask_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0"),
            max_impact_half_spreads=Decimal("10"),
        )
        assert acks[1].fill_price == Decimal("100.05")

    def test_stop_exit_pays_extra_spread_via_fees(self) -> None:
        from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig

        cfg = DefaultCostModelConfig(
            sell_regulatory_bps=Decimal("0"), finra_taf_per_share=Decimal("0")
        )
        normal_acks: list = []
        stop_acks: list = []
        append_market_fill_acks(
            normal_acks,
            SequenceGenerator(),
            DefaultCostModel(cfg),
            _order(Side.SELL, 50, reason=""),
            _quote("100.00", "100.10"),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
            stop_slippage_half_spreads=Decimal("2.0"),
        )
        append_market_fill_acks(
            stop_acks,
            SequenceGenerator(),
            DefaultCostModel(cfg),
            _order(Side.SELL, 50, reason="STOP_EXIT"),
            _quote("100.00", "100.10"),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
            stop_slippage_half_spreads=Decimal("2.0"),
        )
        assert stop_acks[0].fees > normal_acks[0].fees
        # The fill *price* is identical (the touch) — the penalty is billed as
        # a fee, not a worse cross price.
        assert stop_acks[0].fill_price == normal_acks[0].fill_price

    def test_stop_exit_depth_depletion_walks_more_of_the_order(self) -> None:
        """A forced exit with depth-depletion enabled sees a smaller effective
        L1 depth, so more of a same-sized order lands on the impact-adjusted
        excess leg than a normal exit would."""
        normal_acks: list = []
        stop_acks: list = []
        append_market_fill_acks(
            normal_acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.SELL, 80, reason=""),
            _quote("100.00", "100.10", bid_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
            stop_depth_depletion_factor=Decimal("2.0"),
        )
        append_market_fill_acks(
            stop_acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.SELL, 80, reason="STOP_EXIT"),
            _quote("100.00", "100.10", bid_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
            stop_depth_depletion_factor=Decimal("2.0"),
        )
        # Normal: 80 <= depth 100 -> single full fill, no impact leg.
        assert [a.status for a in normal_acks] == [OrderAckStatus.FILLED]
        # Stop: effective depth halved to 50 -> 80 > 50 -> partial + impact leg.
        assert [a.status for a in stop_acks] == [
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        ]

    def test_marketable_limit_never_fills_worse_than_limit_price(self) -> None:
        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.BUY, 150, limit_price="100.06"),
            _quote("100.00", "100.05", ask_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("2.0"),  # large impact to force a clamp
            max_impact_half_spreads=Decimal("10"),
        )
        assert all(a.fill_price <= Decimal("100.06") for a in acks)

    def test_fill_prices_are_on_the_tick_grid(self) -> None:
        from feelies.execution.tick_size import is_on_tick_grid

        acks: list = []
        append_market_fill_acks(
            acks,
            SequenceGenerator(),
            ZeroCostModel(),
            _order(Side.BUY, 150),
            _quote("100.011", "100.017", ask_size=100),
            fill_ts=2_000,
            market_impact_factor=Decimal("0.33"),
            max_impact_half_spreads=Decimal("10"),
        )
        assert all(is_on_tick_grid(a.fill_price) for a in acks if a.fill_price is not None)
