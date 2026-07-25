# Stage-0 Residual Measurement — Report

**Date:** 2026-07-25
**Pre-registration:** [`stage0_residual_preregistration.md`](stage0_residual_preregistration.md) (commit `5019a62`, committed before any outcome data was touched — Inv-2)
**Design:** `dual_permission_actuation_design.md` rev 5 (locked)
**Scope:** Measure the residual Stage 0 leaves; decide Stage-1 GO / NO-GO / UNDERPOWERED.
**Stage 1 was not implemented. Stage-0 behavior was not modified.**

---

## 0. Verdict

> ### UNDERPOWERED — NOT A GO
> ### plus a blocking Stage-0 defect that invalidates the A/B counterfactual

Two independent findings, **either one** of which precludes a GO:

1. **Stage-0 defect (blocking).** `src/feelies/bootstrap.py:1817` constructs
   `RegisteredSignal(...)` without passing `decouple_gate_close`. The flag is
   correctly parsed by the loader and correctly consumed by the engine and both
   risk-layer authors — but it is dropped at the one seam between them. **Stage 0
   is inert end-to-end in any composed platform.** The A/B counterfactual is
   therefore invalid: both arms ran `gate_close_flat`, and their event streams are
   byte-identical. Per pre-registration §7.7 the measurement **STOPPED** here; the
   defect was **not** fixed inline. Details in §1.
2. **Independently UNDERPOWERED.** The `open ∧ safe-OFF ∧ ¬caps` subpopulation
   contains **N_sub = 1 episode** against the pre-registered floor of **N_sub ≥ 200**
   (effective tail sample ≥ 20 at α = 0.10). This finding is **robust to the
   defect** — see §3.3. Bar **B4 fails by a factor of ~200**.

Per pre-registration §8, an under-powered tail cell is **not a GO**, and per design
§3.5 a tail falsifier that cannot be powered **blocks promotion** rather than
defaulting to accept.

**This is not a shortfall.** Per design §4.2, Claim A (bounded deferral) stands
independently and Stage 0 stands alone. But note the finding here is *weaker* than
a clean NO-GO: the residual was **not measured**, so Claim B is neither supported
nor rejected on evidence. It remains unproven, which is where rev 5 already places
it.

---

## 1. Stage-0 defect (BLOCKING) — reported, not fixed

### 1.1 The defect

`src/feelies/bootstrap.py:1795–1829` registers each loaded SIGNAL alpha with the
horizon engine:

```python
engine.register(
    RegisteredSignal(
        alpha_id=module.manifest.alpha_id,
        horizon_seconds=module.horizon_seconds,
        signal=module.signal,
        params=module.params,
        gate=module.gate,
        cost_arithmetic=module.cost,
        trend_mechanism=module.trend_mechanism_enum,
        expected_half_life_seconds=module.expected_half_life_seconds,
        consumed_features=consumed_feature_ids,
        required_warm_feature_ids=warm_ids,
        # decouple_gate_close=module.decouple_gate_close   ← NEVER PASSED
    )
)
```

`RegisteredSignal.decouple_gate_close` defaults to `False`
(`src/feelies/signals/horizon_engine.py:87`). `module.decouple_gate_close` is set
correctly by the loader (`alpha/loader.py:361,415`) and is available on the
in-scope `module` object — it is simply never read here.

**Verified:**

| Check | Result |
|---|---|
| `AlphaLoader().load(spec).decouple_gate_close` | `True` |
| `manifest.safety_exit_policy` | `{'mode': 'decouple_caps_only', 'max_hold_after_safe_off': 600, 'hard_exit_age_seconds': 1800}` |
| `'decouple_gate_close' in inspect.getsource(_create_signal_layer)` | `False` |
| `RegisteredSignal` dataclass default | `False` |

### 1.2 Blast radius — all three Stage-0 legs are inert

The dropped flag is the **sole selector** for every Stage-0 behavior:

1. **Gate-close FLAT is never suppressed.** `horizon_engine.py:503` reads
   `if registered.decouple_gate_close: return` — always False, so the direct FLAT
   always publishes. The decoupling itself never engages.
