# Sensor Audit - 2026-06-19

Read-only audit of the Layer-1 sensor framework and its path into
`HorizonFeatureSnapshot` features. No production code was changed.

Severity legend: **P0** correctness / contract / lookahead risk; **P1** feature
strength / tradability; **P2** research / validation depth.

## Executive Summary

**Assumptions.** The authoritative active sensor set is `platform.yaml`
`sensor_specs:`; dormant modules in `src/feelies/sensors/impl/` are audited as
available research code, not live production inputs. The G16 mechanism contracts
are the fingerprints in `.cursor/skills/microstructure-alpha/SKILL.md:91-107`.

**Verification.** Read-only checks passed:

- `UV_CACHE_DIR=/private/tmp/feelies-uv-cache uv run pytest tests/sensors/ -q`
  -> 183 passed, 1 skipped.
- `UV_CACHE_DIR=/private/tmp/feelies-uv-cache uv run pytest tests/determinism/test_sensor_reading_replay.py tests/determinism/test_horizon_feature_snapshot_replay.py -q`
  -> 4 passed.

**Top findings.**

| Severity | Finding | Evidence | Recommendation |
|---|---|---|---|
| P0 | `HorizonTick.timestamp_ns` and therefore `HorizonFeatureSnapshot.timestamp_ns` are the first event at or after the boundary, not the exact integer boundary. This is causal, but it drifts from the architecture language and shifts staleness / forward-return pairing after sparse periods. | Boundary correlation id uses `boundary_ts`, but `timestamp_ns=now_ns` in `src/feelies/sensors/horizon_scheduler.py:304-315`; snapshots copy tick timestamp in `src/feelies/features/aggregator.py:528-548`; docs describe event-time boundaries in `docs/three_layer_architecture.md:431-484`. | Add an explicit `boundary_ts_ns` or stamp ticks at the boundary, then update replay / IC pairing tests across sparse tapes. |
| P0 | Aggregator buffers are version-keyed, but feature dispatch is version-blind; mixed sensor versions for one `sensor_id` can fold incompatible estimators into the same feature state after only a warning. | Buffers key `(symbol, sensor_id, sensor_version)` while dispatch maps only `sensor_id -> features` in `src/feelies/features/aggregator.py:232-313`; version mismatch is warned, not rejected, in `src/feelies/features/aggregator.py:378-405`. | Reject mixed active versions for a feature, or key feature state by `(sensor_id, sensor_version)` and require explicit feature ids. |
| P0 | The `SensorSpec` throttle contract documents `stateful=True` as required for throttled accumulators, but the current active YAML leaves all throttles null, so the invariant is latent and not acceptance-tested. | Contract in `src/feelies/sensors/spec.py:78-100`; validation only warns on dependency shape in `src/feelies/sensors/spec.py:125-149`; active specs show `throttled_ms: null` throughout `platform.yaml:254-453`. | Make throttled accumulator specs fail fast unless `stateful=True`; add one registry test for stateful vs non-stateful throttle semantics. |
| P1 | The active sensor math is mostly deterministic and causal, but several live sensors are explicitly heuristic L1 proxies rather than identified latent variables: quote replenishment, quote hazard, quote flicker, inventory pressure, liquidity stress, and Hawkes intensity. | Each implementation uses deterministic window math, but proxy definitions are heuristic: replenishment counts same-price size additions (`src/feelies/sensors/impl/quote_replenish_asymmetry.py:115-152`), hazard is quote arrivals/sec (`src/feelies/sensors/impl/quote_hazard_rate.py:79-88`), flicker is direction-reversal fraction (`src/feelies/sensors/impl/quote_flicker_rate.py:110-143`), Hawkes is EWMA impulse tracking (`src/feelies/sensors/impl/hawkes_intensity.py:1-45`). | Treat these as candidate features requiring IC / sign validation by regime and symbol, not as literature-estimated sufficient statistics. |
| P1 | Horizon aggregation is intentionally feature-local; it does not reconcile conflicting signs or fuse related sensors. That keeps invariants clean but pushes collinearity and sign conflicts into alpha code. | Aggregator doc states no cross-feature fusion in `src/feelies/features/aggregator.py:57-70`; snapshot `values` are per feature with per-feature `warm` / `stale` in `src/feelies/features/aggregator.py:492-526`. | Keep this design, but require alpha-level sign matrices and minimal IC evidence for any multi-sensor mechanism. |
| P1 | Current reference alphas use sensible warm-gated features, but some mechanism mappings still leave SNR on the table: Kyle alphas read `ofi_ewma` instead of integrated raw OFI; Hawkes burst ignores the available signed Hawkes imbalance; inventory uses raw quote hazard floors that are quote-rate sensitive. | Kyle reads `ofi_ewma` in `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:147-170`; Hawkes reads intensity z, trade-through, and OFI in `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:151-184`; inventory uses raw `quote_hazard_rate` in `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:221-264`. | Prefer `ofi_integrated` for permanent-impact hypotheses, add `hawkes_intensity_imbalance` to Hawkes direction checks, and normalize quote-rate gates. |
| P1 | Offline sensor IC tooling is real and causal, but covers only four sensor families and lacks regime / cost stratification. | The script defines only OFI, micro-price, realized-vol, and Kyle specs in `scripts/sensor_feature_ic.py:79-114`; it replays through registry / scheduler / aggregator and pairs warm snapshots with forward returns in `scripts/sensor_feature_ic.py:163-246` and `scripts/sensor_feature_ic.py:305-324`. | Extend the harness to inventory, Hawkes, stress, scheduled flow, and output RankIC by regime, spread, hazard, and round-trip cost bucket. |
| P2 | Snapshot persistence touchpoint is an opaque feature-engine checkpoint, not a `HorizonFeatureSnapshot` event store. It does not round-trip `values`, `warm`, `stale`, `source_sensors`, or feature versions. | Checkpoint fields are `symbol`, `version`, `state`, event counters, timestamp, and checksum in `src/feelies/storage/feature_snapshot.py:23-72`; memory store verifies opaque checksum and returns snapshot metadata in `src/feelies/storage/memory_feature_snapshot.py:16-66`. | Do not rely on this touchpoint for feature-event replay; keep event persistence ownership in the data-ingestion audit surface. |

