<!--
  File:   docs/research/prompt_pack_00e_strength_rider_and_thread.md
  Status: Track A rider NORMATIVE for Tasks 7/9/10; Track B thread
          PROPOSED (separate, gated platform thread — not part of this
          pack's alpha delivery). Task FQ-4, 2026-07-07. Resolves OQ-1
          of docs/research/prompt_pack_00_architecture_verification.md.
  Owner:  microstructure-alpha (Track A) / system-architect +
          signals-layer (Track B); prompt-pack Task FQ-4, Phase A.
-->

# Prompt-pack Task FQ-4 — `Signal.strength`: in-pack rider and separate-thread spec

## Verified consumer map (what raw `strength` actually touches)

| Consumer | Behavior with out-of-range strength | Citation |
|---|---|---|
| `BudgetBasedSizer.compute_target_quantity` | **Already clamps** to `[0,1]` (audit R-8) before sizing — conviction can never amplify exposure beyond full allocation. Incidental: `min(1.0, max(0.0, nan))` evaluates to `0.0` under CPython comparison semantics (argument order), so NaN sizes to zero here — safe by accident, not by contract. | `risk/position_sizer.py:94-101` |
| `SignalArbitrator.arbitrate` | **Raw, unclamped**: FLAT pick by `-strength`, composite ranking by `edge_estimate_bps × strength`, dead-zone test on the same product. NaN poisons the sort keys (all comparisons False → order-dependent winner). | `alpha/arbitration.py:72-83` |
| `CrossSectionalRanker` (PORTFOLIO layer) | **Raw, unclamped**: `raw = sign × strength × edge_estimate_bps` at all three scoring sites; NaN propagates into weights. | `composition/cross_sectional.py:293, 438, 513` |
| `EdgeWeightedSizer` | Does not consume `strength` at all. | `risk/edge_weighted_sizer.py:1-11` |
| `HorizonSignalEngine` | Pass-through; no validation post-`evaluate`. | `signals/horizon_engine.py:542-546` |

**Load-bearing finding (changes the Track-B parity answer in advance):**
the `[0,1]` contract is violated **by design** in shipped alphas.
`sig_benign_midcap_v1` uses convex strength scaling
`min(1.0 + (norm − 1.0)**1.2, strength_cap)` with `strength_cap`
default **2.0** (declared range 1.0–4.0) — deliberately emitting
strength > 1 above the old saturation point
(`alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml:88-95,
215-224`). `_paper_smoke_v1` caps at 2.0 (`paper_smoke_v1.alpha.yaml:82`).
The other shipped SIGNAL alphas are bounded ≤ 1 by construction
(template `:170`; kyle_drift `:179`; hawkes_burst `:182`; moc_imbalance
`:212`; inventory_revert `:267` — ratio of a capped numerator to its own
cap). Worse for parity: the locked `reference_alpha_signal_fires`
baseline drives `sig_benign_midcap_v1` at `ofi_ewma_zscore = 2.0` with
default params (`entry_threshold_z = 0.8`), producing strength
`= min(1 + 0.25^1.2, 2.0) ≈ 1.1895 > 1`, and the stream hash folds in
`{s.strength:.6f}`
(`tests/determinism/test_reference_alpha_signal_fires_replay.py:26-32,
53-55`; hash line `tests/determinism/test_signal_replay.py:171-187`).
**An engine-level clamp-to-1.0 would therefore change a shipped alpha's
emissions and break a locked parity baseline.** This is exactly what the
Track-B mandatory parity-impact assessment exists to catch; the answer
is already known to be positive.

---

## TRACK A — In-pack rider (NORMATIVE; Tasks 7, 9, 10 adopt verbatim)

> **Strength-bounds rider (FQ-4).** The new alpha guarantees its own
> emissions by construction: `evaluate()` computes `strength` via an
> explicit bounded form — the template's `min(x, 1.0)` pattern
> (`alphas/_template/template_signal.alpha.yaml:170`) with
> non-negativity guaranteed structurally (e.g. `abs()` numerator over a
> positive denominator) or an explicit `max(0.0, ·)` clamp — so emitted
> `strength ∈ [0, 1]` for every reachable input. The convex
> above-saturation scaling used by `sig_benign_midcap_v1`
> (strength > 1 by design) is NOT available to this candidate. The
> Task-9 test plan gains: (i) a unit test asserting emitted
> `strength ∈ [0, 1]` across the full declared parameter ranges (min
> and max of every `parameters:` entry, not just defaults); (ii) a
> Hypothesis property test driving snapshot values adversarially (NaN,
> ±inf, extreme z-scores, missing keys) and asserting the alpha either
> returns `None` or emits in-range `strength` and non-negative, finite
> `edge_estimate_bps`. Scope note: Phase-B evidence runs are
> single-alpha configs, so malformed strengths from OTHER alphas cannot
> reach arbitration in this pack — defensive modeling of that case is
> explicitly out of scope for the candidate design (and the default
> sizing path is independently clamped, `risk/position_sizer.py:94-101`).

---

## TRACK B — Separate-thread spec (PROPOSED; gated; NOT this pack)

**Thread: engine-level `Signal.strength` normalization (Inv-11
fail-safe semantics).** No code in this pack.

**Hypothesis of the defect class.** `strength` is a documented-but-
unenforced contract (drift D10). The exposure path through the default
sizer is already defended (R-8 clamp), so the residual defect class is
(a) **decision corruption**: NaN/out-of-range strength silently
reweights multi-alpha arbitration (`edge × strength` composite and
FLAT pick) and PORTFOLIO cross-sectional scores, with NaN additionally
making the arbitration winner order-dependent; and (b) **contract
ambiguity**: shipped alphas deliberately emit strength ∈ [0, cap]
(cap ≤ 4.0), so consumers cannot know whether > 1 is a defect or a
conviction super-weight. The engine currently publishes whatever
`evaluate()` returns.

**Semantics (pre-registered, Inv-11: resolution never increases
exposure):**

| Emitted strength | Action | Rationale |
|---|---|---|
| NaN | **Drop the signal** (treat as `None`) + structured WARN (`alert_name="signal_strength_invalid"`, context: strategy_id, symbol, boundary, raw value) | NaN corrupts every downstream comparison; dropping an entry signal only reduces exposure |
| < 0 | **Drop** + WARN | A negative conviction is a direction contradiction, not a scale; reinterpreting it (e.g. flipping direction) would *create* exposure |
| > 1 | **Clamp to 1.0** + WARN | Clamping down bounds exposure and restores the documented scale; silently passing through does not |
| ∈ [0, 1] | Pass through unchanged | — |
| +inf | Falls under "> 1" → clamp + WARN | — |

FLAT signals: apply the same table (a FLAT is exit-direction; dropping
a NaN-strength FLAT must NOT suppress exits — FLAT with invalid
strength is normalized to strength 0.0 and kept, since FLAT semantics
do not scale exposure; spell this out in the implementation tests).

**Enforcement point — decision: `HorizonSignalEngine` post-evaluate
normalization** (immediately after `registered.signal.evaluate(...)`
returns, before publish — `signals/horizon_engine.py:542-546`), NOT
`Signal` construction-time validation. Tradeoffs, per the constraints:

- Construction-time validation (`__post_init__` on the frozen dataclass,
  `core/events.py:207-262`) touches a core event constructed by every
  producer *and by replay/test fixtures*; any fixture that builds a
  probe `Signal` with strength > 1 (several do, deliberately) would
  throw or mutate at construction, carrying broad locked-parity-baseline
  risk and violating the "frozen core contracts" session constraint.
- Engine-level normalization is layer-local (SIGNAL layer, one call
  site), leaves the event type inert, does not affect PORTFOLIO-layer
  producers or hand-built fixture Signals, and is bypassable by nothing
  on the production SIGNAL path (the engine is the sole production
  publisher of SIGNAL-layer Signals — one publish per (alpha, symbol,
  boundary), `horizon_engine.py:342-345, 592-593`).
- Residual gap to record in the thread: PORTFOLIO-layer signals and the
  arbitration path for any non-engine producer are not covered by
  engine-level normalization; the spec should state whether
  `CrossSectionalRanker` gets its own guard or relies on upstream.

**Parity-impact assessment (REQUIRED before implementation approval)**
— plan, with the part already answered:

1. Static: grep all `alphas/**.alpha.yaml` strength expressions and all
   test fixtures constructing `Signal(strength=...)` for values/forms
   that can exceed [0,1]. *Already known positive:*
   `sig_benign_midcap_v1` (cap 2.0 by design), `_paper_smoke_v1`
   (cap 2.0), and the locked `reference_alpha_signal_fires` baseline
   embeds strength ≈ 1.1895 in its hash.
2. Targeted replay: run `tests/determinism/` with the proposed
   normalization active; enumerate which locked baselines move.
   *Predicted:* `reference_alpha_signal_fires` moves (hash embeds
   `strength:.6f`); `level2_signal` (empty stream) does not;
   `signal_fires` uses a probe strength — verify.
3. Behavioral: quantify the effect of clamping on
   `sig_benign_midcap_v1` sizing/arbitration (none via BudgetBasedSizer
   — already clamped; ranker weight changes only in multi-alpha
   PORTFOLIO configs).
4. Decision gate the assessment forces: either (a) re-pin the moved
   baselines under architectural review (baselines are immutable
   without it), and bump `sig_benign_midcap_v1`'s version with its
   convex-strength intent re-expressed inside [0,1] (e.g. rescale by
   `1/strength_cap`), or (b) amend the documented contract to
   "strength ∈ [0, declared cap]" and make the engine clamp at the
   declared cap instead of 1.0. The thread must pick one explicitly;
   the pre-registered default is (a) — restore the [0,1] contract.

**Test list (thread's own):** unit tests for each semantics row
(NaN/negative drop + WARN payload schema; >1 and +inf clamp + WARN;
in-range passthrough byte-identical); FLAT-with-invalid-strength kept
at 0.0 (exit not suppressed — Inv-11); determinism test that WARN
emission does not perturb sequence allocation of the surviving stream;
parity re-pin (if option (a)) in the same commit with manifest
fingerprint update and rationale; regression test that
`BudgetBasedSizer`'s R-8 clamp remains (defense in depth, not
replaced); property test at the engine boundary mirroring the Track-A
Hypothesis test.

**One concrete next action:** run assessment step 2 — a branch-local
replay of `tests/determinism/` with a 10-line prototype of the
post-evaluate normalization — and attach the list of moved baselines to
the thread ticket, so the (a)/(b) contract decision is made on measured
impact rather than the static prediction above.

---

**OQ-1 disposition discharged:** Track A rider is NORMATIVE for Tasks
7/9/10; Track B is PROPOSED for independent scheduling and is NOT a
dependency of any pack task.
