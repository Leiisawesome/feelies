# Risk Engine Audit - 2026-06-20

Scope: read-only audit of the risk layer and adjacent routing/wiring paths. No production code or tests were changed.

Verification run:

- `uv run pytest tests/risk/ -q` - 164 passed.
- `uv run pytest tests/acceptance/test_bt15_buying_power.py tests/determinism/test_hazard_exit_replay.py -q` - 8 passed.
- `uv run pytest tests/integration/test_hazard_exit_e2e.py -q` - 6 passed.

Severity convention used here:

- P0: autonomous exposure increase, or a formal failed risk check still emits/submits an order, under this audit's strict fail-safe rule.
- P1: can block de-risking, weaken a shared invariant, or leave a material audit hole.
- P2: bounded weakness, test gap, documentation drift, or modeling choice that needs explicit owner acceptance.

## 1. Executive summary

- P0: hazard exits run `check_order`, publish/log `REJECT`, and still submit the order to the router. The code explicitly states that REJECT verdicts are logged and the order is submitted anyway, then calls `submit(event)` after the REJECT branch. This violates the audit rule that a failed formal risk check must not still emit/submit an order. Evidence: `src/feelies/kernel/orchestrator.py:6163`, `src/feelies/kernel/orchestrator.py:6188`, `src/feelies/kernel/orchestrator.py:6194`, `src/feelies/kernel/orchestrator.py:6222`.
- P1: `AlphaBudgetRiskWrapper.check_order` rejects any registered-alpha order when current alpha exposure is already at/above the cap, without checking whether the order reduces exposure. The signal gate has a reducing exemption, but the order gate does not. Evidence: `src/feelies/alpha/risk_wrapper.py:102`, `src/feelies/alpha/risk_wrapper.py:107`, `src/feelies/alpha/risk_wrapper.py:224`, `src/feelies/alpha/risk_wrapper.py:228`.
- The base risk engine's order gate is materially stronger than the older risk-audit baseline: multi-leg portfolio intents now pass cumulative admitted gross through `additional_exposure`, and tests cover second-leg drops when aggregate gross breaches the cap. Evidence: `src/feelies/risk/sized_intent_orders.py:87`, `src/feelies/risk/sized_intent_orders.py:146`, `src/feelies/risk/sized_intent_orders.py:193`, `tests/risk/test_basic_risk.py:512`.
- Per-leg veto behavior is implemented as requested: `REJECT` drops only the offending leg, `FORCE_FLATTEN` aborts the whole intent and requests global escalation, and exceptions from per-leg `check_order` are contained as dropped legs. Evidence: `src/feelies/risk/sized_intent_orders.py:80`, `src/feelies/risk/sized_intent_orders.py:97`, `src/feelies/risk/sized_intent_orders.py:146`, `src/feelies/risk/sized_intent_orders.py:159`.
- The partial-portfolio residual risk is not silent: dropped legs are surfaced through `portfolio_intent_partial_execution`, and the message explicitly says cross-sectional invariants are not re-validated after dropping. Evidence: `src/feelies/risk/basic_risk.py:398`, `src/feelies/risk/basic_risk.py:423`, `tests/risk/test_basic_risk.py:343`.
- Regime scaling in the base risk engine and budget sizer is fail-safe for the audited path: missing posterior with a configured engine uses the minimum configured scale, unknown state names use the minimum scale, and runtime values are clamped at 1.0 so regime cannot amplify exposure. Evidence: `src/feelies/risk/basic_risk.py:810`, `src/feelies/risk/basic_risk.py:812`, `src/feelies/risk/basic_risk.py:833`, `src/feelies/risk/position_sizer.py:111`.
- Signal strength is clamped into `[0, 1]` before sizing, so malformed conviction values above 1.0 do not amplify allocation in `BudgetBasedPositionSizer`. Evidence: `src/feelies/risk/position_sizer.py:94`.
- Edge-weighted sizing can amplify target quantity, but only through an explicit config-gated sizer path; platform defaults keep the tilted sizer disabled. Treat this as an intentional modeling/design choice, not an implementation bug, unless deployment config enables it unexpectedly. Evidence: `src/feelies/core/platform_config.py:357`, `src/feelies/bootstrap.py:525`.
- Hazard exit orders are exit-direction-only at the controller: flat positions no-op; long exits sell full current quantity; short exits buy full current quantity. Evidence: `src/feelies/risk/hazard_exit.py:260`, `src/feelies/risk/hazard_exit.py:272`, `tests/integration/test_hazard_exit_e2e.py:330`.
- Hazard suppression is symbol-net and keyed by `(strategy_id, symbol, reason)`, not by departing regime. That is conservative for duplicate suppression but should be explicitly accepted because detector suppression is keyed more narrowly by departing state. Evidence: `src/feelies/risk/hazard_exit.py:164`, `src/feelies/services/regime_hazard_detector.py:188`.
- Escalation is forward-only until `LOCKED`, and unlock/reset require explicit audit-token methods with additional guards. Evidence: `src/feelies/risk/escalation.py:29`, `src/feelies/kernel/orchestrator.py:1606`, `src/feelies/kernel/orchestrator.py:1650`.
- Buying power is enforced on live NAV with 4x intraday and 2x overnight multipliers, and entry gates exempt exits/reductions. Evidence: `src/feelies/risk/buying_power.py:43`, `src/feelies/risk/basic_risk.py:557`, `tests/acceptance/test_bt15_buying_power.py:73`.
- Non-positive live equity is fail-closed to `FORCE_FLATTEN`, independent of drawdown configuration. Evidence: `src/feelies/risk/basic_risk.py:717`, `tests/risk/test_basic_risk.py:606`.
- Main remaining test gaps: formal hazard order handler test where `check_order` returns REJECT, order-level alpha reducing-exit at/over exposure cap, custom regime posterior containing NaN/inf, and portfolio partial-execution invariant disclosure/owner acceptance tests.