## Sensor Inventory

Active sensors are flat: all live `input_sensor_ids` are empty in
`platform.yaml:254-453`, so the sensor DAG currently has no live edges. The
registry can reject missing upstream dependencies and cycles
(`src/feelies/sensors/registry.py:152-213`), but the current production graph is
a fan-out from raw NBBO / trade events.

| Status | Sensor | Version | Inputs | Key params / warm-up | Clock | Primary mechanism |
|---|---|---:|---|---|---|---|
| active | `spread_z_30d` | 1.1.0 | NBBO | count window 6000, `max_gap_seconds=300`, `min_std=1e-9` (`platform.yaml:254-267`) | quote-count with gap reset | liquidity stress / spread regime |
| active | `quote_replenish_asymmetry` | 1.1.0 | NBBO | 5 s, min 20 observations (`platform.yaml:269-278`) | event time | inventory replenishment proxy |
| active | `quote_hazard_rate` | 1.0.0 | NBBO | 5 s, min 20 samples (`platform.yaml:280-289`) | event time | quote activity / ladder freshness |
| active | `ofi_ewma` | 1.1.0 | NBBO | alpha 0.1, warm after 50 in 300 s (`platform.yaml:291-301`) | quote-event decay | signed order-flow pressure |
| active | `ofi_raw` | 1.0.0 | NBBO | warm after 50 in 300 s (`platform.yaml:306-315`) | event time | integrated OFI input |
| active | `micro_price` | 1.1.0 | NBBO | warm after 1 in 60 s (`platform.yaml:317-326`) | event time | size-weighted price pressure |
| active | `book_imbalance` | 1.0.0 | NBBO | warm after 1 in 60 s (`platform.yaml:331-340`) | event time | normalized top-of-book imbalance |
| active | `kyle_lambda_60s` | 2.0.0 | NBBO + Trade | 60 s, min 30 samples, causal (`platform.yaml:344-373`) | event time | price impact / informed flow |
| active | `trade_through_rate` | 1.1.0 | NBBO + Trade | 30 s, min 5 trades (`platform.yaml:375-383`) | event time | NBBO aggression proxy |
| active | `hawkes_intensity` | 1.2.0 | Trade | EWMA alpha/beta, warm 10 trades per side (`platform.yaml:385-396`) | calendar decay on trade events | self-excitation / burstiness |
| active | `scheduled_flow_window` | 1.2.0 | NBBO | calendar injected by bootstrap (`platform.yaml:398-405`) | wall / event calendar | scheduled flow |
| active | `realized_vol_30s` | 1.3.0 | NBBO | 30 s, warm after 16 returns (`platform.yaml:407-416`) | event time | volatility / stress |
| active | `inventory_pressure` | 1.0.0 | Trade | 60 s, min 20 trades (`platform.yaml:420-429`) | event time | dealer inventory proxy |
| active | `liquidity_stress_score` | 1.0.0 | NBBO | count window 6000, sensitivity 2, gap 300 s (`platform.yaml:431-442`) | quote-count with gap reset | liquidity stress |
| active | `quote_flicker_rate` | 1.0.0 | NBBO | 5 s, min 20 quotes (`platform.yaml:444-453`) | event time | quote instability |
| dormant | `vpin_50bucket` | 1.1.0 | Trade | equal-volume buckets | volume time | VPIN / toxic flow |
| dormant | `snr_drift_diffusion` | 1.3.0 | NBBO | grid horizons | grid time | drift-vs-diffusion |
| dormant | `structural_break_score` | 1.2.0 | NBBO | Page-Hinkley over mid returns | event time | break / decay diagnostic |

## Per-Sensor Audit

### `spread_z_30d`

`spread_z_30d` computes a rolling spread z-score using Welford state over the
last `window` quotes and resets after large time gaps
(`src/feelies/sensors/impl/spread_z_30d.py:103-184`). Numerically, this is
stable: bad quotes are dropped, minimum standard deviation is floored, and the
output is bounded by the historical spread distribution rather than by a fixed
tick-size assumption. The main modeling issue is naming: `"30d"` is not a
30-day exchange-time baseline in the live config; it is a 6000-quote count
window (`platform.yaml:254-267`). That makes it quote-rate dependent. This is
acceptable as a stress gate, but it should not be interpreted as a daily
percentile without offline calibration.

