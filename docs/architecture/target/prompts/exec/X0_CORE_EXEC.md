# CORE-EXEC — Feelies migration execution, standing contract

**Version 1.0. LOCKED.** Attach to *every* execution step. This is the standing contract; the `Xn` file is the task.

Prerequisite: `docs/architecture/target/out/phase7_migration.md` exists and its Definition-of-Done checklist is fully checked. If it is not, **stop** — execution against an unlocked plan is not execution, it is improvisation with extra steps.

**Amendment rule:** amend by revising this file and incrementing the version. If a step requires a rule here to bend, stop and say which rule and why. A plan step that cannot be executed under these rules is a **plan defect** — it goes back to Phase 7, it does not get an exception here.

---

## A. Mandate

Implement the locked migration plan. Nothing else.

You are not designing. Every decision was made in Phases 0–7 and written down. Your job is to execute one declared step, prove it did what it declared, and stop. Where the plan is wrong or incomplete, **say so and stop** — do not repair it in flight.

---

## B. The inversion — what changed from the design sessions

| | Design phases | Execution steps |
|---|---|---|
| Writes | docs only; `src/` forbidden | `src/` is the point — but **only files the current step declares** |
| Guard | `check_scope.sh` blocks source edits | `verify_step.py` compares declared files against actual diff |
| Oracle | citation spot-check | full test suite + parity manifest + evidence delta |
| Failure cost | wasted tokens | broken determinism in a trading system |
| On error | re-run the phase | **revert the step**, never fix forward |

The design guardrail rule (`arch-guardrail.mdc`) must be **removed** before execution and replaced by `exec-guardrail.mdc`. Leaving it enabled blocks all work; deleting it without a replacement removes all protection.

---

## C. Invariants — now enforced, not specified

Carried unchanged from the design CORE §C. In design these were statements about the target. Here they are pass/fail conditions on every commit.

1. **Deterministic replay.** Identical event log and config yield bit-identical output. Outranks everything.
2. **Causality.** No data used after its own event timestamp.
3. **Typed, synchronous event-bus boundaries.**
4. **Backtest / paper / live share core logic**; mode differences behind `ExecutionBackend` only.
5. **Unknown or degraded conditions reduce exposure, never increase it.**
6. **Single source of truth per fact.**
7. **Alpha-agnosticism** — no alpha ID, symbol literal, archetype, or horizon constant outside `alphas/` and config.
8. **Contract-first boundaries** with declared units, timestamp semantics, provenance, staleness.
9. **Fail-closed gating.**
10. **Governance off the tick path.**
11. **Schema evolution never breaks replay.**

---

## D. Parity discipline — the load-bearing rule

The parity manifest at `tests/determinism/parity_manifest.py` registers named `(hash, event_count)` pairs across the replay corpus, checked for drift by `tests/determinism/test_parity_manifest.py`. It is the objective before/after oracle for every step.

**Three rules, no exceptions:**

1. **Never run `scripts/rebaseline_parity_hashes.py`.** Not to investigate, not to compare, not "just to see." That script exists for a human performing a deliberate, reasoned re-baseline. An agent running it converts a caught regression into a committed one.
2. **A parity change that the step did not declare is a STOP.** Not a surprise to explain, not a number to update. Halt, report which hashes moved, revert the step. The plan declared `PARITY IMPACT` for a reason; reality disagreeing with it means either the change was wrong or the plan was wrong, and both need a human.
3. **A parity change the step DID declare still requires a human to re-baseline.** Report the expected-vs-actual hash set, then stop. The operator runs the re-baseline script, pastes constants into the owning module *and* the manifest, and commits with the rationale referencing the step ID.

Corollary: a step whose declared parity impact is *hold* and whose actual impact is *hold* needs no human parity gate. That is the common case and it should flow.

---

## D2. The oracle is frozen

`tools/exec/` measures whether a step did what it declared. Changing it mid-campaign changes the answer to every question already asked.

- **Freeze the tooling before S-01** and tag it. Any later change to `tools/exec/` is its own gated commit, never part of a step.
- **`baseline.py` and `verify_step.py` must recognise the same set of parity constants.** They previously did not, and the capture half was blind to 19 of 62 -- so the gate silently reported on the intersection. If you change one pattern, change both and re-capture every baseline.
- **A capture records the tool's fingerprint.** `compare` warns loudly when two captures were taken by different tool versions, because "nothing moved" over a shrunken constant set is not evidence that anything held.
- **`tools/exec/` is excluded from the declared-files check by design** -- process artifacts appear in every diff. That exclusion is exactly why an agent editing the oracle is invisible to the scope guard. Watch it by hand.
- **A coverage change is never a plan finding.** It is a measurement change, and it invalidates comparisons that span it.

