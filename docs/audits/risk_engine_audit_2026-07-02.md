# Risk Engine & Portfolio Governor Audit — 2026-07-02

Scope: read-only audit of `RiskEngine` (`check_signal`, `check_order`, `check_sized_intent`),
the `RiskLevel` escalation SM, position sizing, buying power, and `HazardExitController` —
from `Signal` / `SizedPositionIntent` → `OrderRequest`. No production code, tests, baselines,
configs, or ledgers were changed.

This is the third audit pass on this component (`risk_engine_audit_2026-06-18.md`,
`risk_engine_audit_2026-06-20.md` precede it). Where this pass reconfirms a prior finding —
fixed or still open — that is stated explicitly with a citation to the prior report, rather
than re-derived as new. All severities and line citations below are independent, from a fresh
reading of the current tree.

Verification run (read-only, this pass):

- `uv sync --all-extras` (fresh container; venv was not present) — 38 packages installed.
- `uv run pytest tests/risk/ -q` — **164 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/acceptance/test_bt15_buying_power.py tests/determinism/test_hazard_exit_replay.py -q` — **8 passed**.
- `PYTHONHASHSEED=0 uv run pytest tests/integration/test_hazard_exit_e2e.py -q` — **6 passed**.
- Additionally (in-scope test files, not in the mandated command list, run for completeness): `tests/integration/test_dual_scale_down_e2e.py tests/alpha/test_risk_wrapper.py tests/bootstrap/test_per_alpha_risk_budget_wiring.py tests/services/test_hazard_exit_controller_wiring.py` — **32 passed**.
- Total: **210 passed, 0 failed** across all in-scope test files. No pre-existing failures found, consistent with `CLAUDE.md`'s "green as of 2026-06-11" baseline.

Severity convention used in this report (per the audit brief):

- **P0** — any autonomous exposure increase, a formal failed risk check that still emits/submits
  an order, an escalation reset that isn't genuinely human-gated, a hazard-exit path that can
  open/grow a position, or a non-determinism.
- **P1** — can block de-risking, weakens a shared invariant without meeting the P0 bar, or leaves
  a material audit/observability hole.
- **P2** — bounded weakness, test gap, or a modeling choice / extensibility gap that needs
  explicit owner acceptance rather than a code fix.

Each finding is tagged **[bug]**, **[modeling choice]**, or **[intentional design]** per the
audit brief's quality bar.

---

## 1. Executive summary

1. **P0 (reasoned from code; not reproduced against live broker timing)** — `HazardExitController`
   has no cross-reason in-flight guard: `HAZARD_SPIKE` and `HARD_EXIT_AGE` are independent
   suppression keys, and the only "already acting on this symbol" guard is `position.quantity == 0`
   (§6, Finding **HZ-1**). In PAPER/LIVE, where the orchestrator's own code explicitly documents
   that broker acks land asynchronously (`orchestrator.py:4965`), two full-size exit orders can be
   emitted for the same symbol before the first one's fill reconciles into `PositionStore`. If both
   fill, the net effect **reverses** the original position — new, opposite-direction, un-risk-checked
   exposure that the "exit-only" contract is meant to forbid. No existing test exercises overlapping
   trigger reasons on an unreconciled position (`tests/risk/test_hazard_exit.py:323` only covers
   same-reason suppression).
2. **P1** — the "unconditional" non-positive-equity → `FORCE_FLATTEN` fail-safe
   (`basic_risk.py:729-737`, comment: *"returned unconditionally... forecloses... an allow-unlimited
   hole"*) is **not reachable for ENTRY orders** once `BuyingPowerConfig` is wired. `_check_buying_power`
   (`basic_risk.py:274-282`) runs strictly before `_check_exposure_and_drawdown`
   (`basic_risk.py:313-323`) inside `check_order`, and `buying_power_limit()` returns `Decimal("0")`
   for non-positive equity (`buying_power.py:49-50`), so any entry order is intercepted with a scoped
   `REJECT(INSUFFICIENT_BUYING_POWER)` — never reaching the intended global `FORCE_FLATTEN` +
   escalation. `bootstrap.py:411-415` wires `BuyingPowerConfig` unconditionally for **every** mode
   (BACKTEST/PAPER/LIVE), so this is not a paper/live-only edge case (§3, Finding **FS-2**).
3. **P1** — `reset_risk_escalation` (`orchestrator.py:1690-1708`) is human/audit-token-gated like its
   sibling `unlock_from_lockdown`, but unlike `unlock_from_lockdown`
   (`orchestrator.py:1666-1671`, `exposure != Decimal("0")` → raise), it has **no precondition that
   the book is actually flat or safe** before returning risk state to `NORMAL` from
   `BREACH_DETECTED` / `FORCED_FLATTEN`. Zero test coverage exists for this method anywhere in the
   suite (§5, Finding **ESC-1**).
4. **Confirmed fixed since `risk_engine_audit_2026-06-20.md`**: that report's P0
   ("hazard handler submits after formal `check_order` REJECT") is resolved. The current handler
   independently re-derives whether the order verifiably reduces the live position
   (`order_reduces`, `orchestrator.py:6302-6304`) and only treats a non-reducing `REJECT` as
   authoritative (`orchestrator.py:6310-6335`); a `REJECT` on a genuinely reducing order is logged
   and still submitted, matching the exit-only design intent rather than an unconditional bypass.
5. **Confirmed fixed since `risk_engine_audit_2026-06-20.md`**: that report's P1
   (`AlphaBudgetRiskWrapper.check_order` rejecting reducing orders at the per-alpha exposure cap) is
   resolved — `order_reduces` now exempts reducing orders from that cap
   (`risk_wrapper.py:231-246`).
6. Regime scaling is fail-safe and non-amplifying by construction in **both** consumers:
   `BasicRiskEngine._regime_scaling` (`basic_risk.py:790-837`) and
   `BudgetBasedSizer._get_regime_factor` (`position_sizer.py:111-137`) both floor missing-but-configured
   data to `min(scale map)` and clamp the posterior-EV at `min(1.0, ev)`. The two defaults are
   **aligned** (this closes the "divergent fail-safe" risk the owning skill doc flags as a historical
   concern) and both are enforced at the value level, not just by config discipline — tested at
   `test_basic_risk.py:653-661` and `test_position_sizer.py:88-113`.
7. Sizer (quantity) and risk engine (position *limit*) regime scaling operate **in series, not in
   parallel** — the risk engine never injects a regime factor into `RiskVerdict.scaling_factor`; it
   only tightens `adjusted_max` (`basic_risk.py:190-191`, `257-258`). No multiplicative double-scaling
   exists between the two regime consumers (§6).
8. The **only** path in the risk layer that can legitimately size *above* the single-factor baseline —
   `EdgeWeightedSizer`'s edge/vol tilt, up to a combined `3.0×` (`edge_weighted_sizer.py:44-70`) — is
   config-gated off at every level by default (`platform_config.py:374-386`), SIGNAL-path only (the
   PORTFOLIO path never calls a `PositionSizer`), always re-capped at `max_position_per_symbol` and
   floored at 0 (`edge_weighted_sizer.py:286-289`), and is thoroughly tested
   (`tests/risk/test_edge_weighted_sizer.py`, 25 tests). **[intentional design]**, documented as such
   in-line and in `risk_engine_audit_2026-06-20.md`.
9. Per-leg veto on `check_sized_intent` is correctly isolated: `REJECT` drops only the offending leg,
   `FORCE_FLATTEN` on any leg aborts the **entire** intent and requests global escalation, exceptions
   from a per-leg `check_order` are contained (not propagated), legs are lexicographically ordered for
   replay parity, and admitted-leg gross accumulates cumulatively across legs via `additional_exposure`
   so K individually-clearing legs cannot collectively breach the cap (`sized_intent_orders.py:71-203`).
   Well tested (§4).
10. **P2** — the PORTFOLIO per-leg `SCALE_DOWN` path floors the scaled quantity at 1 share
    (`sized_intent_orders.py:168-175`, `max(1, ...)`), so a scale-down that should reduce a small
    order to zero instead always emits at least 1 share. Bounded (never exceeds the pre-scale
    quantity) and low-materiality, but inconsistent with the standalone SIGNAL path's
    `_compose_scaled_quantity` (`orchestrator.py:4838-4841`), which correctly allows suppression to
    zero (§3, Finding **FS-3**).
11. The `RiskLevel` escalation SM (`escalation.py:19-59`) is structurally monotone-tightening: the
    transition table permits only forward movement plus the single `LOCKED → NORMAL` loosening edge;
    any other edge raises `IllegalTransition`. `_escalate_risk` (`orchestrator.py:3599-3668`) walks
    all remaining stages from whatever level it is re-entered at (sequential `if`, not `elif`), so a
    second breach mid-cascade cannot skip stages. No autonomous (non-human-gated) caller of
    `RiskLevel.NORMAL` was found (§5).
12. Buying-power and PDT/RTH entry gates are correctly exit-exempt
    (`opens_or_increases_signed`-gated) and the 4×-intraday/2×-overnight arithmetic over live NAV is
    correct and well tested (`test_bt15_buying_power.py`); the one gap is the gate-ordering
    interaction in item 2. `tests/risk/test_buying_power.py` has no direct unit test of the
    non-positive-equity → `Decimal("0")` branch (`buying_power.py:49-50`) (§7, §8).
13. Reconfirmed still-open from `risk_engine_audit_2026-06-18.md` (**P2**, not re-derived, no new
    evidence found that changes the assessment): no NaN/inf sanitization on a *custom*
    `RegimeEngine`'s posteriors at the risk/sizer boundary — `min(1.0, float("nan"))` evaluates to
    `1.0` in Python, i.e. a poisoned custom engine fails to the **unscaled baseline**, not the
    fail-safe minimum (`basic_risk.py:837`, `position_sizer.py:137`). The shipped `HMM3StateFractional`
    engine sanitizes its own posteriors and is not affected (regime-detection skill, Failure Modes
    table). **[modeling choice / extensibility gap]**.
14. `RegimeState` is written once per tick at M2 (`orchestrator.py:2397-2401`, before M5/M6 at
    `2607`/`2806`), confirming `current_state()` reads at risk-check time always see the same tick's
    posterior the regime gate saw — consistent with the documented single-writer contract.
15. All mandated read-only verification commands pass (see header); 210 risk-scoped tests total,
    0 failures. No production code, tests, or configs were modified in this pass.

---

## 2. Risk-control inventory

| Entry point | Caller / trigger | Input | Scaling / limit applied | Default (unwired / unconfigured) behavior |
|---|---|---|---|---|
| `check_signal` | Orchestrator M5, once per SIGNAL alpha signal (`orchestrator.py:2607`) | `Signal` + `PositionStore` | Regime-adjusted `max_position_per_symbol` (`basic_risk.py:190-191`); shared exposure/drawdown/scale-down (`_check_exposure_and_drawdown`) | `ALLOW` if within static config limits; regime factor is `1.0` with no engine wired |
| `check_order` | Orchestrator M6 (`orchestrator.py:2806`); hazard bridge (`orchestrator.py:6294`); per-leg via `check_sized_intent` | `OrderRequest` + `PositionStore` + `additional_exposure` (cumulative, default `0`) | PDT min-equity, buying power, RTH session, post-fill position cap, prospective gross exposure, drawdown, scale-down (`basic_risk.py:231-332`) | PDT/buying-power/RTH gates individually **fail open** (return `None`, i.e. pass) when unwired — `warn_on_inert_entry_gates` surfaces this at construction for PAPER/LIVE (`basic_risk.py:140-157`) |
| `check_sized_intent` | Orchestrator `CROSS_SECTIONAL` flush, once per PORTFOLIO alpha per boundary (`orchestrator.py:2041`) | `SizedPositionIntent` + `PositionStore` | Delegates per-leg to `check_order` via `build_sized_intent_orders`; per-leg veto; cumulative `additional_exposure` across legs (`sized_intent_orders.py:71-203`) | Empty `target_positions` → empty result, no-op (`sized_intent_orders.py:104-105`) |
| `BudgetBasedSizer.compute_target_quantity` | SIGNAL-path `IntentTranslator`, pre-risk sizing | `Signal` + `AlphaRiskBudget` + price + equity | `strength` clamped `[0,1]` × regime EV factor clamped `≤1.0` (min-scale on missing data) (`position_sizer.py:80-137`) | Regime factor `1.0` with no engine; `0` shares on non-positive price/equity |
| `EdgeWeightedSizer.compute_target_quantity` | SIGNAL-path, opt-in via `sizer_tilt_drive` (`bootstrap.py:553`) | Wraps `BudgetBasedSizer` + optional edge/vol/inventory providers | `edge × vol × inventory` tilt, each factor and the combined product independently clamped (`edge_weighted_sizer.py:114-289`); re-capped at `max_position_per_symbol`, floored at `0` | All three factors OFF by default → tilt `1.0`, byte-identical to base sizer (parity by construction) |
| `BasicRiskEngine._regime_scaling` | Inside `check_signal`/`check_order`, limit only (never `scaling_factor`) | `symbol → RegimeEngine.current_state()` | EV over posterior × scale map, clamped `min(1.0, ev)` (`basic_risk.py:790-837`) | No engine → `1.0` (explicit opt-out); engine with no committed posterior → `min(scale map)` |
| `HazardExitController` | Bus subscriber on `RegimeHazardSpike` / `Trade`, opt-in per PORTFOLIO/SIGNAL alpha via `hazard_exit.enabled: true` | Live position + hazard score / position age | None — always a full close at current `abs(position.quantity)` (`hazard_exit.py:289-306`) | Inert (`attach()` no-ops) unless ≥1 alpha registers a policy (`hazard_exit.py:196-206`) |
| Risk escalation SM | `Orchestrator._escalate_risk`, invoked on any `FORCE_FLATTEN` verdict or `requires_global_risk_escalation` | `RiskLevel` state (no input scaling — a mode, not a multiplier) | Monotone-tightening transition table (`escalation.py:29-59`) | `NORMAL` at construction; forward-only until human-gated reset |
| `_check_buying_power` | Inside `check_order`, entry-only (`basic_risk.py:557-615`) | Live NAV, phase (intraday/overnight), prospective gross | `equity × {4, 2}` (`buying_power.py:43-56`); `0` on non-positive equity | Inert (`None`) if `buying_power_config` not wired — but bootstrap wires it unconditionally (`bootstrap.py:411-415`) for all modes |
| `_check_pdt_min_equity` / `_check_rth_session` | Inside `check_order`, entry-only | PDT round-trip count / trading-session bounds | Binary REJECT on ENTRY below `$25k` PDT floor / outside RTH | Inert (`None`) if not wired |

---

## 3. Fail-safe audit (Inv-11) — every exposure-increasing path

### 3.1 Every multiplicative factor in the risk/sizing path, and its ceiling

| Factor | Location | Ceiling | Enforcement |
|---|---|---|---|
| `strength` (signal conviction) | `position_sizer.py:100` | `1.0` | `min(1.0, max(0.0, signal.strength))` — value-level clamp, "audit R-8" |
| Regime EV factor (sizer) | `position_sizer.py:130-137` | `1.0` | `min(1.0, ev)` — value-level clamp, "audit P1 R-1" |
| Regime EV factor (risk limit) | `basic_risk.py:833-837` | `1.0` | `min(1.0, ev)` — value-level clamp, "audit P1 R-1" |
| `SCALE_DOWN` factor (`_check_exposure_and_drawdown`) | `basic_risk.py:765-786` | `1.0` | Mathematically bounded to `(0, 1]` by construction (linear interpolation between the scale-down threshold and the hard cap), then clamped `max(0.1, min(1.0, scaling))` |
| Composed `SCALE_DOWN` (SIGNAL path, gate-1 × gate-2) | `orchestrator.py:4838-4841` | `1.0` | Each factor clamped to `[0.0, 1.0]` *before* taking `min(...)` — cannot compound above `1.0` |
| `EdgeWeightedSizer` edge factor | `edge_weighted_sizer.py:118-127` | `edge_cap` (default `2.0`) | Explicit `_clamp`; **can exceed `1.0`** — see below |
| `EdgeWeightedSizer` vol factor | `edge_weighted_sizer.py:130-141` | `vol_cap` (default `2.0`) | Explicit `_clamp`; **can exceed `1.0`** |
| `EdgeWeightedSizer` inventory factor | `edge_weighted_sizer.py:144-154` | `1.0` | Explicit `_clamp(..., 1.0)` — taper-only, documented as never amplifying |
| `EdgeWeightedSizer` combined tilt | `edge_weighted_sizer.py:251` | `tilt_cap` (default `3.0`) | Explicit `_clamp`; then `apply_tilt` re-caps at `max_position_per_symbol` and floors at `0` (`edge_weighted_sizer.py:286-289`) |

**Conclusion on A.1 ("enumerate every path that can increase exposure vs. baseline"):** exactly one
family of factors — the `EdgeWeightedSizer` edge/vol/combined tilt — can produce a target quantity
above the single-factor baseline. Every other multiplier in the risk/sizing path (signal strength,
both regime-EV consumers, both `SCALE_DOWN` paths) is clamped to `≤1.0` at the value level, not just
by configuration discipline, and each clamp has a dedicated test
(`test_basic_risk.py:653`, `test_position_sizer.py:88`, `test_dual_scale_down_e2e.py:109`).

The `EdgeWeightedSizer` amplification path satisfies the audit's "requires explicit config / human
authorization, not autonomous" bar:

- Every enabling flag defaults to `False` (`sizer_tilt_drive`, `sizer_edge_weighting_enabled`,
  `sizer_vol_targeting_enabled`, `sizer_inventory_penalty_enabled` — `platform_config.py:374-386`).
- `sizer_tilt_drive` gates whether the tilted sizer drives the **live** decision at all; when off
  (default) the tilt is computed only for a shadow measurement stream and the live size stays
  single-factor (`bootstrap.py:527-553`, comment: *"a conscious, re-baselined per-deployment choice
  rather than a platform-wide default"*).
- The PORTFOLIO layer never constructs or calls a `PositionSizer` — `CompositionEngine` derives
  `target_usd` directly from the ranked/neutralized/optimized cross-sectional weights
  (composition-layer skill). This amplification path is **SIGNAL-only**.
- The result is still subject to every downstream `check_order` gate (position limit, gross exposure,
  buying power, drawdown) exactly like any other sized order — amplification changes the *input* to
  the normal risk pipeline, it does not bypass any gate.

**Verdict: [intentional design], correctly scoped, off by default, well tested.** No action needed
beyond what `risk_engine_audit_2026-06-18.md` (backlog item 6) already recommended: an explicit
deployment-time acknowledgment artifact when `sizer_tilt_drive: true` ships to PAPER/LIVE. Still open;
not re-verified further this pass.

### 3.2 Missing / unknown regime data → does it reduce exposure?

Both consumers are aligned (this directly answers the audit's D.1 question — "prove `basic_risk`
and `position_sizer` defaults are aligned"):

| Condition | `BasicRiskEngine._regime_scaling` | `BudgetBasedSizer._get_regime_factor` |
|---|---|---|
| No engine configured | `1.0` (explicit operator opt-out) — `basic_risk.py:820-821` | `1.0` (same rationale) — `position_sizer.py:117-118` |
| Engine configured, no posterior yet for symbol | `min(scale map)` — `basic_risk.py:824-825` | `min(factor map)` — `position_sizer.py:121-122` |
| Unknown state name in posterior | `default` = `min(scale map)` in the EV sum — `basic_risk.py:828-830` | same — `position_sizer.py:125-127` |
| EV computed | `min(1.0, ev)` | `min(1.0, ev)` |

This alignment is itself the fix for a divergence the owning skill doc (`risk-engine/SKILL.md`)
flags as a historical risk ("an earlier draft... described argmax"). Both are tested directly
(`test_basic_risk.py:628-661`, `TestRegimeMissingDataFailsSafe`; `test_position_sizer.py:185-198`,
same class name) — **no gap found**.

**Reconfirmed open (P2, from `risk_engine_audit_2026-06-18.md`, not re-derived):** neither consumer
sanitizes a *custom* `RegimeEngine`'s posterior values before use. `min(1.0, ev)` where `ev` is `NaN`
evaluates to `1.0` under Python's `min()` semantics (NaN comparisons are always `False`, so the
first/left operand — here the literal `1.0` — is retained), i.e. a poisoned custom engine's NaN
posterior fails to the **unscaled baseline**, not the intended fail-safe minimum. No `isnan`/`isfinite`
guard exists in `basic_risk.py` or `position_sizer.py` (grep confirms zero hits). The shipped
`HMM3StateFractional` engine already sanitizes NaN/inf internally and substitutes a uniform prior
(regime-detection skill, Failure Modes table), so this is only reachable through a third-party
`RegimeEngine` implementation registered via `register_engine(...)` — an extensibility gap, not a
live exploit against the shipped engine. **[modeling choice]** — recommend a defensive
`math.isfinite` guard at the two EV call sites regardless, since the `RegimeEngine` protocol does not
contractually forbid NaN.

### 3.3 Internal error in a check → veto, not pass?

- **Per-leg (`check_sized_intent`)**: `build_sized_intent_orders` wraps each per-leg `check_order`
  call in `try/except Exception`; a raise is logged and the leg is veto-dropped (treated like
  `REJECT`), never propagated (`sized_intent_orders.py:146-158`, "audit R-2"). Tested directly:
  `test_basic_risk.py:565-602`, `TestSizedIntentRaisingCheckContained`.
- **Standalone SIGNAL/ORDER gates**: `check_signal`/`check_order` themselves have no internal
  try/except, but the orchestrator's tick-processing loop has a documented
  *"mid-tick exception → DEGRADED"* contract (module docstring, `orchestrator.py:30`), concretely
  implemented at multiple call sites (`orchestrator.py:1509`, `1543`, `1579`, `1610`, `2175`,
  `2212-2230`). An unhandled exception inside a risk check aborts the tick and moves macro to
  `DEGRADED` rather than falling through to order submission — fail-safe by construction, though this
  is a kernel-level (not risk-layer-level) guarantee and was not re-verified line-by-line against
  every call path in this pass (kernel internals are out of this audit's declared scope).
- **Exhaustiveness guards**: any `RiskAction` returned from `check_signal`/`check_order` that is not
  in `{ALLOW, SCALE_DOWN}` after the `FORCE_FLATTEN`/`REJECT` branches raises `ValueError` at both M5
  (`orchestrator.py:2669-2673`) and M6 (`orchestrator.py:2892-2899`), explicitly commented
  *"Fail-safe: aborting order path."* This means a future `RiskAction` member added without matching
  orchestrator-side handling fails closed, not open. The per-leg veto loop
  (`build_sized_intent_orders`) has no equivalent exhaustiveness guard — it explicitly enumerates
  `FORCE_FLATTEN`/`REJECT`/`SCALE_DOWN` and implicitly treats anything else as `ALLOW` (falls through
  to the "accept the leg" path at `sized_intent_orders.py:193-198`). Today `RiskAction` has exactly
  four members (`ALLOW`, `SCALE_DOWN`, `REJECT`, `FORCE_FLATTEN` — `core/events.py:269-272`), so this
  is currently latent, not live. **P2** — recommend either an explicit `else: raise` in
  `build_sized_intent_orders` mirroring the M5/M6 guards, or a comment recording that the four-member
  enum is relied upon being exhaustive.

### 3.4 Finding HZ-1 (P0, reasoned from code) — hazard-exit cross-reason double-fire can reverse a position

**Component:** `HazardExitController` (`risk/hazard_exit.py`) + the orchestrator hazard bridge
(`kernel/orchestrator.py:6246`, `_on_bus_hazard_order`).

**Mechanism:**

1. `HazardExitController` tracks "already emitted" suppression **per `(strategy_id, symbol, reason)`**
   (`hazard_exit.py:184-185`), where `reason ∈ {HAZARD_SPIKE, HARD_EXIT_AGE}`
   (`hazard_exit.py:104-108`). These are two **independent** keys for the same symbol.
2. The only "don't act again" guard inside `_maybe_emit_exit` besides the per-reason key is
   `if position.quantity == 0: return` (`hazard_exit.py:277-279`) — i.e. it trusts the live
   `PositionStore` to already reflect any prior exit's fill.
3. Both triggers compute the same full-close quantity from the **current** (possibly stale)
   position: `quantity = abs(position.quantity)` (`hazard_exit.py:290`).
4. `EventBus.publish` is fully synchronous (`bus/event_bus.py:59-68`, handlers run to completion
   before `publish()` returns), and in **BACKTEST** the router fills and the orchestrator reconciles
   the fill back into `PositionStore` synchronously within that same call chain (traced via
   `_on_bus_hazard_order` → `self._backend.order_router.submit(event)` →
   `self._poll_order_router_acks(...)` → `self._reconcile_fills(...)`,
   `orchestrator.py:6357-6382`) — so in BACKTEST, by the time a second trigger is evaluated, the flat
   check at `hazard_exit.py:278` correctly sees the reconciled position and the second trigger no-ops.
5. In **PAPER/LIVE**, the orchestrator's own code explicitly documents that this synchronous
   assumption does **not** hold: *"Paper/live IB acks land asynchronously; backtest fills are
   synchronous"* (`orchestrator.py:4965-4966`), and the very next sentence confirms
   *"Hazard-exit orders bypass this path [the pending-order conflict filter] via
   `_on_bus_hazard_order` (Inv-11)"* (`orchestrator.py:4968-4969`) — i.e. the one mechanism in this
   codebase that exists specifically to stop a second order landing on a symbol with an unfilled
   order in flight (`_has_pending_order_for_symbol`, `_filter_portfolio_orders_for_pending_conflicts`,
   used by the PORTFOLIO path at `orchestrator.py:2059`/`2129`) is **deliberately not applied** to
   hazard orders, on the reasoning that exit-only orders are always safe to duplicate.
6. That reasoning holds for a *delta* reduce, but `HazardExitController` emits a *snapshot* full
   close, not a delta. If a `RegimeHazardSpike` (reason `HAZARD_SPIKE`) and a `Trade`-driven hard-age
   check (reason `HARD_EXIT_AGE`) both become true for the same open symbol before the first exit
   order's fill is acked and reconciled, the controller emits a **second**, independently-keyed,
   full-size exit order — sized identically to the first, because the position snapshot has not
   changed yet. `order_id` differs (SHA-256 includes `reason` and `trigger_ts_ns`,
   `hazard_exit.py:292`), so the orchestrator's own dedup set
   (`_hazard_submitted_order_ids`, keyed on exact `order_id`, `orchestrator.py:6291-6293`) does not
   catch this either — it only prevents a literal duplicate publish of the *same* order.
7. If both orders eventually fill, the net executed quantity is `2 × |original position|` in the
   closing direction — flattening the original position **and then opening a new, equal-and-opposite
   position** that never went through `check_signal`/`check_order`'s ordinary sizing or limit checks
   (the hazard path only runs a *defensive* `check_order`, and even a `REJECT` there is overridden
   for a verifiably-reducing order per `orchestrator.py:6308-6335` — by design, since each order,
   evaluated alone, does reduce the position as of when it was priced).

**Why this is exit-only in intent but not in aggregate:** each individual `OrderRequest` the
controller emits is, by construction, sized and directed to fully close the position **as observed
at that instant** — so no single order can be shown to *increase* exposure. The invariant break is at
the level of *two* orders racing against one unreconciled fill, which is a class of bug the per-order
exit-only proof does not cover.

**Confidence:** the suppression-key gap and the flat-check-only guard are directly confirmed by
reading `hazard_exit.py`; the async-ack precondition is directly confirmed by the orchestrator's own
comment (not inferred); the *consequence* (net position reversal) follows deterministically from the
sizing formula once the precondition holds. What is **not** independently reproduced in this pass is
actual IB Gateway ack latency (no broker connection in this environment, and this audit is read-only)
— so this is reported as **P0-by-mechanism, unconfirmed-by-live-reproduction**. See §10.

**Test gap:** `tests/risk/test_hazard_exit.py:323-355`
(`test_episode_suppression_prevents_double_fire`) tests only the same-reason case (two `HAZARD_SPIKE`
events); it does not feed a `HARD_EXIT_AGE`-qualifying `Trade` alongside an unresolved `HAZARD_SPIKE`
on the same symbol. No test in `tests/integration/test_hazard_exit_e2e.py` or
`tests/determinism/test_hazard_exit_replay.py` exercises overlapping trigger reasons either.

**Recommended direction (not implemented in this pass):** add a per-symbol (not per-reason) "exit
already in flight" guard to `HazardExitController` — e.g. track submitted-but-unconfirmed hazard
`order_id`s per symbol and suppress a second reason's trigger until either the position store reflects
the fill *or* the in-flight order is cancelled/rejected. Add a property/unit test that fires both
reasons for the same symbol before any fill reconciles and asserts exactly one order is emitted.

### 3.5 Finding FS-2 (P1) — non-positive-equity `FORCE_FLATTEN` is unreachable for ENTRY orders once buying power is wired

**Component:** `BasicRiskEngine.check_order` (`risk/basic_risk.py:231-332`) gate ordering, interacting
with `buying_power_limit` (`risk/buying_power.py:43-56`) and `bootstrap.py:411-415`.

**Mechanism:**

1. `check_order`'s gate order is: PDT (`basic_risk.py:265-272`) → buying power
   (`274-282`) → RTH (`284-290`) → post-fill position cap (`292-303`) → prospective gross
   exposure + drawdown, i.e. `_check_exposure_and_drawdown` (`313-323`).
2. `_check_exposure_and_drawdown`'s non-positive-equity branch
   (`basic_risk.py:729-737`) is the code's own stated "unconditional" fail-safe: *"the only correct
   response is `FORCE_FLATTEN`... returned unconditionally and independent of how loosely
   `max_drawdown_pct` is configured"* (docstring, `basic_risk.py:717-725`, "audit R-6").
3. But `_check_buying_power` runs **first**, and only no-ops for orders that do not
   `opens_or_increases` (`basic_risk.py:578-579`) — i.e. it is active for every entry/increase order.
   `buying_power_limit(equity, ...)` returns `Decimal("0")` whenever `equity <= 0`
   (`buying_power.py:49-50`). For any entry order with a resolvable mark, `prospective > limit(=0)`
   is trivially true, so `_check_buying_power` returns
   `REJECT(reason=INSUFFICIENT_BUYING_POWER)` (`basic_risk.py:595-614`) and `check_order` returns
   **that** verdict immediately — the function never reaches `_check_exposure_and_drawdown` at all.
4. `bootstrap.py:411-415` constructs `BuyingPowerConfig` and wires it into `BasicRiskEngine`
   unconditionally — there is no `if config.mode == ...` guard around this construction (confirmed by
   reading `bootstrap.py:385-429` in full); it applies to BACKTEST, PAPER, and LIVE alike. Only
   `warn_on_inert_entry_gates` (a logging-only flag) is mode-conditional.
5. Net effect: once equity is wiped out (e.g. an existing position's unrealized loss drives live NAV
   to zero or negative), **new entry orders are individually rejected** (a fail-safe outcome in
   isolation — no new exposure is added), but the risk escalation SM is **never engaged**, the kill
   switch is **never activated**, and `_emergency_flatten_all` (which force-closes **every** open
   position, including ones on symbols with no new order arriving) **never runs**. If the alpha logic
   generating entries doesn't independently know equity is gone, the book can sit at zero/negative
   equity indefinitely, with existing (possibly still-losing) positions on other symbols left
   completely unmanaged, contradicting the code's own "unconditional" framing.
6. A reducing/exit order arriving while equity ≤ 0 is unaffected by this gap:
   `_check_buying_power` no-ops for it (`578-579`), so it correctly reaches
   `_check_exposure_and_drawdown` and triggers the intended `FORCE_FLATTEN` (which itself submits
   market orders to close **everything**, not just the triggering symbol, via
   `_emergency_flatten_all`). The gap is specifically: *if the first order to reach `check_order`
   after equity goes non-positive is an entry, the global flatten never fires from that order*.

**Confirms the gap is real, not just theoretical:** the one existing test asserting this fail-safe
(`test_basic_risk.py:604-625`, `TestNonPositiveEquityForceFlattens`) constructs
`BasicRiskEngine(cfg)` with **no** `buying_power_config` argument (defaults to `None`,
`basic_risk.py:99`), so `_check_buying_power` no-ops there (`576-577`) regardless of the order's
direction, and the test's own order is a `BUY` (entry) on a **new** symbol (`MSFT`, current
qty `0`) — i.e. this test exercises exactly the code path this finding says is bypassed in the
realistic (bootstrap-wired) configuration, but does so with a configuration that doesn't reflect how
`bootstrap.py` actually constructs the engine.

**Severity reasoning:** does not meet the strictest P0 bar (no single order's exposure increases —
the entry is correctly rejected), but it is a genuine failure of the platform's own "unconditional"
de-risking guarantee to trigger when it is supposed to, with real-money consequences in PAPER/LIVE.
Rated **P1**, flagged as high-severity within that tier.

**Recommended direction (not implemented in this pass):** either (a) check non-positive equity before
the buying-power gate in `check_order` so `FORCE_FLATTEN` is truly unconditional regardless of order
direction, or (b) have `_check_buying_power` special-case `equity <= 0` to return `FORCE_FLATTEN`
instead of `REJECT(INSUFFICIENT_BUYING_POWER)`. Add a test that wires `BuyingPowerConfig` (matching
`bootstrap.py`'s actual construction) and asserts `FORCE_FLATTEN` — not `REJECT` — on an entry order
submitted while equity is non-positive.

### 3.6 Finding FS-3 (P2) — `SCALE_DOWN` floor forces a minimum 1-share order on the PORTFOLIO path

`build_sized_intent_orders`'s `SCALE_DOWN` handling (`sized_intent_orders.py:167-177`):

```python
scaled_qty = max(
    1,
    int((Decimal(quantity) * Decimal(str(verdict.scaling_factor))).to_integral_value(
        rounding=ROUND_HALF_UP
    )),
)
```

`_check_exposure_and_drawdown`'s scaling factor floors at `0.1` (`basic_risk.py:777`), so a small
pre-scale quantity (1–4 shares) scaled by `0.1` rounds to `0` under `ROUND_HALF_UP`, and `max(1, 0)`
forces the leg to still submit **1 share** — the scale-down can never fully suppress a small leg.
This is bounded (`scaled_qty` cannot exceed the pre-scale `quantity`, since `scaling_factor ∈ [0.1,
1.0]`) and immaterial in absolute terms, but it is inconsistent with the standalone SIGNAL path's
`_compose_scaled_quantity` (`orchestrator.py:4838-4841`, `round(base_quantity * capped)`, no floor),
which correctly allows a scale-down to suppress the order entirely
(`orchestrator.py:2871-2888`, `scaled_qty <= 0` → `NO_ORDER`). No test exercises the floor case
specifically — the one decimal-rounding test for this path
(`test_basic_risk.py:664-700`, `test_scale_down_quantity_uses_half_up_not_float_truncation`) uses
`scaling_factor=0.45` on `quantity=10`, which does not hit the floor. **[bug, low materiality]** —
recommend either removing the `max(1, ...)` floor (let a full-suppression scale-down drop the leg,
mirroring the SIGNAL path) or documenting why a portfolio leg must never fully suppress via
`SCALE_DOWN`.

### 3.7 Covered fail-safe paths (no gap found)

- Per-leg exceptions in `check_sized_intent` are contained, not propagated
  (`sized_intent_orders.py:146-158`; `test_basic_risk.py:568`).
- Cumulative gross/buying-power caps across portfolio legs via `additional_exposure`
  (`sized_intent_orders.py:87-109`, `193-197`; `test_basic_risk.py:512-563`).
- Non-positive equity force-flattens rather than falling back to initial `account_equity`
  (`basic_risk.py:717-737`; `test_basic_risk.py:604-625`) — correct for the *reducing-order* and
  *no-buying-power-gate* cases; see Finding FS-2 for the gap.
- `resolve_mark` returns `Decimal("0")` (never raises, never guesses) when no live mark or
  cost-basis is available, and callers treat `0` as "skip this leg" (`sized_intent_orders.py:40-68`).
- Both regime-scaling consumers clamp at `min(1.0, ev)` at the value level (§3.2).
- Hazard-exit orders are exit-direction-only *per order* (side always opposite the position sign,
  quantity `== abs(position.quantity)` at emission time — `hazard_exit.py:289-290`); the aggregate
  gap is Finding HZ-1, not a per-order direction bug.
- **Confirmed fixed since `risk_engine_audit_2026-06-20.md`**: the hazard bridge's `REJECT`-but-submit
  behavior is now gated on independently re-deriving `order_reduces`
  (`orchestrator.py:6302-6304`), and only a **non-reducing** `REJECT` blocks submission
  (`orchestrator.py:6310-6335`) — a reducing order's `REJECT` is logged and still submitted, which is
  the correct Inv-11 reading (a check designed to stop *increases* should not be able to trap an
  *exit*). The prior report's P0 is resolved.
- **Confirmed fixed since `risk_engine_audit_2026-06-20.md`**: `AlphaBudgetRiskWrapper.check_order`'s
  per-alpha exposure cap now exempts reducing orders (`order_reduces`,
  `risk_wrapper.py:231-246`), matching the signal-level exemption
  (`risk_wrapper.py:88-100`). The prior report's P1 is resolved.

---

## 4. Per-leg veto audit (`SizedPositionIntent` → legs)

Single canonical implementation shared by both risk surfaces — `BasicRiskEngine.check_sized_intent`
(`basic_risk.py:334-396`) and `AlphaBudgetRiskWrapper.check_sized_intent`
(`risk_wrapper.py:252-283`) both delegate to `build_sized_intent_orders`
(`sized_intent_orders.py:71-203`), so the two paths cannot drift — the wrapper routes each per-leg
`check_order` through **itself** (`risk_wrapper.py:281`, `check_order=self.check_order`) so per-alpha
budget gates apply to PORTFOLIO legs too, addressing what an in-line comment calls "the only
production-reachable order path post-D.2" (`risk_wrapper.py:264-267`).

Traced contract, symbol-by-symbol:

1. **Determinism**: `for symbol in sorted(intent.target_positions)` (`sized_intent_orders.py:110`) —
   lexicographic iteration, locked by the L4 portfolio-order parity test
   (`tests/determinism/test_portfolio_order_replay.py`).
2. **Mark resolution**: `resolve_mark` prefers `positions.latest_mark(symbol)`, falls back to
   `avg_entry_price`, returns `Decimal("0")` (never raises) if neither exists
   (`sized_intent_orders.py:40-68`). A `mark <= 0` leg is skipped via `continue`
   (`sized_intent_orders.py:114-115`) — not counted as a dropped/veto'd leg (no alert, no order).
3. **Share conversion**: `target_shares = round_half_up(target_usd / mark)`
   (`sized_intent_orders.py:117-121`) — `Decimal` arithmetic throughout, never float.
4. **No-op detection**: `delta_shares == 0` → `continue` (`122-124`) — a leg whose target already
   matches current notional produces **no** order and is explicitly documented as not counted as a
   veto-dropped leg (`basic_risk.py:387-389`).
5. **Order construction**: `order_id = derive_order_id(f"{correlation_id}:{sequence}:{symbol}")` —
   deterministic SHA-256, no randomness (`sized_intent_orders.py:129`); `reason="PORTFOLIO"` stamped
   on every emitted leg (`sized_intent_orders.py:142`, confirming the audit's B.3 ask) for forensic
   lineage; `g12_disclosed_cost_total_bps` carried per-symbol from the intent
   (`sized_intent_orders.py:130,143`).
6. **Risk verdict dispatch** (`check_order(order, positions, additional_exposure=running_extra)`,
   `sized_intent_orders.py:147`), wrapped in `try/except`:
   - Raises → leg veto-dropped, logged, loop continues (`148-158`).
   - `FORCE_FLATTEN` → **immediate return** of `SizedIntentRiskResult(orders=(), requires_global_risk_escalation=True)`
     (`159-163`) — the entire intent is discarded, not just the offending leg. This is the one
     "whole-intent" exception to per-leg veto, and it is intentional: a drawdown-driven
     `FORCE_FLATTEN` on any leg is meant to trigger the same global emergency-flatten +
     `RiskLevel.LOCKED` cascade as a standalone SIGNAL breach
     (`basic_risk.py:363-378`, cross-referenced in the risk-engine skill).
   - `REJECT` → `dropped.append((symbol, verdict.reason)); continue` (`164-166`) — **only that leg**
     is dropped; the loop proceeds to the next symbol. This is the true per-leg veto.
   - `SCALE_DOWN` → leg is rebuilt at the scaled quantity (see Finding FS-3 for the `max(1, ...)`
     floor caveat), quantity re-derived deterministically, order re-emitted with the same
     `order_id`/attribution (`167-191`).
7. **Cumulative cap tracking** ("audit R-1"): each admitted leg's signed gross-notional delta is
   folded into `running_extra` (`193-197`) and passed as `additional_exposure` to the **next** leg's
   `check_order` call — without this, K legs that each individually clear the gross/buying-power cap
   in isolation could collectively breach it; tested directly at
   `test_basic_risk.py:512-563` (`TestSizedIntentCumulativeGrossCap`, both the breach and
   pass-within-cap cases).
8. **Diagnostics**: if any legs were dropped, `on_dropped_legs(intent, dropped)` fires
   (`sized_intent_orders.py:200-201`) → `BasicRiskEngine._emit_dropped_legs_alert`
   (`basic_risk.py:398-450`), which always logs at `WARNING` and additionally publishes an `Alert`
   event (when a bus + sequence generator were wired) explicitly stating that *"any dollar-neutral /
   sector-neutral / mechanism-cap invariant the alpha intended is NOT re-validated after the drop"*
   (`basic_risk.py:438-440`) — the residual cross-sectional risk is surfaced, not silently absorbed.
   Tested: `test_basic_risk.py:343-433`.

**Orchestrator consumption** (`_flush_pending_sized_intents`, `orchestrator.py:1992-2114`): receives
the already-vetted `SizedIntentRiskResult` from `check_sized_intent`, checks
`requires_global_risk_escalation` first (→ `_escalate_risk`, `2042-2048`), then submits the surviving
orders as-is through an additional `_filter_portfolio_orders_for_pending_conflicts` pass
(`2059-2070`, guards against a later boundary's leg duplicating an in-flight order — see §3.4 for why
this same guard is deliberately **not** applied to hazard orders) before walking the normal
`ORDER_DECISION → ORDER_SUBMIT → ORDER_ACK → POSITION_UPDATE` micro-states per leg. No additional veto
logic is duplicated at the orchestrator level — a clean separation of concerns between "decide" (risk
layer) and "execute" (orchestrator).

**Audit conclusion: per-leg veto is sound.** Determinism, isolation, cumulative-cap correctness, and
diagnostic surfacing are all implemented as specified and tested. The one caveat is Finding FS-3
(bounded, P2). Residual cross-sectional risk from partial execution (a surviving leg subset that no
longer satisfies the alpha's intended dollar/sector neutrality) is a **known, alerted, accepted**
design gap carried from `risk_engine_audit_2026-06-18.md`/`-06-20.md` (backlog item: "define
all-or-none semantics for portfolio alphas that cannot tolerate partial legs") — still open, not
re-derived as new in this pass.

---

## 5. Escalation SM audit

### States and transitions

`RiskLevel` (`escalation.py:19-26`): `NORMAL → WARNING → BREACH_DETECTED → FORCED_FLATTEN → LOCKED`.

Transition table (`escalation.py:29-59`), reproduced for clarity:

| From | Permitted to |
|---|---|
| `NORMAL` | `WARNING` |
| `WARNING` | `BREACH_DETECTED` |
| `BREACH_DETECTED` | `FORCED_FLATTEN` |
| `FORCED_FLATTEN` | `LOCKED` |
| `LOCKED` | `NORMAL` |

`StateMachine.__init__` (`core/state_machine.py:90-101`) validates the table is total over the enum
(every `RiskLevel` member must appear as a key, even if terminal) — a missing entry raises at
construction, so the table cannot silently omit a state. `StateMachine.transition()`
(`core/state_machine.py:128-177`) raises `IllegalTransition` for any edge not in the table — e.g.
`WARNING → LOCKED` directly, or `BREACH_DETECTED → NORMAL` via `.transition()`, both raise. **No test
in this repository directly asserts this specific `_RISK_TRANSITIONS` table's illegal edges** (the
generic `StateMachine` mechanism is unit-tested in `tests/core/test_state_machine.py`, but the
risk-specific table's shape is only ever exercised indirectly, by orchestrator integration tests that
always walk the monotonic sequence forward) — see §8.

### Cascade (`_escalate_risk`, `orchestrator.py:3599-3668`)

Implemented as a sequence of `if level == X:` blocks (not `elif`), each reassigning `level` after a
successful transition, so a single call **walks every remaining stage** from wherever the SM is
currently sitting through to `LOCKED` — re-entrant and idempotent regardless of entry level. At
`FORCED_FLATTEN`, `_emergency_flatten_all` (`orchestrator.py:3670+`) attempts to close all non-zero
positions via market orders before the final transition to `LOCKED`; the transition's `trigger` string
records whether the flatten completed cleanly or left residual exposure
(`"positions_zero_flatten_complete"` vs. `"emergency_flatten_incomplete_residual_exposure"`,
`orchestrator.py:3641-3645`) — an audit trail for forensics even when the flatten itself is imperfect.
After reaching `LOCKED`, the kill switch is activated and macro transitions to `RISK_LOCKDOWN`
(`3649-3668`). **Monotone-tightening confirmed** — no code path re-enters this method with a target
below the current level.

### Loosening — human-gated, but asymmetric

Two methods exist to move `RiskLevel` off a non-`NORMAL` state; both require an `audit_token` (a
mandatory keyword argument with no default, so it cannot be omitted). Neither has any caller inside
the tick-processing path — both are operator-facing entry points on `Orchestrator`, confirmed by
grepping every reference to each method name in `src/feelies/`.

| | `unlock_from_lockdown` (`orchestrator.py:1646-1688`) | `reset_risk_escalation` (`orchestrator.py:1690-1708`) |
|---|---|---|
| Applicable from | `LOCKED` only (`assert_state(RISK_LOCKDOWN)`, `1664`) | `WARNING` / `BREACH_DETECTED` / `FORCED_FLATTEN` (raises if `LOCKED`, `1702-1703`; no-ops if already `NORMAL`, `1700-1701`) |
| Exposure precondition | **Yes** — `if exposure != Decimal("0"): raise RuntimeError(...)` (`1666-1671`) | **None** |
| Macro-state precondition | Must be `RISK_LOCKDOWN` (`1664`) | Must **not** be in `TRADING_MODES` (`1704-1705`, `macro.py:111`) |
| Audit token | Required kwarg | Required kwarg |
| Mechanism | `StateMachine.transition(NORMAL, ...)` — validated against the transition table (`LOCKED → NORMAL` is a legal edge) | `StateMachine.reset(...)` — **bypasses** the transition table unconditionally, jumps straight to `initial_state` (`core/state_machine.py:179-209`) |
| Side effects | Also resets the kill switch if active (`1684-1688`) | None beyond the SM state |
| Test coverage | One test, but it never exercises the exposure guard (position store is empty throughout — `test_orchestrator.py:1513-1549`) | **Zero** — no test in the repository calls this method |

**Finding ESC-1 (P1)**: `reset_risk_escalation` is the documented remediation path for *"when
`_escalate_risk()` was interrupted (callback exception) and the risk SM is stranded at `WARNING`,
`BREACH_DETECTED`, or `FORCED_FLATTEN`"* (`orchestrator.py:1693-1695`). A stranding at
`FORCED_FLATTEN` specifically means `_emergency_flatten_all` was either not yet attempted or was
interrupted mid-flight — i.e. the position book may **not** actually be flat. Unlike
`unlock_from_lockdown`, `reset_risk_escalation` has no check that `positions.total_exposure() ==
Decimal("0")` (or any other measure that the stranding is actually safe to clear) before returning
the SM to `NORMAL`. An operator invoking this method with a validly-issued `audit_token` — believing
they are simply un-sticking a callback-exception artifact — could resume `NORMAL` risk operations
(full `1.0×` limits, scale-down thresholds re-armed, no further escalation pending) while the book
still carries the very exposure that triggered the original breach.

This is **not** an autonomous reset (both the priors' 2026-06-18 audit and this pass confirm no
tick-driven or callback-driven caller exists — `orchestrator.py:1690-1708`'s only callers are external
per the grep above), so it does not meet the strictest P0 bar. But it is a real asymmetry between two
methods that exist for structurally similar purposes, it is undocumented as a difference (the two
docstrings do not cross-reference each other's guard), and it has **zero** test coverage — no test
would fail today if the exposure check were accidentally *added* to `unlock_from_lockdown` and never
added to `reset_risk_escalation`, or vice versa. Rated **P1**.

**Recommended direction (not implemented in this pass):** add an exposure-related precondition to
`reset_risk_escalation` appropriate to its use case (e.g. require exposure below some small tolerance,
or require an explicit `force=True` override with its own audit trail when exposure is non-zero, so
the "I know positions are still open and I am choosing to reset anyway" case is distinguishable from
the intended "flatten already completed, SM was just stranded" case). Add a test that seeds a non-zero
position, strands the SM at `FORCED_FLATTEN`, and asserts current behavior (reset succeeds with
exposure still open) so any future fix is a deliberate, reviewed behavior change rather than a silent
one.

### Determinism (Inv-5)

`TransitionRecord`s are stamped with the injected `Clock` (`escalation.py:62-69`,
`self._clock.now_ns()` inside `StateMachine.transition`/`reset`) and `correlation_id`; no wall-clock
or RNG involvement. `_escalate_risk`'s stage order is fixed by the `if` chain, not by iteration over
an unordered collection. **Sound** — consistent with the L-series replay parity hashes covering
`StateTransition` events (`tests/determinism/test_state_transition_replay.py`).

---

## 6. Regime/hazard sizing coherence

### 6.1 Timing — does `current_state()` at M5/M6 see the same M2 posterior the gate saw?

Confirmed directly from the orchestrator's tick sequence: `_update_regime(quote, cid)`
(`orchestrator.py:3480-3489`) is called immediately after the `STATE_UPDATE` micro-transition
(`orchestrator.py:2397-2401`), which happens once per tick, strictly before `SIGNAL_GATE`
(`orchestrator.py:1962` region) and before `RISK_CHECK` (`check_signal` at `2607`, `check_order` at
`2806`). `_update_regime` is the **sole** caller of `RegimeEngine.posterior()` in the codebase
(confirmed by the regime-detection skill's single-writer contract and this pass's read of
`orchestrator.py`); every downstream consumer within the same tick calls only `current_state()`
(a read of the cached result). Since the event bus and tick pipeline are synchronous and single
threaded, there is no interleaving that could let a *later* tick's posterior leak into an *earlier*
tick's risk check. **Confirmed: no lag/staleness bug** — `current_state()` at M5/M6 always reflects
exactly the M2 posterior computed earlier in the same tick.

### 6.2 Series, not parallel — no double-scaling between sizer and risk engine

The module docstring of `basic_risk.py` is explicit: *"Regime scaling of *quantity* is the exclusive
responsibility of the position sizer — the risk engine never injects regime factors into
`scaling_factor` to avoid double-scaling"* (`basic_risk.py:6-9`). Verified in code: `_regime_scaling`'s
only two call sites both feed `adjusted_max` (`basic_risk.py:190-191`, `257-258`), a **hard limit**,
never `RiskVerdict.scaling_factor` (which is only ever set inside `_check_exposure_and_drawdown`'s
gross-exposure-proximity branch, `basic_risk.py:775-786`, and is unrelated to regime state). Meanwhile
`BudgetBasedSizer._get_regime_factor` scales the **proposed quantity** before the order is ever
constructed (`position_sizer.py:103-109`). These are sequential stages in the pipeline — sizer
proposes a (regime-shrunk) quantity, risk engine independently caps the (regime-shrunk) limit — not a
multiplicative composition of the same tick's regime factor applied twice to the same number. Both
factors moving together in the same direction (both shrink under `vol_breakout`, say) is expected
covariance, not compounding: the two are computed independently and used in different arithmetic roles
(`min(proposed, limit)` semantics via the `post_fill_qty > adjusted_max` check, not `proposed ×
limit_factor`). **Confirmed: deliberate series design, not accidental parallel compounding.**
`bootstrap.py:514-526` additionally sources both consumers' scale maps from the *same*
`RiskConfig` fields ("audit R-7"), closing a historical risk that the two could silently drift apart
via independently-hardcoded defaults.

### 6.3 Could the EV-weighted scale ever exceed 1.0×?

No — see §3.2's table; both consumers clamp `min(1.0, ev)` at the value level, independent of the
operator-supplied scale map (so even a misconfigured `{"normal": 2.0}` cannot amplify past baseline —
tested directly at `test_basic_risk.py:653-661` and `test_position_sizer.py:88-113`).

### 6.4 Hazard exit-only invariant

Every individual `OrderRequest` `HazardExitController` constructs is directionally exit-only by
construction: `side = SELL if position.quantity > 0 else BUY`, `quantity = abs(position.quantity)`
(`hazard_exit.py:289-290`) — there is no code path where the controller computes a side that matches
the current position's sign. The orchestrator's defensive `check_order` call independently re-verifies
this per order (`order_reduces`, `orchestrator.py:6302-6304`) before honoring the "submit anyway on
REJECT" fail-safe, rather than trusting the `reason` tag alone (`orchestrator.py:6295-6301`) — a
non-reducing order carrying a hazard reason is treated as a genuine anomaly and blocked
(`6310-6335`). **Per-order exit-only is proven.** The aggregate (multi-order) exit-only property is
**not** proven — see Finding HZ-1 (§3.4), which is the concrete counter-scenario for this dimension's
"interaction with regime gate OFF — double exits or conflicting orders" question, generalized: the
double-exit risk is not specific to the regime gate being off, it is specific to two *independent
trigger reasons* racing against one unfilled order.

### 6.5 Suppression key granularity (reconfirmed open, P2, from `risk_engine_audit_2026-06-18.md`)

Controller-side suppression is keyed `(strategy_id, symbol, reason)` (`hazard_exit.py:184-185`);
detector-side suppression (in `RegimeHazardDetector`, out of this audit's file scope) is keyed
`(symbol, engine_name, departing_state)` — a narrower key. The controller's broader key means a
second hazard spike for the same strategy/symbol with a **different** departing state, arriving before
the position returns to flat, is suppressed by the controller even though the detector would have
allowed it through. This is the same design point the two prior audits flagged as an open
modeling-choice question ("is broader suppression intentional conservatism or a missed-exit risk in
multi-regime churn?") — not re-derived as new, still unresolved, orthogonal to Finding HZ-1 (which is
about *different reasons*, not *different departing states within the same reason*).

---

## 7. Buying power & limits audit

- **Arithmetic**: `buying_power_limit(equity, phase, config) = equity × {intraday: 4, overnight: 2}`
  (config-overridable via `risk_margin_{intraday,overnight}_buying_power_multiplier`,
  `bootstrap.py:413-414`), `Decimal("0")` for `equity <= 0` (`buying_power.py:43-56`). No off-by-one
  or sign errors found — multipliers are validated positive at construction
  (`buying_power.py:39-40`), and only `margin_25k` is accepted (`33-38`), matching the platform's
  locked account-type scope.
- **Entry-only gating**: `_check_buying_power` (and `_check_pdt_min_equity`, `_check_rth_session`)
  all no-op via `opens_or_increases_signed` (`execution/trading_session.py`, shared by all three
  entry gates — `basic_risk.py:479-484`, "so a future edge-case fix lands in exactly one place") —
  reductions and exits are never blocked by these three gates, matching Inv-11's "exits always
  permitted" framing. Tested: `test_bt15_buying_power.py:73-82` (`test_exit_not_blocked_by_buying_power`).
- **Cumulative enforcement across legs**: `additional_exposure` folds prior-admitted-leg gross into
  each subsequent leg's buying-power/gross check within the same `SizedPositionIntent`
  (`basic_risk.py:305-312`, `587-594`) — see §4.
- **Phase switching**: `set_buying_power_phase` (`basic_risk.py:159-161`) flips the 4×/2× multiplier;
  delegated correctly through `AlphaBudgetRiskWrapper.set_buying_power_phase`
  (`risk_wrapper.py:364-377`, with an explicit comment explaining why the forwarder is necessary —
  a bare `getattr` on the wrapper itself would silently miss the inner engine). Tested end-to-end:
  `test_bt15_buying_power.py:85-97`.
- **Gate-ordering gap**: Finding FS-2 (§3.5) — the buying-power gate's placement ahead of the
  non-positive-equity `FORCE_FLATTEN` check inside `check_order` means the latter is unreachable for
  entry orders once buying power is wired (which is always, per `bootstrap.py:411-415`). This is the
  central, and only, correctness gap found in this section.
- **Zero/negative buying power behavior**: correctly returns `Decimal("0")` (full block on entries,
  §3.5), but this specific branch has **no direct unit test** —
  `tests/risk/test_buying_power.py` has exactly three tests (`test_margin_25k_intraday_four_x`,
  `test_margin_25k_overnight_two_x`, `test_unimplemented_account_type_raises`), none of which pass a
  non-positive `equity` to `buying_power_limit`. See §8.
- **Position/notional/concentration limits**: `max_position_per_symbol` (shares, not USD) and
  `max_gross_exposure_pct` (percent of live NAV) are enforced pre-emit at both `check_signal` (early,
  directional) and `check_order` (exact post-fill) gates — see the risk-engine skill's "Not shipped"
  table for the notional/ADV/sector/concentration limits that are policy-only; this pass found no
  evidence contradicting that table (i.e., no code claims to enforce them), so no new P0 is filed
  against those absent features, per the audit brief's explicit instruction to read "Not shipped"
  before filing.

---

## 8. Test gap matrix

| Behavior / invariant | Coverage | Evidence | Note |
|---|---|---|---|
| Per-leg veto isolation (REJECT drops one leg only) | **Covered** | `test_basic_risk.py:512-602` | — |
| FORCE_FLATTEN aborts whole intent + escalation flag | **Covered** | `test_basic_risk.py:434-457` | — |
| Cumulative gross cap across legs | **Covered** | `test_basic_risk.py:512-545` | — |
| Per-leg exception containment | **Covered** | `test_basic_risk.py:565-602` | — |
| Regime EV never amplifies above 1.0 (both consumers) | **Covered** | `test_basic_risk.py:653-661`, `test_position_sizer.py:88-113` | — |
| Missing-posterior fail-safe (both consumers) | **Covered** | `test_basic_risk.py:628-651`, `test_position_sizer.py:185-198` | — |
| Escalation SM forward-only walk (integration) | **Covered** | `test_orchestrator.py` (multiple), `test_state_transition_replay.py` | — |
| `_RISK_TRANSITIONS` illegal edges (e.g. `WARNING→LOCKED` direct) | **Missing** | — | Only the generic `StateMachine` mechanism is unit-tested (`tests/core/test_state_machine.py`); the risk-specific table's shape is untested in isolation |
| `unlock_from_lockdown` exposure guard (`exposure != 0` → raise) | **Missing** | `test_orchestrator.py:1513-1549` exists but never seeds a non-zero position | The one test for this method doesn't exercise its own guard |
| `reset_risk_escalation` (any behavior) | **Missing** | — | Zero calls to this method anywhere in `tests/` |
| Buying-power `equity <= 0 → Decimal("0")` | **Missing** | `test_buying_power.py` has 3 tests, none pass non-positive equity | Directly relevant to Finding FS-2 |
| Non-positive equity `FORCE_FLATTEN` with `BuyingPowerConfig` wired (realistic bootstrap config) | **Missing** | `test_basic_risk.py:604-625` uses `BasicRiskEngine(cfg)` with no `buying_power_config` | Directly the gap in Finding FS-2 — the existing test doesn't reproduce the bootstrap-realistic configuration |
| Hazard exit: same-reason double-fire suppression | **Covered** | `test_hazard_exit.py:323-355` | — |
| Hazard exit: cross-reason (`HAZARD_SPIKE` + `HARD_EXIT_AGE`) race on one unreconciled position | **Missing** | — | Directly the gap in Finding HZ-1 |
| Hazard exit: per-order exit-only direction | **Covered** | `test_hazard_exit.py`, `test_hazard_exit_e2e.py:321-355` (short-position BUY exit) | — |
| Hazard bridge: non-reducing REJECT blocks submission | **Partially covered** | Inferred from `test_hazard_exit_e2e.py` suite; no test directly stubs a non-reducing hazard-tagged order | Recommend an explicit test per the 2026-06-20 backlog item 3 |
| SCALE_DOWN composition never exceeds 1.0 (SIGNAL path) | **Covered** | `test_dual_scale_down_e2e.py:109-175` | — |
| SCALE_DOWN floor forces ≥1 share (PORTFOLIO path) | **Missing** | `test_basic_risk.py:664-700` tests rounding but not the floor case (`scaling_factor` low enough to round to 0) | Directly the gap in Finding FS-3 |
| `EdgeWeightedSizer` clamps and parity-with-base when disabled | **Covered** | `tests/risk/test_edge_weighted_sizer.py` (25 tests) | — |
| Custom `RegimeEngine` NaN/inf posterior at risk/sizer boundary | **Missing** | — | Reconfirmed open from `risk_engine_audit_2026-06-18.md`; not re-derived |
| PDT / RTH / buying-power gate wiring per mode | **Covered** | `test_per_alpha_risk_budget_wiring.py`, `test_risk_wrapper.py` | — |
| Hazard controller wiring scans both SIGNAL and PORTFOLIO alphas | **Covered** | `test_hazard_exit_controller_wiring.py:83-138` | — |

---

## 9. Prioritized backlog

### P0

1. **Add a per-symbol in-flight guard to `HazardExitController`** so `HAZARD_SPIKE` and
   `HARD_EXIT_AGE` cannot both emit a full-size exit for the same symbol before the first order's
   fill reconciles (Finding HZ-1).
   Evidence: `risk/hazard_exit.py:184-185,272-279`; `kernel/orchestrator.py:4963-4970,6289-6293`.
   Effort: **M** (state tracking + a cancel/supersede or defer-until-reconciled policy; needs care to
   preserve Inv-5 replay determinism and the async-ack PAPER/LIVE semantics that motivated the
   existing bypass).
   Expected impact: closes the one path in this audit where the hazard-exit machinery could produce
   net new (reversed) exposure instead of a pure flatten.

### P1

2. **Reorder or special-case the non-positive-equity check ahead of / inside the buying-power gate**
   so `FORCE_FLATTEN` is reachable regardless of order direction once equity is wiped out
   (Finding FS-2).
   Evidence: `risk/basic_risk.py:274-282,313-323,729-737`; `risk/buying_power.py:49-50`;
   `bootstrap.py:411-415`.
   Effort: **S** (a few lines in `check_order`, plus one new test using the bootstrap-realistic
   `BuyingPowerConfig`-wired engine).
   Expected impact: restores the code's own stated "unconditional" fail-safe guarantee for the
   PAPER/LIVE-realistic configuration.
3. **Add an exposure/safety precondition to `reset_risk_escalation`, or explicitly document +
   test its absence as an accepted operator responsibility** (Finding ESC-1).
   Evidence: `kernel/orchestrator.py:1690-1708` vs. `1646-1688`.
   Effort: **S** (one guard clause + tests covering both the guarded and, if kept, the
   explicitly-accepted-risk path).
   Expected impact: removes an asymmetry between two safety-critical, similarly-named methods; makes
   the current behavior (if kept) a reviewed decision rather than an untested gap.
4. **Add tests locking the two fail-safe behaviors confirmed fixed this pass**, so they cannot
   silently regress: (a) hazard bridge blocks submission on a non-reducing `REJECT`; (b)
   `AlphaBudgetRiskWrapper.check_order` exempts reducing orders from the per-alpha exposure cap.
   Evidence: `orchestrator.py:6302-6335`; `risk_wrapper.py:231-246`.
   Effort: **S**.
   Expected impact: locks in the remediation from `risk_engine_audit_2026-06-20.md` items 1–3 with
   regression coverage, closing that report's backlog item 3.

### P2

5. **Remove (or explicitly justify) the `max(1, ...)` floor on `SCALE_DOWN` quantity in the PORTFOLIO
   per-leg path** so a full scale-down-to-zero can suppress a small leg, matching the SIGNAL path's
   behavior (Finding FS-3).
   Evidence: `risk/sized_intent_orders.py:168-175` vs. `kernel/orchestrator.py:4838-4841,2871-2888`.
   Effort: **S**.
6. **Add a defensive `math.isfinite` guard at the two regime-EV call sites** so a misbehaving
   third-party `RegimeEngine` cannot produce a NaN-derived `1.0` (unscaled baseline) instead of the
   intended fail-safe minimum. Reconfirmed open from `risk_engine_audit_2026-06-18.md` backlog item 5.
   Evidence: `risk/basic_risk.py:837`; `risk/position_sizer.py:137`.
   Effort: **S**.
7. **Add a unit test directly against `_RISK_TRANSITIONS`** (e.g. `WARNING → LOCKED` raises
   `IllegalTransition`; `BREACH_DETECTED → NORMAL` via `.transition()` raises) so the risk-specific
   transition table's shape has dedicated coverage independent of the generic `StateMachine` tests
   and the always-forward-walking integration tests.
   Evidence: `risk/escalation.py:29-59`.
   Effort: **S**.
8. **Add a direct unit test for `buying_power_limit`'s non-positive-equity branch.**
   Evidence: `risk/buying_power.py:49-50`.
   Effort: **S**.
9. **Decide and document all-or-none vs. partial-execution policy for portfolio intents whose legs
   are vetoed.** Reconfirmed open from `risk_engine_audit_2026-06-18.md`/`-06-20.md`; not re-derived.
   Effort: **M** (policy decision + `SizedPositionIntent` contract change if all-or-none is adopted).
10. **Decide whether hazard controller suppression should be keyed by departing regime state** (not
    just `(strategy_id, symbol, reason)`), matching the detector's narrower key. Reconfirmed open from
    prior audits; orthogonal to Finding HZ-1. Effort: **S–M**.
11. **Require an explicit deployment acknowledgment when `sizer_tilt_drive: true` ships to
    PAPER/LIVE**, since it is the one path that can size above baseline. Reconfirmed open from prior
    audits. Effort: **S**.

### Proposed minimal new tests (specs only, not implemented this pass)

- *Hazard cross-reason race*: seed an open position; publish a qualifying `RegimeHazardSpike`
  (`HAZARD_SPIKE`) and, before advancing the position store, a qualifying `Trade` for
  `HARD_EXIT_AGE` on the same symbol; assert exactly one `OrderRequest` is emitted (or, if the fix is
  "defer the second until reconciled," assert the second is deferred/cancelled rather than a second
  full-size order landing).
- *Golden escalation replay*: two independent event logs that each drive `_escalate_risk` from a
  different starting `RiskLevel` (e.g. one from `NORMAL`, one artificially seeded at
  `BREACH_DETECTED`) should produce the same `LOCKED` end state and an identical relative transition
  sequence — a property test that `_escalate_risk` is correctly re-entrant.
- *Property: never amplifies*: for a random `RegimeEngine` stub returning arbitrary (including
  adversarial: all-mass-on-one-state, uniform, near-degenerate) posteriors and an arbitrary
  operator-supplied scale/factor map (including values `> 1.0`), assert both
  `BasicRiskEngine._regime_scaling` and `BudgetBasedSizer._get_regime_factor` never return `> 1.0`.
- *Buying-power + non-positive-equity, bootstrap-realistic config*: construct `BasicRiskEngine` with
  a wired `BuyingPowerConfig` (mirroring `bootstrap.py`), drive equity to `<= 0` via unrealized loss,
  submit an entry order, assert `FORCE_FLATTEN` (not `REJECT(INSUFFICIENT_BUYING_POWER)`).

---

## 10. Appendix — open questions needing data runs

- **HZ-1 live reproduction**: this audit reasoned the cross-reason hazard race from code + the
  orchestrator's own comment about async PAPER/LIVE acks, but did not (and could not, read-only,
  no broker connection in this environment) reproduce it against real IB Gateway ack latency. A
  `paper_rth`-tier run (or a targeted integration test with an injected artificial ack delay on a
  stub broker) would confirm whether the window is wide enough to matter in practice, and how often
  `HAZARD_SPIKE` and `HARD_EXIT_AGE` conditions co-occur on the same symbol in historical data.
- **FS-2 operational history**: has any PAPER/LIVE run ever driven live NAV to non-positive while
  entry orders were still arriving? A telemetry/log review (searching for
  `INSUFFICIENT_BUYING_POWER` rejects clustered in time with negative-equity marks, absent a
  corresponding `risk_escalation_lockdown` `KillSwitchActivation`) would confirm whether this gap has
  already been silently hit, versus being a theoretical precondition that has not yet occurred.
- **ESC-1 operational history**: has `reset_risk_escalation` ever been invoked in a real incident, and
  if so, was the book verified flat by the operator out-of-band (outside what the code checks)? This
  would clarify whether the missing guard is a pure latent gap or one that operational practice has
  already been compensating for manually.
- **NaN/inf posterior**: no custom `RegimeEngine` currently ships in this repository, so item 6/13
  (§9/§1) is a defensive hardening question rather than a live bug — worth a fuzz/property test
  through the full sizer + risk-engine path simultaneously (not just each `_get_regime_factor`/
  `_regime_scaling` call in isolation) to confirm the `min(1.0, nan) == 1.0` behavior does not
  compound with anything else downstream.
- **Exhaustiveness guard in `build_sized_intent_orders`** (§3.3): currently latent because
  `RiskAction` has exactly four members; worth deciding whether to add an explicit guard now or accept
  the implicit reliance on enum completeness, documented.
