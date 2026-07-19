"""Tests for BasicRiskEngine — position limits, exposure caps, regime scaling."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.buying_power import BuyingPowerConfig
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


def _make_sized_intent(
    strategy_id: str = "portfolio_alpha",
    targets: dict[str, float] | None = None,
) -> SizedPositionIntent:
    return SizedPositionIntent(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        strategy_id=strategy_id,
        target_positions={
            symbol: TargetPosition(symbol=symbol, target_usd=target_usd)
            for symbol, target_usd in (targets or {}).items()
        },
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

    def test_within_limits_allows(self, config: RiskConfig, store: MemoryPositionStore) -> None:
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

    def test_no_position_allows(self, config: RiskConfig, store: MemoryPositionStore) -> None:
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

    def test_sell_side_signed_delta(self, config: RiskConfig, store: MemoryPositionStore) -> None:
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

    def test_gross_exposure_exceeded_rejects(self, store: MemoryPositionStore) -> None:
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

    def test_drawdown_breached_force_flattens(self, store: MemoryPositionStore) -> None:
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

    def test_approaching_exposure_scales_down(self, store: MemoryPositionStore) -> None:
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
    def test_vol_breakout_reduces_position_limit(self, store: MemoryPositionStore) -> None:
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

    def test_mark_raises_exposure_above_cap(self, store: MemoryPositionStore) -> None:
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

    def test_dynamic_equity_compounds_exposure_cap(self, store: MemoryPositionStore) -> None:
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

    def test_order_gate_uses_prospective_exposure(
        self,
        store: MemoryPositionStore,
    ) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 50, Decimal("100"))
        store.update_mark("AAPL", Decimal("150"))

        order = _make_order(side=Side.BUY, quantity=50)
        verdict = engine.check_order(order, store)

        assert verdict.action == RiskAction.REJECT
        assert "gross exposure" in verdict.reason


class TestSizedIntentMarkSelection:
    def test_live_mark_overrides_avg_entry_for_open_positions(
        self,
        config: RiskConfig,
        store: MemoryPositionStore,
    ) -> None:
        engine = BasicRiskEngine(config)
        store.update("AAPL", 200, Decimal("100"))
        store.update_mark("AAPL", Decimal("125"))

        orders = engine.check_sized_intent(
            _make_sized_intent(targets={"AAPL": 50_000.0}),
            store,
        ).orders

        assert len(orders) == 1
        order = orders[0]
        assert order.symbol == "AAPL"
        assert order.side == Side.BUY
        assert order.quantity == 200


class TestSizedIntentDroppedLegAlert:
    """Audit R4: per-leg PORTFOLIO veto must surface a diagnostic Alert.

    Without the Alert, a partial portfolio-construction execution
    silently executes the surviving legs without re-validating any
    cross-sectional invariant (dollar-neutral, sector-matched,
    mechanism-capped) the alpha intended.
    """

    def test_dropped_leg_publishes_alert_with_full_attribution(
        self, store: MemoryPositionStore
    ) -> None:
        from feelies.bus.event_bus import EventBus
        from feelies.core.events import Alert
        from feelies.core.identifiers import SequenceGenerator

        bus = EventBus()
        captured: list[Alert] = []
        bus.subscribe(Alert, captured.append)  # type: ignore[arg-type]

        # Tight per-symbol cap so MSFT will be vetoed; AAPL passes.
        cfg = RiskConfig(
            max_position_per_symbol=100,
            max_gross_exposure_pct=100.0,
            account_equity=Decimal("1000000"),
        )
        engine = BasicRiskEngine(
            cfg,
            bus=bus,
            alert_sequence_generator=SequenceGenerator(),
        )
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))
        store.update("MSFT", 0, Decimal("200"))
        store.update_mark("MSFT", Decimal("200"))

        intent = _make_sized_intent(
            targets={"AAPL": 5_000.0, "MSFT": 60_000.0},
        )
        orders = engine.check_sized_intent(intent, store).orders

        assert {o.symbol for o in orders} == {"AAPL"}
        assert len(captured) == 1
        alert = captured[0]
        assert alert.alert_name == "portfolio_intent_partial_execution"
        assert alert.context["strategy_id"] == intent.strategy_id
        assert alert.context["total_legs"] == 2
        dropped_syms = {d["symbol"] for d in alert.context["dropped_legs"]}
        assert dropped_syms == {"MSFT"}

    def test_no_alert_when_all_legs_execute(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        from feelies.bus.event_bus import EventBus
        from feelies.core.events import Alert
        from feelies.core.identifiers import SequenceGenerator

        bus = EventBus()
        captured: list[Alert] = []
        bus.subscribe(Alert, captured.append)  # type: ignore[arg-type]

        engine = BasicRiskEngine(
            config,
            bus=bus,
            alert_sequence_generator=SequenceGenerator(),
        )
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))

        engine.check_sized_intent(
            _make_sized_intent(targets={"AAPL": 5_000.0}),
            store,
        )

        assert captured == []

    def test_engine_works_without_bus_wired(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        """Backwards-compat: bus + seq are optional; logging still fires."""
        engine = BasicRiskEngine(config)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))

        orders = engine.check_sized_intent(
            _make_sized_intent(targets={"AAPL": 5_000.0}),
            store,
        ).orders
        assert len(orders) == 1


class TestSizedIntentDrawdownAbortsWholeIntent:
    def test_force_flatten_on_one_leg_returns_empty_orders_and_flag(self) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=100.0,
            max_drawdown_pct=1.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store = MemoryPositionStore()
        store.update("AAPL", 100, Decimal("100"))
        store.update("AAPL", -100, Decimal("90"))
        store.update_mark("AAPL", Decimal("90"))
        store.update("MSFT", 0, Decimal("200"))
        store.update_mark("MSFT", Decimal("200"))

        intent = _make_sized_intent(
            targets={"AAPL": 5_000.0, "MSFT": 10_000.0},
        )
        result = engine.check_sized_intent(intent, store)
        assert result.orders == ()
        assert result.requires_global_risk_escalation is True


class TestPortfolioOrderG12Disclosure:
    """Audit R3: PORTFOLIO orders must carry the per-symbol disclosed cost.

    Without the stamp, the post-fill cost-vs-disclosure stress alert
    in the orchestrator (only fires when ``g12_disclosed_cost_total_bps
    > 0``) is silently disabled for every PORTFOLIO leg — and PORTFOLIO
    is the only production-reachable order path post-D.2.
    """

    def test_portfolio_order_carries_disclosed_cost_per_symbol(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))
        store.update("MSFT", 0, Decimal("200"))
        store.update_mark("MSFT", Decimal("200"))

        intent = SizedPositionIntent(
            timestamp_ns=1_000_000_000,
            correlation_id="corr-1",
            sequence=1,
            strategy_id="portfolio_alpha",
            target_positions={
                "AAPL": TargetPosition(symbol="AAPL", target_usd=5_000.0),
                "MSFT": TargetPosition(symbol="MSFT", target_usd=8_000.0),
            },
            disclosed_cost_total_bps_by_symbol={
                "AAPL": 3.5,
                "MSFT": 4.25,
            },
        )
        orders = engine.check_sized_intent(intent, store).orders

        by_symbol = {o.symbol: o for o in orders}
        assert by_symbol["AAPL"].g12_disclosed_cost_total_bps == 3.5
        assert by_symbol["MSFT"].g12_disclosed_cost_total_bps == 4.25

    def test_missing_per_symbol_disclosure_defaults_to_zero(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        """Backwards-compat: empty map → 0.0, alert remains gated off."""
        engine = BasicRiskEngine(config)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))

        orders = engine.check_sized_intent(
            _make_sized_intent(targets={"AAPL": 5_000.0}),
            store,
        ).orders
        assert len(orders) == 1
        assert orders[0].g12_disclosed_cost_total_bps == 0.0


class TestSizedIntentCumulativeGrossCap:
    """Audit R-1: the gross cap must bind across legs of one intent.

    Each leg's ``check_order`` previously saw only the pre-intent
    ``positions`` snapshot, so K legs each individually under the cap
    could collectively breach it.  ``build_sized_intent_orders`` now
    threads the running admitted gross into ``additional_exposure``.
    """

    def test_second_leg_dropped_when_aggregate_breaches_cap(
        self, store: MemoryPositionStore
    ) -> None:
        # max_gross = 10% of $100k = $10,000.  Two flat symbols at $100.
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=99.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))
        store.update("MSFT", 0, Decimal("100"))
        store.update_mark("MSFT", Decimal("100"))

        # Each leg is $6,000 (< $10k cap) in isolation; together $12,000.
        intent = _make_sized_intent(targets={"AAPL": 6_000.0, "MSFT": 6_000.0})
        result = engine.check_sized_intent(intent, store)

        # Lexicographic order admits AAPL, then MSFT breaches the running
        # cap and is veto-dropped — the rest of the intent is unaffected.
        assert {o.symbol for o in result.orders} == {"AAPL"}
        assert result.requires_global_risk_escalation is False

    def test_both_legs_pass_when_aggregate_within_cap(self, store: MemoryPositionStore) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=99.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))
        store.update("MSFT", 0, Decimal("100"))
        store.update_mark("MSFT", Decimal("100"))

        # $4,000 + $4,000 = $8,000 < $10k cap → both admitted.
        intent = _make_sized_intent(targets={"AAPL": 4_000.0, "MSFT": 4_000.0})
        result = engine.check_sized_intent(intent, store)
        assert {o.symbol for o in result.orders} == {"AAPL", "MSFT"}


class TestSizedIntentRaisingCheckContained:
    """Audit R-2: a raising per-leg check_order must not propagate."""

    def test_raising_leg_is_veto_dropped(self, config: RiskConfig) -> None:
        engine = BasicRiskEngine(config)
        store = MemoryPositionStore()
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))
        store.update("MSFT", 0, Decimal("100"))
        store.update_mark("MSFT", Decimal("100"))

        def boom_check_order(
            self: BasicRiskEngine,
            order: OrderRequest,
            positions: MemoryPositionStore,
            *,
            additional_exposure: Decimal = Decimal("0"),
        ) -> RiskVerdict:
            if order.symbol == "AAPL":
                raise RuntimeError("position store glitch")
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.ALLOW,
                reason="ok",
            )

        with patch.object(BasicRiskEngine, "check_order", boom_check_order):
            # Must not raise; AAPL is dropped, MSFT proceeds.
            result = engine.check_sized_intent(
                _make_sized_intent(targets={"AAPL": 5_000.0, "MSFT": 5_000.0}),
                store,
            )
        assert {o.symbol for o in result.orders} == {"MSFT"}
        assert result.requires_global_risk_escalation is False


class TestNonPositiveEquityForceFlattens:
    """Audit R-6: a wiped-out book must force-flatten, never size against
    initial capital it no longer has — independent of drawdown config."""

    def test_negative_equity_force_flattens_even_with_loose_drawdown(
        self, store: MemoryPositionStore
    ) -> None:
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=1000.0,  # deliberately permissive
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(cfg)
        # Unrealized loss of $120k drives live equity to −$20k.
        store.update("AAPL", 2000, Decimal("100"))
        store.update_mark("AAPL", Decimal("40"))

        order = _make_order(symbol="MSFT", side=Side.BUY, quantity=10)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.FORCE_FLATTEN
        assert "non-positive equity" in verdict.reason

    def test_negative_equity_force_flattens_entry_with_buying_power_wired(
        self, store: MemoryPositionStore
    ) -> None:
        """Audit FS-2 (risk_engine_audit_2026-07-02.md).

        Reproduces the bootstrap-realistic configuration (``bootstrap.py``
        wires ``BuyingPowerConfig`` unconditionally for every mode): before
        the FS-2 fix, ``_check_buying_power`` ran ahead of
        ``_check_exposure_and_drawdown`` inside ``check_order`` and
        ``buying_power_limit`` returns ``Decimal("0")`` for non-positive
        equity, so an ENTRY order was rejected with
        ``INSUFFICIENT_BUYING_POWER`` instead of reaching the intended
        unconditional ``FORCE_FLATTEN``.  The prior test in this class
        (``test_negative_equity_force_flattens_even_with_loose_drawdown``)
        does not catch this because it constructs the engine with no
        ``buying_power_config`` at all.
        """
        cfg = RiskConfig(
            max_position_per_symbol=100_000,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=1000.0,
            account_equity=Decimal("100000"),
        )
        engine = BasicRiskEngine(
            cfg,
            buying_power_config=BuyingPowerConfig(account_type="margin_25k"),
        )
        # Unrealized loss of $120k drives live equity to -$20k.
        store.update("AAPL", 2000, Decimal("100"))
        store.update_mark("AAPL", Decimal("40"))

        order = _make_order(symbol="MSFT", side=Side.BUY, quantity=10)
        verdict = engine.check_order(order, store)
        assert verdict.action == RiskAction.FORCE_FLATTEN
        assert "non-positive equity" in verdict.reason


class TestRegimeMissingDataFailsSafe:
    """Audit R-3: a configured engine with no committed posterior for the
    symbol tightens to min(scales), not the 1.0 baseline."""

    def test_missing_posterior_uses_min_scale(self, store: MemoryPositionStore) -> None:
        regime = HMM3StateFractional()  # no posterior committed for AAPL
        cfg = RiskConfig(
            max_position_per_symbol=1000,
            max_gross_exposure_pct=50.0,
            account_equity=Decimal("10000000"),
        )
        engine = BasicRiskEngine(cfg, regime_engine=regime)
        # min scale = 0.5 → adjusted_max = 500; a 500-share book is at cap.
        store.update("AAPL", 500, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action == RiskAction.REJECT

    def test_no_engine_still_full_limit(
        self, config: RiskConfig, store: MemoryPositionStore
    ) -> None:
        engine = BasicRiskEngine(config, regime_engine=None)
        store.update("AAPL", 500, Decimal("10"))
        verdict = engine.check_signal(_make_signal(), store)
        assert verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)

    def test_regime_scaling_never_amplifies_above_one(self) -> None:
        regime = HMM3StateFractional()
        regime._posteriors["AAPL"] = [0.0, 1.0, 0.0]  # 100% "normal"
        cfg = RiskConfig(max_position_per_symbol=1000, account_equity=Decimal("100000"))
        engine = BasicRiskEngine(cfg, regime_engine=regime)
        # Misconfigure the "normal" scale to an amplifier; the clamp caps EV
        # at 1.0 so the limit never exceeds the unscaled baseline.
        engine._regime_scale_map["normal"] = 2.0
        assert engine._regime_scaling("AAPL") <= 1.0

    def test_nan_posterior_fails_safe_to_min_scale_not_baseline(self) -> None:
        """Audit FS (risk_engine_audit_2026-07-02.md, §3.2).

        A third-party ``RegimeEngine`` that fails to sanitize its own
        posterior (the shipped ``HMM3StateFractional`` always does) could
        produce a NaN EV.  ``min(1.0, float("nan"))`` evaluates to ``1.0``
        under Python's comparison semantics — the *unscaled baseline*, not
        the intended fail-safe minimum.  Directly seeding ``_posteriors``
        bypasses ``posterior()``'s own sanitization to simulate exactly
        that unsanitized-engine scenario.
        """
        regime = HMM3StateFractional()
        regime._posteriors["AAPL"] = [float("nan"), 0.0, 0.0]
        cfg = RiskConfig(max_position_per_symbol=1000, account_equity=Decimal("100000"))
        engine = BasicRiskEngine(cfg, regime_engine=regime)
        assert engine._regime_scaling("AAPL") == engine._regime_scale_default


class TestSizedIntentScaleDownDecimal:
    def test_scale_down_quantity_uses_half_up_not_float_truncation(
        self,
        config: RiskConfig,
        store: MemoryPositionStore,
    ) -> None:
        """10 × 0.45 = 4.5 → 5 shares (Decimal); int(10*0.45) truncates to 4."""

        engine = BasicRiskEngine(config)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))

        def fake_check_order(
            self: BasicRiskEngine,
            order: OrderRequest,
            positions: MemoryPositionStore,
            *,
            additional_exposure: Decimal = Decimal("0"),
        ) -> RiskVerdict:
            if order.symbol == "AAPL" and order.quantity == 10:
                return RiskVerdict(
                    timestamp_ns=order.timestamp_ns,
                    correlation_id=order.correlation_id,
                    sequence=order.sequence,
                    symbol=order.symbol,
                    action=RiskAction.SCALE_DOWN,
                    reason="test_scale_down",
                    scaling_factor=0.45,
                )
            return BasicRiskEngine.check_order(self, order, positions)

        with patch.object(BasicRiskEngine, "check_order", fake_check_order):
            orders = engine.check_sized_intent(
                _make_sized_intent(targets={"AAPL": 1_000.0}),
                store,
            ).orders
        assert len(orders) == 1
        assert orders[0].quantity == 5

    def test_scale_down_to_zero_drops_the_leg(
        self,
        config: RiskConfig,
        store: MemoryPositionStore,
    ) -> None:
        """Audit FS-3 (risk_engine_audit_2026-07-02.md).

        2 x 0.1 = 0.2 rounds to 0 shares (``ROUND_HALF_UP``).  Before the
        FS-3 fix this was floored to a minimum 1-share order regardless of
        how aggressively the risk engine intended to scale down; the leg
        must instead drop, mirroring the SIGNAL path's
        ``_compose_scaled_quantity`` + ``scaled_qty <= 0`` -> ``NO_ORDER``
        behavior in the orchestrator.
        """
        engine = BasicRiskEngine(config)
        store.update("AAPL", 0, Decimal("100"))
        store.update_mark("AAPL", Decimal("100"))

        def fake_check_order(
            self: BasicRiskEngine,
            order: OrderRequest,
            positions: MemoryPositionStore,
            *,
            additional_exposure: Decimal = Decimal("0"),
        ) -> RiskVerdict:
            if order.symbol == "AAPL" and order.quantity == 2:
                return RiskVerdict(
                    timestamp_ns=order.timestamp_ns,
                    correlation_id=order.correlation_id,
                    sequence=order.sequence,
                    symbol=order.symbol,
                    action=RiskAction.SCALE_DOWN,
                    reason="test_scale_down_to_zero",
                    scaling_factor=0.1,
                )
            return BasicRiskEngine.check_order(self, order, positions)

        with patch.object(BasicRiskEngine, "check_order", fake_check_order):
            result = engine.check_sized_intent(
                _make_sized_intent(targets={"AAPL": 200.0}),
                store,
            )
        assert result.orders == ()
