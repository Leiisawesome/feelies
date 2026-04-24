"""Mixed-mechanism universe — Phase 4.1 ranker breakdown integration test.

Drives :class:`feelies.composition.engine.CompositionEngine` with
hand-crafted ``CrossSectionalContext`` events whose signals span three
distinct ``TrendMechanism`` families (KYLE_INFO, INVENTORY,
HAWKES_SELF_EXCITE), then asserts:

* the resulting ``SizedPositionIntent`` carries a non-empty
  ``mechanism_breakdown`` dict;
* every reported family share is ≤ the engine's configured per-family
  cap (Phase 4.1 §20.4);
* two replays of the same fixture produce a bit-identical intent
  stream (Inv-5 — mechanism-cap arithmetic must be deterministic).

This is intentionally narrower than ``test_phase4_e2e.py``: we
exercise the *mechanism-aware path* of the ranker without taking on
the per-symbol sensor wiring overhead of three real SIGNAL alphas.
The reference YAML ``alphas/pofi_xsect_mixed_mechanism_v1`` documents
the consumes-block layout this test pins down at the engine level.
"""

from __future__ import annotations

import hashlib

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import (
    CompositionEngine,
    RegisteredPortfolioAlpha,
)
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.protocol import PortfolioAlpha
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


_HORIZON_SECONDS: int = 300
_STRATEGY_ID: str = "pofi_xsect_mixed_mechanism_v1"
_MECHANISM_CAP: float = 0.4

# 9-symbol universe, 3 symbols per mechanism family.
_UNIVERSE: tuple[str, ...] = (
    "AAPL", "AMZN", "BAC",   # KYLE_INFO
    "CVX", "GOOG", "JPM",    # INVENTORY
    "META", "MSFT", "NVDA",  # HAWKES_SELF_EXCITE
)
_MECHANISM_BY_SYMBOL: dict[str, TrendMechanism] = {
    "AAPL": TrendMechanism.KYLE_INFO,
    "AMZN": TrendMechanism.KYLE_INFO,
    "BAC":  TrendMechanism.KYLE_INFO,
    "CVX":  TrendMechanism.INVENTORY,
    "GOOG": TrendMechanism.INVENTORY,
    "JPM":  TrendMechanism.INVENTORY,
    "META": TrendMechanism.HAWKES_SELF_EXCITE,
    "MSFT": TrendMechanism.HAWKES_SELF_EXCITE,
    "NVDA": TrendMechanism.HAWKES_SELF_EXCITE,
}
_NUM_BOUNDARIES: int = 3


def _make_signal(
    *, symbol: str, mechanism: TrendMechanism, ts_ns: int, seq: int,
    boundary_index: int,
) -> Signal:
    # Deterministic per-(boundary, symbol) variation so the cross-
    # sectional standardization produces non-zero spread *within*
    # each mechanism bucket (a uniform book would collapse to zero
    # weights and trivially satisfy the cap).
    direction = (
        SignalDirection.LONG
        if (boundary_index + ord(symbol[0])) % 2 == 0
        else SignalDirection.SHORT
    )
    strength = 0.5 + 0.1 * ((boundary_index + ord(symbol[0])) % 5)
    edge = 5.0 + 0.5 * ((boundary_index * 3 + ord(symbol[0])) % 7)
    return Signal(
        timestamp_ns=ts_ns,
        sequence=seq,
        correlation_id=f"sig:{symbol}:{seq}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=f"src_{mechanism.name.lower()}",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_SECONDS,
        trend_mechanism=mechanism,
        expected_half_life_seconds=600,
    )


def _make_ctx(*, boundary_index: int, ts_ns: int, seq: int) -> CrossSectionalContext:
    sigs: dict[str, Signal | None] = {}
    for i, symbol in enumerate(_UNIVERSE):
        sigs[symbol] = _make_signal(
            symbol=symbol,
            mechanism=_MECHANISM_BY_SYMBOL[symbol],
            ts_ns=ts_ns - 1_000_000,
            seq=seq * 100 + i,
            boundary_index=boundary_index,
        )
    return CrossSectionalContext(
        timestamp_ns=ts_ns,
        sequence=seq,
        correlation_id=f"xsect:{_HORIZON_SECONDS}:{boundary_index}",
        source_layer="P4",
        horizon_seconds=_HORIZON_SECONDS,
        boundary_index=boundary_index,
        universe=_UNIVERSE,
        signals_by_symbol=sigs,
        completeness=1.0,
    )