2. **No `DeferralCapController` is ever built.** `bootstrap.py:2223`:
   `decoupled = [s for s in horizon_signal_engine.signals if s.decouple_gate_close]`
   → always `[]` → `return None` (line 2225). **The mandatory
   `max_hold_after_safe_off` and `hard_exit_age_seconds` ceilings never exist at
   runtime**, despite being parsed, G17 ceiling-checked at load, and recorded on the
   manifest.
3. **No `ExitComposer` is ever built.** `bootstrap.py:2166` applies the identical
   filter → `return None` (line 2168). The fail-closed error-path EXIT routing
   never exists.

### 1.3 Behavioral proof

The pre-registered A/B was run on APP 2026-06-03 — the one cell in the universe
with an open book at a safe-OFF (§3.2) — under `--inv12-stress`:

| Arm | Config | SafetyStateChange | Signal | OrderRequest | FILL |
|---|---|---|---|---|---|
| A | `mode: gate_close_flat` | 13 | 14 | 2 | 2 |
| B | `mode: decouple_caps_only`, `max_hold=600`, `hard_exit_age=1800` | 13 | 14 | 2 | 2 |

**The two timelines are byte-identical** (`armA == armB` on the full ordered event
dump). Arm B still emits the gate-close FLAT at `t=1780508401005218137` and still
exits at `t=1780508512797102619` — 111.79 s after safe-OFF, driven by the FLAT, not
by any cap. Had decoupling engaged, arm B would have (i) emitted no FLAT and
(ii) flattened at `first_safe_off + 600 s = 1780509001005218137` under
`MAX_HOLD_AFTER_SAFE_OFF` (the `min(...)` binds there; the age backstop sits later
at `1780509614296252974`).

### 1.4 Why the test suite is green over this

Every Stage-0 test exercises one side of the seam and never the join:

- `tests/signals/test_safety_state_change.py`, `tests/determinism/test_decoupled_safety_replay.py`,
  `tests/kernel/test_stage0_decouple_wiring.py` all **hand-construct**
  `RegisteredSignal(decouple_gate_close=...)` and pass it directly to the engine or
  to `_create_deferral_cap_controller` / `_create_exit_composer`.
- `tests/alpha/test_safety_exit_policy.py` asserts on
  `LoadedSignalLayerModule.decouple_gate_close` from the **loader**.

No test asserts that bootstrap **carries the loader's flag onto the
`RegisteredSignal`**. Both halves are covered; the one line joining them is not.

### 1.5 Relationship to the Stage-0 check-up