## 2. Risk-control inventory

| Control | Implementation | Current behavior | Evidence |
| --- | --- | --- | --- |
| Signal gate | `BasicRiskEngine.check_signal` | Applies regime-adjusted position cap, gross exposure, drawdown, and scale-down threshold before alpha signals become orders. | `src/feelies/risk/basic_risk.py:167` |
| Order gate | `BasicRiskEngine.check_order` | Uses exact post-fill quantity, PDT, buying power, RTH, post-fill gross exposure, drawdown, and scale-down checks. | `src/feelies/risk/basic_risk.py:231` |
| Portfolio intent gate | `BasicRiskEngine.check_sized_intent` via `build_sized_intent_orders` | Fans out deterministic per-symbol orders, vets each leg, drops only bad legs unless `FORCE_FLATTEN`. | `src/feelies/risk/basic_risk.py:334`, `src/feelies/risk/sized_intent_orders.py:71` |
| Per-alpha wrapper | `AlphaBudgetRiskWrapper` | Adds strategy-budget checks around base risk engine for signals, orders, and sized intents. | `src/feelies/alpha/risk_wrapper.py:63`, `src/feelies/alpha/risk_wrapper.py:178` |
| Regime-aware sizing | `BudgetBasedPositionSizer` | Converts signal and alpha budget into target shares; strength and regime factors cannot amplify above baseline. | `src/feelies/risk/position_sizer.py:80`, `src/feelies/risk/position_sizer.py:94`, `src/feelies/risk/position_sizer.py:130` |
| Regime hard-limit scaling | `BasicRiskEngine._regime_scaling` | Tightens max position limits by posterior EV; no engine means operator opt-out; configured engine with no posterior uses min scale. | `src/feelies/risk/basic_risk.py:790`, `src/feelies/risk/basic_risk.py:820`, `src/feelies/risk/basic_risk.py:823` |
| Hazard exits | `HazardExitController` and orchestrator hazard bridge | Controller emits full-position exit orders; orchestrator routes matching risk-layer hazard orders to router. | `src/feelies/risk/hazard_exit.py:243`, `src/feelies/kernel/orchestrator.py:6143` |
| Drawdown/HWM | `BasicRiskEngine._check_exposure_and_drawdown` | Computes live NAV, force-flattens non-positive equity and drawdown breach, rejects gross exposure cap. | `src/feelies/risk/basic_risk.py:695` |
| Buying power | `BuyingPowerConfig` and `BasicRiskEngine._check_buying_power` | Enforces Reg-T gross cap against live NAV, only for opens/increases. | `src/feelies/risk/buying_power.py:25`, `src/feelies/risk/basic_risk.py:557` |
| RTH/PDT gates | `BasicRiskEngine._check_pdt_min_equity`, `_check_rth_session` | Optional entry-only suppressors; pure exits and reductions pass through. | `src/feelies/risk/basic_risk.py:486`, `src/feelies/risk/basic_risk.py:522` |
| Risk escalation | `risk/escalation.py` plus orchestrator helpers | Autonomous transitions only tighten; unlock/reset require explicit audited methods. | `src/feelies/risk/escalation.py:29`, `src/feelies/kernel/orchestrator.py:3551` |
| Bus fan-out contracts | Orchestrator `SizedPositionIntent` and hazard handlers | Portfolio intent orders route through per-leg risk; hazard bus orders route through special bridge. | `src/feelies/kernel/orchestrator.py:6130`, `src/feelies/kernel/orchestrator.py:6143` |

