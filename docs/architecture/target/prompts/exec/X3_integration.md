# X3 — Integration checkpoint

**Runs in:** Cursor, Agent mode, Opus. After every batch of steps, and mandatorily after any `platform-wide` step.
**Attach:** `X0_CORE_EXEC.md` + this file + `out/exec/LEDGER.md` + `out/phase7_migration.md`

Merging step branches is where independently-verified steps become jointly-unverified. Each step was proven against the baseline it started from; a batch was never proven together.

---

## 1. Reconcile the ledger against git

```
git log --oneline arch/exec
uv run python tools/exec/verify_step.py --reconcile
```

Every commit on `arch/exec` maps to exactly one ledger entry with `VERDICT: passed`, and every passed entry maps to exactly one commit. A commit without a ledger entry is an unreviewed change — find out what it is before merging anything.

## 2. Merge the batch

```
git checkout arch/exec
git merge --no-ff exec/S-nn      # one at a time, in plan order
```

Never squash across steps. Squashing destroys the independent-revertibility property the plan was built to preserve.

## 3. Re-verify the joint state

```
uv run pytest -q
uv run pytest tests/determinism -q
uv run python tools/exec/baseline.py capture --label post-batch-<n>
uv run python tools/exec/baseline.py compare \
    --before docs/architecture/target/out/exec/baseline_pre.json \
    --after  docs/architecture/target/out/exec/baseline_post-batch-<n>.json
```

The cumulative parity delta must equal the union of every declared break across the batch. **Anything extra is an interaction effect** — two steps that were individually safe and are jointly not. Bisect it; do not absorb it.

## 4. Cumulative net delta

Compare running totals against the plan's declared net delta (design CORE §G.10). Report modules, public symbols, and branch points: declared vs actual, cumulative.

A growing positive delta with no matching justification means steps are adding without deleting. That is drift from the design thesis, and it is worth catching at batch 2 rather than batch 6.

## 5. Re-baseline the reference point

The post-batch capture becomes the new `pre` reference for subsequent steps. Record the new baseline SHA in the ledger header.

## 6. Report

```
batch        <n>: S-aa..S-bb, N steps merged
tests        <before> -> <after>
parity       cumulative declared <set> | actual <set> | MATCH/MISMATCH
net delta    declared <...> | actual <...>
interactions none | <describe>
remaining    N steps, blast-radius distribution
```

**HARD STOP.**
