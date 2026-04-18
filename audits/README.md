# `audits/` — How to invoke the Feelies audit

This directory holds the Living Audit Protocol (SOP), the report template, and one dated report per iteration. Reports diff cleanly against each other because every check ID and every section heading is stable across iterations.

## Files

- [`AUDIT_PROTOCOL.md`](AUDIT_PROTOCOL.md) — the SOP. Read this first every iteration. It lists every check ID, the method (grep / read / pytest / backtest), the pass criterion, and the severity if it fails. Versioned (`v1.0` at lock time).
- [`_template.md`](_template.md) — empty report skeleton. Copy to a dated file before filling.
- `YYYY-MM-DD-<slug>.md` — one report per iteration. The `baseline` report is the first run and the diff anchor for everything that follows.

## How an agent runs the audit

1. **Read `AUDIT_PROTOCOL.md` end-to-end.** It is the only context the agent needs for an iteration.
2. **Identify the prior report**: `Get-ChildItem audits/2*.md | Sort-Object Name | Select-Object -Last 1` (PowerShell). It is the diff anchor.
3. **Copy the template**: `Copy-Item audits/_template.md "audits/$(Get-Date -Format yyyy-MM-dd)-<slug>.md"`. Slugs: `baseline` for the first run, otherwise `iter-N`, `pre-paper`, `post-fix-<topic>`, etc.
4. **Walk Pillar A then Pillar B** in order. For each check, perform the listed Method, decide PASS / FAIL with severity, fill one line of evidence (file path + line number, grep hit count, or command output excerpt). Do **not** skip checks; mark `N/A` only when the protocol explicitly allows it.
5. **Run the embedded automation:**
   - `pytest -q`
   - `python scripts/run_backtest.py --demo` (twice, to verify parity hash stability)
   - `python scripts/run_backtest.py --demo --stress-cost 1.5`
   - `python scripts/run_backtest.py --demo --stress-cost 2.0`
   - Capture: parity hashes, trade count, gross/net PnL, max DD, kill-switch state, `tick_to_decision_latency_ns` p50/p95/p99.
6. **Compute deltas vs prior report** using `git diff --no-index <prior> <new>`. Record new BLOCKERs, resolved findings, new MAJORs.
7. **Re-print the Risk register.** Permanent findings stay until verifiably fixed by the next iteration.
8. **Apply `META-01`.** List every change to `.cursor/rules/platform-invariants.mdc` and `.cursor/skills/**` since the prior audit. Either add a new check ID covering the change, or justify in the META section why no new check is required.
9. **Compute the iteration verdict** using the six PASS conditions in `AUDIT_PROTOCOL.md` ("Pass/Fail criteria for an iteration").
10. **Print the one-line summary**: `verdict=PASS|FAIL BLOCKER=N MAJOR=N MINOR=N parity_hash_stable=Y/N tests_delta=+-N promotion_ready=research|paper|small|scaled`.

## When an iteration runs

Triggered by:

- Every merge to `main` (CI / agent-driven).
- Before any `mode:` switch in `platform.yaml` (BACKTEST -> PAPER, PAPER -> LIVE).
- Any change to `.cursor/rules/` or `.cursor/skills/` (the audit's source of truth changed).
- Any change to high-blast-radius modules: `src/feelies/bootstrap.py`, `src/feelies/kernel/orchestrator.py`, `src/feelies/risk/`, `src/feelies/execution/`, `src/feelies/ingestion/`, `src/feelies/alpha/`, `src/feelies/core/events.py`, `src/feelies/core/state_machine.py`.
- Weekly regardless, against latest `main`, to catch drift.

## What the agent must NOT do

- **Do not modify `AUDIT_PROTOCOL.md` opportunistically.** Any change requires a protocol revision bump (`v1.0` -> `v1.1`) and a corresponding `META-01` entry in the next report.
- **Do not delete prior reports.** They are the diff history.
- **Do not edit source code as part of the audit.** The audit observes; remediation is a separate ticket the user authorizes.
- **Do not skip the embedded automation.** Static checks alone do not satisfy `A-DET-02`, `A-PERFB-02`, `B-FILL-02`, `B-E2E-01..03`, `B-PROMO-04`.

## Promotion gating

A FAIL verdict halts promotion to a higher operating mode (BACKTEST -> PAPER -> LIVE) until the next PASS. A new permanent risk-register entry requires explicit user acknowledgement before the next mode switch.
