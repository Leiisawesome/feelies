# P2-1 — Inventory sign confirmation (forward-return IC)

**Status:** measurement tooling shipped; the study itself is **blocked on
real L1 NBBO data**. The repo ships only synthetic fixtures (a seeded
random walk, `tests/fixtures/event_logs/synth_5min_aapl.jsonl`) which
carry no real microstructure signal, so an IC run on them is a *mechanical
smoke test only* (expected ρ ≈ 0), not a sign confirmation.

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

## Notes

- `min_samples=30` on `RollingZscoreFeature`: the first ~30 boundaries are
  cold (`warm=False`) and must be skipped.
- Use event-time horizons only; never wall-clock (Inv-6 / determinism).
- L1-only: no L2 depth features (platform constraint).
