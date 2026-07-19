# Claude Code audit pack usage

This pack runs repository audits through Claude Code one prompt at a time. The
`.cursor/rules/` and `.cursor/skills/` files are used as plain repository context; they
are not Cursor-only runtime features.

## 1. Preflight

Run from the repository root:

```powershell
$env:PYTHONHASHSEED='0'
uv run pytest tests/docs/test_audit_prompt_structure.py tests/docs/test_prompt_coverage_map.py tests/docs/test_internal_links.py -q
```

If this fails, fix the prompt pack before running audits.

## 2. Prepare Claude Code bundles

Choose the audit date that should appear in report filenames:

```powershell
$env:PYTHONHASHSEED='0'
uv run python scripts/run_audit_pack.py prepare --date 2026-07-02 --force
```

This writes:

```text
docs/audits/_runs/2026-07-02/
  manifest.json
  audit_data_ingestion.bundle.md
  audit_sensor.bundle.md
  ...
```

Each bundle contains `AGENTS.md`, `CLAUDE.md`, the required `.cursor/rules/` and
`.cursor/skills/` context files, and exactly one `docs/prompts/audit_*.md` prompt.

To prepare only one audit:

```powershell
uv run python scripts/run_audit_pack.py prepare --date 2026-07-02 --audit risk_engine --force
```

## 3. Run audits in Claude Code

For each `*.bundle.md`:

1. Open a fresh Claude Code session at the repository root.
2. Paste the full bundle as the initial task message.
3. Let Claude Code read the bundled context and inspect the repository.
4. Require it to write exactly the report named in the bundle, under `docs/audits/`.
5. Do not allow production-code, config, baseline, or ledger edits during the audit pass.

Run bundles independently. Do not combine multiple audit prompts into one Claude Code
session.

## 4. Verify reports

After all reports are written:

```powershell
$env:PYTHONHASHSEED='0'
uv run python scripts/run_audit_pack.py verify --date 2026-07-02
```

The verifier fails if:

- an expected report is missing
- a P0/P1 line lacks `Inv-N`
- a P0/P1 line lacks `path:line` evidence
- the report does not mention the owning skill
- the report lacks a test or coverage gap matrix
- prohibited placeholder text remains, such as `TBD` or `citation needed`

To also fail if non-audit files changed:

```powershell
uv run python scripts/run_audit_pack.py verify --date 2026-07-02 --check-worktree
```

## 5. Synthesize findings

Generate a consolidated summary:

```powershell
uv run python scripts/run_audit_pack.py synthesize --date 2026-07-02
```

This writes:

```text
docs/audits/audit_pack_summary_YYYY-MM-DD.md
```

Use the summary to deduplicate findings and plan follow-up fix PRs. Fixes should be
scoped by invariant or subsystem, not mixed across unrelated audit areas.

## Recommended run order

1. Foundations: `audit_kernel`, `audit_core_clock_config`, `audit_determinism`
2. Backtest reality: `audit_data_ingestion`, `audit_execution_fills`, `audit_harness_cli`
3. Trading logic: `audit_sensor`, `audit_regime`, `audit_signal_alpha`, `audit_composition`
4. Capital path: `audit_risk_engine`, `audit_position_management`
5. Governance/safety: `audit_research_validation`, `audit_alpha_lifecycle`,
   `audit_forensics`, `audit_monitoring_safety`, `audit_live_execution`
6. Performance: `audit_performance`

## Quality rules

- Treat P0/P1 findings without `Inv-N` and `path:line` as invalid.
- Treat `.cursor/skills/*/SKILL.md` as the contract for expected behavior.
- Treat **Not shipped** and **Design Targets** as aspirational unless code, tests, or
  operator docs claim the feature is live.
- Prefer minimal test-backed recommendations over broad redesign proposals.
- Keep the audit pass read-only; implementation belongs in follow-up PRs.