## 3. Fail-safe audit

### Finding P0-R1: hazard handler submits after formal `check_order` REJECT

The hazard bridge is intentionally designed to submit hazard exits after a formal order-gate rejection. The handler comment says hazard exits are exit-direction-only and that `REJECT` verdicts are logged while the order is still submitted. The implementation then calls `check_order`, publishes non-`FORCE_FLATTEN` verdicts, emits an alert when the verdict is `REJECT`, and still calls `self._backend.order_router.submit(event)`.

Evidence:

- Intentional carve-out text: `src/feelies/kernel/orchestrator.py:6163`.
- Formal risk call: `src/feelies/kernel/orchestrator.py:6188`.
- REJECT alert branch: `src/feelies/kernel/orchestrator.py:6194`.
- Router submission after the REJECT branch: `src/feelies/kernel/orchestrator.py:6222`.

Why this matters: this audit's rule is stricter than the local comment. Any path that treats a formal `RiskAction.REJECT` as advisory creates two definitions of the gatekeeper. Even though the controller constructs exit-only orders, the strict invariant is "if the formal risk gate says REJECT, the order must not submit." This is P0 by the user-provided criteria.

Recommended direction, without implementing here:

- Either make the formal `check_order` path correctly return `ALLOW` for proven exit-only hazard orders, or replace the hazard call with a separately named non-gating audit probe so a `RiskAction.REJECT` is never ignored.
- Add a test that stubs the risk engine to return `REJECT` and asserts the handler does not submit when the formal gate is authoritative, or asserts the new probe is not a formal gate.

### Finding P1-R2: alpha order-level exposure cap can reject reducing exits

`AlphaBudgetRiskWrapper.check_signal` computes `signal_reduces` and exempts reducing signals from position/exposure limit rejections. The order-level wrapper computes post-fill position for the position cap, but the exposure cap checks only current alpha exposure against alpha max exposure. It does not compute whether the candidate order reduces current exposure.

Evidence:

- Signal-level reducing exemption: `src/feelies/alpha/risk_wrapper.py:88`, `src/feelies/alpha/risk_wrapper.py:102`.
- Order-level position cap uses post-fill quantity: `src/feelies/alpha/risk_wrapper.py:200`.
- Order-level exposure cap ignores order direction/post-fill exposure: `src/feelies/alpha/risk_wrapper.py:224`.
- Exposure rejection is triggered solely by current `alpha_exposure >= alpha_max_exposure`: `src/feelies/alpha/risk_wrapper.py:228`.

Why this matters: an over-exposed registered alpha may be unable to pass an otherwise de-risking order through the wrapper. It also explains how a hazard exit carrying a registered `strategy_id` can produce the P0 behavior above: the hazard bridge may receive `REJECT` from the wrapper even for an exit-direction-only order, then submit anyway.

Recommended direction, without implementing here:

- At the alpha order gate, compute post-fill per-alpha exposure for the symbol or at least detect whether the order reduces absolute per-alpha exposure. Allow reducing/closing orders even when current exposure is already over budget.
- Add tests for long reduction, short reduction, full close, and reversal across zero when current alpha exposure is above budget.

