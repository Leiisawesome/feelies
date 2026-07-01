"""Gas decision #3 (LAB TEST) — regime-stratified cut of the gas #1/#2
``ofi_kyle_input`` A/B (:mod:`scripts.sensor_feature_ic`).

Hypothesis under test (see ``docs/research/gas_03_dynamic_horizon.md``): a
fixed calendar horizon pools windows with very different information-arrival
rates (compression / normal / vol_breakout regimes), which may explain gas
#1's unstable long-horizon sign and gas #2's cost-gate failure. This module
certifies the plumbing only — the *edge* evidence is an operator-run,
real-data question (see the doc); these tests just confirm the
stratification is causal, correctly bucketed, and additive (no change to
the existing ungrouped A/B).

Scope note: this is offline, read-only harness tooling. Nothing here
touches ``bootstrap``, an alpha YAML, ``HorizonScheduler``, or the live
``RegimeEngine`` wiring — the regime engine instantiated by the harness is
a fresh, throwaway instance used only to bucket already-computed rows.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_H = 5
_NS = 1_000_000_000


def _load_ic_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_sensor_feature_ic_gas3", Path("scripts/sensor_feature_ic.py").resolve()
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _regime_varying_quotes(ic: Any, n: int) -> list[Any]:
    """Synthetic tape with alternating narrow/wide spread (so the default
    ``hmm_3state_fractional`` engine's spread terciles separate) and a
    steady price drift (so forward returns exist and OFI is well-defined)."""
    quotes = []
    for i in range(n):
        wide = (i // 20) % 2 == 1
        half_spread = 0.05 if wide else 0.005
        mid = 100.0 + 1e-3 * i
        quotes.append(
            ic.NBBOQuote(
                timestamp_ns=i * _NS,
                correlation_id=f"q-{i}",
                sequence=i,
                symbol="AAPL",
                bid=Decimal(str(round(mid - half_spread, 5))),
                ask=Decimal(str(round(mid + half_spread, 5))),
                bid_size=10_000 + 30 * i,
                ask_size=10_000,
                exchange_timestamp_ns=i * _NS,
            )
        )
    return quotes


def test_regime_lookup_is_causal_step_series() -> None:
    ic = _load_ic_script()
    lookup = ic._RegimeLookup(ts=[10, 20, 30], dominant=["a", "b", "c"], calibrated=True)
    assert lookup.at(5) is None  # before the first quote — no posterior yet
    assert lookup.at(10) == "a"
    assert lookup.at(15) == "a"
    assert lookup.at(20) == "b"
    assert lookup.at(30) == "c"
    assert lookup.at(1_000) == "c"  # latches the most recent posterior forward


def test_build_regime_lookup_uncalibrated_with_too_few_quotes() -> None:
    # Fewer than HMM3StateFractional's minimum calibration sample count ⇒
    # fails safe to uncalibrated=False (P0-1 pattern), never a fabricated bucket.
    ic = _load_ic_script()
    quotes = _regime_varying_quotes(ic, 10)
    lookup = ic._build_regime_lookup(quotes, "AAPL")
    assert lookup.calibrated is False


def test_ofi_integrated_by_regime_skips_when_uncalibrated() -> None:
    ic = _load_ic_script()
    quotes = _regime_varying_quotes(ic, 10)
    mids = ic._MidSeries.from_events(quotes)
    rows = ic._ofi_integrated_by_regime(quotes, mids, "AAPL", "2026-03-26", frozenset({_H}), 0)
    assert rows == []


def test_ofi_integrated_by_regime_buckets_by_dominant_state() -> None:
    ic = _load_ic_script()
    quotes = _regime_varying_quotes(ic, 200)
    mids = ic._MidSeries.from_events(quotes)
    rows = ic._ofi_integrated_by_regime(quotes, mids, "AAPL", "2026-03-26", frozenset({_H}), 0)
    assert rows, "expected at least one regime-stratified row"
    assert all(r.feature == "ofi_kyle_input" for r in rows)
    assert {r.variant for r in rows} <= {"ofi_ewma_zscore", "ofi_integrated"}
    valid_regimes = {"compression_clustering", "normal", "vol_breakout"}
    assert all(r.regime in valid_regimes for r in rows)
    assert all(r.n > 0 for r in rows)


def test_ofi_integrated_ab_unaffected_by_regime_stratification() -> None:
    """The pooled gas #1/#2 A/B (:func:`_ofi_integrated_ab`) is untouched by
    the gas #3 addition — same feature builder, same rows, no new fields
    populated unexpectedly."""
    ic = _load_ic_script()
    quotes = _regime_varying_quotes(ic, 200)
    mids = ic._MidSeries.from_events(quotes)
    rows = ic._ofi_integrated_ab(quotes, mids, "AAPL", "2026-03-26", frozenset({_H}), 0)
    assert {r.variant for r in rows} == {"ofi_ewma_zscore", "ofi_integrated"}
    assert all(r.regime is None for r in rows)
