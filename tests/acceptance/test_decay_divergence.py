"""Acceptance — decay-ON vs decay-OFF divergence on a mixed-mechanism fixture.

Closes acceptance gap **G-F** (matrix row §20.12.2 #5).  Asserts
that toggling :class:`CrossSectionalRanker.decay_weighting_enabled`
on a deterministic mixed-mechanism PORTFOLIO fixture produces:

* a different ``SizedPositionIntent`` stream hash, and
* the structural invariants documented in
  :doc:`/docs/acceptance/decay_divergence_note` (intent count
  preserved, universe preserved).

The companion note ``docs/acceptance/decay_divergence_note.md``
describes *what* changes between the two branches and *why* this
test exists alongside the existing Level-3 determinism baselines.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

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


# ── Mixed-mechanism fixture ─────────────────────────────────────────────

# Five symbols, each pinned to a *different* trend mechanism so the
# fixture genuinely exercises the cross-mechanism branch (the existing
# determinism baseline pins everything to KYLE_INFO and so cannot
# satisfy the §20.12.2 #5 "mixed-mechanism" wording on its own).
_UNIVERSE: tuple[str, ...] = ("AAPL", "AMZN", "GOOG", "META", "MSFT")
_HORIZON_SECONDS: int = 300
_STRATEGY_ID: str = "pofi_decay_divergence_acceptance_v1"
_NUM_BOUNDARIES: int = 4

_MECHANISMS: tuple[TrendMechanism, ...] = (
    TrendMechanism.KYLE_INFO,
    TrendMechanism.INVENTORY,
    TrendMechanism.HAWKES_SELF_EXCITE,
    TrendMechanism.SCHEDULED_FLOW,
    TrendMechanism.KYLE_INFO,
)

_DIRECTIONS: tuple[SignalDirection, ...] = (
    SignalDirection.LONG,
    SignalDirection.SHORT,
    SignalDirection.LONG,
    SignalDirection.SHORT,
    SignalDirection.LONG,
)

# Per-symbol expected half-life so the decay multiplier varies
# meaningfully across the cross-section (decay = exp(-Δt / hl)).
# IMPORTANT: half-lives must NOT be proportional to per-symbol
# staleness (which is i*60s); otherwise every symbol's decay factor
# collapses to the same constant and the standardizer's z-score
# divides it out, hiding the decay branch behind an apparent no-op.
# These values are deliberately non-proportional to staleness.
_HALF_LIVES: tuple[int, ...] = (240, 1800, 360, 1200, 480)


def _make_signal(
    *,
    symbol: str,
    direction: SignalDirection,
    strength: float,
    edge_bps: float,
    ts_ns: int,
    seq: int,
    mechanism: TrendMechanism,
    half_life_seconds: int,
) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        sequence=seq,
        correlation_id=f"sig:{symbol}:{seq}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=_STRATEGY_ID,
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_SECONDS,
        trend_mechanism=mechanism,
        expected_half_life_seconds=half_life_seconds,
    )


def _make_ctx(
    *, boundary_index: int, ts_ns: int, seq: int,
) -> CrossSectionalContext:
    sigs: dict[str, Signal | None] = {}
    for i, symbol in enumerate(_UNIVERSE):
        direction = _DIRECTIONS[i]
        strength = 0.5 + 0.1 * ((boundary_index + i) % 5)
        edge_bps = 4.0 + 0.5 * ((boundary_index * 3 + i) % 7)
        # Stagger per-symbol staleness so older signals sit on later
        # universe slots: this is exactly the pattern that decay-ON
        # ranking is designed to penalise relative to decay-OFF.
        staleness_ns = (i + 1) * 60 * 1_000_000_000
        sigs[symbol] = _make_signal(
            symbol=symbol,
            direction=direction,
            strength=strength,
            edge_bps=edge_bps,
            ts_ns=ts_ns - staleness_ns,
            seq=seq * 100 + i,
            mechanism=_MECHANISMS[i],
            half_life_seconds=_HALF_LIVES[i],
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
    alpha_id: str = _STRATEGY_ID
    horizon_seconds: int = _HORIZON_SECONDS

    def __init__(self, engine: CompositionEngine) -> None:
        self._engine = engine

    def construct(self, ctx, params):  # type: ignore[no-untyped-def]
        return self._engine.run_default_pipeline(
            ctx, strategy_id=self.alpha_id,
        )


def _build(*, decay: bool) -> tuple[EventBus, list[SizedPositionIntent]]:
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
    return bus, captured


def _replay(*, decay: bool) -> tuple[str, list[SizedPositionIntent]]:
    bus, captured = _build(decay=decay)
    base_ts = 1_700_000_000_000_000_000
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))
    return _hash_intents(captured), captured


def _hash_intents(intents: list[SizedPositionIntent]) -> str:
    lines: list[str] = []
    for it in intents:
        targets = "|".join(
            f"{s}={it.target_positions[s].target_usd:.2f}@"
            f"{it.target_positions[s].urgency:.2f}"
            for s in sorted(it.target_positions)
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
            f"TGT[{targets}]|MECH[{mech}]"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Asserting tests ─────────────────────────────────────────────────────


def test_decay_on_and_off_produce_distinct_intent_hashes() -> None:
    """Primary G-F invariant — decay-ON ≠ decay-OFF on mixed mechanisms."""
    hash_off, _ = _replay(decay=False)
    hash_on, _ = _replay(decay=True)
    assert hash_off != hash_on, (
        "decay-ON and decay-OFF replays produced identical hashes on "
        "the mixed-mechanism PORTFOLIO fixture — decay weighting may "
        "be silently disabled or collapsing to a no-op for this fixture"
    )


def test_each_branch_is_internally_deterministic() -> None:
    """Sub-invariant — each branch must hash to itself bit-identically."""
    hash_off_a, _ = _replay(decay=False)
    hash_off_b, _ = _replay(decay=False)
    assert hash_off_a == hash_off_b, (
        f"decay-OFF replay drift on mixed-mechanism fixture: "
        f"{hash_off_a} vs {hash_off_b}"
    )
    hash_on_a, _ = _replay(decay=True)
    hash_on_b, _ = _replay(decay=True)
    assert hash_on_a == hash_on_b, (
        f"decay-ON replay drift on mixed-mechanism fixture: "
        f"{hash_on_a} vs {hash_on_b}"
    )


def test_intent_count_preserved_across_branches() -> None:
    """Toggling decay must not gain or drop intents (only re-weight)."""
    _, intents_off = _replay(decay=False)
    _, intents_on = _replay(decay=True)
    assert len(intents_off) == _NUM_BOUNDARIES
    assert len(intents_on) == _NUM_BOUNDARIES
    assert len(intents_off) == len(intents_on)


def test_universe_preserved_across_branches() -> None:
    """Decay re-weights ranks but never gates symbols out of the universe."""
    _, intents_off = _replay(decay=False)
    _, intents_on = _replay(decay=True)
    for intent_off, intent_on in zip(intents_off, intents_on):
        assert set(intent_off.target_positions) == set(intent_on.target_positions), (
            "decay toggle changed the per-boundary symbol set — ranker "
            "is gating, not re-weighting"
        )


def test_decay_divergence_note_present() -> None:
    """Companion documentation must exist (matrix row §20.12.2 #5)."""
    note = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "acceptance"
        / "decay_divergence_note.md"
    )
    assert note.is_file(), (
        f"missing companion note: {note} — required by acceptance gap G-F"
    )
    text = note.read_text(encoding="utf-8")
    for required_token in (
        "decay_weighting_enabled",
        "mixed-mechanism",
        "G-F",
    ):
        assert required_token in text, (
            f"decay_divergence_note.md missing required token "
            f"{required_token!r}"
        )
