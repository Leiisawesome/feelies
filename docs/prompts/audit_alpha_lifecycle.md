# Alpha lifecycle, promotion gates & layer validator audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies alpha
governance — the 5-state `AlphaLifecycle` SM, the F-2 declarative gate matrix, the F-1
promotion ledger, the F-5 three-layer threshold merge, the G2–G16 `LayerValidator`, and
the read-only `feelies promote` CLI.

---

## Mission

You are a senior platform-governance engineer and provenance auditor. Perform a
**read-only, evidence-based audit** of the feelies promotion / quarantine / capital-tier
machinery.

**Primary focus:** This is the gate between research and capital. Inv-13 (full provenance,
versioned and auditable) lives here: every promotion must trace to evidence, every config
change to an author and rollback path. A gate that can be bypassed, a ledger that loses
or mutates history, or a per-tick code path that reads the ledger (breaking Inv-5) is a P0.

**Goal:** Identify where gates are enforced vs. skippable, where the ledger is truly
append-only and atomic, where the threshold merge is deterministic, and where layer gates
(G2–G16) catch malformed alphas vs. let them through — without breaking invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-3, 5, 13**; glossary: promotion, gate matrix, promotion ledger, capital-stage tier, layer gate, operator CLI |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` — promotion canonical → this skill |
| 4 | `.cursor/skills/alpha-lifecycle/SKILL.md` (**owner**) |
| 5 | `.cursor/skills/testing-validation/SKILL.md` — acceptance thresholds (not gate wiring) |

CLI surface: `feelies promote` (`src/feelies/cli/promote.py`). Ledger must never be read on the tick path.


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

1. Skim `platform.yaml` `gate_thresholds:` and any alpha `promotion: { gate_thresholds: }`.


**Architecture (contractual):**

```
AlphaLifecycle SM: RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
                   (+ F-6 LIVE→LIVE capital-tier self-loop: SMALL_CAPITAL → SCALED)
promote_*(structured_evidence) → validate_gate(GateId, evidences, thresholds)
                               → on success: StateMachine.on_transition → ledger append
