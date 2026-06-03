# P1 follow-up proposals — P1-4, P1-5, P1-8 (decision-ready)

Companion to `sensor_horizon_feature_audit_2026-06-02.md`. These are the
P1 findings that changed **sensor-level outputs / boundaries** and therefore
needed an explicit decision (version bump, calibration value, or config
policy) before implementation — they are *not* silent code changes.

For each: the precise change, why it splits into a parity-safe part and a
value-changing part, the locked-vector / backtest impact, and the guarding
test. (Implementation status may have changed since this proposal; see the
audit document for the current state.)

---

## P1-4 — Hawkes `α/β = 8.0` and uncalibrated intensity

**Finding.** `hawkes_intensity` defaults `α=0.4, β=0.05` ⇒ `α/β = 8.0`,
emitted verbatim as the 4th tuple component while the docstring asserts
`α/β < 1` for stability (`hawkes_intensity.py:61-63,111`). Platform sets
`warm_trades_per_side = 3` (`platform.yaml:280`) — statistically thin.

**Key clarification.** This sensor is an *additive-impulse EWMA intensity
tracker*, not a fitted Hawkes process: the impulse never feeds back into
arrival generation, so `α/β` does **not** carry the true branching-ratio
stability meaning. The component is **mislabeled**, not (necessarily)
mis-valued. `β` does have a real meaning: the decay half-life is
`ln 2 / β = 13.9 s` at `β=0.05`.

**Proposed split:**

- **P1-4a (parity-safe, do now if approved):** relabel the 4th component
  in the docstring/skill from "branching ratio (stability)" to
  `impulse_decay_ratio` with an explicit note that it is *not* a stability
  metric; document `half_life = ln2/β`. Raise the **default**
  `warm_trades_per_side` to a meaningful count (proposal: **10**). *No
  emitted value changes* (the reference replay vector passes explicit
  params, and the component value 8.0 is unchanged) → **no rebaseline**.
- **P1-4b (value-changing, needs data):** choose `β` so the decay
  half-life lands in the HAWKES envelope (5–120 s) — e.g. `β ≈ 0.023` for
  a ~30 s half-life — and `α` so warm-state `λ` is O(trade-rate). These
  must be **calibrated** (MLE on inter-trade times per symbol), not
  guessed. Ship as a **new `sensor_version` 1.3.0** (keep 1.2.0 for
  replay parity), wire its z + imbalance features under new ids.

**Decision needed:** approve P1-4a now? For P1-4b, confirm we calibrate
from cached data (I can add a `scripts/calibrate_hawkes.py` MLE fitter)
rather than pin a value.

**Guarding test:** assert the emitted decay ratio is documented-non-stability;
property test that `λ` half-life matches `ln2/β` within tolerance.

---

## P1-5 — Kyle-λ `dp`/`dq` time misalignment

**Finding.** `dp = mid_now − mid_at_prev_trade` (the interval *before* the
current trade) is regressed on the *current* trade's `dq`
(`kyle_lambda_60s.py:135-136,158`). The current trade's price impact lands
in the *next* sample's `dp`, so the slope measures *past drift vs current
flow* (≈ flow-autocorrelation) rather than contemporaneous price impact.

**Causality constraint.** The "correct" Kyle pairing — `dq_t` with the
price change it *causes*, `[t, t+1)` — needs the next trade's mid, which is
lookahead at emission time (Inv-6 violation). So we cannot emit the
contemporaneous-impact λ at trade `t`.

**Proposed fix (causal):** pair the realized interval price change
`dp_[t−1,t)` with the flow that occurred **during that interval**,
`dq_{t−1}` (the trade at `t−1` that drove it) — i.e. lag `dq` by one trade.
This is causal (uses only past data) and aligns the regressor with the
price move it explains. Concretely: on trade `t`, append the sample
`(dp = mid_now − mid_prev, dq = signed_size_of_trade_{t−1})` instead of the
current trade's size.

**Why it needs sign-off (not a silent fix):** it is a *semantic* change to
a sensor whose vectors are explicitly locked ("do not refactor" comment at
`kyle_lambda_60s.py:170`). Ship as **new `sensor_version` 1.3.0**; validate
with `scripts/sensor_feature_ic.py` that the re-aligned λ z-score has
higher |RankIC| vs forward return than the current one. If IC does **not**
improve, keep the current estimator and instead just **document** it as a
flow-autocorrelation statistic (the report's alternative).

**Decision needed:** (a) proceed with the lag-one re-aligned variant as a
new version, gated on an IC win; or (b) keep current and relabel as
flow-autocorr.

**Guarding test:** golden vector for the new version; a unit test that a
trending synthetic tape yields the expected sign under the new alignment
(and a different sign/magnitude than the old, proving the change bites).

---

## P1-8 — Session-open anchor / first-bar bias

**Finding.** `platform.yaml:184` leaves `session_open_ns` null, so the
scheduler binds it to the **first event** (`horizon_scheduler.py:174-183`).
The first bucket of the day is then truncated/first-event-anchored, biasing
the first snapshot, and boundaries aren't aligned to the RTH open.

**Proposed fix (config policy):** when `session_kind == RTH` and
`session_open_ns` is unset, bootstrap computes the session date's **09:30
America/New_York** in ns and binds it (DST-correct via the zoneinfo the
platform already uses). The session date is taken from the first event's
date (or an explicit `session_date` config field).

**Decision needed:** confirm the anchor policy = **09:30 ET RTH open** for
`US_EQUITY` (vs. e.g. first-quote, or a per-market calendar lookup). If
multi-market support is wanted, source the open from the market calendar
instead of a hardcoded 09:30 ET.

**Parity impact:** changes `HorizonTick` boundary indices/timestamps for
real runs → the **APP 2026-03-26 backtest baseline re-baselines**. The
determinism vectors pin their own `SESSION_OPEN_NS`, so locked Inv-5 hashes
are unaffected.

**Guarding test:** with `session_open_ns` unset + a synthetic pre-open
event, assert the first RTH boundary lands exactly on 09:30 ET and the
first bucket is full (not truncated).

---

## Summary of decisions requested

| Item | Parity-safe part (do now) | Value-changing part (needs decision) |
|---|---|---|
| P1-4 | relabel component + raise `warm_trades_per_side` default to 10 | calibrate `α,β` from data → new `sensor_version` |
| P1-5 | — | lag-one re-aligned λ as new version, **gated on an IC win** vs current |
| P1-8 | — | bind RTH open = 09:30 ET → re-baseline APP backtest |

I can land the P1-4a parity-safe slice immediately on approval, add the
Hawkes MLE calibration script for P1-4b, and run `sensor_feature_ic.py`
to settle the P1-5 go/no-go — all without guessing quant values.
