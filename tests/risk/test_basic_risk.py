"""Tests for BasicRiskEngine — position limits, exposure caps, regime scaling."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    Side,
    Signal,
    SignalDirection,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.services.regime_engine import HMM3StateFractional


def _make_signal(
    symbol: str = "AAPL",
    direction: SignalDirection = SignalDirection.LONG,
    strength: float = 0.8,
    edge_bps: float = 2.0,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        strategy_id="test_alpha",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )


def _make_order(
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    quantity: int = 100,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        order_id="ord-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )


@pytest.fixture
def config() -> RiskConfig:
    return RiskConfig(
        max_position_per_symbol=1000,
        max_gross_exposure_pct=20.0,
        account_equity=Decimal("1000000"),
    )


@pytest.fixture
def store() -> MemoryPositionStore:
    return MemoryPositionStore()


class TestCheckSignal:
    def test_position_limit_exceeded_scale_down_or_reject(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        store.update("AAPL", 1000, Decimal("150"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.REJECT
        assert "position limit" in verdict.reason

    def test_within_limits_allows(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        store.update("AAPL", 100, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.ALLOW

    def test_exposure_exceeded_rejects(self, store: MemoryPositionStore) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=1.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        # exposure = 10000 * 10 = 100_000, limit = 100000 * 1% = 1000
        store.update("AAPL", 10000, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.REJECT
        assert "gross exposure" in verdict.reason

    def test_no_position_allows(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.ALLOW


class TestCheckOrder:
    def test_buy_within_limits_allows(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        order = _make_order(side=Side.BUY, quantity=100)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.ALLOW

    def test_sell_side_signed_delta(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        """Selling 100 from a 200 long position leaves |100| < 1000 limit."""
        engine = BasicRiskEngine(config)
        store.update("AAPL", 200, Decimal("150"))
        order = _make_order(side=Side.SELL, quantity=100)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.ALLOW

    def test_post_fill_exceeds_limit_rejects(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        store.update("AAPL", 950, Decimal("150"))
        order = _make_order(side=Side.BUY, quantity=100)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.REJECT
        assert "post-fill" in verdict.reason

    def test_gross_exposure_exceeded_rejects(
        self, store: MemoryPositionStore
    ) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=1.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 10_000, Decimal("10"))
        order = _make_order(side=Side.BUY, quantity=10)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.REJECT
        assert "gross exposure" in verdict.reason

    def test_drawdown_breached_force_flattens(
        self, store: MemoryPositionStore
    ) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=100.0,
            max_drawdown_pct=1.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 100, Decimal("100"))
        store.update("AAPL", -100, Decimal("90"))
        order = _make_order(side=Side.BUY, quantity=10)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.FORCE_FLATTEN
        assert "drawdown" in verdict.reason

    def test_approaching_exposure_scales_down(
        self, store: MemoryPositionStore
    ) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            account_equity=Decimal("100000"),
            scale_down_threshold_pct=0.8,
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 900, Decimal("10"))
        order = _make_order(side=Side.BUY, quantity=50)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.SCALE_DOWN
        assert "approaching exposure" in verdict.reason
        assert 0.0 < verdict.scaling_factor < 1.0


class TestRegimeScaling:
    def test_vol_breakout_reduces_position_limit(
        self, store: MemoryPositionStore
    ) -> None:
        """In pure vol_breakout regime, EV scale = 0.5, limit = 500."""
        regime = HMM3StateFractional()
        cfg = RiskConfig(
            max_position_per_symbol=1000,
            max_gross_exposure_pct=50.0,
            account_equity=Decimal("10000000"),
        )
        engine = BasicRiskEngine(cfg, regime_engine=regime)

        regime._posteriors["AAPL"] = [0.0, 0.0, 1.0]

        # EV = 1.0*0.5 = 0.5, adjusted_max = 500, so 500 shares hits limit
        store.update("AAPL", 500, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.REJECT

    def test_no_regime_engine_uses_full_limits(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config, regime_engine=None)
        store.update("AAPL", 999, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)


class TestMarkToMarketExposureAndDrawdown:
    """Exposure caps and drawdown must use live marks, not cost basis."""

    def test_mark_raises_exposure_above_cap(
        self, store: MemoryPositionStore
    ) -> None:
        """A long that rallies hard must show up against the gross cap.

        Before marks: exposure = 500 × $10 = $5000 (under 10% of $100k).
        After mark to $30: exposure = 500 × $30 = $15000 (over cap).
        """
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 500, Decimal("10"))

        # Pre-mark: exposure at cost basis, well under cap.
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.ALLOW

        # After price triples, MTM exposure exceeds cap.
        store.update_mark("AAPL", Decimal("30"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.REJECT
        assert "gross exposure" in verdict.reason

    def test_unrealized_loss_triggers_drawdown_force_flatten(
        self, store: MemoryPositionStore
    ) -> None:
        """Open losses must be visible to the drawdown guard.

        Realized PnL is zero; only unrealized moves.  Pre-fix this
        would have silently passed because ``_is_drawdown_breached``
        used realized-only equity.
        """
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=100.0,
            max_drawdown_pct=1.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        # Small position so exposure stays well under cap; the 20%
        # adverse mark gives a $2k unrealized loss = 2% drawdown.
        store.update("AAPL", 100, Decimal("100"))
        store.update_mark("AAPL", Decimal("80"))

        order = _make_order(side=Side.BUY, quantity=10)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.FORCE_FLATTEN
        assert "drawdown" in verdict.reason

    def test_dynamic_equity_compounds_exposure_cap(
        self, store: MemoryPositionStore
    ) -> None:
        """Exposure cap compounds with equity.

        After realizing a $50k gain on a $100k book, the 10% cap
        should apply against $150k, not stay pinned to $100k.
        """
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=99.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        # Book +$50k realized; then open a new 1200-share long at $10
        # (exposure $12k).  Static cap would reject at 10% of $100k =
        # $10k; dynamic cap allows up to $15k.
        store.update("AAPL", 100, Decimal("100"))
        store.update("AAPL", -100, Decimal("600"))  # realize +$50k
        store.update("MSFT", 1200, Decimal("10"))
        store.update_mark("MSFT", Decimal("10"))

        verdict = engine.check_signal(_make_signal(symbol="MSFT"), store)
        assert verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)