GateThresholds = merge(skill defaults, platform.yaml, per-alpha)   [F-5, registration-time]
LayerValidator G2–G16 runs on every alpha YAML before instantiation
feelies promote {inspect,list,replay-evidence,validate,gate-matrix}  [read-only, forensic]
```

**Hard invariants (non-negotiable):**

- Inv-13: full provenance — every transition recorded with evidence, trigger, ts, corr-id.
- Inv-5: ledger is forensic-only; production per-tick paths never read it (replay-safe).
- Inv-11: quarantine demotion always commits (fail-safe); validator only *flags* spurious.
- Gate matrix completeness: every `GateId` wired; every evidence type has validator + kind.

---

## Scope — files to audit

### Lifecycle & evidence

- `src/feelies/alpha/lifecycle.py` — 5-state SM + F-6 capital-tier self-loop
- `src/feelies/alpha/promotion_evidence.py` — evidence schemas, gate matrix,
  `validate_gate`, threshold merge helpers, `PROMOTE_CAPITAL_TIER_TRIGGER`
- `src/feelies/alpha/promotion_ledger.py` — append-only JSONL, schema version
- `src/feelies/alpha/registry.py` — `_resolve_gate_thresholds`, registration-time merge
- `src/feelies/core/state_machine.py` — generic SM + `on_transition` callback

### Layer validator & loader

- `src/feelies/alpha/layer_validator.py` — G2–G16 gates
- `src/feelies/alpha/loader.py`, `validation.py`, `discovery.py`
- `src/feelies/alpha/module.py` — `AlphaManifest`, `AlphaRiskBudget`, `ParameterDef`,
  `AlphaModule` protocol (the loaded-alpha surface the registry governs)
- `src/feelies/alpha/signal_layer_module.py` — `LoadedSignalLayerModule` (loader output;
  runtime signal semantics are a touchpoint of `audit_signal_alpha.md`)

### Operator CLI (read-only surface)

- `src/feelies/cli/promote.py`, `main.py`, `__main__.py`

### Tests (spec + gap analysis)

- `tests/alpha/test_lifecycle.py`, `test_lifecycle_f4.py`, `test_lifecycle_f6.py`
- `tests/alpha/test_promotion_evidence.py`, `test_promotion_ledger.py`
- `tests/alpha/test_registry.py`, `test_registry_per_alpha_thresholds.py`
- `tests/alpha/test_layer_validator_g2_g13.py`, `test_gate_g16.py`, `test_gate_g16_props.py`
- `tests/alpha/test_loader_promotion_block.py`, `test_loader_v03_blocks.py`,
  `test_module.py`, `test_validation.py`, `test_discovery.py`,
  `test_signal_layer_loader.py`, `test_schema_1_1_loading.py`, `test_layer_templates.py`,
  `test_discovered_alpha_specs_load.py`, `test_shipped_alpha_specs_load.py`
- `tests/cli/**`
- `tests/bootstrap/test_gate_thresholds_wiring.py` (F-5 merge wiring)
- `tests/research/test_promotion_pipeline_e2e.py`, `test_strict_mode_promotion_e2e.py`
- Acceptance: `tests/acceptance/test_strict_mode_default_true.py`,
  `test_strict_mode_reference_alphas.py`, `test_g16_rule_completeness.py`,
  `test_v02_no_trend_mechanism_parity.py`, `test_reference_alpha_load_invariants.py`

**Out of scope:** CPCV/DSR statistical math (see `audit_research_validation.md`), forensic
decay triggers (see `audit_forensics.md`), runtime signal/risk logic.

---

## Audit dimensions (answer each with evidence)

### A. Lifecycle SM correctness

1. Enumerate `_LIFECYCLE_TRANSITIONS`. Are illegal transitions rejected? Is the F-6
   `LIVE→LIVE` self-loop distinguishable from `LIVE→QUARANTINED` (same `from_state`)?
2. `current_capital_tier` algorithm: does it agree with a ledger replay byte-for-byte?
   Does quarantine + revalidate reset to `SMALL_CAPITAL`?
3. Atomicity: if the ledger write fails in `on_transition`, does the SM roll back
   (Inv-13)?

### B. Gate matrix & validation

1. `GATE_EVIDENCE_REQUIREMENTS`: every `GateId` present (`_check_matrix_completeness`)?
   Every required type has a validator + metadata `kind` (`_check_validator_coverage`)?
2. `validate_gate`: refuses missing-required / unsupported-type / duplicate-type before
   merging per-evidence errors?
3. Can a promotion succeed with empty or self-asserted evidence? Is `structured_evidence`
   XOR legacy `PromotionEvidence` enforced (both/neither → `ValueError`)?

### C. Threshold merge determinism (F-5)

1. Three-layer merge (skill defaults → platform.yaml → per-alpha): non-mutating
   (`dataclasses.replace`), run once at registration, immutable thereafter?
2. YAML grammar: field validation, bool-not-int strictness, no string→number coercion —
   identical for platform and per-alpha entry points?
3. Could a per-alpha override *loosen* a gate below a platform floor without authorization?

### D. Promotion ledger (Inv-13, Inv-5)

1. Append-only: any code path that rewrites/truncates the JSONL? Schema-version check on
   read?
2. Round-trip: `evidence_to_metadata` ↔ `metadata_to_evidence` lossless for all evidence
   kinds (legacy `{"evidence": {...}}` and F-2 shapes)?
3. **Forensic-only contract:** grep production code for any per-tick read of the ledger.
   Does ledger presence perturb replay (audit A-DET-02)?

### E. Layer validator (G2–G16)

1. For each gate, state what it enforces and whether it raises a distinct
   `LayerValidationError` subclass. Any gate that logs-and-continues where it should block?
2. `enforce_layer_gates` flag: confirm G9–G16 **always** block regardless; only G1/G3
   downgrade to warnings.
3. G16 strict mode default (`enforce_trend_mechanism: true`): schema-1.1 SIGNAL/PORTFOLIO
   missing `trend_mechanism:` is rejected? Cross-check `AGENTS.md` known-failure note.
   > **Auditor note:** `docs/three_layer_architecture.md` §9 still claims "only G12–G15
   > are blocking; G1–G11 warnings logged" — that predates the invariants glossary and is
   > stale. The glossary (`enforce_layer_gates` entry) is canonical; flag the doc drift,
   > do not "resolve" the conflict in the doc's favor.

### F. Operator CLI (read-only / fail-safe)

1. Confirm the CLI never writes the ledger and never imports orchestrator/risk production
   code (Inv-5 / Inv-10). Timestamps *rendered*, not read from wall clock?
2. Exit codes pinned (0/1/2/3) as documented? `replay-evidence` distinguishes OK /
   SKIPPED / FAIL correctly?

### G. Test & validation gaps + prioritized recommendations

1. Map invariants (provenance, append-only, gate completeness, merge determinism,
   forensic-only) to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (gate-bypass attempt, ledger tamper detection,
   merge-determinism property) — specs only.
3. Tiers:
   - **P0:** gate bypass, ledger mutation/loss, per-tick ledger read, non-atomic
     transition, threshold loosening without authorization.
   - **P1:** lossy evidence round-trip, gate that warns instead of blocks, CLI side effects.
   - **P2:** richer evidence types, CLI ergonomics, schema migration tooling.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **gate matrix snapshot** (GateId → required evidence types → thresholds) and a
   **lifecycle transition table** from code.
2. Audit `validate_gate` + the matrix completeness checks first.
3. Audit the ledger (append-only, round-trip, forensic-only).
4. Audit the threshold merge and layer validator.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/alpha/test_lifecycle.py tests/alpha/test_lifecycle_f6.py tests/alpha/test_promotion_evidence.py tests/alpha/test_promotion_ledger.py -q`
   - `uv run pytest tests/alpha/test_layer_validator_g2_g13.py tests/alpha/test_gate_g16.py tests/alpha/test_registry_per_alpha_thresholds.py -q`
   - `uv run feelies promote gate-matrix --json`
   Do not modify production code or the ledger.

---

## Output format (strict)

Write the audit report to `docs/audits/alpha_lifecycle_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top provenance/bypass risks first.
2. **Gate matrix snapshot** (markdown table).
3. **Lifecycle SM audit** (transitions, capital tier, atomicity).
4. **Gate validation audit** (matrix completeness, evidence enforcement).
5. **Threshold merge audit** (determinism, no unauthorized loosening).
6. **Ledger audit** (append-only, round-trip, forensic-only contract).
7. **Layer validator audit** (G2–G16, block vs warn).
8. **CLI audit** (read-only, exit codes).
9. **Test gap matrix**.
10. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented limitation** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("a per-alpha `gate_thresholds` override lowers
  `cpcv_min_mean_sharpe` below the platform floor with no authorization check") over
  adjectives.
- Treat any gate-bypass or ledger-mutation path as a P0 Inv-13 violation.
- Any production per-tick read of the ledger is a P0 (breaks Inv-5 / A-DET-02).
- Respect the read-only/forensic-only contract of the CLI.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for transition atomicity and any gate that warns
  instead of blocks as a follow-up PR plan."*
- *"Attempt to construct a malformed alpha YAML that passes G2–G16 but violates a layer
  invariant — describe it as a counterexample test spec, don't ship it."*