### Covered fail-safe paths

- `build_sized_intent_orders` contains raising per-leg `check_order` calls and veto-drops only that leg rather than propagating exceptions. Evidence: `src/feelies/risk/sized_intent_orders.py:97`, `src/feelies/risk/sized_intent_orders.py:146`, `tests/risk/test_basic_risk.py:567`.
- Multi-leg gross/buying-power caps are cumulative through `running_extra`, so each later leg sees earlier admitted gross. Evidence: `src/feelies/risk/sized_intent_orders.py:87`, `src/feelies/risk/sized_intent_orders.py:193`, `tests/risk/test_basic_risk.py:512`.
- Non-positive equity force-flattens instead of falling back to initial account equity. Evidence: `src/feelies/risk/basic_risk.py:717`, `src/feelies/risk/basic_risk.py:729`, `tests/risk/test_basic_risk.py:606`.
- Optional entry gates can be absent when not wired, but bootstrap wires supported margin accounts with PDT, buying power, and trading-session constraints. Evidence: `src/feelies/risk/basic_risk.py:576`, `src/feelies/bootstrap.py:409`.

## 4. Per-leg veto audit

The per-leg veto implementation matches the requested semantics for portfolio-level intents.

Observed contract:

- Symbols are evaluated in sorted order for deterministic fan-out. Evidence: `src/feelies/risk/sized_intent_orders.py:110`.
- Each symbol's target USD is converted to shares using current mark and `ROUND_HALF_UP`. Evidence: `src/feelies/risk/sized_intent_orders.py:117`.
- `REJECT` appends that symbol to the dropped-leg list and continues to later symbols. Evidence: `src/feelies/risk/sized_intent_orders.py:164`.
- `FORCE_FLATTEN` returns no orders and sets `requires_global_risk_escalation=True`. Evidence: `src/feelies/risk/sized_intent_orders.py:159`.
- `SCALE_DOWN` rebuilds the same leg with the scaled quantity, preserving deterministic order ID and attribution. Evidence: `src/feelies/risk/sized_intent_orders.py:167`.
- Admitted leg exposure is accumulated into `running_extra` for later cap checks. Evidence: `src/feelies/risk/sized_intent_orders.py:193`.

Test evidence:

- Dropped-leg alert contains attribution and only surviving symbols are ordered. Evidence: `tests/risk/test_basic_risk.py:343`.
- Drawdown `FORCE_FLATTEN` aborts the whole intent and sets the global escalation flag. Evidence: `tests/risk/test_basic_risk.py:434`.
- Aggregate gross cap drops the second leg when two individually valid legs collectively exceed the cap. Evidence: `tests/risk/test_basic_risk.py:512`.
- Raising per-leg checks are contained and the other leg proceeds. Evidence: `tests/risk/test_basic_risk.py:567`.

Residual design risk: a surviving partial portfolio can violate alpha-level cross-sectional assumptions such as dollar neutrality or sector matching. The current implementation acknowledges this by alerting `portfolio_intent_partial_execution`, including a message that surviving legs execute as a partial portfolio and that cross-sectional invariants are not re-validated. Evidence: `src/feelies/risk/basic_risk.py:398`, `src/feelies/risk/basic_risk.py:423`.

Audit conclusion: per-leg veto itself is sound. The remaining question is a design decision: whether partial execution is acceptable for each portfolio alpha, or whether certain alphas must mark a leg drop as whole-intent reject.

## 5. Escalation SM audit

The risk escalation state machine is monotonic for autonomous transitions:

- Levels are `NORMAL`, `WARNING`, `BREACH_DETECTED`, `FORCED_FLATTEN`, `LOCKED`. Evidence: `src/feelies/risk/escalation.py:19`.
- Transition table only permits forward movement until `LOCKED`; the only loosening edge is `LOCKED -> NORMAL`. Evidence: `src/feelies/risk/escalation.py:29`, `src/feelies/risk/escalation.py:53`.
- The orchestrator's `_escalate_risk` walks all stages to `LOCKED`, activates the kill switch, and moves live/paper macro state to `RISK_LOCKDOWN`. Evidence: `src/feelies/kernel/orchestrator.py:3551`.

