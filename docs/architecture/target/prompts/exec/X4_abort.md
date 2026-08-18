# X4 — Abort and rollback

**Runs in:** Cursor, Agent mode, Opus. Invoked when a step or batch must be undone.
**Attach:** `X0_CORE_EXEC.md` + this file + `out/exec/LEDGER.md`

Aborting is a normal outcome, not a failure of the process. A reverted step with a recorded finding is worth more than a fixed-forward step nobody can review.

---

## 1. Classify

| Situation | Action |
|---|---|
| Step failed verification, not yet committed | §2 — discard the branch |
| Step committed on its own branch, not merged | §2 — discard the branch |
| Step merged to `arch/exec` | §3 — revert the merge |
| Batch merged, interaction effect found | §3 for each, newest first |
| Parity re-baselined in error | §4 — **the serious case** |

## 2. Discard an unmerged step

```
git checkout arch/exec
git branch -D exec/S-nn
git status --porcelain          # must be empty
uv run pytest -q                # must match the pre-step baseline exactly
```

## 3. Revert a merged step

```
git revert -m 1 <merge sha>
uv run pytest -q
uv run pytest tests/determinism -q
uv run python tools/exec/baseline.py capture --label post-revert-S-nn
```

Revert in reverse plan order. The parity state after reverting must return to what it was before the step — if it does not, the step was not independently revertible, which is a **plan defect worth recording loudly**, because the same property was claimed for every other step.

## 4. Undo an erroneous re-baseline

The dangerous case: parity constants were updated to match a change that should not have been made, so the tests now pass against a wrong reference.

```
git log --oneline -- tests/determinism/parity_manifest.py
git checkout <sha before the bad rebaseline> -- tests/determinism/
uv run pytest tests/determinism -q
```

Then confirm the restored constants match `baseline_pre.json`:

```
uv run python tools/exec/baseline.py compare \
    --before docs/architecture/target/out/exec/baseline_pre.json \
    --after  <current capture> --parity-only
```

Any hash still differing from `pre` that was not a legitimately approved break is unrecovered. Do not proceed until the parity set matches the approved state exactly.

## 5. Record

Append to the ledger:

```
## ABORT  S-nn
DATE:        <iso>
TRIGGER:     <which stop-the-line condition>
EVIDENCE:    <the output that caused it>
SCOPE:       <branch discarded | merge reverted | rebaseline undone>
RESTORED TO: <sha>, verified by <test + parity output>
ROOT CAUSE:  <implementation error | plan defect | stale gap | environment>
PLAN ACTION: <no change | amend step S-nn | re-open Phase 7>
```

`ROOT CAUSE: plan defect` means the plan is amended before that step is retried — not retried harder.

## 6. Report

```
aborted      S-nn
trigger      <condition>
restored     <sha>, tests <n> passed, parity MATCHES pre
root cause   <class>
plan action  <what must change before retry>
```

**HARD STOP.** Do not retry the step in this session.