This is the same defect *class* as commit `da32627` ("Wire Stage-0 decoupling end to
end"), whose own message records: *"Because every Stage-0 test hand-constructs its
own risk authors, all six PRs passed green over a system in which the
bounded-deferral guarantee did not execute."* That audit fixed the three seams
**downstream** of the flag (B1 controller construction, B2 bridge routing, B3
revocation). It did not check the seam **upstream** of it — the predicate that
selects which alphas those authors cover. `_create_deferral_cap_controller`, added
by that commit, is itself inert for the same reason it was added.

### 1.6 Severity and direction

**Fail-safe, not fail-open.** The platform silently retains today's
`gate_close_flat` behavior — immediate flatten on gate close. There is no stranded
book and no Inv-11 violation in the dangerous direction. The concrete harms are:

- An alpha promoted to `decouple_caps_only` **silently gets `gate_close_flat`**.
  The promotion ledger would record an authorization with no runtime effect.
- Any Stage-0 validation run (including this one) measures the baseline against
  itself and cannot detect the difference except by noticing the streams are
  identical.

**No fix was applied**, per the brief and pre-registration §7.7. §7 records the
recommended remediation for a separate change.

---

## 2. What ran, and what the defect invalidates

| Pre-registered step | Status |
|---|---|
| §4.1 A/B counterfactual (same log, two modes) | **INVALID** — arms byte-identical (§1.3) |
| §4.2 Modeled fills under `--inv12-stress` | Ran; applied to both arms |
| §4.3 Subpopulation sizing | **VALID** (see §3.3) |
| §4.5 Purged CPCV estimation | **NOT RUN** — requires N_sub ≥ 10 for `n_groups=10`; N_sub = 1 |
| §6.1 Population (a) wrong holds | **NOT ESTIMABLE** |
| §6.2 Population (b) + hindsight ceiling | **NOT ESTIMABLE** |
| §6.3 Diagnostics | Partially measurable; see §5 |

A control run **without** `--inv12-stress` reproduced the identical zero-entry
result, confirming the stress flag is not implicated (the alpha's `cost_floor_bps`
is a static param, upstream of any stressed cost).

---

## 3. Population sizing — the power finding

### 3.1 Census

`sig_kyle_drift_v1`, arm A (baseline), all replayable cells, `--inv12-stress`:

| Symbol | Sessions | Signals | Directional entries | Gate-close (`SafetyStateChange`) | Fills |
|---|---|---|---|---|---|
| APP | 14 | 229 | **1** | 228 | 2 |
| AAPL | 2 (03-13, 04-09) | 16 | 0 | 16 | 0 |
| SNDU | 1 (05-01) | 12 | 0 | 12 | 0 |
| **Total** | **17** | **257** | **1** | **256** | **2** |

The 10 remaining replayable cells (AAPL 03-26/04-08/04-28, SNDU 04-30, INTC 05-04,
SPY ×5 — the large ones, 1.4–5.3 M events each) were still replaying at the time of
writing. They are baseline-arm only and were left running after the defect stopped
the A/B; the census is therefore **17 of 27 cells**. Even if every remaining cell
produced an entry that coincided with a safe-OFF, N_sub ≤ 11 against a floor of 200,
so the order of magnitude is not in question.

### 3.2 The funnel

Clause-by-clause census of the entry conjunction over every
`HorizonFeatureSnapshot` (APP, two representative sessions):

| Stage | APP 2026-06-01 | APP 2026-03-23 |
|---|---|---|
| Snapshots | 1092 | 1092 |
| Bindings present | 1087 | 1085 |
| `kyle_lambda_60s_percentile ≥ 0.7` | 426 | 385 |
| **`|ofi_ewma| ≥ 0.5`** | **3** | **1** |
| `edge_bps > cost_floor_bps (6.5)` | 3 | 1 |
| max observed `|ofi_ewma|` | 0.697 | 1.026 |

**`|ofi_ewma| ≥ 0.5` is the binding constraint** — it admits ~0.1–0.3 % of
snapshots. Of the few that pass, most do not coincide with gate-ON, which is why
257 signals across 17 sessions contain exactly **one** directional entry.

### 3.3 N_sub = 1

The subpopulation is `open ∧ safe-OFF ∧ ¬caps`. Across 17 sessions there were **256
gate-close safety events** but only **one** occurred with an open book:

> **APP 2026-06-03.** LONG 50 filled @ 567.17 (`t=1780507814296252974`), first
> `safe→OFF` 586.71 s later (`t=1780508401005218137`, `reason=clean_transition`),
> exit filled @ 568.06. Gross **+15.69 bps**.

| | Pre-registered floor | Observed | Ratio |
|---|---|---|---|
| N_sub | ≥ 200 | **1** | 0.5 % |
| Effective tail sample ⌊0.10 · N_sub⌋ | ≥ 20 | **0** | — |

**Bar B4 fails.** With `effective_tail_sample = 0`, `conditional_cvar` is undefined
and `CPCVConfig(n_groups=10, …)` cannot even partition the series.

**Robustness to the defect.** N_sub is determined by *entry* behavior and gate
transitions — the baseline arm, which ran correctly. The defect changes only what
happens *after* a safe-OFF with an open book. A working arm B could shift N_sub
slightly (a longer hold can occlude a later entry), but it cannot manufacture
entries: the alpha entered once in 17 sessions, and the deficit is ~200×. **The
UNDERPOWERED verdict stands independently of the defect.**

### 3.4 Secondary pilot — `sig_moc_imbalance_v1` (as pre-declared)

Pre-registration §1.2 declared this alpha expected-underpowered in advance. It is,
and by a wider margin than predicted:

- **Only one date in the frozen universe has an `MOC_IMBALANCE` window** —
  2026-03-26. The reference calendar (`storage/reference/event_calendar/`) carries
  MOC rows on just three dates overall (2026-01-15, 03-24, 03-26); 2026-04-02 has
  `ALGO_CLOCK` rows only. Every other universe date has **no calendar file at all**.
- Both qualifying cells were run:

| Cell | Signals | Directional | Fills |
|---|---|---|---|
| APP 2026-03-26 | 1 (FLAT) | 0 | 0 |
| AAPL 2026-03-26 | 1 (FLAT) | 0 | 0 |

**N_sub = 0.** This confirms — rather than discovers — the exclusion recorded in
`prompt_pack_07_program_retrospective.md` §4.2 (single-window SCHEDULED_FLOW
mechanisms, 5× short of the ≥ 100 floor). Per §1.2 this is **not evidence either
way** and is excluded from the verdict arithmetic.

---

## 4. The two populations — not estimable

### 4.1 (a) WRONG HOLDS

**Not estimable.** Requires the arm-B counterfactual, which the defect invalidated
(§1.3). Even with a working arm B, N_sub = 1 supports no conditional left tail:
CVaR₁₀ on a single observation is that observation.

### 4.2 (b) MISSED EARLY STORY-DEATH

**Not estimable**, and therefore **the hindsight ceiling is undefined**. This is the
only population that motivates Stage 1 (design §2.3), so with it unmeasured Claim B
has received no test. Bars **B1** and **B2** cannot be evaluated.

### 4.3 The single episode — anecdote, explicitly not evidence

Recorded for completeness only. At the safe-OFF:

| Gate `off_condition` clause | Value at safe-OFF | Fired? |
|---|---|---|
| `spread_z_30d > 2.0` | −0.625 | no |
| `realized_vol_30s_zscore > 3.5` | −1.478 | no |
| `P(normal) < 0.4` | — | **yes** (by elimination) |

The gate closed on **regime collapse**, not toxicity or vol breakout. At that moment
`kyle_lambda_60s_percentile = 0.918` and `zscore = 1.705` — the mechanism's own λ
signature was still *elevated* — while `ofi_ewma` had decayed from +0.502 at entry
to −0.122, i.e. the OFI confirmation had inverted.

That pattern is exactly the §2.1 tension a powered study would test: the gate's
"weather" reading and the alpha's "still looks holdable" reading diverging off the
same latent state. **With n = 1 this is an anecdote.** It is reported because the
pre-registration (§6.1) asked for the per-clause decomposition; it must not be read
as a finding in either direction.

The episode's gross **+15.69 bps** also sits below the **19.5 bps** Inv-12-stressed
round-trip cost (13 bps disclosed × 1.5). Again n = 1 — noted, not concluded.

---

## 5. Mandatory diagnostics (§6.3)

| Diagnostic | Result |
|---|---|
| **Deadline-binding share** (B3) | **Not measurable.** No `DeferralCapController` is ever constructed (§1.2), so no deadline can bind. Zero `MAX_HOLD_AFTER_SAFE_OFF` / `HARD_EXIT_AGE` / `SESSION_FLATTEN` orders were emitted in any run. |
| **Event-time vs wall-clock gap** | **Not measurable** for the same reason; no quote-freeze episode could reach `session_flatten` via the cap. |
| **Turnover delta** (Inv-12) | Observed ratio **1.000** (2 round-trip legs in both arms) — but this is an artifact of the arms being identical, **not** evidence that deferral is turnover-neutral. |
| **N_sub / effective tail sample** | 1 / 0 (§3.3) |

---

## 6. Verdict against the pre-registered bar

| Bar | Threshold | Observed | Result |
|---|---|---|---|
| **B1** ceiling magnitude | ≥ 20 bps/episode | undefined | **not evaluable** |
| **B2** population dominance | (b) ≥ 2 × \|(a)\| | undefined | **not evaluable** |
| **B3** deadline-binding share | ≥ 30 % | 0 % (cap never built) | **not evaluable** |
| **B4** power | effective tail ≥ 20 | **0** | **FAIL** |

### **UNDERPOWERED — NOT A GO.**

Per pre-registration §8 and design §3.5, an under-powered cell FAILs rather than
default-accepting; the fallback is `gate_close_flat`, which — by virtue of the
defect — is what the platform is already doing.

No pre-registered value was moved to reach this result. §7 of the pre-registration
(anti-fitting commitments) was honored in full: the config, α, horizon, universe,
and bars are as committed in `5019a62`.

---

## 7. What would be needed

### 7.1 Precondition — fix the defect first

Any re-run is meaningless until `bootstrap.py:1817` passes
`decouple_gate_close=module.decouple_gate_close`. Recommended alongside it (**not
done here**):

1. An integration test asserting that a `decouple_caps_only` spec loaded through
   `build_platform` yields `engine.signals[i].decouple_gate_close is True` **and** a
   non-`None` `DeferralCapController` and `ExitComposer` — closing the seam class
   that `da32627` and this defect share.
2. A promotion-time assertion that an alpha authorized for `decouple_caps_only` has
   a live deferral cap, so the ledger cannot record an authorization with no
   runtime effect.

### 7.2 Data and universe breadth to power the gate

Observed entry rate: **1 directional entry per 17 symbol-sessions**, and the single
entry did coincide with a safe-OFF. Taking that as an upper bound on the
episode yield (~0.06 subpopulation episodes per symbol-session):

| Requirement | Arithmetic |
|---|---|
| N_sub ≥ 200 (α = 0.10, tail ≥ 20) | ≈ **3,400 symbol-sessions** at the observed rate |
| vs. available | 27 replayable — a **~125×** shortfall |

Three routes, in order of leverage:

1. **Universe breadth, not session depth.** The deficit is not fixable by adding
   sessions to APP. It needs a wide cross-section — order 100+ symbols × 30+
   sessions — because the entry conjunction is rare per symbol-session.
2. **Re-examine the entry conjunction.** `|ofi_ewma| ≥ 0.5` admits ~0.1–0.3 % of
   snapshots and is the binding clause. If that threshold is mis-scaled relative to
   the sensor's actual normalization, the alpha is far more inert than intended, and
   *no* Stage-0 study on it can be powered. This is worth a separate look — it is
   an alpha-calibration question, out of scope here.
3. **A denser-firing pilot.** Any Stage-0 residual study needs an alpha that both
   holds positions and sees gate-OFFs while open. None of the five alphas in
   `alphas/` is known to clear that on the current cache; the short-half-life
   families are excluded by §2.8 in any case.

### 7.3 Data-availability findings (incidental)

- **4 of 31 cached symbol-sessions are unreplayable**: `DiskEventCache.exists()`
  returns `False` on `event_schema_hash` mismatch, so AAPL 2026-03-18, MSFT
  2026-04-08, NVDA 2026-04-08 and TSLA 2024-12-20 (schema hashes `41de152…` /
  `60bde3f…` vs current `8ff5342…`) silently present as cache misses. Effective
  universe **27**, not 31.
- **5 further cached dates are empty** (`event_count == 0`): AAPL 03-14, APP 03-21 /
  03-22, SPY 05-10, plus SPY 05-09 (2 events, no quotes).

---

## 8. Reproduction

```bash
uv sync --all-extras
```

Arm A (baseline) and the census used `configs/bt_sig_kyle_drift.yaml`; arm B used a
copy of the alpha spec with the pre-registered `safety_exit_policy` block appended
(`mode: decouple_caps_only`, `max_hold_after_safe_off: 600`,
`hard_exit_age_seconds: 1800`). Both were driven through
`feelies.harness.backtest_runner._run_backtest_phases_2_7` on
`load_event_log_from_disk_cache`, with `PYTHONHASHSEED=0` and `--inv12-stress`,
capturing the returned `BusRecorder`. The measurement scripts are scratch-only; no
Stage-0 source file was modified.

---

## Document control

| Field | Value |
|---|---|
| Verdict | **UNDERPOWERED — NOT A GO**, plus a blocking Stage-0 defect |
| Blocking defect | `src/feelies/bootstrap.py:1817` drops `decouple_gate_close` |
| Primary pilot | `sig_kyle_drift_v1` — N_sub = 1 (floor 200) |
| Secondary pilot | `sig_moc_imbalance_v1` — N_sub = 0 (pre-declared underpowered) |
| Bars evaluated | B4 FAIL; B1–B3 not evaluable |
| Stage 1 | **Not implemented.** Claim B untested, remains unproven (design §4.2) |
| Stage-0 behavior | **Unmodified.** Defect reported, not fixed |
