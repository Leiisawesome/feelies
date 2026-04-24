"""Level-3 baseline — ``SizedPositionIntent`` replay parity (decay OFF).

Phase-4-finalize locks a deterministic Level-3 fingerprint of the
``SizedPositionIntent`` stream emitted by the canonical
``CompositionEngine`` default pipeline (Ranker → FactorNeutralizer →
SectorMatcher → TurnoverOptimizer) when driven through a synthetic
``CrossSectionalContext`` event sequence.

Determinism requires:

* The ranker uses ``decay_weighting_enabled=False`` (this file).  See
  :mod:`tests.determinism.test_sized_intent_with_decay_replay` for the
  decay-ON variant.
* Closed-form turnover-optimizer fallback is used (no CVXPY needed in
  CI by design).  ``TurnoverOptimizer.optimize`` rounds to whole-cent
  precision so the intent stream is bit-identical (Inv-5).
* Iteration over ``intent.target_positions`` is lexicographically
  sorted on symbol when serialised for the hash.
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


_UNIVERSE: tuple[str, ...] = ("AAPL", "AMZN", "GOOG", "META", "MSFT")
_HORIZON_SECONDS: int = 300
_STRATEGY_ID: str = "pofi_xsect_v1"
_NUM_BOUNDARIES: int = 4

# Deterministic per-(boundary, symbol) signal book.  Mix LONG/SHORT,
# vary strength + edge so the ranker produces non-degenerate weights at
# every boundary.  ``None`` simulates a stale snapshot for one symbol
# at one boundary so the "hold existing position" branch is exercised.
_DIRECTIONS: tuple[SignalDirection, ...] = (
    SignalDirection.LONG,
    SignalDirection.LONG,
    SignalDirection.SHORT,
    SignalDirection.LONG,
    SignalDirection.SHORT,
)


def _make_signal(
    *,
    symbol: str,
    direction: SignalDirection,
    strength: float,
    edge_bps: float,
    ts_ns: int,
    seq: int,
) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        sequence=seq,
        correlation_id=f"sig:{symbol}:{seq}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id="pofi_kyle_drift_v1",
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_SECONDS,
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=600,
    )


def _make_ctx(*, boundary_index: int, ts_ns: int, seq: int) -> CrossSectionalContext:
    sigs: dict[str, Signal | None] = {}
    for i, symbol in enumerate(_UNIVERSE):
        # Drop one symbol per boundary to exercise the None path.
        if i == (boundary_index % len(_UNIVERSE)):
            sigs[symbol] = None
            continue
        direction = _DIRECTIONS[i]
        strength = 0.5 + 0.1 * ((boundary_index + i) % 5)
        edge_bps = 4.0 + 0.5 * ((boundary_index * 3 + i) % 7)
        # Per-symbol staleness offset (in nanos): older signals on
        # later universe slots so the decay-ON ranker assigns
        # asymmetric weights and the decay-ON / decay-OFF Level-3
        # hashes diverge (guarded by the cross-check in the decay-ON
        # baseline test).  Offsets are deterministic constants.
        staleness_ns = (i + 1) * 60 * 1_000_000_000  # 60s, 120s, ...
        sigs[symbol] = _make_signal(
            symbol=symbol,
            direction=direction,
            strength=strength,
            edge_bps=edge_bps,
            ts_ns=ts_ns - staleness_ns,
            seq=seq * 100 + i,
        )
    completeness = sum(1 for v in sigs.values() if v is not None) / len(_UNIVERSE)
    return CrossSectionalContext(
        timestamp_ns=ts_ns,
        sequence=seq,
        correlation_id=f"xsect:{_HORIZON_SECONDS}:{boundary_index}",
        source_layer="P4",
        horizon_seconds=_HORIZON_SECONDS,
        boundary_index=boundary_index,
        universe=_UNIVERSE,
        signals_by_symbol=sigs,
        completeness=completeness,
    )


class _DefaultPipelineAlpha:
    """Thin wrapper that delegates to ``CompositionEngine.run_default_pipeline``."""

    alpha_id: str = _STRATEGY_ID
    horizon_seconds: int = _HORIZON_SECONDS

    def __init__(self, engine: CompositionEngine) -> None:
        self._engine = engine

    def construct(self, ctx, params):  # type: ignore[override, no-untyped-def]
        return self._engine.run_default_pipeline(
            ctx, strategy_id=self.alpha_id,
        )


def _build_engine(*, decay: bool) -> tuple[EventBus, CompositionEngine, list[SizedPositionIntent]]:
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, captured.append)  # type: ignore[arg-type]

    engine = CompositionEngine(
        bus=bus,
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(decay_weighting_enabled=decay),
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


def _replay(*, decay: bool) -> tuple[str, int]:
    bus, _engine, captured = _build_engine(decay=decay)
    base_ts = 1_700_000_000_000_000_000  # nanos, deterministic constant
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))
    return _hash_intent_stream(captured), len(captured)


def _hash_intent_stream(intents: list[SizedPositionIntent]) -> str:
    lines: list[str] = []
    for it in intents:
        targets = "|".join(
            f"{s}={it.target_positions[s].target_usd:.2f}@{it.target_positions[s].urgency:.2f}"
            for s in sorted(it.target_positions)
        )
        factors = "|".join(
            f"{f}={it.factor_exposures[f]:.6f}"
            for f in sorted(it.factor_exposures)
        )
        mech = "|".join(
            f"{m.name}={it.mechanism_breakdown[m]:.6f}"
            for m in sorted(it.mechanism_breakdown, key=lambda m: m.name)
        )
        lines.append(
            f"{it.sequence}|{it.timestamp_ns}|{it.strategy_id}|"
            f"{it.layer}|{it.horizon_seconds}|{it.correlation_id}|"
            f"GE={it.expected_gross_exposure_usd:.2f}|"
            f"TO={it.expected_turnover_usd:.2f}|"
            f"TGT[{targets}]|FX[{factors}]|MECH[{mech}]"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Determinism (replay twice → same hash) ──────────────────────────────


def test_two_replays_produce_identical_intent_hash() -> None:
    hash_a, count_a = _replay(decay=False)
    hash_b, count_b = _replay(decay=False)
    assert count_a == count_b, (
        f"intent count drift across replays: {count_a} vs {count_b}"
    )
    assert hash_a == hash_b, (
        "Level-3 SizedPositionIntent (decay OFF) hash drift across "
        f"identical replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_intent_count_matches_boundary_count() -> None:
    """Sanity guard: one intent per boundary."""
    _hash, count = _replay(decay=False)
    assert count == _NUM_BOUNDARIES, (
        f"expected exactly {_NUM_BOUNDARIES} intents (one per boundary), "
        f"got {count}"
    )
