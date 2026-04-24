# Decay-ON vs Decay-OFF: Documented Divergence

This note closes the documentation half of acceptance gap **G-F**
(matrix row §20.12.2 #5) by recording *what* changes when the
PORTFOLIO-layer ranker switches its decay-weighting branch on,
holding the input mixed-mechanism fixture identical.

The asserting test —
[`tests/acceptance/test_decay_divergence.py`](../../tests/acceptance/test_decay_divergence.py)
— re-runs the canonical Level-3 `SizedPositionIntent` replay fixture
twice (`decay=False`, `decay=True`) and asserts the two intent-stream
hashes diverge, then cross-checks the snapshot below.

---

## Fixture

Reused from
[`tests/determinism/test_sized_intent_replay.py`](../../tests/determinism/test_sized_intent_replay.py)
(Phase-4-finalize Level-3 baseline) so the two surfaces are pinned
in lockstep:

- Universe: `("AAPL", "AMZN", "GOOG", "META", "MSFT")`
- Boundaries: 4 sequential horizon ticks at `300s` cadence
- Per-boundary signal book: deterministic mix of `LONG` / `SHORT`
  signals from KYLE_INFO + INVENTORY trend mechanisms (the canonical
  "mixed-mechanism" fixture).
- Composition pipeline: `CrossSectionalRanker` →
  `FactorNeutralizer(loadings_dir=None)` (no-op) →
  `SectorMatcher(sector_map_path=None)` (no-op) →
  `TurnoverOptimizer(capital_usd=1_000_000.0)`.
- The only knob that flips between the two runs is
  `CrossSectionalRanker(decay_weighting_enabled=...)`.

---

## What changes

When `decay_weighting_enabled=True`, the ranker multiplies each
signal's raw score by `exp(-Δt / expected_half_life_seconds)` where
`Δt` is the wall-clock age of the signal at the boundary.  In the
fixture, the four boundaries are spaced at exactly the alpha's
horizon, so the older signals are downweighted relative to the
fresher ones.  This propagates through to:

1. **Intent stream hash** — the per-symbol `target_usd` and `urgency`
   change because the optimizer now sees a different cross-sectional
   ranking.  This is the primary signal the asserting test guards
   against the "decay branch is silently a no-op" regression.
2. **Mechanism breakdown** — the per-mechanism share of gross
   exposure (`SizedPositionIntent.mechanism_breakdown`) changes
   because the relative contribution of each family to the portfolio
   shifts when its older signals are downweighted.
3. **Expected turnover** — the ranker's choice of which symbols are
   in the top/bottom buckets at each boundary differs, which
   propagates to the optimizer's turnover budget.

What does **not** change:

- The total number of intents (one per boundary, four total).
- The set of symbols in the universe (the ranker is purely
  re-weighting, not gating).
- Any factor exposures (the FactorNeutralizer is a no-op in this
  fixture; structural neutralization is exercised separately by
  `test_reference_alpha_load_invariants.py::test_portfolio_factor_exposure_within_tolerance`).

---

## Snapshot

Recorded once during the Acceptance Sweep authoring pass.  The
asserting test cross-checks against this JSON snapshot below; if a
future PR moves these numbers, the test fails loudly and the snapshot
must be re-recorded in the *same commit* with a written justification
explaining why the change is intentional (e.g. the decay formula
itself was tuned, or the fixture's half-life parameter changed).

```json
{
  "fixture_id": "level3_mixed_mechanism_v1",
  "boundary_count": 4,
  "decay_off": {
    "intent_count": 4,
    "hash_kind": "sha256(intent_stream_serialised)"
  },
  "decay_on": {
    "intent_count": 4,
    "hash_kind": "sha256(intent_stream_serialised)"
  },
  "invariants": {
    "decay_on_hash_neq_decay_off_hash": true,
    "intent_count_equal_across_branches": true,
    "intent_count_equal_to_boundary_count": true
  }
}
```

The two specific hash values are not pinned in this note (they are
already the subject of the locked Level-3 baselines in the
determinism suite — `test_sized_intent_replay.py` for OFF and
`test_sized_intent_with_decay_replay.py` for ON).  Pinning them here
*as well* would be redundant and create three places to update on
every legitimate baseline bump.  The acceptance test instead asserts
the *invariants* listed in the JSON above — which is the property
§20.12.2 #5 actually demands.

---

## Why this is necessary even though the determinism suite exists

The decay determinism suite asserts that **each** branch is
deterministic and that the two branches have **distinct** hashes
(`tests/determinism/test_sized_intent_with_decay_replay.py
::test_decay_changes_hash_vs_baseline`).  What it does *not* assert
is the structural property the matrix row demands — namely that this
distinctness holds *on a mixed-mechanism portfolio fixture* (rather
than, e.g., a single-mechanism degenerate case where decay weighting
collapses to a no-op).  This acceptance pair (test + note) anchors
that property in one auditable place.
