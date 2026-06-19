# Risk Engine & Portfolio Governor — Audit Report

- **Date:** 2026-06-18
- **Auditor role:** senior quantitative risk engineer / systems auditor
- **Mode:** read-only, evidence-based. No production code modified.
- **Scope:** `src/feelies/risk/*`, `src/feelies/alpha/risk_wrapper.py`, the
  orchestrator escalation + sized-intent drain (`src/feelies/kernel/orchestrator.py`),
  and the regime `current_state` reader contract. Regime math, composition, and
  fill simulation are out of scope.
- **Read-only checks run (all green):** `tests/risk/`,
  `tests/acceptance/test_bt15_buying_power.py`,
  `tests/determinism/test_hazard_exit_replay.py`,
  `tests/integration/test_hazard_exit_e2e.py`,
  `tests/integration/test_dual_scale_down_e2e.py`,
  `tests/services/test_hazard_exit_controller_wiring.py`,
  `tests/bootstrap/test_per_alpha_risk_budget_wiring.py`,
  `tests/alpha/test_risk_wrapper.py` → **190 passed**.

Legend for classification: **[bug]** implementation defect, **[model]** modeling
choice (defensible but worth challenging), **[design]** intentional and correct,
**[doc]** documentation/comment defect that misleads risk reasoning.

---

## 1. Executive summary

Fail-safe findings first (Inv-11 is the priority lens).

1. **No autonomous regime amplification.** Both regime scalings are hard-clamped at
   `min(1.0, ev)` — `basic_risk._regime_scaling` (`src/feelies/risk/basic_risk.py:760`)
   and `position_sizer._get_regime_factor` (`src/feelies/risk/position_sizer.py:126`).
   An operator config of `{"normal": 1.5}` or a >1.0 posterior tilt cannot lift
   exposure above baseline. **[design] — sound.**
2. **P1 — cumulative gross-exposure cap is NOT enforced across legs of a single
   `SizedPositionIntent`.** Every per-leg `check_order` is evaluated against the
   *same pre-intent* `PositionStore` snapshot
   (`src/feelies/kernel/orchestrator.py:1954`, `src/feelies/risk/sized_intent_orders.py:90-126`);
   legs do not see each other's prospective notional. K distinct symbols each
   individually under the 20% gross cap can collectively breach it. This is an
   *autonomous* breach of the configured gross limit. **[bug]**
3. **P1 — `check_sized_intent` can raise, violating its own "MUST NOT raise"
   contract** (`src/feelies/risk/engine.py:73`). `build_sized_intent_orders`
   invokes `check_order` with no surrounding try/except
   (`src/feelies/risk/sized_intent_orders.py:126`); a raising per-leg check
   propagates out and is not fail-safe-contained. **[bug]**
4. **P1 — missing-data regime default is `1.0×` (baseline), not reduced.** When
   `regime_engine is None` or `current_state(symbol)` is `None`/empty, both the
   risk engine (`basic_risk.py:743-748`) and the sizer (`position_sizer.py:106-110`)
   return `1.0`. The SKILL/module docstrings imply unknown→reduced; in practice
   unknown→full size. The two components *agree* (no divergence), but neither
   reduces on missing data. **[model]** — note the prompt's hypothesized
   "basic_risk min vs sizer 1.0" divergence does **not** exist; both are 1.0.
5. **P2 — gross-cap equity fallback loosens on non-positive NAV.** When live
   equity ≤ 0, the cap reverts to *initial* `account_equity`
   (`basic_risk.py:668`), so an underwater book is sized against initial capital,
   not zero. The 5% drawdown gate normally `FORCE_FLATTEN`s first, so this is a
   defense-in-depth edge, not a live hole. **[model]**
6. **Escalation SM is monotone-tightening and cannot silently reset.** Transition
   table is forward-only NORMAL→WARNING→BREACH_DETECTED→FORCED_FLATTEN→LOCKED with
   LOCKED→NORMAL only (`src/feelies/risk/escalation.py:29-59`). The only loosening
   paths require a human `audit_token` and refuse during active trading / when
   LOCKED (`orchestrator.py:1603-1621`, `:1559-1601`). **[design] — sound.**
