# Sensor math-rigor & performance review — 2026-07-02

A focused review of **all 18 Layer-1 sensor implementations** for mathematical
rigor (estimator correctness, numerical stability, edge cases) and algorithmic
performance (per-event complexity, memory bounds). Companion to the
feature-strength audit [`sensor_audit_2026-07-02.md`](sensor_audit_2026-07-02.md);
this pass looks *inside* the estimators rather than at their path into
features. Findings are labelled **F1–F5** and are cited by those labels from
the code comments that implement the fixes.

**Net:** no correctness P0s — every estimator computes what it claims. Five
findings, all **implemented** in the same pass (see "Remediation" per finding).
All changes verified against the full suite (`uv run pytest` — 3856 passed,
43 skipped; only two pre-existing, unrelated failures remained untouched:
`tests/kernel/test_orchestrator.py::TestForcedExit*/TestTradeJournalProvenance`
STOP_EXIT journaling, and `test_no_walltime_outside_clock.py`'s stale
allowlist entry), `uv run mypy src/feelies` (strict, clean), and
`uv run ruff check` (clean).

Parity discipline: several of these sensors are pinned by locked golden-vector
fixtures (`tests/sensors/fixtures/*.jsonl`) and the Level-4 SensorReading
determinism hash (`tests/determinism/test_sensor_reading_replay.py`). Each fix
below states how it preserves or intentionally re-bakes those locks.

---

## F1 — `kyle_lambda_60s`: numerically fragile OLS (Medium-High) — FIXED

**Finding.** The slope was computed from four add-on-arrival /
subtract-on-eviction running sums as the textbook
`λ = (n·Σδpδq − Σδp·Σδq) / (n·Σδq² − (Σδq)²)` (`kyle_lambda_60s.py:202-218`
pre-fix). This is the "shortcut" sum-of-products form — the exact
catastrophic-cancellation pattern Welford's algorithm exists to avoid. With
`Δq ~ O(10²–10⁴)` shares over a 60 s window, `n·Σδq²` and `(Σδq)²` are both
~`10¹²` and their difference loses ~5–6 significant digits when `Δq` is nearly
constant — the regime where informed flow is most regular. The running sums
are also never periodically recomputed, so float error accumulates monotonically
across a full session. The `denom_eps` guard only catches full degeneracy
(blow-up), not the precision erosion of the slope itself.

**Remediation.** Added a streaming **Welford/Bennett co-moment** estimator
(`covariance_estimator="welford"`): running means + `M2_Δq` + co-moment `C`
with reverse updates on eviction and an exact recompute-from-window guard if
cancellation ever drives `M2_Δq` negative (mirroring F2). `λ = C / M2_Δq` — the
sample count cancels between Cov and Var, so it equals the sum-of-products
slope *in exact arithmetic* while staying near machine precision. Shipped as a
new `sensor_version="2.1.0"` (canonical pairing: `alignment="causal"` +
`covariance_estimator="welford"`); the default `"sum_products"` path (versions
1.2.0/2.0.0) is byte-untouched, so the locked golden vector passes unchanged.
Adopted in `platform.yaml` (kyle bumped 2.0.0 → 2.1.0); the APP config-contract
hash was re-baked accordingly (`sig_benign_midcap_v1`, the baselined alpha,
does not depend on `kyle_lambda_60s`, so the trade path / P&L pins are
unaffected). A stress test drives near-constant large `Δq` and shows the
sum-of-products estimator is measurably (>10×) less accurate than welford
against an exact-rational OLS reference, while welford is near-exact
(`tests/sensors/test_kyle_lambda_60s.py`).

**Evidence:** `src/feelies/sensors/impl/kyle_lambda_60s.py`,
`platform.yaml:363-389`, `tests/sensors/test_kyle_lambda_60s.py`.

---

## F2 — inconsistent Welford robustness across the three variance sensors (Medium) — FIXED

**Finding.** Three sliding-window Welford variance implementations existed with
three different levels of drift protection: `horizon_windowed` (3P-4) had a
clamp `M2 ≥ 0` **and** an exact recompute-from-window on drift;
`liquidity_stress_score._welford_push` clamped only; `spread_z_30d` did
**neither** — it subtracted from `M2` on eviction with no internal clamp, so a
cancellation-induced negative `M2` could persist into subsequent adds (masked
only at read via `max(0.0, var)`).

**Remediation.** Gave both `spread_z_30d` and `liquidity_stress_score` the same
clamp + exact recompute-from-window guard as `horizon_windowed`. The guard only
fires when `M2 < 0` (a pure float-cancellation artifact), which never occurs on
well-conditioned windows — so the emitted streams (and the Level-4 hash /
locked vectors) are **byte-identical**, verified. Added tests for the recompute
helper and a long-run stability invariant.

**Evidence:** `src/feelies/sensors/impl/spread_z_30d.py`,
`src/feelies/sensors/impl/liquidity_stress_score.py`,
`tests/sensors/test_spread_z_30d.py`.

