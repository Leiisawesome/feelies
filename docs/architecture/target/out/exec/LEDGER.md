# Execution ledger — feelies architecture migration

Append one CORE-EXEC §I block after every step, passed or failed. This header
records the starting line X1 proved.

## Header

| | |
|---|---|
| Opened | 2026-08-17 |
| Plan | `docs/architecture/target/out/phase7_migration.md` |
| Plan blob | `2c674a0e` (amended during X1; pre-amendment `95269d1`) |
| Baseline SHA | `8d56ccfc03677bad1d65bab8bd1bcefe595ede2e` |
| Branch | `arch/exec` |
| Full suite | 4757 passed, 0 failed, 29 skipped |
| Determinism corpus | 145 passed, 0 failed |
| Hash-seed independence | 1 passed under `PYTHONHASHSEED=random` |
| Parity constants captured | 62 — all 52 referenced by the 26-entry manifest, plus the 8 APP acceptance-oracle constants and 2 solver constants |
| Evidence | 196 modules, 43 197 sloc, 551 public symbols, 2 import cycles, alphaleak 2 — no drift vs Phase 0 |
| Capture | `docs/architecture/target/out/exec/baseline_pre.json` |

## Steps

35 steps: S-01 … S-34 plus S-11a.

| Blast radius | Count |
|---|---|
| `local` | 4 |
| `boundary` | 20 |
| `platform-wide` | 11 |

Parity-breaking: 4 — S-16, S-17, S-23, S-31. Matches §G.7's re-pin schedule.

## X1 — pre-execution

```
DATE:            2026-08-17
BASE SHA:        8d56ccfc03677bad1d65bab8bd1bcefe595ede2e
RESULT SHA:      e47b1d8, c9d0c9d, de57a6e (+ this ledger commit)
VERDICT:         passed (after one plan amendment, operator-authorised)
CONFORMANCE:     n/a — X1 writes no code
TESTS:           4757 passed / 0 failed / 29 skipped (unchanged; no src or tests edit)
PARITY:          declared hold | actual hold | MATCH
FILES DECLARED:  n/a
FILES TOUCHED:   docs/architecture/target/out/phase7_migration.md
                 docs/architecture/target/out/phase2_contracts.md
                 tools/exec/{baseline.py,verify_step.py}
                 tools/arch/{measure,inventory,gapscan,gatescan}.py
                 docs/architecture/target/out/exec/{LEDGER.md,baseline_pre.json}
NET DELTA:       none — no change under src/ or tests/
```

**First pass failed the lock.** `verify_step.py --list` exited 1 on five steps
whose `PARITY IMPACT` asserted both hold and movement with no constant named
(S-07, S-09, S-11, S-28, S-30), and S-31 — the widest re-pin in the plan — parsed
as `hold` because its field opens "Step 1: all 26 hold". The X1 §3 check that the
captured constant count is consistent with the manifest also failed: 43 of 52.

**Amendment, authorised by the operator before it was made.** Two edits, neither
changing any step's substance:

1. `phase7_migration.md` — added a leading `hold` / `break` verdict token to the
   six `PARITY IMPACT` fields above, naming S-31's ten constants; replaced the
   `0` and `+1` left in §G.7's **Cause** column for S-17 and S-23 with the causes
   stated in those steps' own blocks. 29 insertions, 8 deletions.
2. `tools/exec/` — `baseline.py` now matches values written across a newline
   inside parentheses (11 manifest hashes were invisible), captures the APP
   acceptance oracle, and parses pytest's `skipped` / `deselected` counts;
   `verify_step.py` recognises `_BASELINE_*` names and `tests/acceptance/` paths
   so those constants can be declared.

S-30 is declared `hold` rather than `break`: the plan pre-authorises no re-pin for
it and §G.7 does not schedule one, so a moved baseline there is an undeclared
change and a stop, which is what the block's own "the finding, not the failure"
already meant.

