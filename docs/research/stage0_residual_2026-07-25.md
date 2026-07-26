# Stage-0 Residual Measurement — Report

**Date:** 2026-07-25
**Pre-registration:** [`stage0_residual_preregistration.md`](stage0_residual_preregistration.md) (commit `5019a62`, committed before any outcome data was touched — Inv-2)
**Design:** `dual_permission_actuation_design.md` rev 5 (locked)
**Scope:** Measure the residual Stage 0 leaves; decide Stage-1 GO / NO-GO / UNDERPOWERED.
**Stage 1 was not implemented.** Stage-0 behavior was not modified *during the
measurement*. Both defects found (§1.1, §1.7) were fixed afterwards on explicit
instruction; each fix restores the documented Stage-0 contract rather than changing
it.

---

## 0. Verdict

> ### UNDERPOWERED — NOT A GO
> ### plus two Stage-0 defects that invalidated the A/B counterfactual

Three findings, **any one** of which precludes a GO:

1. **Stage-0 defect (blocking).** `src/feelies/bootstrap.py:1817` constructs
   `RegisteredSignal(...)` without passing `decouple_gate_close`. The flag is
   correctly parsed by the loader and correctly consumed by the engine and both
   risk-layer authors — but it is dropped at the one seam between them. **Stage 0
   is inert end-to-end in any composed platform.** The A/B counterfactual is
   therefore invalid: both arms ran `gate_close_flat`, and their event streams are
   byte-identical. Per pre-registration §7.7 the measurement **STOPPED** here; the
   defect was **not** fixed inline. Details in §1. *(Fixed later on explicit
   instruction — which then exposed defect 2 below.)*
2. **Second Stage-0 defect — FAIL-OPEN (found after fixing the first).**
   `StrategyPositionStore`, the strategy-slice book both Stage-0 authors read, is
   **never written on entry fills**: `FillAttributionLedger.record(...)` has no
   callers, so the ledger the write path is gated on is always empty. With
   decoupling live the pilot book was held **2361.6 s** against a declared **600 s**
   ceiling and was flattened by an unrelated stop author, not by any cap. The
   bounded-deferral guarantee — the load-bearing Inv-11 defense — did not execute.
   Details in §1.7. **Fixed on instruction** (§1.8): the ceiling now binds at
   `first_safe_off + 600 s` exactly, verified end to end. It also un-suppressed
   directional exits that had been silently blocked, moving a pinned acceptance
   baseline — re-pinned to the corrected value (§1.8.1).
3. **Independently UNDERPOWERED.** The `open ∧ safe-OFF ∧ ¬caps` subpopulation
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

## 1. Stage-0 defects (BLOCKING)

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

**Remediation (applied later, on request).** The one-line fix — passing
`decouple_gate_close=module.decouple_gate_close` at the registration call — plus an
integration test through the real loader→registry→bootstrap chain
(`tests/kernel/test_stage0_decouple_registration_seam.py`) was applied after this
report's measurement was complete, at the operator's explicit instruction. Applying
it **immediately exposed a second, more serious defect** — see §1.7. The fix is
verified correct in itself (arm A stays bit-identical; the gate-close FLAT is now
suppressed for a decoupled alpha), and it does **not** ship alone: §1.7 was fixed
alongside it (§1.8).

### 1.7 Second defect (FAIL-OPEN) — `StrategyPositionStore` was never written

Uncovered only once §1.1 was fixed and decoupling actually engaged. Reported first per
pre-registration §7.7, then fixed on instruction — see §1.8.

**Symptom.** With decoupling live, the pilot episode's book was held **+2361.6 s**
past its first `safe→OFF` — against a declared `max_hold_after_safe_off` of **600 s**
and a `hard_exit_age_seconds` deadline falling at **+1213 s** from that anchor. **No
`MAX_HOLD_AFTER_SAFE_OFF`, `HARD_EXIT_AGE` or `SESSION_FLATTEN` order was ever
emitted.** The position was eventually flattened by an unrelated `__stop_exit__`
author at ~4× the declared ceiling.

