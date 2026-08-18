"""X5 — failed position lookup must fail closed.

G20: ``except Exception: current_positions[s] = 0.0`` reports a failed
read as flat, so the optimizer sizes a fresh entry on top of a book it
could not see.  A lookup that raises is an unknown state (Inv-11):
construction must halt for that boundary, emit, and produce no target.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import CompositionEngine, RegisteredPortfolioAlpha
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator

_STRATEGY_ID = "x5_portfolio"
_HORIZON_SECONDS = 300
_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")


class _InjectedLookupFailure:
    """Raises ``KeyError`` on every call and records that it did.

    The record is the anti-vacuity: the handler at
    ``composition/engine.py`` (the ``try`` around ``_position_lookup``)
    is ``# pragma: no cover``, so a passing assertion that never entered
    it proves nothing.  ``calls`` / ``raised`` are how this test knows
    the injected failure reached that handler.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.raised: list[KeyError] = []

    def __call__(self, strategy_id: str, symbol: str) -> float:
        self.calls.append((strategy_id, symbol))
        exc = KeyError(f"injected lookup failure for {strategy_id}/{symbol}")
        self.raised.append(exc)
        raise exc


class _DefaultPipelineAlpha:
    alpha_id = _STRATEGY_ID
    horizon_seconds = _HORIZON_SECONDS

    def __init__(self, engine: CompositionEngine) -> None:
        self._engine = engine

    def construct(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        return self._engine.run_default_pipeline(ctx, strategy_id=self.alpha_id)


def _make_signal(symbol: str, *, direction: SignalDirection, strength: float) -> Signal:
    return Signal(
        timestamp_ns=1_000,
        sequence=0,
        correlation_id=f"sig:{symbol}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id="feeder",
        direction=direction,
        strength=strength,
        edge_estimate_bps=10.0,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_SECONDS,
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    )


def _make_ctx() -> CrossSectionalContext:
    # Asymmetric long/short book: identical LONG strengths z-score to zero
    # and the silent-flat path then produces no target, which would XPASS
    # this test before G20 is closed.
    sigs: dict[str, Signal | None] = {
        "AAPL": _make_signal("AAPL", direction=SignalDirection.LONG, strength=1.0),
        "MSFT": _make_signal("MSFT", direction=SignalDirection.LONG, strength=0.5),
        "NVDA": _make_signal("NVDA", direction=SignalDirection.SHORT, strength=1.2),
    }
    return CrossSectionalContext(
        timestamp_ns=2_000,
        sequence=0,
        correlation_id="ctx:1",
        source_layer="P4",
        horizon_seconds=_HORIZON_SECONDS,
        boundary_index=1,
        universe=_UNIVERSE,
        signals_by_symbol=sigs,
        completeness=1.0,
    )


def _build_engine(*, lookup: Any) -> tuple[EventBus, CompositionEngine, list[SizedPositionIntent]]:
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, captured.append)
    engine = CompositionEngine(
        bus=bus,
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(),
        neutralizer=FactorNeutralizer(loadings_dir=None),
        sector_matcher=SectorMatcher(sector_map_path=None),
        optimizer=TurnoverOptimizer(capital_usd=1_000_000.0),
        completeness_threshold=0.0,
        position_lookup=lookup,
    )
    engine.register(
        RegisteredPortfolioAlpha(
            alpha_id=_STRATEGY_ID,
            horizon_seconds=_HORIZON_SECONDS,
            alpha=_DefaultPipelineAlpha(engine),
            params={},
        )
    )
    engine.attach()
    return bus, engine, captured


def test_failed_position_lookup_halts_emits_and_produces_no_target() -> None:
    control_bus, _control_engine, control_captured = _build_engine(lookup=None)
    control_bus.publish(_make_ctx())
    assert any(intent.target_positions for intent in control_captured), (
        "control book (no lookup wired) produced no target — this fixture "
        "cannot distinguish G20's silent-flat path from a pipeline that "
        "never sizes"
    )

    lookup = _InjectedLookupFailure()
    bus, _engine, captured = _build_engine(lookup=lookup)
    bus.publish(_make_ctx())

    assert lookup.calls, (
        "position_lookup was never invoked — the injected KeyError never "
        "reached composition/engine.py:384-389, so this assertion would not "
        "be testing G20"
    )
    assert lookup.raised, (
        "position_lookup was invoked but did not raise — the handler's "
        "except clause was not entered"
    )
    assert captured, (
        "construction halted with no emission — a failed lookup must emit "
        "a barrier/completeness notification for the abandoned boundary"
    )
    with_targets = [intent for intent in captured if intent.target_positions]
    assert not with_targets, (
        "failed position lookup produced a target (G20 silent-flat): "
        f"{[(i.strategy_id, {s: tp.target_usd for s, tp in i.target_positions.items()}) for i in with_targets]}"
    )
