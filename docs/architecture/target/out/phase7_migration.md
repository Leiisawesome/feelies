# PHASE 7 — Design thesis and migration plan

**Basis.** Phases 0–6 are treated as accepted inputs. Current-state claims carry
their original label; new material is `specified`. Numbers attributed to
`tools/arch/evidence/` were read from the evidence file, not estimated.

**Status vocabulary (arch guardrail).** `specified` / `implemented` /
`conformance-tested` / `open defect`.

**Deliverable state.** A and G are below. A was accepted before G was begun.
I (do-not-change list), J (assumption register) and K (model findings) are
**not started**.

---

## A. Design thesis

### A.1 The target architecture, in a paragraph

Twelve engines, each the sole writer of one class of fact, communicating only
through versioned contracts. They sit in five import tiers — declarations,
mechanism, engines, composition root, entry — with no upward import and no
engine importing another engine; the subscription graph that is the platform's
real integration graph stops being emergent and becomes a declared, hashed
wiring manifest. The kernel keeps dispatch, sequencing, the injected clock, the
state-machine framework, the exception taxonomy and the schema gate, and holds
no trading logic at all. Every payload is exactly one of a forecast, a fact, a
decision or an action, and never two of them at once: engine 4 forecasts, engine
6 reduces N forecasts to one desired portfolio, engine 8 permits or requires a
reduction, engine 9 turns permission into an executable plan, engine 10 is the
only place a mode difference or a wire exists, and engine 7 is the sole book of
record that all of them read and none of them recompute. Every read of another
engine's truth either returns that truth or fails — it never substitutes a
value. Every gate is a row in one registry rather than a branch in a function:
19 governance gates at load, 34 on the runtime spine, each emitting a verdict on
allow as well as on deny, because a record that exists only on denial cannot
prove that the veto is monotone. Governance, forensics and observability are
cold by construction, with exactly one hot exception, the kill-switch read.
Correctness is established by per-event conservation identities and a parity
surface, not by review; performance is established by a per-engine budget whose
breach is itself a recorded event, so that replay consumes the record rather
than re-measuring a wall clock. What makes the whole thing worth doing is stated
as a falsifiable property rather than a hope: the second, fifth and twentieth
alpha attach by manifest and configuration, with zero edits under `kernel/`,
`bus/`, `core/`, `risk/` or `execution/`.

### A.2 The three decisions it turns on

**1. Placement follows from the tier rule; it is not a judgment about size.**
The god orchestrator is dissolved not because 4 778 sloc and 11.1% of the
platform is too much (`VERIFIED`, computed this session from
`tools/arch/evidence/inventory.json`: 4 778 of 43 197 sloc over 196 modules; see
§A.4) but because a Tier-1 mechanism module performs Tier-2 reads on behalf of
nine engines — regime classification, three accounting methods, sizing and
escalation and emergency flatten, nine engine-9 methods, six engine-10
transitions
(`VERIFIED` across the twelve Phase 2 `GAP vs CURRENT` lines). Once the rule is
stated, every one of those methods has a determined destination: the engine
whose sheet claims it. Decomposition stops being a negotiation. The same rule
catches import cycle 2 — `core.inv12_stress` → `core.platform_config` →
`promotion.evidence` (`VERIFIED`, Phase 0 D0.1) — by *direction* rather than by
cycle detection, and Phase 3 is explicit that the forbidden-reads matrix is
unenforceable until this holds. If this decision is reversed, none of the twelve
contract sheets is checkable and Phases 2–3 reduce to documentation.

**2. One payload, one job — forecast, fact, decision and action are four kinds.**
The load-bearing instance is `OrderRequest`, which today carries both the
outbound order of hop 33 and the inbound de-risk command from four exit authors
in `risk/`, disambiguated only by a free-text `reason` field
(`src/feelies/core/events.py:290`; publishers at `src/feelies/risk/stop_exit.py:297`,
`src/feelies/risk/hazard_exit.py:253`, `src/feelies/risk/deferral_cap.py:378`, `src/feelies/risk/exit_composer.py:486`; re-entry at
`src/feelies/kernel/orchestrator.py:585`; `VERIFIED`). The target has engine 8
emit a *requirement* and engine 9 own all order construction including exits.
This removes a use rather than adding a type, collapses four independent
engine-7 reads with four staleness policies into one, and is the same cut that
makes arbitration a declared engine-6 construction policy instead of a kernel
default at `_select_bus_signal:1676`. It is the decision that re-draws engine
boundaries, and it is the one that re-pins the most parity baselines.

**3. Fail-closed is proved, not reviewed.** All four P0 gaps are one shape: a
read or a check that resolves to a permissive value instead of refusing —
`except Exception: current_positions[s] = 0.0` (G20,
`src/feelies/composition/engine.py:384-389`), `except KeyError: pass` skipping
the whole per-alpha budget block (G23, `src/feelies/alpha/risk_wrapper.py:186-192`),
an exactly-once set that means "since construction" (G03,
`src/feelies/execution/passive_limit_router.py:183`), and a latency measurement
compared to nothing (G43, `src/feelies/kernel/orchestrator.py:2128-2149`) — all
`VERIFIED` by direct read in Phase 5. The target answer is uniform and
mechanical: gates as data with verdict totality, conservation identities asserted
at every event rather than at run end, durability as a precondition of trading
(journal before wire; refuse on unprovable absence), and budget breach as a
recorded event. Phase 6's `xfail(strict=True)` ordering is what makes this a
decision rather than an intention — the test lands before the fix, authored by
someone who has not yet written it.

### A.3 The one thing most likely to be wrong

**That the platform can afford to emit everything the design requires it to
emit.** The proofs in decision 3 are built out of records: a verdict on every
gate evaluation including allow, a gate record per gate, a mark record per quote,
a divergence record on every check rather than only on breach, a decline record
per intent, a `LatencyBreach` event. Every one of those is an event on the hot
path, and the hot path is already the binding constraint. Measured: 136.2 µs per
quote, 42.2 µs per event, **4.2× the platform's own declared 10 µs/event target**
(`VERIFIED`, Phase 4 §2). The platform already publishes **17.07 events per
quote, of which 10.03 reach zero handlers — 58.7% of all publishes**
(`VERIFIED`, computed this session from `tools/arch/evidence/perf_census.json`,
n = 82 678 quotes), and Phase 4 attributes 12.8 µs/quote (9.4% of total cost) to
work no production consumer reads. Dividing the 7.2 µs/quote Phase 4 charges to
`StateTransition` by its measured 8.007 publishes per quote gives roughly
**0.9 µs per emission** (`INFERRED` — it conflates construction with dispatch),
which puts ten new per-tick records at about 9 µs/quote, or 28% of the entire
32 µs/quote target, added to a path already over it. The uncomfortable detail is
that `RiskVerdict` today publishes 43 times in a whole session to zero handlers
(`VERIFIED`, same evidence file); verdict totality makes it one of the densest
streams in the platform.

Two failure modes follow, and they are opposite. If emission is affordable, the
design is fine and Phase 4's budget simply has to be re-cut to include the new
records — which Phase 4 does not do, because it budgets the path as it exists.
If it is not, the observability requirements have to move to sampling, batching,
or an off-path channel, and every one of those weakens the proof: a sampled
verdict stream cannot establish monotonicity, and a batched record written after
the decision cannot be read by the decision. The thesis would then need a third
answer — records that are cheap by construction rather than events — and that is
a redesign of decision 3, not a tuning pass.

**What would falsify it.** A per-emission cost measurement against the *target*
record set rather than the current one: extend `tools/arch/perfmeasure.py` with a
mode that publishes the specified records at their specified rates and re-measures
µs/quote. If total cost with full record emission lands under the 32 µs/quote
target, this section is wrong and should be struck. **Blast radius if wrong:**
platform-wide, and it lands on the deliverable that has not been written yet —
it changes which steps in G are safe to ship, because a step that adds emission
before the budget exists is a step that degrades the constraint it is meant to
protect.

**Why this is the nomination and not the engine-6/8 unit question.** Whether
`SizedPositionIntent.target_positions` carries weights, notional or shares — and
therefore whether engine 6 has already performed engine 8's sizing on the
PORTFOLIO path (Phase 2 engine 8 overlap 3) — is the more likely thing to be
*factually* wrong, but it is settled by one field read and changes one boundary.
The emission-cost tension is internal to the target, is measured on both sides,
and cannot be resolved by reading the code.

---

### A.4 Disagreement recorded

Phase 1 §1 and Phase 3 §B state the orchestrator is **11.8%** of the platform.
The evidence file both cite gives **11.06%** — 4 778 sloc against a total of
43 197 over 196 modules, all under `src/feelies/`
(`tools/arch/evidence/inventory.json`, recomputed this session). The denominator
that produces 11.8% would be ≈40 492 sloc and is not present in the file. The
figure is immaterial to the argument — decision 1 turns on the tier violation,
not on the share — but it is not resolved here and it should not be repeated as
11.8% in Deliverable G without re-measuring. `open defect` in the Phase 1 / Phase
3 text, not in the code.

---

## G. Migration plan

### G.0 How to read this plan

**Ordering rule, and it is CORE §G.10's rule rather than mine.** §G.10 permits a
net complexity increase for exactly three things: conformance tests, contract
definitions, and P0 fixes. The waves below are those three categories in that
order, followed by the work that must be net-negative:

| Wave | Steps | §G.10 status | Touches `src/` |
|---|---|---|---|
| **A** — instrument | S-01…S-04 | conformance tests: net increase permitted | no |
| **B** — the four P0s | S-05…S-08 | P0 fixes: net increase permitted | yes, narrowly |
| **C** — substrate | S-09…S-18 | contract definitions: net increase permitted | yes |
| **D** — ownership | S-19…S-30 | **must be net-neutral or negative** | yes, widely |
| **E** — cost and retirement | S-31…S-34 | **must be net-negative** | yes |

P7 requires P0s and their detecting tests first, and `platform-wide` blast radius
last "unless a P0 forces it earlier." **The P0 rule holds without exception: all
four P0s are in wave B, none is `platform-wide`, and none is preceded by anything
except tests.** The one place a P0 pulls work forward is S-08, which needs a
durable journal — a new module in wave B rather than wave C.

**The platform-wide rule does not hold cleanly, and pretending otherwise would
misrepresent the plan.** Counted from the blocks: 3 steps are `local`, 22 are
`boundary`, and **9 are `platform-wide`** — S-11, S-12, S-21, S-23, S-26, S-30,
S-31, S-32, S-33, S-34 (10 if S-34 is counted, which it is). Six of those sit
before wave E. Each is placed early for a stated reason rather than by drift:

| Step | Why it precedes wave E |
|---|---|
| S-11 gate registry | 329 sites gain a registry binding and **no predicate changes**. Every later step states its failure behaviour against these rows, so deferring it means every wave-D step declares its gating in prose. |
| S-12 wiring manifest | Wave D moves code between engines; without a declared subscription graph, each move is a change to an artifact nobody has written down. |
| S-21 engine 7 | 36 direct store calls is the measure of how thoroughly the single-source invariant is held by coupling. S-05's P0 fix is only complete when substitution is structurally impossible, which is engine 7's read-only view. |
| S-23 `OrderRequest` | The one hot-path contract whose meaning changes. It re-pins four baselines and must precede S-24, which touches one of them. |
| S-26 engine 6 | Consolidating three reducers into one; deferring it leaves the platform's stated purpose — A > 1 — blocked. |
| S-30 §F.1 / §F.3 | 200 and 165 sites; the universe and session authorities every other engine reads. |

Wide reach with narrow behaviour change is the shape all six share: S-11 and S-21
touch hundreds of call sites and change no predicate, and their tables say so.
That is not the same risk as S-31, which re-pins the oracle.

### G.0.1 The rule that makes every PARITY IMPACT derivable

P7 requires each step to state parity impact and forbids "hashes will change"
without a reason. One measured fact makes this mechanical rather than a guess.

**`sequence` is the first field of nearly every parity hash helper.** `VERIFIED`
by reading: `tests/determinism/test_sensor_reading_replay.py:62`,
`tests/determinism/test_horizon_feature_snapshot_replay.py:62`, `tests/determinism/test_risk_verdict_replay.py:88`,
`tests/determinism/test_sized_intent_replay.py:181`, `tests/determinism/test_portfolio_order_replay.py:71`,
`tests/determinism/test_hazard_exit_replay.py:124`, and all four helpers in
`tests/determinism/test_orchestrator_replay.py:65,76,87,98`.
`tests/determinism/parity_manifest.py:182` labels the `state_transition` entry
"State-machine emission order **and sequence allocation**," and
`tests/determinism/test_legacy_sequence_isolation.py` exists solely to assert
that separate generators do not interact, its docstring stating "Sharing
counters would shift downstream replay sequences."

**Therefore:** a step holds all 26 baselines if and only if it changes neither
the number nor the order of draws from a shared `SequenceGenerator`, and changes
no hashed field value. `src/feelies/kernel/orchestrator.py` draws from
`self._seq` at **17 sites** and from `self._hazard_seq` at one (`:2519`)
(`VERIFIED`, counted this session). Adding or removing a publish that draws from
`self._seq` shifts every later event on that tick and breaks every baseline
downstream of it.

**The repo has already run this experiment and documented the result.**
`tests/determinism/test_orchestrator_replay.py:273-278` records what happened
when stop-exit authoring was moved off the kernel's signal family: the order
hash moved (`source_layer` RISK was SIGNAL, `strategy_id` `""` was
`__stop_exit__`, new content-derived order id), the position-update hash moved
"because the stop no longer draws from the kernel's signal family," and the
intent hash was **unchanged** "which is the point." S-23 is the same move for
the three remaining exit authors and should be expected to produce the same
three outcomes. This is the plan's single most useful precedent and it is why
S-23 is a step of its own rather than folded into S-22.

**The second parity fact, with the opposite sign.** Hash inputs are hand-written
field lists per helper, so **adding a field to an event cannot break parity**
(Phase 0 P-1, Phase 1 §6). S-09 adds `schema_version` to the envelope and all 26
baselines hold — which is also why the oracle cannot see schema growth, and why
S-09 must be followed by a declared re-pin if the field is ever hashed.

### G.0.2 What a branch point is, and the measured baseline

"Branch point" is otherwise unmeasurable, so this plan counts it over the three
populations that existing scanners enumerate, and says so:

| Population | Baseline | Source |
|---|---|---|
| Mode branches outside the composition root | **7** | `gapscan.json:mode_branches` — 27 total, 20 in `src/feelies/bootstrap.py` |
| Fail-quiet `except` handlers | **20** | `gatescan.json:n_fail_quiet_except_handlers` |
| Runtime gate call sites | **329** | `gatescan.json:family_totals`, 10 families |
| **Total branch points** | **356** | |

Module and public-symbol baselines: **196 modules, 551 public symbols, 43 197
sloc** under `src/feelies/` (`inventory.json`, re-read this session). Test files
are tracked separately in the ledger because §G.10 exempts conformance tests.

**Per-step NET DELTA figures are `INFERRED` projections, not measurements** — a
refactor that has not happened cannot be measured. The acceptance condition is
that `tools/arch/inventory.py`, `tools/arch/gapscan.py` and `tools/arch/gatescan.py` are re-run after
every step and the **actual** delta recorded beside the projection. A ledger of
projections that is never reconciled is the same defect as a latency metric
compared to nothing (G43).

### G.0.3 Three declared deviations from Phase 6's build order

Phase 6 §6 sequences its tests in five waves. This plan deviates in three places
and states each rather than quietly reordering.

1. **The P0-detecting tests move from Phase 6 wave 3 into this plan's wave B.**
   X4, X5, X6 (narrow clause), X7 (narrow clause), H2, X10 and X11 are specified
   in Phase 6 wave 3, behind the wave-2 engine-extraction tests. They do not
   depend on those tests, only on wave 0/1 fixtures. Holding a P0 fix behind an
   unrelated extraction test inverts P7's ordering rule. **X1 stays late** — it
   is a property over the *enumerable* degradation set, and that enumeration is
   an artifact S-11 and S-22 create, so X1 genuinely cannot precede them.
2. **Phase 6's per-test `BUILD ORDER` fields disagree with its own §6 table for
   four tests** — C4, C5 and R4 are wave 2 per their blocks and wave 3/4 per the
   table; S12 is wave 1 per its block and "wave 3, clause (a)" per the table
   (`VERIFIED`, `tools/arch/evidence/p7_index.json`, generated this session by
   `tools/arch/p7_index.py`). This plan follows the **§6 table** as the
   sequencing authority, because §6 is the section P6 designates for ordering,
   and records the disagreement here rather than resolving it silently.
3. **Eleven tests ship atomically with their artifact, not before it** — S1, S8,
   S9, S12, S13, S14, S15, R5, X8, X10, X11, per Phase 6 §0.3. Those steps are
   labelled `artifact + closure test, atomic` and are not claimed as
   "test first."

### G.0.4 Two gaps have no conformance test

`tools/arch/p7_index.py` cross-references all 45 gap IDs against every gap ID
named in all 50 Phase 6 test blocks. **G31 (§F.1 universe definition, 200 sites
across 11 packages) and G32 (§F.2 symbol identity, 3 sites, unimplemented) are
named by no test** (`VERIFIED`, `p7_index.json:unmapped`). Every other gap has
at least one. S-30 therefore has to author its own gates, and Phase 6's S1
registry closure test — which asserts every P0 and P1 gap has ≥ 1 test — **will
fail on these two** the moment it is written, in wave A, before any remediation.
That is the correct behaviour and it is the first thing S-01 will report.

### G.1 Wave A — instrument before touching anything

No step in this wave edits `src/feelies/`. Parity therefore cannot move, and that
is itself the assertion: if any baseline moves during wave A, the wave was not
what it claimed to be.

```
STEP:            S-01
CLOSES:          none directly — enables every later step
PROBLEM:         Phase 6's 50 tests need FIX-1, HARN-1, HARN-2 and a gap-to-test
                 registry before any of them can be written or trusted. CORE
                 §C.13 provenance: a remediation with no registry cannot show
                 which gap a change closed.
FILES:           tests/conformance/registry.py (new, the gap-to-test map)
                 tests/conformance/test_registry_closure.py (S1)
                 tests/conformance/fixtures/null_alpha/ (FIX-1)
                 tests/conformance/harness/engine_probe.py (HARN-1)
                 tests/conformance/harness/fault_injector.py (HARN-2)
                 tests/conformance/test_null_alpha_conservation.py (C1)
WHY THIS OWNER:  The registry belongs with the tests, not under tools/arch/,
                 because S1 asserts closure over it at collection time — the
                 same pattern as GATE_EVIDENCE_REQUIREMENTS'
                 module-level assertion (src/feelies/promotion/evidence.py:1720-1731).
REFACTOR PATH:   (1) registry as a literal dict, all 45 gap IDs, empty test
                 lists; (2) S1 asserting every P0/P1 gap has >= 1 test — it
                 fails on G31 and G32 immediately (G.0.4), so it lands
                 xfail(strict=True, reason="GAP G31, G32"); (3) FIX-1 as an
                 alpha manifest that emits nothing by construction; (4) HARN-1
                 and HARN-2; (5) C1 asserting position, realized and unrealized
                 P&L are identically zero at every event under FIX-1.
BLAST RADIUS:    local — tests/ only
VALIDATED BY:    S1, C1; full suite green; `uv run pytest -m "not functional and
                 not paper_rth"`; the parity oracle unchanged
PARITY IMPACT:   All 26 baselines hold, and the trade parity hash holds. No src
                 edit, no sequence draw changed. C1 introduces a new replay but
                 registers no baseline.
DELETES:         nothing. **CORE §G.10 justification:** conformance tests are one
                 of the three categories §G.10 exempts from net-negative. This
                 step is the exemption's central case.
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Test files +6.
ROLLBACK:        `git revert` the single commit. Nothing depends on it yet.
```

```
STEP:            S-02
CLOSES:          G08 (partially — puts the oracle under a random seed)
PROBLEM:         Four behaviours Phase 5 rates already-correct are the ones a
                 refactor breaks silently: whole-run parity, reduction-always-
                 permitted, passive/aggressive fill-eligibility parity, and
                 alpha purity. CORE §C.1, §C.5, §C.7. G08's residual is that
                 tests/determinism/ runs at PYTHONHASHSEED=random
                 (`.github/workflows/ci.yml:100-115`) while the parity oracle
                 runs pinned at "0" (`:138`) — the guard that matters most is
                 the one seed-order dependence cannot reach.
