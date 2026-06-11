# Risk engine & portfolio governor audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
risk control layer — `RiskEngine` (`check_signal`, `check_order`, `check_sized_intent`),
the `RiskLevel` escalation SM, position sizing, buying-power, and the
`HazardExitController` — from `Signal` / `SizedPositionIntent` → `OrderRequest`.

---

## Mission

You are a senior quantitative risk engineer and systems auditor. Perform a
**read-only, evidence-based audit** of the feelies risk layer.

**Primary focus:** This is the **last line before capital**. Inv-11 (fail-safe default)
is non-negotiable here: risk controls may only *tighten* exposure autonomously; loosening
requires human re-authorization. Any path where risk *increases* exposure vs. baseline,
or where a failed risk check still emits an order, is a P0.

**Goal:** Identify where risk logic is sound vs. fragile, where the per-leg veto on
`check_sized_intent` is correct, where escalation latches vs. silently resets, and where
regime/hazard sizing could amplify rather than dampen — without breaking invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/risk-engine/SKILL.md` end-to-end.
2. Read `.cursor/skills/regime-detection/SKILL.md` § on hazard spikes, and
   `.cursor/skills/composition-layer/SKILL.md` § on `SizedPositionIntent`.
3. Read `docs/three_layer_architecture.md` §5.7 (`SizedPositionIntent`), §7 (micro SM
   stages M5/M6).
4. Skim `platform.yaml` risk keys and any alpha `hazard_exit:` / sizing blocks.

**Architecture (contractual):**

```
M5  Signal       → check_signal  → (size) → OrderRequest?
    SizedIntent   → check_sized_intent → per-leg OrderRequest (per-leg veto)
    position_sizer.get_factor(current_state)     [regime EV scaling]
M6  OrderRequest → check_order  → emit / veto
    RegimeHazardSpike → HazardExitController → exit-only OrderRequest