7. **Per-leg veto is correct.** `REJECT` drops only the offending leg; surviving
   legs proceed; `FORCE_FLATTEN` aborts the whole intent with
   `requires_global_risk_escalation=True` (`sized_intent_orders.py:127-134`),
   which the orchestrator promotes to macro RISK_LOCKDOWN
   (`orchestrator.py:1954-1962`). **[design] — sound.**
8. **P2 [doc] — `BasicRiskEngine.check_sized_intent` docstring contradicts the
   code.** Lines `basic_risk.py:330-336` claim a per-leg `FORCE_FLATTEN` is "not
   promoted to orchestrator global lockdown — the leg is veto-dropped like
   REJECT." The code does the opposite (escalates to macro lockdown) and the same
   docstring's preceding paragraph (`:325-328`) says so. Dangerously misleading.
9. **Hazard exit is exit-only by construction.** Order side is always opposite the
   live position sign (`src/feelies/risk/hazard_exit.py:238`); a flat position
   emits nothing (`:227`). It can only reduce exposure. **[design] — sound.**
10. **Hazard determinism holds**, but the order-id docstring is stale: it says the
    SHA-256 key is `(correlation_id, sequence, symbol, reason)`
    (`hazard_exit.py:22`) while the code uses `trigger_ts_ns`, not `sequence`
    (`:241`). Replay is still bit-identical (timestamp-driven). **P2 [doc].**
11. **Hazard suppression key omits `departing_state`.** The controller keys on
    `(strategy_id, symbol, reason)` cleared on flat (`hazard_exit.py:138, 221, 267-280`),
    not the `(symbol, alpha_id, departing_state)` the prompt/SKILL imply. Effect is
    *more* conservative (≤1 exit per open episode regardless of which regime
    departs). **[design] but doc/spec drift — note.**
12. **Exits/reductions are always permitted across every gate** (PDT, buying-power,
    RTH, position-limit), gated behind `_opens_or_increases`
    (`basic_risk.py:433-442, 461, 489, 530`) and `_signal_reduces_position`
    (`risk_wrapper.py:369-388`). **[design] — sound, Inv-11-correct.**
13. **P2 — config-presence fail-open on PDT / buying-power / RTH gates.** Each
    returns `None` (pass) when its config object is unwired
    (`basic_risk.py:459, 487, 528`). A deployment that forgets to wire
    `buying_power_config` silently has no Reg-T cap (the 20% gross cap still
    applies). **[model]**
14. **Two independent regime scale maps** (RiskConfig fields vs sizer
    `_DEFAULT_REGIME_FACTORS`) with identical defaults but no shared source of
    truth (`basic_risk.py:107-111`, `position_sizer.py:63-67`) — drift risk if one
    is reconfigured. **P2 [model].**
15. **`resolve_mark` is correctly fail-safe**: live-mark accessor exceptions are
    swallowed with a WARNING and fall back to `avg_entry_price`, then to `0`
    (skip-leg) — never raises into the risk path (`sized_intent_orders.py:46-66`).
    **[design] — sound.**

---

## 2. Risk-control inventory