Tests cover warm-up, gaps, determinism, and invalid quotes
(`tests/sensors/test_spread_z_30d.py:28-95`). Missing: a property that a
constant spread remains near zero after warm-up across different quote rates.

### `quote_replenish_asymmetry`

The estimator counts positive same-price size additions on bid and ask inside a
5 s window, then emits `(bid_add - ask_add) / (bid_add + ask_add)`
(`src/feelies/sensors/impl/quote_replenish_asymmetry.py:115-152`). The
inventory interpretation is plausible but heuristic: L1 cannot tell whether a
size increase is a single market maker replenishing inventory, venue rotation,
odd-lot consolidation, hidden depth refresh, or quote stuffing. Warm-up requires
enough quotes and at least one addition on both sides
(`src/feelies/sensors/impl/quote_replenish_asymmetry.py:30-35`), which avoids
one-sided denominator artifacts but can keep the feature cold during exactly the
most one-sided dislocations.

The inventory alpha explicitly acknowledges the sign assumption needs empirical
confirmation against forward 30 s micro-price returns
(`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:233-239`).
That is the right stance. The sensor should be treated as a candidate
inventory-fade feature, not a proven sign source.

### `quote_hazard_rate`

This is a quote arrival intensity, `count / window_seconds`, over a rolling
deque (`src/feelies/sensors/impl/quote_hazard_rate.py:79-88`). It is rigorous
as an L1 activity-rate statistic, but not a fitted survival hazard. Because the
inventory alpha uses an absolute floor of 4 events/sec
(`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:75-99` and
`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:221-228`),
feature meaning is symbol-, venue-, and feed-rate sensitive. Use the raw value
for ladder-freshness gating only after per-symbol calibration; for alpha
ranking, prefer z-score or percentile at the horizon.

### `ofi_ewma`

`ofi_ewma` implements the Cont-Kukanov-Stoikov L1 OFI contribution rules and
then applies an event-count EWMA
(`src/feelies/sensors/impl/ofi_ewma.py:127-147`). This is the strongest
signed-flow estimator in the active set: the formula is standard, causal, and
deterministic. Warm-up is a sliding quote-count budget inside a wall-clock
window (`src/feelies/sensors/impl/ofi_ewma.py:149-166`), so it recovers after
gaps.

The caveat is time basis. Alpha 0.1 is a per-quote decay, not a 60-1800 s Kyle
half-life. It becomes a very fast flow-pressure sensor during active names and
a slower sensor in sparse names. For permanent-impact mechanisms, the already
wired `ofi_raw` + horizon-window `sum` path is closer to the literature than
using the boundary EWMA level.

### `ofi_raw`

`ofi_raw` emits the same CKS per-event contribution without EWMA smoothing
(`src/feelies/sensors/impl/ofi_raw.py:125-160`). The first quote emits a cold
zero rather than seeding false flow (`src/feelies/sensors/impl/ofi_raw.py:108-123`).
This is the correct input for integrated OFI features; bootstrap already wires
`ofi_integrated` through a horizon-window `sum`
(`src/feelies/bootstrap.py:1147-1163`). That feature should be preferred for
Kyle-style permanent impact tests over the `ofi_ewma` last-value feature.

### `micro_price`

