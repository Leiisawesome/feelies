# EXEC-RUNBOOK — Feelies migration execution

The design pack produced a locked plan. This pack executes it, one step at a time, under gates that make an undeclared change impossible to commit quietly.

**Prerequisite:** `docs/architecture/target/out/phase7_migration.md` exists with its Definition-of-Done checklist fully checked. If not, stop — `X1` will refuse anyway.

---

## Contents

```
prompts/X0_CORE_EXEC.md     standing contract — attach to EVERY step
prompts/X1_baseline.md      pre-execution: verify lock, prove green, capture baseline
prompts/X2_step.md          the per-step loop — reused for every step
prompts/X2_ONESHOT.md       X0+X2 merged into a single paste; no attachments needed
prompts/X3_integration.md   merge a batch, re-verify jointly, re-baseline
prompts/X4_abort.md         rollback, including undoing a bad re-baseline
tools/exec/baseline.py      capture/compare git + tests + parity constants + evidence
tools/exec/verify_step.py   declared-vs-actual checker; plan parser; ledger reconcile
exec-guardrail.mdc          Cursor always-on rule — REPLACES arch-guardrail.mdc
```

---

## Why this pack is shaped differently from the design pack

The guardrail model inverts. In design, the protection was *"never write to `src/`."* Here writing to `src/` is the entire job, so the protection becomes *"never write outside what this step declared, and never let a number move that this step did not predict."*

Two repository-specific facts drive the design:

**The parity manifest is the oracle.** `tests/determinism/parity_manifest.py` registers named `(hash, event_count)` pairs across the replay corpus, and `test_parity_manifest` catches drift between modules. That gives an objective before/after answer stronger than the test suite alone: a refactor that silently changes replay output is the worst possible outcome, because it looks like success.

**`scripts/rebaseline_parity_hashes.py` is a loaded gun.** Its documented workflow — run it, paste constants, commit — is correct for a human doing a deliberate re-baseline. In an agentic loop the failure mode is automatic: *test fails → rebaseline → test passes → done*, which converts a caught regression into a committed one. **The agent never runs it.** That rule appears in `X0`, in `X2`, and in the always-on guardrail, deliberately three times.

---

## PRE-EXECUTION — do these before any step

### 1. Install the pack

```powershell
$Pack = "$HOME\Downloads\feelies-exec-pack\feelies-exec"
Get-ChildItem $Pack -Recurse -File | Unblock-File

New-Item -ItemType Directory -Force -Path 'docs\architecture\target\prompts\exec' | Out-Null
New-Item -ItemType Directory -Force -Path 'docs\architecture\target\out\exec'     | Out-Null
New-Item -ItemType Directory -Force -Path 'tools\exec'                            | Out-Null

Copy-Item "$Pack\prompts\*.md"        'docs\architecture\target\prompts\exec\' -Force
Copy-Item "$Pack\EXEC-RUNBOOK.md"     'docs\architecture\target\'              -Force
Copy-Item "$Pack\tools\exec\*.py"     'tools\exec\'                            -Force
Copy-Item "$Pack\exec-guardrail.mdc"  '.cursor\rules\'                         -Force
```

### 2. Swap the guardrails

```powershell
Remove-Item '.cursor\rules\arch-guardrail.mdc' -Force
Get-ChildItem '.cursor\rules' -Name
```

The design rule forbids `src/` writes and will block every step. Expect to see `exec-guardrail.mdc`, `karpathy-guidelines.mdc`, `platform-invariants.mdc`.

### 3. Check the plan is machine-readable

```powershell
uv run python tools\exec\verify_step.py --list
```

Every step must parse with all eleven P7 fields present, and every parity-breaking step must **name its hashes**. `PARITY IMPACT: hashes will change` is reported as unparseable — that is intentional, P7 called it a blocker.

Fix any reported defect **in the plan**, then re-lock. Do not work around it here.

### 4. Prove the baseline is green

```powershell
uv run pytest -q
uv run pytest tests\determinism -q
$env:PYTHONHASHSEED="random"; uv run pytest tests\determinism\test_hash_seed_independence.py -q; Remove-Item Env:\PYTHONHASHSEED
```

**A red baseline stops everything.** Every subsequent step becomes uninterpretable — you cannot tell a step's breakage from pre-existing breakage. A pre-existing failure becomes **step S-00** in an amended plan, with its own conformance proof, executed first.

### 5. Capture the reference baseline

```powershell
git checkout -b arch/exec
uv run python tools\exec\baseline.py capture --label pre
```

Records git state, the full test summary, every `EXPECTED_*_HASH`/`_COUNT` constant under `tests/determinism/`, and a fresh evidence snapshot. Exits non-zero if the suite is red.

Check the evidence snapshot against the Phase 0 numbers. **Drift means main moved since the review**, and the gap table may be stale — worth knowing now rather than at step 9.

### 6. Open the ledger

Run the `X1` prompt in Cursor; it writes the ledger header and reports lock status, baseline colour, parse results, drift, and the first step.

---

## THE STEP LOOP

One step per chat. Fresh chat every time.

**Two ways to run a step.** Use whichever suits the moment; they enforce identical rules.

**A — one-shot (simplest).** Open `prompts/X2_ONESHOT.md`, replace every `S-NN` with the step ID, paste into a fresh chat. Nothing to attach: it tells the agent which files to read from disk and which to ignore. Best for `local` and `boundary` steps and for keeping the context tight.

**B — attach set (more explicit context).** Attach `X0_CORE_EXEC.md` + `X2_step.md` and let Cursor index the relevant packages up front. Better for `platform-wide` steps where the agent benefits from seeing the surrounding packages before it starts.

