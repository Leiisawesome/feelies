"""Tests for :class:`feelies.composition.engine.CompositionEngine`."""

from __future__ import annotations

from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import (
    CompositionEngine,
    RegisteredPortfolioAlpha,
)
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.protocol import (
    CompositionContextError,
    PortfolioAlpha,
)
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.core.identifiers import SequenceGenerator


def _make_signal(symbol: str) -> Signal:
    return Signal(
        timestamp_ns=1_000,
        sequence=0,
        correlation_id=f"sig:{symbol}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id="alpha_a",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
        horizon_seconds=300,
    )


def _make_ctx(*, completeness: float = 1.0) -> CrossSectionalContext:
    universe = ("AAPL", "MSFT")
    sigs: dict[str, Signal | None] = {
        s: (_make_signal(s) if completeness > 0 else None) for s in universe
    }
    return CrossSectionalContext(
        timestamp_ns=2_000,
        sequence=0,
        correlation_id="ctx:1",
        source_layer="P4",
        horizon_seconds=300,
        boundary_index=1,
        universe=universe,
        signals_by_symbol=sigs,
        completeness=completeness,
    )


def _build_engine(
    bus: EventBus, *, completeness_threshold: float = 0.0
) -> CompositionEngine:
    return CompositionEngine(
        bus=bus,
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(),
        neutralizer=FactorNeutralizer(loadings_dir=None),
        sector_matcher=SectorMatcher(sector_map_path=None),
        optimizer=TurnoverOptimizer(capital_usd=1_000_000),
        completeness_threshold=completeness_threshold,
    )


class _NoopAlpha:
    alpha_id = "noop"
    horizon_seconds = 300

    def construct(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        return SizedPositionIntent(
            timestamp_ns=ctx.timestamp_ns,
            sequence=0,
            correlation_id="x",
            source_layer="PORTFOLIO",
            strategy_id=self.alpha_id,
            layer="PORTFOLIO",
            horizon_seconds=ctx.horizon_seconds,
            target_positions={"AAPL": TargetPosition(symbol="AAPL", target_usd=1000.0)},
        )


def test_dispatch_publishes_one_intent_per_alpha():
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, lambda e: captured.append(e))

    engine = _build_engine(bus)
    engine.register(RegisteredPortfolioAlpha(
        alpha_id="noop",
        horizon_seconds=300,
        alpha=_NoopAlpha(),
        params={},
    ))
    engine.attach()
    bus.publish(_make_ctx())
    assert len(captured) == 1
    intent = captured[0]
    assert intent.strategy_id == "noop"
    assert intent.layer == "PORTFOLIO"
    assert intent.horizon_seconds == 300
    assert "AAPL" in intent.target_positions


def test_low_completeness_emits_degenerate_intent():
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, lambda e: captured.append(e))

    engine = _build_engine(bus, completeness_threshold=0.99)
    engine.register(RegisteredPortfolioAlpha(
        alpha_id="noop", horizon_seconds=300, alpha=_NoopAlpha(), params={},
    ))
    engine.attach()
    bus.publish(_make_ctx(completeness=0.5))
    assert len(captured) == 1
    assert captured[0].target_positions == {}


def test_alpha_exception_emits_degenerate_intent():
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, lambda e: captured.append(e))

    class _RaisingAlpha:
        alpha_id = "raises"
        horizon_seconds = 300

        def construct(self, ctx, params):
            raise CompositionContextError("solver infeasible")

    engine = _build_engine(bus)
    engine.register(RegisteredPortfolioAlpha(
        alpha_id="raises",
        horizon_seconds=300,
        alpha=_RaisingAlpha(),
        params={},
    ))
    engine.attach()
    bus.publish(_make_ctx())
    assert len(captured) == 1
    assert captured[0].target_positions == {}


def test_attach_is_noop_when_empty():
    bus = EventBus()
    engine = _build_engine(bus)
    engine.attach()
    bus.publish(_make_ctx())