`micro_price` implements the Stoikov size-weighted micro-price formula and
falls back to mid with `warm=False` on zero depth
(`src/feelies/sensors/impl/micro_price.py:79-102`). The estimator is rigorous,
but the emitted level is not the best alpha feature. The informative component
is `micro - mid = spread * book_imbalance / 2`; z-scoring the raw price level
mostly captures mid-price drift. Bootstrap currently wires passthrough, z-score,
and horizon delta features for `micro_price`
(`src/feelies/bootstrap.py:1296-1314`). The safer L1 feature for size pressure is
the separate `book_imbalance` sensor, which `sig_benign_midcap_v1` now uses for
OFI confirmation (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:170-193`).

### `book_imbalance`

`book_imbalance` emits `(bid_size - ask_size) / (bid_size + ask_size)`, bounded
in `[-1, 1]`, with `warm=False` when both sides have zero depth
(`src/feelies/sensors/impl/book_imbalance.py:111-142`). This is the
level-invariant form of the micro-price footprint and is more suitable for
cross-symbol alpha than raw `micro_price`. L1 cannot see hidden depth or queue
priority, but the top-of-book statistic is mathematically clean and cheap.

Tests cover formula and degenerate books (`tests/sensors/test_book_imbalance.py`
via the `tests/sensors/` pass), and economic sign goldens include book imbalance
alignment (`tests/sensors/test_sensor_sign_goldens.py:60-157`).

### `kyle_lambda_60s`

The active config pins the causal v2.0.0 alignment for Kyle lambda
(`platform.yaml:344-373`). The implementation pairs previous signed trade size
with the next observed mid-price change, maintains OLS sums in a 60 s window,
and emits the slope when the denominator is nondegenerate
(`src/feelies/sensors/impl/kyle_lambda_60s.py:166-230`). That is the right
causal correction for L1 replay.

Remaining limitations are L1-identifiability issues: trade signing uses a tick
rule (`src/feelies/sensors/impl/kyle_lambda_60s.py:158-164`), NBBO mid may be
stale between trades, and lambda is not normalized by price, ADV, or spread.
The OLS estimator is also noisy at the configured `min_samples=30`, so its best
use is as a percentile / regime feature, not a standalone directional signal.

### `trade_through_rate`

Despite the id, the implementation is not strict Reg-NMS trade-through
detection; its own docstring states it is a broader "at or beyond NBBO"
aggression rate retained under the legacy id
(`src/feelies/sensors/impl/trade_through_rate.py:1-12`). It stores the last
valid NBBO and counts trades with `price >= ask` or `price <= bid`
(`src/feelies/sensors/impl/trade_through_rate.py:89-127`). As a Hawkes burst
confirmatory feature this is useful, but it should be described as
`nbbo_aggression_rate` in research notes to avoid legal / market-structure
confusion.

### `hawkes_intensity`

The sensor keeps two exponentially decayed impulse accumulators for buy- and
sell-signed trades, not a fitted Hawkes conditional intensity with a branching
ratio (`src/feelies/sensors/impl/hawkes_intensity.py:1-45`). Decay is calendar
time between trades (`src/feelies/sensors/impl/hawkes_intensity.py:137-157`),
trade side uses a tick rule, and the output tuple is `(buy_lambda, sell_lambda,
total_lambda, ratio)` (`src/feelies/sensors/impl/hawkes_intensity.py:158-224`).

This is deterministic and useful as a burstiness statistic, but the math should
not be oversold: alpha/beta from `scripts/calibrate_hawkes.py` fits a different
true Hawkes likelihood (`scripts/calibrate_hawkes.py:50-79` and
`scripts/calibrate_hawkes.py:152-174`). Bootstrap now exposes both total
intensity z-score and a signed imbalance feature
(`src/feelies/bootstrap.py:1252-1272`; `src/feelies/features/impl/sensor_passthrough.py:159-241`).
`sig_hawkes_burst_v1` still directs with OFI rather than the available Hawkes
imbalance (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:151-184`).

### `scheduled_flow_window`

This is a deterministic event-calendar sensor, not a market-data estimator. It
selects the active configured window and emits `(active, seconds_to_close,
window_id_hash, direction_prior)` (`src/feelies/sensors/impl/scheduled_flow_window.py:112-186`).
Warm means the symbol has at least one eligible calendar window
(`src/feelies/sensors/impl/scheduled_flow_window.py:76-108`), not that current
flow is empirically strong.

