"""Tests for ``scripts/regime_diagnostics.py`` (audit second-pass R-2).

Locks the empirical claim behind the #123 regression: on a tight, stable
spread the calibrated 3-state engine is *not discriminative* — separation
collapses below the 0.5 floor and the posterior entropy sits near ln(3), so
any ``P(state)``/``entropy`` gate threshold filters noise.  Runs on the
committed synthetic fixture, no external data.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from feelies.services.regime_engine import HMM3StateFractional

_FIXTURE = Path("tests/fixtures/event_logs/synth_5min_aapl.jsonl")


def _load():
    spec = importlib.util.spec_from_file_location(
        "_regime_diag_test",
        Path("scripts/regime_diagnostics.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_regime_diag_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.fixture(scope="module")
def quotes(mod):
    qs = mod._load_quotes_from_jsonl(_FIXTURE)
    assert len(qs) > 1000
    return qs


def test_tight_spread_fixture_is_degenerate(mod, quotes) -> None:
    diag = mod.compute_diagnostics(
        quotes,
        HMM3StateFractional(),
        calibration_max_quotes=len(quotes),
        horizon_seconds=30,
        vol_bound=0.30,
    )
    assert diag.calibrated is True
    # Separation collapses far below the 0.5 weak-discrimination floor.
    assert diag.min_separation < 0.5
    # Posterior is near-uniform: entropy at/above 0.95 on essentially every tick.
    assert diag.entropy_frac_gt_095 > 0.99
    # P(normal) never clears the benign ON floor on this degenerate tape.
    assert diag.p_normal_gt_05_frac == 0.0
    # Therefore every regime gate clause prunes to zero — the signal is noise.
    assert diag.prune_table[0][1] == 0.0


def test_report_renders_and_buckets_present(mod, quotes) -> None:
    diag = mod.compute_diagnostics(
        quotes,
        HMM3StateFractional(),
        calibration_max_quotes=len(quotes),
        horizon_seconds=30,
        vol_bound=0.30,
    )
    report = mod.format_report(diag, label="fixture")
    assert "DEGENERATE" in report  # separation flag fires
    assert "min pairwise separation" in report
    # Forward-return deciles are produced (10 buckets) for both keys.
    assert len(diag.fwd_by_vol_decile) == 10
    assert len(diag.fwd_by_entropy_decile) == 10


def test_variable_spread_recovers_discrimination(mod, quotes) -> None:
    """Control: when spreads disperse, separation and a usable signal return —
    proving the degeneracy is a property of the tape, not a bug."""
    import random
    from decimal import Decimal

    from feelies.core.events import NBBOQuote

    rng = random.Random(0)
    varied = [
        NBBOQuote(
            timestamp_ns=q.timestamp_ns,
            correlation_id=q.correlation_id,
            sequence=q.sequence,
            symbol=q.symbol,
            bid=Decimal("179.99"),
            ask=Decimal("179.99") + Decimal(rng.choice([1, 1, 1, 2, 3, 5])) / Decimal(100),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=q.exchange_timestamp_ns,
        )
        for q in quotes
    ]
    diag = mod.compute_diagnostics(
        varied,
        HMM3StateFractional(),
        calibration_max_quotes=len(varied),
        horizon_seconds=30,
        vol_bound=0.30,
    )
    assert diag.min_separation > 0.5  # discrimination restored
    assert diag.entropy_frac_gt_095 < 0.5  # posteriors now mostly peaked


def _view(mod, *, normal, comp, vb, entropy=0.3):
    return mod._RegimeView(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(comp, normal, vb),
        dominant_name=("compression_clustering", "normal", "vol_breakout")[
            max(range(3), key=lambda i: (comp, normal, vb)[i])
        ],
        posterior_entropy_nats=entropy,
    )


def test_latch_simulation_catches_aggressive_off_condition(mod) -> None:
    """The latch ON-fraction detects off-condition-driven latch collapse that
    the instantaneous prune table misses.

    NOTE: this is a *general* property of the metric, not the APP regression
    mechanism — on APP the regime-isolated latch retained 97% of baseline
    ON-time, so the real cause is regime×sensor coupling, not the regime terms
    alone (audit 2026-06-13 §2.5).  Here, with regime terms constructed to
    differ, a lenient off keeps the latch ON across vol excursions while a
    `P(vol_breakout) > 0.40` off knocks it OFF every other boundary.
    """
    views = []
    for _ in range(50):
        views.append(_view(mod, normal=0.70, comp=0.20, vb=0.10))  # on-eligible
        views.append(_view(mod, normal=0.40, comp=0.15, vb=0.45))  # vol excursion

    on = "P(normal) > 0.5 and P(vol_breakout) < 0.30 and spread_z_30d < 1.5"
    lenient_off = "P(normal) < 0.35 or spread_z_30d > 3.0 or realized_vol_30s_zscore > 4.5"
    aggressive_off = (
        "P(normal) < 0.35 or P(vol_breakout) > 0.40 or entropy > 0.95 "
        "or spread_z_30d > 3.0 or realized_vol_30s_zscore > 4.5"
    )

    base_frac, _ = mod.simulate_latch_on_fraction(views, on, lenient_off)
    cand_frac, _ = mod.simulate_latch_on_fraction(views, on, aggressive_off)

    # Lenient off latches ON and holds through the vol excursions.
    assert base_frac > 0.9
    # Aggressive off is knocked OFF on every vol excursion -> roughly halved.
    assert cand_frac < 0.6
    assert cand_frac < base_frac