```
FINDINGS:
  F1  verify_step.py --show raises UnicodeEncodeError on any step whose text
      carries a non-cp936 character (S-31's "12.8 µs/quote") when the console
      code page is GBK. --list is unaffected. Workaround: PYTHONIOENCODING=utf-8.
  F2  §G.0 counts blast radius as 3 local / 22 boundary / 9 platform-wide, then
      names ten platform-wide steps; verify_step.py counts 4 / 20 / 11 over 35.
      Part of the gap is the tool escalating on prose — S-07 says "Not
      platform-wide" and is escalated for containing the phrase — and part is
      S-11a not being counted in §G.0. Not amended; out of the authorised scope.
  F3  §J.0's header says nineteen inherited assumptions; the Definition-of-Done
      says 21. Not amended.
  F4  CLOSED. X2 §1 requires `git status --porcelain` to be empty before every
      step and it could not be. Three causes, all removed: the exec pack was
      untracked and the guardrail deletion unstaged (both committed, e47b1d8);
      and the evidence scanners re-run at each step boundary wrote CRLF against
      a repo declaring `eol=lf`, dirtying the tree on every run. The churn was
      real, not stale stat data — `git checkout` then re-running measure.py
      reproduced it. measure/inventory/gapscan/gatescan now pass
      `newline="\n"`; verified by re-running all four to a clean tree.
  F5  CLOSED as three separate answers — see "Pre-execution items" below. Two
      of the three changed the plan's factual basis; A5.4 came back FALSE.
  F6  A5.4 is FALSE and S-31 cannot be executed as written. Of the 106 "uncalled
      public methods", the scanner's own per-item flags show 85 are called by
      tests and 7 more are reached by a `getattr` name literal; 14 are reached
      by nothing. Hand-verification of receiver collisions in both directions
      puts the genuinely-dead count at ~16. S-31's declared -106 public symbols
      becomes about -16, which turns the plan's headline from -73 to roughly
      +17. §G.6's ledger, §G.9's G44 row, S-31's NET DELTA and §G.10's wave-E
      justification all rest on the -106. Operator decision required.
  F7  tools/arch/hotpath.py:734 subtracts one occurrence that does not exist:
      for a property it computes `all_text.count(f".{fn.name}") - 1` with the
      comment "minus the def itself", but a `def foo(self)` line contains no
      `.foo`. Any property read exactly once in src/ is therefore reported as
      uncalled. 11 of the 41 properties in the 106 are in exactly that state
      and their single reader is production code. Not fixed — outside X1.
  F8  Phase 7 missed a §F-class finding that Phase 2 had already recorded.
      §K.1.4 and the Definition-of-Done both state that no phase had a method
      for finding a ninth unassigned responsibility; phase2_contracts.md:687
      records "a ninth unassigned responsibility: risk-model provenance", using
      that word, and :2011 lists it beside the horizon grid. Recorded as
      §F.9 (unresolved) in the Phase 2 addendum; needs an operator.
NOTES:
  Guardrails were already swapped before this session: arch-guardrail.mdc
  deleted on disk, exec-guardrail.mdc installed, arch/exec checked out. The
  deletion is now staged and committed (e47b1d8).
```

### Pre-execution items the plan required to close

**U-3 — does `broker/ib/` reconcile position-of-record beyond the fill stream?
No.** All four files under `src/feelies/broker/ib/` were read end to end (873
lines). The adapter subclasses `EWrapper`/`EClient` and implements exactly three
callbacks — `nextValidId`, `orderStatus`, `error` (`connection.py:353-452`).
A repo-wide search for `reqPositions`, `reqAccountUpdates`, `reqAccountSummary`,
`reqExecutions`, `reqOpenOrders` and `updatePortfolio` across `src/` returns
zero matches. Positions come solely from cumulative `orderStatus` data converted
to per-delta acks (`router.py:312-357`) and applied by
`Orchestrator._reconcile_fills`. Nothing compares a broker-reported position to
the internal store. The `live-execution` skill documents a 30s position query and
a reconnect snapshot as a design target; neither is shipped.

*Consequences.* §F.4 is a **build, not a wiring task**, which is the branch S-21
and S-30 §F.4 were waiting on. WL-2 is thereby discharged in the favourable
direction: Phase 2 set the condition that if reconciliation must be built from
scratch, engine 8's action can be designed alongside it and the
declare/act separation honoured by construction. It must be. A1.1 is
correspondingly weakened — nothing outside the platform's own journal bounds a
duplicate fill.

**A5.4 — are the 106 uncalled public methods dead? No.** See F6. The 106 was
never a deletion list: `hotpath.py` measures "no call site *in src/*", and
persists `called_by_tests` and `reached_by_name_literal` per item, which S-31
read past. The most dangerous entry is
`AlphaBudgetRiskWrapper.refresh_high_water_mark`, reached at
`orchestrator.py:1616` through `getattr(..., None)` behind a `callable()` guard
on the mark path: deleting it stops peak-equity tracking with no exception, no
log, and no parity movement in any run that never draws down. That is an Inv-11
fail-safe regression that the oracle cannot see.

**§F.8 — the horizon grid.** Resolved in a marked addendum to
`phase2_contracts.md`, on Phase 2's own §F template and its uncontested
recommendation of engine 2. Verified against current code rather than the
three-phase-old sheet: three holders keep *separately derived* views
(`horizon_scheduler.py:97`, `synchronizer.py:68-75`,
`aggregator.py:153-157`), all handed inputs by the composition root at
`bootstrap.py:1206` and `:1471`. The acceptance condition is stated as the
removal of those three views, not as hash stability — declaring the contract
moves no baseline, which is precisely why "the tests pass" would not evidence it.
Step placement is left to the operator: §K.5 ruled no new step is needed, and
which existing step declares it is not derivable from anything written down.