Bootstrap exposes active, seconds-to-close, and direction-prior components, but
not `window_id_hash` (`src/feelies/bootstrap.py:1276-1295`). That is adequate
for a single MOC-type alpha. If multiple scheduled-flow event types coexist,
downstream alphas cannot distinguish them without adding an id or category
feature. The MOC alpha correctly treats the directional edge as exogenous prior
plus OFI agreement (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:157-214`).

### `realized_vol_30s`

The sensor computes sample standard deviation of log mid-price returns over a
30 s event-time window, with invalid quotes clearing the previous mid
(`src/feelies/sensors/impl/realized_vol_30s.py:94-152`). The estimator is
standard and numerically stable for L1 mid returns. `warm_after=16` is thin for
a variance estimate but reasonable as a low-latency stress input.

Bootstrap uses a count-window rolling z-score rather than horizon-window z-score
for realized vol (`src/feelies/bootstrap.py:1315-1328`). That makes the
normalizer quote-rate dependent, but it likely reduces horizon smearing for
stress gates. Keep it as a gating feature, not as a directional alpha input.

### `inventory_pressure`

`inventory_pressure` uses tick-rule trade signing, flips aggressor side to infer
market-maker inventory change, and emits normalized inventory pressure over a
60 s trade window (`src/feelies/sensors/impl/inventory_pressure.py:105-156`).
This is a Ho-Stoll / Madhavan-Smidt-style L1 proxy, not observable inventory.
It can help contrarian hypotheses, but first-trade sign defaults and midpoint
prints can bias early state. The live inventory alpha currently uses
`quote_replenish_asymmetry_zscore` rather than `inventory_pressure` itself
(`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:207-239`),
which is conservative.

### `liquidity_stress_score`

This is a composite unsigned stress alarm: spread z-score plus inverted-depth
z-score through Welford baselines, with gap resets and warm gating
(`src/feelies/sensors/impl/liquidity_stress_score.py:171-215`). It is useful
for exit and regime suppression, but it is not directional. G16 explicitly marks
`LIQUIDITY_STRESS` as exit-only (`.cursor/skills/microstructure-alpha/SKILL.md:91-95`),
so this family should continue to block entries rather than generate them.

### `quote_flicker_rate`

The sensor counts best-price direction reversals as a fraction of recent quote
moves (`src/feelies/sensors/impl/quote_flicker_rate.py:110-143`). This is a
reasonable top-of-book instability proxy, but "rate" is a misnomer because the
output is a fraction, not reversals/sec. It ignores quote lifetime, size, and
venue identity, so it should be an exit / stress overlay only.

### Dormant Implementations

`vpin_50bucket` implements equal-volume buckets with tick-rule trade signing and
VPIN over filled buckets (`src/feelies/sensors/impl/vpin_50bucket.py:104-157`).
It is literature-aligned with Easley-Lopez de Prado-O'Hara VPIN, but inactive in
`platform.yaml`.

`snr_drift_diffusion` computes drift-vs-diffusion SNR on deterministic grids
with gap splitting (`src/feelies/sensors/impl/snr_drift_diffusion.py:140-218`).
It is mathematically stronger than most heuristics, but `abs(mu)` removes
direction and default anchoring should be session-aware before promotion.

`structural_break_score` is a Page-Hinkley-like detector over absolute mid
log-returns (`src/feelies/sensors/impl/structural_break_score.py:149-214`).
Its docstring says the intended future design is a cross-sensor break score over
upstream sensors such as Hawkes (`src/feelies/sensors/impl/structural_break_score.py:16-27`),
so the dormant module does not yet implement the advertised composition.

## Horizon Aggregation Audit

**Boundary alignment.** `HorizonScheduler` uses integer boundary math and lazy
session anchoring (`src/feelies/sensors/horizon_scheduler.py:86-145` and
`src/feelies/sensors/horizon_scheduler.py:173-229`). It emits one current
boundary per event and does not backfill skipped boundaries
(`src/feelies/sensors/horizon_scheduler.py:233-285`). This prevents synthetic
snapshots in sparse tapes, but it also means the first event after a gap carries
the next snapshot timestamp. The boundary index and correlation id are computed
from the exact boundary timestamp while `HorizonTick.timestamp_ns` is the
triggering event timestamp (`src/feelies/sensors/horizon_scheduler.py:287-326`).
Aggregator staleness and offline forward-return pairing therefore use trigger
time, not exact boundary time.

**Snapshot construction.** The aggregator sorts features deterministically,
buckets them by horizon, and builds snapshots only for matching horizon seconds
(`src/feelies/features/aggregator.py:163-198` and
`src/feelies/features/aggregator.py:477-491`). `values` contains warm feature
values only; `warm` and `stale` include every feature
(`src/feelies/features/aggregator.py:513-526`). The event schema matches the
Layer-2 contract: `values`, `warm`, `stale`, `source_sensors`,
`feature_versions`, and parent correlation id
(`src/feelies/core/events.py:604-644`).

**Warm / stale semantics.** The last warm reading timestamp is updated only for
warm sensor readings (`src/feelies/features/aggregator.py:284-301` and
`src/feelies/features/aggregator.py:354-419`). At snapshot time, a feature is
stale when no warm input arrived within that feature horizon
(`src/feelies/features/aggregator.py:492-512`). This is conservative and avoids
last-value lookahead. `HorizonSignalEngine` suppresses entries on required warm
/ stale failures but still evaluates gates and allows close signals, preserving
the fail-safe exit invariant (`src/feelies/signals/horizon_engine.py:333-380`
and `src/feelies/signals/horizon_engine.py:389-480`).

**Aggregation policies.**

| Policy | Implementation | Sensors / features | Audit verdict |
|---|---|---|---|
| latest warm scalar | `SensorPassthroughFeature` ignores cold / tuple readings and emits the latest warm scalar (`src/feelies/features/impl/sensor_passthrough.py:34-89`) | spread stress, OFI EWMA, raw rates, trade-through, inventory pressure, liquidity stress | Good for state-like sensors; can smear fast mean-reversion if used as a 30 s alpha input without explicit staleness checks. |
| tuple component | `TupleComponentFeature` extracts configured tuple positions (`src/feelies/features/impl/sensor_passthrough.py:92-156`) | scheduled flow active / seconds / prior, Hawkes components | Good; missing scheduled `window_id_hash` if event identity matters. |
| signed tuple imbalance | `(pos - neg) / (pos + neg)` (`src/feelies/features/impl/sensor_passthrough.py:159-241`) | Hawkes buy/sell intensity imbalance | Good feature-quality improvement; not yet consumed by Hawkes alpha. |
| event-time horizon window | `HorizonWindowedFeature` retains warm readings in `[tick-horizon, tick]` and supports last / mean / sum / delta / percentile / rms / z-score (`src/feelies/features/impl/horizon_windowed.py:229-308`) | OFI integrated, book-imbalance mean, micro-price drift, many z-scores | Strong general surface. The `sum` reducer is event-count sum, not time integral; fine for raw OFI contributions, less appropriate for irregular quote-rate sensors. |
| count-window rolling stats | `RollingZscoreFeature` and percentile maintain FIFO sample windows (`src/feelies/features/impl/rolling_stats.py:87-321`) | Kyle percentile/z, realized-vol z | Useful for regime ranking, but quote/trade-rate dependent and should be backed by offline IC evidence. |

**Feature wiring.** Bootstrap creates features for all active sensors; unknown
sensor ids are silently skipped by factory lookup only if a future active sensor
lacks a factory (`src/feelies/bootstrap.py:1343-1360`). The active wiring
includes `ofi_integrated` (`src/feelies/bootstrap.py:1147-1163`), book imbalance
mean / z-score (`src/feelies/bootstrap.py:1164-1188`), Kyle percentile / z-score
(`src/feelies/bootstrap.py:1189-1205`), Hawkes total z and signed imbalance
(`src/feelies/bootstrap.py:1252-1272`), scheduled-flow components
(`src/feelies/bootstrap.py:1276-1295`), and realized-vol z-score
(`src/feelies/bootstrap.py:1315-1328`).

**Multi-sensor fusion.** Aggregator does not fuse signs across sensors. That is
intentional (`src/feelies/features/aggregator.py:57-70`) and architecturally
clean, but it means the alpha author must reconcile momentum-like `ofi_ewma`
with contrarian `quote_replenish_asymmetry`, unsigned stress sensors, and
calendar priors. The current signal engine prioritizes snapshot values and only
falls back to sensor cache for missing ids (`src/feelies/signals/horizon_engine.py:613-660`),
so `HorizonFeatureSnapshot` is effectively the Layer-2 feature source.

## Mechanism × Horizon Matrix

G16 requires each alpha's `horizon_seconds / expected_half_life_seconds` ratio
to lie in `[0.5, 4.0]` and marks liquidity stress as exit-only
(`.cursor/skills/microstructure-alpha/SKILL.md:91-112`).

| Mechanism | G16 horizon | Active L1 observables | Reference consumers | Feature-quality verdict |
|---|---:|---|---|---|
| `KYLE_INFO` | 60-1800 s | `kyle_lambda_60s`, `ofi_ewma`, `ofi_raw`, `micro_price`, `book_imbalance`, `spread_z_30d` | `sig_kyle_drift_v1` at 300 s consumes Kyle percentile/z and OFI (`alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:132-170`); `sig_benign_midcap_v1` at 120 s consumes OFI z and book imbalance mean (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:150-200`). | Coverage is good. Strongest improvement is replacing / augmenting OFI EWMA with `ofi_integrated` for permanent-impact tests and avoiding raw micro-price level z-score. |
| `INVENTORY` | 5-60 s | `quote_replenish_asymmetry`, `inventory_pressure`, `quote_hazard_rate`, `spread_z_30d` | `sig_inventory_revert_v1` at 30 s consumes replenishment asymmetry z, raw hazard, and vol taper (`alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:207-264`). | Horizon is appropriate. Sign is empirical and L1-limited; quote hazard should be normalized or calibrated per symbol before live confidence. |
| `HAWKES_SELF_EXCITE` | 5-60 s | `hawkes_intensity`, `trade_through_rate`, `ofi_ewma`, `quote_flicker_rate` | `sig_hawkes_burst_v1` at 30 s consumes total Hawkes z, trade-through rate, and OFI (`alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:128-184`). | Fast horizon matches mechanism. The total-intensity feature captures burstiness, but direction currently comes from OFI; add Hawkes signed imbalance to avoid discarding side-specific excitation. |
| `LIQUIDITY_STRESS` | 30-600 s, exit-only | `liquidity_stress_score`, `realized_vol_30s`, `spread_z_30d`, `quote_hazard_rate`, `quote_flicker_rate`; dormant `vpin_50bucket` | Used in gates across alphas, e.g. spread/vol off switches in `sig_benign_midcap_v1` (`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:121-138`). | Correct as entry suppression / exit context. Do not promote stress alone to directional entries without a separate force. |
| `SCHEDULED_FLOW` | 60-1800 s | `scheduled_flow_window`, `ofi_ewma`, `realized_vol_30s` | `sig_moc_imbalance_v1` at 120 s consumes active, seconds-to-close, direction prior, and OFI (`alphas/sig_moc_imbalance_v1/sig_moc_imbalance_v1.alpha.yaml:146-214`). | Mechanism is exogenous prior + confirmation, not endogenous alpha. Add event identity only if multiple schedule types share one alpha surface. |