class _DefaultPipelineAlpha:
    alpha_id: str = _STRATEGY_ID
    horizon_seconds: int = _HORIZON_SECONDS

    def __init__(self, engine: CompositionEngine) -> None:
        self._engine = engine

    def construct(self, ctx, params):  # type: ignore[override, no-untyped-def]
        return self._engine.run_default_pipeline(
            ctx, strategy_id=self.alpha_id,
        )


def _build_engine() -> tuple[EventBus, CompositionEngine, list[SizedPositionIntent]]:
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, captured.append)  # type: ignore[arg-type]

    engine = CompositionEngine(
        bus=bus,
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(
            mechanism_max_share_of_gross=_MECHANISM_CAP,
        ),
        neutralizer=FactorNeutralizer(loadings_dir=None),
        sector_matcher=SectorMatcher(sector_map_path=None),
        optimizer=TurnoverOptimizer(capital_usd=1_000_000.0),
        completeness_threshold=0.0,
        position_lookup=None,
    )
    alpha: PortfolioAlpha = _DefaultPipelineAlpha(engine)
    engine.register(RegisteredPortfolioAlpha(
        alpha_id=_STRATEGY_ID,
        horizon_seconds=_HORIZON_SECONDS,
        alpha=alpha,
        params={},
    ))
    engine.attach()
    return bus, engine, captured


def _replay() -> list[SizedPositionIntent]:
    bus, _engine, captured = _build_engine()
    base_ts = 1_700_000_000_000_000_000
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))
    return captured


def _hash_intents(intents: list[SizedPositionIntent]) -> str:
    lines: list[str] = []
    for it in intents:
        targets = "|".join(
            f"{s}={it.target_positions[s].target_usd:.2f}"
            for s in sorted(it.target_positions)
        )
        mech = "|".join(
            f"{m.name}={it.mechanism_breakdown[m]:.6f}"
            for m in sorted(it.mechanism_breakdown, key=lambda m: m.name)
        )
        lines.append(
            f"{it.sequence}|{it.timestamp_ns}|{it.strategy_id}|"
            f"{it.correlation_id}|TGT[{targets}]|MECH[{mech}]"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Mechanism breakdown is reported and bounded ─────────────────────────


def test_mixed_mechanism_intent_carries_non_empty_breakdown() -> None:
    intents = _replay()
    assert intents, "expected at least one SizedPositionIntent"
    for it in intents:
        if not it.target_positions:
            # Degenerate intents (empty targets) carry no breakdown.
            continue
        assert it.mechanism_breakdown, (
            f"intent for boundary {it.correlation_id} has empty "
            "mechanism_breakdown despite non-degenerate targets"
        )
        # Every reported family share ≤ the configured per-family cap.
        for mech, share in it.mechanism_breakdown.items():
            assert share <= _MECHANISM_CAP + 1e-9, (
                f"mechanism {mech.name} share {share:.6f} exceeds "
                f"cap {_MECHANISM_CAP}"
            )


def test_mixed_mechanism_breakdown_covers_all_three_families() -> None:
    """Across the boundary stream, all three families appear at least once."""
    intents = _replay()
    seen_families: set[TrendMechanism] = set()
    for it in intents:
        seen_families.update(it.mechanism_breakdown.keys())
    assert TrendMechanism.KYLE_INFO in seen_families
    assert TrendMechanism.INVENTORY in seen_families
    assert TrendMechanism.HAWKES_SELF_EXCITE in seen_families


# ── Determinism ─────────────────────────────────────────────────────────


def test_mixed_mechanism_replay_byte_identical() -> None:
    intents_a = _replay()
    intents_b = _replay()
    assert len(intents_a) == len(intents_b)
    assert _hash_intents(intents_a) == _hash_intents(intents_b), (
        "Mixed-mechanism SizedPositionIntent hash drift across "
        "identical replays"
    )
