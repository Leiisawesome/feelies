"""Regression tests for the composition-layer P0 audit fixes (2026-06-20).

Covers:

* **P0-1** — ``factor_neutralization: false`` opt-out is honoured even when a
  global ``factor_loadings_dir`` is configured (the declared opt-out must not
  be silently overridden by platform-level loadings).
* **P0-6** — the ``trend_mechanism.consumes`` family whitelist is enforced at
  runtime so an undeclared mechanism family cannot enter the book.
* **P0-2** — ``decision_basis_hash`` is populated and covers the factor /
  sector / optimizer construction inputs, not just the ranker inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import CompositionEngine
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator

_HORIZON: int = 300
_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")


def _sig(
    symbol: str,
    direction: SignalDirection,
    strength: float,
    edge: float,
    mech: TrendMechanism,
    *,
    strategy_id: str = "src",
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000,
        sequence=1,
        correlation_id=f"sig:{symbol}:{strategy_id}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge,
        layer="SIGNAL",
        horizon_seconds=_HORIZON,
        trend_mechanism=mech,
        expected_half_life_seconds=600,
    )


def _ctx(
    signals: dict[str, Signal | None],
    *,
    universe: tuple[str, ...] = _UNIVERSE,
    by_strategy: dict[str, dict[str, Signal | None]] | None = None,
) -> CrossSectionalContext:
    return CrossSectionalContext(
        timestamp_ns=2_000_000_000,
        sequence=1,
        correlation_id=f"xsect:{_HORIZON}:1",
        source_layer="P4",
        horizon_seconds=_HORIZON,
        boundary_index=1,
        universe=universe,
        signals_by_symbol=signals,
        signals_by_strategy_by_symbol=by_strategy or {},
        completeness=1.0,
    )


def _engine(neutralizer: FactorNeutralizer, *, capital: float = 1_000_000.0) -> CompositionEngine:
    # Generous per-name / gross caps so a 3-name book does not saturate the
    # caps (which would mask weight differences between pipeline variants).
    return CompositionEngine(
        bus=EventBus(),
        intent_sequence_generator=SequenceGenerator(),
        ranker=CrossSectionalRanker(),
        neutralizer=neutralizer,
        sector_matcher=SectorMatcher(sector_map_path=None),
        optimizer=TurnoverOptimizer(
            capital_usd=capital,
            gross_cap_pct=1.0,
            per_name_cap_pct=0.8,
        ),
        completeness_threshold=0.0,
        position_lookup=None,
    )


def _targets(intent: object) -> dict[str, float]:
    return {s: round(tp.target_usd, 2) for s, tp in intent.target_positions.items()}  # type: ignore[attr-defined]


# ── P0-1: factor-neutralization opt-out ─────────────────────────────────


def test_factor_neutralization_opt_out_bypasses_configured_loadings(tmp_path: Path) -> None:
    """``neutralize=False`` must equal the no-op path even WITH loadings set."""
    (tmp_path / "loadings.json").write_text(
        json.dumps({"AAPL": {"MKT": 1.2}, "MSFT": {"MKT": 0.8}, "NVDA": {"MKT": 1.6}}),
        encoding="utf-8",
    )
    sigs: dict[str, Signal | None] = {
        "AAPL": _sig("AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO),
        "MSFT": _sig("MSFT", SignalDirection.LONG, 0.8, 8.0, TrendMechanism.KYLE_INFO),
        "NVDA": _sig("NVDA", SignalDirection.SHORT, 1.2, 9.0, TrendMechanism.KYLE_INFO),
    }
    ctx = _ctx(sigs)

    eng = _engine(FactorNeutralizer(factor_model="MARKET_ONLY", loadings_dir=tmp_path))
    optin = eng.run_default_pipeline(ctx, strategy_id="a", neutralize=True)
    optout = eng.run_default_pipeline(ctx, strategy_id="a", neutralize=False)

    # Reference: a neutralizer with no loadings is a pure passthrough.
    passthrough = _engine(FactorNeutralizer(loadings_dir=None)).run_default_pipeline(
        ctx, strategy_id="a", neutralize=True
    )

    # The opt-out book equals the un-neutralized passthrough book ...
    assert _targets(optout) == _targets(passthrough)
    # ... and is genuinely different from the neutralized book (loadings bite).
    assert _targets(optin) != _targets(optout)
    # Reported exposure: neutralized ≈ 0; opted-out carries the real exposure.
    assert abs(optin.factor_exposures.get("MKT", 0.0)) < 1e-9
    assert abs(optout.factor_exposures.get("MKT", 0.0)) > 1e-6


# ── P0-6: runtime consumes whitelist ────────────────────────────────────


def test_consumes_whitelist_excludes_undeclared_family() -> None:
    ranker = CrossSectionalRanker()
    sigs: dict[str, Signal | None] = {
        "AAPL": _sig("AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO),
        "MSFT": _sig("MSFT", SignalDirection.SHORT, 1.0, 10.0, TrendMechanism.INVENTORY),
        "NVDA": _sig("NVDA", SignalDirection.LONG, 0.8, 9.0, TrendMechanism.KYLE_INFO),
    }
    ctx = _ctx(sigs)

    base = ranker.rank(ctx)
    assert base.raw_scores["MSFT"] != 0.0
    assert TrendMechanism.INVENTORY in base.mechanism_by_symbol.values()

    filtered = ranker.rank(ctx, consumes_mechanisms=(TrendMechanism.KYLE_INFO,))
    # The undeclared INVENTORY symbol is excluded fail-safe.
    assert filtered.raw_scores["MSFT"] == 0.0
    assert filtered.weights["MSFT"] == 0.0
    assert "MSFT" not in filtered.mechanism_by_symbol
    assert TrendMechanism.INVENTORY not in filtered.mechanism_by_symbol.values()
    # The declared family still participates.
    assert any(filtered.weights[s] != 0.0 for s in ("AAPL", "NVDA"))


def test_consumes_whitelist_drops_only_undeclared_feeder_contribution() -> None:
    ranker = CrossSectionalRanker()
    kyle = _sig(
        "AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO, strategy_id="s_kyle"
    )
    inv = _sig(
        "AAPL", SignalDirection.SHORT, 5.0, 50.0, TrendMechanism.INVENTORY, strategy_id="s_inv"
    )
    msft = _sig(
        "MSFT", SignalDirection.LONG, 1.0, 8.0, TrendMechanism.KYLE_INFO, strategy_id="s_kyle"
    )
    by_strategy: dict[str, dict[str, Signal | None]] = {
        "AAPL": {"s_kyle": kyle, "s_inv": inv},
        "MSFT": {"s_kyle": msft, "s_inv": None},
        "NVDA": {"s_kyle": None, "s_inv": None},
    }
    ctx = _ctx({"AAPL": kyle, "MSFT": msft, "NVDA": None}, by_strategy=by_strategy)

    filtered = ranker.rank(
        ctx,
        feeder_strategy_ids=("s_inv", "s_kyle"),
        consumes_mechanisms=(TrendMechanism.KYLE_INFO,),
    )
    # Only the KYLE contribution survives on AAPL (10.0); the INVENTORY feeder
    # (which alone would dominate at -250) is dropped.
    assert filtered.raw_scores["AAPL"] == pytest.approx(10.0)
    assert filtered.mechanism_by_symbol["AAPL"] == TrendMechanism.KYLE_INFO


# ── P0-2: decision_basis_hash coverage ──────────────────────────────────


def test_decision_basis_hash_populated_and_covers_optimizer_params() -> None:
    sigs: dict[str, Signal | None] = {
        "AAPL": _sig("AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO),
        "MSFT": _sig("MSFT", SignalDirection.LONG, 0.8, 8.0, TrendMechanism.KYLE_INFO),
        "NVDA": _sig("NVDA", SignalDirection.SHORT, 1.2, 9.0, TrendMechanism.KYLE_INFO),
    }
    ctx = _ctx(sigs)

    intent = _engine(FactorNeutralizer(loadings_dir=None)).run_default_pipeline(
        ctx, strategy_id="a"
    )
    assert intent.decision_basis_hash != ""

    # Replay determinism: identical inputs → identical hash.
    again = _engine(FactorNeutralizer(loadings_dir=None)).run_default_pipeline(
        ctx, strategy_id="a"
    )
    assert intent.decision_basis_hash == again.decision_basis_hash

    # Optimizer parameters are now covered: differ only in capital → new hash.
    bigger = _engine(
        FactorNeutralizer(loadings_dir=None), capital=2_000_000.0
    ).run_default_pipeline(ctx, strategy_id="a")
    assert bigger.decision_basis_hash != intent.decision_basis_hash


def test_decision_basis_hash_distinguishes_neutralize_flag() -> None:
    """Structurally-identical books with different provenance must differ."""
    sigs: dict[str, Signal | None] = {
        "AAPL": _sig("AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO),
        "MSFT": _sig("MSFT", SignalDirection.SHORT, 1.0, 8.0, TrendMechanism.KYLE_INFO),
        "NVDA": _sig("NVDA", SignalDirection.LONG, 0.9, 9.0, TrendMechanism.KYLE_INFO),
    }
    ctx = _ctx(sigs)
    eng = _engine(FactorNeutralizer(loadings_dir=None))

    on = eng.run_default_pipeline(ctx, strategy_id="a", neutralize=True)
    off = eng.run_default_pipeline(ctx, strategy_id="a", neutralize=False)

    # No loadings → both books are identical (neutralizer is a no-op) ...
    assert _targets(on) == _targets(off)
    # ... but the provenance hash distinguishes the two decisions.
    assert on.decision_basis_hash != off.decision_basis_hash


def test_decision_basis_hash_distinguishes_decay() -> None:
    """Decay on/off changes the ranker inputs → must change the hash."""
    sigs: dict[str, Signal | None] = {
        "AAPL": _sig("AAPL", SignalDirection.LONG, 1.0, 10.0, TrendMechanism.KYLE_INFO),
        "MSFT": _sig("MSFT", SignalDirection.LONG, 0.8, 8.0, TrendMechanism.KYLE_INFO),
        "NVDA": _sig("NVDA", SignalDirection.SHORT, 1.2, 9.0, TrendMechanism.KYLE_INFO),
    }
    ctx = _ctx(sigs)
    eng = _engine(FactorNeutralizer(loadings_dir=None))

    decay_off = eng.run_default_pipeline(ctx, strategy_id="a", decay_weighting_enabled=False)
    decay_on = eng.run_default_pipeline(ctx, strategy_id="a", decay_weighting_enabled=True)
    assert decay_off.decision_basis_hash != decay_on.decision_basis_hash