FILES:           .github/workflows/ci.yml (R1 — a job change, not a new test
                 file: Phase 6 specifies R1's path as the CI workflow itself)
                 tests/conformance/test_reduction_permitted.py (X3)
                 tests/execution/test_router_fill_timing_parity.py (extend, H1)
                 tests/conformance/test_alpha_purity.py (A1)
WHY THIS OWNER:  R1 extends the existing random-seed job rather than adding a
                 new one, per Phase 6 §3's promotion rule; H1 extends the 589
                 lines already pinning the passive path rather than restating
                 them.
REFACTOR PATH:   (1) add the parity oracle to the existing random-seed job with
                 FEELIES_REQUIRE_BASELINE_CACHE=1 — the oracle must not be
                 able to skip; (2) X3 as a targeted adversarial suite, one case
                 per declared degraded state, asserting a flattening order is
                 permitted; (3) H1's parity half — the aggressive path on the
                 same tape, one eligibility rule; (4) A1.
BLAST RADIUS:    local — tests/ and CI config
VALIDATED BY:    R1, X3, H1, A1 all green; and each of the four proved by the
                 AGENTS.md mutation procedure, since all four pass today.
                 H1's mutation: change the exchange-time comparison at
                 `src/feelies/execution/passive_limit_router.py:527` to a
                 wall-clock read; restore; prove the restore.
PARITY IMPACT:   All 26 hold. R1 runs the *existing* hashes under a random seed:
                 if a hash moves, that is G08 firing for real and the step has
                 found a live defect rather than broken one.
DELETES:         the `PYTHONHASHSEED: "0"` pin on the oracle job as the only
                 seed under which the oracle is ever run. The pinned job stays;
                 it stops being the sole coverage.
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Test files +3, CI job steps +1.
ROLLBACK:        revert the commit; the CI job returns to its current form.
                 Independent of S-01 except that A1 consumes FIX-1.
```

```
STEP:            S-03
CLOSES:          none outright — arms the detectors for G01, G04, G10, G12, G21,
                 G22, G25, G26, G36, G39, G41, G42, G44, G45
PROBLEM:         Fourteen of Phase 6's tests are assertions over scans that
                 already run and already produce the right numbers; the numbers
                 are in evidence files nothing enforces. CORE §H measure-don't-
                 estimate is satisfied; CORE §G's "runtime enforced boundaries"
                 is not.
FILES:           tests/conformance/ — S3, S5, S6, S7, S10, S11, S16, S17,
                 R2, R7, R8, C2, C3
                 tests/acceptance/test_no_walltime_outside_clock.py (extend, S4)
                 promoting tools/arch/{measure,clockscan,hotpath,gatescan,
                 gapscan,contracts,substrate,coupling}.py
WHY THIS OWNER:  Phase 6 §3 lists 8 of these as promotions of an existing
                 script. Re-implementing the scans in tests would create two
                 measurements of one fact — the recompute-as-redundancy
                 anti-pattern the review is supposed to remove.
REFACTOR PATH:   Each test imports the scanner and asserts on its output. Every
                 test that fails today lands as
                 xfail(strict=True, reason="GAP Gnn"). S4 additionally replaces
                 the whole-file allowlist entry for
                 `src/feelies/kernel/orchestrator.py` — which today exempts
                 5,480 lines — with call-granular entries.
BLAST RADIUS:    local — tests/ only
VALIDATED BY:    the 14 tests; S1 then passes on every gap they name; existing
                 suite green
PARITY IMPACT:   All 26 hold. No src edit.
DELETES:         the whole-file clock allowlist entry for the orchestrator; the
                 implicit duplication between each scanner's evidence file and
                 the reviewer who reads it.
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Test files +13, allowlist entries -1 file +12 call sites.
ROLLBACK:        revert. Each test is independently revertible; they share no
                 fixture.
```

```
STEP:            S-04
CLOSES:          G16, and arms the detector for G40 and every wave-D step
PROBLEM:         `feelies.core.inv12_stress` -> `feelies.core.platform_config`
                 -> `feelies.promotion.evidence` puts the governance package in
                 the import closure of every tick-path module. Inv-8 layer
                 separation. Under the tier rule this is a Tier 0 -> Tier 2
                 edge, illegal whether or not it closes a loop — and Phase 3
                 states the forbidden-reads matrix is unenforceable until the
                 tier rule holds.
FILES:           pyproject.toml (add import-linter to the dev extra; [tool.importlinter] contracts -- layers over tiers 0-4, independence over the twelve engine module sets)
                 uv.lock (relocked by the dev-extra addition)
                 .github/workflows/ci.yml
                 tests/conformance/test_import_contracts.py (S2)
                 tools/arch/importgraph.py (new -- grimp evidence, per Phase 3)
WHY THIS OWNER:  Phase 3 §3.1 already made this call and named both tools. The
                 root cause is placement — a stress/validation module sits in
                 the contracts tier — so the fix is a move, not an import
                 rearrangement.
REFACTOR PATH:   (1) add import-linter with the contract expressed but
                 **allowed to fail**, and S2 as xfail(strict=True,
                 reason="GAP G16"); (2) in the same step, move
                 `inv12_stress` out of `core/` and drop the xfail. If the move
                 turns out to require breaking a public import path, split:
                 ship the contract xfailed, move in S-04b.
BLAST RADIUS:    boundary — one module moves; its importers change import path
VALIDATED BY:    S2 lands as xfail(strict=True); `uv run mypy src/feelies` clean;
                 full suite; `tools/arch/importgraph.py` reports the G16 chain
                 (coupling.py does not report cycles)
PARITY IMPACT:   All 26 hold. A module move changes no sequence draw and no
                 hashed field. If a baseline moves, the "move" changed
                 behaviour and the step is wrong.
DELETES:         nothing. This step arms the detector; G16 and G40 remain open
                 under strict xfail. CI runs the contract with
                 continue-on-error: true until they close.
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Config files +2, test files +1, tools +1.
ROLLBACK:        revert; the import path reverts with it. import-linter becomes
                 an unused dev dependency until re-landed.
```

```
STEP:            S-04b
CLOSES:          G16 (the Tier 0 -> Tier 2 edge; S-04 armed the detector only)
PROBLEM:         core/platform_config.py:1199 lazily imports
                 promotion.evidence.parse_gate_thresholds_overrides so tier 0
                 can validate governance threshold semantics, putting the
                 governance package in the import closure of every tick-path
                 module. Inv-8 layer separation. The comment at :1196 shows the
                 cycle was known and deferred to call time rather than cut.
                 The parse is also redundant: apply_gate_thresholds_overrides
                 re-parses at evidence.py:1567, and bootstrap.py:684 already
                 calls it. The parser cannot move to core -- its whitelist is
                 derived from GateThresholds (evidence.py:383, 1493) by
                 introspection, with a sync assertion at :1761. Root cause is
                 that tier 0 parses at all, not where the parser lives.
WHY THIS OWNER:  Governance owns the semantics of its own thresholds. The
                 contracts tier owns config structure. platform_config keeps the
                 structural checks it can make without governance types and
                 stops making the ones it cannot.
REFACTOR PATH:   (1) platform_config._parse_gate_thresholds_block keeps the
                 structural checks (None, non-mapping, empty) and returns the
                 raw block; delete the lazy import and comment at :1196-1200.
                 (2) bootstrap._build_platform_gate_thresholds wraps the
                 resulting ValueError as ConfigurationError carrying the config
                 source path, so a malformed block still fails eagerly at
                 startup with attribution. (3) move the semantic assertions in
                 tests/core/test_platform_config_gate_thresholds.py (lines
                 84-89, 103, 128-156) to bootstrap level. (4) drop S2's G16
                 xfail. G40 keeps its xfail -- that is the separate
                 kernel -> engines violation and is not closed here.
FILES:           src/feelies/core/platform_config.py
                 src/feelies/bootstrap.py
                 tests/core/test_platform_config_gate_thresholds.py
                 tests/bootstrap/test_gate_thresholds_wiring.py
                 tests/conformance/test_import_contracts.py
BLAST RADIUS:    boundary -- one lazy import is cut; the config object's
                 gate_thresholds_overrides field changes from normalized to raw
VALIDATED BY:    S2's G16 xfail drops and the layers contract reports KEPT for
                 the core -> promotion edge; tools/arch/importgraph.py reports
                 the G16 chain gone; a malformed gate_thresholds still fails at
                 startup with the config path in the message; mypy clean; full
                 suite
PARITY IMPACT:   hold. VERIFIED: platform.yaml, configs/paper_smoke_rth.yaml and
                 configs/paper_run.yaml all set `gate_thresholds: {}`, and the
                 empty case returns at :1192 before the lazy import is reached,
                 so the parser never executes on any replayed tape and no
                 int->float normalization occurs. No test YAML sets the block;
                 the only determinism-adjacent reference
                 (tests/acceptance/test_bt13_portfolio_research_only.py:54)
                 default-constructs GateThresholds and never loads a
                 PlatformConfig. EXPIRES IF: any config sets a non-empty block,
                 since storing raw would change the config snapshot's
                 serialized content.
DELETES:         the Tier 0 -> Tier 2 edge; the lazy import and its comment at
                 core/platform_config.py:1196-1200; one redundant parse of the
                 same block
NET DELTA:       src modules 0, public symbols 0, branch points -1
ROLLBACK:        git revert; the import path and the normalization revert
                 together. S2's G16 xfail must be restored with it or the test
                 fails strict.
```

### G.2 Wave B — the four P0s

Each step carries its own detecting test, moved forward from Phase 6 wave 3 per
G.0.3. Every step in this wave is `boundary` or narrower except S-08.

```
STEP:            S-05
CLOSES:          G20 (P0)
PROBLEM:         `except Exception: current_positions[s] = 0.0` reports a failed
                 position lookup to the optimizer as **flat**, so the optimizer
                 computes target-minus-zero and sizes a fresh entry on top of an
                 existing position — approximately doubling it. Marked
                 `# pragma: no cover - defensive`, so untested by construction,
                 and it emits nothing. **Inv-11 fail-safe default**, and CORE
                 §J.5 silent degradation.
FILES:           src/feelies/composition/engine.py:384-389
                 tests/conformance/test_position_read_fails_closed.py (X5, new)
                 tests/conformance/test_exception_containment.py (X7, narrow
                 clause: this handler only. The file already exists — S-03
                 created it for S6 — so this step adds a case, not a file.)
WHY THIS OWNER:  Phase 2 engine 6 overlap 3 settles that the *read* is
                 legitimate — turnover control cannot be computed without the
                 book — and that the defect is the **substitution on failure**.
                 Engine 6 owns the behaviour on a failed read; engine 7 owns
                 making substitution impossible, which is S-21's read-only view.
                 This step does the half that does not wait for S-21.
REFACTOR PATH:   (1) X5 first, injecting a lookup failure and asserting
                 construction halts for that boundary, emits, and produces no
                 target — xfail(strict=True, reason="GAP G20"); (2) replace the
                 handler with: catch the specific lookup failure, emit a
                 barrier/completeness notification, abandon the boundary; (3)
                 remove the `# pragma: no cover`; (4) drop the xfail.
BLAST RADIUS:    boundary — PORTFOLIO path only, and only when
                 `_position_lookup` is wired
VALIDATED BY:    X5, X7 (narrow), C1, the four engine-6 baselines,
                 the parity oracle
PARITY IMPACT:   All 26 expected to hold — **and this is the step's second
                 finding.** The four engine-6 baselines
                 (`level3_sized_intent_decay_off`, `level3_sized_intent_decay_on`,
                 `cross_sectional_context`, `level4_portfolio_order`) exercise
                 `CompositionEngine`. If any moves, the handler was firing
                 inside a baseline run and nobody knew — which **resolves
                 assumption A5.3** ("G20 has never fired in any recorded run",
                 unresolvable today because the handler logs nothing). The
                 parity check is the counter A5.3 asked for.
DELETES:         one fail-quiet handler (20 -> 19); one `# pragma: no cover`;
                 the silent-flat path
NET DELTA:       src modules 0, public symbols 0, branch points **-1**
                 (fail-quiet handler removed; the replacement raises/emits
                 rather than branching to a value).
                 Test files +2.
ROLLBACK:        revert; restores the handler and re-xfails X5. Independent of
                 S-06 through S-08.
```
```
STEP:            S-05a
CLOSES:          new -- fail-safe inversions in BasicRiskEngine's shared
                 exposure/drawdown gate (S-02 ledger finding 1, extended)
PROBLEM:         Two defects in _check_exposure_and_drawdown (basic_risk.py:637).
                 (1) The gross cap at :673 has no reduction exemption, unlike
                 the per-symbol cap at :191 and the buying-power gate at :520
                 which both cite Inv-11. Gate 1 computes `signal_reduces` at
                 :184 and discards it before calling the shared gate, which
                 always sees positions.total_exposure(). A flatten signal on an
                 over-cap book is rejected pre-sizing.
                 (2) The gross reject at :673 returns before the HWM update at
                 :686 and the drawdown check at :688, so an event breaching both
                 yields REJECT, never FORCE_FLATTEN. VERIFIED reachable:
                 500 AAPL at 100 marked to 80 gives equity 89995, exposure
                 40000, cap 17999, drawdown 10.005% vs a 5% limit -- verdict is
                 "gross exposure limit". The drawdown rail is unreachable in the
                 state it exists for, and the HWM goes stale while over-cap.
WHY THIS OWNER:  Phase 2 engine 8 owns the veto and it is monotone. Both defects
                 make it non-monotone: (1) blocks a reduction, (2) suppresses a
                 mandated de-risk.
REFACTOR PATH:   (0) X3 REPAIR FIRST. tests/conformance/test_reduction_permitted.py:81
                 sets max_gross_exposure_pct: 100.0, a cap that never binds, so
                 the test cannot exercise this gate. Set a binding cap, prove
                 the repaired X3 FAILS, and only then implement.
                 (1) thread the reduction signal into the shared gate; exempt a
                 non-increasing request from the gross cap. The general predicate
                 is "prospective exposure does not increase" -- gate 2 already
                 passes exposure_override for this; gate 1 has signal_reduces.
                 (2) evaluate the HWM update and drawdown check before the gross
                 cap, so FORCE_FLATTEN wins over REJECT on a doubly-breached
                 event.
FILES:           src/feelies/risk/basic_risk.py
                 tests/conformance/test_reduction_permitted.py
                 tests/risk/test_basic_risk.py
BLAST RADIUS:    platform-wide -- the shared gate serves gate 1 and gate 2, and
                 clause 2 changes a verdict class on the de-risking path
VALIDATED BY:    repaired X3 with a binding cap, failing before and passing
                 after; a new case asserting FORCE_FLATTEN on the doubly-breached
                 scenario above; the risk verdict replay baseline; full suite
PARITY IMPACT:   hold across all 62 constants. VERIFIED structurally, not
                 inferred from passing baselines: _check_exposure_and_drawdown
                 is reached by exactly one determinism tape.
                 - test_risk_verdict_replay.py: all 4 verdicts enumerated, hash
                   b388a2c5... reproduced exactly. Clause 1 -- verdict 2 (GOOG,
                   gross 27000.00 >= 19999.700) is an entry on a symbol with no
                   position, so the exemption does not apply. Clause 2 -- no
                   event breaches both rails: verdict 2 is gross-only, verdict 3
                   is drawdown-only (equity 83000.50, exposure 10001.00, cap
                   16600.10).
                 - test_forced_exit_attribution_replay.py: stubs check_signal /
                   check_order at :193-196; the real engine is never built.
                 - test_decoupled_safety_replay.py: no BasicRiskEngine, no
                   max_gross_exposure_pct, no account_equity; flatten orders
                   originate in the safety/decoupling path.
                 - test_state_transition_replay.py: ":122 check_order_pass" is a
                   state label, not a call.
                 EXPIRES IF: any tape constructs a BasicRiskEngine, or adds a
                 reducing signal meeting a breached gross cap, or an event
                 breaching gross and drawdown together.
DELETES:         two fail-safe inversions; one unreachable code path
NET DELTA:       src modules 0, public symbols 0, branch points +1 (the
                 exemption) -1 (no new branch for reordering) = 0
ROLLBACK:        revert; both clauses revert together. X3's binding cap reverts
                 with it, restoring the vacuous configuration.
```
```
STEP:            S-06
CLOSES:          G23 (P0)
PROBLEM:         `try: self._registry.get(strategy_id) / except KeyError: pass`
                 skips the **entire** per-alpha budget block — position limit,
                 drawdown and exposure checks — for any `strategy_id` the
                 registry does not know. The comment states the intent
                 ("Synthetic and net strategies use aggregate risk checks
                 only") but the *condition* is registry absence, not
                 synthetic-ness, so a config typo or a failed registration
                 takes the same path. **Inv-11**: unknown state resolving to
                 *fewer* constraints.
                 Two committed tests assert the fall-through as correct:
                 TestCheckOrderDelegatesToInner::test_unknown_strategy_passes_through
                 and TestCheckSizedIntent::test_unregistered_strategy_id_falls_through,
                 both from e3281a1 (2026-04-11), a bug-fix pass that pinned
                 observed behaviour rather than a design. The class docstring
                 asserts only that check_order still delegates to the inner
                 engine for aggregate checks, which this step preserves. The
                 platform already has a sanctioned bypass for ids that
                 legitimately skip per-alpha budgets -- the `__` prefix, with an
                 explicit branch. A second, silent bypass for any unregistered
                 id is a hole, not a design. Both tests are rewritten here to
                 assert the new contract.                 
FILES:           src/feelies/alpha/risk_wrapper.py:186-192
                 tests/conformance/test_per_alpha_budget.py (X4)
                 tests/conformance/test_pathological_refusal.py (X6, narrow)
                 tests/conformance/fixtures/pathological/ (FIX-3, first case only —
                 the unregistered-id input. The other six input classes need the
                 gate registry to bind a *named* gate, so they land in S-11.)
                 tests/alpha/test_risk_wrapper.py (overturns two tests that pin
                 the G23 fail-open as intended behaviour)
WHY THIS OWNER:  Phase 2 engine 5 standing check 3 settles it: engine 5 *sets*
                 per-alpha budgets, engine 8 *enforces* them. That the wrapper
                 currently lives in `alpha/` is a placement problem (S-22's);
                 that it fails open is engine 8's, and is this step's.
REFACTOR PATH:   (1) X4 first — every `strategy_id` reaching the wrapper
                 resolves to a budget or to zero-with-an-alert; xfail(strict);
                 (2) make the synthetic branch **explicit**: test the `__`
                 prefix, not registry absence; (3) unknown non-synthetic id ->
                 zero budget plus an emitted alert; (4) drop the xfail.
BLAST RADIUS:    boundary — the risk wrapper; every order carrying a
                 `strategy_id`
VALIDATED BY:    X4, X6 (narrow), the `risk_verdict` baseline, the parity oracle
PARITY IMPACT:   All 26 expected to hold **provided step (2) lands before step
                 (3)** — making the synthetic path explicit is what preserves
                 today's deliberate aggregate-only behaviour for `__`-prefixed
                 strategies. If `risk_verdict` or
                 `decoupled_risk_flatten_order` moves, a non-synthetic
                 unregistered id was reaching the wrapper in a baseline run,
                 which is the defect and not a re-pin.
DELETES:         one fail-quiet handler (19 -> 18); the registry-absence branch; 
                 two assertions pinning the fail-open as correct
NET DELTA:       src modules 0, public symbols 0, branch points **-1 +1 = 0**
                 (fail-quiet handler removed, explicit synthetic test added —
                 net zero, and the new branch is enumerable where the old was
                 not).
                 Test files +2.
ROLLBACK:        revert; independent of every other step.
```
```
STEP:            S-06a
CLOSES:          new -- S-06 ledger finding (registry alpha_id validation)
PROBLEM:         AlphaRegistry.register (registry.py:102) checks for a duplicate
                 alpha_id at :114, runs alpha.validate() at :117, and enforces
                 threshold floors at :122 -- but never applies _ALPHA_ID_RE. The
                 YAML path is closed: loader.py:128 defines
                 ^[a-z][a-z0-9_]*$ and applies it at :866, and alphas/SCHEMA.md
                 states the same rule, so a leading underscore raises
                 AlphaLoadError. A module registered programmatically with a
                 `__` prefix, however, counts as registered and takes the
                 synthetic bypass in the risk wrapper, skipping per-alpha
                 budgets. After S-06 closed the unregistered-id fall-through,
                 this is the remaining registration route to an unbudgeted
                 order. Fifth instance of one shape: a check enforced at one
                 entry point and absent at another.

                 The bypass has two doors and this step closes the registration
                 one. VERIFIED: bootstrap.py:747-754 registers only modules
                 returned by loader.load, so _ALPHA_ID_RE has already run on
                 every id reaching register in production -- the added check is
                 inert at runtime and guards the programmatic path. The
                 order-side door is closed by convention rather than by code:
                 the only `__`-prefixed strategy_id in src/ is
                 orchestrator.py:4006 "__working_exit_fallback__", kernel-
                 authored on an exit path, with no alpha-reachable route to set
                 one. `__synthetic_net__` is never a registered alpha_id -- it
                 appears only as an order strategy_id -- so a blanket regex
                 needs no allowance.
WHY THIS OWNER:  Engine 5 owns alpha identity. The loader validates ids arriving
                 by YAML; the registry is the second door and must apply the
                 same rule. The regex currently lives in loader.py, a parsing
                 module, so this step moves it to registry.py, which owns
                 identity, and the loader imports it from there.
REFACTOR PATH:   (1) a conformance case registering a `__`-prefixed module
                 programmatically and asserting AlphaRegistryError, that the
                 rejection names the id rule, and that no registry state was
                 mutated; plus a control registering a valid id that still
                 succeeds -- prove the case FAILS first, and prove the failure
                 is the registry accepting the id rather than a malformed stub;
                 (2) move _ALPHA_ID_RE to registry.py, have loader.py import it,
                 and apply it in register() before the duplicate check at :114,
                 raising AlphaRegistryError like the adjacent guards; (3)
                 confirm the wrapper's `__` branch remains reachable only by
                 platform construction, not by registration.
FILES:           src/feelies/alpha/registry.py
                 src/feelies/alpha/loader.py
                 tests/conformance/test_per_alpha_budget.py
                 tests/alpha/test_registry_per_alpha_thresholds.py
BLAST RADIUS:    boundary -- one guard added at one call site; the regex moves
                 between two engine-5 modules and the loader's behaviour is
                 unchanged
VALIDATED BY:    the new conformance case failing before and passing after; the
                 valid-id control passing throughout; the loader's existing
                 id-rejection tests still passing after the move; mypy clean;
                 full suite; the parity oracle
PARITY IMPACT:   hold, structurally. bootstrap.py:754 is the only production
                 caller of AlphaRegistry.register, and every module reaching it
                 came through loader.load, where the regex already ran -- so the
                 added check cannot alter any tape. Confirm by reading that no
                 determinism tape registers a module by another route; do not
                 infer hold from a green baseline, which is consistent with the
                 guard never firing. EXPIRES IF: any caller registers a module
                 built other than by loader.load.
DELETES:         the last registration path to an unbudgeted order; the
                 duplicated ownership of the alpha-id rule between a parsing
                 module and an identity module
NET DELTA:       src modules 0, public symbols 0 (the regex is module-private in
                 both locations), branch points +1
ROLLBACK:        git revert; the regex returns to loader.py and the registry
                 accepts unvalidated ids again. Independent of S-07 onward.
```

```
STEP:            S-07
CLOSES:          G43 (P0), G41 (partially — creates the budget G41 is measured
                 against)
PROBLEM:         There is no budget in the code. `_tick_timings` is written at
                 three sites, read once at
                 `src/feelies/kernel/orchestrator.py:2128`, published as
                 `MetricEvent`s, and **never compared to anything** (`VERIFIED`
                 by reading `:2126-2153` this session). So the measured 4.2x
                 overrun is invisible to the running system in every mode, and
                 Inv-11's requirement that stress resolve toward reduced
                 exposure has no implementation on the latency axis.
                 S4 at tests/acceptance/test_no_walltime_outside_clock.py
                 allowlists ten perf_counter_ns sites in orchestrator.py by line
                 number, so it fails on any insertion above them regardless of
                 wall-clock behaviour. This step adds no new read -- the count
                 stays at 10 -- but all ten shift (1524->1533, 1633->1642,
                 1635->1644, 1675->1684, 1677->1686, 1771->1780, 1773->1782,
                 2104->2113, 3940->3958, 3950->3968). Three of them (1524, 2104,
                 3940) are named in the allowlist comment at :38-41 as G01's
                 residual, closed by S-32, so their line numbers are a
                 cross-step reference: they are re-keyed here by enclosing
                 symbol -- _process_tick_inner, _finalize_tick,
                 _drain_async_fills -- which are distinct and unambiguous. The
                 remaining seven are retargeted in place; fully de-line-pinning
                 S4 is out of scope.                 
FILES:           src/feelies/core/events.py (LatencyBreach, new)
                 src/feelies/monitoring/ (budget predicate + breach record)
                 src/feelies/core/platform_config.py (per-engine budget table)
                 src/feelies/kernel/orchestrator.py:2126-2153 (comparison site)
                 tests/conformance/test_latency_budget.py (X10)
                 tests/acceptance/test_no_walltime_outside_clock.py (S4's ten
                 orchestrator entries are line-pinned and shift on any insertion
                 above them; retarget all ten, and re-key the three G01
                 residuals by enclosing symbol so S-32's reference is stable)                 
WHY THIS OWNER:  Phase 2 splits §F.6: engine 11 owns the response to a budget
                 breach, engine 1 owns ingress shedding. The measurement stays
                 where it is; only the comparison and the response are new.
REFACTOR PATH:   **Artifact + closure test, atomic** (Phase 6 §0.3). (1) the
                 per-engine budget as config data, **each entry declaring its
                 statistic and window**: p99 over a declared rolling event count,
                 never the mean — Phase 4 §6 rules for p99 and measures a 3.9x
                 mean-to-p99 ratio, so a mean-based budget and a p99 one breach
                 in different places and "over budget" is meaningless without the
                 statistic named. X10 asserts closure: every hot-path engine has
                 a budget entry carrying both. (2) the comparison, live only, and
                 **fail-closed when the statistic cannot be computed** — fewer
                 than a window of samples reads as `never-seen`, never as
                 `within budget` (§K.1.2: this predicate is a safety-critical
                 metric feeding a fail-closed control, so an absent measurement
                 must not read as compliance). (3) `LatencyBreach` appended to
                 the event log, carrying the statistic, window and observed value
                 so the record is interpretable without the config that produced
                 it. (4) the response: kill-switch escalation on sustained
                 breach, reduce-only. (5) **replay reads the recorded breach and
                 never re-measures** — Phase 4 §6's resolution, and the only
                 shape under which a wall-clock-derived decision can satisfy
                 Inv-5.
                 Steps (1) and (2) close A7.13, which recorded that this block
                 named neither statistic nor window.
BLAST RADIUS:    boundary — one new event type, one comparison, one response
                 path. Not platform-wide, because the measurement already
                 exists.
VALIDATED BY:    X10; R1 under a random seed; the parity oracle; and a
                 deliberate slow-engine injection through HARN-2 asserting the
                 breach fires, the record is written, and replay of that log
                 reproduces the same response without re-measuring
PARITY IMPACT:   hold — all 26 baselines, conditional on (a) and (b) below.
                 **All 26 hold, and the reason is a design constraint, not an
                 accident.** Two things must be true. (a) `LatencyBreach` must
                 not draw from `self._seq` — the always-on timers at
                 `:2127-2141` are already routed with `sequence=0` precisely so
                 they "cannot shift kernel event IDs" (the comment at `:2126`
                 says so), and the breach record follows that route. If it
                 instead draws `self._seq.next()`, every baseline downstream on
                 that tick breaks. (b) The baseline replays contain no breach
                 events, so the no-breach branch is taken and output is
                 identical. Backtest has no wall-clock deadline (Phase 5 G43),
                 so no breach is generated during replay.
DELETES:         the unread-metric path for `_tick_timings` becomes a compared
                 input on PAPER. The MetricEvent publish path REMAINS --
                 removing the seq.next() publishes on signal_evaluate_ns /
                 risk_check_ns would shift kernel event IDs. Supplemented, not
                 removed. Also deletes the line-number coupling of G01's three
                 residuals.
NET DELTA:       src modules +1, public symbols +2 (LatencyBreach, the budget
                 table), branch points **+2** (the comparison and the
                 escalation) — both enumerable, both gate-registry entries once
                 S-11 lands.
                 Test files +1.
ROLLBACK:        revert. The comparison and the event disappear; `_tick_timings`
                 returns to being published and unread. No state migration,
                 because the breach record is append-only and replay-read.
```

```
STEP:            S-08
CLOSES:          G03 (P0)
PROBLEM:         `derive_order_id` is correctly a pure function of provenance,
                 so a restart re-derives the same `order_id` -- and nothing
                 durable records which IDs were **submitted**.
                 `self._submitted_order_ids: set[str] = set()`
                 (src/feelies/execution/passive_limit_router.py:183, read this
                 session; its comment says "ever submitted" and its lifetime is
                 the object's), `_next_valid_id` starts `None` each process, so
                 exactly-once submission holds only within one process.
WHY THIS OWNER:  Phase 2 engine 10 owns exactly-once submission across restart
                 and reconnect; engine 7 owns book durability. Both resolve the
                 same way -- journal before wire, refuse on unprovable absence
                 -- which makes durability a precondition of trading rather than
                 a feature of it.
REFACTOR PATH:   **Artifact + closure test, atomic.**
                 (1) H2 and X11 first, xfail(strict, "GAP G03").
                 (2) the durable journal as an append-only file with a
                 content-addressed record per submission. DURABILITY MODE IS
                 fsync-per-record: a page-cached append survives `kill -9` but
                 not power loss, and the requirement is power-loss safety.
                 (3) write **before** the wire, never after -- Phase 2 engine
                 10's ON EXCEPTION clause is explicit that a raise between wire
                 and journal is the one case with no safe containment.
                 (4) refuse to submit any ID not provably absent from the
                 journal.
                 (5) THE REJECT ASYMMETRY IS DELIBERATE. The in-memory set at
                 :183 is not append-only: `append_reject_ack`
                 (passive_limit_router.py:777-786) removes an id on reject
                 unless `release_submitted_id=False`. The journal does not
                 release. So the journal records submission ATTEMPTS, and
                 restart recovery must distinguish "journaled and rejected"
                 (safe to re-derive) from "journaled, outcome unknown" (refuse).
                 Recording only post-wire confirmations would contradict (3) and
                 is not the resolution.
FILES:           src/feelies/storage/ (durable submitted-order journal, new)
                 src/feelies/execution/passive_limit_router.py:183
                 src/feelies/broker/ib/connection.py:353-364
                 src/feelies/bootstrap.py:358 (wire the durable journal)
                 src/feelies/core/platform_config.py (journal latency budget entry)
                 tests/conformance/test_order_idempotency.py (H2)
                 tests/conformance/test_reconciliation.py (X11)
                 tests/broker/ib/test_next_valid_id_high_water.py (new,
                 gateway-free)
BLAST RADIUS:    boundary -- live and paper only. Backtest is single-process and
                 unaffected, which is why this is shippable ahead of wave C.
VALIDATED BY:    H2 (kill mid-submission, restart, assert no duplicate reaches
                 the broker) WITH AN EXPLICIT fsync-MODE ASSERTION -- a
                 page-cached write survives `kill -9` and would pass the restart
                 test without meeting the durability requirement, so the restart
                 alone does not discriminate between the three modes;
                 X11; the parity oracle; `market_fill_acks` and `halt_ack`;
                 a rejected-then-re-derived case proving (5) -- an id journaled
                 and rejected must be re-submittable, not permanently refused;
                 and a REPLAY of a session that used the durable journal,
                 asserting the same refusal decisions, since the durable path is
                 otherwise exercised only by H2 and never by the oracle; 
                 a gateway-free test over nextValidId's
                 high-water logic -- empty journal, persisted below incoming,
                 persisted above incoming, and a simulated reconnect that must
                 not regress -- since all 14 tests in
                 tests/broker/ib/test_ib_functional.py skip without a reachable
                 gateway and the reconnect invariant at connection.py:371-373 is
                 otherwise unasserted.
PARITY IMPACT:   All 26 hold. The journal is a side-effect store, draws no
                 sequence, and adds no hashed field. Backtest keeps
                 `InMemoryTradeJournal`, so the oracle's code path is unchanged
                 -- **which is also this step's weakness**: the durable path is
                 exercised only by H2, which is why VALIDATED BY adds a replay
                 of a journal-backed session.
                 LATENCY: submission is on the tick-critical path
                 (orchestrator.py:1407 and :1462 call
                 `order_router.submit(order)` inside the walk that records
                 `risk_check_ns` at :1782), and a portfolio batch writes one
                 record per leg, not one per tick. An fsync costs 1-10 ms
                 against S-07's 3 ms p99 budgets, so the write must either carry
                 its own `ENGINE_LATENCY_BUDGETS` entry with a stated statistic
                 and window, or be moved off-tick with the ordering guarantee in
                 (3) preserved by another mechanism. State which, and state what
                 a breach does -- S-07 wired breach to kill-switch escalation.
DELETES:         the in-process-only exactly-once guarantee; the claim in
                 src/feelies/execution/passive_limit_router.py:183's comment
                 that the set holds IDs "ever submitted", which becomes true
                 rather than aspirational.
NET DELTA:       src modules +1, public symbols +2, branch points **+2** (the
                 refusal, and the rejected-vs-unknown discrimination in (5)).
                 sec. G.10: P0 fix, net increase permitted. Test files +2.
ROLLBACK:        revert, and delete the journal file -- it is append-only and
                 nothing else reads it. The router falls back to the in-memory
                 set. **Do not roll back while a live session is mid-flight**:
                 the journal is the only record of what was sent.
```

---

### G.3 Wave C — substrate contracts

Every step here is a **contract definition**, which §G.10 exempts from
net-negative. Ten of the eleven artifact-atomic tests from Phase 6 §0.3 land in
this wave. The wave's purpose is that wave D's ownership moves have something to
be checked against; shipping wave D first would move code with no contract to
move it to.

```
STEP:            S-09
CLOSES:          G07
PROBLEM:         2 of 21 event classes carry a version field. Every hot-path
                 event is unversioned, so no consumer can detect a producer
                 shape change. CORE sec. C.11 schema evolution never breaks
                 replay; CORE sec. F.7, resolved to the Kernel in Phase 2.
WHY THIS OWNER:  Phase 2 assigns sec. F.7 to the Kernel and puts
                 `schema_version` on the base `Event` envelope rather than
                 per-class, so the compatibility rule is one rule. The Kernel
                 owns the rule; the INGEST PATH enforces it, because
                 orchestrator.py:2395 replays an already-loaded log and a
                 refusal there is too late -- by then a bad-version log is in
                 memory. The precedent is `require_healthy_ingestion_manifests`
                 (storage/cache_replay.py:82, :131-140), which reads a per-day
                 manifest and refuses fail-closed at load: the same mechanism
                 with a different key.
REFACTOR PATH:   **Artifact + closure test, atomic.**
                 (1) `schema_version` on the envelope with a default.
                 (2) S8 asserting closure -- every event class resolves a
                 version, and the pinned-code-per-log rule is stated in one
                 place. S8 must detect a DRIFT, not the presence of a field.
                 MUTATION PROOF: add a throwaway field to an event class,
                 confirm S8 fails naming it, restore byte-identical.
                 (3) R5 IS WITHDRAWN. `event_schema_hash`
                 (disk_event_cache.py:60-71, :126-131) already refuses a cache
                 whose NBBOQuote/Trade shape this build does not know, with a
                 missing key failing closed because None != hash. A second
                 mechanism would add only "same shape, different declared
                 generation" -- a distinction with no consumer. The hash IS the
                 log-level pin; document it as such. schema_version goes on the
                 envelope for consumer readability only.
FILES:           src/feelies/core/events.py (Event envelope)
                 tests/conformance/test_schema_drift.py (S8)
BLAST RADIUS:    boundary -- one envelope field, 21 classes, one gate at ingest
VALIDATED BY:    S8 with the throwaway-field mutation proof; all 26 baselines;
                 the parity oracle; `uv run mypy src/feelies`
PARITY IMPACT:   hold -- no constant moves, and the oracle cannot see this step
                 (hand-written field lists per helper; S-17a closes that).
                 BUT event_schema_hash DOES move: schema_version is inherited
                 into NBBOQuote and Trade, so _compute_schema_hash changes and
                 EVERY cached day is invalidated, requiring a one-time
                 re-ingestion of every cached session including APP/2026-03-26.
                 The functional baseline skips on that miss unless
                 FEELIES_REQUIRE_BASELINE_CACHE=1, under which it FAILS. Re-ingest
                 before running that gate.
DELETES:         the 83 `schema_version` sites' ambiguity -- alpha-YAML
                 versioning in `promotion/` (25) and `cli/` (19) stops being the
                 only thing the name means. No module deleted. sec. G.10:
                 contract definition, net increase permitted.
NET DELTA:       src modules 0, public symbols +1, branch points +1 (the schema
                 gate; enumerable, becomes a gate-registry row under S-11).
                 Test files +2.
ROLLBACK:        revert. The field disappears and no baseline moves -- but
                 event_schema_hash moves BACK, invalidating any cache written
                 while S-09 was live. This is NOT the cheapest step to revert.
                 Verify the revert by S8 failing again, not by a green suite.
```

```
STEP:            S-10
CLOSES:          G46 (proposed in Phase 6 §8.1, absent from Phase 5's table)
PROBLEM:         CORE §C.8 states that a field whose unit is not declared does
                 not exist. **No event type declares a unit for any field** —
                 `unit` occurs once in `src/feelies/core/events.py`, as prose in
                 a docstring at `:557` (Phase 6 §8.1, `VERIFIED`). This makes
                 every boundary validation unwritable, which is why it precedes
                 every extraction.
FILES:           src/feelies/core/events.py (unit declarations)
                 tests/conformance/test_unit_declaration.py (S9)
                 tests/conformance/registry.py (register G46 -- S-01 deferred it
                 here and registry.py names S-10 as its registrar)                 
WHY THIS OWNER:  Units are a property of the contract, so they belong on the
                 contract in Tier 0, not in the consumer that interprets them.
REFACTOR PATH:   **Artifact + closure test, atomic.** (1) a unit declaration
                 mechanism on the envelope; (2) declare units for every numeric
                 field on all 21 classes; (3) S9 asserting closure — a numeric
                 field with no unit fails.
BLAST RADIUS:    boundary — declarations only, no arithmetic changes
VALIDATED BY:    S9, all 26 baselines, the parity oracle, mypy
PARITY IMPACT:   All 26 hold — declarations are metadata and enter no helper's
                 field list. **This step's risk is the opposite of parity**: it
                 will surface fields whose unit nobody can name, and Phase 2
                 flagged two already (`SizedPositionIntent.target_positions` —
                 weights, notional or shares — and
                 `disclosed_cost_total_bps_by_symbol`). Declaring a unit
                 wrongly is worse than declaring none, so a field whose unit is
                 disputed must be marked `undetermined` and block S-24, not be
                 guessed.
DELETES:         nothing. §G.10 justification: contract definition, the second
                 of the three exempt categories.
NET DELTA:       src modules 0, public symbols +1, branch points 0.
                 Test files +1.
ROLLBACK:        revert. Declarations vanish; S9 re-xfails.
```

```
STEP:            S-11
CLOSES:          G17, G38
PROBLEM:         Two independent gate ladders with no common registry. G1-G17
                 are string-keyed method calls in `LayerValidator` — 16
                 implemented, **G13 has zero references anywhere in
                 `src/feelies`** — and runtime gating is 329 call sites across
                 10 families. No operator can enumerate what would block a
                 trade. CORE §G enumerable gates; Inv-13 auditable provenance.
FILES:           src/feelies/core/gate_registry.py (the gate registry, new — 53 
                 rows as  data)
                 src/feelies/alpha/layer_validator.py:306-341
                 tests/conformance/test_gate_registry.py (S13, new)
                 tests/conformance/test_pathological_refusal.py (X6, completed
                 here — S-06 created the file with its first case; this step
                 adds FIX-3's remaining six input classes, which need a *named*
                 registered gate and so could not land earlier)
                 src/feelies/alpha/risk_wrapper.py (RT.BUDGET_RESOLVE)
                 src/feelies/execution/order_admission.py (session, min-size, cost)
                 src/feelies/monitoring/kill_switch.py (RT.KILL_SWITCH)
                 src/feelies/monitoring/latency_budget.py (RT.LATENCY_BUDGET)
                 src/feelies/ingestion/data_integrity.py (RT.DATA_HEALTH)
                 src/feelies/risk/basic_risk.py (leg D)
                 src/feelies/kernel/orchestrator.py (spine legs)                 
WHY THIS OWNER:  Phase 3 §D specifies 53 declared gates — 19 governance, 34
                 runtime spine — in one registry as data, from which ordinals,
                 docs and test bindings are generated. That resolves the G13
                 numbering problem by separating **ordinal** from **stable ID**,
                 so a hole in the numbering stops being possible.
REFACTOR PATH:   **Artifact + closure test, atomic.** (1) the registry with all
                 53 rows including stable ID, owner, latency class, failure
                 behaviour, exposure effect, monotonicity and disableable
                 status; (2) S13 asserting closure over it, on the
                 `GATE_EVIDENCE_REQUIREMENTS` pattern
                 (`src/feelies/promotion/evidence.py:1720-1731`); (3) bind the
                 existing 329 call sites to registry rows without changing any
                 predicate; (4) X6 asserting every gate emits a verdict.
                 (5) THE REGISTRY IS 53 ROWS: 19 governance + 34 runtime spine.
                 RT.SCHEMA_SUPPORTED, RT.CONTRACT_CONFORM and RT.IN_UNIVERSE are
                 per-boundary FAMILY TEMPLATES per Phase 3 D.4 -- their instance
                 count is generated from the wiring manifest (S-12), not
                 hand-counted as rows. A registry of 56 is a defect.
                 (6) X6 REQUIRES AN EMITTED RECORD, NOT AN API PROBE. Phase 6:
                 each FIX-3 class is refused by a named registered gate AND
                 produces an emitted record; a silent skip fails even when the
                 exposure outcome is correct. Phase 3 D.9: FAIL/UNKNOWN always
                 on the notification channel. Runtime sites must call
                 record_verdict at their existing refuse/allow -- that is not a
                 predicate change.
                 (7) The three FIX-3 classes bound to family templates
                 (nan, out_of_universe, missing_schema_version) have no named
                 row until family instances exist at S-12. Bind them to the
                 family template ID and mark those X6 cases
                 xfail(strict=True, reason="family instances land at S-12").                 
BLAST RADIUS:    platform-wide by reach, boundary by behaviour — 329 sites gain
                 a registry binding; **no predicate changes**. This is the one
                 place a wide reach is accepted before wave E, because every
                 later step's failure behaviour is stated against these rows.
VALIDATED BY:    S13, X6, all 26 baselines, the parity oracle, X3 from S-02
PARITY IMPACT:   hold — all 26 baselines, conditional on the emission channel
                 named below.
                 All 26 hold **if and only if no gate emission draws from a
                 shared sequence generator**. X6 requires every gate to emit a
                 verdict, and today `RiskVerdict` publishes 43 times in a whole
                 session (`perf_census.json`). Verdict totality makes it one of
                 the densest streams in the platform, and if those verdicts draw
                 `self._seq.next()` every baseline breaks. **The call: gate
                 verdicts are recorded on engine 11's notification channel,
                 which G29 confirms is entirely outside the parity manifest,
                 not published on the domain bus.** This is also the mitigation
                 for §A.3's emission-cost risk — a notification record need not
                 be a frozen domain event.
DELETES:         the G13 hole; the two-ladder split; 16 string-keyed method
                 dispatches in `LayerValidator` replaced by registry rows.
                 §G.10: contract definition.
NET DELTA:       src modules +1, public symbols +2, branch points 329 -> 329
                 (bound, not added; record_verdict calls sit at existing
                 decision points). Test files +2.
ROLLBACK:        revert. The 329 sites lose their binding and behave as today.
                 Reverting after S-22 is harder — see G.7's dependency note.
```

```
STEP:            S-11a
CLOSES:          nothing in Phase 5 — this is S-12's missing prerequisite,
                 identified by §K.1.3. It closes WL-7, the Phase 3 watch-line
                 whose live candidate is `src/feelies/bootstrap.py:355`.
PROBLEM:         bootstrap.py:355 claims "Subscribe the router before sensors so
                 fills retain their triggering quote." VERIFIED FALSE for that
                 pair: sensors cannot change fills. SensorRegistry._on_event
                 publishes SensorReading (sensors/registry.py:291);
                 HorizonSignalEngine._on_sensor_reading only caches
                 (signals/horizon_engine.py:207-239); HorizonAggregator only
                 buffers (features/aggregator.py:268) and snapshots fire on
                 HorizonTick, not the quote. Resting fills use the `quote`
                 argument to on_quote (passive_limit_router.py:233-239, :551),
                 so a second NBBOQuote subscriber that does not submit cannot
                 alter the fill stream. R3 confirms it: permuting router/sensor
                 order yields identical OrderAck streams today.
                 The comment therefore documents a hazard the code does not
                 have, while naming the wrong subscriber. The subscriber that
                 CAN submit on the same publish is StopExitController
                 (risk/stop_exit.py:172) -- see S-11b.
FILES:           src/feelies/bootstrap.py:353-355 (delete the comment and the
                 ordering requirement it encodes)
WHY THIS OWNER:  Phase 3 §238 prescribes exactly this resolution — "move the
                 requirement onto fill provenance" — and names it as what keeps
                 the wiring ordinal from acquiring trading-domain content. Engine
                 10 owns the fill and its provenance; the kernel owns
                 registration. A property of the fill belongs on the fill, not in
                 the kernel's registration order.
REFACTOR PATH:   (1) delete bootstrap.py:355's comment and the ordering
                 requirement.
                 (2) NO R3 HERE. R3 was written and proven unfalsifiable: the
                 router/sensor pair has no orderable hazard, so no mutation can
                 make a subscription-order test fail. EventBus runs each handler
                 to completion; a non-submitting subscriber never writes
                 _last_quotes; the router always sees the same `quote` argument
                 and the same _last_quotes at the start of on_quote. Two
                 mutations were tried -- reading _last_quotes after the write,
                 and reading a stale snapshot taken before it -- and neither
                 produced disagreeing streams. R3 originates in S-11b, where a
                 submitting subscriber makes the race observable.
                 (3) NO PROVENANCE FIELD. There is no Fill type; fills are
                 OrderAck, and S8's PINNED_PAYLOAD (test_schema_drift.py:90-100)
                 is exact equality over the field tuple.
BLAST RADIUS:    local -- one comment deleted, no code path touched
VALIDATED BY:    all 26 baselines, the parity oracle, mypy, full suite
PARITY IMPACT:   hold. One comment line is deleted. No field, no draw, no
                 computed value changes.
DELETES:         bootstrap.py:355's ordering requirement, unenforced and false
                 as stated for the pair it names
NET DELTA:       src modules 0, public symbols 0, branch points 0, test files 0
ROLLBACK:        revert; the comment returns. Nothing depends on it.
```
```
STEP:            S-11b
CLOSES:          new -- the real WL-7 race, found while executing S-11a
PROBLEM:         StopExitController subscribes NBBOQuote
                 (risk/stop_exit.py:172) and can publish an OrderRequest on the
                 same publish: _on_quote -> _emit_exit -> bus.publish(MARKET) at
                 :177-197, :269-297, with source_layer="RISK" and reason in
                 {STOP_EXIT, SESSION_FLAT}. The orchestrator routes that to
                 _submit_instrumented_order (orchestrator.py:594, :4947, :5019)
                 and on to backend.order_router.submit (:3863). But submit
                 prices from self._last_quotes, not from the triggering quote
                 (passive_limit_router.py:308-312, backtest router :172-176),
                 and on_quote writes _last_quotes first (passive :235, backtest
                 :142).
                 So the fill price depends on whether the router or stop-exit
                 subscribed first. Router-first: _last_quotes is this quote and
                 the stop fills at it. Stop-first: _last_quotes is the previous
                 quote or missing -- the stop fills at a stale price, or is
                 rejected with "no quote available for symbol". Ack sequence
                 draws move with it.
                 Bootstrap registers the router at :356 and stop-exit via
                 _create_stop_exit_controller -> attach() at :468, :1642, so the
                 correct order holds today by accident of registration order and
                 nothing enforces it. CORE sec. C.3 contract-first boundaries;
                 Inv-5, delivery order is output-determining.
WHY THIS OWNER:  Engine 10 owns the price a fill is struck at. A forced exit
                 must price against the quote that triggered it, not against
                 whatever the router last saw.
REFACTOR PATH:   (1) R3 is extended to permute router/stop-exit registration
                 order and assert an identical fill stream -- prove it FAILS
                 first, and report which of the two failure modes it produces
                 (stale price, or "no quote available for symbol").
                 (2) the triggering quote is carried as an EXPLICIT
                 DEFAULTED ARGUMENT on submit(), sourced from the quote
                 StopExit already holds, with _last_quotes as fallback. Both
                 simulated routers take it. NO ContextVar: implicit state across
                 a nested publish, and it forced risk/stop_exit.py to import a
                 private symbol from a concrete router -- a new forbidden
                 risk->execution edge on the already-broken G40 independence
                 contract, worse than the existing shared-helper edges. NO field
                 on OrderRequest either: S8's PINNED_PAYLOAD
                 (test_schema_drift.py:101-113) is exact equality on that tuple
                 as well as OrderAck.
                 (3) NO FIELD ON OrderAck. S8's PINNED_PAYLOAD
                 (test_schema_drift.py:90-100) is exact equality over the field
                 tuple; any addition fails by name. If the resolution requires
                 an OrderAck field, that is a scope change -- stop and report,
                 do not edit PINNED_PAYLOAD.
                 (4) NO SIGNATURE SNIFFING. _submit_to_router calls
                 submit(order, triggering_quote=quote) unconditionally. A
                 co_varnames check that falls back to submit(order) is fail-quiet
                 on the exact defect this step closes: a callee lacking the
                 parameter reverts to stale-price pricing and nothing reports it.
                 (5) _DelayedRouter overrides submit and must FORWARD to
                 super().submit(...), not swallow the argument.
                 _FillingRouter is the forced-exit tape double -- if it ignores
                 the quote, coverage on that path is fake.                 
FILES:           src/feelies/execution/passive_limit_router.py
                 src/feelies/execution/backtest_router.py:142,172-176 (same
                 _last_quotes race; this is the router APP and
                 test_orchestrator_replay.py actually use, since execution_mode
                 defaults to "market" -- a PassiveLimit-only fix cannot close
                 the defect)
                 src/feelies/execution/backend.py (OrderRouter protocol gains a
                 defaulted triggering-quote argument so the orchestrator can
                 pass it under mypy --strict)
                 src/feelies/broker/ib/router.py (matching unused parameter; IB
                 prices from the wire, not _last_quotes)
                 src/feelies/risk/stop_exit.py
                 src/feelies/kernel/orchestrator.py
                 tests/conformance/test_registration_order.py
                 src/feelies/storage/submitted_order_journal.py:118 (install_on's
                 wrapper must forward triggering_quote -- on paper it always
                 replaces order_router.submit, since IBOrderRouter has no
                 bind_submitted_order_journal, so a non-forwarding wrapper
                 strips the quote and the race returns)
                 tests/kernel/test_orchestrator_hazard_exit_routing.py:83,138
                 tests/kernel/test_orchestrator_exit_composer_routing.py:83
                 tests/kernel/test_orchestrator_bus_sized_intent.py:92
                 tests/determinism/test_forced_exit_attribution_replay.py:85
                 tests/kernel/test_orchestrator_async_fill_latency.py:41
                 tests/kernel/test_orchestrator_order_routing.py:98-101
                 (monkeypatches order_router.submit with raise_on_submit(_order);
                 must accept and ignore triggering_quote so the RuntimeError it
                 asserts is not preempted by a TypeError)                                  
BLAST RADIUS:    boundary -- one pricing source changes on the forced-exit path
VALIDATED BY:    R3 as extended with its fail-first proof, all 26 baselines, the
                 parity oracle, mypy
PARITY IMPACT:   VERIFY, DO NOT ASSUME. The correct order holds today by
                 accident, so recorded tapes were produced under router-first
                 and should be unaffected. But this changes the pricing source
                 on a path that emits orders, and ack sequence draws move if
                 fills change. Establish structurally which determinism tapes
                 construct StopExitController before declaring, and enumerate
                 any affected stream. If a constant moves, name it.
DELETES:         the dependence of forced-exit fill price on subscription order
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert. Pricing returns to _last_quotes and the ordering
                 becomes load-bearing again.
```

```
STEP:            S-12
CLOSES:          G02, G10, G28, G39
PROBLEM:         Four defects with one cause: the subscription graph is
                 emergent. 32 subscribe sites, 16 of which publish from inside
                 their own dispatch, no depth bound, no dedup key, delivery
                 order output-determining, and nothing hashing any of it (G02);
                 6 event types published to zero static subscribers (G10);
                 `KillSwitchActivation` inert despite a docstring at
                 `src/feelies/core/events.py:416` promising "all layers can
                 react" (G28); and 45 external attribute assignments plus 10
                 cross-object private accesses, so objects are not valid after
                 `__init__` (G39). CORE §C.3; Inv-3 contract-first boundaries.
FILES:           src/feelies/core/wiring_manifest.py (wiring manifest, new)
                 src/feelies/bus/event_bus.py:59-70 (depth bound)
                 src/feelies/bootstrap.py:584,587,588,411,1543
                 tests/conformance/test_wiring_manifest.py (S15, new)
                 tests/conformance/test_composition_root.py (S17, new)
                 tests/conformance/test_cascade_depth.py (X8, new)
                 tests/conformance/test_kill_switch_consumer.py (X9, new)
                 tests/conformance/test_registration_order.py (R3, created in
                 S-11b; extended here to permute registration order over the
                 full manifest and assert an identical hash)
WHY THIS OWNER:  Phase 3 §B specifies the wiring manifest as a declared, hashed
                 artifact and the composition root as the only place wiring
                 happens. A manifest is the only thing that makes subscription
                 order reviewable, and subscription order is output-determining.
REFACTOR PATH:   **Requires S-11a first** — until fill provenance is explicit,
                 `NBBOQuote` subscription order is load-bearing and R3 below
                 cannot pass, so this step cannot reach its own completion
                 criterion (§K.1.3). **Artifact + closure test, atomic.** (1) the
                 manifest declaring every subscription and its order, hashed into
                 the run fingerprint; (2) S15 asserting the manifest matches the runtime
                 graph — a subscription not in the manifest fails; (3) X8
                 asserting a cascade depth bound on the re-entrant bus; (4) the
                 six zero-subscriber types resolved one at a time: give a
                 consumer or reclassify as a notification record — the decision
                 per type recorded in the manifest; (5) `KillSwitchActivation`
                 gains a consumer and X9 asserts fail-closed, durable and
                 observable; (6) move the five post-construction assignments in
                 `src/feelies/bootstrap.py` into constructor injection, S17 asserting no
                 external attribute assignment outside a composition-root
                 allowlist.
BLAST RADIUS:    platform-wide — the composition root changes shape
VALIDATED BY:    S15, S17, X8, X9, R3 (registration-order permutation), all 26
                 baselines, the parity oracle, mypy
PARITY IMPACT:   **All 26 must hold, and R3 is what proves it.** Declaring the
                 existing order changes nothing; *changing* the order changes
                 output, because Phase 1 §3 measured delivery order as
                 output-determining. The manifest must therefore be written
                 **from the measured current order**, not from a reading of
                 `src/feelies/bootstrap.py`. R3 permutes registration order and asserts an
                 identical hash — if R3 fails, the manifest is load-bearing in a
                 way the target forbids and the step is incomplete.
                 Step (4) is where a baseline can move: giving
                 `PositionUpdate` or `OrderAck` a real subscriber changes
                 nothing computed, but **removing** a publish removes a
                 `self._seq` draw. Any type whose publish is removed re-pins.
                 Enumerate that per type inside the step; do not batch it.
DELETES:         the emergent subscription graph; up to 6 inert publishes; 45
                 external attribute assignments -> allowlisted composition-root
                 set; 10 cross-object private accesses;
                 `subscribe_all` (0 call sites, `src/feelies/bus/event_bus.py:55`) `subscribe_all` is NOT deleted here. Zero call sites in
                 src/feelies apart from its definition, but six outside FILES
                 use it: tests/bus/test_event_bus.py (3),
                 tests/kernel/test_orchestrator.py (2),
                 tests/kernel/test_single_writer_invariant.py,
                 tests/fixtures/replay.py,
                 tests/conformance/harness/engine_probe.py (HARN-1) and
                 scripts/smoke_pipeline.py. Removing it is a separate cleanup.
NET DELTA:       src modules +1, public symbols +2 (`subscribe_all` deleted),
                 branch points +1 (the depth bound).
                 Test files +4.
ROLLBACK:        revert — but this is the least cleanly revertible step in wave
                 C, because constructor-injection changes touch every consumer's
                 signature. Ship it as its own release, not batched.
```
```
STEP:            S-12a
CLOSES:          the three X6 cases deferred from S-11
PROBLEM:         S-11 landed RT.SCHEMA_SUPPORTED, RT.CONTRACT_CONFORM and
                 RT.IN_UNIVERSE as per-boundary FAMILY TEMPLATES, not registry
                 rows, per Phase 3 D.4: their instance count is generated from
                 the wiring manifest, not hand-counted. Three X6 cases -- nan,
                 out_of_universe and missing_schema_version -- are bound to those
                 templates and carry xfail(strict=True, reason="family instances
                 land at S-12"). S-12 delivered the manifest but did not generate
                 the instances, so the xfails still stand and S13 forbids the
                 three IDs from appearing in GATE_REGISTRY.
WHY THIS OWNER:  Engine 5 owns the gate registry; the manifest is the generator.
                 A family instance is a registry row derived from a declared
                 subscription, not a hand-written one.
REFACTOR PATH:   (1) generate family instances from
                 wiring_manifest.SUBSCRIPTIONS -- one per receiving boundary per
                 template; (2) S13 asserts the generated set matches the manifest
                 and that the three template IDs remain absent as hand-written
                 rows; (3) drop the three xfails in X6. strict=True means a
                 green xfail is a failure, so they must be dropped in the same
                 commit that makes them pass.
FILES:           src/feelies/core/gate_registry.py
                 tests/conformance/test_gate_registry.py (S13)
                 tests/conformance/test_pathological_refusal.py (X6)
BLAST RADIUS:    boundary -- registry rows are generated, no predicate changes
VALIDATED BY:    S13 with the generated-instance assertion, X6 with the three
                 xfails dropped, all 26 baselines, the parity oracle, mypy
PARITY IMPACT:   hold. Generated rows are registry data on engine 11's
                 notification channel, outside the parity manifest per G29. No
                 self._seq draw, no predicate change. VERIFY, do not assume.
DELETES:         the three deferred xfails; the gap between declared templates
                 and instantiated rows
NET DELTA:       src modules 0, public symbols 0, branch points 0
ROLLBACK:        revert; the instances vanish and the three xfails must be
                 restored or X6 fails strict.
```

```
STEP:            S-13
CLOSES:          G09
PROBLEM:         26 `SequenceGenerator` constructions, 13 taking the
                 `thread_safe=True` default, and no registry naming which stream
                 each owns. No collision is possible today because sequences are
                 per-object and never compared — the gap is that nothing records
                 the invariant, so a future cross-stream comparison is silently
                 wrong. CORE §C.6 single source of truth per fact.
FILES:           src/feelies/core/identifiers.py:28
                 src/feelies/core/sequence_authority.py (producer +
                 sequence-authority registry, new)
                 src/feelies/signals/horizon_engine.py
                 src/feelies/sensors/registry.py
                 src/feelies/sensors/horizon_scheduler.py
                 src/feelies/kernel/orchestrator.py
                 src/feelies/execution/backtest_router.py
                 src/feelies/execution/passive_limit_router.py
                 src/feelies/ingestion/massive_normalizer.py
                 src/feelies/features/aggregator.py
                 src/feelies/bootstrap.py
                 src/feelies/broker/ib/router.py
                 src/feelies/monitoring/horizon_metrics.py
                 tests/conformance/test_single_owner.py (S12)
WHY THIS OWNER:  One sequence authority per stream is Tier 0 declaration, and
                 S12's other clause — one producer per contract — is the same
                 registry read the other way.
REFACTOR PATH:   **Artifact + closure test, atomic.** (1) registry mapping
                 stream -> sequence authority and contract -> sole producer;
                 (2) S12 asserting closure both ways; (3) `SequenceGenerator`
                 gains a required stream name so an unregistered generator
                 cannot be constructed.(3) `stream` is a REQUIRED KEYWORD ARGUMENT on SequenceGenerator, enforced by S12 over PRODUCTION call sites
                 only, not by the constructor signature. A required positional
                 would TypeError 154 constructions across 65 test files and 21
                 across 7 scripts -- out of proportion to the step, and the
                 registry is a production invariant. S12 asserts: every
                 SequenceGenerator in src/feelies passes stream=, every stream
                 named there is in the registry, and every registry stream is
                 constructed. Tests and scripts may construct unnamed
                 generators; they are not authorities.
                 (4) the stream list and the contract -> producer rows are
                 DERIVED, not invented: streams from the src/feelies
                 construction sites found by the S12 scan, producers from the
                 publish sites already enumerated in wiring_manifest.SUBSCRIPTIONS
                 and gate_registry. If a stream or contract cannot be attributed
                 from those, STOP and report it rather than choosing an owner. 
BLAST RADIUS:    boundary — 26 construction sites gain a name
VALIDATED BY:    S12, all 26 baselines, the parity oracle,
                 `tests/determinism/test_legacy_sequence_isolation.py`
PARITY IMPACT:   All 26 hold. Naming a generator changes no draw order. This is
                 the step that makes G.0.1's rule **checkable** rather than
                 merely true: once every stream has a named authority, a later
                 step that changes draw counts is visible in the registry diff
                 rather than discovered by a broken hash.
DELETES:         13 implicit `thread_safe=True` defaults become explicit;
                 the unnamed-generator construction path the unnamed-generator construction path IN PRODUCTION only.
NET DELTA:       src modules +1, public symbols +1, branch points 0.
                 Test files +1.
ROLLBACK:        revert; generators lose their names.
```

```
STEP:            S-14
CLOSES:          G37
PROBLEM:         **Zero sites.** No forbidden-read assertion, no
                 boundary-violation check, no runtime guard anywhere in
                 `src/feelies`. Enforcement is entirely static — G1 at YAML load,
                 downgradable to a warning, plus `mypy --strict` — and neither
                 can see a cross-layer read performed through an object the type
                 system permits. Inv-8 layer separation.
FILES:           src/feelies/core/forbidden_reads.py (forbidden-reads matrix, new)
                 tests/conformance/test_forbidden_reads.py (S14)
                 tests/conformance/harness/engine_probe.py (HARN-1, dynamic half)
WHY THIS OWNER:  Phase 3 §C specifies the matrix; Phase 3 also states plainly
                 that "the matrix is unenforceable until 3.1's tier rule holds",
                 which is why S-04 precedes this and not the reverse.
REFACTOR PATH:   **Artifact + closure test, atomic.** (1) the matrix as data,
                 one row per (engine, fact) pair; (2) S14's static half — import
                 and attribute-access analysis against the matrix; (3) S14's
                 dynamic half via HARN-1 — instrument each engine's read
                 surface, run a tick sequence, assert no forbidden read occurs.
BLAST RADIUS:    boundary — a new artifact plus instrumentation; no production
                 behaviour changes
VALIDATED BY:    S14 both halves, all 26 baselines, the parity oracle
PARITY IMPACT:   All 26 hold. The matrix is declarative and the probe is
                 test-only. **Phase 3 records the honest limit and it belongs
                 here:** the largest violation of the matrix has no row in it,
                 because a Tier-1 module performs Tier-2 reads on behalf of nine
                 engines and there is no cell for "the kernel read engine 7 on
                 engine 8's behalf." S14 will pass while the god orchestrator
                 stands. It becomes meaningful only as wave D lands, which is
                 the correct dependency direction and not a weakness of the
                 test.
DELETES:         nothing. §G.10: contract definition.
NET DELTA:       src modules +1, public symbols +1, branch points 0.
                 Test files +1.
ROLLBACK:        revert.
```

```
STEP:            S-15
CLOSES:          G04
PROBLEM:         110 stateful classes, 38 mutate outside `__init__`, **32 have
                 no reset path**. `Orchestrator` is the extreme at 104
                 `__init__` attributes, 38 mutated later, zero reset methods.
                 Contained today only by process-per-run; breaks the moment two
                 runs share a process — parameter sweeps, notebooks, a
                 long-lived paper session. Inv-1 deterministic replay.
FILES:           src/feelies/kernel/orchestrator.py
                 src/feelies/execution/passive_limit_router.py
                 src/feelies/execution/backtest_router.py
                 src/feelies/execution/moc_fill.py
                 src/feelies/execution/trading_session.py
                 src/feelies/ingestion/massive_normalizer.py
                 src/feelies/ingestion/massive_ws.py
                 src/feelies/broker/ib/connection.py
                 src/feelies/broker/ib/router.py
                 src/feelies/monitoring/horizon_metrics.py
                 src/feelies/monitoring/in_memory.py
                 src/feelies/signals/horizon_engine.py
                 src/feelies/alpha/registry.py
                 src/feelies/alpha/risk_wrapper.py
                 src/feelies/features/aggregator.py
                 src/feelies/risk/basic_risk.py
                 src/feelies/sensors/horizon_scheduler.py
                 src/feelies/services/regime_state_cache.py
                 src/feelies/bus/event_bus.py
                 src/feelies/composition/engine.py
                 src/feelies/composition/synchronizer.py
                 src/feelies/core/clock.py
                 src/feelies/core/identifiers.py
                 src/feelies/harness/backtest_prep.py
                 src/feelies/portfolio/memory_position_store.py
                 src/feelies/storage/submitted_order_journal.py
                 src/feelies/ingestion/massive_ingestor.py
                 src/feelies/portfolio/cross_sectional_tracker.py
                 src/feelies/risk/deferral_cap.py
                 src/feelies/risk/exit_composer.py
                 src/feelies/risk/hazard_exit.py
                 src/feelies/risk/stop_exit.py
                 src/feelies/sensors/registry.py
                 src/feelies/storage/memory_event_log.py
                 tests/conformance/test_reset_paths.py (S16 — authored in S-03;
                 this step drops its xfail)
                 tests/conformance/test_recovery_determinism.py (R6, new)
WHY THIS OWNER:  Phase 2 puts the reset path on the engine that owns the state.
                 Several of the 32 are engine 10's routers and engine 7's stores,
                 whose reset contracts differ in kind — the submitted-order
                 journal is **durable and must not be reset by replay**, while
                 the position stores are cold-start-only. The registry/ledger
                 split from Phase 2 engine 5 applies here.
REFACTOR PATH:   (1) S16 as an assertion over the existing scan, xfail(strict);
                 (2) declare per class whether its state is run-scoped or
                 durable — durable state is exempt **with a stated reason**, not
                 silently; (3) `reset()` on each run-scoped class; (4) R6
                 asserting reset-then-replay equals cold-start replay. (5) THE CLASS SET IS DERIVED, NOT HAND-COUNTED. Run
                 tools/arch/substrate.py and take stateful_no_reset — the
                 emitted stateful_no_reset_top is TRUNCATED to 25 by
                 substrate.py:410 while n_stateful_no_reset reports 34, so the
                 artifact cannot name the set. FILES above lists the files those
                 classes live in. If the scan names a class in a file not listed,
                 STOP and report it — do not edit an undeclared file, and do not
                 skip a class to stay inside FILES. The plan's "32" is stale;
                 report the count you find. broker/ib/router.py and portfolio/memory_position_store.py are
                 declared but absent from the 34: the scanner counts `self.attr =`
                 only, not dict writes, so IBOrderRouter and MemoryPositionStore
                 mutate through containers. Declaring them is deliberate -- if
                 either needs a reset on the same reasoning, add it and say so;
                 if not, leave them untouched and record why.
BLAST RADIUS:    boundary — 32 classes gain a method
VALIDATED BY:    S16, R6, all 26 baselines, the parity oracle
PARITY IMPACT:   All 26 hold. Adding an unused method changes nothing.
                 **R6 is where a latent defect surfaces**: if reset-then-replay
                 diverges from cold-start replay for any class, that class held
                 state the reset does not restore, and the divergence was
                 already present and merely unreachable.
DELETES:         `_handle_tick_failure`'s ad-hoc three-attribute clearing at
                 `src/feelies/kernel/orchestrator.py:1474` — a recovery path
                 masquerading as a reset — replaced by the declared reset
NET DELTA:       src modules 0, public symbols **+32**, branch points 0.
                 Test files +2. **This is the plan's largest public-symbol
                 increase**; §G.10 permits it as a contract definition, and the
                 justification is that a reset path is the contract that makes
                 replay-from-known-state possible.
ROLLBACK:        revert. The methods disappear unused; the ad-hoc clearing
                 returns.
```

```
STEP:            S-16
CLOSES:          G06, G30
PROBLEM:         Alpha manifest **content** moves no checksum: `alpha_specs` is
                 reduced to `sorted(spec.name for spec in value)` at
                 `src/feelies/core/platform_config.py:726-727`, and no
                 `manifest_hash` / `spec_hash` / `yaml_hash` / `sha256` exists
                 anywhere in `src/feelies/alpha/`. Editing a threshold in an
                 `alphas/**/*.alpha.yaml` changes what the platform trades and
                 moves no checksum. Engine 12's forensic outputs carry no
                 fingerprint at all. Inv-13 full provenance; CORE §C.13.
FILES:           src/feelies/alpha/module.py
                 src/feelies/alpha/loader.py
                 src/feelies/alpha/registry.py
                 src/feelies/alpha/signal_layer_module.py
                 src/feelies/core/platform_config.py
                 src/feelies/forensics/analyzer.py
                 src/feelies/forensics/decay_detector.py
                 src/feelies/forensics/cost_survival.py
                 src/feelies/forensics/cost_circuit_breaker.py
                 src/feelies/forensics/edge_calibration.py
                 src/feelies/forensics/gate_close_attribution.py
                 src/feelies/forensics/decouple_backstop.py
                 tests/conformance/test_fingerprint_totality.py (R4)
                 tests/acceptance/test_backtest_app_baseline.py (`_BASELINE_CONFIG_HASH` re-pin)
                 tests/core/test_platform_config.py (snapshot path; dummy `alpha_specs` Paths)
WHY THIS OWNER:  Phase 2 engine 5: the engine that reads and validates
                 manifests is the one that must compute their hash. Engine 12
                 stamps the fingerprint it was given; it does not compute one.
REFACTOR PATH:   (1) R4 asserting the fingerprint covers everything that can
                 change output, xfail(strict); (2) `manifest_hash` per alpha,
                 computed at load; (3) include it in `_to_dict`; (4) stamp
                 engine 12's outputs with the run fingerprint; (5) drop the
                 xfail.
                 **Scope: the resolved registry, never the promotion ledger**
                 (§K.1.1). The registry is a run input and must be
                 bit-reproducible; the ledger is a durable record of decisions
                 and must not be expected to reproduce. R4 asserts the
                 fingerprint covers what can change output, and a ledger entry
                 cannot — it is never read on the tick path. If R4 is written to
                 demand ledger coverage it will demand reproducibility of a
                 wall-clock-stamped append-only log, which is unachievable; state
                 the exclusion in R4 rather than discovering it. 
                 New `manifest_hash` / forensic fingerprint fields take a default
                 so existing `AlphaManifest` / `TCAReport` sites outside FILES
                 stay valid. Do not add a field to `Signal` or otherwise touch
                 `src/feelies/core/events.py` (S8 `PINNED_PAYLOAD`). Stamp R4's
                 Signal provenance via `metadata` in the loader wrap;
                 `HorizonSignalEngine._patch_signal` already preserves `metadata`.
                 `test_app_baseline_config_contract_hash` calls `from_yaml` then
                 `snapshot()` and never loads alphas, so `_to_dict` must disclose
                 spec *content* (not names-only) or that oracle will not move.
BLAST RADIUS:    boundary — the config snapshot gains a field
VALIDATED BY:    R4, all 26 baselines, and specifically
                 `tests/acceptance/test_backtest_app_baseline.py`'s
                 `test_app_baseline_config_contract_hash`
PARITY IMPACT:   **All 26 replay baselines hold; the config-contract hash
                 `_BASELINE_CONFIG_HASH` breaks by construction, and that is the
                 point.** The snapshot exists to change when the run's inputs
                 change. `_BASELINE_CONFIG_HASH` is already exempted from the
                 parity manifest as "config-contract hash, not a replay
                 baseline" (`tests/determinism/test_parity_manifest.py:174-175`),
                 so this is a one-line re-pin in the acceptance test, not a
                 manifest re-pin. Note the compatibility shims at
                 `src/feelies/core/platform_config.py:740-754` and `:756-764` exist precisely to
                 keep established checksums valid — this step deliberately
                 breaks that checksum and must not extend the shim to hide it.
DELETES:         the names-only reduction at `:726-727`; the largest hole in run
                 provenance
NET DELTA:       src modules 0, public symbols +1, branch points 0.
                 Test files +1.
ROLLBACK:        revert, and restore `_BASELINE_CONFIG_HASH` to its prior value
                 in the same commit. The prior value is in git history.
```

```
STEP:            S-17
CLOSES:          G05, G29, and G11's parity clause
PROBLEM:         6 event classes have no hash helper at all (`Alert`,
                 `KillSwitchActivation`, `MetricEvent`, `NBBOQuote`,
                 `SensorReading`, `Trade`) and 15 carry fields in no hash.
                 `NBBOQuote` and `Trade` are the **inputs** — engine 1's
                 canonical stream has no baseline of its own, so an
                 ingestion-side change is invisible to the oracle until it moves
                 a downstream hash. Engine 11's entire output stream is outside
                 the manifest. Inv-5.
FILES:           tests/conformance/test_market_data_canonical.py (R2 —
                 authored in S-03; this step supplies
                 EXPECTED_MARKET_DATA_CANONICAL_HASH on the manifest
                 and drops the xfail)
                 tests/determinism/test_alert_taxonomy_replay.py (engine 11
                 taxonomy: alert_name and severity only, never message)
                 tests/determinism/parity_manifest.py
                 tests/determinism/test_parity_manifest.py (R9 — extends the two
                 closure tests already at `:261` and `:288`; re-pins
                 EXPECTED_MANIFEST_FINGERPRINT)
WHY THIS OWNER:  Phase 1 §6.1 specifies exactly this and calls it "the cheapest
                 coverage gain available in this axis" because it needs **no
                 production change**: feed a fixed raw-frame fixture through
                 `MassiveNormalizer.on_message`
                 (`src/feelies/ingestion/massive_normalizer.py:292`) and hash the
                 emitted `NBBOQuote`/`Trade` sequence over the full declared
                 field set, `Decimal` fields as exact strings rather than `.6f`.
                 No transcendental math, so it is portable and can be a manifest
                 entry rather than an exemption.
REFACTOR PATH:   (1) the engine-1 baseline; (2) engine 11's **taxonomy** only —
                 `alert_name` and `severity` per stream, never `message`, per
                 Phase 1 §6.1's warning that pinning alert content converts
                 every diagnostic improvement into a parity break; (3) R9
                 asserting closure — every engine output is hashed or
                 exempt-with-a-reason; (4) state the `.6f`/`.2f` float tolerance
                 **in the manifest**, per Phase 1 §6's recommendation, so
                 "bit-identical" stops overstating what the oracle checks.
BLAST RADIUS:    local — `tests/` only. No `src/` edit.
VALIDATED BY:    R9, the two closure tests already at
                 `tests/determinism/test_parity_manifest.py:261,288`, the
                 parity oracle
PARITY IMPACT:   All 26 existing baselines hold; **the manifest gains 2 or more
                 entries (26 -> 28+) and `manifest_fingerprint()` changes by
                 construction.** That is a manifest-growth re-pin, not a
                 behavioural break, and it is one visible line by design
                 (`tests/determinism/test_parity_manifest.py:352`). Declaring the
                 float tolerance changes no hash — it documents the one the
                 helpers already use.
DELETES:         the claim that engine 1 is pinned by `symbol_halted`; the
                 undocumented `.6f` tolerance
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Test files +1, manifest entries +2.
ROLLBACK:        revert; `manifest_fingerprint()` returns to its prior value.
```
```
STEP:            S-17a
CLOSES:          new -- the parity oracle is blind to schema growth
PROBLEM:         Hash inputs are hand-written field lists per helper (Phase 0
                 P-1, Phase 1 sec. 6), so adding a field to any event moves no
                 replay hash. CORE sec. C.11 -- schema evolution never breaks
                 replay -- is therefore unenforced by the oracle: S-09's
                 schema_version, S-11's gate-verdict field, S-16's config
                 snapshot field and S-31's unread-field deletions all pass
                 invisibly. The gap is stated at
                 phase7_migration.md:1021-1022 ("the oracle cannot see this
                 step (hand-written field lists per helper; S-17a closes
                 that)"). The cites previously listed as :1009-1013, :2878,
                 :3730, :3977 do not name this gap. S-17 grows
                 manifest_fingerprint() by adding manifest ENTRIES, which is
                 a different thing from covering field sets.
WHY THIS OWNER:  The Kernel owns the determinism substrate. One line in
                 manifest_fingerprint() converts schema drift from invisible to
                 declared.
WHY HERE:        After S-09, S-11 and S-16 have added their fields and after
                 S-17's manifest growth (28 entries), so the fingerprint
                 re-pin falls in one window. Placing it earlier would make
                 those field-adding steps parity=break for no additional
                 safety.
REFACTOR PATH:   (1) a test asserting that adding a field to any Event
                 subclass moves manifest_fingerprint() and does not move the
                 28 replay hashes. Prove it FAILS first: add
                 `Signal.s17a_probe: int = 0`. S8
                 (`tests/conformance/test_schema_drift.py`, PINNED_PAYLOAD)
                 will fail by name if PINNED_PAYLOAD is not updated -- that
                 is not the oracle proof. The oracle proof is
                 test_manifest_fingerprint_matches_locked_value and
                 test_manifest_entry_matches_replay both still passing.
                 Every concrete Event subclass is in PINNED_PAYLOAD; there
                 is no class S8 will ignore. (2) fold the per-event field
                 set (class name + dataclass field names, in dataclass
                 order, every Event subclass) into
                 manifest_fingerprint()'s input. Do not rewrite hash-helper
                 field lists. (3) operator re-pins
                 EXPECTED_MANIFEST_FINGERPRINT only, in the same commit,
                 with the rationale referencing this step. The 28
                 EXPECTED_*_HASH values must not move.
FILES:           tests/determinism/parity_manifest.py
                 tests/conformance/test_schema_drift.py (S8 -- authored in
                 S-09; this step adds the fingerprint-moves-on-field-add
                 assertion, or a sibling in the same file)
                 tests/determinism/test_parity_manifest.py
                 (EXPECTED_MANIFEST_FINGERPRINT re-pin)
BLAST RADIUS:    platform-wide -- the fingerprint re-pins once. No replay
                 baseline re-pins. After this lands, every later field add
                 or delete is a fingerprint break by design, including
                 S-31 step 1 (20 unread fields) which today claims all
                 baselines hold.
VALIDATED BY:    the drift test failing before (fingerprint holds with the
                 throwaway present) and passing after (fingerprint moves,
                 28 replay hashes do not); test_parity_manifest reporting
                 no drift between owning modules and the manifest
PARITY IMPACT:   break -- EXPECTED_MANIFEST_FINGERPRINT moves exactly once,
                 by construction. The 28 replay hashes and counts do not
                 move. The operator re-pins EXPECTED_MANIFEST_FINGERPRINT;
                 the agent does not. No behaviour changes: the recorded
                 streams are identical, only the fingerprint's input set
                 grows (Event subclass field names). Do not re-pin any
                 EXPECTED_*_HASH. The corpus is 28 manifest entries and 64
                 scanned file constants; the two
                 EXPECTED_MARKET_DATA_CANONICAL_* bindings live in
                 tests/conformance/ and are invisible to baseline.py's
                 scanner. 
DELETES:         the oracle's blindness to schema growth; the standing need
                 to remember to update a helper's field list by hand for
                 the fingerprint to notice
NET DELTA:       src modules 0, public symbols 0, branch points 0. Test
                 files +0 (extends S-09's closure test).
ROLLBACK:        revert, and restore EXPECTED_MANIFEST_FINGERPRINT from the
                 pre-S-17a capture. After this lands, every field-adding
                 or field-deleting step is parity=break on the fingerprint
                 by design -- that is the point, not a regression. S-23
                 (new DeRiskRequirement) and S-31 (unread-field deletions;
                 StateTransition removal) are the remaining events.py
                 shape changes.
```

```
STEP:            S-18
CLOSES:          G12
PROBLEM:         All 21 event classes are frozen dataclasses and 8 of them
                 carry mutable dict fields (17 fields). HorizonFeatureSnapshot
                 has 5: values, warm, stale, source_sensors, feature_versions.
                 The others: Alert.context; CrossSectionalContext
                 signals_by_symbol, signals_by_strategy_by_symbol,
                 snapshots_by_symbol; MetricEvent.tags; RiskVerdict.constraints;
                 Signal.metadata; SizedPositionIntent target_positions,
                 factor_exposures, mechanism_breakdown,
                 disclosed_cost_total_bps_by_symbol; StateTransition.metadata.
                 There is no list or set field on any Event subclass.
                 Frozen-ness is advisory for those payloads; a holder can
                 mutate a published event in place. SizedPositionIntent and
                 CrossSectionalContext are each published to three subscribers,
                 so in-place mutation by one is invisible to the others.
                 Inv-7 typed schemas.
FILES:           src/feelies/core/events.py (the 8 classes, 17 dict fields)
                 tests/conformance/test_event_immutability.py (S10 — authored
                 in S-03; this step drops its xfail after the last class)
WHY THIS OWNER:  Immutability is a property of the contract, so it belongs in
                 Tier 0 with the contract.
REFACTOR PATH:   S10 already asserts the live AST
                 (tools.arch.contracts mutable_container on dict/list/set
                 annotations) with xfail(strict, GAP G12). contracts.json is a
                 generated evidence file (key
                 events_with_mutable_container_fields), not a test input, and
                 is not in the tree. (1) freeze each class's dict fields as
                 MappingProxyType (or an equivalent immutable mapping) inside
                 the dataclass so publishers keep passing dict; do not rewrite
                 construction sites. tuple/frozenset do not apply — zero
                 list/set fields exist. Cheapest first. (2) drop the xfail on
                 the last class. Convert one class per commit so a moved hash
                 names its class.
BLAST RADIUS:    boundary — every consumer that mutates a received event
                 breaks loudly at that point, which is the intended discovery
                 mechanism
VALIDATED BY:    S10, all 28 baselines, the parity oracle, mypy, full suite
PARITY IMPACT:   hold — all 28 replay hashes and
                 EXPECTED_MANIFEST_FINGERPRINT. S-17a's fold hashes class names
                 and field names only, not annotations, so a type change does
                 not move the fingerprint. Replay helpers that read these
                 fields use Mapping .items() / .get() / key indexing;
                 MappingProxyType with the same contents hashes identically. A
                 tuple-of-pairs conversion would AttributeError those helpers,
                 not silently re-pin. **Unless a consumer was mutating a
                 published event and the hash was reading the mutated value.**
                 If a baseline moves, this step has found a live
                 read-after-mutation defect (Phase 0 C-7). Convert one class
                 per commit.
DELETES:         17 mutable dict fields on 8 frozen event classes
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Test files +0 (drops xfail on S-03's S10).
ROLLBACK:        revert per class. Converting one class per commit is what
                 makes this revertible at useful granularity.
```

---

### G.4 Wave D — ownership moves

**Every step in this wave must be net-neutral or net-negative in modules, public
symbols and branch points.** §G.10 permits a net increase only for conformance
tests, contract definitions and P0 fixes, and this wave is none of the three. A
step here that adds surface has not moved a responsibility — it has copied one.

**The common shape, stated once so the blocks stay short.** Each step moves
methods out of `src/feelies/kernel/orchestrator.py` into the engine whose Phase 2
sheet claims them. The refactor path is the same every time and the parity rule
from G.0.1 governs all of them:

1. Land the engine's conformance tests, xfailed where they fail.
2. Move the method bodies unchanged, leaving a delegating call.
3. Assert all 26 baselines and the parity oracle hold — **a pure move changes no
   sequence draw and no hashed field, so a moved hash means the move was not
   pure.** This is the wave's single acceptance criterion.
4. Delete the delegating call and repoint the caller.
5. Drop the xfails.

Step 3 is the whole reason the wave is safe. Step 4 is where a step becomes
independently revertible: after 3 the code is in two places and works; after 4 it
is in one.

```
STEP:            S-19
CLOSES:          G14
PROBLEM:         5 regime classification methods live in the kernel —
                 `_calibrate_regime_engine:2335`, `_update_regime:2432`,
                 `_maybe_publish_hazard_spike:2501`, `_regime_label_for:4556`,
                 `_checkpoint_regime_snapshot:5460`. The engine CORE §E most
                 insists must be singular is authored in the module CORE §J
                 names as the anti-pattern. Inv-8.
FILES:           src/feelies/kernel/orchestrator.py (the 5 methods)
                 src/feelies/services/regime_engine.py (destination — engine 3
                 has no package of its own; it lives in `services/` alongside
                 `src/feelies/services/regime_state_cache.py`, which is itself a finding: the engine
                 CORE §E.3 requires to be singular is the one engine with no
                 package boundary to be singular inside of. This step moves the
                 methods to the existing module and does **not** create a
                 package, because creating one is a naming decision for S-34's
                 residual classification, not a prerequisite for this move.)
WHY THIS OWNER:  Engine 3 already has the platform's strongest contract
                 discipline — a single declared read path at
                 `src/feelies/bootstrap.py:289`, two parity baselines, and a
                 gate correctly off by default. Only its placement is wrong,
                 which makes it the cheapest first extraction and the one that
                 proves the wave's method.
REFACTOR PATH:   the common shape. Move `_maybe_publish_hazard_spike` **last**:
                 it draws from `self._hazard_seq` (`:2519`), a separate
                 generator, so it is the one method in this step whose move
                 could shift a sequence family.
BLAST RADIUS:    boundary
VALIDATED BY:    S2, S12, S14, `level5_regime_hazard_spike`, `level6_regime_state`,
                 the parity oracle, full suite
PARITY IMPACT:   All 26 hold. Pure move. `level5_regime_hazard_spike` is the one
                 to watch, for the `_hazard_seq` reason above.
DELETES:         5 methods from the orchestrator (123 -> 118); 3 method calls
                 through `self._regime_engine`
NET DELTA:       src modules 0, public symbols **0** (the methods are private on
                 both sides), branch points 0. Orchestrator lines **-~200**.
ROLLBACK:        revert; the methods return to the kernel.
```

```
STEP:            S-20
CLOSES:          G11, G13
PROBLEM:         Engine 1's responsibility is split across `ingestion/`,
                 `storage/` and 5 orchestrator methods
                 (`_update_halt_state:5014` through `_verify_data_integrity:5379`).
                 Engine 2's feature checkpoint/restore is authored in the kernel
                 (`_restore_feature_snapshots:5423`,
                 `_checkpoint_feature_snapshots:5454`) against a store that is
                 always empty in the shipped configuration. Inv-8.
FILES:           src/feelies/kernel/orchestrator.py (7 methods)
                 src/feelies/ingestion/, src/feelies/features/
WHY THIS OWNER:  Phase 2 engine 1 owns wire-to-canonical translation, sequence
                 stamping, gap detection and validation, and resolves §F.3
                 session/halt state to engine 1. Engine 2 owns the state it
                 checkpoints.
REFACTOR PATH:   the common shape, engine 1 first. **G13's honest disposition:**
                 the checkpoint path is dead in the shipped configuration
                 because the store is always empty, so Phase 1 §5 flags it as a
                 removal candidate. This step **moves** it rather than removing
                 it, because removal is a behaviour decision belonging to S-31,
                 and moving dead code is reversible while deleting it is a
                 judgment about whether persistence is ever wired.
BLAST RADIUS:    boundary
VALIDATED BY:    S2, S12, S14, `symbol_halted`, the 5 engine-2 baselines, the
                 new `market_data_canonical` baseline from S-17, the oracle
PARITY IMPACT:   All 26 plus the new engine-1 baseline hold. Pure move. S-17
                 lands first specifically so this step has an engine-1 baseline
                 to be checked against — before S-17, an ingestion-side mistake
                 here is invisible until it moves a downstream hash.
DELETES:         7 methods from the orchestrator (118 -> 111)
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Orchestrator lines -~300.
ROLLBACK:        revert.
```

```
STEP:            S-21
CLOSES:          G21, G34
PROBLEM:         **36 direct store calls from the kernel** (`self._positions`
                 23, `self._strategy_positions` 13 — re-measured in
                 `gapscan.json:orchestrator.store_access`, with 34 and 20 bare
                 references respectively), plus 3 accounting methods in the
                 kernel (`_reconcile_fills:4229`,
                 `_distribute_fill_to_strategies:4577`,
                 `_record_fill_attribution:4057`) and a 4th in engine 5's
                 package (`src/feelies/alpha/fill_attribution.py`). §F.4 broker
                 reconciliation is 23 sites, 14 in the kernel. CORE §C.6 single
                 source of truth; Inv-8.
FILES:           src/feelies/kernel/orchestrator.py (3 methods, 36 call sites)
                 src/feelies/alpha/fill_attribution.py -> src/feelies/portfolio/
                 src/feelies/portfolio/strategy_position_store.py:145-148
                 src/feelies/portfolio/ (read-only view type)
WHY THIS OWNER:  Engine 7 is the sole book of record. Phase 2 makes the
                 enforcement concrete: **a read-only view type for every
                 consumer**, because "everything reads this; nothing else
                 computes it" is unenforceable through a mutable handle — and
                 that view is what makes S-05's substitution structurally
                 impossible rather than merely removed.
REFACTOR PATH:   the common shape, plus two specifics. (1) **Return an ordered
                 mapping from the store**: `:148` returns
                 `{sym: ... for sym in symbols}` over `symbols: set[str]`
                 (`:145`), whose key order is seed-dependent, and three
                 consumers currently neutralise it independently
                 (`src/feelies/kernel/orchestrator.py:2611`, `src/feelies/risk/basic_risk.py:764`,
                 `src/feelies/harness/backtest_report.py:193`). One line at the producer
                 retires an open defect three consumers carry. (2) Introduce the
                 read-only view before moving the 36 call sites, so the moves
                 land against the target surface.
BLAST RADIUS:    platform-wide by call-site count, boundary by behaviour.
                 **Justified early despite the reach**: S-05's P0 fix is
                 complete only when substitution is impossible, and 36 call
                 sites is the measure of how thoroughly the invariant is held by
                 coupling rather than by contract.
VALIDATED BY:    C2 (conservation identities at **every event**, not run end),
                 C5, X11, S12, `position_pnl`, `forced_exit_attribution`,
                 `halt_position_update`, R1 under a random seed, the oracle
PARITY IMPACT:   All 26 hold. The ordered-mapping change is the one to reason
                 about: it makes an order **deterministic** that three consumers
                 already sorted, so output is unchanged — **unless a fourth
                 consumer iterates unsorted**, which Phase 1 budget row 2a names
                 as the live risk. R1 under `PYTHONHASHSEED=random` is the test
                 that distinguishes "no fourth consumer" from "we did not look."
DELETES:         3 kernel accounting methods (111 -> 108); 36 direct store
                 calls; `src/feelies/alpha/fill_attribution.py` from engine 5's
                 package; the three independent sort-neutralisers at the
                 consumers
NET DELTA:       src modules 0 (one moves), public symbols **+1 -0** (the
                 read-only view; net +1 is a contract definition and is the one
                 §G.10-exempt addition in this wave), branch points 0.
                 Orchestrator lines -~250.
ROLLBACK:        revert. The read-only view disappears and the 36 call sites
                 return. Ship as its own release.
```

```
STEP:            S-22
CLOSES:          G22
PROBLEM:         Sizing, escalation and emergency flatten are in the kernel —
                 `_compute_target_quantity:2718`, `_escalate_risk:2530`,
                 `_emergency_flatten_all:2601`,
                 `_maybe_flip_buying_power_at_rth_close:782`. Risk policy cannot
                 be reviewed, tested or versioned as a unit. Inv-8; CORE §J.4
                 policy in mechanics.
FILES:           src/feelies/kernel/orchestrator.py (4 methods)
                 src/feelies/risk/
                 src/feelies/alpha/risk_wrapper.py -> src/feelies/risk/
WHY THIS OWNER:  Phase 2 engine 8 owns the veto and it is monotone: every path
                 yields `min(asked, permitted)`. That property is provable only
                 if every path is in one place. The per-alpha wrapper moves here
                 too — S-06 fixed its failure direction; this step fixes its
                 address.
REFACTOR PATH:   the common shape. Land X1 in this step, not earlier: X1 is a
                 property over the **enumerable** degradation set, and that
                 enumeration is the gate registry from S-11 plus this step's
                 consolidated ON-DEGRADED-INPUT table. Also land X2's
                 monotonicity property — for any input, permitted <= requested,
                 and `_compose_scaled_quantity` never produces a factor
                 exceeding either input's.
BLAST RADIUS:    boundary
VALIDATED BY:    X1, X2, X3 (from S-02, must still pass), X4, `risk_verdict`,
                 `level4_hazard_exit_order`, `decoupled_risk_flatten_order`,
                 the oracle
PARITY IMPACT:   All 26 hold. Pure move. **Note the two baselines that make this
                 step's boundary ambiguous:** `level4_hazard_exit_order` and
                 `decoupled_risk_flatten_order` are *orders*, so engine 8's
                 parity coverage today partly pins output that S-23 says belongs
                 to engine 9. They hold here and re-pin in S-23. That is the
                 declared sequence, not a surprise.
DELETES:         4 methods from the orchestrator (108 -> 104);
                 `src/feelies/alpha/risk_wrapper.py` from engine 5's package
NET DELTA:       src modules 0 (one moves), public symbols 0, branch points 0.
                 Orchestrator lines -~200.
ROLLBACK:        revert.
```

```
STEP:            S-23
CLOSES:          G19 (the `OrderRequest` clause)
PROBLEM:         `OrderRequest` carries **two jobs** — the outbound order of
                 hop 33 and the inbound de-risk command from four exit authors
                 in `risk/` — "disambiguated only by the free-text `reason`
                 field" (`src/feelies/core/events.py:290`). Publishers:
                 `src/feelies/risk/stop_exit.py:297`, `src/feelies/risk/hazard_exit.py:253`,
                 `src/feelies/risk/deferral_cap.py:378`, `src/feelies/risk/exit_composer.py:486`; re-entry at
                 `src/feelies/kernel/orchestrator.py:585` ->
                 `_on_bus_hazard_order:4919`. CORE §C.8 contract-first
                 boundaries: two meanings on one type distinguished by prose.
FILES:           src/feelies/core/events.py (DeRiskRequirement, new)
                 the four exit authors above
                 src/feelies/kernel/orchestrator.py:585, :4919 (delete)
                 src/feelies/risk/exit_composer.py, src/feelies/risk/sized_intent_orders.py
WHY THIS OWNER:  Phase 2 resolves it on engine 9's sheet: deciding *how* to
                 reduce — which legs, what urgency, what limit price, whether to
                 net against a pending order — is the same job engine 9 does for
                 entries, and doing it twice in two packages is *why* the type
                 carries two meanings. Engine 8 emits a requirement; engine 9
                 constructs the plan. **This removes a use rather than adding a
                 type**, and it collapses four independent engine-7 reads with
                 four independent staleness policies into one.
REFACTOR PATH:   (1) `DeRiskRequirement` on the envelope; (2) one author at a
                 time — convert `stop_exit` first, because the repo has already
                 done exactly this move for it and documented the result;
                 (3) engine 9 constructs the plan; (4) delete the inbound
                 `OrderRequest` path at `:585` -> `:4919`; (5) C4's discharge
                 identity: every requirement is discharged by named orders, or
                 outstanding, or emitted as dropped — no fourth outcome.
BLAST RADIUS:    platform-wide — a hot-path contract changes meaning
VALIDATED BY:    C4, X1, X2, X3, H4, and the four re-pinned baselines below
PARITY IMPACT:   **Four baselines break, and the repo has already run this
                 experiment.** `tests/determinism/test_orchestrator_replay.py:273-278`
                 documents the outcome of the earlier stop-exit decoupling: the
                 order hash moved (`source_layer` RISK where it was SIGNAL,
                 `strategy_id` `""` where it was `__stop_exit__`, and a new
                 content-derived order id from the new author), the
                 position-update hash moved "because the stop no longer draws
                 from the kernel's signal family", and the intent hash was
                 **unchanged** "which is the point." Expect the same three
                 outcomes for the remaining three authors:
                 `level4_hazard_exit_order` and `decoupled_risk_flatten_order`
                 re-pin because the author and the order id change;
                 `halt_order` and `symbol_halted` re-pin because the halt path
                 is engine 1/9 shared; `position_pnl` re-pins if a draw family
                 changes. **Re-pin one author per commit** so each moved hash
                 names its own cause. A batched re-pin of four baselines is
                 indistinguishable from a mistake.
                 After S-17a, the new DeRiskRequirement class adds a field set
                 and moves EXPECTED_MANIFEST_FINGERPRINT in addition to the
                 named replay hashes.
DELETES:         the inbound `OrderRequest` direction; `_on_bus_hazard_order`;
                 the bus re-entry at `:585`; four `OrderRequest` publishers
                 become requirement publishers; three redundant engine-7 read
                 paths with three staleness policies
NET DELTA:       src modules 0, public symbols **+1 -1 = 0** (`DeRiskRequirement`
                 added, `_on_bus_hazard_order` deleted), branch points **-1**
                 (the free-text `reason` disambiguation disappears).
ROLLBACK:        revert per author, restoring that author's baseline value from
                 git history in the same commit. Because each author is one
                 commit with one re-pin, rollback granularity equals re-pin
                 granularity — which is why (2) insists on one at a time.
```

```
STEP:            S-24
CLOSES:          G24
PROBLEM:         **9 of engine 9's methods sit in the kernel** —
                 `_plan_for_signal:2814`, `_try_build_order_from_intent:3278`,
                 `_resolve_order_route:3371`,
                 `_filter_portfolio_orders_for_admission:3505`,
                 `_execute_reverse:2984`, and the four cost-gate methods at
                 `:2184`, `:2226`, `:2266`, `:2295`. The most dispersed engine in
                 the platform; order-emission logic cannot be unit-tested without
                 constructing the orchestrator. Inv-8; CORE §J.1.
FILES:           src/feelies/kernel/orchestrator.py (9 methods)
                 src/feelies/execution/ (policy side only)
WHY THIS OWNER:  Engine 9 owns everything between "engine 8 permits X" and
                 "engine 10 has an order to work", including the
                 edge-versus-cost gate — a trade declined for insufficient edge
                 is an execution-policy decision, not a risk veto, and
                 conflating them makes the veto non-monotone in a way no test
                 would catch.
REFACTOR PATH:   the common shape. **Blocked on S-10** if
                 `SizedPositionIntent.target_positions`' unit is still
                 `undetermined`: `_compute_target_quantity` (engine 8) appears on
                 the SIGNAL path at hop 29 and at no hop on the PORTFOLIO path,
                 so if the portfolio path arrives pre-sized then engine 6 has
                 performed engine 8's job for that path and engine 8's
                 monotonicity guarantee covers half the platform. One field read
                 settles it and it must be settled before this step, not during.
BLAST RADIUS:    boundary
VALIDATED BY:    C4, X1, X6, S14, `level4_portfolio_order`, `halt_order`, the
                 oracle
PARITY IMPACT:   All 26 hold **given S-23 has already re-pinned the four order
                 baselines**. Pure move. If S-23 has not landed, this step and
                 S-23 will both move `halt_order` and the causes become
                 indistinguishable — which is the specific reason S-23 precedes
                 S-24 despite S-24 being the larger extraction.
DELETES:         9 methods from the orchestrator (104 -> 95)
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Orchestrator lines -~450.
ROLLBACK:        revert.
```

```
STEP:            S-25
CLOSES:          G27
PROBLEM:         **6 order-lifecycle transitions in the kernel** —
                 `_submit_tracked_order:3831`, `_poll_order_router_acks:3793`,
                 `_apply_ack_to_order:4103`, `_transition_order:4086`,
                 `_drain_async_fills:3936`, `cancel_order:3438`. Order state can
                 be advanced from two modules. Inv-8; Inv-9.
FILES:           src/feelies/kernel/orchestrator.py (6 methods)
                 src/feelies/execution/ (mechanics side)
WHY THIS OWNER:  Engine 10 owns the order state machine and the fact that its
                 transitions are **total**. Two modules advancing one state
                 machine is how a (state, event) pair goes undefined.
REFACTOR PATH:   the common shape, plus H4: every (state, event) pair defined,
                 unknown pairs **raise** rather than proceed — the same
                 discipline as the existing exhaustiveness guard at
                 `src/feelies/kernel/orchestrator.py:1984`, which "raises rather
                 than submitting" and is promoted here from behaviour to
                 contract.
BLAST RADIUS:    boundary
VALIDATED BY:    H4, H1 (must still pass), H2, `market_fill_acks`, `halt_ack`,
                 the oracle
PARITY IMPACT:   All 26 hold. Pure move. `cancel_order:3438` is the one to check:
                 Phase 2 records it as mechanics with **no measured policy
                 caller**, so if moving it changes anything, it had a caller
                 nobody found.
DELETES:         6 methods from the orchestrator (95 -> 89)
NET DELTA:       src modules 0, public symbols **-1** (`cancel_order` is public
                 on the orchestrator today and becomes engine-10-internal),
                 branch points 0. Orchestrator lines -~300.
ROLLBACK:        revert.
```

```
STEP:            S-26
CLOSES:          G15, G19 (the reducer clause)
PROBLEM:         Reducing N forecasts to one portfolio — engine 6's defining
                 responsibility — exists in **three places**: `composition/`,
                 `_select_bus_signal` in the kernel (def at
                 `src/feelies/kernel/orchestrator.py:4831`, tick-path call at
                 `:1676`), and `src/feelies/alpha/arbitration.py` in engine 5's
                 package. Three implementations of one rule and nothing asserts
                 they agree. CORE §C.6; Inv-8.
FILES:           src/feelies/kernel/orchestrator.py:4831, :1676
                 src/feelies/alpha/arbitration.py
                 src/feelies/composition/
                 tests/conformance/test_composition_identity.py (C6)
                 tests/conformance/fixtures/shape_adversarial/ (FIX-2 — required
                 by C6 and by A3 in S-29; Phase 6 §4.1 established that neither
                 existing fixture covers this role)
WHY THIS OWNER:  Phase 2 resolves it on engine 6's sheet with an argument rather
                 than an assertion: selecting one forecast from N and sizing it
                 **is** portfolio construction with a concentration constraint
                 of one. Treating it as a separate mechanism is what allowed it
                 to be implemented twice in two packages, neither of them engine
                 6's. Top-1 remains available as a **declared construction
                 policy**; it stops being the only reachable behaviour.
REFACTOR PATH:   (1) C6 asserting one reducer and the accounting identity —
                 contributors + exclusions == forecasts in scope at the
                 boundary, with a reason on every exclusion; (2) top-1 as a
                 configured policy in `composition/`; (3) repoint the tick path
                 at `:1676`; (4) delete `_select_bus_signal` and
                 `src/feelies/alpha/arbitration.py`; (5) **publish** the losing
                 forecasts in an arbitration record — today they are only traced
                 (`_trace_buffered_signals_arbitration:638`), and a discarded
                 forecast that appears in no contract cannot be attributed
                 against.
BLAST RADIUS:    platform-wide — the SIGNAL path's reduction point moves
VALIDATED BY:    C6, C4, A3, the four engine-6 baselines, `level2_signal`,
                 `signal_fires`, the oracle, and R1 under a random seed
PARITY IMPACT:   **Expected to hold at A=1 and this is the step's honest
                 weakness.** With one alpha the reduction is an identity, so
                 three implementations cannot disagree and the baselines cannot
                 distinguish a correct consolidation from a broken one. Phase 5
                 states it directly for G15: "With A=1 the reduction is an
                 identity and cannot be wrong." **The step is therefore not
                 validated by the oracle** — it is validated by C6's accounting
                 identity plus FIX-2 (a second, differently-shaped alpha), which
                 is why FIX-2 is a precondition here and not merely a wave-4
                 nicety. Shipping S-26 without FIX-2 ships an untested
                 consolidation with a green oracle.
DELETES:         `_select_bus_signal` from the orchestrator (89 -> 88);
                 `src/feelies/alpha/arbitration.py` (**a module deleted**);
                 two of three reducer implementations
NET DELTA:       src modules **-1**, public symbols **-1**, branch points 0.
ROLLBACK:        revert. Both deleted implementations return from git history.
```

```
STEP:            S-27
CLOSES:          G18, G30 (the authority clause)
PROBLEM:         The `LIVE -> QUARANTINED` transition is written from
                 **engine-12 code** at
                 `src/feelies/forensics/cost_circuit_breaker.py:159`. Demotion
                 always commits, which is the exposure-reducing direction, so
                 the safety outcome is correct and only the authority boundary is
                 violated. CORE §C.6 single source of truth.
FILES:           src/feelies/forensics/cost_circuit_breaker.py:159
                 src/feelies/promotion/lifecycle.py
                 tests/conformance/test_cold_engines.py (A2)
WHY THIS OWNER:  Phase 2: a closed loop is a decision **driven by** forensics,
                 not a write **performed by** forensics. Engine 12 emits
                 evidence and a recommendation; engine 5 performs the
                 transition. Same output, one writer, and it survives a second
                 forensic input arriving later — which the current shape does
                 not.
REFACTOR PATH:   (1) A2 asserting **both** halves of CORE §C.10 — zero reads
                 under instrumentation *and* no import edge; it passes on reads
                 today and fails on imports, and Phase 6 warns that asserting
                 only one makes the invariant read as satisfied; (2) engine 12
                 emits a quarantine recommendation with its evidence reference;
                 (3) engine 5 performs the transition and records actor, reason
                 and evidence reference on the ledger; (4) delete the
                 cross-engine write.
BLAST RADIUS:    boundary — cold path only; nothing in flight
VALIDATED BY:    A2, S2 (from S-04), the promotion ledger's append-only
                 property, and a test that **demotion still always commits** —
                 the safety outcome must not regress while the authority moves
PARITY IMPACT:   All 26 hold. Cold path, no sequence draw, no hashed field.
                 Engine 5's outputs are outside the manifest entirely (Phase 1
                 §6.1 records no manifest entry for engine 5), which is exactly
                 why this step needs a behavioural test rather than a hash.
DELETES:         the cross-engine state write at
                 `src/feelies/forensics/cost_circuit_breaker.py:159`; one of the two writers to the
                 lifecycle state machine
NET DELTA:       src modules 0, public symbols +1 -1 = 0 (recommendation
                 contract added, cross-engine write path removed), branch
                 points **-2** (two of the seven non-bootstrap mode branches are
                 in `src/feelies/forensics/cost_circuit_breaker.py` at `:63` and `:172`; this step
                 removes them or moves them to the composition root — see S-28).
ROLLBACK:        revert.
```

```
STEP:            S-28
CLOSES:          G26
PROBLEM:         27 mode branches, **all outside `execution/` and `broker/`** —
                 and zero inside, so the seam itself is clean and the platform
                 routes around it. 20 are in `src/feelies/bootstrap.py`, which
                 is the composition root choosing the seam and is where mode
                 branching belongs. **The 7 outside bootstrap are the gap**:
                 `src/feelies/core/platform_config.py:58,:447`,
                 `src/feelies/forensics/cost_circuit_breaker.py:63,:172`,
                 `src/feelies/harness/backtest_prep.py:141`,
                 `src/feelies/harness/backtest_runner.py:190`,
                 `src/feelies/promotion/lifecycle.py:570`
                 (`VERIFIED`, `gapscan.json:mode_branches.sites`, enumerated
                 this session). Inv-9 backtest/live parity; CORE §C.4.
FILES:           the 7 sites above
                 tests/conformance/test_mode_seam.py (S7 — authored in S-03;
                 this step drops its xfail)
                 tests/conformance/test_mode_parity.py (H3, new)
WHY THIS OWNER:  Phase 2 engine 10 draws the line: **composition-root selection
                 is legitimate, in-engine mode branching is not.** Those are
                 different things and the 27 must be split on that line before
                 any is called a defect.
REFACTOR PATH:   (1) S7 with the composition-root exemption as an **explicit
                 allowlist** rather than a hard-coded `{execution, broker}` set;
                 (2) each of the 7 moved to the composition root or removed, one
                 per commit; (3) H3 asserting backend substitution changes the
                 construction at the composition root and nothing else.
BLAST RADIUS:    boundary
VALIDATED BY:    S7, H3, H1, the oracle, and `src/feelies/bootstrap.py:203`'s
                 `enforce_market_order = config.mode != OperatingMode.PAPER` —
                 Phase 1's open defect on silent reordering, which stays in
                 bootstrap and must be **declared** there rather than moved
PARITY IMPACT:   hold — all 26 baselines, conditional on each of the 7 moves
                 being behaviour-preserving.
                 All 26 hold if each move is behaviour-preserving.
                 `src/feelies/harness/backtest_prep.py:141` and `src/feelies/harness/backtest_runner.py:190` are on the
                 oracle's own path, so a mistake there breaks the oracle
                 immediately — which makes them the safest two to move and the
                 right two to move first.
DELETES:         7 in-engine mode branches
NET DELTA:       src modules 0, public symbols 0, branch points **-7**.
                 Test files +2.
ROLLBACK:        revert per site.
```

```
STEP:            S-29
CLOSES:          G25
PROBLEM:         `src/feelies/core/platform_config.py` names an alpha as a
                 default value: `moc_strategy_ids: tuple[str, ...] =
                 ("sig_moc_imbalance_v1",)` at `:108` (read this session),
                 repeated at `:910`. It reaches `_moc_strategy_ids` at
                 `src/feelies/kernel/orchestrator.py:876`, is tested at `:3386`
                 to set `OrderRequest.is_moc`, and thereby diverts the order
                 from the continuous book to the closing auction. **No file
                 under `configs/` or `platform.yaml` sets it, so every
                 deployment inherits the hardcoded default.** Inv-6
                 alpha-agnosticism; CORE §C.7, §I.
FILES:           src/feelies/core/platform_config.py:108, :910
                 src/feelies/kernel/orchestrator.py:876, :3386
                 alphas/ (manifest declaration of the routing property)
WHY THIS OWNER:  Route selection is engine 9 policy. A route selected by a
                 string literal in platform config is that policy expressed as
                 an identity check. The target is **route-by-declared-property**
                 — an order's route follows from urgency, style and session, all
                 of which an alpha's manifest may declare — never from
                 membership in a hardcoded ID list.
REFACTOR PATH:   (1) A3 asserting attachment costs zero core edits, and S3 from
                 S-03 already asserting no alpha literal; (2) the routing
                 property on the manifest; (3) `_resolve_order_route` reads the
                 property; (4) default `moc_strategy_ids` to `()` and then
                 delete the field. **Open question this step must answer first:**
                 whether `_resolve_order_route:3371` has any input other than
                 `_moc_strategy_ids` — it decides whether this is a one-line
                 default change plus a config contract, or a route-policy design.
BLAST RADIUS:    boundary
VALIDATED BY:    S3, A3, `level4_portfolio_order`, `halt_order`, the oracle
PARITY IMPACT:   Expected to hold. `sig_moc_imbalance_v1` is not the APP
                 baseline's alpha, so no baseline order should currently carry
                 `is_moc=True` from this default. `INFERRED` — the step must
                 confirm by scanning the baseline fixtures for that
                 `strategy_id` **before** changing the default. If a fixture does
                 use it, `level4_portfolio_order` and `market_fill_acks` re-pin
                 and the reason is that an order moves from the closing auction
                 to the continuous book, which is a behaviour change and must be
                 stated as one.
DELETES:         the platform's **only** alpha-id leak into core; the
                 `moc_strategy_ids` field; one identity-check branch
NET DELTA:       src modules 0, public symbols **-1**, branch points **-1**.
                 Test files +1.
ROLLBACK:        revert; the default returns.
```

```
STEP:            S-30
CLOSES:          G31, G32, G33, G35, G36
PROBLEM:         Five §F responsibilities with no single owner. G31 universe:
                 **200 sites across 11 packages**, so every layer forms its own
                 view and disagreement between them is undetectable. G32 symbol
                 identity: **3 sites**, no CUSIP/FIGI mapping, no
                 corporate-action handling — unimplemented rather than
                 misplaced. G33 session/halt: 165 sites across 9 packages. G35
                 backpressure: 4 sites, no queue-depth or drop policy. G36
                 exception propagation: 20 fail-quiet handlers, of which S-05 and
                 S-06 removed the two on decision paths, leaving 18 on cold or
                 benign paths. Inv-11; Inv-8; CORE §J.5.
FILES:           src/feelies/alpha/ (universe, §F.1 -> engine 5)
                 src/feelies/portfolio/ (symbol identity, §F.2 -> engine 7)
                 src/feelies/ingestion/ (session/halt, §F.3 -> engine 1;
                 backpressure ingress, §F.6 -> engine 1)
                 src/feelies/kernel/ (exception taxonomy, §F.5 -> Kernel)
                 src/feelies/monitoring/ (budget-breach shedding, §F.6 -> engine 11)
                 src/feelies/sensors/ (horizon grid, §F.8 -> engine 2)
                 src/feelies/composition/, src/feelies/features/ (§F.8
                 consumers: the private grid views these two hold)
WHY THIS OWNER:  Phase 2 resolves all six and this step only implements the
                 resolutions: §F.1 and §F.2 to engine 5 and engine 7
                 respectively, §F.3 to engine 1, §F.5 to the Kernel, §F.6 split
                 between engine 1 (ingress shedding) and engine 11 (budget
                 breach — already landed in S-07), and **§F.8 to engine 2**.
                 §F.8 was resolved in X1 as an addendum to Phase 2 rather than
                 by Phase 2 itself, on that phase's own uncontested
                 recommendation; it lands here because this is where §F is
                 implemented, and because it is structurally identical to §F.1
                 — both are frozen composition-time artifacts hashed into the
                 run fingerprint.
REFACTOR PATH:   **Ship as six independent commits, one per §F item**, in this
                 order: §F.5 exception taxonomy first (every other step's ON
                 EXCEPTION clause assumes one exists to fail into), then §F.3,
                 §F.1, **§F.8**, §F.6 ingress, §F.2 last. §F.8 must follow §F.3
                 because the grid's anchor is the session open §F.3 assigns to
                 engine 1, and it follows §F.1 so the `UniverseSnapshot`
                 pattern is already in place to copy. **G32 is the only gap in
                 the plan that is net-new capability rather than remediation**
                 — no symbol-identity handling exists to move — so it is the
                 one candidate for deferral if scope must be cut; see G.9.
BLAST RADIUS:    platform-wide for §F.1 and §F.3 by site count; boundary for the
                 rest, §F.8 included (three holders across three packages)
VALIDATED BY:    C2, C3, X1, X6, X7, S6, S14, the oracle. **G31 and G32 have no
                 Phase 6 test (G.0.4)**, so this step must author its own gates
                 and register them in S-01's registry, or S1 stays xfailed.
                 §F.8 has no Phase 6 test either and authors one: an AST scan
                 asserting no module outside engine 2 holds a sorted horizon
                 collection, on the pattern of
                 `tests/acceptance/test_no_walltime_outside_clock.py:72`.
PARITY IMPACT:   hold — all 26 baselines. This step pre-authorises no re-pin
                 and G.7 does not schedule one for it, so a moved baseline is
                 an undeclared change: stop the line under CORE-EXEC §D.2 and
                 hand the disagreement to the operator.
                 §F.5, §F.6 and §F.2 hold — taxonomy, policy and net-new
                 capability, none of which changes a draw or a hashed field.
                 §F.1 and §F.3 are the risk: consolidating 200 and 165 sites
                 onto one authority will change behaviour anywhere the current
                 views **disagree**, and a disagreement is precisely what is
                 undetectable today. Expect at most one baseline to move per §F
                 item; a moved baseline here is a discovered disagreement, which
                 is the finding, not the failure. One commit per item so the
                 cause is nameable.
                 **§F.8 holds, and its acceptance condition is not the hashes.**
                 The grid is composition-time data that enters no hash helper's
                 field list, so by Phase 1 §8's table the oracle is blind to it
                 — the same property as `schema_version` under §F.7. Accept
                 §F.8 on the removal of the three private views, not on a green
                 suite: if `_horizons_sorted`, `_signal_horizons_sorted` and the
                 composition-root derivation survive the commit, the contract
                 was added without removing what it replaced and the
                 disagreement it exists to prevent is still possible. It is
                 also the one §F item here that could move a baseline for a
                 *benign* reason — publishing one ordered grid where three
                 independently sorted views existed changes nothing only if
                 they already agreed, which is the same discovered-disagreement
                 case as §F.1.
DELETES:         199 of 200 universe definition points; 164 of 165 session/halt
                 authorities; up to 18 fail-quiet handlers (18 -> 0); the three
                 private horizon-grid views (`horizon_scheduler.py:97`,
                 `synchronizer.py:74`, and the `_composition_signal_horizons`
                 derivation at `bootstrap.py:1471`)
NET DELTA:       src modules **+2** (symbol identity, exception taxonomy),
                 public symbols +5 (+4, plus `HorizonGrid` declared in an
                 existing engine-2 module — §K.5 rules §F.8 a contract to
                 declare, not a capability to build, so it adds no module),
                 branch points **-18** (fail-quiet handlers).
ROLLBACK:        revert per §F item. §F.2's revert is trivial (nothing depended
                 on it); §F.1's is the hardest in the plan. §F.8's is cheap —
                 restore the three private views — which is the other reason it
                 is safe to carry in the plan's widest step.
```

---

### G.5 Wave E — cost and retirement

**Must be net-negative.** This is the wave that pays back §G.10, and it is last
because every step in it is `platform-wide` and none is a P0.

```
STEP:            S-31
CLOSES:          G44, G10 (the residual)
PROBLEM:         **~12.8 µs/quote (9.4%) provably unread** — 20 unread event
                 fields of 179, 2 unread metric names of 9, 106 public methods
                 with zero in-src call sites of 564 — led by **7.2 µs/quote
                 publishing `StateTransition` to zero subscribers**. CORE §G.10
                 justified net complexity. **The 106 is a measurement, not a
                 deletion list.** A5.4 closed **FALSE** in X1 — see REFACTOR
                 PATH (3) and NET DELTA.
FILES:           src/feelies/kernel/orchestrator.py:4694-4707
                 (`_emit_state_transition`)
                 src/feelies/core/events.py:344 (`StateTransition`)
                 tests/determinism/parity_manifest.py:183 (`state_transition`)
                 the 20 unread fields, 2 unread metrics, and the verified-dead
                 method set the coverage gate admits
WHY THIS OWNER:  Engine 11 owns observability. `StateTransition`'s docstring
                 promise — "Logged whenever any state machine transitions. No
                 silent transitions" (`src/feelies/core/events.py:345`) — is
                 worth keeping; publishing it on the **domain** bus to zero
                 subscribers is not. It becomes a record on engine 11's
                 notification channel.
REFACTOR PATH:   **This step corrects Phase 5's own claim about itself and that
                 is the first thing to state.** Phase 5 G44 says removing dead
                 compute "changes nothing computed, so the parity hash must not
                 move — each item is independently verifiable against the
                 oracle." That is **false for its largest item.**
                 `_emit_state_transition` publishes with
                 `sequence=self._seq.next()` (`:4700`, read this session) at
                 8.007 transitions per quote, so deleting the publish removes
                 ~8 draws per quote from the shared kernel generator and shifts
                 every later event on every tick.
                 Path: (1) the 20 fields, 2 metrics and the verified-dead
                 methods first, one category per commit, each verified against
                 the oracle — those genuinely do not move a hash; (2)
                 `StateTransition` **last and alone**, as the
                 notification-channel move plus a declared re-pin; (3) **A5.4
                 is closed and it is FALSE — the method deletion is rescoped
                 and gated.** X1 cross-referenced `tests/`, `scripts/`,
                 `tools/`, `alphas/`, `configs/` and string-literal dispatch:
                 of the 106, **82 are called from `tests/` alone** and only
                 13 are reached by nothing. Two independent static passes
                 disagreed in both directions (13 vs 16) on same-name receiver
                 collisions, which is why the residue is settled empirically
                 rather than by a third search. **Gate:** run the full suite
                 under `coverage` with branch data and delete only methods the
                 run proves unexecuted; then replay the APP oracle. A method
                 the gate cannot reach but that is *documented* as an
                 extension point is **not** deletable — `FeatureComputation.
                 update_trade` (`alphas/SCHEMA.md:78`) is the worked example,
                 and coverage cannot see it because nothing implements the
                 optional hook today.
BLAST RADIUS:    platform-wide (step 2); local per commit for step 1
VALIDATED BY:    S5, S11, C1, the oracle, the coverage gate above, and Phase
                 4's per-quote measurement re-run to confirm the ~12.8 µs is
                 actually recovered — a deletion that does not move the number
                 deleted the wrong thing. Note the corrected expectation: the
                 method deletion recovers ~0 µs because an uncalled method
                 costs nothing per quote, so the recovered time is
                 attributable to `StateTransition` and the unread fields.
PARITY IMPACT:   break — step 2 only; step 1 holds all 26. Step 2 deletes
                 EXPECTED_STATE_TRANSITION_HASH and
                 EXPECTED_STATE_TRANSITION_COUNT from the manifest, and re-pins
                 EXPECTED_LEVEL2_SIGNAL_HASH, EXPECTED_SIGNAL_FIRES_HASH,
                 EXPECTED_LEVEL3_INTENT_DECAY_OFF_HASH,
                 EXPECTED_LEVEL3_INTENT_DECAY_ON_HASH,
                 EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH,
                 EXPECTED_POSITION_PNL_HASH, EXPECTED_RISK_VERDICT_HASH and
                 _BASELINE_TRADE_PARITY_HASH. No COUNT constant is declared to
                 move; one that does is an unpredicted event-count change and
                 remains a stop.
                 **Step 1: all 26 hold, per item, and that is the acceptance
                 test.** Step 2: the `state_transition` baseline does not re-pin,
                 it is **deleted from the manifest** (26 -> 25, or 27 -> 28 after
                 S-17's additions), because with the publish gone the stream has
                 zero events and there is nothing to hash. Every baseline whose
                 events draw from `self._seq` after a transition re-pins:
                 expect `level2_signal`, `signal_fires`,
                 `level3_sized_intent_*`, `level4_portfolio_order`,
                 `position_pnl`, `risk_verdict` and the trade parity hash to
                 move. **The rejected alternative, stated:** draw the sequence
                 and discard it, keeping every hash intact. Rejected because 8
                 phantom draws per quote whose only purpose is to satisfy an
                 oracle is precisely the dead work being removed, and §G.10
                 would not permit it.
                 After S-17a, step 1's 20 unread-field deletions also move
                 EXPECTED_MANIFEST_FINGERPRINT. The "all baselines hold" line
                 above predates S-17a and covers replay hashes only.
DELETES:         `_emit_state_transition`; the `StateTransition` domain-bus
                 publish; 20 unread event fields; 2 unread metric names; **up
                 to 12 verified-dead public methods** (13 measured, less
                 `FeatureComputation.update_trade`, which is a documented
                 author hook); the `state_transition` manifest entry.
                 **~12.8 µs/quote, 9.4% of measured tick cost.**
NET DELTA:       src modules 0, public symbols **-12** (was **-106**; A5.4
                 closed FALSE in X1 and the step is rescoped — the coverage
                 gate may reduce this further, never increase it),
                 branch points 0, manifest entries **-1**.
                 Orchestrator lines -~15 plus the field removals.
                 **Three of the 12 are documented contract surfaces, not
                 plain dead code, and each needs an explicit call rather than
                 a mechanical deletion:** `CostArithmetic.
                 declared_round_trip_cost_bps` (the Inv-12 disclosure
                 accessor) and the `AlphaBudgetRiskWrapper.
                 checkpoint_risk_state` / `restore_risk_state` pair (which
                 §J.2 already reasons about).
ROLLBACK:        revert per commit. Step 2's revert must restore the
                 `state_transition` baseline value and every re-pinned hash from
                 git history in one commit — which is why step 2 is alone in its
                 commit.
```

```
STEP:            S-32
CLOSES:          G45, G01, G08 (residual)
PROBLEM:         Hot-path prohibitions violated with PROVEN per-event
                 occurrences: per-event dict construction 3, string formatting
                 3, wall-clock read 3, dynamic dispatch 2, per-event set
                 construction 2, plus `dataclass_replace` at 5 per-event sites.
                 12 of 18 clock reads in tick-critical packages are absent from
                 the allowlist and 5 of the 22 allowlist entries are not clock
                 reads at all. 5 unsorted set iterations on the tick path, none
                 order-sensitive today. CORE §G measured budget; Inv-1; Inv-10.
FILES:           the sites in `hotpath.json`'s prohibition table
                 `src/feelies/monitoring/in_memory.py:74` (f-string metric key)
                 `src/feelies/composition/synchronizer.py:80,83`
                 `src/feelies/kernel/orchestrator.py:2938`
                 `src/feelies/portfolio/strategy_position_store.py:148`
                 `src/feelies/signals/regime_gate.py:555`
WHY THIS OWNER:  Phase 4 §1's allow list is a platform-wide contract, not an
                 engine's. Each violation is owned by the engine whose hot path
                 it sits on.
REFACTOR PATH:   one prohibition class per commit, cheapest first: the f-string
                 metric key (pre-allocate the dict at construction, per Phase 4
                 §7), then dict/set construction, then `dataclass_replace`, then
                 dynamic dispatch. The 3 wall-clock reads are the residual of
                 G01 after S-03 made the allowlist call-granular.
                 `src/feelies/portfolio/strategy_position_store.py:148` is already fixed by S-21's
                 ordered mapping — do not fix it twice.
BLAST RADIUS:    platform-wide by reach; each commit is local
VALIDATED BY:    S4, S5, R1 under a random seed, R8, the oracle, and a re-run of
                 Phase 4's per-quote measurement per commit
PARITY IMPACT:   All baselines must hold, per commit — these are cost changes,
                 not behaviour changes. **Two exceptions to check rather than
                 assume:** sorting a currently-unsorted iteration changes output
                 if the container's order was load-bearing (Phase 5 rates 3 of
                 the 5 sites order-insensitive by reading, which A5.2 records as
                 unenforced), and pre-allocating a metric key dict changes the
                 metric stream's construction order. Neither should move a hash;
                 if either does, A5.2 was wrong and that is the finding.
DELETES:         13 unconditional per-event prohibited operations; 5 stale clock
                 allowlist entries; 5 unsorted tick-path set iterations
NET DELTA:       src modules 0, public symbols 0, branch points 0.
                 Measured cost: the target is the residual of the 136.2 µs after
                 S-31's 12.8 µs — this step should be measured, not projected.
ROLLBACK:        revert per commit.
```

```
STEP:            S-33
CLOSES:          G42, G41
PROBLEM:         Engine 2 is **6.1× over its budget share**, and each additional
                 sensor costs **+22.6 µs/quote — 70% of the entire per-quote
                 budget for one sensor**. Engine 2 alone reaches ~277 µs at full
                 registration, and the whole platform 335 µs/quote — 10.5× the
                 32 µs/quote target. This is the single dominant cost and it
                 grows linearly with the thing the platform exists to add. CORE
                 §G; Inv-12 stress viability.
FILES:           src/feelies/sensors/registry.py
                 src/feelies/features/
WHY THIS OWNER:  Engine 2 owns sensor fan-out and horizon aggregation.
REFACTOR PATH:   **Measure before optimising, and the measurement does not
                 exist yet.** Phase 4 A4.5 records that the 22.6 µs/quote figure
                 is an average over 9 added sensors, not per sensor, and names
                 the missing evidence: per-sensor probes at full registration,
                 for which `--mode sensorscale` already installs the arming
                 hook. (1) per-sensor probes; (2) attack the dominant term the
                 probes name; (3) re-measure after each change; (4) X10's budget
                 from S-07 now has a number engine 2 can be held to.
BLAST RADIUS:    platform-wide — engine 2 is on every quote
VALIDATED BY:    S5, X10, the 5 engine-2 baselines, the oracle, and A5.6's
                 replay with two SIGNAL alphas registered
PARITY IMPACT:   All 26 must hold. Engine 2 holds 5 baselines and is the
                 best-pinned engine in the platform, which makes it the safest
                 place in the plan to change hot-path code — the oracle sees
                 almost everything engine 2 does.
DELETES:         to be determined by the probes. **A step whose DELETES cannot
                 be named before measuring is a step that must measure first**,
                 which is why (1) is a probe and not an optimisation.
NET DELTA:       unknown before (1). Declared as a projection of **0 modules, 0
                 public symbols, 0 branch points** with cost as the only
                 intended delta; if (1) shows otherwise, this step is re-planned
                 rather than stretched.
ROLLBACK:        revert per commit.
```

```
STEP:            S-34
CLOSES:          G40
PROBLEM:         `Orchestrator` is **5,480 lines, 123 methods (22 public), 104
                 `__init__` attributes**, and hosts responsibilities of engines
                 1, 2, 3, 4, 6, 7, 8, 9, 10 and 12. CORE §J.1 god orchestrator;
                 Inv-8. Phase 5 lists it separately from G11-G30 because
                 "shrink the orchestrator" is distinct work from any single
                 extraction.
FILES:           src/feelies/kernel/orchestrator.py
WHY THIS OWNER:  Phase 3 §B fixes what remains in Tier 1: **dispatch,
                 sequencing, the clock, the state-machine framework, the
                 exception taxonomy and the schema gate.** Everything else has
                 been claimed by an engine sheet, so this step has no
                 destinations left to decide — it is the residual after S-19
                 through S-30.
REFACTOR PATH:   (1) confirm the count: after S-19 (-5), S-20 (-7), S-21 (-3),
                 S-22 (-4), S-24 (-9), S-25 (-6), S-26 (-1), the projection is
                 **123 -> 88 methods**, ~35 moved. (2) The 104 `__init__`
                 attributes are the real measure and no step above reduces them
                 directly — they fall out of S-12's constructor injection and
                 S-15's reset declarations. Re-measure them here rather than
                 assuming. (3) Whatever remains outside the six Tier-1
                 responsibilities is either an undiscovered engine
                 responsibility or genuine mechanism; **classify it, do not move
                 it**, and open a step per finding.
BLAST RADIUS:    platform-wide
VALIDATED BY:    S2, S12, S14, S17, all baselines, the oracle, and
                 `gapscan.json:orchestrator` re-run to confirm the counts
PARITY IMPACT:   All baselines hold — by this point every behavioural change has
                 already shipped and re-pinned in an earlier step. **If a
                 baseline moves here, an earlier step was incomplete**, and this
                 step's value is largely that it is the detector for exactly
                 that.
DELETES:         ~35 methods from the orchestrator; the god-orchestrator
                 anti-pattern
NET DELTA:       src modules 0, public symbols **-14** (22 public methods -> the
                 8 the six Tier-1 responsibilities need; `INFERRED`),
                 branch points 0. Orchestrator lines **-1,700 projected**.
ROLLBACK:        this step is a classification and a residual cleanup; revert per
                 commit. It has no single revert because it has no single change.
```

---

### G.6 Running net-delta ledger

Baseline: **196 modules, 551 public symbols, 356 branch points** (7 non-bootstrap
mode branches + 20 fail-quiet handlers + 329 runtime gate sites),
`src/feelies/` only. Test files are tracked separately because §G.10 exempts
conformance tests. **Every figure is an `INFERRED` projection** — see G.0.2 for
the reconciliation requirement.

| Step | Δ mod | Δ sym | Δ branch | Running mod | Running sym | Running branch | Δ test files |
|---|---|---|---|---|---|---|---|
| baseline | — | — | — | 196 | 551 | 356 | — |
| S-01 | 0 | 0 | 0 | 196 | 551 | 356 | +6 |
| S-02 | 0 | 0 | 0 | 196 | 551 | 356 | +2 |
| S-03 | 0 | 0 | 0 | 196 | 551 | 356 | +13 |
| S-04 | 0 | 0 | 0 | 196 | 551 | 356 | +1 |
| **wave A** | **0** | **0** | **0** | **196** | **551** | **356** | **+22** |
| S-05 | 0 | 0 | −1 | 196 | 551 | 355 | +1 |
| S-06 | 0 | 0 | 0 | 196 | 551 | 355 | +3 |
| S-07 | +1 | +2 | +2 | 197 | 553 | 357 | +1 |
| S-08 | +1 | +2 | +1 | 198 | 555 | 358 | +2 |
| **wave B** | **+2** | **+4** | **+2** | **198** | **555** | **358** | **+7** |
| S-09 | 0 | +1 | +1 | 198 | 556 | 359 | +2 |
| S-10 | 0 | +1 | 0 | 198 | 557 | 359 | +1 |
| S-11 | +1 | +2 | 0 | 199 | 559 | 359 | +1 |
| S-11a | 0 | +1 | 0 | 199 | 560 | 359 | 0 |
| S-12 | +1 | +1 | +1 | 200 | 561 | 360 | +4 |
| S-13 | +1 | +1 | 0 | 201 | 562 | 360 | +1 |
| S-14 | +1 | +1 | 0 | 202 | 563 | 360 | +1 |
| S-15 | 0 | +32 | 0 | 202 | 595 | 360 | +1 |
| S-16 | 0 | +1 | 0 | 202 | 596 | 360 | +1 |
| S-17 | 0 | 0 | 0 | 202 | 596 | 360 | 0 |
| S-18 | 0 | 0 | 0 | 202 | 596 | 360 | 0 |
| **wave C** | **+4** | **+41** | **+2** | **202** | **596** | **360** | **+12** |
| S-19 | 0 | 0 | 0 | 202 | 596 | 360 | 0 |
| S-20 | 0 | 0 | 0 | 202 | 596 | 360 | 0 |
| S-21 | 0 | +1 | 0 | 202 | 597 | 360 | 0 |
| S-22 | 0 | 0 | 0 | 202 | 597 | 360 | +2 |
| S-23 | 0 | 0 | −1 | 202 | 597 | 359 | +1 |
| S-24 | 0 | 0 | 0 | 202 | 597 | 359 | 0 |
| S-25 | 0 | −1 | 0 | 202 | 596 | 359 | +1 |
| S-26 | −1 | −1 | 0 | 201 | 595 | 359 | +2 |
| S-27 | 0 | 0 | −2 | 201 | 595 | 357 | +1 |
| S-28 | 0 | 0 | −7 | 201 | 595 | 350 | +1 |
| S-29 | 0 | −1 | −1 | 201 | 594 | 349 | +1 |
| S-30 | +2 | +5 | −18 | 203 | 599 | 331 | +1 |
| **wave D** | **+1** | **+3** | **−29** | **203** | **599** | **331** | **+10** |
| S-31 | 0 | −12 | 0 | 203 | 587 | 331 | 0 |
| S-32 | 0 | 0 | 0 | 203 | 587 | 331 | 0 |
| S-33 | 0 | 0 | 0 | 203 | 587 | 331 | 0 |
| S-34 | 0 | −14 | 0 | 203 | 573 | 331 | 0 |
| **wave E** | **0** | **−26** | **0** | **203** | **573** | **331** | **0** |
| **whole plan** | **+7** | **+22** | **−25** | **203** | **573** | **331** | **+51** |

**The S-31 row was −106 and is now −12** (X1, A5.4 closed FALSE). Every figure
downstream of it in this table moved by +94, and the whole-plan symbol column
changed sign. The pre-amendment row is kept here rather than in git history
alone because §G.6's purpose is to be argued against, and the argument changed:
`| S-31 | 0 | −106 | 0 | 203 | 492 | 331 | 0 |`, giving wave E −120 and the
whole plan −73.

**The test-file column is measured, not projected.** Phase 6's 50 tests resolve
to **49 distinct paths — 45 new test modules and 4 existing files extended**
(`.github/workflows/ci.yml` for R1,
`tests/acceptance/test_no_walltime_outside_clock.py` for S4,
`tests/determinism/test_parity_manifest.py` for R9,
`tests/execution/test_router_fill_timing_parity.py` for H1); S6 and X7 share one
file, which is why 50 tests need 49 paths (`VERIFIED`, computed from
`tools/arch/evidence/p7_index.json`). Adding the 6 support files — the gap
registry, FIX-1 to FIX-3, HARN-1 and HARN-2 — gives the **+51** in the last
column. Six steps show `0` because the test they author was already given a file
by an earlier step.

**Reading the ledger against §G.10.** Net across the plan: **+7 modules, +22
public symbols, −25 branch points**, plus 51 files under `tests/` which §G.10
exempts. Three things in it deserve to be argued rather than tabulated:

1. **Modules go up by 7 and every one is a contract or a P0 fix.** The durable
   journal and `LatencyBreach` (P0, S-07/S-08); the gate registry, wiring
   manifest, sequence registry and forbidden-reads matrix (contract definitions,
   S-11 to S-14); symbol identity and the exception taxonomy (S-30). Wave D nets
   +1 module only because S-26 deletes `src/feelies/alpha/arbitration.py` and S-30 adds two.
2. **Public symbols rise by 21, and the sensitivity this note used to describe
   as hypothetical has fired.** The original note read: "Public symbols fall by
   73, and −106 of that is one step… **if A5.4 is wrong the plan's headline
   net-negative disappears**: without S-31 the plan is +33 public symbols."
   **A5.4 was wrong.** X1 closed it FALSE — of the 106 methods with no in-`src/`
   call site, 82 are called from `tests/` and only 13 are reached by nothing —
   so S-31 is rescoped from −106 to −12 and the plan nets **+22 public symbols**.
   The largest single contributor is now S-15's 32 `reset()` methods.

   **What this does and does not break.** §G.10's rule is per-category, not
   per-plan: waves A, B and C may increase, and waves D and E must not. Wave E
   is still net-negative (−26) and wave D is unchanged, so **the plan still
   satisfies §G.10 as written**. What it loses is the rhetorical claim of an
   overall net-negative, which was never §G.10's test — it was this plan's own
   framing, and it rested one assumption deep on a static measure that was
   never a deletion list. The honest statement is that the plan buys −25 branch
   points and 51 conformance tests at a cost of +7 modules and +22 public
   symbols, and that trade must be argued on its merits rather than on a
   headline.
3. **Branch points fall by 25 and the plan never adds an unenumerable one.** The
   +4 additions (schema gate, cascade bound, latency comparison and escalation,
   journal refusal) all become rows in S-11's gate registry; the −29 removals are
   20 fail-quiet handlers, 7 in-engine mode branches, the `OrderRequest`
   free-text disambiguation and the `is_moc` identity check.

---

### G.7 Parity re-pin schedule

P7 forbids "hashes will change" without a reason. Only **four** steps in 35 move
a hash, and each has a named cause. Everything else holds all 26 baselines, and
in the wave-D extractions that is the acceptance criterion rather than a
prediction: a pure move that moves a hash was not pure.

| Step | Artifact affected | Direction | Cause |
|---|---|---|---|
| S-16 | `_BASELINE_CONFIG_HASH` only | re-pin, 1 value | The config snapshot gains the alpha manifest hash. It is already exempt from the parity manifest as "config-contract hash, not a replay baseline" (`tests/determinism/test_parity_manifest.py:174-175`), so no replay baseline moves. |
| S-17 | `manifest_fingerprint()` | grow, 26 → 28+ | Manifest growth, not behavioural change. S-17 adds the engine-1 canonical-stream baseline and engine 11's alert taxonomy; `manifest_fingerprint()` is one visible line over the entry set by design (`tests/determinism/parity_manifest.py:234`), so gaining entries moves it while no existing baseline moves. |
| S-23 | `level4_hazard_exit_order`, `decoupled_risk_flatten_order`, `halt_order`, `symbol_halted`; possibly `position_pnl` | re-pin, one author per commit | The three remaining exit authors move off the kernel's signal family, the move the repo has already run once and documented (`tests/determinism/test_orchestrator_replay.py:273-278`): `source_layer`, `strategy_id` and the content-derived order id all change, and the halt path is engine 1/9 shared. `position_pnl` moves only if a draw family changes. |
| S-31 step 2 | `state_transition` **deleted**; then `level2_signal`, `signal_fires`, `level3_sized_intent_*`, `level4_portfolio_order`, `position_pnl`, `risk_verdict`, trade parity hash | delete 1, re-pin the rest | `_emit_state_transition` draws `self._seq.next()` (`src/feelies/kernel/orchestrator.py:4700`) 8.007 times per quote. Removing the publish removes those draws and shifts every later `sequence` on every tick, and `sequence` is the first field of nearly every helper. The `state_transition` stream becomes empty, so its entry is deleted rather than re-pinned. |

**Two dependency rules that fall out of this table.**

- **S-23 before S-24.** Both touch `halt_order`. If S-24 ships first, two steps
  move the same hash and the causes become indistinguishable — the failure mode
  AGENTS.md documents for batched changes.
- **S-31 step 2 last in the whole plan except S-32 to S-34.** It re-pins the
  widest set, so any step shipped after it inherits a freshly re-pinned oracle
  and loses the ability to say "the hash held." S-32 to S-34 are permitted after
  it only because each must hold every hash and therefore benefits from a stable
  reference rather than establishing one.

**One thing this schedule cannot promise.** The float tolerance is `.6f` ×10 and
`.2f` ×1 across all 120 helpers (Phase 0 P-1), so two runs differing by 5e-7 hash
identically while money arithmetic is exact `Decimal`. **A P&L identity can break
by less than the oracle can see.** C2's per-event conservation identities, not
the hash, are the guard for every step in wave D — which is why S-21 lists C2
first in VALIDATED BY and the baselines second.

---

### G.8 Gap coverage — all 45, plus the two proposed

Generated against `tools/arch/evidence/p7_index.json`. Every Phase 5 gap has a
step; three carry an explicit deferral of part of their scope, recorded in G.9.

| Gap | Sev | Step(s) | Enforcing tests |
|---|---|---|---|
| G01 | P2 | S-03, S-32 | S4 |
| G02 | P1 | S-12 | S15, R3, X8 |
| G03 | **P0** | **S-08** | X9, X11, H2 |
| G04 | P1 | S-15 | S16, R6 |
| G05 | P1 | S-17 | R2, R9 |
| G06 | P1 | S-16 | R4 |
| G07 | P1 | S-09 | S8, R5 |
| G08 | P2 | S-02, S-32 | R1, R8 |
| G09 | P2 | S-13 | S12 |
| G10 | P1 | S-12, S-31 | S11, X2 |
| G11 | P1 | S-20, S-17 | R2, C3 |
| G12 | P1 | S-18 | S10, S13 |
| G13 | P2 | S-20 | S2, S13, S15 |
| G14 | P1 | S-19 | S2, S12, S13 |
| G15 | P1 | S-26 | S12, C6, A3 |
| G16 | P2 | S-04 | S2, A2 |
| G17 | P1 | S-11 | S13, X6 |
| G18 | P1 | S-27 | A2 |
| G19 | P1 | S-23, S-26 | S12, C6 |
| G20 | **P0** | **S-05** | S6, X1, X5, X7 |
| G21 | P1 | S-21 | S2, S12, R8, C2, C5 |
| G22 | P1 | S-22 | S2, X2 |
| G23 | **P0** | **S-06** | S6, X1, X4, X6, X7 |
| G24 | P1 | S-24 | S2, C4 |
| G25 | P1 | S-29 | S3, A3 |
| G26 | P1 | S-28 | S7 |
| G27 | P1 | S-25 | S2, H4 |
| G28 | P1 | S-12 | S11, X9 |
| G29 | P2 | S-17 | R9 |
| G30 | P1 | S-16, S-27 | S2, R4, C5 |
| G31 | P1 | S-30 | **none — see G.0.4** |
| G32 | P1 | S-30 (deferrable) | **none — see G.0.4** |
| G33 | P1 | S-30 | C3 |
| G34 | P1 | S-21 | C2, X11 |
| G35 | P1 | S-30 | X1 |
| G36 | P1 | S-05, S-06, S-30 | S6, R6, X6, X7 |
| G37 | P1 | S-14 | S14 |
| G38 | P1 | S-11 | S13, C4, X6 |
| G39 | P1 | S-12 | S15, S17 |
| G40 | P1 | S-34 | S2 |
| G41 | P1 | S-07, S-33 | S5 |
| G42 | P1 | S-33 | S5, R7 |
| G43 | **P0** | **S-07** | X1, X10 |
| G44 | P2 | S-31 | S5 |
| G45 | P2 | S-32 | S5 |
| G46 | P1 (proposed, Phase 6 §8.1) | S-10 | S9 |

**All 50 Phase 6 tests are placed, and "placed" means authored — not passing.**
A test is authored once, `xfail(strict=True)` if it fails, and the step that
closes its gap is the step that drops the marker. Six tests are therefore named
twice in this plan on purpose: S5, S7, S10, S11, S16 and S17 are authored in
S-03 and closed later (S-32, S-28, S-18, S-12, S-15, S-12 respectively). That is
the mechanism from Phase 6 §0.1, not double-counting.

| Wave | Tests authored | Count |
|---|---|---|
| A | S1, S2, S3, S4, S5, S6, S7, S10, S11, S16, S17, R1, R2, R7, R8, C1, C2, C3, X3, H1, A1 | 21 |
| B | X4, X5, X6, X7, X10, X11, H2 | 7 |
| C | S8, S9, S12, S13, S14, S15, R3, R4, R5, R6, R9, X8, X9 | 13 |
| D | X1, X2, C4, C5, C6, H3, H4, A2, A3 | 9 |
| **total** | | **50** |

Twenty-one of the 50 land before the first line of remediation, including all
four of Phase 6's non-negotiable guards (R1, X3, H1, A1). No conformance test
carries `functional` or `paper_rth`, per Phase 6 §7's prohibition.

---

### G.9 Deferrals, stated with reasons

P7 requires every Phase 5 gap to have a step **or an explicit deferral with a
reason**. Every gap has a step; three carry a partial deferral, and one whole gap
is nominated as the cut line if scope must shrink.

| Item | Deferred | Reason | What un-defers it |
|---|---|---|---|
| **G32** (§F.2 symbol identity) | The whole gap, if scope must be cut | It is the plan's only **net-new capability** rather than remediation — no symbol-identity handling exists to move (3 sites, no CUSIP/FIGI, no corporate-action handling). Phase 5's own blast-radius reading is that intraday single-day replay is unaffected and only a multi-day series crossing a corporate action is silently wrong. The platform is intraday. | A multi-day backtest, or any live position held across a corporate action. Until then this is a known-wrong number in a case the platform does not currently produce. |
| **G41** (4.2× latency overrun) | The overrun itself, to S-33 | S-07 creates the budget and the breach response, which is the P0 (G43). **Closing the overrun is a different job from detecting it**, and doing them in one step would mean optimising against a budget that had never fired. | S-07 shipped and X10 observed firing at least once under HARN-2 injection. |
| **G44** (106 uncalled methods) | The method deletion, now rescoped to ~12 | A5.4 closed **FALSE** in X1: static analysis covered `src/` call sites only, and 82 of the 106 are called from `tests/`. The deletion no longer carries the plan's headline, because there is no longer a headline net-negative to carry (G.6 note 2). What survives is the silent-break risk on the residue — `getattr`-reached methods fail closed with no exception. | Delete only what a `coverage` run with branch data proves unexecuted, then replay the oracle. Documented extension points are excluded regardless of coverage. |
| **X1** (degraded monotonicity property) | From wave B to S-22 | X1 is a property over the **enumerable** degradation set, and that enumeration is an artifact S-11 and S-22 create. It genuinely cannot precede them. **X3 covers the P0-relevant clause in wave A** — reduction is always permitted — so no P0 ships without a monotonicity guard. | S-11 and S-22 shipped. |
| **G31, G32 conformance tests** | Authored in S-30 rather than wave A | Phase 6 specifies no test for either (G.0.4, `p7_index.json:unmapped`). S1 will fail on both from wave A onward, xfailed with their gap IDs, which is the correct signal rather than a silent hole. | S-30 authoring the gates and registering them in S-01's registry. |

**Not deferred, and worth saying so.** Every P0 ships in wave B. Every §F item
Phase 2 resolved gets a step. No gap is dropped, and no step is contingent on a
later step in a way that makes it unshippable — the one place that was tempting,
S-04's `inv12_stress` move, carries an explicit split into S-04b if the move
turns out to break a public import path.

---

### Verification performed on Deliverable G

**Numbering note.** This section is deliberately unnumbered. Every "§G.10" above
means **CORE §G.10** — "net complexity is justified" — which this plan's ledger
is written against; a §G.10 of my own would have made twenty of those references
ambiguous.

- `tools/arch/p7_index.py` written this session and run; it parses all 45 gap
  rows from Phase 5 and all 50 test blocks from Phase 6 and emits
  `tools/arch/evidence/p7_index.json`. It reproduces Phase 5's severity
  distribution exactly — **P0 = 4, P1 = 33, P2 = 8** — which is the check that
  the parse is faithful rather than approximately right. First run gave P1 = 30
  with three cells mis-split, because three gap rows contain a pipe inside a
  backticked regex; severity is now indexed from the right.
- **Every P0 citation re-read in source this session, not carried:**
  `src/feelies/composition/engine.py:384-389` (the `except Exception` /
  `0.0` substitution and the `# pragma: no cover - defensive`),
  `src/feelies/alpha/risk_wrapper.py:186-192` (`except KeyError: pass` past the
  whole `else`), `src/feelies/execution/passive_limit_router.py:183` (the bare
  `set()` and its "ever submitted" comment),
  `src/feelies/kernel/orchestrator.py:2126-2153` (`_tick_timings` published and
  never compared), `src/feelies/bootstrap.py:358` (`InMemoryTradeJournal` the
  only wired journal), `src/feelies/core/platform_config.py:108`
  (`moc_strategy_ids` default).
- **The parity rule in G.0.1 was established by reading, not assumed.**
  `self._seq.next()` counted at 17 sites in the orchestrator plus one
  `_hazard_seq` draw at `:2519`; `_emit_state_transition` confirmed to draw at
  `src/feelies/kernel/orchestrator.py:4700`; `sequence` confirmed as the leading
  hash field in seven helper functions across six determinism modules.
- **The strongest evidence in this deliverable is a precedent, not an
  inference.** `tests/determinism/test_orchestrator_replay.py:273-278` documents
  the outcome of the earlier stop-exit decoupling — which hashes moved, which did
  not, and why — and S-23 is the same move for three more authors. Found by
  reading, and it changed S-23 from a step with a guessed parity impact into one
  with a measured antecedent.
- The 7 non-bootstrap mode-branch sites in S-28 were enumerated from
  `gapscan.json:mode_branches.sites`, not counted by hand.
- Ledger baselines read from `inventory.json` (196 modules, 551 public symbols,
  43 197 sloc) and `gatescan.json` (20 fail-quiet handlers, 329 gate sites).
  **All per-step src deltas are `INFERRED` projections** and the ledger states
  its own reconciliation requirement. Ledger arithmetic checked
  programmatically: every running total equals the accumulated deltas, and the
  net is +7 / +22 / −25 (was +7 / −73 / −25 before X1 rescoped S-31).
- **One ledger column was wrong in the first draft and was corrected by
  measuring.** The test-file column originally read `+50`, which matched the
  test count — because it was copied from it. The 50 tests resolve to **49
  distinct paths, 45 of them new**, since 4 tests extend existing files and S6
  and X7 share one. Six steps that had been credited with a new file were
  authoring a test into a file an earlier step created. A column that agrees
  with a number it was copied from is not evidence, and the coincidence is what
  made it look like one.
- Phase 6's per-test `BUILD ORDER` fields were compared against its §6 table;
  four disagreements found (C4, C5, R4, S12) and recorded in G.0.3 rather than
  resolved.
- Two gaps found to have no conformance test (G31, G32), by cross-reference
  rather than by reading — recorded in G.0.4 and carried into G.8 and G.9.
- **One Phase 5 claim contradicted:** G44's "removing dead compute changes
  nothing computed, so the parity hash must not move" is false for its own
  largest item, because the `StateTransition` publish draws a shared sequence.
  Recorded in S-31 rather than worked around.
- **Every path in every `FILES:` block was checked for existence, and one
  destination did not exist.** S-19 originally named `src/feelies/regime/` as
  engine 3's destination package. There is no such package — `RegimeEngine` lives
  at `src/feelies/services/regime_engine.py`, which is itself worth recording:
  the engine CORE §E.3 requires to be singular is the one engine with no package
  boundary to be singular inside of. S-19 now names the real module and states
  why it does not create a package. All other `src/feelies/` destinations exist.
- **Nineteen test paths were renamed to Phase 6's, after I had invented my own.**
  The first draft wrote plausible names — test_position_read_totality.py,
  test_schema_envelope_closure.py, test_reset_totality.py — where Phase 6
  specifies test_position_read_fails_closed.py, test_schema_drift.py and
  test_reset_paths.py. **Those six names are unbracketed on purpose**, and
  writing this bullet is what proved why: inside backticks the checker read all
  six as live citations and failed them as "file missing," taking a clean
  spotcheck to 6 failures. Phase 5 recorded this recursion, Phase 6 recorded it
  again, and it has now happened a third time in the sentence describing it.
  Phase 6 is an accepted input, so its paths are
  authoritative; a plan that renames them makes the file-count ledger
  unverifiable against the document it is derived from, and would have produced
  19 duplicate files at execution time. Checked mechanically against
  `p7_index.json`: the only test paths this plan names that Phase 6 does not are
  the three support files it does not give `.py` paths for — the gap registry and
  the two harnesses.
- `tools/arch/p7_check.py` written this session; it asserts all 35 step blocks
  carry P7's twelve required fields, that step IDs are contiguous, and that every
  one of the 45 gap IDs has a step in the coverage table. Reports `OK`.
- `tools/arch/fix_citations.py` (pre-existing) run to expand abbreviated
  citations, then `spotcheck -n 200`: **72 distinct citations, 72 sampled, 0
  failures** — `n` exceeds the population, so this is the full set. The first
  submission had 23 failures, all of them Phase 5's and Phase 6's recorded
  defect recurring: a citation written package-relative rather than under
  `src/feelies/`. Three phase outputs in a row have now made the same mistake,
  which suggests the checker should run before submission rather than after, not
  that three authors were careless.
- Scope guard run: `powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1`
  reports `scope: OK -- no protected-path changes`. Writes confined to
  `docs/architecture/target/out/` and `tools/arch/`. One scaffolding script used
  to assemble this document was deleted after use rather than left behind, since
  it could never usefully run again.

---

---

## I. Do-not-change list

### I.0 What "promotion" means, and the column Phase 5 left blank

Phase 5 called this a **candidate** list. Promotion means re-measured, not
carried: `tools/arch/p7_dnc.py` was written this session and re-checks the 12
entries that are mechanically checkable; **all 12 still hold**
(`tools/arch/evidence/p7_dnc.json`). The other 12 were re-verified by reading the
cited lines, and each entry below carries the line it was read at. Three entries
were flagged as changed on the first run and all three were checker defects, not
regressions — recorded in *Verification performed* rather than silently fixed.

**Two entries are restated more narrowly than Phase 5 wrote them.** Being sound
at a narrower scope is not the same as being sound as written, and a do-not-change
list that overstates its own entries protects the wrong thing (§I.6).

**The column Phase 5 left blank is the threat.** Phase 5 says of these entries
that "each is a regression risk during remediation" and stops there. Deliverable
G now exists, so the risk has a name: every entry below states **which step
threatens it** and **which conformance test catches the breach**. An entry with a
threatening step and no guard is a blocker, and there is one (I-19).

**Format.** `SOUND BECAUSE` is the mechanism that keeps it true, not the
measurement that shows it is true — a property that holds by accident is not on
this list. `STOPS WHEN` is the falsifier. `THREATENED BY` names steps from
Deliverable G, or `none`.

---

### I.1 Determinism substrate

```
I-01  Content-derived identity; no `uuid` anywhere in src/feelies
SOUND BECAUSE:  Identity is a pure function of provenance, so it is reproducible
                rather than recorded: `make_correlation_id` is
                f"{symbol}:{exchange_timestamp_ns}:{sequence}" and
                `derive_order_id` is sha256(seed)[:16]
                (`src/feelies/core/identifiers.py:9,18`). Re-verified: **0 uuid
                imports** across 196 modules, and the only RNG sites are in
                `src/feelies/research/cpcv.py`, which is cold.
STOPS WHEN:     A new event or order author generates an identifier from a
                counter, a timestamp alone, or an RNG. The failure is silent —
                a non-derived id still looks like an id, and replay still runs.
THREATENED BY:  S-08 (the durable journal keys on order_id and could be tempted
                to mint its own record id) and S-23 (three new order authors in
                engine 9, each of which must derive rather than assign — the
                earlier stop-exit move already produced "a content-derived order
                id from the new author", so the pattern is established).
GUARD:          H2 asserts the id survives a restart, which only holds if it is
                derived. Add the uuid/RNG scan to S-03's static set so the
                absence is asserted rather than observed.
```

```
I-02  Deterministic total order on the market-data merge
SOUND BECAUSE:  `event_merge_sort_key` returns
                (exchange_timestamp_ns, symbol, type_rank, sequence)
                (`src/feelies/storage/event_resequence.py:33-43`) — four fields
                whose last component is unique, so the order is total and no tie
                can fall through to list position.
STOPS WHEN:     A third market-data type joins the merge path. `_TYPE_RANK` is
                a **bare dict subscript** (`:37`), so an unranked type raises
                `KeyError` at ingest — fail-closed, and the right direction. The
                dangerous case is adding the type *and* a rank without deciding
                what the rank means, which silently reorders same-timestamp rows.
                It also stops being enforced wherever
                `enforce_market_order=False`, which live and paper logs set by
                design (`src/feelies/storage/memory_event_log.py:48-55`).
THREATENED BY:  none in this plan — no step adds a market-data type. S-09 and
                S-23 add `LatencyBreach` and `DeRiskRequirement`, which are not
                market data and never reach this key (see §I.6 for why that is a
                narrower claim than Phase 5's).
GUARD:          `ReplayFeed` raises `CausalityViolation` on any backward key
                (`src/feelies/ingestion/replay_feed.py:91-99`), and R1 under a
                random seed covers the tie-break.
```

```
I-03  Every event class is a frozen dataclass
SOUND BECAUSE:  Immutability is declared on the type, so no consumer can rebind
                a field on a received event. Re-verified: **0 non-frozen**
                dataclasses in `src/feelies/core/events.py`.
STOPS WHEN:     A new event class omits `frozen=True`, or an existing one gains
                a field that is a mutable container — which is G12, already
                true of 8 classes, and is why this entry is about the decorator
                and not about the payload.
THREATENED BY:  S-09 and S-23 add event types; S-18 rewrites the container
                fields of 8 existing classes. S-18 is the higher risk because it
                edits the classes rather than adding to them.
GUARD:          S10 (authored in S-03, closed by S-18) asserts frozen in
                substance; the decorator half needs the same assertion and S-03
                should carry both clauses.
```

```
I-04  No global handler fan-in; exact-type bus dispatch
SOUND BECAUSE:  Dispatch is by exact type, so a handler cannot receive a subtype
                it did not ask for, and `subscribe_all` — the one API that would
                create a global fan-in — has **0 call sites**, its only
                occurrence being its own definition at
                `src/feelies/bus/event_bus.py:55` (re-verified). The
                subscription graph is therefore knowable by reading
                subscriptions.
STOPS WHEN:     Anything calls `subscribe_all`, or dispatch gains subtype
                matching. Either makes the emitted-type registry (S-13)
                unable to name a contract's consumers.
THREATENED BY:  S-12 — and it **strengthens** rather than threatens: the step
                deletes `subscribe_all` outright, converting a property held by
                nobody-happens-to-call-it into one held by the method not
                existing. This is the cheapest hardening in the plan.
GUARD:          S15's wiring-manifest closure fails on any subscription the
                manifest does not declare, which a global fan-in cannot satisfy.
```

```
I-05  Realised money is `Decimal`
SOUND BECAUSE:  Exact decimal arithmetic makes P&L accumulation order-free,
                which is what lets engine 7 be summed in any order and still
                hash identically. Re-verified field by field: `Trade.price`,
                `OrderRequest.limit_price`, `OrderAck.fill_price`,
                `OrderAck.cost_bps`, and all four of
                `PositionUpdate.{avg_price, realized_pnl, unrealized_pnl,
                cost_bps}` are `Decimal`; quantities are `int`.
                **Phase 5 wrote "money is Decimal end to end"; measured, the
                boundary is the fill** — see §I.6.
STOPS WHEN:     A float reaches the realised side. The compensating control for
                the float side is I-13, so I-05 and I-13 are one property in two
                halves: if I-13's `fsum`-over-sorted-keys discipline is not
                applied to a new float sum, I-05's boundary stops being safe
                even though every `Decimal` field is untouched.
THREATENED BY:  S-21 (engine 7's read-only view must not widen a `Decimal` to a
                float on the way out) and S-10, which will be the first step
                forced to name the unit and type of every numeric field and is
                therefore where a wrong answer gets written down.
GUARD:          C2's per-event conservation identities, which are the only guard
                that can see a rounding divergence smaller than the `.6f` hash
                tolerance (see G.7's closing note).
```

```
I-06  A substantial, closed parity surface
SOUND BECAUSE:  26 `LOCKED_PARITY_BASELINES` entries, each imported from the
                test that computes it — so a baseline cannot exist without a
                producer (`tests/determinism/parity_manifest.py:133`) — plus two
                closure tests that AST-scan the whole `tests/` tree for
                unregistered 64-hex literals and for stale exemptions
                (`tests/determinism/test_parity_manifest.py:261,:288`), and one
                `manifest_fingerprint()` over the sorted manifest (`:234`) so a
                coordinated re-pin is one visible line.
STOPS WHEN:     A re-pin is made without moving `manifest_fingerprint()`, or a
                baseline is exempted without a reason. The structural limit is
                that hash inputs are hand-written field lists, so **adding a
                field cannot break parity** — the oracle is blind to schema
                growth, which is G07's blast radius and not a defect in this
                entry.
THREATENED BY:  S-16, S-17, S-23 and S-31 all re-pin or grow the manifest — by
                design, and each states its reason in G.7. The threat is not the
                re-pin; it is a re-pin that rides along with a behavioural change
                and so cannot be attributed.
GUARD:          G.7's schedule plus the rule that each re-pin is its own commit.
                S-23 and S-31 both carry "one author per commit" for this reason.
```

```
I-07  Ingress duplicate policy is explicit and fail-closed
SOUND BECAUSE:  On ambiguous input the normalizer takes the exposure-reducing
                branch: exact duplicates are dropped, and a sequence reused with
                a *different* payload transitions the symbol to `CORRUPTED`
                (`src/feelies/ingestion/massive_normalizer.py:777`,
                `_reject_sequence_reuse`), which
                `src/feelies/ingestion/data_integrity.py:58` declares terminal
                by giving it an empty `frozenset()` of onward transitions — so
                there is no path back without a restart.
STOPS WHEN:     `CORRUPTED` gains an outbound transition, or the reuse check is
                relaxed to a warning. Both would be loosening a safety control
                autonomously, which Inv-11 forbids without human
                re-authorization.
THREATENED BY:  S-20 moves 5 engine-1 methods out of the kernel, and S-30's §F.3
                consolidates 165 session/halt sites onto one authority. Neither
                targets this code, which is why the risk is collateral rather
                than direct.
GUARD:          C3 (ingress conservation) and the new `market_data_canonical`
                baseline from S-17 — which is exactly why S-17 is sequenced
                before S-20 rather than after it.
```

```
I-08  CI runs the determinism suite at PYTHONHASHSEED=random
SOUND BECAUSE:  A pinned seed cannot detect newly introduced hash-order
                dependence, and the job carries a comment saying so and
                instructing against re-pinning
                (`.github/workflows/ci.yml`, re-verified present). This is the
                guard that keeps G08 at P2 rather than P1.
STOPS WHEN:     Someone re-pins the seed to make a flake go away. The comment is
                the only thing standing in the way, and a comment is the weakest
                mechanism Phase 3 ranks.
THREATENED BY:  S-02 edits this job — and **strengthens** it, by adding the
                parity oracle inside it. The risk is procedural: an edit to a job
                whose correctness lives in a comment.
GUARD:          R1 is the assertion that replaces the comment.
```

```
I-09  The parity oracle cannot pass without replaying
SOUND BECAUSE:  `FEELIES_REQUIRE_BASELINE_CACHE=1` turns a cache-miss skip into
                a failure, and the fork-PR skip is stated rather than silent
                (`.github/workflows/ci.yml`, re-verified present). This closed a
                defect where the oracle had **three independent ways to report
                success without executing**.
STOPS WHEN:     The env var is dropped, the job is renamed out of the required
                set, or a conformance test is given a `functional` marker and
                quietly deselected. All three have precedent in this repo.
THREATENED BY:  S-02, which edits the same workflow file. This is the entry
                whose breach would hide every other breach in the plan, because
                31 of 35 steps name the replay baselines or the parity
                oracle as their acceptance criterion.
GUARD:          Phase 6 §7's prohibition — no conformance test may carry
                `functional` or `paper_rth` — asserted by S1's registry closure.
```

---

### I.2 Engine and layer structure

```
I-10  `signals/` is a clean engine-4 package
SOUND BECAUSE:  Its inputs are exactly three, and none of them is position, P&L
                or order state: `RegimeState`, `SensorReading` and
                `HorizonFeatureSnapshot`
                (`src/feelies/signals/horizon_engine.py:196-198`, re-read). A
                forecast that cannot see the book cannot accidentally become a
                decision, which is what makes engine 4 substitutable and
                testable in isolation.
STOPS WHEN:     A fourth subscription is added, specifically to `PositionUpdate`
                or `OrderAck`. That single edit would convert engine 4 from a
                forecaster into a decider and make every alpha's output depend
                on execution history.
THREATENED BY:  S-26 consolidates three reducers into `composition/`. The risk
                is the opposite direction to the obvious one: the temptation is
                to give engine 4 position awareness so it can pre-filter, rather
                than let engine 6 reduce.
GUARD:          A1 (alpha purity, authored in S-02 as one of the four
                non-negotiable guards) and S14's forbidden-reads matrix.
```

```
I-11  Zero mode branches inside `execution/` or `broker/`
SOUND BECAUSE:  The seam itself is clean — every one of the 27 measured mode
                branches is outside it (re-verified: **0 sites** inside either
                package). Backtest/live parity is structural there rather than
                maintained, because the code cannot tell which mode it is in.
STOPS WHEN:     Any mode test appears inside the seam. The likely vector is a
                "just for backtest" shortcut in a router.
THREATENED BY:  **S-08 and S-25, both directly.** S-08 wires a durable journal
                selected by mode and edits
                `src/feelies/execution/passive_limit_router.py` and
                `src/feelies/broker/ib/connection.py`; if the mode test lands in
                the router instead of at the composition root, this entry breaks
                in the same commit that fixes a P0. S-25 moves 6 order-state
                transitions into `execution/` from a kernel that does branch on
                mode.
GUARD:          S7, with the composition-root exemption as an explicit
                allowlist. S-08's block already says the selection happens "in
                `src/feelies/bootstrap.py` where mode selection is legitimate" —
                that sentence is load-bearing, not decoration.
```

```
I-12  Both passive fill paths are gated in exchange time
SOUND BECAUSE:  All four gates compare `exchange_timestamp_ns`, never a wall
                clock: `src/feelies/execution/passive_limit_router.py:377`
                (fill deadline) and `:527` (ack timestamp), and
                `src/feelies/execution/moc_fill.py:83` (MOC cutoff) and `:132`
                (official close) — all four re-read this session. Fill
                eligibility is therefore a function of the tape, so it is
                identical in backtest and live and survives a slow process.
STOPS WHEN:     A fill decision reads `time.time()` or the injected clock's wall
                time instead of the event's exchange timestamp. A slow replay
                would then produce different fills than a fast one.
THREATENED BY:  S-08 (edits the router) and S-25 (moves 6 transitions into
                `execution/`). S-07 is the subtler threat: it introduces the
                platform's first legitimate wall-clock *decision*, and the
                boundary between "latency budget may read the wall clock" and
                "fill eligibility may not" is a rule someone must keep.
GUARD:          H1, one of the four guards in S-02, extended in that step to
                cover the aggressive path on the same tape.
```

```
I-13  `src/feelies/composition/cross_sectional.py` holds the platform's best determinism discipline
SOUND BECAUSE:  Every sum is taken over a lex-sorted key list *and* accumulated
                with `math.fsum`, so float accumulation order is fixed
                regardless of dict or set iteration order — `keys =
                sorted(gross_by_family)` then `math.fsum(...)` at
                `src/feelies/composition/cross_sectional.py:78-79`, with the
                docstring at `:75-76` naming Inv-5 as the reason. The reason it
                is sound is that it states *why*, so the next reader knows not to
                simplify it.
STOPS WHEN:     A new sum in `composition/` uses builtin `sum()` over an
                unsorted iterable. Nothing detects this: float addition is
                order-dependent at a magnitude far below the `.6f` hash
                tolerance, so the oracle would not move.
THREATENED BY:  **S-26 directly.** It consolidates three reducers into
                `composition/`, and two of the three being consolidated —
                `_select_bus_signal` in the kernel and
                `src/feelies/alpha/arbitration.py` — do not have this
                discipline. Merging code that lacks it into the package that has
                it is exactly how the discipline gets diluted.
GUARD:          R8 (store-ordering seed independence, authored in S-03) and R1
                under a random seed. Both are weaker than the property, because
                a seed change does not reliably reorder a small dict. C6's
                accounting identity is the real guard.
```

```
I-14  Engine 3 has a single declared read path
SOUND BECAUSE:  One place declares it — "One read path for regime: consumers
                read what was published, never the ..."
                (`src/feelies/bootstrap.py:289`, re-read) — and two parity
                baselines pin the output (`level5_regime_hazard_spike`,
                `level6_regime_state`). The regime gate is also correctly off by
                default, so the read path is exercised without the gate being a
                live dependency.
STOPS WHEN:     A second consumer calls the regime engine directly instead of
                reading what was published, which reintroduces the recompute
                this comment exists to prevent.
THREATENED BY:  S-19 moves 5 regime methods out of the kernel. The declared read
                path is the thing the move must preserve, and it is documented
                in a comment at the composition root rather than enforced.
GUARD:          S12 (one producer per contract) and the two baselines. S-19's
                note to move `_maybe_publish_hazard_spike` last, because it
                draws from `self._hazard_seq`, protects the baseline half.
```

```
I-15  The kill switch is read directly on the tick path and returns early
SOUND BECAUSE:  It is a **synchronous property read, not a subscription**:
                `if self._kill_switch is not None and
                self._kill_switch.is_active` at
                `src/feelies/kernel/orchestrator.py:1561`, inside tick
                processing, transitioning to `DEGRADED` and suppressing the
                tick. The same direct read guards session entry (`:759`),
                recovery from degraded (`:1033`) and unlock from lockdown
                (`:1070`). None of the four depends on bus delivery, so the
                safety control cannot be lost, reordered, or dropped by a
                re-entrant bus with 16 handlers that publish from inside
                dispatch. **The control works; only its announcement is inert
                (G28).**
STOPS WHEN:     The direct read is replaced by a subscription to
                `KillSwitchActivation`. The kill switch would then be as
                reliable as event delivery on the bus described above, and the
                failure mode is that it silently does not fire.
THREATENED BY:  **S-12, and this is the most dangerous single interaction in the
                plan.** S-12 step (5) gives `KillSwitchActivation` a consumer to
                close G28. Read carelessly, "give the event a consumer" becomes
                "route the check through the event." **The consumer must be
                additive — an observer that records and alerts — and the four
                direct reads must survive untouched.** If the diff for S-12
                deletes any of `:759`, `:1033`, `:1070` or `:1561`, the step is
                wrong regardless of what the tests say.
GUARD:          X9 asserts the kill switch is fail-closed, durable **and**
                observable, and must assert all three clauses — an X9 that only
                checks observability would pass on the broken version. This is
                the one place in the plan where a guard's absence would not be
                caught by another guard.
```

```
I-16  `promotion/` is cold and executes nothing per event
SOUND BECAUSE:  Measured `governance_evaluation`: **0 proven per-event sites, 0
                hot sites, 45 cold sites** (`hotpath.json`, re-read). Governance
                is resolved at composition time, so a promotion decision cannot
                enter the tick path and a slow ledger cannot slow a trade. The
                package is also append-only, so a forensic read cannot mutate
                lifecycle state.
STOPS WHEN:     Any per-event code path consults lifecycle state — for example a
                risk check that asks "is this alpha still LIVE?" on every order
                rather than at load. The import-time coupling (G16) is a
                separate and lesser problem; this entry is about execution.
THREATENED BY:  S-04 moves `inv12_stress` out of `core/` to break the import
                edge, and S-27 changes who writes the quarantine transition.
                S-27 is the one to watch: moving the write to engine 5 is correct,
                but engine 5 must not then be consulted per event to find out
                whether the write happened.
GUARD:          A2, which must assert **both** halves of CORE §C.10 — zero reads
                under instrumentation and no import edge. Phase 6 warns that
                asserting only one makes the invariant read as satisfied, and
                A2 passes today on reads and fails on imports.
```

```
I-17  The gate-evidence matrix enforces its own completeness — three times
SOUND BECAUSE:  `_check_matrix_completeness()` raises `RuntimeError` naming the
                missing members if any `GateId` lacks an entry
                (`src/feelies/promotion/evidence.py:1719-1732`), and it is
                **invoked at module import** — as are two sibling checks,
                `_check_validator_coverage()` and
                `_check_threshold_direction_coverage()`, all three called at
                `:1772-1774` (re-verified). A contributor adding an enum member
                without populating the matrix cannot import the module. This is
                the strongest enforcement mechanism in the platform: it fails at
                import, not at test time, so it cannot be deselected.
STOPS WHEN:     The module-level invocations are removed, or a check is defined
                and never called. The assertion living inside a function is what
                makes that possible — and is why my first re-verification
                reported this entry as broken (see *Verification performed*).
THREATENED BY:  S-11 builds the 53-row gate registry **on this pattern**. The
                threat is replacement rather than extension: if the new registry
                supersedes `GATE_EVIDENCE_REQUIREMENTS` without carrying the
                import-time check forward, the plan trades the platform's
                strongest mechanism for a test.
GUARD:          S13's closure test — but note that S13 is a *test*, which is a
                weaker mechanism than what exists here. S-11 should keep the
                import-time check and add S13, not substitute.
```

```
I-18  The platform is alpha-agnostic except at one point
SOUND BECAUSE:  Re-verified against manifest filenames rather than directory
                names: **11 alpha ids declared, 3 literal occurrences in all of
                `src/feelies`** — `src/feelies/core/platform_config.py:108` and
                `:910` (the `moc_strategy_ids` default) and a docstring at
                `src/feelies/research/forward_ic.py:10`. So one real leak, one
                duplicate of it, one comment. Core does not branch on alpha
                identity anywhere else.
STOPS WHEN:     A second id is added to a core default, or — the case a
                substring scan cannot see — core branches on an alpha
                *characteristic* rather than its name. Phase 6 states this limit
                of S3 explicitly.
THREATENED BY:  S-29 removes the one real leak, so the plan **strengthens** this
                entry to zero. The risk is in the replacement: S-29 introduces
                route-by-declared-property, and a property that only one alpha
                ever declares is the same coupling with a new name.
GUARD:          S3 for the literal half, A3 for the behavioural half — A3
                asserting attachment with **zero diff** under `kernel/`, `bus/`,
                `core/`, `composition/`, `risk/` and `execution/`.
```

---

### I.3 Performance and typing

```
I-19  Five hot-path prohibitions are clean
SOUND BECAUSE:  Re-read from `hotpath.json` this session: `regex` 0 proven / 0
                hot / **0 cold**, `disk_io` 0 proven / **0 hot** / 58 cold,
                `deep_copy` 0 proven / 0 hot / 1 cold,
                `governance_evaluation` 0 proven / 0 hot / 45 cold, and
                `serialization` 0 proven per-event / **2 hot sites** / 100 cold.
                No disk touch and no serialization occurs per event, which is
                what makes the tick path's cost a function of computation rather
                than of the filesystem.
STOPS WHEN:     Anything writes to disk or serializes on the tick path. The cost
                is not a constant — an fsync is unbounded, so this is the one
                prohibition whose breach can produce a latency outlier rather
                than a latency increase.
THREATENED BY:  **S-08, directly and by design — this is a blocker, see §I.7.**
                Journal-before-wire puts a disk write **and** a serialization on
                the order-submission path, which is inside tick processing. The
                P0 fix for G03 and this entry cannot both be satisfied as
                currently specified.
GUARD:          S5 (hot-path allow list, authored in S-03) would fail on S-08 —
                which is the system working correctly. X10's budget from S-07
                is what would measure the cost, and S-07 is sequenced *before*
                S-08 partly for that reason.
```

```
I-20  `mypy --strict` is clean on all of `src/feelies`, acceptance-locked
SOUND BECAUSE:  Strict typing with **no `ignore_errors` overrides**, enforced by
                an acceptance test rather than by CI configuration alone, so the
                lock cannot be loosened by editing a workflow. This is the
                mechanism currently holding the platform's strongest invariant —
                Phase 6 notes that the 36 direct store calls are held by "type
                annotations plus `mypy --strict`, not a runtime check."
STOPS WHEN:     An `ignore_errors` or a broad `type: ignore` is added. The
                acceptance test catches the former; the latter is per-line and
                would not fail the test.
THREATENED BY:  Every step that edits `src/feelies`, which is 31 of 35. The
                specific risk is S-12's constructor injection, which changes
                consumer signatures across the platform, and S-18's container
                conversions, which change field types on 8 event classes.
GUARD:          `uv run mypy src/feelies` is in VALIDATED BY for S-04, S-09,
                S-10, S-12, S-16, S-18 and S-21. It should be in all 30 —
                recorded here as a correction to Deliverable G rather than
                edited in silently.
```

---

### I.4 Promoted from Phase 6, absent from Phase 5's list

```
I-21  Engine 2's input contract is closed and already enforced
SOUND BECAUSE:  `SensorSpec.subscribes_to` cannot name a type outside a
                hard-coded `{NBBOQuote, Trade}` map, and a `ConfigurationError`
                naming the valid set is raised otherwise
                (`src/feelies/core/platform_config.py`, re-verified: closed map
                present, raise present). Phase 6 §8.2 closed question U-4 with
                this and called the enforcement point "a model for S13's
                registry." No test is needed because the constraint is a load
                failure.
STOPS WHEN:     The map is widened without deciding what a sensor over a
                non-market event means — a sensor subscribing to `OrderAck`
                would make engine 2 a function of execution history.
THREATENED BY:  S-13 and S-11 both build registries and may be tempted to
                generalise this one. Generalising a closed set is how it stops
                being closed.
GUARD:          The `ConfigurationError` itself, which is stronger than any test
                in Phase 6's suite.
```

```
I-22  Sensor throttling is in event time
SOUND BECAUSE:  `binding.throttle_ns` is compared against
                `event.timestamp_ns - last_ns` (`src/feelies/sensors/registry.py`,
                re-verified: the comparison is present and there is **no
                wall-clock read anywhere in the module**). So engine 2 is a pure
                function of the event prefix on this axis, and a throttled
                sensor produces identical output on a fast and a slow host.
STOPS WHEN:     The comparison moves to `perf_counter` or the injected clock's
                wall time, at which point replay stops being reproducible and
                the failure appears as an intermittent parity break.
THREATENED BY:  S-33 optimises engine 2's per-sensor cost, and throttling is the
                most obvious lever. Making throttle wall-clock-based would
                genuinely reduce measured cost and silently destroy replay.
GUARD:          R7, which Phase 6 correctly classifies as a **guard rather than
                a gap-closer**, with the verified value in its `FALSIFIED BY`
                field. It is authored in S-03, before S-33.
```

```
I-23  One dynamic import, prefix-constrained
SOUND BECAUSE:  The only `importlib.import_module` under `src/feelies` requires
                its target to live under `feelies.sensors.impl.*`
                (`src/feelies/core/platform_config.py`), and
                `src/feelies/composition/turnover_optimizer.py:33` uses
                `find_spec` as an extras probe rather than an import. So the
                static import graph **is** the real import graph, with one
                config-driven edge whose range is bounded.
STOPS WHEN:     A second dynamic import appears, or the prefix constraint is
                relaxed. Either makes S-04's tier contract unverifiable, because
                import-linter reasons over the static graph.
THREATENED BY:  S-04 itself, which makes the static graph load-bearing for the
                first time. Nothing in the plan adds a dynamic import.
GUARD:          S2 via import-linter, plus a scan asserting the count stays at
                one — which S-04 should add and currently does not.
```

```
I-24  The layer gates ship strict, and nothing turns them off
SOUND BECAUSE:  The fail-safe posture is the **default**, not the configured
                value, and it is declared strict in **all four** places it
                appears: `src/feelies/core/platform_config.py:339` and
                `src/feelies/alpha/layer_validator.py:234` and
                `src/feelies/alpha/loader.py:221` all default `True`, and
                `src/feelies/core/platform_config.py:1106` reads
                `bool(data.get("enforce_layer_gates", True))` so a config that
                omits the key gets strict. `src/feelies/alpha/layer_validator.py:257` states the
                intent — "Default True (production posture)". Re-measured this
                session: **zero occurrences across `configs/**/*.yaml`**, which
                is what closed U-6. Composing the two halves: no shipped config
                disables G1 or G3, and disabling them requires adding a key on
                purpose. This is Inv-11's fail-safe default implemented as a
                default value rather than as a check.
STOPS WHEN:     Any config adds `enforce_layer_gates: false`. Phase 3 states the
                consequence — "a governance ladder that can be switched off by
                configuration in production is not a cold ladder; it is a
                runtime-varying eligibility rule with no per-event record"
                (`docs/architecture/target/out/phase3_flow_gating.md:562`). The
                downgrade is also *silent by design*: `_softly` logs a warning
                and continues (`src/feelies/alpha/layer_validator.py:283-287`).
THREATENED BY:  S-11, which builds the gate registry and must declare each gate's
                `DISABLEABLE` status. Phase 3 could not declare it and called U-6
                blocking for that reason. It is now answerable: G1 and G3 are
                disableable **in principle** and disabled **in no config**, which
                are two different rows and should not be collapsed into one.
GUARD:          S13. It should assert the absence over `configs/` rather than the
                default value alone, because the default protects a config that
                omits the key and not one that sets it.
```

---

### I.5 Considered and **not** promoted

| Candidate | Why not |
|---|---|
| ~~`enforce_layer_gates` absent from `configs/`~~ | **Refused, then promoted as I-24 after reading the code.** My refusal reasoned from the glossary sentence "if false, only G1/G3 downgrade to warnings" and inferred that absence from every config meant the gates ship advisory. The inference was backwards: the default is `True` in all three places it is declared. The corrected entry is I-24 and the error is recorded as A7.12. |
| The 106 uncalled public methods (Phase 5 G44) | Phase 5 puts these in the gap table, and its assumption A5.4 (`docs/architecture/target/out/phase5_gaps.md:371`) leaves open whether they are dead. **A5.4 closed FALSE in X1** — 82 are called from `tests/` — so 94 of the 106 were never candidates for anything, and the ~12 that remain are too small to be worth deferring separately. |
| `TargetPosition.target_usd` as a settled unit | Now settled (§I.8) but it is a *finding*, not a sound boundary — a float dollar exposure is the weaker half of I-05. |

---

### I.6 Two entries restated more narrowly than Phase 5 wrote them

A do-not-change list that overstates its entries is worse than a short one,
because the overstatement is what gets quoted in a review while the real
boundary goes unguarded.

**I-02 is a total order over the market-data ingress stream, not over the event
log.** Phase 5 reads "Deterministic total order on merge — `_TYPE_RANK` plus
`event_merge_sort_key` give a total tie-break." Measured, `_TYPE_RANK` is
`{NBBOQuote: 0, Trade: 1}` — **two types, not 21** — and
`event_merge_sort_key` is typed to accept only `NBBOQuote | Trade`
(`src/feelies/storage/event_resequence.py:30,33-35`). Derived events never reach
this key at all; their order comes from the `SequenceGenerator` and the bus's
depth-first dispatch, which is a different mechanism with a different failure
mode. The narrower claim is the true one and it is still worth protecting — but
anyone reading Phase 5's sentence would believe the platform has a declared total
order over all events, and it does not. That belief would make S-09's and S-23's
new event types look like they need `_TYPE_RANK` entries, which they do not.

While re-verifying this I found **a second, independent encoding of the same
ordering rule**: `src/feelies/ingestion/massive_ingestor.py:43-44` defines its own
`_TYPE_RANK_QUOTE = 0` / `_TYPE_RANK_TRADE = 1` and sorts raw dicts with a lambda
whose comment says "Mirror the canonical merge key." It does not mirror it — the
canonical key's second component is `symbol` and the ingestor's key omits it
entirely, sorting on `(sip_timestamp, type_rank, sequence_number)`. The outcome is
nonetheless correct, because `append_batch` re-sorts each chunk with the canonical
key and `_enforce_market_order` raises `CausalityViolation` on any backward step
across chunks. So **the safety net is the guard raising, not the mirror being
accurate** — and the comment claims a correspondence that does not hold, which is
the kind of claim a future reader would rely on. This is a two-sources-of-truth
finding of the same shape as G46, and it is not in Phase 5's gap table. Recorded,
not fixed.

**I-05 is a `Decimal` boundary at the fill, not `Decimal` end to end.** Phase 5
reads "Money is `Decimal` end to end, which is what makes P&L reductions
order-free." Measured field by field in `src/feelies/core/events.py`, the
partition is exact and it is not arbitrary:

| Side | Type | Fields |
|---|---|---|
| Realised — the book of record | `Decimal` | `Trade.price`, `OrderRequest.limit_price`, `OrderAck.fill_price`, `OrderAck.cost_bps`, `PositionUpdate.avg_price`, `PositionUpdate.realized_pnl`, `PositionUpdate.unrealized_pnl`, `PositionUpdate.cost_bps` |
| Intended and estimated | `float` | `TargetPosition.target_usd`, `SizedPositionIntent.expected_turnover_usd`, `SizedPositionIntent.expected_gross_exposure_usd`, `SizedPositionIntent.disclosed_cost_total_bps_by_symbol`, `Signal.disclosed_cost_total_bps`, `Signal.reversal_cost_estimate_bps`, `OrderRequest.g12_disclosed_cost_total_bps`, `SafetyStateChange.disclosed_cost_total_bps` |

The boundary is defensible: exactness is required where values **accumulate into
a book** and merely useful where they are estimates consumed once. Basis points
are ratios and float is the right type for them.

But the restatement changes which control is load-bearing. Phase 5's sentence
implies order-free reduction is guaranteed by the type system. It is not:
`expected_gross_exposure_usd` and the per-family gross shares are floats that
**are** summed, in engine 6, which is precisely why I-13's `fsum`-over-sorted-keys
discipline exists. **I-13 is the compensating control for I-05's boundary, and
neither entry says so.** That coupling is why S-26 is the most dangerous
non-P0 step in the plan (§I.7).

---

### I.7 Three conflicts between this list and Deliverable G

Phase 5 could not produce this section because the plan did not exist. These are
not risks to monitor; two need a decision before their step is written and one
needs a line added to a step block.

#### I.7.1 S-08 versus I-19 — a P0 fix that breaks a clean prohibition. **Blocker.**

G03 is a P0: order submission is not idempotent across restart, so a crash
between wire and ack can double-submit. S-08 closes it with a **durable journal,
written before the wire**. `disk_io` currently measures **0 hot sites** and
`serialization` **0 proven per-event sites** (`hotpath.json`). Journal-before-wire
adds both to the order-submission path, which runs inside tick processing.

The two cannot both hold as specified. What makes this a blocker rather than an
accepted cost is that the resulting latency is **unbounded, not merely larger**:
an fsync can block for milliseconds under memory pressure, and the platform has no
live latency measurement at all. Phase 5's assumption **A5.5** — that 136.2
µs/quote is representative of the live path — is still open, and Phase 6 §8 states
the consequence bluntly: "**X10's budget is therefore specified against a
measurement the live path does not yet produce**"
(`docs/architecture/target/out/phase6_conformance.md:1559`). So the property would
stop being sound in exactly the mode where the breach cannot be observed.

(A5.n are Phase 5 **assumption-register** ids from
`docs/architecture/target/out/phase5_gaps.md:369-374`, not subsections of
Deliverable A, which ends at §A.4. Deliverable J carries them forward.)

Three ways out, with the trade named:

1. **Journal in backtest memory, fsync only in live.** Preserves the measured
   property on the oracle's path and keeps the P0 closed where it matters, since
   a backtest has no restart to be non-idempotent across. Cost: it is a mode
   branch in the write path, which threatens I-11, and it means the fsync is
   never exercised by the parity oracle.
2. **Journal to an append-only buffer with the fsync barrier before the *first*
   order of a tick rather than before each order.** Amortises the syscall. Cost:
   a crash can lose the tail of a tick's orders, so idempotency becomes
   per-tick rather than per-order — which may be sufficient, but is a weaker
   guarantee than G03 asks for and must be stated as such.
3. **Accept it and budget it.** Cost: X10's budget from S-07 must then carry an
   explicit disk-I/O allowance, and I-19 loses `disk_io` as a member. Honest,
   and it makes the cost visible rather than hidden.

**Recommendation: (1), with the mode selection at the composition root and
nowhere else.** It is the only option that keeps both the P0 closed and the
measured path clean, and the I-11 exposure is containable because S-08 already
specifies that mode selection happens in `src/feelies/bootstrap.py`. Option 3 is
the honest fallback if (1)'s branch cannot be confined. **This decision must be
made before S-08 is written, not during review**, because it determines the
step's file list.

#### I.7.2 S-12 versus I-15 — do not route the kill switch through the bus

Stated in full at I-15. The short form: G28 says `KillSwitchActivation` has zero
subscribers. That is a **notification** defect, not a control defect — the
control is four direct synchronous reads and it works. The fix is to give the
event an observer. The fix is **not** to make the tick-path check depend on
delivery.

This needs one line added to S-12's block: *the four direct kill-switch reads at
`src/feelies/kernel/orchestrator.py:759,1033,1070,1561` are unchanged by this
step.* Without that line, a correct-looking diff can convert the platform's most
reliable safety control into its least reliable one, and X9 as currently specified
would not necessarily catch it.

#### I.7.3 S-26 versus I-13 — consolidating into the disciplined package dilutes it

S-26 merges three reducers into one, and the survivor lives in `composition/` —
the package holding the platform's best float discipline (I-13). The two reducers
being merged in, `_select_bus_signal` in the kernel and
`src/feelies/alpha/arbitration.py`, do not have it.

Nothing catches dilution. Float addition is order-dependent at magnitudes far
below the `.6f` hash tolerance, so the parity oracle would not move, and R8's
seed-shuffle does not reliably reorder a small dict. S-26's block should require
that every sum in the consolidated reducer is `math.fsum` over a sorted key list,
and C6 should assert the identity rather than the implementation.

---

### I.8 One open question settled while re-verifying

§A.3 nominated the engine-6/8 sizing asymmetry as the claim "more likely to be
factually wrong than architecturally wrong", and said one field read would settle
it. Reading it settled it.

`SizedPositionIntent.target_positions` is `dict[str, TargetPosition]`
(`src/feelies/core/events.py:697`), and `TargetPosition.target_usd` is documented
at `:546-547` as **"the signed dollar exposure (positive = long, negative =
short)"** (`:564`).

So **engine 6 emits signed USD notional per symbol — not weights, not shares.**
The consequences are concrete:

- Engine 8's `_compute_target_quantity` is genuinely absent from the PORTFOLIO
  path because engine 6 has already done that conversion. Phase 2's asymmetry is
  real and correctly described, and Phase 3's decision to place engine 8 at hop
  29 on the SIGNAL path and nowhere on the PORTFOLIO path is right.
- On the PORTFOLIO path engine 8 **vetoes and scales what engine 6 already
  sized**, so its monotonicity guarantee is a guarantee about a reduction, not
  about a sizing.
- The docstring at `:553-557` explains why: the ranker "folds each contributing
  signal's `edge_estimate_bps` into a raw score and then z-scores it, so a final
  weight is a cross-sectional *ordering*, not an expected return." A weight does
  exist inside engine 6; the USD conversion happens before emission.

**This unblocks S-24, and it settles both of the fields S-10 was told to dispute.**
S-10's PARITY IMPACT field names two fields Phase 2 could not assign a unit to and
rules that either must be marked `undetermined` and block S-24 rather than be
guessed. Neither needs to be:

- `SizedPositionIntent.target_positions` — **signed USD notional per symbol**,
  documented at `src/feelies/core/events.py:546-547`. Not weights, not shares.
- `disclosed_cost_total_bps_by_symbol` — **one-way cost in basis points, per
  symbol**, declared by the field comment at `src/feelies/core/events.py:702`:
  "Per-symbol one-way cost disclosed by the consumed signals."

The second carries a hazard worth naming while S-10 is still being written. Inv-12
states the bar as `expected_edge > 1.5× round_trip_cost`, so a consumer that reads
this one-way figure as a round-trip cost understates the bar by a factor of two.
I have **not** verified how the cost gate consumes it — that is a read S-10 should
do when it declares the unit, and it is the kind of error a unit declaration exists
to prevent. Recorded as a question for S-10, not as a defect.

So S-24's dependency on S-10 can be dropped, and S-10 declares two units rather
than discovering them.

`TargetPosition` is also **not** an `Event` subclass — it is a value object nested
inside the intent, with no `sequence` and no `timestamp_ns`, so it sits outside
the sequence-authority rule S-13 registers. Worth knowing before S-13 tries to
assign it a producer.

---

### I.9 Where the plan strengthens the list

Four entries end the plan stronger than they began, which is worth recording
because the same steps appear in §I.7 as threats and the ledger should be net.

| Entry | Step | Change |
|---|---|---|
| I-04 no global fan-in | S-12 | `subscribe_all` deleted, so the property holds by absence rather than by nobody calling it. |
| I-08 random-seed CI | S-02 | The determinism job gains the parity oracle, so the seed guard covers the strongest regression test rather than only the hash suite. |
| I-18 alpha-agnosticism | S-29 | The one real leak is removed; literals go from 3 to 1 (the remaining occurrence being a docstring). |
| I-06 parity surface | S-17 | Engines 1 and 11 gain baselines, closing two of the five deliberate exclusions. |

---

### Verification performed on Deliverable I

**Re-verification, not carry-forward.** `tools/arch/p7_dnc.py` was written this
session and re-checks 12 of the 24 entries mechanically against current source;
`tools/arch/evidence/p7_dnc.json` holds the measured values. **12/12 hold.** The
remaining 12 were re-verified by reading the cited lines this session — I-06's
manifest and closure tests, I-07's `_reject_sequence_reuse` and the terminal
`frozenset()`, I-10's three subscriptions, I-12's four exchange-time comparisons,
I-13's `sorted` + `fsum`, I-14's declared read path, I-15's four direct reads,
I-16's and I-19's prohibition rows in `hotpath.json`, and I-20's acceptance lock.

**Three checker defects found and fixed, not silently corrected.** The first run
reported I-05, I-17 and I-18 as changed. All three were my errors:

- **I-18** — I derived alpha ids from directory names under `alphas/`, so
  `alphas/research/` became an "alpha id" named `research` and matched that
  substring in 30+ unrelated lines. Corrected to read ids from `*.alpha.yaml`
  filenames, which reproduces Phase 5's count exactly: 11 declared, 3 sites.
- **I-17** — I searched for a raise near the matrix name. The assertion is inside
  a function, so the search missed it; what makes it load-bearing is the bare
  module-level call. Corrected to look for the invocation, which also surfaced
  **two sibling checks Phase 5 does not mention**, strengthening the entry.
- **I-05** — the checker pass-failed the whole claim and so reported a
  regression. Rewritten to locate the boundary instead, which produced §I.6's
  restatement. **A pass-fail check on an overstated claim reports a defect that
  is not there and hides the scope error that is.**

**One citation ambiguity fixed.** I cited A5.4 and A5.5 as though they were
subsections of Deliverable A, which ends at §A.4. They are Phase 5
assumption-register ids. Deliverable G already cites them this way in four places,
so the ambiguity is inherited rather than introduced; it is now disambiguated at
first use in §I.7, the same way `CORE §G.10` is disambiguated from `G.10`.

**Two entries restated, one candidate refused, one gap-shaped finding recorded.**
I-02 and I-05 are narrower than Phase 5 wrote them (§I.6). `enforce_layer_gates`
absent from `configs/` was refused promotion because it means two load gates ship
advisory (§I.5). The duplicate `_TYPE_RANK` encoding in
`src/feelies/ingestion/massive_ingestor.py:43-44`, whose "mirror the canonical
merge key" comment does not hold, is recorded as a finding under the guardrail —
not fixed, and not added to Phase 5's table, which is closed.

**Coverage against Phase 5.** All 20 candidates from Phase 5's list are promoted
as I-01 through I-20 with numbering deliberately aligned, so a reader can
cross-reference without a mapping table. Four more are promoted from Phase 6 §8.2
as I-21 through I-24. Total: **24 promoted**, with two items refused for stated
reasons (§I.5) — neither of them a Phase 6 item, since the one I initially refused
is now I-24.

**Conflicts against Deliverable G.** Every entry was checked against all 35
steps, and the mapping was then measured rather than asserted: **23 of the 24
entries have at least one threatening step, and 24 distinct steps appear as a
threat to something.** Only I-02 is untouched by the plan. I first wrote
"fifteen" here from memory and the check caught it — the corrected figure is
uncomfortable and it is the point of the exercise: a plan that touches all but one
sound boundary is a plan that needs this list. Three conflicts are material enough
to change a step (§I.7); one of those, S-08 versus I-19, is a **blocker requiring
a decision before the step is written**, because a P0 fix and a clean prohibition
cannot both hold as currently specified. Four entries are strengthened by the plan
(§I.9).

**Unverified.** I have not run the conformance suite — it does not exist yet, so
every "GUARD" line is a claim about a specified test, not a passing one. The
threat mapping in `THREATENED BY` is **INFERRED** from step blocks in Deliverable
G, not measured: it reflects the file lists those steps declare, and a step that
touches a file it did not declare could breach an entry I marked unthreatened.

---

## J. Assumption and unknowns register

### J.0 Scope: thirteen new, nineteen inherited

This register has two halves. **§J.1 is new**: the assumptions I made while writing
Deliverables A, G and I, which did not exist before this phase. **§J.2 is
inherited**: the entries from earlier phases that are still open *and* that a step
in the plan depends on — measured, not recalled, from
`tools/arch/evidence/p7_assumptions.json` (12 register entries across Phases 4–5,
plus Phase 0's 9-entry unknowns register at
`docs/architecture/target/out/phase0_comprehension.md:941`, of which 7 remain
open).

Carrying the inherited half forward is not optional bookkeeping. The plan locks
after Deliverable K, and **two inherited entries are load-bearing for decisions
already made in it**: A5.4 carries the plan's entire headline net-negative, and
U-8 decides whether "all 26 baselines hold" — the acceptance criterion of 31 of 35
steps — means what it appears to mean. A register that listed only my own new
assumptions would omit the two that matter most. **X1 vindicated this: A5.4 was
tested before S-01 and it was false**, which moved the headline from −73 to +22
public symbols. Had it stayed off the register, the plan would have executed
S-31 against a number that was never a deletion list.

Each entry carries the four fields P7 requires. `FALSIFIED BY` states a check
someone could actually run, not a restatement of the doubt.

---

### J.1 New in Phase 7

```
A7.1  Parity impact is derivable from sequence-draw changes
ASSUMPTION:   Because `sequence` is the leading field of nearly every parity hash
              helper, a step that changes neither the number nor the order of
              draws from a shared `SequenceGenerator` cannot move a baseline —
              and one that does moves every downstream baseline in that space.
WHY NEEDED:   P7 requires every step to state its parity impact and forbids
              "hashes will change" without a reason. 35 steps against 120 hash
              helpers is not an analysis anyone would read; this rule reduces it
              to one question per step, which is what made the PARITY IMPACT
              field answerable at all.
FALSIFIED BY: Either of two checks, both runnable today and neither needing a
              step to exist: (1) enumerate the 120 helpers and confirm each
              leads with `sequence` — a helper that does not is insensitive to
              draws and my rule would over-predict breakage for it; (2) find a
              step whose draws are unchanged but which touches a field some
              helper hashes, which would make the rule under-predict.
BLAST RADIUS: Every PARITY IMPACT line in the plan, and G.7's re-pin schedule.
              Under-prediction is the dangerous direction: a baseline moving in a
              step that declared "all 26 hold" surfaces as a surprise mid-wave
              failure, which is precisely the unattributable case AGENTS.md
              documents for the min-order-floor commit.
```

```
A7.2  Pure method moves preserve parity
ASSUMPTION:   Moving a method body from the orchestrator into an engine, with the
              orchestrator retaining a delegating call, changes no hash — same
              computation, same order, same publisher.
WHY NEEDED:   Wave D is 12 of 35 steps and 9 of them claim all 26
              baselines hold. Without this assumption each move needs its own
              parity argument, and the wave's "no behaviour change" framing —
              which is what makes the moves reviewable — does not survive.
FALSIFIED BY: Any Wave D step breaking a baseline. There are exactly two
              mechanisms by which it could, and both are inspectable before the
              move: the moved code draws from a `SequenceGenerator` in a
              different relative order than before, or it reads instance state
              that differs on the new owner. S-19's instruction to move
              `_maybe_publish_hazard_spike` last, because it draws from
              `self._hazard_seq`, is this assumption's one acknowledged
              exception — which means the mechanism is real and I have found it
              once.
BLAST RADIUS: S-19 through S-28. If wrong in general, each move needs a declared
              re-pin, and the review problem inverts: a genuine behaviour change
              would then hide behind an expected hash movement.
```

```
A7.3  The net-delta ledger's per-step projections are approximately right
ASSUMPTION:   The per-step Δ modules, Δ public symbols and Δ branch points in G.6
              are close enough that the running totals mean something.
WHY NEEDED:   CORE §G.10 requires a net-complexity justification for the plan as
              a whole. The steps do not exist, so the deltas cannot be measured;
              a plan with no complexity accounting would not satisfy §G.10 at
              all.
FALSIFIED BY: Re-measuring after each step with the same scanners that produced
              the baseline of 196 modules, 551 public symbols and 356 branch
              points. G.0.2 already labels every delta INFERRED and makes
              re-measurement an acceptance condition rather than a nicety.
BLAST RADIUS: The headline claim, which has already moved once. G.6 note 2
              named the dominant sensitivity — −106 of the symbol reduction was
              S-31 alone and depended on A5.4 — and **X1 closed A5.4 FALSE**,
              so the claim is now **+22 public symbols and −25 branch points**,
              not −73 and −25. The headline was one assumption deep and that
              assumption did not hold; what remains is −25 branch points, which
              rests on the enumerated gate-registry rows rather than on a
              static measure.
```

```
A7.4  Steps revert in reverse order, not arbitrarily
ASSUMPTION:   P7 requires each step to be independently revertible and I wrote
              `ROLLBACK: revert` on most of them. The true statement is weaker: a
              step reverts cleanly **if the steps after it are reverted first.**
WHY NEEDED:   Nothing required me to assume this — I asserted it, and stating the
              weaker true version is the correction rather than a defence. S-01
              creates the conformance registry that every later test registers
              in; reverting S-01 with S-05 landed leaves a test registered
              against a registry that no longer exists.
FALSIFIED BY: Revert any single step out of order and run the suite. The
              artifact-creating steps whose dependants make out-of-order revert
              unsafe are S-01 (registry), S-11 (gate registry), S-12 (wiring
              manifest) and S-13 (sequence authority).
BLAST RADIUS: The plan's shippability claim, not its correctness. In practice the
              rollback unit is a wave boundary rather than a step, and that is
              how it should be written in the step blocks — `ROLLBACK: revert`
              is accurate for the most recent step and misleading for any other.
```

```
A7.5  "All 26 baselines hold" means the behaviour did not change
ASSUMPTION:   The parity surface is a sufficient detector for the kinds of change
              this plan makes.
WHY NEEDED:   It is the acceptance criterion for 31 of the 35 steps. Every step
              that claims to be behaviour-preserving proves it this way.
FALSIFIED BY: **U-8, which is open and was supposed to close two phases ago.**
              Phase 0 D-12 demonstrated that `tools/arch/parityscan.py` unions
              field names across all 120 helpers, so per-event coverage is a
              union-of-names **upper bound**; Phase 1 §6 recorded that it
              "remains open and should be resolved before Phase 5" and Phase 2
              assigned it to engine 12 saying "Phase 5 needs it"
              (`docs/architecture/target/out/phase2_contracts.md:1420`). It did
              not close. The check is one script: attribute each helper to the
              event type it hashes via its `_REPLAY_BY_NAME` entry and recompute
              coverage per stream. Two further known blind spots compound it —
              hash inputs are hand-written field lists, so **adding a field
              cannot break parity** (I-06), and the `.6f` tolerance hides small
              float drift (A7.9).
BLAST RADIUS: The entire validation story. A step can be green on all 26
              baselines and still have changed substance that no helper hashes,
              and 30 steps would report success. **This is the assumption I would
              close first**: it is the cheapest in the register to settle and the
              most expensive to be wrong about.
```

```
A7.6  A backtest is never resumed mid-run, so S-08 option (1) closes G03 where it matters
ASSUMPTION:   Journaling to memory in backtest and fsyncing only in live leaves
              no idempotency hole, because a backtest has no restart across which
              a submitted order could be lost.
WHY NEEDED:   It is the premise of the recommendation in §I.7.1, which is the
              only way I found to close a P0 without breaking I-19.
FALSIFIED BY: A resumable replay. Checked this session: the checkpoint/restore
              machinery is real but serves two other purposes —
              `_restore_feature_snapshots` at
              `src/feelies/kernel/orchestrator.py:5423` is a session-open **warm
              start** for regime state, called once from `:930`, and
              `src/feelies/ingestion/massive_ingestor.py:14-16` resumes an
              interrupted **backfill ingest**. Neither resumes a partially
              executed order flow. `restore_risk_state` and
              `src/feelies/promotion/lifecycle.py:761` are likewise state restoration, not
              run resumption. So the assumption holds today; it would stop
              holding the moment a mid-session replay resume is added.
BLAST RADIUS: The S-08 decision alone. If wrong, option (3) — accept the disk
              cost and budget it explicitly — becomes the answer, and I-19 loses
              `disk_io` as a member.
```

```
A7.7  The 53 gates are a complete enumeration
ASSUMPTION:   Phase 3's 19 governance plus 34 runtime gates are all of them, so
              S-11 can build the registry as 53 rows of data.
WHY NEEDED:   S-11 creates the registry from Phase 3's ladders and asserts its own
              completeness against them, in the shape of I-17. An assertion is
              only as good as the set it closes over.
FALSIFIED BY: A gate found during S-11 that appears in neither ladder. The count
              came from `tools/arch/evidence/gatescan.json`, which finds gate call
              sites **by pattern**, so a gate implemented without the pattern is
              invisible to the scan that produced the number.
BLAST RADIUS: S-11, S13 and X6, and contained in the benign direction: an
              under-count means the registry gains rows, which is additive. The
              damaging version is a **runtime gate mis-classified as
              governance**, because it would be registered as cold and never get
              a per-event verdict record — the same conflation Phase 3 flagged
              when it called U-6 blocking for this axis.
```

```
A7.8  Phase 6's tests detect the gaps they are mapped to
ASSUMPTION:   The gap-to-test mapping in `tools/arch/evidence/p7_index.json` means
              each gap's test fails while that gap's defect is present.
WHY NEEDED:   G.8's coverage table and every step's VALIDATED BY line rest on it.
              What I verified was that the mapping is **complete** — every gap has
              a test — not that it is **effective**.
FALSIFIED BY: AGENTS.md's mutation procedure, run per test: break the guard,
              confirm the new test fails, restore, confirm it passes again. That
              document exists because this exact assumption failed before — five
              defects in #220 and one in #221 hid behind fixtures covering only
              the input shape the buggy logic happened to handle, and #221's test
              never reached the `max()` it was written to pin.
BLAST RADIUS: All 45 gaps. A test that passes over a live defect is worse than no
              test, because it converts an open question into a false claim of
              closure — and the plan's own G.8 table would then read as complete.
              **At minimum the four P0 tests (X4, X5, X10, H2) should carry a
              recorded mutation proof**, which no step block currently requires.
```

```
A7.9  Float drift from a diluted `fsum` sits below the parity tolerance
ASSUMPTION:   If S-26 loses I-13's `fsum`-over-sorted-keys discipline, the
              resulting drift is too small to move a baseline — which is why I
              called that dilution undetectable.
WHY NEEDED:   It is the reason §I.7.3 ranks the S-26 conflict as needing a change
              to the step block rather than relying on an existing guard.
FALSIFIED BY: Computing the magnitude on real gross-share vectors and comparing
              it against the `.6f` rounding the hash helpers apply. If drift
              exceeds the tolerance, the oracle does catch the dilution and the
              conflict is milder than I stated.
BLAST RADIUS: The severity ranking, not the direction — losing the discipline is
              a defect either way. Worth measuring because it is cheap and either
              retires the concern or promotes it above a step-block note.
```

```
A7.10 Deliverable I's threat mapping is inferred from declared file lists
ASSUMPTION:   The `THREATENED BY` column reflects what each step actually
              touches, derived from the FILES line in its block.
WHY NEEDED:   Measuring it requires the steps to exist. The mapping is the main
              contribution of Deliverable I, so an inferred version is worth more
              than none.
FALSIFIED BY: A step touching a file it did not declare — likely at least once
              across 35 steps.
BLAST RADIUS: Narrow, and asymmetric. An over-broad threat costs a reviewer's
              attention; a **missed** threat costs a boundary. Since I-02 is the
              only entry marked `none`, the whole exposure of the second kind is
              one row, and I-02's guard (`CausalityViolation` on any backward
              merge key) is independent of the plan.
```

```
A7.11 The plan is run to a wave boundary rather than abandoned mid-way
ASSUMPTION:   Stopping early is safe. I ordered the plan by risk and asserted
              that each step ships independently, but I never checked what the
              platform looks like if the programme stops — and the honest reading
              is that **not every stopping point is safe.**
WHY NEEDED:   35 steps, 45 new test modules and 23 threatened boundaries is a
              large programme, and programmes this size are commonly stopped
              part-way. An ordering that is only safe if fully executed is a
              worse ordering than one that degrades gracefully.
FALSIFIED BY: Nothing measurable — this is a programme risk, not a technical
              claim. What can be stated is which boundaries are safe:
              • **After Wave A — safe and independently valuable.** No `src/`
                behaviour change at all; the xfail(strict=True) suite documents
                every gap as an executable claim. Strictly better than today.
              • **After Wave B — safe.** The four P0s are closed.
              • **After Wave C — the dangerous one.** Registries, manifests and
                contracts exist *alongside* an intact god orchestrator: two
                sources of truth for ownership, which is the exact condition this
                review keeps identifying as a defect (G46, and I-02's duplicate
                `_TYPE_RANK` encoding). **If the programme is likely to stop
                here, it is better not to begin Wave C.**
              • **After Wave D — safe.** Ownership has moved; only cost work is
                outstanding.
BLAST RADIUS: The platform's end state. This is the entry with the largest
              consequence and the least evidence, which is why it is stated
              rather than left implicit in the wave ordering.
```

```
A7.12 Claims I sourced from documentation are backed by code
ASSUMPTION:   Where I cited the glossary, a skill, or a prior phase for a
              behavioural fact rather than reading source, the code agrees.
WHY NEEDED:   Six prior phase documents and the platform glossary are the fastest
              route to a claim, and re-deriving every one from source is not
              affordable inside one phase.
FALSIFIED BY: Reading the code — and **one instance is already found and
              corrected.** §I.5 refused a do-not-change candidate on the reasoning
              that the glossary says "if false, only G1/G3 downgrade to warnings",
              from which I inferred that the key's absence from every config meant
              the gates ship advisory. The default is `True` in all four
              declarations (`src/feelies/core/platform_config.py:339` and `:1106`,
              `src/feelies/alpha/layer_validator.py:234`,
              `src/feelies/alpha/loader.py:221`), so absence means **strict** —
              the opposite of what I wrote. The candidate is now I-24. The
              glossary sentence was accurate; my inference from it was not,
              because it describes the semantics of the flag and says nothing
              about its default.
BLAST RADIUS: Unquantified, which is the point of recording it. Every VERIFIED
              label in Deliverables A, G and I that traces to a document rather
              than a `path:line` is exposed. The cost here was one refused
              candidate; the same inversion inside a P0 step block would cost
              more, and the guardrail states the rule I broke — code is truth,
              documentation is a claim.
```

```
A7.13 S-07's latency budget is a p99 budget, not a mean
ASSUMPTION:   That "the per-engine budget as config data" in S-07 means a p99
              budget over a defined sample window. **The step block never says
              so** — it names neither the statistic nor the window.
WHY NEEDED:   I wrote S-07 against Phase 4's budget table and treated "budget" as
              a term Phase 4 had already defined, so I did not restate it.
FALSIFIED BY: Reading Phase 4 §6 against S-07's block. Phase 4 rules explicitly:
              "**Percentiles, not means.** Budgets are p99 targets ... a
              mean-based gate would pass a system whose p99 had doubled", and
              measures the ratio at **3.9×** — 0.112 ms mean against 0.432 ms p99
              (`docs/architecture/target/out/phase4_performance.md:526-529`).
              Phase 4 also warns at `:224` that the 136.2 µs/quote per-engine
              figures and the tick-to-decision p99 "are different things — a p99
              tick segment versus a mean per event".
BLAST RADIUS: G43, which is a P0. A mean-based predicate would satisfy X10 — whose
              closure assertion is that *every hot-path engine has a budget
              entry*, not that the predicate is right — while failing to detect
              the condition the P0 exists to catch, and would make the
              kill-switch escalation both late and jittery. **S-07's block needs
              the statistic and window stated before it is written**, and this is
              a concrete instance of A7.8: a closure test passing over a wrong
              predicate.
STATUS:       **Closed.** S-07 step (1) now declares p99 over a rolling event
              count and cites Phase 4's 3.9× ratio as the reason the statistic
              must be named; step (2) adds the fail-closed rule for an
              uncomputable statistic, which §K.1.2 requires of any safety-critical
              metric. This is no longer an assumption — it is in the block.
```

---

### J.2 Inherited, still open, and depended upon by a step

Measured from `tools/arch/evidence/p7_assumptions.json`. Every row is open. The
`Depended on by` column is what makes them Phase 7's problem rather than history.

#### J.2.1 The Phase 4 and Phase 5 registers — all 12 still open

| ID | Assumption | Depended on by | If wrong |
|---|---|---|---|
| A4.1 | The N=8 sensor scaling ratio extrapolates toward N=100 | S-33 | S-33 optimises against a projected curve; the real curve could make engine 2's budget unreachable or already met |
| A4.2 | A thread-CPU-time clock would separate compute cost from OS preemption | S-07, S-33 | Budget breaches conflate "our code got slower" with "the host was busy", and the reduce-only response fires on the latter |
| A4.3 | The 20 unread event fields are genuinely unread, not reached via serialization | **S-31** | S-31 deletes them. A field read only through a serializer is invisible to the scan that found them |
| A4.4 | `NBBOQuote` construction cost (1,241.6 ns) is a live-path cost, not replay setup | S-07, S-32 | The live budget is set against a cost the live path does not pay, or pays differently |
| A4.5 | 22.6 µs/quote marginal cost per sensor is representative of unmeasured sensors | S-33 | Engine 2's optimisation target is wrong in magnitude |
| A4.6 | Sensor registration is output-neutral for alphas other than `sig_benign_midcap_v1` | S-33, S-17 | Adding or reordering sensors changes signals, and S-33's "all baselines hold" fails for a legitimate reason |
| A5.1 | IB rejects a re-submitted duplicate `order_id` server-side, bounding G03 | **S-08** | G03's blast radius is larger than P0-with-containment: nothing outside our journal prevents the double fill. **U-3 is the same question from the other side** |
| A5.2 | The 3 order-insensitive set-iteration sites in G08 remain order-insensitive | S-32 | A hash-order dependence exists that R1's random seed has not yet happened to expose |
| A5.3 | G20 has never fired in any recorded run | **S-05** | The P0 has been silently zeroing positions in recorded history, and S-05's "all 26 baselines hold" prediction is wrong — which S-05 is explicitly written to detect |
| ~~A5.4~~ | ~~The 106 uncalled public methods are genuinely dead~~ — **CLOSED FALSE in X1** | **S-31** | It was wrong, and the consequence it predicted has happened: 82 of the 106 are called from `tests/` and 13 by nothing. S-31 is rescoped −106 → −12, the plan nets **+22 public symbols** (G.6 note 2), and the residue is settled by a coverage gate rather than a third static search |
| A5.5 | 136.2 µs/quote is representative of the live path | **S-07, S-08** | The budget is set against a number the live path does not produce, and the S-08 blocker in §I.7.1 cannot be evaluated at all |
| A5.6 | G41's 4.2× overrun scales with alpha count | S-33, S-26 | The platform's stated purpose — A > 1 — is gated on a performance problem of unknown size |

#### J.2.2 Phase 0's unknowns register — 7 of 9 still open

| ID | Unknown | Depended on by | If wrong / unresolved |
|---|---|---|---|
| U-1 | Whether `RiskVerdict`, `StateTransition`, `SymbolHalted`, `KillSwitchActivation` are consumed by out-of-tree operator tooling | **S-31, S-12** | S-31 deletes the `StateTransition` domain-bus publish and its baseline. If a notebook or runbook reads it off the bus, that is a silent break in tooling no test covers. Phase 2 assigned this to engine 11 and it stayed open |
| U-2 | Whether `_select_bus_signal` arbitration is stable across equal-strength signals from different alphas | **S-26** | The reducer consolidation changes behaviour rather than preserving it, and "parity holds at A=1" hides it because ties need two alphas to occur. Phase 2 §4 resolves this *structurally* for the target via a published tie-break key, and says explicitly that it "says nothing about what today's comparator does" |
| ~~U-3~~ | ~~Whether `broker/ib/` reconciles position-of-record beyond the fill stream~~ — **CLOSED NO in X1** | **S-21, S-30 §F.4** | It does not. All four files under `src/feelies/broker/ib/` were read end to end; the adapter implements three `EWrapper` callbacks (`nextValidId`, `orderStatus`, `error`) and `reqPositions`, `reqAccountUpdates`, `reqAccountSummary`, `reqExecutions`, `reqOpenOrders` and `updatePortfolio` have **zero occurrences in `src/`**. So **§F.4 is a build, not a wiring task**, and WL-2 is discharged in the favourable direction — engine 8's action is designed alongside the reconciliation, so Phase 2's declare/act separation is honoured by construction. **A5.1 is correspondingly weakened**: nothing outside the platform's own journal bounds a duplicate fill |
| U-5 | Whether a multi-symbol run is pinned end to end | **S-17, S-26** | The axis the platform exists to serve is pinned only in isolation. Engine 6 holds four baselines but none is a multi-symbol whole-run oracle, so S-26's consolidation has no end-to-end detector at N>1 |
| U-7 | Actual tick-path latency distribution | S-07 | **Largely closed by Phase 4** — tick-to-decision p99 is 0.432 ms against a 3 ms target — but the per-engine figures remain means, which is what makes A7.13 necessary |
| U-8 | True per-stream parity coverage, versus the union-of-names upper bound | **all 30 steps that claim baselines hold** | See A7.5. This is the highest-leverage open item in the register and the cheapest to close |
| U-9 | Whether the 2 host-sensitive orchestrator exemptions are the only place whole-platform parity is asserted | S-17 | S-17 adds baselines to close deliberate exclusions; if the exclusion list is itself incomplete, it closes the wrong ones |

---

### J.3 Inherited and closed since — recorded because one closure was misread

| ID | Status | Note |
|---|---|---|
| U-4 | **Closed** by Phase 6 §8.2 | `SensorSpec.subscribes_to` cannot name a type outside `{NBBOQuote, Trade}`; enforced by `ConfigurationError`. Promoted here as I-21 |
| U-6 | **Closed** by Phase 6 §8.2 | `enforce_layer_gates` appears zero times in `configs/`. **I read the closure backwards** — see A7.12. Composed with the four `True` defaults it means the gates ship strict, which is now I-24, and it also answers the question Phase 3 called blocking for the gate registry (`docs/architecture/target/out/phase3_flow_gating.md:968`) |

---

### J.4 The three I am least comfortable with

P7 says a register with fewer than five entries is not honest. Thirteen new
entries satisfy the count; what follows is the part that would not be honest to
leave as an unranked list, because these three are not equal to the other ten.

**A7.5 / U-8 — the plan's main verification mechanism is assumed effective, not
shown effective.** Thirty-one of 35 steps prove themselves with "all 26 baselines
hold". Three independent facts say that phrase covers less than it sounds: per-event
coverage is a union-of-names upper bound (U-8, open since Phase 0 and twice
scheduled to close), hash inputs are hand-written field lists so adding a field
cannot break parity (I-06), and the `.6f` tolerance hides small float drift
(A7.9). **Closing U-8 is one script and should happen before S-01.** I did not
write it this phase because the guardrail confines me to `tools/arch/` and
`docs/architecture/target/out/`, and it is a `tests/` question — but that is a
scope explanation, not a justification for shipping the plan without it.

**A7.8 — the plan's other verification mechanism is assumed effective too.** I
verified that every gap maps to a test. I did not verify that any test detects its
gap, and AGENTS.md exists because that exact assumption failed six times in two
prior reviews. Taken with A7.5 this is the register's uncomfortable centre: **both
detectors the plan relies on are assumed rather than demonstrated**, and A7.13 is
already a concrete instance — X10 would pass over a mean-based predicate that
cannot detect the P0 it closes.

**A7.11 — the worst place to stop is the middle, and nothing prevents stopping
there.** After Wave C the platform has registries, manifests and contracts
*alongside* an intact god orchestrator: two sources of truth for ownership, which
is the defect shape this review has found repeatedly. Waves A, B and D are safe
stopping points; C is not. If the programme cannot commit through Wave D, the
right decision is to run Waves A and B and stop — which is a genuinely good
outcome, since it closes four P0s and makes every remaining gap an executable
claim.

---

### Verification performed on Deliverable J

**The inherited half is measured, not recalled.** `tools/arch/p7_assumptions.py`
was written this session and extracts every `A<n>.<m>` register row from the phase
outputs into `tools/arch/evidence/p7_assumptions.json`: **12 entries across
`phase4_performance.md` and `phase5_gaps.md`**, and it reports which ids
Deliverables A, G and I already cite — 6 of the 12, which is why the other 6 needed
finding rather than remembering. Phase 0's 9-entry unknowns register is in a
different format (`U-n`, at
`docs/architecture/target/out/phase0_comprehension.md:941`) and was read directly;
open-versus-closed status for each was established by searching every phase output
for its id, not by assuming Phase 0's list still stood.

**Two claims in Deliverable I were checked and one was wrong.** Before writing this
register I re-checked the two factual claims in Deliverable I that I had sourced
from documentation rather than code. The `enforce_layer_gates` claim was **inverted**
(A7.12) and is corrected: §I.5's refusal is withdrawn, the entry is promoted as
I-24 with all four strict defaults cited, and `tools/arch/p7_dnc.py` now re-verifies
it mechanically — **12 of 24 entries now checked by script, 12/12 holding**. The
backtest-resumability premise behind the S-08 recommendation was checked and
**holds**, with the three checkpoint/restore paths that could have falsified it
named in A7.6.

**One new omission found in Deliverable G.** S-07 specifies a latency budget
without naming its statistic or window, while Phase 4 §6 rules for p99 and measures
a 3.9× mean-to-p99 ratio. Recorded as A7.13 rather than edited into S-07, because
the step blocks are the accepted artifact and this register is the right place for a
defect in them.

**Counts.** 13 new entries (A7.1–A7.13), 19 inherited and open (12 from the Phase
4–5 registers, 7 from Phase 0's unknowns), 2 inherited and closed. P7 requires more
than five; the number is 13 because that is how many I found, and three of them
(§J.4) matter more than the rest.

**One checker bug, worth recording for its shape.** `tools/arch/p7_i_check.py`
initially matched entry headings with a two-space separator, which the two-digit
ids do not use, so it saw 9 entries, reported "contiguous A7.1..A7.9", and
**passed** — hiding four entries and their field checks behind a green result. That
is A7.8's failure shape reproduced in my own tooling within the same session: a
check that passes because it never reached what it was written to inspect. Fixed to
match one-or-more spaces; it now sees 13 and verifies each one's four fields.

**Unverified.** Every `FALSIFIED BY` field names a check that has **not been run** —
that is what makes these assumptions rather than findings. Six of the thirteen are
falsifiable today without any step existing (A7.1, A7.3, A7.5, A7.7, A7.9, A7.13),
and A7.5 is the one to run first. The `Depended on by` column in §J.2 is
**INFERRED** from step blocks, with the same limitation A7.10 states for
Deliverable I's threat mapping.

---

## K. Model findings

### K.0 How this was decided — nine inherited watch-lines, not a fresh hunt

K asks where the 12-engine decomposition itself does not fit, and P7 states that
empty is expected while a forced fit is not. The disciplined way to answer is not
to go looking: **Phases 1–3 already ran this test 23 times and returned "Model
finding: none" every time** — measured, not recalled: once for the plumbing axis,
twelve times for the engine sheets, seven times for the §F resolutions, three times
for the flow and gating axes.

But nine of those twenty-three verdicts are **conditional**. Each names a specific
future observation that would flip it, in the form "if a later phase finds X, this
becomes a model finding." **Phase 7 is the last phase.** Nothing after this
discharges them, so K's job is to decide each one on the evidence now available,
and a "none" that leaves nine conditions dangling is not an answer.

| # | Watch-line | Set by | Verdict |
|---|---|---|---|
| WL-1 | Engine 5's two jobs require different determinism contracts | `phase2_contracts.md:567` | **FIRES** |
| WL-2 | Engine 8 cannot act on divergence without accounting-internal state | `phase2_contracts.md:814` | **cannot discharge** |
| WL-3 | Engine 8's veto cannot be written without mutation | `phase2_contracts.md:936` | does not fire |
| WL-4 | The kill switch needs metric state to decide activation | `phase2_contracts.md:1293` | **FIRES** |
| WL-5 | The exception taxonomy needs an engine's trading semantics | `phase2_contracts.md:1834` | does not fire |
| WL-6 | The schema compatibility rule must branch on what an event means | `phase2_contracts.md:2003` | does not fire |
| WL-7 | The wiring manifest needs an event's meaning to declare an ordinal | `phase3_flow_gating.md:238` | **FIRES** |
| WL-8 | The notification channel needs a payload's trading meaning to route | `phase3_flow_gating.md:507` | does not fire |
| WL-9 | A gate's ordinal depends on what an alpha means | `phase3_flow_gating.md:962` | does not fire |

Three fire. One cannot be decided in this phase and the reason is itself a
finding about the review, not about the model. A fourth finding comes from outside
the watch-lines: Phase 2 found an eighth unassigned responsibility that CORE §F
does not contain, recorded it for the operator, and no phase resolved it (§K.1.4).

---

### K.1 The four findings

#### K.1.1 Engine 5 carries two determinism contracts, not one — WL-1 fires

**The condition.** Phase 2's engine-5 sheet found two jobs with different rhythms —
composition-time resolution, which runs once and must fail the boot, and ongoing
lifecycle management, which runs on an evidence cadence and must fail contained. It
declined to call this a model finding because they share one output surface and one
record, and set the condition: "**If a later phase finds they also require
different determinism contracts, this becomes a model finding**"
(`docs/architecture/target/out/phase2_contracts.md:567`).

**The evidence that discharges it comes from this plan.** S-16 adds the alpha
manifest content hash to the **run fingerprint**, which makes the resolved registry
an input that must be bit-reproducible — that step re-pins `_BASELINE_CONFIG_HASH`
by design. The promotion ledger goes the other way: the glossary defines it as
"append-only JSONL of lifecycle transitions... **never read on the tick path
(forensic only)**", Phase 1 §6.1 records **no manifest entry for engine 5 at all**,
and Phase 2's own call on the same sheet is "**fingerprint the registry, do not
parity-hash the ledger** — one is an input to the run, the other is a durable
record of decisions and should not be expected to reproduce."

So one half must reproduce bit-for-bit and the other must **not be expected to**.
Those are two determinism contracts, and Phase 7 is the phase that made them
explicit rather than merely available. The condition is met.

**Why it is a model finding and not a code gap.** Nothing here is a defect in the
code. The decomposition assigns engine 5 a single contract slot, and the engine
needs two, because the determinism obligation of a *run input* and of a *durable
decision record* are opposites. Any sheet that states "engine 5's determinism
contract" as one clause is stating something false.

**What it costs, and what it does not.** The remedy is a two-surface
specification, not a re-decomposition — exactly the shape Phase 2 already applied
to engine 8 (`evaluate` versus `observe`) and to engine 5's own exception policy,
which it split for the same reason. Engine 5 stays one engine. What changes is that
its contract sheet carries two determinism clauses and S-16's fingerprint must be
scoped to the registry with the ledger explicitly excluded — **which S-16's block
does not currently say.**

#### K.1.2 The model puts a fail-closed control and a fail-open reporter in one engine, then makes the control depend on the reporter — WL-4 fires

**The condition.** Phase 2's engine-11 sheet observed that engine 11 holds
observability (cold, best-effort, must never break trading) and safety (the kill
switch — hot-read, fail-closed, must break trading), that these have **opposite
failure directions**, and that CORE §E puts them in one engine. It reconciled them
on the ground that the kill switch is a single boolean read structurally separate
from the metrics machinery, and set the condition: "**If a later phase finds the
kill switch needs metric state to decide activation, that dependency inverts and
this becomes a model finding**" (`docs/architecture/target/out/phase2_contracts.md:1293`).

**It needs metric state, and CORE §E is what requires it.** The kill switch is
activated from a realized-cost computation at
`src/feelies/kernel/orchestrator.py:4498-4504`, with
`reason="realized_cost_persistent_overrun"`, where the deciding `escalate` boolean
comes from cost tracking — and `src/feelies/harness/backtest_report.py:788` records
that `cost_bps` is "the realized cost the B4 gate and
`feelies.forensics.cost_circuit_breaker` read to quarantine an alpha." This is not
drift from the model. CORE §E's engine-11 row **mandates** it: "Kill switches
monitor *assumption violations* — latency drift, fill-rate drift, regime break,
contract rejection rate, reconciliation divergence — as well as P&L."

**So the finding is not "activation uses metrics" — it is that the model requires
the fail-closed half to consume the fail-open half and never says how.** Phase 2's
reconciliation ("the safety surface holds no dependency on the observability
surface") is not compatible with §E's own mandate. The read direction Phase 2
protected is intact and verified — I-15 confirms four direct synchronous reads at
`src/feelies/kernel/orchestrator.py:759,1033,1070,1561` — but the *activation*
direction runs from best-effort inputs into a fail-closed control, and **the model
provides no rule that a safety-critical metric must be computed to a higher
standard than a dashboard metric.**

**This plan makes it worse before it makes it better.** S-07 creates the second
instance: a latency metric becomes safety-critical, because sustained budget breach
escalates the kill switch. A7.13 then records that S-07 never states the budget's
statistic or window, while Phase 4 §6 rules for p99 and measures a 3.9×
mean-to-p99 ratio. So the plan adds a fail-closed control driven by a metric whose
definition is unspecified — the exact hazard this finding names, introduced by the
step that closes a P0.

**What changes.** The target needs a declared class of **safety-critical metric**
with a stronger computation contract than observability metrics: defined statistic,
defined window, defined behaviour when the input is missing, and a fail-closed
default when it cannot be computed. Two metrics are in that class today — realized
cost and, after S-07, tick latency — and neither is declared as such anywhere.

#### K.1.3 The wiring ordinal carries a trading-domain justification — WL-7 fires, and it invalidates S-12's acceptance criterion

**The condition.** Phase 3 set this one with a named suspect: "if the wiring
manifest turns out to need knowledge of what an event *means* to a strategy in
order to declare an ordinal — rather than declaring the ordinal as an opaque
tie-break — the kernel would be acquiring trading-domain content and this becomes a
model finding. **The one live candidate is `src/feelies/bootstrap.py:355`**, and the
resolution above (move the requirement onto fill provenance) is what keeps it from
firing" (`docs/architecture/target/out/phase3_flow_gating.md:238`).

**Read this session, the candidate is real.** `src/feelies/bootstrap.py:355` is a
comment — "Subscribe the router before sensors so fills retain their triggering
quote" — sitting immediately after `src/feelies/bootstrap.py:353` subscribes
`NBBOQuote` to the backtest router. Sensors subscribe to `NBBOQuote` too, so that
type has multiple handlers whose **relative order is justified by a domain fact
about fill provenance**, recorded in prose and enforced by nothing.

**Phase 3's escape hatch is not taken by the plan.** The resolution that would keep
this from firing is to move the requirement onto fill provenance — make the fill
carry its triggering quote explicitly, so subscription order stops mattering. S-12
does not do that. Its refactor path declares the manifest "**from the measured
current order**", which preserves the semantic dependency and writes it into a
kernel artifact. That is the kernel acquiring trading-domain content, which is
Phase 3's stated trigger.

**And it exposes a defect in Deliverable G.** S-12's PARITY IMPACT makes R3 the
proof of correctness: "R3 permutes registration order and asserts an identical hash
— **if R3 fails, the manifest is load-bearing in a way the target forbids and the
step is incomplete**." But `src/feelies/bootstrap.py:355` says permuting that order
changes fill provenance, and Phase 1 §3 measured delivery order as
output-determining. **R3 will fail on `NBBOQuote`, so S-12 as written cannot reach
its own acceptance criterion.** The step is not wrong about what to require; it is
missing the prerequisite. Fill provenance must be made explicit *before* the
manifest is declared, or S-12 permanently reports incomplete.

**What changes.** One step is added ahead of S-12, doing only what Phase 3
prescribed: carry the triggering quote on the fill so that subscription order is no
longer load-bearing. Then the manifest declares an opaque ordinal, R3 can pass, and
the kernel holds no trading-domain content. This is the one finding in K that adds
work to the plan rather than adding a clause to a contract.

#### K.1.4 CORE §F's enumeration of unassigned responsibilities is incomplete

**Not from a watch-line.** Phase 2's engine-2 sheet found "**an eighth unassigned
responsibility, not in CORE §F.1–7: the horizon grid**" — which horizons exist,
when their boundaries fall, and what anchors them — and established that it is "a
fact consumed by at least four places at the same event time, with no single
producer" (`docs/architecture/target/out/phase2_contracts.md:217`). It observed
that this is "structurally identical to §F.1 (universe): several engines must see
the same fact at the same event time, and none owns it", recommended engine 2 as
owner, and then correctly declined to resolve it, because §F resolutions belong to
the pass after all twelve sheets and **this item is not in §F at all**
(`:228`). The §F pass then resolved §F.1 through §F.7 and did not pick it up. No
later phase did either.

**Why this is a model finding rather than an oversight.** CORE §F is the model's own
declaration of where it knows it is incomplete — "None falls cleanly out of §E. For
each: name one owning engine." A responsibility that meets §F's definition exactly,
and is absent from §F's list, means the list is not closed. That is a defect in the
model's self-knowledge, and it is the only finding here that impugns CORE's text
directly rather than an engine boundary.

**Its practical consequence is small and it should still be recorded.** The
recommended owner is uncontested, the fix is one contract, and the horizon grid is
in practice a config constant today. But §F's value is that it is exhaustive — a
seven-item list that turns out to have eight items invites the question of whether
it has nine, and nothing in Phases 0–7 was designed to answer that. **Every §F item
was resolved on the same produce/interpret/apply pattern** (Phase 2 records the
pattern holding across F.1, F.2, F.3 and F.4 and calls the consistency "itself
evidence the 12-engine model is holding"), so the mechanism for resolving a ninth
exists; what does not exist is a method for finding it.

---

### K.2 One watch-line cannot be discharged, and the reason is a review finding

**WL-2 — whether engine 8 can act on a reconciliation divergence without
accounting-internal state.** Phase 2's engine-7 sheet found the one place CORE §E
appears self-contradictory: §E gives engine 7 "the divergence policy" while
simultaneously forbidding it "decisions of any kind", and §F.4 requires the action
on breach to be exposure-reducing, which is a decision. It resolved this by
separating declaration from action — engine 7 declares divergence, engine 8 acts —
and set the condition: "If a later phase finds engine 8 cannot act without
accounting-internal state, this becomes a model finding"
(`docs/architecture/target/out/phase2_contracts.md:814`).

**Deciding it requires U-3, which is still open.** U-3 asks whether `broker/ib/`
performs any position-of-record reconciliation beyond the fill stream. Phase 0
registered it as an unknown because the IB adapter was not read exhaustively; Phase
2 escalated it to "open and **now blocking**", said it "decides whether F.4 is a
wiring task or a build", and stated it "should close before Phase 5"
(`docs/architecture/target/out/phase2_contracts.md:1729`). It did not close before
Phase 5, or 6, or 7. It is carried in §J.2.2 with S-21 and S-30 §F.3 depending on it.

**So the honest verdict is neither fired nor cleared.** If reconciliation must be
built from scratch, engine 8's action is designed alongside it and the separation
can be honoured by construction. If an implementation already exists inside the IB
adapter, its shape decides whether the action can be taken without reading
accounting internals — and nobody has looked. Compounding it, Phase 2 noted that
`paper_rth`-gated tests never run in CI, so even a present implementation is
unexercised.

**This is a finding about the review, not the model.** An unknown that three phases
in a row marked as needing closure before the next phase, and which reached the
final phase open, is the review's own process failing rather than the decomposition
failing. It is also among the cheapest open items to close — Phase 0 named the route
as reading `src/feelies/broker/ib/` end to end and checking for a positions-request
call, one session's work — and it should close before the plan is locked, because a
§F item whose model status is undetermined is not a resolved §F item.

---

### K.3 The five watch-lines that did not fire

```
WL-3  Engine 8's veto cannot be written without mutation      DOES NOT FIRE
CONDITION:   `phase2_contracts.md:936` — engine 8 holds both a per-decision veto
             (hot, per-order, which should be a pure function so it stays
             testable and monotone) and a stateful portfolio-state manager.
             Phase 2's reconciliation was two declared surfaces: a pure
             `evaluate(request, state) -> verdict` and a state-advancing
             `observe(event) -> state`, with the veto never mutating.
EVIDENCE:    **Today's veto does mutate.** The per-alpha drawdown check advances
             the high-water mark inside the decision path:
             `src/feelies/alpha/risk_wrapper.py:155-158` reads `self._alpha_hwm`
             and, on a new high, assigns `self._alpha_hwm[strategy_id] = hwm`
             before computing `drawdown_pct` and returning a REJECT verdict at
             `:164-175`.
WHY NOT:     The condition is impossibility, not current practice. Every input to
             the high-water mark — `alpha_equity`, `realized_pnl`, `fees`,
             `unrealized_pnl` — is available at observe time from
             `PositionUpdate`, so the ratchet can move to `observe()` and leave
             `evaluate()` pure. The split is available; it has simply not been
             made.
BUT NOTE:    **No step in Deliverable G makes it.** S-22 moves four risk methods
             and S-06 fixes the fail-open `except KeyError: pass` in this same
             file; neither splits the two surfaces. Phase 2 specified engine 8's
             `reset()` "over the state surface only", which presumes a split that
             does not exist. This is not a determinism defect — a running maximum
             is order-insensitive and replay stays deterministic — but X1's
             monotonicity property is stated over a function that is not pure,
             which makes it harder to assert than Phase 6 assumes.
```

```
WL-5  The exception taxonomy needs an engine's trading semantics   DOES NOT FIRE
CONDITION:   `phase2_contracts.md:1834` — Phase 2 called F.5 "the closest the
             model has come" to firing, because exception propagation fits no §E
             engine. It did not fire because §E's cross-cutting kernel is part of
             the model rather than an exception to it, and the responsibility is
             framework with no trading-domain calculation.
WHY NOT:     Classification is by whether a fault sits on an exposure-affecting
             leg — a structural property readable from the wiring manifest and
             the gate registry — not by what an alpha means. A failed position
             read (G20) is severe because it is upstream of sizing; a failed
             metric write is not; neither judgement requires knowing which alpha
             is trading or what its mechanism is.
```

```
WL-6  The schema compatibility rule must branch on event meaning   DOES NOT FIRE
CONDITION:   `phase2_contracts.md:2003` — the same shape as WL-5, for F.7.
WHY NOT:     S-09 adds `schema_version` to the envelope as metadata that enters
             no hash helper's field list, and the compatibility rule is a version
             comparison with a refuse-and-fail-loud default. Comparing two
             integers carries no trading-domain content.
```

```
WL-8  The notification channel needs trading meaning to route      DOES NOT FIRE
CONDITION:   `phase3_flow_gating.md:507`.
WHY NOT:     Routing is by payload type. The two things this plan puts on the
             channel — gate verdicts in S-11 and `StateTransition` in S-31 — are
             both routed as records of a structural event, never by what the
             underlying decision meant to a strategy.
```

```
WL-9  A gate's ordinal depends on what an alpha means              DOES NOT FIRE
CONDITION:   `phase3_flow_gating.md:962`.
WHY NOT:     Ordinals in S-11's 53-row registry come from which leg a gate sits
             on. G16 is the closest call, because it caps by trend-mechanism
             family — but the mechanism decides the gate's **verdict**, never its
             position in the ladder, and the family is a closed enum the alpha
             declares rather than something the registry interprets.
```

---

### K.4 Five candidates considered and rejected

P7 warns that a forced fit is worse than an empty answer. These are the
model-finding candidates I formed while writing Deliverables A, G and I, each
refuted by reading CORE or a prior phase rather than by judgement.

| Candidate | Why rejected |
|---|---|
| **The model has no seat for the kernel**, so the god orchestrator had nowhere to belong and accumulated trading logic | Refuted by CORE §E's own text. The cross-cutting paragraph names the kernel — `core/`, `bus/`, `kernel/`, `src/feelies/bootstrap.py` — gives it contracts, clocks, deterministic sequencing, the state-machine framework, causal orchestration and composition, and **forbids it "no trading-domain calculation."** The orchestrator's 4,778 SLOC violate a prohibition the model already states. That is a gap (G40 and the Wave D moves), not a misfit |
| **No engine owns reference data**, so symbol identity across corporate actions is homeless | Refuted by Phase 2's §F pass: "F.1 and F.2 are one artifact resolved at one moment by one engine, which is **a strong fit rather than a forced one**" (`docs/architecture/target/out/phase2_contracts.md:1577`). The remaining problem is that the capability does not exist (G32, the plan's only net-new build), not that the model cannot place it |
| **Sizing lives in engine 6 on the PORTFOLIO path and engine 8 on the SIGNAL path** — the asymmetry §I.8 settled by reading `TargetPosition.target_usd` | Refuted by Phase 2's engine-6 sheet, which already permits either output form: "Engine 6 emits target weight or target notional; engine 8 converts under buying power and limits" (`docs/architecture/target/out/phase2_contracts.md:598`). §E's "target weights" is narrower than Phase 2's contract, so this is drift between two layers of the specification, and a code gap — not a decomposition that fails to fit |
| **Engine 6's transformation is lossy**, so `expected_edge_bps` must be carried through it for a downstream cost gate | Not a misfit. The docstring at `src/feelies/core/events.py:550-557` explains that z-scoring turns edge into an ordering and the edge "cannot be recovered downstream", so the field travels alongside. A pass-through field is the ordinary contract solution to a lossy stage; that the model does not discuss it is not the same as not accommodating it |
| **Engine 3's cardinality is unspecified**, so nobody knows whether it is O(1) or O(N_sym) | Refuted by §E, which says "***Shared*** online market-state classification ... published once" — fixing it as one market-wide classification. Phase 3's open item (`docs/architecture/target/out/phase3_flow_gating.md:215`) is that the *code's* arity is unmeasured, which is a gap |

---

### K.5 Consequences — what each finding changes

| Finding | Change to the target | Change to the plan |
|---|---|---|
| K.1.1 engine 5's two determinism contracts | Engine 5's sheet carries **two** determinism clauses: the resolved registry is a run input and must be bit-reproducible; the promotion ledger is a decision record and must not be expected to reproduce | S-16's fingerprint scoped explicitly to the registry, with the ledger named as excluded. One clause added to one block |
| K.1.2 safety depends on best-effort metrics | A declared class of **safety-critical metric**, with a stronger contract than an observability metric: defined statistic, defined window, defined behaviour on missing input, and fail-closed when it cannot be computed. Two members today — realized cost and, after S-07, tick latency | S-07 states its statistic and window (closing A7.13) and its behaviour when the measurement is unavailable. One clause added to one block |
| K.1.3 the wiring ordinal is semantically justified | The kernel's wiring manifest declares an **opaque** ordinal; fill provenance is explicit on the fill rather than implied by subscription order | **One new step ahead of S-12**, carrying the triggering quote on the fill, per Phase 3's prescribed resolution. Without it, S-12 cannot satisfy its own R3 criterion |
| K.1.4 §F has eight items, not seven | §F becomes an eight-item list; the horizon grid goes to engine 2 as a versioned contract, on Phase 2's recommendation | No new step — the grid is a config constant today, so this is a contract to declare rather than a capability to build. **Resolved in X1** as a marked addendum to `phase2_contracts.md`, and **placed in S-30** — after §F.1, before §F.6 — because that is where the other five §F items land and §F.8 is structurally identical to §F.1. S-30's symbol delta goes +4 → +5 |
| K.1.5 §F has nine items, and Phase 2 said so | **Added in X1.** §F.9 — risk-model provenance: factor loadings, covariance and betas, which CORE §E has engine 6 consume and gives no engine the production of. Phase 2 recorded it as "a ninth unassigned responsibility" (`phase2_contracts.md:687`) and listed it beside the horizon grid at `:2011`; K.1.4 read one of the two sheets and concluded no method existed to find a ninth | **Recorded, not resolved.** Scheduled to resolve alongside §F.8's contract work. Two reasons it is not settled here: its recommended owner (engine 12) conflicts with the write-authority rule that rejected engine 12 for §F.2, and unlike the grid it may be a capability to build, so §K.5's "no new step" reasoning does not transfer |

**Net effect on the plan: one new step, three step blocks amended, one contract
sheet amendment recorded but not applied.** X1 adds: §F.8 resolved, §F.9
recorded and scheduled, and S-31 rescoped on A5.4's closure.

**All three plan changes are now applied.** S-11a is inserted between S-11 and
S-12 — lettered rather than renumbered, because renumbering S-12 through S-34
would invalidate every step cross-reference in Deliverables I, J and K, and a
stale cross-reference is a worse defect than an unusual ID. S-12 gains an explicit
"requires S-11a first". S-07 states p99 over a rolling event count and the
fail-closed rule for an uncomputable statistic, which closes A7.13. S-16 scopes the
fingerprint to the registry and names the ledger as excluded. §K.1.4's §F amendment
is **recorded and not applied**: it changes a Phase 2 contract sheet, and editing a
prior phase's output to fix a finding this phase made would erase the evidence that
the finding was made here.

**The ledger was rebuilt rather than hand-adjusted, and that exposed a
pre-existing arithmetic error.** Inserting a step mid-plan shifts every subsequent
running total, so `tools/arch/p7_ledger.py` now recomputes the running and subtotal
columns from the per-step deltas. Doing so revealed that **wave C's public-symbol
subtotal read +39 while its steps sum to +40** — the running column was right and
the subtotal was wrong, so the whole-plan figure of −74 was correct and only the
wave line disagreed with it. With S-11a's +1 the plan was then **+7 modules, −73
public symbols, −25 branch points**, and `p7_ledger.py --check` fails if the table
ever stops reconciling with itself again. (**X1 subsequently rescoped S-31 from
−106 to −12 on A5.4's closure, making the current figure +7 / +22 / −25**; the
reconciliation check is what confirmed the amended table still sums.) Three claims that quote the symbol figure
were updated with it; nine step-count claims were recomputed from measurement
rather than incremented, which is how "Wave D is 10 of 34 steps" was found to be
12 of 35.

**The plan is still not locked**, but the reason has changed: what remains is the
CORE §M closing check and the open items in §J.2, not a step with an unreachable
criterion.

---

### Verification performed on Deliverable K

**The method was inherited, not invented, and the census was measured.** All **23**
"Model finding" verdicts in Phases 1–3 were counted by script — 1 in
`phase1_plumbing.md`, 19 in `phase2_contracts.md`, 3 in `phase3_flow_gating.md` —
and **9 carry a conditional clause**, 6 in Phase 2 and 3 in Phase 3, which is
exactly the watch-line set below. I first wrote 23 as "20" from memory and
mis-split the §F resolutions as four rather than seven; both are corrected against
the count. K decides those nine and
adds one finding from outside them. This is why K is not empty: I did not go
hunting for misfits, I discharged conditions that earlier phases deliberately left
for the last phase.

**Three watch-lines were decided by reading code this session rather than by
inference.** WL-3, by reading `src/feelies/alpha/risk_wrapper.py:150-176` and
finding the high-water-mark assignment inside the veto path — which is why it is
reported with a "BUT NOTE" rather than a bare "does not fire". WL-4, by reading
`src/feelies/kernel/orchestrator.py:4498-4504` and
`src/feelies/harness/backtest_report.py:788`, then re-reading CORE §E's engine-11
row and finding that §E **mandates** the dependency Phase 2 had assumed away. WL-7,
by reading `src/feelies/bootstrap.py:344-359` and finding Phase 3's named candidate
present and load-bearing.

**One defect in Deliverable G was found by K and is not fixed here.** S-12's PARITY
IMPACT makes R3 — permute registration order, assert an identical hash — the proof
that the manifest is not load-bearing. `src/feelies/bootstrap.py:355` states that
subscription order determines fill provenance, and Phase 1 §3 measured delivery
order as output-determining, so R3 will fail on `NBBOQuote`. Recorded as K.1.3 with
the remedy Phase 3 already prescribed. Editing S-12 is a plan revision rather than a
K finding, so the block is left as written and the amendment is listed in §K.5.

**Candidates rejected, with the refutation named.** Five, in §K.4. Four were refuted
by a prior phase's own resolution, and one — the most tempting, that the model has
no seat for the kernel — by CORE §E's cross-cutting paragraph, which I had not read
closely until this deliverable. Recording the refutations is the only way to show
the three firing findings are not a forced fit.

**Unverified.** WL-2 is undecidable without U-3, which no phase closed (§K.2). The
claim that R3 will fail on `NBBOQuote` is **INFERRED** — from the comment at
`src/feelies/bootstrap.py:355`, the two `NBBOQuote` subscriptions, and Phase 1 §3's
measurement — not demonstrated, because R3 does not exist yet. The check is to write
R3 first and observe it, which is among the cheapest items in the register to
settle. Whether the horizon grid is the *only* responsibility missing from §F is
**not established**: §K.1.4's point is precisely that no phase had a method for
finding an eighth, so none has a method for finding a ninth.

## Closing check — Definition of done (CORE §M)

Measured by `tools/arch/p7_done.py`, evidence at `tools/arch/evidence/p7_done.json`.
Two of the five are judgment calls and are labelled as such; the other three are
counts.

- [x] **Every deliverable in CORE §K exists.** 12 checked, 0 missing — the seven
  phase outputs `phase0_comprehension.md` through `phase6_conformance.md`, plus
  sections A, G, I, J and K in this file. §K's last row bundles five deliverables
  into one output file, so the check is per-section, not per-file.

- [x] **Every CORE §F item has exactly one named owner** — 7 of 7, each with its own
  resolution section in `phase2_contracts.md` and each closing "Model finding:
  none". **Passes as written, and the caveat is load-bearing:** §K.1.4 found an
  eighth responsibility meeting §F's definition — the horizon grid — that §F does
  not list and no phase assigned. It has a *recommended* owner (engine 2) and not an
  assigned one. **The call:** M2 is met, because the horizon grid is not a §F item;
  the list §F encloses is what is incomplete. Add it as §F.8 and resolve it on the
  produce/interpret/apply pattern the other seven used, before execution rather than
  during it.

- [x] **Every CORE §C invariant has a named enforcing test in Phase 6** — 11 of 11,
  measured across Phase 6's 50 spec blocks by reading each block's `INVARIANT:`
  field. Coverage is uneven and legitimately so: §C.5 (degraded reduces exposure)
  draws 5 tests and §C.9 (fail-closed gating) 4, while §C.1, §C.3, §C.7 and §C.8
  each rest on exactly one. **A single-test invariant is a single point of failure**,
  and §C.1 — determinism, which CORE §C says "outranks every other consideration" —
  is one of them: `test_parity_oracle_under_random_hash_seed` alone. A7.5 and A7.8
  are the assumptions that this test, and the 49 others, actually detect what they
  claim.
  Note the numbering hazard: Phase 6 cites both `CORE §C.n` and `Inv-N`, which are
  **different schemes** — `Inv-N` is `platform-invariants.mdc`. My first pass at this
  check conflated them and reported 11/11 for the wrong reason; the mapping above is
  from the §C citations only.

- [x] **Every Phase 5 gap has a Phase 7 step, or an explicit deferral with a
  reason** — 45 of 45, verified by `tools/arch/p7_check.py` against the gap list
  parsed from `phase5_gaps.md`. Two gaps have no conformance test and say so (§G.0.4);
  the deferrals with their reasons are in §G.9.

- [x] **Assumption register is non-empty and honest** — 13 new Phase 7 entries plus
  21 inherited rows, against P7's floor of five. **Non-empty is measured; honest is
  a claim I am making about my own work**, so here is what backs it: the register
  names the three assumptions I am least comfortable with (§J.4), it records the one
  case where reading the code proved an earlier inference of mine backwards (A7.12,
  `enforce_layer_gates`), and A7.13 was filed against a step I had already written
  rather than omitted to keep the plan looking finished. That entry is now closed
  because §K.5 fixed the block it indicted.

### The plan is locked

All five hold, so §M is satisfied and execution is a separate session with a separate
prompt. Locked means the step set, ordering and acceptance criteria are fixed — not
that every question is answered. **Three things should close before execution
begins**, none of which §M tests. **All three were closed in X1, and two of them
changed the plan:**

1. **U-3** — whether `broker/ib/` reconciles positions beyond the fill stream. Phase
   0 raised it, Phase 2 called it "open and now blocking" and said it should close
   before Phase 5, and it reached the last phase untouched. It blocks S-21, S-30 §F.3
   and the §K.2 watch-line, and Phase 0 named the route: read the adapter end to end
   and look for a positions request. One session.
   **CLOSED — no.** The adapter implements three `EWrapper` callbacks and issues no
   position query; §F.4 is a build, not a wiring task, and §K.2's WL-2 is discharged
   in the favourable direction. See §J.2.2.
2. **A5.4** — whether the 106 uncalled public methods S-31 deletes are genuinely
   dead. The plan's headline net-negative is −73 public symbols; without S-31 it is
   +33. This is the single assumption with the largest effect on whether the plan
   meets §G.10 at all.
   **CLOSED — false, and it was the right thing to test first.** 82 of the 106 are
   called from `tests/`; 13 are reached by nothing. S-31 is rescoped to −12, the plan
   nets **+22 public symbols**, and §G.10 still holds per-category because wave E
   remains net-negative. See §G.6 note 2.
3. **§F.8** — the horizon grid, per M2 above.
   **CLOSED — resolved to engine 2** in a marked addendum to
   `docs/architecture/target/out/phase2_contracts.md`, on Phase 2's own §F template,
   and **placed in S-30 after §F.1 and before §F.6**.
   **And M2's premise was too generous to the phases.** It reasons that no phase had
   a method for finding a ninth §F-class responsibility. Phase 2 had one and used it:
   `phase2_contracts.md:687` records "a ninth unassigned responsibility: risk-model
   provenance", and `:2011` lists it beside the horizon grid. §F.9 is therefore
   **recorded and deliberately unresolved** — its recommended owner (engine 12)
   conflicts with the write-authority rule that rejected engine 12 for §F.2, and
   unlike the grid it may be a capability to build rather than a contract to declare.
   It is scheduled to resolve alongside §F.8's contract work rather than before S-01.

**What locking does not settle** is whether the conformance suite works. Thirty-one
of 35 steps are accepted on "the baselines hold", 50 conformance tests are specified
and none is written, and A7.8 records that a test's existence is not evidence of its
effectiveness. `AGENTS.md` already prescribes the remedy — mutate the source, watch
the new test fail, restore, watch it pass — and the parity oracle's own history is
the argument for it: it had three independent ways to report success without
executing, and a commit moved its hash with CI fully green.

**HARD STOP.** The plan is locked. Execution is a separate session with a separate
prompt.
