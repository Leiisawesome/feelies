"""Tests for StrategyPositionStore — per-strategy isolation with aggregate view."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.portfolio.strategy_position_store import StrategyPositionStore


@pytest.fixture
def store() -> StrategyPositionStore:
    return StrategyPositionStore()


class TestStrategyIsolation:
    def test_two_strategies_same_symbol_separate_positions(
        self, store: StrategyPositionStore
    ) -> None:
        store.update("alpha_1", "AAPL", 100, Decimal("150"))
        store.update("alpha_2", "AAPL", 200, Decimal("155"))

        pos_1 = store.get("alpha_1", "AAPL")
        pos_2 = store.get("alpha_2", "AAPL")

        assert pos_1.quantity == 100
        assert pos_1.avg_entry_price == Decimal("150")
        assert pos_2.quantity == 200
        assert pos_2.avg_entry_price == Decimal("155")

    def test_update_one_strategy_does_not_affect_other(
        self, store: StrategyPositionStore
    ) -> None:
        store.update("alpha_1", "AAPL", 100, Decimal("150"))
        store.update("alpha_2", "AAPL", 50, Decimal("160"))
        store.update("alpha_1", "AAPL", -50, Decimal("170"))

        assert store.get("alpha_1", "AAPL").quantity == 50
        assert store.get("alpha_2", "AAPL").quantity == 50


class TestGetAggregate:
    def test_sums_quantities_across_strategies(
        self, store: StrategyPositionStore
    ) -> None:
        store.update("alpha_1", "AAPL", 100, Decimal("150"))
        store.update("alpha_2", "AAPL", 200, Decimal("155"))

        agg = store.get_aggregate("AAPL")
        assert agg.quantity == 300

    def test_unknown_symbol_returns_zero(self, store: StrategyPositionStore) -> None:
        agg = store.get_aggregate("TSLA")
        assert agg.quantity == 0
        assert agg.avg_entry_price == Decimal("0")

    def test_weighted_avg_price(self, store: StrategyPositionStore) -> None:
        store.update("a", "AAPL", 100, Decimal("10"))
        store.update("b", "AAPL", 100, Decimal("20"))
        agg = store.get_aggregate("AAPL")
        assert agg.avg_entry_price == Decimal("15")

    def test_mixed_direction_avg_price_not_inflated(
        self, store: StrategyPositionStore,
    ) -> None:
        """Long + short across strategies must not inflate avg_entry_price.

        Before the fix, +100@10 / -50@20 produced avg=40 (impossible).
        Signed-notional / net-qty gives avg=0: the short's proceeds
        fully offset the long's cost for the net 50 shares.
        """
        store.update("long_alpha", "AAPL", 100, Decimal("10"))
        store.update("short_alpha", "AAPL", -50, Decimal("20"))

        agg = store.get_aggregate("AAPL")
        assert agg.quantity == 50
        expected = (Decimal("10") * 100 + Decimal("20") * (-50)) / 50
        assert agg.avg_entry_price == expected  # Decimal("0")

    def test_near_full_offset_avg_price(
        self, store: StrategyPositionStore,
    ) -> None:
        """Near-complete offset: net 1 share should not show inflated price."""
        store.update("a", "AAPL", 100, Decimal("10"))
        store.update("b", "AAPL", -99, Decimal("20"))

        agg = store.get_aggregate("AAPL")
        assert agg.quantity == 1
        expected = (Decimal("10") * 100 + Decimal("20") * (-99)) / 1
        assert agg.avg_entry_price == expected  # Decimal("-980")

    def test_full_offset_avg_price_zero(
        self, store: StrategyPositionStore,
    ) -> None:
        """Fully offsetting positions yield zero avg_entry_price."""
        store.update("a", "AAPL", 100, Decimal("10"))
        store.update("b", "AAPL", -100, Decimal("20"))

        agg = store.get_aggregate("AAPL")
        assert agg.quantity == 0
        assert agg.avg_entry_price == Decimal("0")

    def test_same_direction_unaffected(
        self, store: StrategyPositionStore,
    ) -> None:
        """Same-direction aggregation still works correctly after the fix."""
        store.update("a", "AAPL", 100, Decimal("10"))
        store.update("b", "AAPL", 200, Decimal("25"))

        agg = store.get_aggregate("AAPL")
        assert agg.quantity == 300
        expected = (Decimal("10") * 100 + Decimal("25") * 200) / 300
        assert agg.avg_entry_price == expected  # Decimal("20")


class TestTotalExposure:
    def test_aggregates_across_strategies(self, store: StrategyPositionStore) -> None:
        store.update("alpha_1", "AAPL", 100, Decimal("10"))
        store.update("alpha_2", "MSFT", 50, Decimal("20"))
        # 100*10 + 50*20 = 1000 + 1000 = 2000
        assert store.total_exposure() == Decimal("2000")

    def test_empty_store_zero_exposure(self, store: StrategyPositionStore) -> None:
        assert store.total_exposure() == Decimal("0")


class TestAsAggregate:
    def test_returns_position_store_interface(self, store: StrategyPositionStore) -> None:
        agg = store.as_aggregate()
        store.update("alpha_1", "AAPL", 100, Decimal("150"))
        pos = agg.get("AAPL")
        assert pos.quantity == 100

    def test_all_positions_returns_aggregate(self, store: StrategyPositionStore) -> None:
        store.update("a", "AAPL", 100, Decimal("10"))
        store.update("b", "MSFT", 50, Decimal("20"))
        agg = store.as_aggregate()
        all_pos = agg.all_positions()
        assert set(all_pos.keys()) == {"AAPL", "MSFT"}

    def test_total_exposure_delegates(self, store: StrategyPositionStore) -> None:
        store.update("a", "AAPL", 100, Decimal("10"))
        agg = store.as_aggregate()
        assert agg.total_exposure() == Decimal("1000")

    def test_update_raises_runtime_error(self, store: StrategyPositionStore) -> None:
        agg = store.as_aggregate()
        with pytest.raises(RuntimeError, match="Cannot update aggregate view"):
            agg.update("AAPL", 100, Decimal("10"))