Tradability implication: the cost bars in reference alphas are already explicit
and conservative, but the sensor audit cannot validate `expected_edge > 1.5x`
round-trip cost from code alone. The offline IC harness must stratify by spread,
hazard, and realized vol before any sensor-family edge is considered tradable.

## Test Gap Matrix

| Surface | Current coverage | Gap | Minimal new test spec |
|---|---|---|---|
| Registry / DAG | Registration validates ids, versions, dependencies, provenance, and deterministic order (`src/feelies/sensors/registry.py:152-213`; `tests/sensors/test_registry.py` in the green run). | No active DAG edges; cycle / dependency coverage is synthetic only. | Add one two-sensor test where an upstream reading is consumed by a downstream sensor to exercise topological order under real `SensorReading` inputs. |
| Throttle semantics | Dispatch has separate stateful vs non-stateful throttle behavior (`src/feelies/sensors/registry.py:232-312`). | No active spec sets `throttled_ms`; no acceptance guard for accumulator aliasing. | Golden test: a stateful accumulator under throttle must see every event while emitting sparsely; a non-stateful sensor must skip update calls. |
| Boundary alignment | Scheduler tests cover emission and props (`tests/sensors/test_horizon_scheduler.py:34-177`; `tests/sensors/test_horizon_scheduler_props.py:47-84`). | No sparse-tape assertion that `timestamp_ns` is trigger time while boundary id is nominal time. | Build a tape with a 10-minute gap; assert exact `boundary_ts_ns` once added, or lock documented trigger-time behavior. |
| Snapshot warm/stale | Aggregator tests cover passive/active/stale, horizon mismatch, per-symbol isolation, buffer eviction, dedup, and feature versions (`tests/features/test_aggregator.py:118-338`). | Version mismatch is warning-only, not fail-fast; no mixed-version pollution test. | Register two versions of same sensor id feeding same feature and assert boot rejection or separate feature ids. |
| OFI family | OFI unit tests and sign goldens cover main mechanics (`tests/sensors/test_ofi_ewma.py:27-99`; `tests/sensors/test_sensor_sign_goldens.py:60-157`). | No explicit comparison of `ofi_ewma` vs `ofi_integrated` on a known horizon tape. | Golden tape: known CKS contributions over 30 s; assert `ofi_integrated == sum(e_t)` and EWMA sign follows recent flow. |
| Micro-price / book imbalance | Unit tests cover formula and degenerate depth (`tests/sensors/test_micro_price.py:27-73`). | No test proving `micro - mid == spread * book_imbalance / 2` across random valid quotes. | Property test over positive bid/ask sizes and valid spreads; assert algebra and sign. |
| Kyle lambda | Unit tests cover causal alignment and regression vectors (`tests/sensors/test_kyle_lambda_60s.py:46-240`). | No alpha-level test that Kyle percentile + integrated OFI sign preserves forward-return sign on a golden tape. | Replay miniature tape with known signed impact and assert positive causal lambda, positive `ofi_integrated`, and no legacy-sign path. |
| Quote replenishment | Unit tests cover bounds / warm / window behavior (`tests/sensors/test_quote_replenish_asymmetry.py:30-121`). | Economic sign not in `test_sensor_sign_goldens.py`. | Golden: bid-side same-price replenishment after bid depletion -> positive sensor; assert alpha's documented direction mapping separately. |
| Quote hazard / flicker | Unit tests cover basic rates and bounds (`tests/sensors/test_quote_hazard_rate.py:28-98`; `tests/sensors/test_quote_flicker_rate.py:51-115`). | No per-symbol normalization or sparse-feed false-warm test. | Property: same quote pattern at 2x event rate changes raw hazard but not z-score after normalization; sparse stale ladder fails entry gate. |
| Hawkes | Unit tests cover decay/warm and calibration script tests cover MLE utilities (`tests/sensors/test_hawkes_intensity.py:26-122`; `tests/scripts/test_calibrate_hawkes.py:1-109`). | Sensor and calibrator implement different mathematical objects; no test ties calibrated beta to sensor half-life behavior. | Fit synthetic clustered trades, set sensor beta from fit, and assert deterministic decay half-life; separately assert side imbalance sign. |
| Scheduled flow | Unit tests cover calendar selection and tuple output (`tests/sensors/test_scheduled_flow_window.py:60-137`). | No feature-level test for missing `window_id_hash` when two windows overlap with same prior. | Add overlapping windows with distinct ids; assert deterministic earliest-end selection and decide whether feature exposes id. |
| Realized vol / stress | Unit tests cover realized-vol and stress behavior (`tests/sensors/test_realized_vol_30s.py:28-93`; `tests/sensors/test_liquidity_stress_score.py:51-129`). | No test that stress sensors cannot directly create entry signals. | Alpha validation test: `LIQUIDITY_STRESS` mechanism with non-flat entry should fail G16 gate. |
| Offline IC | Script tests cover forward return drop and snapshot pairing (`tests/scripts/test_sensor_feature_ic.py:1-153`). | Only four sensor families; no regime/cost buckets. | Add fixtures for inventory, Hawkes, scheduled-flow, and stress; output RankIC by horizon, regime posterior, spread z, hazard, and cost bucket. |