**For B, generate the attach set — do not choose it by hand:**

```powershell
uv run python tools\exec\verify_step.py --attach S-01
```

It prints the `@`-reference line and the GO line, both ready to paste. The set is derived from the step's own `FILES`, `VALIDATED BY`, `PARITY IMPACT`, and `BLAST RADIUS`:

| Included | Source |
|---|---|
| The four process docs | fixed: X0, X2, the plan, the ledger |
| Declared files that exist | `FILES` |
| Their parent packages | the engine boundary the step works inside — a file cannot be changed correctly without its siblings and its `__init__` |
| Declared directory scopes | `FILES`, trailing-slash entries |
| Landing folders for files the step will create | `FILES` / `VALIDATED BY`, reported separately since they cannot be attached |
| `tests/determinism` | only when parity is declared to break, or the step is platform-wide |
| `src/feelies/core` + `src/feelies/bus` | only when the step changes a contract or event type |

**Two exclusions that matter:**

- **The Phase 0–6 outputs are not attached.** They are design rationale. In execution they invite re-litigating decisions the plan already settled — the plan is the contract, the reasoning behind it is not in scope.
- **Never `@Codebase` or semantic search.** It returns plausible partial context, which is precisely what the scope discipline of a step cannot tolerate. Explicit paths only.

The agent runs the loop: restate → pre-flight → **failing conformance test** → implement → verify → parity gate → blast-radius gate → commit → ledger → stop.

**Your gates:**

| Blast radius | What you do |
|---|---|
| `local` | Read the five-line report. |
| `boundary` | Read the diff. Approve or reject explicitly. |
| `platform-wide` | Read the diff and the rollback. Explicit go/no-go. **Silence is not approval.** |
| Declared parity break | You run `scripts/rebaseline_parity_hashes.py`, paste constants into the owning module *and* the manifest, commit referencing the step ID. The agent does not. |

**Accept a step when** `verify_step.py` reports CLEAN on all four checks, the ledger entry is complete including the step-2 failure text, and the report's `next` line points where you expect.

---

## INTEGRATION

After each batch, and mandatorily after any `platform-wide` step, run `X3`. Steps were each proven against the baseline they started from; a batch was never proven together. The cumulative parity delta must equal the union of declared breaks — anything extra is an interaction effect between two individually-safe steps.

```powershell
uv run python tools\exec\verify_step.py --reconcile
uv run python tools\exec\baseline.py compare --before docs\architecture\target\out\exec\baseline_pre.json --after docs\architecture\target\out\exec\baseline_post-batch-1.json
```

`--reconcile` catches commits with no ledger entry, which is how an unreviewed change surfaces.

---

## ABORT

Run `X4`. Classify, revert, verify restoration against `baseline_pre.json`, record root cause.

The serious case is §4 — an erroneous re-baseline, where constants were updated to match a change that should not have been made, so tests now pass against a wrong reference. That is why re-baselining is human-gated and why `baseline_pre.json` is kept for the whole campaign.

**Never fix forward.** A reverted step with a recorded finding is worth more than a fixed-forward step nobody can review. `ROOT CAUSE: plan defect` means the plan is amended before retry — not retried harder.

---

## Command reference

| Purpose | Command |
|---|---|
| Parse and validate the plan | `uv run python tools\exec\verify_step.py --list` |
| Capture a baseline | `uv run python tools\exec\baseline.py capture --label <name>` |
| Fast capture, no tests | `... capture --label <name> --skip-tests` |
| Compare two baselines | `uv run python tools\exec\baseline.py compare --before <a> --after <b>` |
| Parity only | `... compare --before <a> --after <b> --parity-only` |
| Emit a step's attach set | `uv run python tools\exec\verify_step.py --attach S-07` |
| Inspect one step's parsed fields | `uv run python tools\exec\verify_step.py --show S-07` |
| Verify a step | `uv run python tools\exec\verify_step.py S-07 --base <sha>` |
| Ledger vs git | `uv run python tools\exec\verify_step.py --reconcile` |

`baseline.py` and `verify_step.py` only read and record. Neither writes to `src/` or `tests/`.

---

## Failure modes

| Symptom | Meaning | Action |
|---|---|---|
| `verify_step.py --list` reports MISSING fields | Plan not machine-readable | Fix the plan, re-lock. Not a workaround here. |
| Conformance test passes before implementation | Test is wrong, or the gap does not exist | Stop. Report which. Do not implement. |
| Undeclared parity movement | Step did something unpredicted | **Stop the line.** Revert. Never reconcile. |
| Agent proposes running the rebaseline script | Guardrail breach | Reject. Re-attach `X0`. |
| Files touched outside `FILES` | Plan defect or scope creep | Stop. Report the file and why. |
| `--reconcile` shows UNREVIEWED | A commit bypassed the process | Investigate before merging anything. |
| Cumulative parity delta exceeds declared union | Interaction between steps | Bisect. Do not absorb. |
| Net delta positive with no justification | Steps adding without deleting | Catch at batch 2, not batch 6. |
| Suite skip count mismatches a captured baseline | RTH-gated skips move with wall clock; S-09 gating-day re-ingest is done. Last full suite: 4812 passed / 29 skipped / 10 xfailed. Informational unless failed > 0 or the parity map moved. | See LEDGER.md -> DEFERRAL cache re-ingestion after S-09. |

---

## Delete when finished

`exec-guardrail.mdc` is `alwaysApply: true` and taxes every unrelated request. Remove it when the plan completes, along with `tools/exec/` if you do not want it in the repo long-term. The ledger and the baselines stay — they are the audit trail.