**Mechanism.** Both Stage-0 authors are strategy-slice-scoped by design (§3.3) and
read `StrategyPositionStore`. That store is written on fills **only** from the
multi-alpha attribution branch at `kernel/orchestrator.py:4842`, which is gated on
`self._fill_ledger.allocate_fill(...)` returning allocations.
`FillAttributionLedger.record(...)` (`alpha/fill_attribution.py:60`) has **no callers
anywhere in the codebase**, so the ledger is always empty, `allocate_fill` returns
`[]` for every unknown `order_id` (line 89–91), and the slice store is never written
for an entry fill. The `elif order.reason in EXIT_COMPOSER_EXIT_REASONS` branch does
self-attribute *composer exits*, so exits can write the store — but entries never do,
so no author ever sees the position an entry created.

**Verified on a full session in which a 50-share position opened and closed:**

| Check | Result |
|---|---|
| `cap._position_store is orch._strategy_positions` | `True` — correct object, correctly wired |
| `cap.policies['sig_kyle_drift_v1']` | `max_hold=600s, hard_age=1800s, universe=('APP',)` — correctly armed |
| `DeferralCapController._maybe_emit_exit` calls | **94,833** (the cap is attached and evaluating on every `Trade`) |
| …of which saw a non-zero position | **0** |
| `StrategyPositionStore.update` calls | **0** |

The cap is built, armed with the right ceilings, and reading the right object. The
object is simply empty, so `_maybe_emit_exit` returns at
`if position.quantity == 0` on every one of its 94,833 evaluations and
`_on_safety_state_change` never anchors an episode (`opened_at_ns` is always `None`).

**Why this is worse than §1.1.** Defect §1.1 was **fail-safe**: the platform silently
kept today's immediate flatten. With §1.1 fixed and this defect present, the
gate-close FLAT is suppressed *and* no cap can bind — exposure is **retained past the
declared ceiling with no exit author**. That directly violates the §2.6 composition
check ("No path **retains** exposure beyond the deferral ceiling when safe OFF") and
guts the Inv-11 defense §2.5 rests on: the bounded-deferral ceiling is what makes
decoupling a *delay* rather than a *removal* of today's flatten. Under this defect it
is a removal.

**Exposure today: nil, but conditional.** No alpha in `alphas/` declares a
`safety_exit_policy` block and no config sets `decouple_caps_only`, so the §1.1 fix
changes no current behavior. The hazard materializes the moment any alpha opts in.

This is the **third** instance of one defect family: a Stage-0 component that is
built, unit-tested in isolation, and inert in situ because the seam feeding it is
unconnected (§1.1 the flag; `da32627`'s B1–B3 the authors and routing; this the slice
book). A test asserting only that a component *exists* cannot catch it — the
assertion has to be that it *acts* on a real fill.

### 1.8 Defect §1.7 — fixed, and what it changed

Fixed on instruction, together with §1.1 so neither ships alone.

**Change.** `kernel/orchestrator.py` now self-attributes a **single-strategy** fill to
its own slice: the existing composer-exit branch was broadened to cover any order that
carries a `strategy_id` and is either an explicitly slice-scoped forced exit
(`_SLICE_SCOPED_FORCED_EXIT_REASONS`) or not a forced exit at all — i.e. an ordinary
signal-path entry or exit. The standalone path arbitrates a **single winner** per order
(`SignalArbitrator`), so such a fill belongs entirely to that strategy. Symbol-net
hazard exits deliberately still fall through to the proportional split.

**Verified end to end on the pilot episode.** The cap now sees the book and the ceiling
binds exactly as pre-registered:

| | before | after |
|---|---|---|
| `_maybe_emit_exit` calls that saw a non-zero position | 0 / 94,833 | **2,667** / 94,833 |
| `StrategyPositionStore.update` calls | 0 | non-zero |
| Episode anchored at first `safe→OFF` | never | **yes** (`opened=…814296252974`, `anchor=…401005218137`) |
| Deferral order emitted | none | **1 ×** `MAX_HOLD_AFTER_SAFE_OFF` at `first_safe_off + 600.1 s` |
| Hold past safe-OFF | 2361.6 s (stop author) | **610.6 s** (600 s ceiling + fill latency) |