Controlled loosening paths:

- `unlock_from_lockdown(audit_token=...)` requires macro `RISK_LOCKDOWN`, no exposure, and an audit token before moving macro to `READY`, risk `LOCKED -> NORMAL`, and clearing the kill switch. Evidence: `src/feelies/kernel/orchestrator.py:1606`.
- `reset_risk_escalation(audit_token=...)` refuses `LOCKED`, refuses active trading modes, requires an audit token, and is limited to intermediate levels. Evidence: `src/feelies/kernel/orchestrator.py:1650`.
- Tests cover unlock clearing the kill switch and restoring risk to `NORMAL`, and session entry refusing non-normal risk. Evidence: `tests/kernel/test_orchestrator.py:1377`, `tests/kernel/test_orchestrator.py:1439`.

Audit conclusion: no silent benign-tick reset or autonomous de-escalation path was found. The reset/unlock APIs are intentionally human/audit-token paths, not implementation bugs.

## 6. Regime/hazard sizing coherence

### Regime state consumption

The risk and sizing layers consume `current_state(symbol)`, not fresh posterior updates. The regime service caches posteriors and exposes a copy via `current_state`; risk uses that downstream snapshot. Evidence: `src/feelies/services/regime_engine.py:500`, `src/feelies/services/regime_engine.py:559`, `src/feelies/risk/basic_risk.py:823`, `src/feelies/risk/position_sizer.py:120`.

### Missing and unknown regime data

The configured-engine missing-data policy is fail-safe:

- Basic risk: no engine means explicit opt-out and returns 1.0; configured engine with no posterior returns `_regime_scale_default`, the minimum scale. Evidence: `src/feelies/risk/basic_risk.py:820`, `src/feelies/risk/basic_risk.py:823`.
- Position sizer: same policy for factors. Evidence: `src/feelies/risk/position_sizer.py:111`, `src/feelies/risk/position_sizer.py:117`.
- Unknown state names default to the minimum scale/factor. Evidence: `src/feelies/risk/basic_risk.py:810`, `src/feelies/risk/position_sizer.py:125`.
- Tests cover missing posterior and no-amplification behavior. Evidence: `tests/risk/test_basic_risk.py:630`, `tests/risk/test_position_sizer.py:185`.

### Amplification checks

Base regime scaling does not amplify exposure:

- Basic risk clamps regime EV at 1.0. Evidence: `src/feelies/risk/basic_risk.py:833`.
- Budget position sizing clamps signal strength into `[0, 1]` and clamps regime factor at 1.0. Evidence: `src/feelies/risk/position_sizer.py:94`, `src/feelies/risk/position_sizer.py:130`.

Separate modeling choice: `EdgeWeightedSizer` can amplify a base target from explicit edge/volatility factors, but defaults keep that path disabled for live sizing unless the operator opts in. This is not a hidden risk-layer amplification bug, but deployments should treat enabling it as a conscious exposure-increase decision. Evidence: `src/feelies/risk/edge_weighted_sizer.py:25`, `src/feelies/core/platform_config.py:357`, `src/feelies/bootstrap.py:525`.

### Hazard semantics

Hazard exits are exit-only at the controller:

- The controller no-ops when position quantity is zero. Evidence: `src/feelies/risk/hazard_exit.py:260`.
- Long positions generate SELL; short positions generate BUY; quantity is absolute current position. Evidence: `src/feelies/risk/hazard_exit.py:272`.
- The emitted order is tagged `source_layer="RISK"` and reason `HAZARD_SPIKE` or `HARD_EXIT_AGE`. Evidence: `src/feelies/risk/hazard_exit.py:277`.
- Integration tests cover duplicate suppression, threshold no-op, short-position BUY exit, and universe filters. Evidence: `tests/integration/test_hazard_exit_e2e.py:180`, `tests/integration/test_hazard_exit_e2e.py:220`, `tests/integration/test_hazard_exit_e2e.py:330`, `tests/integration/test_hazard_exit_e2e.py:357`.