```

- **Three entry points:** `check_signal`, `check_order`, `check_sized_intent`.
- **Per-leg veto:** a single failed leg drops only that leg, not the whole intent.
- **Read-only regime:** sizer/risk call `current_state(symbol)`, never `posterior()`.

**Hard invariants (non-negotiable):**

- Inv-11: fail-safe — unknown/missing state → reduced exposure; controls only tighten
  autonomously.
- Inv-5: deterministic replay; escalation SM transitions reproducible.
- Inv-12: transaction-cost realism factored into sizing where claimed.
- Single-direction safety: hazard path is **exit-only**; never opens or grows positions.

---

## Scope — files to audit

### Risk core

- `src/feelies/risk/engine.py` — `RiskEngine` protocol + entry points
- `src/feelies/risk/basic_risk.py` — `_regime_scaling()` (EV over posteriors), limits
- `src/feelies/risk/escalation.py` — `RiskLevel` escalation state machine
- `src/feelies/risk/position_sizer.py` — `_get_regime_factor()`, sizing math
- `src/feelies/risk/buying_power.py` — buying-power / margin arithmetic
- `src/feelies/risk/sized_intent_orders.py`, `sized_intent_result.py` — intent → per-leg
  decomposition + per-leg veto
- `src/feelies/risk/hazard_exit.py` — `HazardExitController` (exit-only)
- `src/feelies/alpha/risk_wrapper.py` — per-alpha risk param wiring

### Tests (spec + gap analysis)

- `tests/risk/test_basic_risk.py`, `test_buying_power.py`, `test_position_sizer.py`,
  `test_hazard_exit.py`
- `tests/services/test_hazard_exit_controller_wiring.py` (controller wiring)
- `tests/bootstrap/test_per_alpha_risk_budget_wiring.py` (per-alpha budget wiring)
- `tests/alpha/test_risk_wrapper.py` (per-alpha risk param wiring)
- Determinism: `tests/determinism/test_hazard_exit_replay.py`
- Acceptance: `tests/acceptance/test_bt15_buying_power.py`
- Integration: `tests/integration/test_hazard_exit_e2e.py`,
  `tests/integration/test_dual_scale_down_e2e.py`

**Out of scope:** regime engine math (see `audit_regime.md`), composition (see
`audit_composition.md`), fill simulation.

---

## Audit dimensions (answer each with evidence)

### A. Fail-safe correctness (Inv-11) — highest priority

1. Enumerate every code path that can **increase** exposure vs. the unscaled baseline.
   For each, prove it requires explicit config / human authorization, not autonomous.
2. Unknown regime state / missing posterior / NaN: does sizing default to *reduced*
   exposure? Compare `basic_risk` default (`min(scales)`?) vs `position_sizer` default —
   are they aligned and conservative?
3. On any internal error in a check, is the outcome veto (no order) rather than pass?

### B. Per-leg veto on check_sized_intent

1. Trace `SizedPositionIntent` → per-leg `OrderRequest`. Is the veto truly per-leg (one
   bad leg drops only that leg), and are surviving legs unaffected?
2. Delta resolution against `PositionStore` (current qty + `latest_mark`): correct sign
   and rounding? Deterministic leg ordering (lexicographic by symbol)?
3. `OrderRequest.reason = "PORTFOLIO"` stamped for lineage?

### C. Escalation state machine

1. Formalize `RiskLevel` states and transitions. Is escalation **monotone-tightening**
   under sustained stress, and does de-escalation require an explicit trigger?
2. Can the SM silently reset to a looser level on a benign tick (Inv-11 violation)?
3. Replay determinism of escalation given identical event log.

### D. Regime-conditional sizing coherence

1. `_regime_scaling()` (EV over posteriors) vs `_get_regime_factor()` (sizer): are these
   two scalings a *deliberate series* or accidental compounding (double-scaling)?
2. Timing: does `current_state()` at M5/M6 reflect the same M2 posterior the gate saw,
   or a newer tick? Document the lag model.
3. Could the EV-weighted scale ever exceed 1.0× (amplification)?

### E. Buying power & limits

1. Buying-power arithmetic: margin, available capital, per-symbol and gross caps.
   Off-by-one or sign errors? Behavior at zero/negative buying power.
2. Position/notional/concentration limits: enforced pre-emit? Fail-safe on breach?

### F. Hazard exit controller

1. Exit-only invariant: prove no entry/grow `OrderRequest` can originate here.
2. `hazard_score` vs `hazard_score_threshold`, `min_age_seconds`, `hard_exit_age_seconds`
   semantics; suppression per `(symbol, alpha_id, departing_state)`.
3. Interaction with regime gate OFF — double exits or conflicting orders?

### G. Test & validation gaps + prioritized recommendations

1. Map invariants (fail-safe, per-leg veto, escalation latch, exit-only, double-scaling)
   to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (property-based "never amplifies", golden escalation
   replay) — specs only.
3. Tiers:
   - **P0:** any autonomous exposure increase, failed-check-still-emits, escalation reset,
     hazard entry path, non-determinism.
   - **P1:** double-scaling, buying-power arithmetic edge cases, default-state divergence.
   - **P2:** richer risk model, regime-conditional limit calibration.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **risk-control inventory** (entry points, limits, scalings, escalation states,
   defaults).
2. Audit fail-safe paths first (grep every scale/multiplier; prove ≤ 1.0× autonomous).
3. Audit per-leg veto by tracing one multi-leg intent.
4. Audit escalation SM and hazard exit.
5. Run **read-only** checks only:
   - `uv run pytest tests/risk/ -q`
   - `uv run pytest tests/acceptance/test_bt15_buying_power.py tests/determinism/test_hazard_exit_replay.py -q`
   - `uv run pytest tests/integration/test_hazard_exit_e2e.py -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/risk_engine_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): every fail-safe risk first.
2. **Risk-control inventory** (markdown table: entry point, input, scaling, default).
3. **Fail-safe audit** (every exposure-increasing path enumerated — largest section).
4. **Per-leg veto audit** (intent → legs trace).
5. **Escalation SM audit** (states, transitions, latch).
6. **Regime/hazard sizing coherence** (double-scaling, timing, exit-only).
7. **Buying power & limits audit**.
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing data runs.

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **modeling choice** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("if `current_state` returns unknown, `position_sizer`
  defaults to configured 1.0× while `basic_risk` defaults to min — divergent fail-safe")
  over adjectives.
- Treat **any** autonomous exposure increase as a P0 Inv-11 violation.
- Flag double-scaling explicitly (sizer × risk EV).
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for the default-state fail-safe alignment and
  any escalation-reset path as a follow-up PR plan."*
- *"Enumerate every multiplier in the risk path and prove each is ≤ 1.0× without explicit
  human authorization — audit commentary only."*