The order fires on the first trade 72 ms after the deadline — event-time enforcement
per §2.3 — and exactly once, so the per-episode dedup holds. Attribution is **exact**:
on a single-alpha run the slice book equals the aggregate book on quantity, realized
PnL and fees.

`tests/kernel/test_fill_attribution_seam.py` drives the orchestrator's real
ack-reconciliation path (5 of its 7 tests fail without the fix; the other 2 are
negative controls). It is the assertion the family was missing — the existing Stage-0
end-to-end test hand-seeds the slice store before checking the ceiling, so it verified
the promise over a book the real fill path never filled.

#### 1.8.1 Behavioral side effect — a pinned baseline moved

Populating the slice book also un-blocks a second reader:
`standalone_signal_actionable_for_strategy` (`alpha/arbitration.py:54–55`) returns
`_signal_reduces_book(strategy_qty, direction)` whenever a signal reduces the aggregate
book. With `strategy_qty` permanently 0 that was always `False`, so **every directional
reducing exit from a standalone alpha was silently non-actionable**. Those exits now
fire when the alpha genuinely owns the exposure — which is what the function documents
("directional exits likewise require matching strategy exposure").

Consequence: `tests/acceptance/test_backtest_app_baseline.py` now fails on its pinned
net PnL — **430.85 → 363.34** on APP 2026-03-26 (gross realized 536.31 → 468.80; fees
unchanged at 105.46). Fill count and the parity hash still match. Per-alpha budgets in
`AlphaBudgetRiskWrapper` also became computable, but measured on this cell **none
bind** (zero budget REJECTs), so they are not the cause.

**Re-pinned on the owner's decision.** The old number encodes the suppressed-exit bug —
the alpha was holding positions it should have exited, which flattered PnL on this
session — so 363.34 is the corrected value. `_BASELINE_NET_PNL` is updated with the
cause recorded at the pin; `_BASELINE_FILL_COUNT` and the config hash are untouched.
This is also the re-verification that pin's own CAVEAT had been requesting: it warned
the value had not been re-checked since sensor pruning went live and could not be
confirmed in an environment without an APP/2026-03-26 cache. It has now been checked
against a cached run, and the delta is behavioral rather than pruning drift.

#### 1.8.2 Follow-ups — both closed

**The ledger is now the live attribution path.** `_track_order` calls
`FillAttributionLedger.record(...)` for every order that owns one slice — step 1 of the
ledger's own documented contract, which had **no caller at all**. Attribution now flows
through `allocate_fill`, so if cross-alpha netting is ever wired a multi-contribution
record splits the fill proportionally on its own instead of silently self-attributing a
netted fill to one strategy. Verified behaviour-neutral today: the pilot deferral
episode replays **byte-identical** to the pre-wiring run.

**The ledger gate is gone.** The attribution block is gated on
`self._strategy_positions is not None` alone. Neither surviving branch needs the ledger,
so a deployment that skipped constructing one used to lose slice attribution silently —
and with it the Stage-0 ceiling, the composer's scoping, and every per-alpha budget.

**One predicate, one rule.** `_order_owns_one_slice(order)` is the single source of
truth for slice-vs-symbol-net attribution, used both to decide which orders get a record
and which fills self-attribute when no record exists. Previously the rule lived inline
in one branch only, so record-time and fill-time could have disagreed.

**Still genuinely absent (by design, not defect).** Cross-alpha netting itself:
`aggregate_intents` (`alpha/aggregation.py`) has **no production caller**, so every order
carries exactly one `strategy_id` and records always hold a single 100% contribution. The
proportional-split machinery is therefore exercised but never multi-contribution. Wiring
netting changes how orders are built — order counts, sequences, parity hashes — and needs
its own design review; it is not a defect fix and was not attempted here.

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
| SPY | 5 | 58 | 0 | 58 | 0 |
| AAPL | 5 | 27 | 0 | 27 | 0 |
| SNDU | 2 | 15 | 0 | 15 | 0 |
| INTC | 1 | 14 | 0 | 14 | 0 |
| **Total** | **27** | **343** | **1** | **342** | **2** |