Modeling choice to accept or revise: controller suppression is keyed by `(strategy_id, symbol, reason)`, while the detector suppression is keyed by `(symbol, engine_name, departing_state)`. Controller suppression is more conservative and can suppress a later different departing-state spike until flat. Evidence: `src/feelies/risk/hazard_exit.py:164`, `src/feelies/services/regime_hazard_detector.py:188`.

## 7. Buying power & limits audit

Buying power implementation:

- `BuyingPowerConfig` supports only `margin_25k`, defaults to 4x intraday and 2x overnight, and rejects non-positive multipliers. Evidence: `src/feelies/risk/buying_power.py:25`.
- `buying_power_limit` returns zero for non-positive equity and otherwise multiplies live equity by the active phase multiplier. Evidence: `src/feelies/risk/buying_power.py:43`.
- `BasicRiskEngine._check_buying_power` is entry-only: exits and reductions return `None`. Evidence: `src/feelies/risk/basic_risk.py:566`, `src/feelies/risk/basic_risk.py:578`.
- The check uses prospective post-fill gross exposure plus `additional_exposure` from prior admitted portfolio legs. Evidence: `src/feelies/risk/basic_risk.py:587`, `src/feelies/risk/basic_risk.py:593`.

Limit implementation:

- Order gate computes exact signed post-fill quantity, checks PDT, buying power, RTH, post-fill position cap, and then prospective gross/drawdown. Evidence: `src/feelies/risk/basic_risk.py:257`, `src/feelies/risk/basic_risk.py:265`, `src/feelies/risk/basic_risk.py:292`, `src/feelies/risk/basic_risk.py:305`.
- Shared gross cap uses live NAV. Non-positive live equity force-flattens. Evidence: `src/feelies/risk/basic_risk.py:727`, `src/feelies/risk/basic_risk.py:729`, `src/feelies/risk/basic_risk.py:738`.
- Gross cap breach rejects; drawdown breach force-flattens; near-cap returns bounded scale-down. Evidence: `src/feelies/risk/basic_risk.py:741`, `src/feelies/risk/basic_risk.py:755`, `src/feelies/risk/basic_risk.py:775`.

Test evidence:

- Intraday entry within 4x passes; above 4x rejects. Evidence: `tests/acceptance/test_bt15_buying_power.py:49`, `tests/acceptance/test_bt15_buying_power.py:63`.
- Exit is not blocked by buying power. Evidence: `tests/acceptance/test_bt15_buying_power.py:73`.
- Overnight phase uses 2x and switching back to intraday restores 4x allowance. Evidence: `tests/acceptance/test_bt15_buying_power.py:85`.
- Funded equity, not a hidden one-million baseline, drives the cap. Evidence: `tests/acceptance/test_bt15_buying_power.py:100`.

Audit conclusion: the base buying-power path is coherent and covered. The main gap is the alpha wrapper's order-level exposure cap, which sits above the base engine and can reject reducing exits before the base entry-only gates can allow them.

## 8. Test gap matrix

| Gap | Risk | Suggested test |
| --- | --- | --- |
| Hazard handler `check_order == REJECT` still submits | P0 by audit rule; formal gate becomes advisory | Stub orchestrator risk engine to return `REJECT`; assert no router submission if the formal gate remains authoritative, or assert a renamed non-gating probe is used instead. |
| Alpha wrapper order-level reducing exit over cap | P1; can block de-risking and feed hazard REJECTs | Registered alpha current exposure above budget; submit SELL reducing long and BUY reducing short; expect allow/delegate, not wrapper reject. |
| Alpha wrapper order-level full close and reversal | P1; reducing to flat should pass, reversal should treat only exposure-increasing remainder as entry | Cases for close-to-zero and cross-zero. Expect close allowed; reversal constrained on the new exposure side. |
| Custom regime engine returns NaN/inf posterior | P2; built-in HMM sanitizes, custom engine may make `min(1.0, nan)` behave as 1.0 | Fake regime engine `current_state` returning NaN/inf; expect min-scale or reject, not baseline exposure. |
| Partial portfolio intent breaks cross-sectional invariant | P2 design gap; current behavior is alerted but not policy-selectable | Portfolio alpha declares all-or-none intent; one leg rejects; expect whole-intent reject once such a policy exists. |
| Hazard controller suppression by departing state | P2 design gap; controller suppresses by reason, not departing state | Two spikes for same strategy/symbol/reason but different departing states before flat; assert expected owner policy. |
| Edge-weighted sizer deployment guard | P2 operational guard | Config with `sizer_tilt_drive=True`; assert audit/log or explicit config acceptance that exposure amplification is enabled. |
| RTH/PDT/buying-power absent wiring | P2 integration guard | Bootstrap unsupported/disabled gates should be explicit in config validation or deployment smoke, not silent operator surprise. |

