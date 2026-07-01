# Post-trade forensics & decay detection audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
post-trade forensics — multi-horizon attribution (per-mechanism, per-regime), the
`DecayDetector`, fill attribution / TCA, and the operator-invoked quarantine path
(`QuarantineTriggerEvidence` → `AlphaLifecycle.quarantine`).

---

## Mission

You are a senior post-trade analytics and edge-decay auditor. Perform a **read-only,
evidence-based audit** of the feelies forensics layer.

**Primary focus:** This layer is the platform's feedback loop — it decides whether a live
edge is still real. Inv-4 (decay is the default) and Inv-11 (fail-safe) meet here: a decay
detector that under-fires keeps dead strategies on capital; an attribution that mis-buckets
PnL corrupts every promotion and quarantine decision downstream.

**Goal:** Identify where attribution math is sound vs. ad hoc, where expected-vs-realized
comparisons are statistically meaningful, where decay/crowding detection is calibrated vs.
arbitrary, and where the quarantine trigger is appropriately fail-safe — without breaking
invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-1, 4, 11, 13**; glossary: quarantine, quarantine-trigger evidence, trend mechanism breakdown |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/post-trade-forensics/SKILL.md` (**owner**) — **Not shipped**: auto-trigger, daily health JSON, dedicated forensic events |
| 5 | `.cursor/skills/alpha-lifecycle/SKILL.md` — operator-invoked `quarantine` + evidence schemas |

Quarantine demotion is fail-safe (Inv-11) but **not** auto-wired from forensics today.


Before running commands, follow `AGENTS.md` for environment/test guidance. If Claude Code
also loads `CLAUDE.md`, `AGENTS.md`, this prompt, and `.cursor/rules/` /
`.cursor/skills/` context take precedence for audit execution.

**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §6.10 (forensics module).


**Architecture (contractual):**

```
fills + Signal provenance (trend_mechanism, expected_half_life, regime)
  → MultiHorizonAttributor: PnL decomposed by mechanism family × regime × horizon
  → DecayDetector: expected vs realized slippage / hit-rate / net-alpha drift
  → QuarantineTriggerEvidence → operator/tooling calls `registry.quarantine(...)` (fail-safe commit; not auto-wired today)
