# Monitoring & safety-controls audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
operational safety surface — the kill switch, alerting, health state, telemetry,
structured logging, and the session recorder — with Inv-11 (fail-safe) as the lens.

---

## Mission

You are a senior trading-operations and safety auditor. Perform a **read-only,
evidence-based audit** of the feelies monitoring/safety layer.

**Primary focus:** This layer is the platform's autonomic nervous system. Inv-11 is
absolute here: safety controls may only *tighten* exposure autonomously; loosening
requires human re-authorization, and every control must **fail closed** on its own error.
A kill switch that fails open, an alert that never fires, or a health state that degrades
upward is a direct path to uncontrolled capital loss.

**Goal:** Identify where safety controls fail-safe vs. fail-open, where trigger coverage is
complete vs. gapped, where health/alerting reflects reality vs. lags it, and where
observability is sufficient to diagnose a live incident — without changing behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-11**; glossary: hazard exit |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/live-execution/SKILL.md` (**owner**) — `safety-controls.md` supplement |
| 5 | `.cursor/skills/risk-engine/SKILL.md` — hazard exit controller |
| 6 | `.cursor/skills/regime-detection/SKILL.md` — hazard spike writer |

**Not shipped:** tiered circuit breaker / capital throttle tables in skills — verify against `monitoring/` code before P0.


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §14 (monitoring & observability).


**Architecture (contractual):**

```
runtime signals (PnL, latency, data health, fill drift, regime hazard)
  → health state machine → alerting → kill_switch (halt / flatten)
  → telemetry + structured_logging (provenance for incident review)
  → paper_session_recorder (paper-run capture)
```

**Hard invariants (non-negotiable):**

- Inv-11: controls only tighten autonomously; loosening needs human re-auth; **fail closed**.
- Inv-10: timestamps via injectable clock (so paper/live capture is replay-consistent).
- Inv-13: enough provenance/telemetry to reconstruct any decision post-incident.

---

## Scope — files to audit

### Safety controls

- `src/feelies/monitoring/kill_switch.py` — halt/flatten triggers and arming
- `src/feelies/monitoring/health.py` — health state machine / degradation
- `src/feelies/monitoring/alerting.py` — alert thresholds and routing

### Observability

- `src/feelies/monitoring/telemetry.py`, `structured_logging.py`
- `src/feelies/monitoring/horizon_metrics.py`, `in_memory.py`
- `src/feelies/monitoring/paper_session_recorder.py`

### Tests (spec + gap analysis)

- `tests/monitoring/test_kill_switch.py`, `test_alerting.py`, `test_in_memory.py`,
  `test_sensor_metrics.py`
- Health coverage lives partly outside `monitoring/`: `tests/ingestion/test_ingest_health.py`,
  `tests/kernel/test_data_integrity_runtime.py`. Note: `monitoring/health.py` has **no
  dedicated test module** — flag this coverage gap.
- Integration: `tests/integration/test_paper_rth_safety.py`

**Out of scope:** the upstream detectors themselves (regime/hazard/risk — audited
separately); here the focus is **whether monitoring reacts correctly and fail-safe**.

---

## Audit dimensions (answer each with evidence)

### A. Kill switch fail-safe (Inv-11) — highest priority

1. On trigger, does the kill switch **halt new entries and/or flatten** deterministically?
   Does it block the order path, or merely log?
2. **Fail closed on its own error:** if the kill-switch evaluation throws, is the result
   "halt" (safe) or "continue trading" (unsafe)?
3. Arming/disarming: can it be disarmed autonomously, or only by explicit human action?
4. Latency: how fast does a trigger propagate to the order path? Any window where orders
   still flow after trigger?

### B. Trigger coverage

1. Enumerate every kill-switch / health trigger condition (PnL drawdown, latency, data
   staleness/gap, fill-rate drift, error rate, regime hazard). Map each to its source.
2. Coverage gaps: which failure modes have **no** trigger (e.g. silent data corruption,
   broker disconnect, runaway order rate)?
3. Thresholds: justified or arbitrary? Are they configurable and bounded fail-safe?

### C. Health state machine

1. Formalize health states and transitions. Is degradation **monotone** under sustained
   problems, and does recovery require an explicit/affirmative condition (not a single
   benign tick)?
2. Can health ever transition *upward* (less safe) autonomously in a way that loosens
   control (Inv-11)?
3. How do orchestrator/bootstrap consume health — does a degraded state actually reduce
   exposure?

### D. Alerting

1. Do alerts fire on the conditions that matter, and are they deduplicated without
   suppressing genuine re-alerts?
2. Any alert that is computed but never routed/surfaced (dead alert)?
3. Severity mapping aligned with operator response?

### E. Observability & provenance (Inv-13, Inv-10)

1. Is there enough structured logging / telemetry to reconstruct a decision and a
   kill-switch firing post-incident?
2. Clock: does the recorder/telemetry use the injectable clock so paper/live capture is
   replay-consistent (Inv-10)? Any `datetime.now()`?
3. `paper_session_recorder`: does it capture what's needed to compare paper vs backtest?

### F. Test & validation gaps + prioritized recommendations

1. Map invariants (fail-closed kill switch, monotone health, trigger coverage, alert
   delivery) to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (kill-switch-throws → halt, health-never-loosens
   property, trigger-coverage matrix) — specs only.
3. Tiers:
   - **P0:** kill switch fails open / disarms autonomously / only logs; health loosens
     autonomously; an uncovered catastrophic failure mode.
   - **P1:** arbitrary thresholds, dead alerts, propagation-latency window, wall-clock in
     recorder.
   - **P2:** richer telemetry, operator dashboards, incident-replay tooling.

Each item: component, `file:line`, one-sentence fix, expected impact on safety.

---

## Working method

1. Build a **safety-control inventory** (control, trigger conditions, action, fail
   direction on error, disarm authority).
2. Audit the kill switch fail-closed behavior first (including its own error path).
3. Audit the health SM for monotone degradation.
4. Map trigger coverage against known failure modes; find the gaps.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/monitoring/ tests/ingestion/test_ingest_health.py tests/kernel/test_data_integrity_runtime.py -q`
   - `uv run pytest tests/integration/test_paper_rth_safety.py -q` (note: paper safety path)
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/monitoring_safety_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top fail-open / coverage-gap risks first.
2. **Safety-control inventory** (markdown table: control, trigger, action, fail direction).
3. **Kill-switch audit** (fail-closed, latency, disarm authority — deep dive).
4. **Trigger-coverage matrix** (failure mode × covered? × threshold justified?).
5. **Health-SM audit** (monotone degradation, consumption).
6. **Alerting audit** (fire, dedup, dead alerts).
7. **Observability & provenance audit** (clock, telemetry sufficiency).
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented limitation** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("if `kill_switch.evaluate()` raises, the caller
  swallows it and continues → fails open") over adjectives.
- A kill switch that fails open, or any control that loosens autonomously, is a P0.
- Treat an uncovered catastrophic failure mode (e.g. broker disconnect with open
  positions) as a P0.
- Any `datetime.now()` in the recorder/telemetry path is an Inv-10 finding.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for kill-switch fail-closed behavior and any
  uncovered catastrophic failure mode as a follow-up PR plan."*
- *"Produce the full failure-mode × trigger-coverage matrix as a standalone table — audit
  commentary only."*
- *"Design a 'kill-switch evaluation throws → system halts' test — spec only, no code."*