## Prioritized Backlog

### P0 - Correctness / Contract Hardening

1. **`horizon_scheduler.py` / `aggregator.py`: make boundary timestamp semantics explicit.** Add `boundary_ts_ns` to `HorizonTick` / `HorizonFeatureSnapshot`, or stamp `timestamp_ns` at the exact boundary. Expected impact: removes sparse-tape horizon jitter from staleness and IC labels. Evidence:
   `src/feelies/sensors/horizon_scheduler.py:304-315`,
   `src/feelies/features/aggregator.py:528-548`.

2. **`features/aggregator.py`: reject mixed sensor versions feeding one feature.** Current warning-only handling can blend incompatible estimators into one feature state. Expected impact: prevents silent A/B or migration contamination. Evidence:
   `src/feelies/features/aggregator.py:232-313`,
   `src/feelies/features/aggregator.py:378-405`.

3. **`sensors/spec.py` / registry tests: enforce throttled accumulator semantics.** Make non-null `throttled_ms` plus accumulator-style sensors require `stateful=True`. Expected impact: prevents future throttle aliasing of OFI / Kyle / Hawkes state. Evidence:
   `src/feelies/sensors/spec.py:78-100`,
   `src/feelies/sensors/registry.py:232-312`.

### P1 - Feature Strength / Alpha Usability