---

## F3 — `realized_vol_30s` computes centered std, not uncentered RV (Low) — FIXED

**Finding.** The sensor returned the mean-subtracted Bessel-corrected sample std
`√(Var(r)) = √(E[r²] − E[r]²)`. Canonical realized volatility
(Andersen–Bollerslev) is the **uncentered** second moment — it does *not*
subtract the drift. For HF returns `E[r] ≈ 0` so they nearly coincide, but under
sustained intraday drift they diverge (the uncentered form correctly includes
the directional component). The `sensor_id` implies RV; the behaviour was
centered std.

**Remediation.** Added an opt-in `centered: bool = True` parameter. The default
preserves the legacy centered behaviour exactly (byte-identical; Level-4 hash
unchanged). `centered=False` selects the uncentered per-return RMS
`√(M2/n + mean²)` (the Welford identity `Σr² = M2 + n·mean²`), which stays on
the same per-return scale as the centered std. Docstring sharpened on the
distinction. No shipped alpha needs the uncentered form, so `platform.yaml` is
unchanged.

**Evidence:** `src/feelies/sensors/impl/realized_vol_30s.py`,
`tests/sensors/test_realized_vol_30s.py`.

---

## F4 — `ofi_ewma` time-decay weights a flow like a level (Low) — FIXED (documentation)

**Finding.** `ofi_t` is a *flow* (signed increment per quote), but the sensor
EWMA-*smooths* it. With event-time decay `α_t = 1 − exp(−dt/τ)` the weighting is
inverted from a pressure measure's intuition: during dense bursts `α_t → 0`
(each event under-weighted); after a gap `α_t → 1` (a single event dominates).

**Remediation (documentation only — deliberately no behavior change).** The
smoothing is a *legitimate* responsiveness filter and the correct input for a
regime/gate "is imbalance currently one-sided?" view; changing it would break
the sensor's parity lock and is not clearly better. The platform already ships
the principled alternative for permanent-impact (KYLE) hypotheses — `ofi_raw`
(per-event, unsmoothed) with a windowed `sum` reducer (`ofi_integrated`), which
counts each event exactly once. The fix makes this flow-vs-level tradeoff and
the "use `ofi_integrated` for KYLE" guidance explicit in the docstring, so
authors consume the right OFI aggregate for the mechanism they model.

**Evidence:** `src/feelies/sensors/impl/ofi_ewma.py` (docstring).

---

## F5 — `vpin_50bucket` volume-spill loop unbounded in principle (Low) — FIXED

**Finding.** The `while remaining > 0` fill loop was `O(size / bucket_volume)` —
a block/sweep print (e.g. 1e6 shares into a 5000-share bucket) cost ~200
iterations in one `update()`, breaching the per-sensor latency budget on that
event.

**Remediation.** Rewrote the fill as O(1) in the trade size. Because the
tick-rule `side` is constant within a single `update()`, every *fully-filled*
spanned bucket is 100 %-one-sided ⇒ imbalance exactly 1.0; so the middle run of
whole buckets is batched (`O(min(k, window))`) instead of looped, and the
window-overwrite case (`k ≥ window`) is handled in one step with an exact
`buckets_sum` reset. On non-spanning trades (the fixture and normal markets) the
batch branch is never taken, so the emitted stream is **byte-identical** to the
loop — the locked `vpin_50bucket.jsonl` vector passes unchanged. New tests lock
the block-trade path against a from-scratch naive-loop reference.

**Evidence:** `src/feelies/sensors/impl/vpin_50bucket.py`,
`tests/sensors/test_vpin_50bucket.py`.

---

## Verified correct (spot-checked, not merely assumed)

- **`ofi_ewma` / `ofi_raw` OFI signs** — Cont–Kukanov–Stoikov (2014) term-by-term.
- **`micro_price`** — Stoikov weighting (each side's price × opposite side's size).
- **`kyle_lambda_60s`** — causal alignment is causal (no lookahead); the welford
  and sum-of-products slopes are algebraically identical (`λ = C/M2 = numer/denom`).
- **`structural_break_score`** — Page-Hinkley `max(0, ·)` is the canonical
  reflected-random-walk form; Kahan-compensated sum (best numerical hygiene in
  the layer).
- **`snr_drift_diffusion`** — closed-form `(1−λ)^n` multi-bar update is O(1)
  across gaps.
- **`hawkes_intensity`** — `_decay_to` guards same-instant and backwards events;
  `intensity_ratio` ε-guarded.

## Performance summary

Every sensor is **O(1) amortized per event** after F5, with memory bounded per
`(sensor, symbol)` by window length. Adjacent note (not a sensor, but on the
sensor-reading path): `HorizonAggregator._latest_warm_reading_ns_at_or_before`
falls back to an O(buffers × buffer_len) scan on a `_last_reading_ns` cache
miss — usually cached; left as-is (out of scope for this sensor review).
