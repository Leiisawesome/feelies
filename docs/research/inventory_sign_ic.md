# P2-1 — Inventory sign confirmation (forward-return IC)

**Status (2026-06-15): run on real NBBO → `sig_inventory_revert_v1`
QUARANTINED.** Across 6 sessions / 3 symbols (AAPL 2026-03-20/23/26, APP
2026-06-01/05, AGNC 2026-04-21) the pooled Spearman IC of
`quote_replenish_asymmetry_zscore` vs the forward 30 s micro-price return is
indistinguishable from zero (pooled ρ ≈ −0.007; per-day sign unstable; no
session significant at p < 0.05). Conditional forward returns are ~0.1–1.4
bps — far below the disclosed 8.8 bps edge and ~11 bps round-trip cost — and
the SHORT leg (very negative `asym_z`) shows *positive* forward returns in
5/6 sessions, contradicting the fade premise. The alpha is marked
`lifecycle_state: RESEARCH` (blocks PAPER/LIVE) pending a regime-gated,
by-leg, multi-day re-study. See
`docs/audits/signal_alpha_audit_2026-06-14.md` §10.

The repo's synthetic fixture (`tests/fixtures/event_logs/synth_5min_aapl.jsonl`,
a seeded random walk) is a *mechanical smoke only* (ρ ≈ 0), never a
confirmation — use cached real NBBO via the disk cache.

## Objective

`sig_inventory_revert_v1` fades quote-replenishment asymmetry with the
convention **`LONG` when `quote_replenish_asymmetry_zscore > 0`**
(`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:209-215`).
The alpha's own comment flags this sign as *empirical and unconfirmed*.
This study measures the Spearman rank IC of `quote_replenish_asymmetry_zscore`
at each 30 s horizon boundary against the **forward 30 s micro-price
return**, to confirm, flip, or kill the convention.

Sensor sign convention (ground truth):
`sensors/impl/quote_replenish_asymmetry.py:26` — positive ⇒ **bid**
replenishes faster.

## Decision gate

| Measured | Action |
|---|---|
| ρ > 0 and p < 0.05 | Keep the `LONG`-on-positive convention; pin ρ in the YAML falsification baseline. |
| ρ < 0 and p < 0.05 | **Flip** the sign branch (`LONG if asym_z < 0`); re-baseline; re-lock per-alpha test. |
| \|ρ\| < 0.02 or p ≥ 0.05 | Mechanism is noise at this horizon → mark `sig_inventory_revert_v1` for decommission / re-research. |

Run per symbol (AAPL/MSFT/NVDA) and pooled; also inspect the bucketed
profile (monotone mean-forward-return across `asym_z` deciles is the
signature of a real conditional edge).

## Measurement core (shipped)

`src/feelies/research/forward_ic.py` (pure-Python, stdlib only, unit-tested
in `tests/research/test_forward_ic.py`):

- `spearman_ic(feature, forward_return) -> ICResult(rho, n, p_value)` —
  rank IC with average-tie ranks and a Fisher-z normal-approx p-value.
- `bucketed_forward_return(feature, forward_return, n_buckets=5)` —
  equal-count conditional-forward-return profile.
- `forward_return_at(times_ns, mids, anchor_ns, horizon_seconds)` —
  forward return from the mid at/before an anchor to the mid at/after
  `anchor + horizon` (NaN near the series end).

## Procedure (when real NBBO is available)

1. **Load events.** Real cached NBBO comes from the disk cache:
   `feelies.storage.cache_replay.load_event_log_from_disk_cache(...)`
   (canonical codec; `feelies.storage.disk_event_cache.DiskEventCache`).
   Do **not** reuse the synthetic-fixture loader for real data — they use
   different JSON encodings (`kind` vs `__type__`).

