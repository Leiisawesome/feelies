# Backtest harness, reporting & operator CLI audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
operator-facing surface — the backtest run harness, PnL/trade reporting, JSONL emit, the
`feelies` CLI (backtest path), and operator scripts. The lens is **run reproducibility and
report fidelity**, not the math inside each layer.

---

## Mission

You are a senior research-tooling and reproducibility auditor. Perform a **read-only,
evidence-based audit** of the feelies harness / CLI / scripts surface.

**Primary focus:** This is what researchers and operators actually run. A backtest report
whose PnL doesn't faithfully reconstruct the fills, a JSONL emit that loses information, a
run that isn't reproducible from its config + cache, or a CLI that exits 0 on failure
silently corrupts every downstream decision — even when the engine underneath is correct.

**Goal:** Identify where runs are reproducible vs. environment-dependent, where reports
reconcile with the underlying fills vs. drift, where the CLI/exit-code contract is sound
vs. misleading, and where operator scripts are safe vs. footguns — without changing
behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5, 13**; glossary: operator CLI, replay |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` — CLI routing table |
| 4 | `.cursor/skills/backtest-engine/SKILL.md` (**owner**) — `feelies backtest` |
| 5 | `.cursor/skills/alpha-lifecycle/SKILL.md` — `feelies promote` (read-only forensics) |
| 6 | `.cursor/skills/research-workflow/SKILL.md` — artifact reproducibility |

Split ownership: ingest path in `audit_data_ingestion.md`; promote CLI deep-dive in `audit_alpha_lifecycle.md`.


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `AGENTS.md` (CLI / smoke / backtest commands) and `docs/paper_rth_test_runbook.md`.
   (provenance).


**Architecture (contractual):**

```
config + cache → backtest_prep (ingest/resequence, OWNED by audit_data_ingestion)
              → backtest_runner (run loop) → orchestrator
              → backtest_report (PnL / trade aggregation) + backtest_jsonl (emit)
