# X1 — Pre-execution: lock verification and baseline capture

**Runs in:** Cursor, Agent mode, Opus. Once, before any step.
**Output:** `docs/architecture/target/out/exec/baseline_pre.json` + `LEDGER.md` header
**Attach:** `X0_CORE_EXEC.md` + this file + `out/phase7_migration.md` + `out/phase5_gaps.md`

You are not changing any code in this phase. You are proving the starting line is where the plan thinks it is.

---

## 1. Verify the lock

Read `phase7_migration.md` and confirm every item:

- [ ] Design thesis exists and fits a page
- [ ] Every Phase 5 gap has a step, or an explicit deferral with a reason
- [ ] Every step has all eleven fields from the P7 template, none blank
- [ ] Every step is independently shippable and independently revertible
- [ ] Conformance tests are sequenced before the refactors they protect
- [ ] Every step touching the parity surface declares its parity impact **with named hashes**, not "hashes will change"
- [ ] Running net delta is reported
- [ ] Assumption register has ≥ 5 entries
- [ ] Do-not-change list exists

**Any unchecked box means the plan is not locked.** Report which, and stop. Do not repair the plan here — it goes back to Phase 7.

Additionally, verify the plan is **machine-readable**: `tools/exec/verify_step.py` parses steps by their `STEP:` / `FILES:` / `PARITY IMPACT:` / `BLAST RADIUS:` / `DELETES:` field labels. Run:

```
uv run python tools/exec/verify_step.py --list
```

Every step must parse. A step that does not parse is a plan defect — report it and stop.

## 2. Prove the baseline is green

```
uv run pytest -q
uv run pytest tests/determinism -q
PYTHONHASHSEED=random uv run pytest tests/determinism/test_hash_seed_independence.py -q
```

On PowerShell the last one is:

```
$env:PYTHONHASHSEED="random"; uv run pytest tests/determinism/test_hash_seed_independence.py -q; Remove-Item Env:\PYTHONHASHSEED
```

**A red baseline stops everything.** You cannot measure a refactor against a broken starting point — every subsequent step becomes uninterpretable. If anything fails:

- Report exactly what failed and whether it is pre-existing (check `git log` on the failing test).
- Do **not** fix it as part of this phase.
- A pre-existing failure becomes **step S-00** in an amended plan, executed before everything else, with its own conformance proof.

## 3. Capture the baseline

```
uv run python tools/exec/baseline.py capture --label pre
```

This records: git SHA and branch, the full test summary, every `EXPECTED_*_HASH` and `EXPECTED_*_COUNT` constant under `tests/determinism/`, and a fresh `measure.py` evidence snapshot for the net-delta arithmetic.

Confirm the output reports a parity constant count consistent with the manifest, and that the evidence snapshot matches the Phase 0 baseline. **If the evidence snapshot has drifted from Phase 0, main has moved since the review** — report the delta and stop, because the gap table may be stale.

## 4. Set up branches

```
git checkout -b arch/exec
```

Step branches come off `arch/exec`, one per step, named `exec/S-nn`. Nothing merges to main until the plan completes or the operator says otherwise.

## 5. Swap the guardrails

```
git rm --cached .cursor/rules/arch-guardrail.mdc
```

Delete `arch-guardrail.mdc` and install `exec-guardrail.mdc` in its place. The design rule forbids `src/` writes and will block every step.

## 6. Open the ledger

Create `docs/architecture/target/out/exec/LEDGER.md` with a header recording: date, plan version and SHA, baseline SHA, baseline test counts, parity constant count, and the total step count with their blast-radius distribution.

## 7. Report

State plainly:

- Plan lock: verified / **N boxes unchecked**
- Baseline: green / **red, N failures**
- Steps parsed: N of N
- Evidence drift vs Phase 0: none / **describe**
- First step to execute, its blast radius, and whether it is human-gated

**HARD STOP.** Do not begin S-01.
