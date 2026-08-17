Windows/PowerShell. Use `python` not `python3`; `uv run` unchanged.

Execute migration step **S-NN**. Only that step. Stop at the hard stop.

# Read, in this order -- nothing else

1. `docs/architecture/target/out/phase7_migration.md` -> find the block beginning `STEP: S-NN`. That block is your entire specification.
2. `docs/architecture/target/out/exec/LEDGER.md` -> the last entry, to confirm where the campaign stands.
3. Only the files that step's `FILES` field declares, plus their package siblings.

**Do not read the Phase 0-6 outputs.** They are design rationale. In execution they invite re-litigating decisions the plan already settled; the plan is the contract, the reasoning behind it is out of scope. If a step cannot be executed without its rationale, that is a plan defect -- say so and stop.

**Do not use codebase-wide semantic search.** Explicit paths only. Semantic retrieval returns plausible partial context, which is exactly what a scope-disciplined step cannot tolerate.

# Standing rules -- these override default behaviour

- **Edit only files in the step's `FILES` field.** If the change genuinely needs another file, that is a plan defect: stop and report it. Do not edit it.
- **Never run `scripts/rebaseline_parity_hashes.py`.** Not to investigate, not to compare, not "just to see." Parity re-baselining is a human action. An agent running it converts a caught regression into a committed one.
- **Any parity hash change the step did not declare is a STOP.** Not a number to update, not a discrepancy to reconcile. Halt, report which moved, revert.
- **Write the conformance test first and prove it FAILS** before implementing. A test that passes beforehand protects nothing.
- **Never fix forward.** A failed step is reverted and the plan is amended. Fixing forward turns one bad step into an unreviewable compound change.
- **Found a bug outside the step? Record it as a finding. Do not fix it.**
- **No opportunistic renaming, reformatting, import reordering, or annotation tidying.** It pollutes the diff and defeats blast-radius review.
- **Stop the line** on any of: undeclared parity movement * a previously-passing test now failing * a red pre-step baseline * files touched outside `FILES` * the conformance test passing before implementation * evidence delta contradicting `DELETES`/`NET DELTA` * the step needing a decision the plan does not contain * anything unexpected around exposure, order submission, or the kill switch.
- **No status called "working."** Use `passed` / `reverted` / `blocked`.
- Lead with results. No preamble, no closing summary.

# The loop

## 0. Restate
Quote back from the plan, verbatim: `STEP`, `CLOSES`, `PROBLEM`, `FILES`, `PARITY IMPACT`, `BLAST RADIUS`, `VALIDATED BY`, `DELETES`, `NET DELTA`, `ROLLBACK`.

If your restatement does not match the plan, you read the wrong block -- stop.

Escalation: if this step touches the parity surface, the kill switch, order submission, or `ExecutionBackend`, treat it as `platform-wide` regardless of its stated classification.

## 1. Pre-flight
```
git status --porcelain
git rev-parse --abbrev-ref HEAD
uv run python tools\exec\baseline.py capture --label pre-S-NN
```
Working tree must be clean and HEAD on `arch/exec`. The capture must match the previous step's post-baseline; if it does not, the tree changed outside the process -- stop.

Then: `git checkout -b exec/S-NN`

## 2. Conformance test first -- prove it fails
Write or enable the test named in `VALIDATED BY`. Run only that test.

**It must fail**, for the reason the step exists. Capture the failure output verbatim -- it goes in the ledger as proof the test is load-bearing.

If it passes, stop. Either the test is wrong or the gap does not exist. Say which you believe and why. Do not implement.

## 3. Implement
The smallest change within `FILES` that makes the test pass.

## 4. Verify
```
uv run pytest <the step's test> -q
uv run pytest -q
uv run pytest tests/determinism -q
uv run python tools\exec\baseline.py capture --label post-S-NN
uv run python tools\exec\verify_step.py S-NN --base <pre SHA>
```
All four `verify_step` checks -- files, parity, tests, net delta -- must be clean.

## 5. Parity gate
- Declared hold, actual hold -> proceed.
- Declared break, actual break, same set -> **STOP.** Report expected-vs-actual hash sets and hand off. The operator re-baselines. You do not.
- Any undeclared movement -> **STOP.** Revert per sec.7.

## 6. Blast-radius gate
- `local` -> report and commit.
- `boundary` -> present the full diff plus verification output, wait for explicit approval.
- `platform-wide` -> present the diff, verification output, and the rollback procedure, wait for explicit go/no-go. **Silence is not approval.**

## 7. Commit, or revert
Pass:
```
git add <declared files only>
git commit -m "S-NN: <title>

Closes: <gap IDs>
Parity: <hold | rebaselined by operator, see ledger>
Blast radius: <class>"
```
Stop-the-line:
```
git checkout arch/exec
git branch -D exec/S-NN
```

## 8. Ledger
Append to `docs/architecture/target/out/exec/LEDGER.md`, every field populated from captured output including the step-2 failure text:

```
## S-NN  <title>
DATE:            <iso>
BASE SHA:        <sha before>
RESULT SHA:      <sha after, or "reverted">
VERDICT:         passed | reverted | blocked
CONFORMANCE:     <test id> | failed-before: yes/no | passes-after: yes/no
TESTS:           <before> -> <after>
PARITY:          declared <...> | actual <...> | MATCH/MISMATCH
FILES DECLARED:  <list>
FILES TOUCHED:   <list>
NET DELTA:       declared <...> | actual <...>
FINDINGS:        <bugs seen but not fixed, or "none">
NOTES:           <anything a reviewer needs>
```

## 9. Report -- five lines, no more
```
S-NN      passed | reverted | blocked
tests     <before> -> <after>
parity    declared <x> | actual <y> | MATCH/MISMATCH
files     N declared, N touched, clean/dirty
next      S-NN+1 <title> (<blast radius>)
```

**HARD STOP.** Do not begin the next step.