2. **Replay to materialise the feature.** Reuse the wiring pattern in
   `tests/determinism/test_signal_replay.py:109-168`:
   - `SensorRegistry` with a `quote_replenish_asymmetry` `SensorSpec`
     (`sensor_version="1.1.0"`).
   - `HorizonScheduler(horizons={30}, session_open_ns=...)`.
   - `HorizonAggregator(horizon_features=[RollingZscoreFeature(
     "quote_replenish_asymmetry", 30,
     feature_id="quote_replenish_asymmetry_zscore")])`.
   - Subscribe to `HorizonFeatureSnapshot`; for each, when
     `snapshot.warm["quote_replenish_asymmetry_zscore"]`, record
     `(snapshot.timestamp_ns, snapshot.values["quote_replenish_asymmetry_zscore"])`.
   - In parallel, build the mid series `(timestamp_ns, (bid+ask)/2)` from
     the `NBBOQuote` stream.

3. **Join + compute.**
   ```python
   from feelies.research.forward_ic import (
       spearman_ic, bucketed_forward_return, forward_return_at,
   )
   fwd = [forward_return_at(times, mids, ts, 30.0) for ts, _ in boundaries]
   feat = [z for _, z in boundaries]
   print(spearman_ic(feat, fwd))
   for b in bucketed_forward_return(feat, fwd, n_buckets=5):
       print(b)
   ```

4. **Apply the decision gate** above.

## Runner (`scripts/research/inventory_sign_ic.py`)

The script wires steps 1–4 over the disk cache. Single day or pooled range,
with a per-leg edge at the entry threshold (the decision-relevant numbers):

```bash
# single session
python scripts/research/inventory_sign_ic.py --symbol AAPL --date 2026-03-26
# pooled range, entry threshold 2.0 (the alpha's |asym_z| floor)
python scripts/research/inventory_sign_ic.py --symbol AAPL \
    --start 2026-03-16 --end 2026-03-27 --threshold 2.0
```

It prints the pooled Spearman IC, the bucketed profile (in bps), and the
**per-leg fade edge** — `LONG (asym_z > +thr)` wants positive forward
return, `SHORT (asym_z < -thr)` wants negative — each with an indicative
t-stat (which ignores intra-session autocorrelation, so read it loosely).
Missing days in a range are skipped with a warning.

### `--regime-gated` (the decision-grade run)

```bash
python scripts/research/inventory_sign_ic.py --symbol AAPL \
    --start 2026-03-16 --end 2026-03-27 --regime-gated
```

This conditions on the alpha's **actual regime gate**: it builds the real
`RegimeEngine` (`hmm_3state_fractional`), the alpha's `RegimeGate` DSL (from
the YAML), and the extra sensors the gate reads (`spread_z_30d`,
`realized_vol_30s_zscore`, `quote_hazard_rate`), then evaluates the gate at
each boundary exactly as `HorizonSignalEngine` does (same `_build_bindings`
+ `RegimeState`, snapshot-values-priority with a sensor-cache fallback) and
pools **only the boundaries the gate turns ON**. The hysteresis latch is
reset per session. This is the faithful "what the alpha actually trades"
test.

Fidelity caveats (call them out when reporting):

* **HMM calibration** is per-session — the engine is calibrated on *that
  day's* spread distribution (no cross-day seeding), so the `P(normal)` /
  `P(vol_breakout)` posteriors approximate, not reproduce, a production run
  warm-started from history.
* `spread_z_30d` is a **count**-window sensor (warms after ~6000 quotes),
  so the first few minutes of each session are gate-cold; on a full RTH day
  this is negligible.
* On any missing gate binding the harness fails the gate **OFF**
  (conservative), mirroring the engine — so the gated boundary count is a
  lower bound.

## Notes

- `min_samples=30` on `RollingZscoreFeature`: the first ~30 boundaries are
  cold (`warm=False`) and must be skipped.
- Use event-time horizons only; never wall-clock (Inv-6 / determinism).
- L1-only: no L2 depth features (platform constraint).