1. **Kyle family: prefer `ofi_integrated` over `ofi_ewma` for permanent-impact hypotheses.** `ofi_integrated` is already wired via `ofi_raw` sum, while `sig_kyle_drift_v1` reads `ofi_ewma`. Expected impact: less event-decay distortion at 300 s horizons. Evidence:
   `src/feelies/bootstrap.py:1147-1163`,
   `alphas/sig_kyle_drift_v1/sig_kyle_drift_v1.alpha.yaml:147-170`.

2. **Hawkes family: add `hawkes_intensity_imbalance` to directional confirmation.** Total intensity z-score captures burstiness, but OFI currently supplies direction. Expected impact: preserves side-specific self-excitation and reduces contradictory signals. Evidence:
   `src/feelies/bootstrap.py:1252-1272`,
   `alphas/sig_hawkes_burst_v1/sig_hawkes_burst_v1.alpha.yaml:151-184`.

3. **Inventory family: normalize quote hazard / flicker before alpha gating.** Raw events/sec depends on symbol and feed rate. Expected impact: fewer false inactive / false active gates across liquidity regimes. Evidence:
   `src/feelies/sensors/impl/quote_hazard_rate.py:79-88`,
   `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml:75-99`.

4. **Scheduled flow: expose event identity if multiple calendar event types are modeled.** Current features omit `window_id_hash`. Expected impact: prevents mixing MOC, earnings, and other scheduled priors under one indistinguishable feature surface. Evidence:
   `src/feelies/sensors/impl/scheduled_flow_window.py:152-186`,
   `src/feelies/bootstrap.py:1276-1295`.

5. **Micro-price family: keep alphas on `book_imbalance` or normalized `micro-mid`, not raw `micro_price_zscore`.** Expected impact: avoids price-level momentum leakage in a feature that is intended to represent L1 size pressure. Evidence:
   `src/feelies/sensors/impl/micro_price.py:90-102`,
   `src/feelies/sensors/impl/book_imbalance.py:111-142`,
   `src/feelies/bootstrap.py:1296-1314`.

6. **Offline IC: expand `scripts/sensor_feature_ic.py` to every live mechanism.** Expected impact: converts heuristic sensors into evidence-ranked alpha inputs. Evidence:
   `scripts/sensor_feature_ic.py:79-114`,
   `scripts/sensor_feature_ic.py:305-324`.

### P2 - Research / Calibration

1. **Calibrate Hawkes beta / alpha per symbol but document that the live sensor is EWMA impulse tracking.** Expected impact: better half-life tuning without claiming true Hawkes branching-ratio semantics. Evidence:
   `src/feelies/sensors/impl/hawkes_intensity.py:1-45`,
   `scripts/calibrate_hawkes.py:50-79`.

2. **Promote VPIN only after bucket-size sensitivity and cost survival tests.** Expected impact: adds a literature-aligned toxic-flow stress input without overfitting volume buckets. Evidence:
   `src/feelies/sensors/impl/vpin_50bucket.py:104-157`.

3. **Rework `structural_break_score` into the intended cross-sensor decay diagnostic before activation.** Expected impact: detects alpha-regime breaks rather than just mid-return volatility spikes. Evidence:
   `src/feelies/sensors/impl/structural_break_score.py:16-27`,
   `src/feelies/sensors/impl/structural_break_score.py:149-214`.

4. **Evaluate cross-sectional normalization at the horizon boundary.** Expected impact: improves universe-level comparability for raw rate / count-window sensors. This belongs after the current per-symbol deterministic pipeline because the aggregator is intentionally per-symbol and feature-local
   (`src/feelies/features/aggregator.py:57-70`).

## Appendix

**Core contracts read.**

- Sensors are incremental, per-symbol, deterministic functions that emit
  `SensorReading` or `None` (`src/feelies/sensors/protocol.py:1-22` and
  `src/feelies/sensors/protocol.py:53-70`).
- `SensorReading` carries value, warm flag, sensor id/version, and provenance
  (`src/feelies/core/events.py:580-601`).
- `HorizonFeatureSnapshot` carries warm-only `values`, full `warm` / `stale`
  maps, source sensors, feature versions, and parent correlation id
  (`src/feelies/core/events.py:604-644`).
- Feature-engine skill confirms per-feature warm / stale semantics and
  entry-only suppression (`.cursor/skills/feature-engine/SKILL.md:188-239` and
  `.cursor/skills/feature-engine/SKILL.md:293-307`).

**Read-only checks.**

```text
UV_CACHE_DIR=/private/tmp/feelies-uv-cache uv run pytest tests/sensors/ -q
183 passed, 1 skipped

UV_CACHE_DIR=/private/tmp/feelies-uv-cache uv run pytest \
  tests/determinism/test_sensor_reading_replay.py \
  tests/determinism/test_horizon_feature_snapshot_replay.py -q
4 passed
```

**Notes on persistence touchpoint.** `feature_snapshot.py` and
`memory_feature_snapshot.py` persist opaque feature-engine state, not emitted
`HorizonFeatureSnapshot` events. Therefore this audit does not claim event
snapshot round-trip coverage from that store.