| Entry point | Input | Scaling applied | Limit(s) enforced | Fail-safe default |
|---|---|---|---|---|
| `BasicRiskEngine.check_signal` | `Signal` + `PositionStore` | regime EV on *limit* (`_regime_scaling`, clamp ≤1.0) | per-symbol position limit (directional), gross exposure, drawdown, scale-down band | unknown regime → 1.0× limit; reducing signals exempt |
| `BasicRiskEngine.check_order` | `OrderRequest` + `PositionStore` | regime EV on *limit* | PDT min-equity, Reg-T buying power, RTH, post-fill position limit, prospective gross exposure, drawdown, scale-down | each optional gate inert if unwired; exits exempt |
| `BasicRiskEngine.check_sized_intent` | `SizedPositionIntent` + `PositionStore` | per-leg via `check_order` | per-leg veto (REJECT drops leg; FORCE_FLATTEN aborts intent + escalates) | zero/negative mark → skip leg |
| `AlphaBudgetRiskWrapper.check_*` | same | `min(alpha, platform)` limits | per-alpha position, exposure, drawdown (REJECT→quarantine), then delegates aggregate to inner | unregistered `strategy_id` → skip per-alpha, aggregate-only |
| `BudgetBasedSizer.compute_target_quantity` | `Signal`, budget, price, equity | regime EV on *quantity* (`_get_regime_factor`, clamp ≤1.0) + `signal.strength` | caps at `budget.max_position_per_symbol` | price/equity ≤0 → 0 shares; unknown regime → 1.0× |
| `HazardExitController` | `RegimeHazardSpike`, `Trade` | none (full-position exit) | exit-only; episode suppression `(sid, symbol, reason)` | flat position → no-op |
| `buying_power_limit` | equity, phase, config | 4× intraday / 2× overnight | gross cap | equity ≤0 → limit 0 |
| Escalation SM | risk verdicts (orchestrator) | n/a | forward-only ladder | LOCKED is terminal absent human unlock |

Regime scale maps (must stay aligned, no shared constant):
`vol_breakout 0.5`, `compression_clustering 0.75`, `normal 1.0` in both
`basic_risk.py:107-111` and `position_sizer.py:63-67`.

---

## 3. Fail-safe audit (Inv-11) — exposure-increasing paths enumerated

### 3.1 Every multiplier in the risk path, with bound