```

**Hard invariants (non-negotiable):**

- Inv-1: PnL attributable by named mechanism family (provenance from `Signal`).
- Inv-4: decay is assumed; burden of proof is on continued viability.
- Inv-5: forensics is offline/forensic — never on the per-tick decision path.
- Inv-11: quarantine demotion always commits; spurious triggers only *flagged*.

---

## Scope — files to audit

### Forensics core

- `src/feelies/forensics/multi_horizon_attribution.py` — per-mechanism/regime/horizon PnL
- `src/feelies/forensics/decay_detector.py` — drift detection
- `src/feelies/forensics/analyzer.py` — orchestration / reporting
- `src/feelies/alpha/fill_attribution.py` — fill → alpha lineage

### Trigger surface

- `src/feelies/alpha/promotion_evidence.py` — `QuarantineTriggerEvidence`,
  `validate_quarantine_trigger`
- `src/feelies/alpha/lifecycle.py` — `quarantine` path (fail-safe commit)

### Tests (spec + gap analysis)

- `tests/forensics/test_tca.py`
- Acceptance: `tests/acceptance/test_decay_divergence.py`
- Cross-ref: `tests/alpha/test_promotion_evidence.py` (quarantine-trigger validator)

**Out of scope:** lifecycle SM mechanics (see `audit_alpha_lifecycle.md`), CPCV/DSR
pre-deployment stats (see `audit_research_validation.md`), live execution.

---

## Audit dimensions (answer each with evidence)

### A. Attribution correctness — highest priority

1. Multi-horizon attribution: state the decomposition in plain math. Does
   Σ(per-mechanism PnL) = total PnL with no double-counting or leakage across buckets?
2. Mechanism bucketing: does it read `Signal.trend_mechanism` / `expected_half_life`
   provenance, or re-infer (risking mismatch with Inv-1 claims)?
3. Regime bucketing: which `RegimeState` is used per trade, and is it the one in effect at
   entry (causal), not a later one?
4. Holding-period bucketing vs the alpha's *own* `expected_half_life_seconds`.

### B. Expected vs realized comparison (TCA)

1. Expected slippage / hit-rate / net-alpha: sourced from the alpha's disclosed
   `cost_arithmetic` and signal edge? Realized computed from fills — apples-to-apples?
2. Are comparisons statistically meaningful (sample size, variance), or point estimates
   presented as conclusions?
3. Sign conventions and units consistent between expected and realized?

### C. Decay detection calibration (Inv-4)

1. `DecayDetector`: what triggers a decay flag (threshold, window, statistic)? Are
   thresholds justified or arbitrary?
2. False-negative bias: could a genuinely-decayed edge stay undetected (the costly error
   under Inv-4)? False-positive cost?
3. Crowding / latency-disadvantage / microstructure-regime-change signals — present, or
   only raw PnL drift?

### D. Quarantine trigger (fail-safe)

1. `QuarantineTriggerEvidence` fields vs the skill's documented thresholds
   (net-alpha-negative days, hit-rate collapse, PnL compression, microstructure breaches,
   crowding symptoms). Aligned?
2. `validate_quarantine_trigger` only *flags* spurious triggers — confirm it never blocks
   the demotion (Inv-11).
3. Does the forensic layer actually *call* `AlphaLifecycle.quarantine`, or only produce
   evidence? Trace the wiring.

### E. Determinism & provenance

1. Is forensic computation deterministic given the same fills + provenance (so two audits
   agree)?
2. Does any forensic code read the promotion ledger or perturb the per-tick path (Inv-5)?

### F. Test & validation gaps + prioritized recommendations

1. Map invariants (attribution conservation, causal regime bucketing, decay sensitivity,
   fail-safe trigger) to tests — **covered / partial / missing** (note: `tests/forensics/`
   currently holds only `test_tca.py` — flag thin coverage).
2. Propose **minimal** new tests (attribution-conservation property, decay-sensitivity
   golden case) — specs only.
3. Propose offline validation: per-mechanism realized vs expected on cached fills
   (APP/2026-03-26) — methodology only.
4. Tiers:
   - **P0:** attribution leakage/double-count, non-causal regime bucketing, trigger that
     blocks demotion, decay detector that can't fire.
   - **P1:** arbitrary thresholds, weak statistical basis, missing crowding signals.
   - **P2:** richer attribution axes, automated decay reporting.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **forensic-metric inventory** (metric, formula, threshold, trigger).
2. Audit attribution conservation first (Σ buckets = total).
3. Audit expected-vs-realized comparison and decay thresholds.
4. Trace the quarantine trigger wiring end-to-end.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/forensics/test_tca.py tests/acceptance/test_decay_divergence.py -q`
   - `uv run pytest tests/alpha/test_promotion_evidence.py -q -k quarantine`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/forensics_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top decision-corruption risks first.
2. **Forensic-metric inventory** (markdown table).
3. **Attribution audit** (conservation, mechanism/regime/horizon bucketing — deep dive).
4. **Expected-vs-realized (TCA) audit**.
5. **Decay detection audit** (calibration, false-negative bias).
6. **Quarantine trigger audit** (fail-safe, wiring).
7. **Determinism & provenance audit**.
8. **Test gap matrix** (flag thin `tests/forensics/` coverage).
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing data runs.

Use code citations as `path:line` for every non-trivial claim.
When citing literature, give author-year-title, not vague "standard practice."
Distinguish **implementation bug** vs **modeling choice** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("attribution buckets by mechanism re-inferred from
  features, so a KYLE_INFO alpha's PnL can land in the INVENTORY bucket") over adjectives.
- Under Inv-4, treat a decay detector that **cannot fire** on a dead edge as a P0.
- The quarantine trigger must never be blockable (Inv-11).
- Respect that forensics is offline: no fixes that touch the per-tick path.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for attribution conservation and causal regime
  bucketing as a follow-up PR plan."*
- *"Propose an attribution-conservation property test (Σ per-mechanism PnL == total) —
  spec only, no code."*
- *"Compute per-mechanism realized vs expected slippage on disk cache APP/2026-03-26 —
  methodology only."*