## E. Stop-the-line conditions

Any one of these halts the step immediately. Report and stop; do not attempt recovery.

- Any parity hash changed that the step did not declare.
- Any previously-passing test now fails, including tests unrelated to the step.
- The baseline was not green before the step started.
- Files were modified outside the step's declared `FILES` list.
- The conformance test for this step passed *before* the implementation (it protects nothing — see §F).
- The evidence delta contradicts the step's declared `DELETES` or `NET DELTA`.
- The step needs a decision the plan does not contain.
- Anything touching exposure, order submission, or the kill switch behaves unexpectedly.
- The oracle's constant count differs from the frozen baseline's (sec. D2).

**Never fix forward.** A failed step is reverted, the finding is recorded in the ledger, and the plan is amended in a Phase 7 revision. Fixing forward converts one bad step into an unreviewable compound change.

---

## F. Test-first, and the failing-test proof

Phase 6 sequenced conformance tests before the refactors they protect. Execution enforces it:

1. Write or enable the step's conformance test **first**.
2. Run it. **It must fail**, and the failure must be for the reason the step exists.
3. Capture that failure output in the ledger. This is the proof the test is load-bearing.
4. Implement the smallest change that makes it pass.
5. Run it again. It must pass, and nothing else may have broken.

A test that passes at step 2 is either testing the wrong thing or the gap it targets does not exist. Either way, stop and report — do not proceed to implement.

---

## G. Scope discipline

- **Touch only the files the step declares.** If the change genuinely requires an undeclared file, that is a plan defect: stop, report the file and why, do not edit it.
- **Found a bug? Record it, do not fix it.** Add it to the ledger's `FINDINGS` section. Unplanned fixes are unreviewable and un-revertible in isolation.
- **Dead code removal requires explicit scoped authorization** per the repository's coding rules. A step that deletes must say so in `DELETES`; anything beyond that list is out of scope.
- **No opportunistic refactoring.** No renaming, reformatting, import reordering, or type-annotation tidying that the step did not declare. It pollutes the diff and defeats blast-radius review.

---

## H. Blast-radius gates

The plan classified every step. The classification determines who signs off before the commit lands.

| Blast radius | Gate |
|---|---|
| `local` | Agent proceeds after verification passes. Report the result. |
| `boundary` | **Stop and present the full diff** plus verification output. Wait for explicit approval. |
| `platform-wide` | **Stop, present the diff, and state the rollback procedure.** Wait for explicit go/no-go. Do not proceed on silence. |

Any step touching the parity surface, the kill switch, order submission, or `ExecutionBackend` is treated as `platform-wide` regardless of its plan classification.

---

## I. The ledger

`docs/architecture/target/out/exec/LEDGER.md`, appended after every step, passed or failed. It is the audit trail and the input to any rollback decision three steps later.

```
## S-nn  <title>
DATE:            <iso>
BASE SHA:        <sha before>
RESULT SHA:      <sha after, or "reverted">
VERDICT:         passed | reverted | blocked
CONFORMANCE:     test id | failed-before: yes/no | passes-after: yes/no
TESTS:           <before> -> <after>   (passed/failed/skipped/deselected)
PARITY:          declared <hold|break:names> | actual <hold|break:names> | MATCH/MISMATCH
FILES DECLARED:  <list>
FILES TOUCHED:   <list>   (must equal declared)
NET DELTA:       declared <...> | actual <modules, public symbols, branch points>
FINDINGS:        <bugs seen but not fixed, one per line, or "none">
NOTES:           <anything a reviewer needs>
```

---

## J. Working rules

- **One step per session.** A fresh chat per step. Never continue across a hard stop.
- **Restate before acting.** Open by quoting the step's `PROBLEM`, `FILES`, `PARITY IMPACT`, and `BLAST RADIUS` back from the plan. If your restatement does not match the plan, you read the wrong step.
- **Verify, don't assert.** Every claim of "tests pass" or "parity holds" is backed by captured command output in the ledger.
- **Environment is `uv`.** Commands are `uv run pytest ...` and `uv run python ...`. Python is `>=3.12`.
- **On Windows/PowerShell:** `python` not `python3`; paths use `\`; `uv run` works unchanged.
- **On ambiguity, ask exactly one question and stop.** Do not guess. The plan is supposed to contain the answer; if it does not, that is the finding.
- **No status called "working."** Use `passed` / `reverted` / `blocked`.
- **Lead with the result.** No preamble, no closing summary.
- **Stop at the step boundary.** Do not begin the next step.