| Multiplier | Location | Bound | Autonomous amplify? |
|---|---|---|---|
| risk regime EV (limit) | `basic_risk.py:752-760` | `min(1.0, Σ pᵢ·scaleᵢ)` | **No** — clamped ≤1.0 |
| sizer regime EV (quantity) | `position_sizer.py:115-126` | `min(1.0, Σ pᵢ·scaleᵢ)` | **No** — clamped ≤1.0 |
| `signal.strength` | `position_sizer.py:94-95` | `max(0.0, strength)`; conviction = allocated·strength | No (strength is the alpha's own conviction in [0,1] by convention; **not clamped to ≤1** here — see note) |
| `scaling_factor` (SCALE_DOWN) | `basic_risk.py:707-708` | `max(0.1, min(1.0, …))` | No — clamped ≤1.0, floor 0.1 |
| per-leg SCALE_DOWN rebuild | `sized_intent_orders.py:135-143` | `max(1, round(qty·factor))` | No — factor ≤1.0 upstream; floor 1 share |
| buying-power multiplier | `buying_power.py:30-31, 51-56` | 4× / 2× of equity (Reg-T) | Increases *limit*, not order qty; standard margin. Requires explicit wiring. |

**Note on `signal.strength`:** `conviction_capital = allocated * strength`
(`position_sizer.py:95`). `strength` is floored at 0 but **not capped at 1.0**. A
signal emitting `strength > 1.0` would size above the alpha's allocated capital
*before* the ≤1.0 regime clamp, then be re-capped only by
`budget.max_position_per_symbol` (`position_sizer.py:101`). This is bounded by the
position cap, not by capital allocation. **P2 [model]** — confirm `Signal.strength`
is contractually ≤1.0 upstream; if not, add a clamp.

### 3.2 Cumulative gross cap not enforced intra-intent — **P1 [bug]**

`_flush_pending_sized_intents` calls `check_sized_intent(intent, self._positions)`
once for the whole intent (`orchestrator.py:1954`); inside,
`build_sized_intent_orders` loops legs against the **unchanging** `positions`
snapshot (`sized_intent_orders.py:90-126`) and only submits/reconciles fills
*after* all legs are built (`orchestrator.py:1995-2021`). Each leg's
`_prospective_total_exposure` (`basic_risk.py:617-642`) therefore measures
`snapshot_total − contribᵢ + postfillᵢ` for *its own* symbol only. The aggregate
post-fill gross `snapshot + Σ(postfillᵢ − contribᵢ)` is never checked, so a
multi-leg intent can autonomously push realized gross above
`max_gross_exposure_pct`. Bounded by per-symbol position limits and corrected on
the next tick's check, but it is a genuine autonomous cap breach. Needs a runtime
repro (Appendix Q1).

### 3.3 Unknown / missing regime state

- `regime_engine is None` → `1.0` (both `basic_risk.py:744`, `position_sizer.py:107`).
- `current_state(symbol)` is `None` (symbol never filtered) → `1.0`
  (`basic_risk.py:747-748`, `position_sizer.py:109-110`).
- **Unknown state *name* inside a present posterior** → `min(all scales)` via
  `.get(name, default)` (`basic_risk.py:753`, `position_sizer.py:116`), with
  `default = min(scales)` (`basic_risk.py:115`, `position_sizer.py:76-78`).

So "unknown name within a known posterior" is conservative (min), but "no
posterior at all / no engine" is baseline (1.0). The two components are **aligned**
(both 1.0 on missing) — contradicting the prompt's hypothesized divergence. The
residual concern is that missing data resolves to *full* size, not reduced. **P1
[model]** (consider a missing-data reduction factor, or document the choice).

NaN handling lives in the regime engine, not the risk layer: `posterior()` resets
to uniform on NaN/inf (`services/regime_engine.py:537-545`), and `current_state`
only returns committed (finite) posteriors (`:559-561`), so the risk layer never
sees NaN.

### 3.4 Internal-error outcome

- `resolve_mark`: exception → WARNING + fallback, never raises
  (`sized_intent_orders.py:52-66`). Zero mark → skip leg. **Sound.**
- `check_sized_intent`: **does not** wrap `check_order` in try/except
  (`sized_intent_orders.py:126`). A raising per-leg check propagates out,
  violating `engine.py:73` ("Implementations MUST NOT raise"). On the standalone
  SIGNAL path a raising `check_order`/`check_signal` likewise propagates — but
  there the contract does not promise non-raising. **P1 [bug]** for the intent
  path specifically.
- Drawdown HWM is bumped via an explicit `_update_high_water_mark` step kept
  separate from the pure predicate `_is_drawdown_breached`
  (`basic_risk.py:779-818`), so a speculative check cannot ratchet the HWM. HWM ≤ 0
  → `_is_drawdown_breached` returns `True` (fail to flatten) (`basic_risk.py:812-813`).
  **Sound.**

---

## 4. Per-leg veto audit (`SizedPositionIntent` → legs)

Trace for a 3-symbol intent (`AAA`, `BBB`, `CCC`) via `sized_intent_orders.py`:

1. Empty `target_positions` → early `SizedIntentRiskResult(orders=())` (`:85-86`).
2. Iterate `sorted(intent.target_positions)` — lexicographic, deterministic
   (`:90`, satisfies Inv-5 / L3-orders parity hash).
3. Per symbol: `mark = resolve_mark(...)`; `mark ≤ 0` → **skip leg** (Inv-11)
   (`:93-95`).
4. `target_shares = round_half_up(target_usd / mark)` via `Decimal`
   (`:97-101`) — no float; `delta = target − current.quantity`; `delta == 0` →
   no-op (not counted as veto-dropped) (`:102-104`).
5. Side from delta sign, `quantity = abs(delta)` (`:106-107`).
6. `order_id = derive_order_id(f"{corr}:{seq}:{symbol}")` — deterministic
   (`:109`). `reason="PORTFOLIO"`, `source_layer="PORTFOLIO"` stamped (`:115, 122`).
   Per-symbol disclosed cost propagated (`:110, 123`).
7. `verdict = check_order(order, positions)` (`:126`):
   - `FORCE_FLATTEN` → **abort whole intent**, `orders=()`,
     `requires_global_risk_escalation=True` (`:127-131`).
   - `REJECT` → append `(symbol, reason)` to `dropped`, **continue** (only this leg
     dropped) (`:132-134`).
   - `SCALE_DOWN` → rebuild leg at `max(1, round_half_up(qty·factor))`
     (`:135-158`).
   - else (`ALLOW`) → append as-is (`:159`).
8. After loop, `on_dropped_legs` fires once with all dropped legs
   (`:161-162`); base engine publishes a WARNING `Alert` listing dropped symbols
   (`basic_risk.py:356-408`).

**Sign & rounding:** correct — `ROUND_HALF_UP` on `Decimal`, delta sign drives
side. **Ordering:** lexicographic, deterministic. **Lineage:** `reason="PORTFOLIO"`
stamped, `correlation_id` inherited. **Per-leg isolation:** confirmed — REJECT does
not affect surviving legs.

**Wrapper parity:** `AlphaBudgetRiskWrapper.check_sized_intent`
(`risk_wrapper.py:241-272`) routes each leg through `self.check_order` so per-alpha
budgets actually apply (the documented audit R2 fix), and reuses the inner engine's
`_emit_dropped_legs_alert` via `getattr` (`:266-271`). Single canonical
implementation in `sized_intent_orders.py` prevents drift. **Sound.**

**Caveat (already self-documented):** `mechanism_breakdown` is *not* re-validated
after legs are dropped — surviving legs may violate the alpha's intended
dollar/sector/mechanism neutrality (`basic_risk.py:393-399`, SKILL §Layer-3). This
is disclosed via the partial-execution Alert. **[design] — acceptable, surfaced.**

---

## 5. Escalation SM audit

**States/transitions** (`escalation.py:19-59`): `NORMAL → WARNING →
BREACH_DETECTED → FORCED_FLATTEN → LOCKED`; `LOCKED → NORMAL` only. No
intermediate de-escalation edge exists, so `StateMachine.transition` raises
`IllegalTransition` for any loosening attempt (`state_machine.py:148-149`).

**Cascade** (`orchestrator._escalate_risk`, `:3451-3520`): walks R0→R4 in one call
using cumulative `if level == …` blocks (idempotent regardless of entry level), runs
`_emergency_flatten_all` at FORCED_FLATTEN, then activates the kill switch and moves
macro to RISK_LOCKDOWN. **Monotone-tightening confirmed.**

**Can it silently reset on a benign tick?** No. The only loosening entry points are
human-gated:
- `reset_risk_escalation` (`:1603-1621`): requires `audit_token`, refuses if
  LOCKED, refuses during active trading (`TRADING_MODES`).
- `unlock_from_lockdown` (`:1559-1601`): zero-exposure guard + audit token, also
  resets the kill switch.

`StateMachine.reset` *does* bypass the transition table unconditionally
(`state_machine.py:174-198`), but it is only reachable through the two guarded
methods above — there is no per-tick caller. **No silent reset path found.**

**Determinism (Inv-5):** transitions are driven by deterministic verdicts and
stamped with `correlation_id`; timestamps come from the injected `Clock`
(`escalation.py:62-69`). Escalation order is fixed. **Sound.** One nit: kill-switch
activation and `KillSwitchActivation`/macro transition timestamps use
`self._clock.now_ns()` (`orchestrator.py:3508, 3517`) — fine under the injected
clock, but the residual-alert path inside the hazard handler uses
`self._clock.now_ns()` too (`:5999`); ensure all such reads are the injected clock
(they are) so replay stays bit-identical.

---

## 6. Regime / hazard sizing coherence

### 6.1 Double-scaling (D.1)

**Deliberate series, not accidental compounding.** The module docstring is explicit:
the risk engine applies regime EV only to *limits*, never to `scaling_factor`
(`basic_risk.py:5-9, 721-740`); the sizer applies regime EV to *quantity*
(`position_sizer.py:96-98`). Sizer proposes a quantity (scaled once by regime),
the risk engine caps it against a separately regime-scaled *limit* — different
axes. There is no path that multiplies the regime factor onto the same quantity
twice. **[design] — sound.** Residual risk: the two scale maps are independent
constants (§2); a reconfiguration of one without the other would desynchronize the
series. **P2.**

### 6.2 Timing / lag (D.2)

Both `_regime_scaling` and `_get_regime_factor` call `current_state(symbol)`, a
read-only cached-posterior lookup (`services/regime_engine.py:559-561`). The cache
is written by `posterior()` at M2. At M5/M6 the value reflects the **most recent
`posterior()` call for that symbol**, which is the current tick's quote in the
standard per-tick walk. If no new quote for the symbol arrived, it is the last
known posterior (monotone-stale, fail-safe). No lookahead: `current_state` never
advances state. **[design] — sound; lag is "last committed posterior".**

### 6.3 Can EV exceed 1.0? (D.3)

No. `min(1.0, ev)` in both (`basic_risk.py:760`, `position_sizer.py:126`), with
unit tests `test_factor_clamped_at_one_when_config_supplies_amplifier`
(`tests/risk/test_position_sizer.py:88`). **Sound.**

### 6.4 Hazard exit-only (F)

- Side is always opposite the position sign; flat → no emission
  (`hazard_exit.py:227, 238`). No entry/grow path exists. **Proven exit-only.**
- `HAZARD_SPIKE`: `hazard_score ≥ threshold` (`:171`) AND open age ≥
  `min_age_seconds` (`:233-236`). `HARD_EXIT_AGE`: age ≥ `hard_exit_age_seconds`
  measured off `Trade` arrival as a deterministic clock (`:182-205`); min-age does
  not apply to the hard path (`:231-232`). **Correct.**
- Suppression key `(strategy_id, symbol, reason)`, cleared on flat
  (`:221-223, 267-280`) — omits `departing_state` (§1.11). More conservative than
  the spec wording.
- **Regime-gate-OFF interaction:** the controller does not consult the regime gate;
  it acts purely on position sign + spike/age. The orchestrator's defensive
  `check_order` on a hazard exit logs REJECT but **submits anyway** (Inv-11
  exit fail-safe) and never broadcasts FORCE_FLATTEN to avoid a spurious global
  lockdown while it is itself submitting the exit (`orchestrator.py:5990-6016`).
  Duplicate publishes are deduped via `_hazard_submitted_order_ids` (`:5987-5989`).
  No double-exit or conflicting-order path found. **Sound.**

---

## 7. Buying power & limits audit

- `buying_power_limit`: `equity ≤ 0 → 0` (`buying_power.py:49-50`); else
  `equity × multiplier` (4× intraday / 2× overnight, `:51-56`). No off-by-one;
  multipliers validated `> 0` and `account_type == "margin_25k"` enforced in
  `__post_init__` (`:33-40`). **Sound.**
- `_check_buying_power` (`basic_risk.py:515-564`): gates only opens/increases
  (`:530`); exits return `None`. Uses live NAV via `_compute_current_equity` and
  `_prospective_total_exposure`; `prospective > limit → REJECT
  INSUFFICIENT_BUYING_POWER`. Strict `>` (not `≥`) — a fill landing exactly on the
  limit is allowed, consistent with "limit = max permitted". **Sound.**
- Gross exposure cap (`_check_exposure_and_drawdown`, `:644-719`): `exposure ≥
  max_exposure → REJECT` (`:672`). `max_exposure = equity_for_cap ×
  pct/100`, `equity_for_cap = current_equity if >0 else account_equity`
  (`:668`) — **the non-positive-equity fallback to initial capital is the §3.5 /
  §1.5 loosening edge.** **P2 [model].**
- Scale-down band: `scale_down_threshold_pct ≥ 1.0 → REJECT` (guards div-by-zero,
  `:697-705`); otherwise `SCALE_DOWN` with `max(0.1, min(1.0, …))` (`:706-717`).
  **Sound.**
- Position limit: gate 1 directional (`check_signal`, `:164-183`) + gate 2 post-fill
  (`check_order`, `:223-268`), both regime-scaled and exit-exempt. Per-alpha
  `min(alpha, platform)` mirror in the wrapper (`risk_wrapper.py:80-100, 199-220`).
  **Sound.**
- "Policy-only" limits (max notional, max symbols, ADV%, net, sector gross,
  concentration) are documented as **not implemented** (SKILL §Position & Exposure
  Limits); no silent partial enforcement found. **Accurate.**

---

## 8. Test gap matrix

| Invariant / behavior | Coverage | Evidence / gap |
|---|---|---|
| Regime EV clamp ≤1.0 (no amplify) | **Covered** | `test_position_sizer.py:88` (`test_factor_clamped_at_one_when_config_supplies_amplifier`) |
| No-regime-engine → 1.0 | **Covered** | `test_position_sizer.py:151`, `test_basic_risk.py:215` |
| vol_breakout reduces limit/size | **Covered** | `test_basic_risk.py:198`, `test_position_sizer.py:74` |
| Per-leg REJECT drops one leg | **Partial** | dropped-leg alert covered (`test_basic_risk.py:352`), but no explicit "surviving legs unaffected, 1 of N dropped" assertion on `orders` tuple |
| Per-leg FORCE_FLATTEN aborts intent + flag | **Covered** | `test_basic_risk.py:435` |
| SCALE_DOWN half-up rounding (intent) | **Covered** | `test_basic_risk.py:513` |
| **Cumulative gross cap across legs of one intent** | **Missing** | no test submits a multi-leg intent that is per-leg-OK but aggregate-over-cap (§3.2) |
| **`check_sized_intent` never raises (per-leg check raises)** | **Missing** | no test injects a raising `check_order` to assert containment (§3.4) |
| Missing-posterior → 1.0 (documented behavior) | **Partial** | `None`-engine covered; symbol-never-filtered (`current_state→None`) path not asserted at risk layer |
| Escalation monotone / no silent reset | **Partial** | SM table is structurally forward-only; no golden "benign tick cannot loosen" replay test in `tests/risk/` |
| Escalation reset requires audit token | **Partial** | orchestrator guards exist; covered in kernel tests, not risk-layer |
| Hazard exit-only (side opposite sign) | **Covered** | `test_hazard_exit.py:92` + long/short cases |
| Hazard episode suppression | **Covered** | `test_hazard_exit.py:323` |
| Hazard replay byte-identical | **Covered** | `test_hazard_exit.py:371`, `tests/determinism/test_hazard_exit_replay.py` |
| Buying power 4×/2× + unimplemented raise | **Covered** | `test_buying_power.py:16,25,34`, `tests/acceptance/test_bt15_buying_power.py` |
| Non-positive-equity gross-cap fallback | **Missing** | no test drives `current_equity ≤ 0` to assert the cap basis |
| `signal.strength > 1.0` upsizing | **Missing** | no test asserts strength is clamped/contracted |

---

## 9. Prioritized backlog

Effort: **S** ≤ ½ day, **M** ~1–2 days, **L** > 2 days.

### P0
None. No autonomous regime amplification, failed-check-still-emits (except the
intentional hazard exit fail-safe), escalation reset, hazard entry path, or
non-determinism was found.

### P1
| ID | Component | `file:line` | One-line fix | Impact |
|---|---|---|---|---|
| R-1 | Intra-intent gross cap | `sized_intent_orders.py:90-126`, `orchestrator.py:1954` | Accumulate admitted-leg prospective notional within the loop (pass a running exposure delta into `check_order`, or post-check the aggregate). **M** | Closes an autonomous breach of the configured gross cap on multi-leg intents. |
| R-2 | `check_sized_intent` non-raising contract | `sized_intent_orders.py:126` | Wrap per-leg `check_order` in try/except → treat exception as veto-drop (REJECT-equivalent) + Alert. **S** | Honors `engine.py:73`; a single PositionStore/regime bug cannot crash the whole intent path. |
| R-3 | Missing-data regime default | `basic_risk.py:744-748`, `position_sizer.py:107-110` | Either return a configurable reduction factor on missing posterior, or document "missing→full size" as an explicit accepted risk. **S** | Aligns behavior with the Inv-11 "unknown→reduced" expectation, or makes the deviation auditable. |

### P2
| ID | Component | `file:line` | One-line fix | Impact |
|---|---|---|---|---|
| R-4 | Stale docstring (intent FORCE_FLATTEN) | `basic_risk.py:330-336` | Delete/rewrite the contradictory "Macro interaction" paragraph. **S** | Prevents future maintainers from wrongly assuming the PORTFOLIO path cannot lock down. |
| R-5 | Hazard order-id docstring | `hazard_exit.py:22` | Change `sequence` → `trigger_ts_ns` to match `:241`. **S** | Doc accuracy for determinism reasoning. |
| R-6 | Non-positive-equity gross-cap basis | `basic_risk.py:668` | On `current_equity ≤ 0`, set cap to 0 (block new exposure) rather than initial equity. **S** | Tightens the underwater edge; defense-in-depth behind the drawdown gate. |
| R-7 | Duplicate regime scale maps | `basic_risk.py:107-111`, `position_sizer.py:63-67` | Share a single canonical map / validate alignment at bootstrap. **S** | Removes silent drift risk in the deliberate sizer×limit series. |
| R-8 | `signal.strength` upper bound | `position_sizer.py:94-95` | Clamp `strength` to ≤1.0 (or assert the upstream contract). **S** | Prevents above-allocation sizing before the regime clamp. |
| R-9 | Config-presence fail-open | `basic_risk.py:459, 487, 528` | Log a one-shot WARNING when an expected gate config is absent in live mode. **S** | Surfaces accidentally-unwired Reg-T/PDT/RTH gates. |
| R-10 | Test gaps | §8 | Add the four **Missing** specs (intent aggregate cap, raising per-leg check, ≤0-equity cap basis, strength bound) + a golden escalation-no-loosen replay. **M** | Locks the P1/P2 behaviors against regression. |

### Proposed minimal new tests (specs only)
1. **Property "never amplifies"**: for random posteriors and operator scale maps
   (including >1.0 entries), assert `_regime_scaling` and `_get_regime_factor`
   return ≤ 1.0.
2. **Intent aggregate gross cap**: build a 3-leg intent where each leg is
   individually within the 20% cap but the sum exceeds it; assert at least one leg
   is vetoed (will currently fail — codifies R-1).
3. **Raising per-leg check**: inject a `check_order` that raises; assert
   `check_sized_intent` returns a `SizedIntentRiskResult` and does not propagate
   (will currently fail — codifies R-2).
4. **Golden escalation replay**: feed an identical verdict log twice; assert the
   `StateTransition` sequence is byte-identical and that no benign tick produces a
   loosening transition.

---

## 10. Appendix — open questions needing data runs

- **Q1 (R-1 confirmation):** Run a backtest with a PORTFOLIO alpha emitting a
  multi-symbol intent whose summed target notional exceeds `max_gross_exposure_pct`
  while each leg is individually compliant. Confirm realized post-fill gross
  exceeds the cap for one tick and is corrected on the next. Quantify the worst-case
  overshoot as a function of universe size and per-symbol headroom.
- **Q2:** Measure the regime `current_state` staleness distribution at M5/M6 in a
  live-like replay — how often is the posterior from a prior tick vs the current
  quote? Confirms the §6.2 lag model empirically.
- **Q3:** Does any shipped `Signal` producer emit `strength > 1.0`? If never, R-8
  is doc-only; if yes, it is a live sizing concern.
- **Q4:** Stress the non-positive-equity path (Q3 + adverse marks) to confirm the
  drawdown gate always FORCE_FLATTENs before the §1.5 gross-cap fallback is
  reachable, or find the gap where it is not.