## 9. Prioritized backlog

1. P0 - Remove the formal-gate bypass in hazard routing.
   Evidence: `src/feelies/kernel/orchestrator.py:6188`, `src/feelies/kernel/orchestrator.py:6194`, `src/feelies/kernel/orchestrator.py:6222`.
   Expected impact: restores single meaning to `RiskAction.REJECT`. Hazard exits can remain fail-safe by making exit-only orders pass the formal gate or by using a clearly non-gating diagnostic probe.

2. P1 - Add reducing-exit semantics to `AlphaBudgetRiskWrapper.check_order`.
   Evidence: `src/feelies/alpha/risk_wrapper.py:224`, `src/feelies/alpha/risk_wrapper.py:228`.
   Expected impact: prevents alpha budget controls from trapping over-cap positions and reduces the chance of hazard exits hitting the P0 bypass branch.

3. P1 - Add tests around hazard routing with rejecting risk engines and alpha-wrapper exit reductions.
   Evidence for current coverage focus: hazard routing tests verify normal submission and filtering, not rejecting formal gate behavior. `tests/kernel/test_orchestrator_hazard_exit_routing.py:180`.
   Expected impact: locks the fail-safe default that failed formal checks cannot submit.

4. P2 - Define all-or-none semantics for portfolio alphas that cannot tolerate partial legs.
   Evidence: partial execution is acknowledged but not re-validated. `src/feelies/risk/basic_risk.py:423`.
   Expected impact: turns a known design caveat into per-alpha policy instead of relying on downstream alert review.

5. P2 - Sanitize custom regime posterior values at the risk/sizer boundary.
   Evidence: risk and sizer trust `current_state` numeric values and clamp only the upside. `src/feelies/risk/basic_risk.py:829`, `src/feelies/risk/position_sizer.py:126`.
   Expected impact: prevents a custom engine's NaN/inf from producing baseline or undefined sizing behavior.

6. P2 - Add deployment evidence when edge-weighted tilt is enabled.
   Evidence: edge weighting is deliberately opt-in and can amplify. `src/feelies/risk/edge_weighted_sizer.py:25`, `src/feelies/core/platform_config.py:357`.
   Expected impact: makes exposure-increasing sizer behavior explicit in operator artifacts.

7. P2 - Decide whether hazard controller episode suppression should include departing state.
   Evidence: controller key is `(strategy_id, symbol, reason)` while detector includes departing state. `src/feelies/risk/hazard_exit.py:164`, `src/feelies/services/regime_hazard_detector.py:188`.
   Expected impact: clarifies whether the current broader suppression is intentional conservatism or missed exits in multi-regime churn.

## 10. Appendix open questions

- Should the hazard bridge be allowed to submit after `check_order` rejects if the order is proven exit-only, or is `check_order` always the formal last line before capital? This audit assumes the latter because the user request defined failed risk checks that still emit orders as P0.
- Are partial portfolio executions acceptable for every portfolio alpha, or should the `SizedPositionIntent` contract grow an all-or-none flag?
- Should per-alpha exposure at the order gate be computed prospectively using per-strategy marks, or is a simpler "allow if absolute position exposure decreases" predicate sufficient?
- Should hazard controller suppression be per departing regime, per detector episode, or per symbol/reason until flat?
- Should custom regime engines be required to expose sanitized finite posteriors, or should risk/sizer enforce finite values defensively regardless of engine implementation?
- Should enabling `EdgeWeightedSizer` in live config require an explicit deployment/audit acknowledgment because it can intentionally increase exposure?
- Should optional PDT/RTH/buying-power gates fail closed in production boot if config implies they are required but dependencies are absent?
