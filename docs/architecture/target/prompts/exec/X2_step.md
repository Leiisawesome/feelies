# X2 — Execute one step

**Runs in:** Cursor, Agent mode, Opus. **One step per chat.** Reused for every step.
**Attach:** `X0_CORE_EXEC.md` + this file + `out/phase7_migration.md` + `out/exec/LEDGER.md` + the source folders the step declares

The GO line names the step: `Execute step S-07 only.`

---

## 0. Restate

Before touching anything, quote back from the plan:

```
STEP:            S-nn <title>
CLOSES:          <gap IDs>
PROBLEM:         <one line>
FILES:           <exact list>
PARITY IMPACT:   <hold | break: named hashes>
BLAST RADIUS:    <local | boundary | platform-wide>
DELETES:         <what goes>
VALIDATED BY:    <tests>
ROLLBACK:        <procedure>
```

If your restatement does not match the plan verbatim, you read the wrong step — stop.

Apply the CORE-EXEC §H escalation: if this step touches the parity surface, the kill switch, order submission, or `ExecutionBackend`, treat it as `platform-wide` regardless of its plan classification.

## 1. Pre-flight

```
git status --porcelain              # must be empty
git rev-parse --abbrev-ref HEAD     # must be arch/exec
uv run python tools/exec/baseline.py capture --label pre-S-nn
```

The capture must match the previous step's post-baseline. **If it does not, someone changed the tree outside the process** — stop and report.

Then branch:

```
git checkout -b exec/S-nn
```

## 2. Conformance test first — and prove it fails

Write or enable the test named in `VALIDATED BY`. Run only that test.

**It must fail.** Capture the failure output verbatim; it goes in the ledger as proof the test is load-bearing.

If it passes before the implementation, **stop**. Either the test is not testing the gap, or the gap does not exist. Report which you believe and why. Do not proceed to implement.

## 3. Implement

The smallest change in `FILES` that makes the test pass.

- No file outside `FILES`. If the change genuinely needs one, that is a plan defect — stop and report it.
- No opportunistic renaming, reformatting, import reordering, or annotation tidying.
- Found a bug on the way? Record it for the ledger's `FINDINGS`. Do not fix it.

## 4. Verify

```
uv run pytest <the step's test> -q          # must now pass
uv run pytest -q                            # full suite
uv run pytest tests/determinism -q          # replay corpus
uv run python tools/exec/baseline.py capture --label post-S-nn
uv run python tools/exec/verify_step.py S-nn --base <pre SHA>
```

`verify_step.py` reports four comparisons. **All four must be clean:**

| Check | Fails when |
|---|---|
| Files | the diff touches anything outside `FILES` |
| Parity | any hash moved that `PARITY IMPACT` did not name |
| Tests | any previously-passing test now fails |
| Net delta | actual module / symbol / branch counts contradict `DELETES` or `NET DELTA` |

## 5. Parity gate

- **Declared hold, actual hold** → proceed.
- **Declared break, actual break, same set** → **STOP.** Report expected-vs-actual hash sets and hand off. The operator re-baselines; you do not. Never run `scripts/rebaseline_parity_hashes.py`.
- **Any undeclared movement** → **STOP.** Revert the step (§7). This is a stop-the-line condition, not a discrepancy to reconcile.

## 6. Blast-radius gate

- `local` → report and proceed to commit.
- `boundary` → present the full diff plus verification output, wait for explicit approval.
- `platform-wide` → present the diff, verification output, and the rollback procedure; wait for explicit go/no-go. **Silence is not approval.**

## 7. Commit, or revert

On pass:

```
git add <declared files only>
git commit -m "S-nn: <title>

Closes: <gap IDs>
Parity: <hold | rebaselined by operator, see ledger>
Blast radius: <class>"
```

On any stop-the-line condition:

```
git checkout arch/exec
git branch -D exec/S-nn
```

Record the failure in the ledger with `VERDICT: reverted` and what was learned. **Never fix forward.**

## 8. Ledger

Append the CORE-EXEC §I block. Every field populated, backed by captured output — including the step-2 failure text.

## 9. Report

Five lines, no more:

```
S-nn      passed | reverted | blocked
tests     <before> -> <after>
parity    declared <x> | actual <y> | MATCH/MISMATCH
files     N declared, N touched, clean/dirty
next      S-nn+1 <title> (<blast radius>)
```

**HARD STOP.** Do not begin the next step.
