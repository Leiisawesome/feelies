"""Level-3 baseline — ``SizedPositionIntent`` replay parity (cvxpy/ECOS path).

Companion to :mod:`tests.determinism.test_sized_intent_replay` (which locks the
closed-form fallback).  Audit P0-3: the cvxpy/ECOS optimizer path was previously
**unverified** — ECOS failed on the closed-form fixture and silently fell back,
so no golden hash ever exercised a successful solve.  This module drives the same
synthetic ``CrossSectionalContext`` sequence through a ``TurnoverOptimizer`` built
with ``require_solver=True`` (audit P0-1: the path is now selected by that flag,
not by ``_HAS_CVXPY``) and locks the resulting intent-stream hash.

Determinism requires:

* cvxpy + ECOS installed (the test is skipped otherwise).
* ECOS invoked with pinned ``abstol/reltol/feastol/max_iters`` (audit P0-2) so the
  solution does not drift across solver builds.
* The weight-space objective (audit P0-1/P1-1) so a successful solve produces a
  real book rather than the empty allocation the old USD-space objective returned.

If this hash drifts, re-baseline in the same commit with justification (ideally
attributing the drift to a deliberate ECOS-version or objective change).
"""

from __future__ import annotations

import pytest

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import CompositionEngine, RegisteredPortfolioAlpha
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.protocol import PortfolioAlpha
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.turnover_optimizer import TurnoverOptimizer, _HAS_CVXPY
from feelies.core.events import SizedPositionIntent
from feelies.core.identifiers import SequenceGenerator
from tests.determinism.test_sized_intent_replay import (
    _HORIZON_SECONDS,
    _NUM_BOUNDARIES,
    _STRATEGY_ID,
    _DefaultPipelineAlpha,
    _hash_intent_stream,
    _make_ctx,
)

pytestmark = pytest.mark.skipif(
    not _HAS_CVXPY,
    reason="cvxpy/ECOS not installed (the [portfolio] extra); solver-path parity is skipped",
)


def _build_solver_engine() -> tuple[EventBus, CompositionEngine, list[SizedPositionIntent]]:
    bus = EventBus()
    captured: list[SizedPositionIntent] = []
    bus.subscribe(SizedPositionIntent, captured.append)  # type: ignore[arg-type]

    engine = CompositionEngine(
        bus=bus,
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(decay_weighting_enabled=False),
        neutralizer=FactorNeutralizer(loadings_dir=None),
        sector_matcher=SectorMatcher(sector_map_path=None),
        optimizer=TurnoverOptimizer(capital_usd=1_000_000.0, require_solver=True),
        completeness_threshold=0.0,
        position_lookup=None,
    )
    alpha: PortfolioAlpha = _DefaultPipelineAlpha(engine)
    engine.register(
        RegisteredPortfolioAlpha(
            alpha_id=_STRATEGY_ID,
            horizon_seconds=_HORIZON_SECONDS,
            alpha=alpha,
            params={},
        )
    )
    engine.attach()
    return bus, engine, captured


def _replay_solver() -> tuple[str, int, int]:
    bus, _engine, captured = _build_solver_engine()
    base_ts = 1_700_000_000_000_000_000
    for k in range(_NUM_BOUNDARIES):
        ts = base_ts + k * _HORIZON_SECONDS * 1_000_000_000
        bus.publish(_make_ctx(boundary_index=k + 1, ts_ns=ts, seq=k + 1))
    non_empty = sum(1 for it in captured if it.target_positions)
    return _hash_intent_stream(captured), len(captured), non_empty


# Locked Level-3 solver-path baseline.  Re-baseline only in a batched
# determinism pass with explicit justification in the commit message.
EXPECTED_LEVEL3_SOLVER_HASH = "7a5d74e7e51e369809f73d3c2ef48c732344de4ac2aa3dc549f9f71d20714fa5"
EXPECTED_LEVEL3_SOLVER_COUNT = 4


def test_solver_intent_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count, _non_empty = _replay_solver()
    assert actual_count == EXPECTED_LEVEL3_SOLVER_COUNT, (
        f"solver intent count drift: expected {EXPECTED_LEVEL3_SOLVER_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_LEVEL3_SOLVER_HASH, (
        "Level-3 SizedPositionIntent (cvxpy/ECOS) hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL3_SOLVER_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (ECOS version / objective change), update the constant in the "
        "same commit and justify."
    )


def test_solver_two_replays_produce_identical_hash() -> None:
    hash_a, count_a, _ = _replay_solver()
    hash_b, count_b, _ = _replay_solver()
    assert count_a == count_b
    assert hash_a == hash_b, (
        f"Level-3 solver hash drift across identical replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_solver_path_produces_non_empty_book() -> None:
    """Guard against regression to the empty-allocation bug (audit P0-1/P1-1).

    The old USD-space objective collapsed every successful solve to ``{}``; the
    weight-space objective must produce a real book on at least one boundary.
    """
    _hash, _count, non_empty = _replay_solver()
    assert non_empty > 0, "cvxpy/ECOS path produced only empty allocations (objective regressed)"