**Census is complete** — all 27 replayable cells of the frozen universe (§3 of the
pre-registration, less the 4 unreplayable cells in §7.3). Across the whole universe
the alpha opened a position **once**.

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
343 signals across 27 sessions contain exactly **one** directional entry.

### 3.3 N_sub = 1

The subpopulation is `open ∧ safe-OFF ∧ ¬caps`. Across 27 sessions there were **342
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
entries: the alpha entered once in 27 sessions, and the deficit is ~200×. **The
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

Two defects must be closed before any re-run is meaningful.

**Done (on instruction).** `bootstrap.py:1817` now passes
`decouple_gate_close=module.decouple_gate_close`, with
`tests/kernel/test_stage0_decouple_registration_seam.py` asserting the flag survives
the real loader→registry→bootstrap chain *and* that both risk authors get built with
the declared ceilings. Verified to fail without the fix and to leave arm A
bit-identical.

**Also done (§1.8).** The slice-store population defect. Single-strategy fills now
self-attribute, so the ceiling binds; `tests/kernel/test_fill_attribution_seam.py`
asserts the slice book is actually written by the real ack path — the "does it *act*"
assertion this defect family kept slipping past.

**Also done.** The APP baseline was re-pinned to the corrected value (430.85 → 363.34,
§1.8.1) with the cause recorded at the pin — this is the re-verification the baseline
file's own CAVEAT had been asking for since pruning went live. Both §1.8.2 follow-ups
are closed: the fill ledger is populated and is now the live attribution path, and the
attribution block no longer depends on the ledger existing.

**Outstanding.**

1. **Cross-alpha netting is unwired** — `aggregate_intents` has no production caller, so
   proportional attribution, while now exercised, is never multi-contribution (§1.8.2).
   Wiring it is an execution-path change needing its own design review, not a defect fix.
2. A promotion-time guard so `decouple_caps_only` cannot be authorized unless its
   ceiling is demonstrably able to bind, so the ledger cannot record an authorization
   with no runtime effect.

### 7.2 Data and universe breadth to power the gate

Observed entry rate over the complete census: **1 directional entry per 27
symbol-sessions**, and that single entry did coincide with a safe-OFF — so the
subpopulation yield is ~**0.037 episodes per symbol-session**:

| Requirement | Arithmetic |
|---|---|
| N_sub ≥ 200 (α = 0.10, tail ≥ 20) | 200 × 27 ≈ **5,400 symbol-sessions** at the observed rate |
| vs. available | 27 replayable — a **200×** shortfall |

The yield estimate is itself based on a single episode, so it carries essentially no
precision; treat 5,400 as an order-of-magnitude floor, not a target.

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
| Verdict | **UNDERPOWERED — NOT A GO**, plus two Stage-0 defects |
| Defect 1 (fixed on instruction) | `src/feelies/bootstrap.py:1817` dropped `decouple_gate_close` — Stage 0 wholly inert; fail-safe |
| Defect 2 (fixed on instruction) | `StrategyPositionStore` never written on entry fills — deferral ceiling could not bind; was fail-open (§1.7, §1.8) |
| APP baseline | Re-pinned 430.85 → 363.34 with cause recorded (§1.8.1) — the re-verification the pin's own CAVEAT asked for |
| Primary pilot | `sig_kyle_drift_v1` — N_sub = 1 (floor 200) |
| Secondary pilot | `sig_moc_imbalance_v1` — N_sub = 0 (pre-declared underpowered) |
| Bars evaluated | B4 FAIL; B1–B3 not evaluable |
| Stage 1 | **Not implemented.** Claim B untested, remains unproven (design §4.2) |
| Stage-0 behavior | Unmodified during measurement; defect 1 fixed afterwards on instruction, defect 2 left open |