feelies CLI: backtest → harness; promote → lifecycle (OWNED by audit_alpha_lifecycle)
scripts/: run_backtest, run_paper, smoke_pipeline, compare_paper_backtest, ...
```

**Hard invariants (non-negotiable):**

- Inv-5: same config + cache + params → bit-identical run **and** identical report.
- Inv-13: reports/emit carry enough provenance to trace every number to an event.
- Report numbers must reconcile with the fills/positions they summarize (no drift).
- CLI exit codes are a contract: non-zero on any failure; never exit 0 on error.

---

## Scope — files to audit

### Backtest harness (run + report — owned here)

- `src/feelies/harness/backtest_runner.py` — run loop / orchestration (the **run** path;
  the `ingest_data()` / resequence path is a *touchpoint* — owned by `audit_data_ingestion`)
- `src/feelies/harness/backtest_report.py` — PnL / trade-list / daily-PnL aggregation
- `src/feelies/harness/backtest_jsonl.py` — JSONL emit fidelity
- `src/feelies/harness/backtest_cli.py` — harness CLI glue
- `src/feelies/harness/backtest_prep.py` — *touchpoint only* (resequence audited elsewhere)

### Operator CLI (backtest path — owned here)

- `src/feelies/cli/backtest.py`, `cli/env.py`, `cli/main.py`, `cli/__main__.py`
  (`cli/promote.py` is owned by `audit_alpha_lifecycle` — touchpoint here)

### Operator scripts

- `scripts/run_backtest.py`, `scripts/run_paper.py`, `scripts/run_paper_soak.py`
- `scripts/smoke_pipeline.py`, `scripts/compare_paper_backtest.py`
- `scripts/split_backtest_emit.py`
- `scripts/generate_bt12_fixtures.py` (regenerates BT-12 acceptance fixtures —
  fixture-mutating; audit for guardrails)
- `scripts/rebaseline_parity_hashes.py`, `scripts/record_perf_baseline.py`,
  `scripts/record_paper_perf_baseline.py`
  (destructive/baseline-mutating — audit for guardrails, not behavior)

### Tests (spec + gap analysis)

- `tests/harness/test_backtest_cli.py`, `test_backtest_prep.py`, `test_backtest_report.py`
- `tests/cli/test_backtest_cli.py`
- `tests/scripts/test_run_paper.py`, `test_split_backtest_emit.py`
- Acceptance: `tests/acceptance/test_backtest_app_baseline.py`,
  `test_backtest_app_config_keys.py`, `test_bt12_reference_alpha_validation.py`,
  `test_bt13_portfolio_research_only.py`

**Out of scope:** ingest/resequence/replay correctness (see `audit_data_ingestion.md`),
fill/cost model (see `audit_execution_fills.md`), `feelies promote` (see
`audit_alpha_lifecycle.md`), per-layer math.

---

## Audit dimensions (answer each with evidence)

### A. Run reproducibility (Inv-5) — highest priority

1. Given identical config + disk cache + params, is the run bit-identical across two
   invocations and across machines? Any environment dependence (cwd, env vars, locale,
   thread count, dict/JSON ordering)?
2. Is the config fully captured/echoed into the run artifacts so a run is reconstructable?
3. Does the runner pin or record the code/version and alpha manifest (provenance)?

### B. Report fidelity (the core question)

1. `backtest_report.py`: do the reported PnL, trade list, and daily-PnL **reconcile**
   with the underlying fills/positions? Recompute a small case by hand and compare.
2. Off-by-one / double-count in trade aggregation, daily bucketing at session edges,
   sign conventions on shorts?
3. Are costs/fees reflected in reported PnL consistently with the cost model?
4. Rounding: report rounding vs internal Decimal — any misleading display vs stored value?

### C. JSONL emit fidelity (Inv-13)

1. `backtest_jsonl.py`: is the emit lossless and round-trippable? Does it match what a
   replay of the same run would produce (cross-ref the determinism JSONL tests)?
2. `split_backtest_emit.py`: does splitting preserve ordering and completeness?

### D. CLI contract

1. Exit codes: does `feelies backtest` (and harness CLI) exit non-zero on **every** failure
   (bad config, missing cache, run error)? Any path that swallows errors and exits 0?
2. `test_backtest_app_config_keys.py`: are unknown/misspelled config keys rejected, or
   silently ignored (a classic silent-misconfiguration footgun)?
3. Arg parsing / help / `--json` stability where applicable.

### E. Operator scripts safety

1. `compare_paper_backtest.py`: is the sim-vs-live divergence computation correct and
   apples-to-apples (same normalizer, same clock)? It feeds promotion decisions.
2. `rebaseline_parity_hashes.py` / `record_perf_baseline.py`: are these **clearly gated**
   as intentional, destructive operations (they overwrite the platform's correctness
   baselines)? Could they be run accidentally in CI or by a researcher?
3. `run_paper.py` / `run_paper_soak.py`: max-runtime / safety wiring present?

### F. Test & validation gaps + prioritized recommendations

1. Map invariants (reproducibility, report reconciliation, emit fidelity, exit-code
   contract, config-key strictness) to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (report-reconciles-with-fills property, exit-code-on-error
   cases, JSONL round-trip) — specs only.
3. Tiers:
   - **P0:** report doesn't reconcile with fills, run not reproducible, CLI exits 0 on
     error, baseline-mutating script ungated, lossy JSONL.
   - **P1:** config keys silently ignored, daily-bucketing edge cases, paper-compare
     mismatch.
   - **P2:** CLI ergonomics, richer provenance in reports, script hardening.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **run-artifact inventory** (what a backtest run writes; what's captured for
   provenance).
2. Audit `backtest_report.py` reconciliation first — recompute a small case by hand.
3. Audit reproducibility (two-run diff) and JSONL fidelity.
4. Audit CLI exit codes and config-key strictness.
5. Audit baseline-mutating scripts for guardrails.
6. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
7. Run **read-only** checks only:
   - `uv run pytest tests/harness/ tests/cli/test_backtest_cli.py tests/scripts/ -q`
   - `uv run pytest tests/acceptance/test_backtest_app_baseline.py tests/acceptance/test_backtest_app_config_keys.py -q` (disk cache APP/2026-03-26 required)
   - `uv run python scripts/smoke_pipeline.py` (read-only smoke; no writes to baselines)
   Do not modify production code, baselines, or parity hashes.

---

## Output format (strict)

Write the audit report to `docs/audits/harness_cli_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top reproducibility/fidelity risks first.
2. **Run-artifact inventory** (markdown table).
3. **Reproducibility audit** (two-run / cross-machine determinism).
4. **Report-fidelity audit** (reconciliation with fills — deep dive, with a worked example).
5. **JSONL emit audit**.
6. **CLI contract audit** (exit codes, config strictness).
7. **Operator-scripts safety audit** (baseline-mutating guardrails).
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented limitation** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("daily-PnL buckets fills by receipt date, not session
  date, so a post-16:00 fill lands on the wrong day → report ≠ fills") over adjectives.
- Treat a report that doesn't reconcile with the fills as a P0 — it lies to every reviewer.
- Treat any ungated baseline-mutating script as a P0 operational hazard.
- Stay read-only; never overwrite a baseline or parity hash to make something pass.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for report-vs-fills reconciliation and CLI
  exit-code-on-error as a follow-up PR plan."*
- *"Recompute the APP/2026-03-26 backtest PnL from the trade list by hand and reconcile
  against `backtest_report` output — methodology + result only, no code changes."*
- *"Propose a guardrail design for `rebaseline_parity_hashes.py` (explicit confirm flag) —
  spec only, no code."*
