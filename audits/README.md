# `audits/` — How to invoke the Feelies audit

This directory holds the Living Audit Protocol (SOP), the report template, and one dated report per iteration. Reports diff cleanly against each other because every check ID and every section heading is stable across iterations.

## Files

- [`AUDIT_PROTOCOL.md`](AUDIT_PROTOCOL.md) — the SOP. Read this first every iteration. It lists every check ID, the method (grep / read / pytest / backtest), the pass criterion, and the severity if it fails. Current revision **`v1.3` LOCKED** `2026-05-03` — replay-harness alignment (retired `run_backtest.py --demo`) + `B-MULTI-02` arbitration wiring; authoritative text lives only in **`AUDIT_PROTOCOL.md`** (`v1.2` = `2026-05-02` seal · `v1.1` / `v1.0` prior).
- [`_template.md`](_template.md) — report skeleton. Copy to a dated file before filling; **`Protocol version:` must match `AUDIT_PROTOCOL.md`** (currently **`v1.3 LOCKED (2026-05-03)`**).
- `.cursor/plans/recurring-codebase-audit-protocol_301e015c.plan.md` *(optional)* — architecture narrative; **not authoritative** for checks.
- `YYYY-MM-DD-<slug>.md` — one report per iteration. The `baseline` report is the first run and the diff anchor for everything that follows.

## How an agent runs the audit

1. **Read `AUDIT_PROTOCOL.md` end-to-end.** It carries every check definition; `_template.md` / this README never override it.
2. **Identify the prior report**: `Get-ChildItem audits/2*.md | Sort-Object Name | Select-Object -Last 1` (PowerShell). It is the diff anchor.
3. **Copy the template**: `Copy-Item audits/_template.md "audits/$(Get-Date -Format yyyy-MM-dd)-<slug>.md"`. Slugs: `baseline` for the first run, otherwise `iter-N`, `pre-paper`, `post-fix-<topic>`, etc. Confirm **`Protocol version:`** in the new file matches **`AUDIT_PROTOCOL.md`**.
4. **Walk Pillar A (`A1`–`A16`, incl. `A8b`) then Pillar B (`B1`–`B14`)** in protocol order. For each check, perform the listed Method, decide PASS / FAIL with severity, fill one line of evidence (file path + line number, grep hit count, or command output excerpt). Do **not** skip checks; mark `N/A` only when the protocol explicitly allows it.
5. **Run the embedded automation** (see `AUDIT_PROTOCOL.md` “How an iteration runs” step 4 — **Replay harness**):
   - `pytest -q`
   - **Primary:** `python scripts/run_backtest.py --date … --config …` (with `MASSIVE_API_KEY`) twice; then `--stress-cost 1.5` / `2.0`. Capture footer `parity_hash (both)`, PnL, DD, kill-switch, latency percentiles where applicable.
   - **Substitute (document deferral):** `pytest tests/integration/test_phase4_e2e.py -q` (e.g. twice for smoke); does **not** replace stress/portfolio PnL checks — record `MAJOR` deferral per SOP.
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
- Any change to high-blast-radius modules: `src/feelies/bootstrap.py`, `src/feelies/kernel/orchestrator.py`, `src/feelies/risk/`, `src/feelies/execution/`, `src/feelies/ingestion/`, `src/feelies/alpha/`, `src/feelies/features/`, `src/feelies/sensors/`, `src/feelies/signals/`, `src/feelies/composition/`, `src/feelies/services/`, `src/feelies/core/events.py`, `src/feelies/core/state_machine.py`.
- Weekly regardless, against latest `main`, to catch drift.

## What the agent must NOT do

- **Do not modify `AUDIT_PROTOCOL.md` opportunistically.** Any change requires a protocol revision bump (**`v1.3` → `v1.4+`**) and a corresponding `META-01` entry in the report that merges the bump.
- **Do not delete prior reports.** They are the diff history.
- **Do not edit source code as part of the audit.** The audit observes; remediation is a separate ticket the user authorizes.
- **Do not skip the embedded automation.** Static checks alone do not satisfy `A-DET-02`, `A-PERFB-02`, `B-FILL-02`, `B-E2E-01..03`, `B-PROMO-04` — use the **primary** replay path or the **documented substitute + deferral** in `AUDIT_PROTOCOL.md`.

## Promotion gating

A FAIL verdict halts promotion to a higher operating mode (BACKTEST -> PAPER -> LIVE) until the next PASS. A new permanent risk-register entry requires explicit user acknowledgement before the next mode switch.
