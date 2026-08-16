# Phase 6 — Conformance suite specification

**Scope.** 50 conformance tests, 3 fixtures and 2 harnesses that make the Phase
1–4 target mechanical. Every test carries the P6 template. No production code is
proposed, sequenced, or written — Phase 7 sequences, a later session executes.

**Citation convention, carried from Phase 5.** Existing paths are cited inside
backticks and resolve under `tools/arch/measure.py spotcheck`. **Intended new
file paths are written unbracketed on purpose** — inside backticks the checker
reads them as live citations and fails them as "file missing", which is how
Phase 5 first produced 45 spurious failures. A plain-text path in a `TEST:` line
is a file to create, not a claim about the repo.

**Re-measured this session, not carried.** `tools/arch/gapscan.py` (0.717 s),
`tools/arch/gatescan.py` (1.299 s) and `tools/arch/hotpath.py` (2.143 s) were
re-run; every headline number reproduced Phase 5 exactly. Five open questions
carried into this phase were closed by reading code, and one gap Phase 5's table
does not contain was found. Both are in *Findings raised in this phase* below.

---

## 0. The two mechanisms that make this suite possible

P6's instruction — "conformance tests come *before* the refactors they protect" —
collides with two facts about this repository. Both need a mechanism, not
goodwill, and specifying them is the load-bearing part of this phase.

### 0.1 A test that fails today cannot be committed green — `xfail(strict=True)` is the answer

**36 of the 50 tests below fail against current source.** 7 pass and carry a
mutation instead (§0.2), 6 have never been run and say so, and 1 — A2 — passes on
one clause and fails on another, which is why it is specified as one test with
both. CI is green on `main` and must stay green
(`.github/workflows/ci.yml:98`), so there are three ways to commit a failing test
and two of them are the defects this repo has already been burned by.

| Option | Consequence |
|---|---|
| Wait for the fix, then write the test | The test is authored by whoever wrote the fix, against the code in front of them. This is exactly the failure `AGENTS.md` documents: five defects in #220 and one in #221 hid behind fixtures covering the one input shape the buggy logic handled |
| Commit behind a deselected marker | This is the parity-oracle defect verbatim — `functional` deselection plus a skip-on-cache-miss gave "three independent ways to report success without executing". Rejected |
| **Commit with `@pytest.mark.xfail(strict=True, reason="GAP Gnn")`** | Green today. The moment the gap is remediated the test **XPASSes strictly, which fails the build**, forcing the marker's removal in the same commit as the fix. The test is authored against the target by someone who has not yet written the fix |

**The call: `xfail(strict=True)`, with the Phase 5 gap ID in the reason string.**
It is the only option under which the test precedes the fix *and* the suite
cannot silently stop testing. `pytest` is already the harness; no new dependency.

This creates one new failure mode — an `xfail` that is wrong about *why* it
fails, or that outlives its gap — and that failure mode gets its own test (S1).

### 0.2 A guard that cannot fail today protects nothing unless the mutation is named

7 of the 50 tests pass against current source: S8, R1, R7, R8, X3, H1, A1, plus
A2's read clause. P6 is right that such a test
"protects nothing" *as written* — but the 20 do-not-change entries in Phase 5 are
regression risks precisely during remediation, and deleting their guards leaves
the platform's strongest correct behaviours unprotected at the moment they are
most likely to break. `AGENTS.md` already resolves this for safety branches:
break the guard deliberately, confirm the new test fails, restore, prove the
restore.

**Template extension, declared once:** every test with `FAILS TODAY: no` carries
a **`FALSIFIED BY:`** field naming the exact source mutation that must make it
fail. A guard whose mutation is not specified is not accepted into the suite. A
second extension, **`PROMOTES:`**, names the existing script or test a row is a
promotion of, per P6's reuse requirement.

### 0.3 Eleven tests cannot precede their subject, and that is structural

S1, S8, S9, S12, S13, S14, S15, R5, X8, X10 and X11 assert properties **of an
artifact the target creates** — the conformance registry, the schema-version
envelope, the unit declaration, the emitted-type and sequence registries, the
gate registry, the forbidden-reads matrix, the wiring manifest, the latency
budget, the cascade bound, the reconciliation policy. A test over a registry
cannot be written before the registry exists.

For these eleven, test and artifact ship in **one step**, and the test's honesty
comes from being a *closure* test rather than a content test: it asserts
completeness over the registry, so a partial registry fails it. This pattern is
already proven twice in the repo — `GATE_EVIDENCE_REQUIREMENTS`' module-level
completeness assertion (`src/feelies/promotion/evidence.py:1720-1731`) and the
parity manifest's closure tests (`tests/determinism/test_parity_manifest.py:261`,
`:288`). Phase 7 must not sequence these as "tests first"; it must sequence them
as "artifact and closure test, atomically."

---

## 1. Required coverage — P6's table, mapped

| Invariant | Enforcing test(s) | Fails today |
|---|---|---|
| Dependency direction, acyclicity | **S2** | yes |
| Boundary contracts | **S9**, **S14**, **X7** | yes |
| Gate ladder integrity | **S13** | yes |
| Determinism | **R1**, **R8**, **R9**, **A1** | R1/R9 yes; R8/A1 guards |
| Schema evolution | **S8**, **R5** | yes |
| Conservation | **C1**, **C2**, **C3**, **C4**, **C5**, **C6** | C4/C6 yes; rest measure-first |
| Execution honesty | **H1** | no — guard, mutation named |
| Order idempotency | **H2** | yes (G03, P0) |
| Alpha-agnosticism | **S3**, **A3** | yes |
| No wall clock on tick path | **S4** | yes |
| Degraded monotonicity | **X1**, **X2**, **X3** | yes |
| Exception containment | **X7**, **S6** | yes |
| Single owner per fact | **S11**, **S12** | yes |
| Mode parity | **S7**, **H3** | S7 yes |
| Reconciliation | **X11** | yes |

**Rows P6's table misses, added from CORE §C and the Phase 1–4 targets:**

| Added invariant | Source | Enforcing test |
|---|---|---|
| Causality — no output uses data timestamped after its own event time | CORE §C.2 | **R7**, **A1**, plus existing `tests/causality/test_anti_lookahead.py` |
| Governance off the tick path — resolved at composition, never per event | CORE §C.10 | **A2** |
| Reset-path totality — replay starts from a known state | Phase 1 §5 | **S16** |
| Hot-path allow list — only A1–A8 on the tick-critical path | Phase 4 §1 | **S5** |
| Latency budget exists and a breach has an exposure-reducing response | Phase 4 §6, CORE §G.7 | **X10** |
| Parity-surface closure — every engine output hashed or exempt-with-reason | Phase 1 §6.1 | **R9** |
| Run-fingerprint totality — everything that can change output is covered | Phase 1 §7 | **R4** |
| Emission has a consumer — a publish with no subscriber is not an event | Phase 3 C.1 | **S11** |
| Subscription graph declared, ordered and hashed | Phase 3 B, the wiring manifest | **S15** |
| Cascade depth bounded on a synchronous re-entrant bus | Phase 1 §3, §F.5 | **X8** |
| Frozen events are frozen in substance, not only by decorator | Phase 3 C, Phase 0 C-7 | **S10** |
| No post-construction mutation or cross-object private access | Phase 3 B, Inv-3 | **S17** |
| Registration order is not an output-determining input | Phase 1 §3 | **R3** |
| Kill switch is fail-closed, durable and observable | Phase 2 E11 | **X9** |
| Order state machine is total | Phase 2 E10 | **H4** |
| Attachment costs zero core edits | CORE §G.1 | **A3** |
| The suite itself stays honest as gaps close | this phase | **S1** |

---

## 2. CORE §C invariants — every one has a named enforcing test

| # | Invariant | Primary | Supporting | Weakest link |
|---|---|---|---|---|
| C.1 | Deterministic replay | **R1** — oracle under `PYTHONHASHSEED=random` | R3, R8, R9, R6, A1 | R1 is a CI-job change plus an assertion; it is the only test that covers the *whole* platform rather than a stream |
| C.2 | Causality | **R7** — throttle predicate in event time | A1, existing `tests/causality/test_anti_lookahead.py` | No test asserts causality over the *whole* field set; R7 covers the one axis Phase 2 left open |
| C.3 | Typed synchronous bus boundaries | **S15** — wiring manifest closure | S11, X7, X8 | Payload validation at dispatch (X7) is mechanism M5 — runtime and late, Phase 3's weakest row |
| C.4 | Backtest / paper / live share core logic | **S7** — mode branches only at the composition root | H3, H1 | H3 needs an identically stubbed backend that does not exist; without it C.4 is enforced statically only |
| C.5 | Unknown or degraded reduces exposure | **X1** — property over every declared degradation | X2, X3, X4, X5, X6, X9, X10, X11, S6 | X1 depends on the degradation set being *enumerable*; that enumeration is an artifact the target creates |
| C.6 | Single source of truth per fact | **S12** — one producer per contract, one sequence authority per stream | S11, C2, C5 | Static uniqueness cannot see a *read-then-recompute*; C2's identities are what catch that |
| C.7 | Alpha-agnosticism | **S3** — no alpha ID / symbol / archetype / horizon literal outside `alphas/` and config | A3 | S3 is a substring scan; a branch on an alpha *characteristic* rather than its name passes. A3 is the behavioural half |
| C.8 | Contract-first boundaries — units, timestamps, provenance, staleness | **S9** — declared unit on every numeric contract field | S8, X7 | **This is the invariant with the least implementation today: zero unit declarations exist.** See *Findings* |
| C.9 | Fail-closed gating | **S6** + **X7** | X4, X5, X6, S13 | S6 is AST-shaped and allowlist-driven; the allowlist is where a fail-quiet handler will hide |
| C.10 | Governance off the tick path | **A2** — zero reads under instrumentation | S2 (the import edge) | A2 passes today on reads and fails on imports; the two halves must both be asserted or the invariant reads as satisfied |
| C.11 | Schema evolution never breaks replay | **R5** — refusal outside the supported range | S8 | S8 is the load-bearing half: without a pinned schema hash, a field addition is invisible to all 26 baselines |

**No invariant is unmapped.** Two are mapped only weakly and are named as such:
C.8 has no implementation to test against, and C.4's dynamic half (H3) depends
on a harness that does not exist.

---

## 3. Reuse before invention — what is a promotion

Eight of the seventeen static tests are a promotion of a script under
`tools/arch/`; two more extend an existing test. This is what keeps CORE §G.10
honest: the suite's net-new code is smaller than its test count implies.

| Test | Promotes | What the promotion adds |
|---|---|---|
| **S3** | `tools/arch/measure.py` `cmd_alphaleak` | `LEAK_EXEMPT_FILES` at `tools/arch/measure.py:139` is already an empty allowlist and `:425` already applies it. Adds: the assertion, symbol/archetype/horizon literals alongside IDs, and a stale-entry guard |
| **S4** | `tools/arch/clockscan.py` + existing `tests/acceptance/test_no_walltime_outside_clock.py` | The existing test allowlists whole *files*, so `src/feelies/kernel/orchestrator.py` is exempt across 5,480 lines. Adds: call-granular entries and the hot-module set |
| **S5** | `tools/arch/hotpath.py` | The prohibition table and the executed-function intersection already exist. Adds: `ALLOWED_NOT_PROHIBITED` becomes the A1–A8 allow list, and the PROVEN column becomes an assertion |
| **S6** | `tools/arch/gatescan.py` `fail_quiet_handlers` | Already enumerates all 20 sites with their bodies. Adds: per-entry justification and the assertion |
| **S7** | `tools/arch/gapscan.py` `mode_branches` / `tools/arch/coupling.py` `mode_branches` | Already partitions by package. Adds: the composition-root exemption as an explicit allowlist rather than a hard-coded `{execution, broker}` set |
| **S10** | `tools/arch/contracts.py` `mutable_containers_in_frozen_events` | Already enumerates the 8 classes. Adds: the assertion |
| **S11** | `tools/arch/contracts.py` `bus_sites` / `published_never_subscribed` | Already computes both directions. Adds: mode-awareness (a backtest-only subscriber must count) and the assertion |
| **S16** | `tools/arch/substrate.py` `stateful_no_reset_top` | Already ranks the 32 classes. Adds: the assertion and the reset-determinism replay in R6 |
| **S17** | `tools/arch/coupling.py` `cross_object_private` + `external_attribute_assignment` | Already enumerates 10 + 45 sites. Adds: the composition-root allowlist and the assertion |
| **S2** | `tools/arch/measure.py` `cmd_imports` (evidence only) | Adds `import-linter` as the enforcing mechanism; Phase 3 §3.1 already made this call |
| **H1** | existing `tests/execution/test_router_fill_timing_parity.py` | 589 lines already pin the **passive** path's causal timing. Adds the *parity* half: the aggressive path on the same tape, asserting one eligibility rule |
| **R1** | existing `.github/workflows/ci.yml:100-115` job | The random-seed job already exists and covers `tests/determinism/` only. Adds: the parity oracle inside it |
| **S8**, **S13** | pattern only | `tests/acceptance/test_no_walltime_outside_clock.py:72` (AST scan) and `src/feelies/promotion/evidence.py:1720-1731` (registry self-completeness) are the two templates; no script to promote |

**Net-new code, honestly counted:** 5 static tests are net-new logic (S1, S8,
S9, S12, S13, S14, S15 — of which S14 and S15 are closure tests over artifacts
Phase 3 specifies, so their logic is a set comparison). Everything in the R, C,
X, H and A groups is net-new, because no measurement script executes the platform.

---

## 4. Fixtures

### 4.1 What already exists — checked, per CORE §I

CORE §I requires reading `sig_contra_fixture_v1` and `paper_smoke_v1` before
building anything. Both manifests were read.

| Existing asset | Role it covers | Role it does not |
|---|---|---|
| `alphas/sig_contra_fixture_v1/sig_contra_fixture_v1.alpha.yaml` | **Partial FIX-2.** `RESEARCH` lifecycle, mirrors `sig_benign_midcap_v1`'s sensor set and parameters with the direction inverted — a real two-sided contest for netting and per-strategy attribution | Everything CORE §I actually asks FIX-2 to vary: same horizon, same symbol cardinality, same archetype, same cadence. It is an *inversion* fixture, which is the optional fourth role (a second live-shaped alpha), not the shape-adversarial one |
| `alphas/_paper_smoke_v1/paper_smoke_v1.alpha.yaml` | **Partial FIX-2 and partial FIX-3.** 30 s horizon against the reference set's longer buckets, a single sensor, `SPY` rather than `APP`, and **no `trend_mechanism` block** — which makes it a live G16 probe | Not adversarial by construction; it is a minimal smoke alpha whose shape differences are incidental. Nothing in it is designed to fail |
| **Neither** | — | **FIX-1 does not exist.** No alpha emits nothing by construction, so there is no analytic reference run |

**Conclusion: the suite is a promotion of existing assets for the optional fourth
role only.** `sig_contra_fixture_v1` is retained as-is and consumed by C2 and C5.
FIX-1 and FIX-3 are net-new. FIX-2 is net-new because the two existing fixtures
between them vary one axis (horizon) of the four CORE §I names, and vary it by
accident.

### 4.2 FIX-1 — Null alpha

alphas/\_conformance/null\_v1/null\_v1.alpha.yaml

**Emits:** nothing. `layer: SIGNAL`, lifecycle `RESEARCH`, one sensor dependency
so the load path and the sensor DAG are exercised, `regime_gate.on_condition:
"False"` so `HorizonSignal.evaluate` is reached and returns no `Signal`. It must
load cleanly through all 16 implemented layer gates — a fixture that fails
validation tests the validator, not the platform.

**Proves:**

1. **Level-based conservation against an analytic reference.** With zero
   forecasts the target portfolio is the zero vector, so every conserved quantity
   has a closed form: position 0, realized P&L 0, unrealized P&L 0, orders 0,
   fills 0, attributed P&L 0, and `Δposition = Σ signed fill quantity` holds
   trivially at every event. Any non-zero is a leak, not a rounding difference.
   This is the only run in the platform whose correct output is known *a priori*
   rather than by comparison to a previous run.
2. **Stability under zero signal.** The full tick-critical path runs to
   completion with no order emitted: warm-up, staleness, regime, barrier, risk
   and admission all execute their no-op branches. Phase 4 measured 136.2 µs/quote
   on the shipped 4-sensor backtest; the null run isolates how much of that is
   paid before any decision exists.
3. **That the parity oracle is not the only oracle.** CORE §I is explicit that
   replay parity proves you did not change behaviour, not that behaviour is
   correct. FIX-1 is the platform's first correctness oracle.

**Consumed by:** C1 (primary), C2, C3, X10 (a budget breach with no signal must
still respond), S5 (the null tape is the cleanest hot-path measurement), R9.

### 4.3 FIX-2 — Shape-adversarial alpha

alphas/\_conformance/shape\_adversarial\_v1/shape\_adversarial\_v1.alpha.yaml

**Emits** forecasts whose *shape* differs from the live payload on all four axes
CORE §I names, simultaneously — the point is that varying one axis at a time
cannot find code that assumes two of them together:

| Axis | Live payload | FIX-2 |
|---|---|---|
| Layer / archetype | `SIGNAL`, single-name | `PORTFOLIO`, cross-sectional — consumes `CrossSectionalContext`, emits `SizedPositionIntent` |
| Horizon | 300 s and 900 s in the reference set | **1800 s**, the top of the canonical set, so the boundary count per session is smallest and the barrier is most likely to be starved |
| Symbol cardinality | effectively 1 (`APP` 36 times in `configs/` + `platform.yaml`) | **≥ 4**, at least one of which never trades on the tape, so `composition_completeness_threshold` is exercised at both sides of 0.80 |
| Cadence and direction | one signal per boundary, long-biased | Emits on a subset of boundaries, and inverts the direction convention where the schema permits |

**Proves:** every place the live alpha's shape is baked into shared code fails
loudly. Concretely it is the only fixture that can fail these:

- CORE §G.1 — attachment costs zero edits under `kernel/`, `bus/`, `core/`,
  `composition/`, `risk/`, `execution/`. Phase 5 G25 already shows one alpha ID
  in core config defaults (`src/feelies/core/platform_config.py:108`, repeated at
  `:910`), so the claim is known to be false at one point; FIX-2 finds the rest.
- G15's identity reduction — `_select_bus_signal` reduces engine 4's output to
  one surviving forecast per tick inside the kernel
  (`src/feelies/kernel/orchestrator.py:1676`, definition at `:4831`). With A=1 the
  reduction is an identity and cannot be observed to be wrong. FIX-2 plus one
  live-shaped alpha is the minimum configuration under which it can.
- The horizon grid — Phase 3 carries the horizon-grid question as one of two
  open §F-class findings. A 1800 s alpha alongside a 300 s alpha is what decides
  it.

**Consumed by:** A3 (primary), S3, R3, C6, C4, X1, X4 (per-alpha budget at A>1 is
where G23's blast radius stops being near-zero), R9.

### 4.4 FIX-3 — Pathological alpha

alphas/\_conformance/pathological\_v1/pathological\_v1.alpha.yaml plus a
generator under tests/conformance/fixtures/

**Emits**, one input class per parametrised case, so a refusal can be attributed
to a named gate rather than to "something rejected it":

| Class | Payload | Must be refused by |
|---|---|---|
| NaN | `edge = float("nan")`, `confidence = nan`, a NaN feature value | The receiving boundary, before sizing |
| Stale timestamp | `anchor_ts_ns` older than the staleness envelope; and one *newer than its own event time* | Staleness gate; causality check (CORE §C.2) |
| Out-of-universe symbol | A symbol absent from the §F.1 universe at that event time | Universe gate (§F.1's owner is engine 5) |
| Duplicate ID | Two forecasts with identical `correlation_id`; two orders deriving the same `order_id` | Idempotency — the same key H2 tests durably |
| Self-contradictory | Long and short on one symbol at one boundary; `edge` sign opposite to `direction`; mechanism inconsistent with `expected_half_life_seconds` (G16's envelope) | Boundary validation with provenance |
| Unregistered `strategy_id` | A non-empty `strategy_id` the registry does not know | **The per-alpha budget — which is G23, and which today takes `except KeyError: pass` at `src/feelies/alpha/risk_wrapper.py:189`** |
| Missing schema version | An event constructed without the F.7 envelope field | Refusal at dispatch, not defaulted to v1 |

**Proves** gates are fail-closed rather than fail-quiet — the distinction Phase 5
measures as 20 fail-quiet handlers, two of them on decision paths and both P0.
Every case must produce a **named gate plus an emitted record**; a silent skip
fails the test even when the exposure outcome is correct, because an unrecorded
refusal cannot be audited (Inv-13) and cannot be counted (X9's rejection-rate
monitor).

**Consumed by:** X6 (primary), X4, X5, X7, S6, S13, R5, X9.

### 4.5 HARN-1 — engine surface probe

tests/conformance/harness/probe.py

An instrumentation context manager that counts reads and writes through a named
engine surface, built the way `tools/arch/perfmeasure.py` already wraps call
sites (`tools/arch/perfmeasure.py:297` `_wrap`, `:343` `_install_direct_probes`).
Needed by A2 (zero governance reads on the tick path), X2's "no shadow book"
clause, C5, and engine 12's zero-write assertion. Specified once because Phase 2
asks for the same instrument on two sheets and says the two "should share a
harness".

### 4.6 HARN-2 — fault injector

tests/conformance/harness/faults.py

Injects a raise at a named containment unit — a bus handler, a store read, an
engine entry point — and records what the platform did next. Needed by X5, X7,
X8, X11, R6. Without it, §F.5's containment specification has no test and the
20-handler class is addressed two sites at a time.

---

## 5. Per-test specifications

### 5.1 Static checks (S1–S17)

```
TEST:            test_conformance_registry_closure
                 tests/conformance/test_registry_closure.py
INVARIANT:       Phase 6 §0.1 — the suite stays honest as gaps close
KIND:            static check
FIXTURE:         none
PASS CONDITION:  A registry maps each Phase 5 gap ID to the test IDs that
                 enforce it. Assert: (a) every P0 and P1 gap has >= 1 test;
                 (b) every test marked xfail(strict) names a gap ID that exists
                 in the registry; (c) no gap ID appears with zero tests; (d) no
                 xfail exists whose reason string names no gap.
FAILS TODAY:     yes — no registry exists
COST:            fast unit (registry comparison, no source scan)
BUILD ORDER:     0 — before every other test in this document
PROMOTES:        pattern from src/feelies/promotion/evidence.py:1720-1731
```

```
TEST:            test_import_tiers_and_engine_independence
                 tests/conformance/test_import_contracts.py
INVARIANT:       CORE §C.3, §G.2; Phase 3 §3.1 tier rule
KIND:            static check
FIXTURE:         none
PASS CONDITION:  import-linter reports zero contract violations for the layers
                 contract (Tier 0->4, no upward import) and the independence
                 contracts over the twelve engine module sets.
FAILS TODAY:     yes — Phase 0 D0.1 cycle 2, feelies.core.inv12_stress ->
                 feelies.core.platform_config -> feelies.promotion.evidence, is
                 a Tier 0 -> Tier 2 edge and illegal whether or not it closes
                 a loop (G16)
COST:            fast unit (~2 s over 196 modules)
BUILD ORDER:     1 — before G13, G14, G16, G21, G22, G24, G27, G30, G40
PROMOTES:        tools/arch/measure.py cmd_imports (evidence); adds the enforcer
```

```
TEST:            test_no_alpha_shape_literal_outside_alphas_and_config
                 tests/conformance/test_alpha_agnosticism.py
INVARIANT:       CORE §C.7, §I; Inv-6
KIND:            static check
FIXTURE:         FIX-2 (the behavioural half is A3)
PASS CONDITION:  No alpha_id, symbol literal, archetype name, or horizon
                 constant from the canonical set appears in src/feelies outside
                 a per-entry-justified allowlist. Stale allowlist entries fail.
FAILS TODAY:     yes — 3 alpha-id literals measured today: two in
                 `src/feelies/core/platform_config.py` (`:108`, `:910`,
                 `moc_strategy_ids` default) and a docstring in
                 `src/feelies/research/forward_ic.py:10` (G25)
COST:            fast unit (0.7 s measured, gapscan alpha_leaks)
BUILD ORDER:     1 — before G25, and before any FIX-2 attachment work
PROMOTES:        tools/arch/measure.py cmd_alphaleak; LEAK_EXEMPT_FILES at :139
                 is already the allowlist and :425 already applies it
```

```
TEST:            test_no_wall_clock_read_on_hot_path
                 tests/acceptance/test_no_walltime_outside_clock.py (extend)
INVARIANT:       Inv-10 clock abstraction; Phase 4 P11
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every raw wall-clock call site in a tick-critical module is a
                 named allowlist entry at call granularity — path plus line
                 plus justification — and each entry is reachable. An entry
                 that is not a clock read fails as stale.
FAILS TODAY:     yes, twice. 12 of 18 reads in tick-critical packages are absent
                 from `tools/arch/evidence/clock.json`'s allowlist and 5 of the
                 22 entries are not clock reads (G01). Separately the existing
                 test allowlists whole files, so `src/feelies/kernel/orchestrator.py`
                 is exempt across 5,480 lines — a `datetime.now()` anywhere in
                 it passes today
COST:            fast unit
BUILD ORDER:     1 — before G01, and before the engine-9 expiry work (Phase 2
                 E9 test 5 depends on this granularity)
PROMOTES:        tests/acceptance/test_no_walltime_outside_clock.py:72 with its
                 stale-entry guard at :96; census from tools/arch/clockscan.py
```

```
TEST:            test_hot_path_allow_list
                 tests/conformance/test_hot_path_allow_list.py
INVARIANT:       Phase 4 §1 (A1-A8 permitted, P1-P14 prohibited); CORE §G.7
KIND:            static check
FIXTURE:         FIX-1 (null tape gives the cleanest executed-function set)
PASS CONDITION:  Zero unconditional per-event hits on any prohibited category
                 for functions in the executed set, except entries in a
                 justified allowlist. A2 and A6 (Decimal, transcendental) are
                 declared allowed and reported, not suppressed.
FAILS TODAY:     yes — 13 unconditional per-event hits measured today: dict
                 construction 3, string formatting 3, wall-clock read 3,
                 dynamic dispatch 2, set construction 2 (G45). 9 of the 13 are
                 in `kernel/` or `core/`
COST:            slow replay (2.1 s scan measured; needs the executed-function
                 map, which needs one replay)
BUILD ORDER:     2 — before G41, G42, G44, G45
PROMOTES:        tools/arch/hotpath.py — the prohibition table, the executed
                 intersection and the control-flow split all already exist
```

```
TEST:            test_no_fail_quiet_exception_handler
                 tests/conformance/test_exception_containment.py
INVARIANT:       CORE §C.9, §F.5; Inv-11
KIND:            static check
FIXTURE:         none
PASS CONDITION:  No `except` clause whose body neither raises, returns a value,
                 nor logs, outside an allowlist carrying a per-entry
                 justification. Stale entries fail.
FAILS TODAY:     yes — 20 handlers measured today, 6 of them bare ONLY-PASS.
                 By package: ingestion 4, cli 3, composition 3, harness 3, root
                 2, alpha 2, broker 2, kernel 1 (G36)
COST:            fast unit (1.3 s measured, gatescan)
BUILD ORDER:     1 — before G20, G23, G36
PROMOTES:        tools/arch/gatescan.py fail_quiet_handlers, which already
                 enumerates all 20 with their bodies
```

```
TEST:            test_mode_branches_only_at_composition_root
                 tests/conformance/test_mode_seam.py
INVARIANT:       CORE §C.4; Inv-9 backtest/live parity
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Zero OperatingMode / is_live branches outside `execution/`,
                 `broker/`, and an explicit composition-root allowlist. Branch
                 count inside `execution/` and `broker/` stays at zero — the
                 seam is selected, not branched.
FAILS TODAY:     yes — 27 branches measured today, all outside `execution/` and
                 `broker/`: root 20, `core` 2, `forensics` 2, `harness` 2,
                 `promotion` 1. The 20 in `src/feelies/bootstrap.py` are the
                 composition root and belong in the allowlist; **the 7 outside
                 bootstrap are the gap** (G26)
COST:            fast unit
BUILD ORDER:     1 — before G26; must precede H3, which assumes the seam holds
PROMOTES:        tools/arch/gapscan.py mode_branches / tools/arch/coupling.py
```

```
TEST:            test_event_schema_hash_pinned_and_version_coupled
                 tests/conformance/test_schema_drift.py
INVARIANT:       CORE §C.11; §F.7 conformance tests 3 and 4; Inv-10
KIND:            static check
FIXTURE:         none
PASS CONDITION:  AST-scan every event class's declared field set (name, type,
                 default, order), hash it, compare to a pinned value. A field
                 added, removed, renamed or retyped fails. A changed schema
                 hash without a `schema_version` bump fails.
FAILS TODAY:     no — it pins whatever shape exists today. This is the point:
                 it is the only mechanism that makes schema growth visible,
                 because Phase 1 §8 measured that adding a field leaves **all
                 26 parity baselines green, silently**
FALSIFIED BY:    Add one field to any class in `src/feelies/core/events.py` and
                 run only this test. It must fail. Confirm the parity manifest
                 still passes on the same mutation — that contrast is the
                 test's entire justification
COST:            fast unit
BUILD ORDER:     1 — before G07 and before F.2's `instrument_id` change, which
                 touches all 21 types and is F.7's first customer
PROMOTES:        pattern from tests/acceptance/test_no_walltime_outside_clock.py:72
```

```
TEST:            test_every_numeric_contract_field_declares_a_unit
                 tests/conformance/test_unit_declaration.py
INVARIANT:       CORE §C.8 — "a field whose unit is not declared does not exist"
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every numeric field on every event type resolves to a declared
                 unit from a closed enumeration. A field with no unit fails,
                 naming the type and field.
FAILS TODAY:     yes, completely. **No event type declares a unit for any
                 field.** The string `unit` occurs once in
                 `src/feelies/core/events.py` — in prose at `:557`. `SensorReading`
                 (`:607`) carries `value`, `confidence` and `warm` with no unit;
                 `HorizonFeatureSnapshot` (`:631`) carries `warm`, `stale`,
                 `source_sensors` and `feature_versions` maps but no units map.
                 See *Findings raised in this phase* — Phase 5's table has no
                 row for this
COST:            fast unit
BUILD ORDER:     1 — before every engine extraction; a boundary moved before
                 its units are declared cannot be validated at the new boundary
```

```
TEST:            test_frozen_events_carry_no_mutable_container
                 tests/conformance/test_event_immutability.py
INVARIANT:       Inv-7 typed schemas; Phase 3 C; CORE §J mutable-in-frozen
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every field on a frozen event class is a scalar, a tuple, a
                 frozenset, or a frozen mapping type. `dict`, `list`, `set` and
                 mutable dataclass fields fail.
FAILS TODAY:     yes — 8 event classes carry mutable containers: `Alert`,
                 `CrossSectionalContext`, `HorizonFeatureSnapshot`, `MetricEvent`,
                 `RiskVerdict`, `Signal`, `SizedPositionIntent`,
                 `StateTransition`. `HorizonFeatureSnapshot` alone has 5, and
                 they are the fields carrying the feature payload (G12)
COST:            fast unit
BUILD ORDER:     1 — before G12; and before C2, because an identity asserted
                 over a mutable published event can be broken after the assert
PROMOTES:        tools/arch/contracts.py mutable_containers_in_frozen_events
```

```
TEST:            test_every_published_type_has_a_subscriber
                 tests/conformance/test_emission_registry.py
INVARIANT:       Inv-7; Phase 3 C.1 — a publish with no consumer is not an event
KIND:            static check
FIXTURE:         none
PASS CONDITION:  For every event type published anywhere in src/feelies, at
                 least one subscriber exists in at least one composed mode, or
                 the type is in a justified `notification-only` set. Zero
                 subscribed-never-published types.
FAILS TODAY:     yes — 6 types published to zero static subscribers:
                 `KillSwitchActivation`, `OrderAck`, `PositionUpdate`,
                 `RiskVerdict`, `StateTransition`, `SymbolHalted` (G10). Note
                 `subscribe_all` is defined at `src/feelies/bus/event_bus.py:55`
                 and has zero call sites in src (re-verified today), so no
                 global handler rescues them
COST:            fast unit
BUILD ORDER:     1 — before G10, G28; before X2's verdict-totality clause and
                 X9's rejection-rate monitor, both of which need `RiskVerdict`
                 observable
PROMOTES:        tools/arch/contracts.py bus_sites / published_never_subscribed
```

```
TEST:            test_single_owner_per_fact
                 tests/conformance/test_single_owner.py
INVARIANT:       CORE §C.6; Phase 1 §2 sequence authority; CORE §E.3
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Three closure assertions over one registry: (a) each event
                 contract has exactly one producing engine; (b) each sequence
                 stream has exactly one `SequenceGenerator` owner; (c) exactly
                 one construction site exists for each singleton classifier —
                 a second `RegimeState` publisher fails the build.
FAILS TODAY:     yes — the forecast-to-portfolio reduction exists in three
                 places (`composition/`, `_select_bus_signal` in the kernel,
                 `src/feelies/alpha/arbitration.py`) with nothing asserting they
                 agree (G19); 26 `SequenceGenerator` constructions with no
                 registry naming which stream each owns (G09); no
                 producer-uniqueness registry exists at all
COST:            fast unit
BUILD ORDER:     1 for the registry; 3 for clause (a) — before G09, G14, G15,
                 G19, G21
```

```
TEST:            test_gate_registry_enumeration_closure
                 tests/conformance/test_gate_registry.py
INVARIANT:       CORE §G.5 — every gate enumerable from a single source, docs
                 and tests generated from it; Inv-13
KIND:            static check
FIXTURE:         FIX-3 (each pathological class must bind to a registered gate)
PASS CONDITION:  Four assertions: every registry entry has an ordinal, a
                 predicate, a fail-closed branch and a bound test; every gate
                 call site in src resolves to a registry entry; the generated
                 doc table is byte-identical to the committed one; no ordinal
                 gap and no duplicate.
FAILS TODAY:     yes — two independent ladders with no common registry. G1-G17
                 are string-keyed method calls in `LayerValidator`, of which
                 **16 are implemented: G1-G12 then G14-G17, and G13 has zero
                 references anywhere in src** (re-measured today: 16 G-numbers,
                 no no-op stub detected). `GateId` is a separate 7-member enum
                 at `src/feelies/promotion/evidence.py:67`. Runtime gating is 329
                 call sites across 10 families (G17, G38)
COST:            fast unit
BUILD ORDER:     1 for the registry, atomic with it (§0.3) — before G17, G38
PROMOTES:        the self-completeness pattern at
                 src/feelies/promotion/evidence.py:1720-1731, which already does
                 exactly this over GateId and is what G1-G17 lacks
```

```
TEST:            test_forbidden_reads_matrix_closure
                 tests/conformance/test_forbidden_reads.py
INVARIANT:       Inv-8 layer separation; Phase 3 C.6; CORE §G.3
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every read edge exercised in a composed platform appears as a
                 permitted cell in the matrix. The matrix is closed: an edge not
                 explicitly permitted fails. Includes the M6 clauses — no
                 cross-object private access, no forbidden symbol import — and
                 the "no consumer reads a stale regime label" rule.
FAILS TODAY:     yes — **zero enforcement sites exist.** A repo-wide scan for
                 `forbidden_read|assert_no_read|boundary_violation` returns 0
                 hits (G37). Enforcement today is G1 at YAML load, which is
                 downgradable to a warning, plus `mypy --strict`, neither of
                 which sees a cross-layer read through a permitted type
COST:            fast unit for the static half; the dynamic half needs HARN-1
BUILD ORDER:     2, and **not before S2** — Phase 3 states the matrix "is
                 unenforceable until the tier rule holds", so the two ship
                 together or neither does. Before G37
```

```
TEST:            test_wiring_manifest_closure
                 tests/conformance/test_wiring_manifest.py
INVARIANT:       Inv-7; Phase 3 §3.1 — the subscription graph is the real
                 integration graph
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every subscribe call in a composed platform matches a manifest
                 entry with a declared ordinal and delivery semantics; every
                 manifest entry is realised or explicitly `absent_by_config`;
                 the manifest hash enters the run fingerprint. An undeclared
                 subscription fails the build.
FAILS TODAY:     yes — 32 subscribe sites, 16 of them reaching `publish` from
                 inside a handler, delivery order output-determining, and
                 nothing hashing any of it. `publish` has no idempotency key, no
                 seen-set and no dedup (`src/feelies/bus/event_bus.py:59-70`);
                 ordering is pinned by six prose comments in `build_platform`
                 (G02)
COST:            fast unit
BUILD ORDER:     1, atomic with the manifest (§0.3) — before G02, G13, G39;
                 before R3, which asserts the property the manifest declares
```

```
TEST:            test_reset_path_totality
                 tests/conformance/test_reset_paths.py
INVARIANT:       Inv-1; Phase 1 §5 — every engine declares a reset path
KIND:            static check
FIXTURE:         none
PASS CONDITION:  Every class that mutates state outside `__init__` exposes a
                 declared reset, or is in a justified allowlist of
                 construct-once objects. Paired with R6's reset-determinism
                 replay: reset then replay must equal fresh-construct then
                 replay, bit for bit.
FAILS TODAY:     yes — 110 stateful classes, 38 mutate outside `__init__`, and
                 32 of those have no reset path. `Orchestrator` is the extreme:
                 104 `__init__` attributes, 38 mutated later, zero reset
                 methods (G04)
COST:            fast unit
BUILD ORDER:     2 — before G04; and before any work that puts two runs in one
                 process (parameter sweeps, notebooks, long-lived paper)
PROMOTES:        tools/arch/substrate.py stateful_no_reset_top
```

```
TEST:            test_no_post_construction_mutation_or_private_reach
                 tests/conformance/test_construction_integrity.py
INVARIANT:       Inv-3 contract-first boundaries; Phase 3 C.6 mechanism M6
KIND:            static check
FIXTURE:         none
PASS CONDITION:  No assignment to an attribute of an object the assigning module
                 did not construct, and no access to a `_`-prefixed member
                 across object boundaries, outside a composition-root allowlist.
                 Objects are valid after `__init__`.
FAILS TODAY:     yes — 45 external attribute assignments and 10 cross-object
                 private accesses. `src/feelies/bootstrap.py` sets
                 `orchestrator.config_snapshot`, `.live_feed` and `.ib_connection`
                 after construction (`:584`, `:587`, `:588`) and reaches into
                 `metric_collector._store_raw_events` (`:411`); the harness
                 subscribes through `orchestrator._bus` (G39)
COST:            fast unit
BUILD ORDER:     2 — before G39; before engine 12's declared observation
                 interface, which is what removes the harness reach-through
PROMOTES:        tools/arch/coupling.py cross_object_private and
                 external_attribute_assignment
```

### 5.2 Determinism and replay (R1–R9)

```
TEST:            test_parity_oracle_under_random_hash_seed
                 .github/workflows/ci.yml (job change) + no new test file
INVARIANT:       CORE §C.1; §G.4 — bit-identical under PYTHONHASHSEED=random
KIND:            replay
FIXTURE:         none
PASS CONDITION:  The APP baseline replay produces the pinned trade parity hash,
                 net PnL and fill count under `PYTHONHASHSEED: random`, with
                 `FEELIES_REQUIRE_BASELINE_CACHE=1` still set so a cache miss
                 fails rather than skips.
FAILS TODAY:     no — the corpus is seed-independent (verified at seeds 1, 12345
                 and 99999 for `tests/determinism/`). The gap is coverage: the
                 random-seed job covers `tests/determinism/` only
                 (`.github/workflows/ci.yml:115`) while the parity oracle runs at
                 `PYTHONHASHSEED: "0"` (`:138`), so the platform's strongest
                 guard never sees a random seed (G08)
FALSIFIED BY:    **Not by removing a `sorted()` — by injection, and the reason
                 matters.** Phase 5 measured that no tick-path output is
                 currently ordered by a hash-ordered container (G08 is P2 for
                 exactly that reason), so there is no sort whose removal breaks
                 the hash today. The mutation is to make a hashed output ordered
                 by a string set at the one site where such a container already
                 exists on the read path:
                 `src/feelies/portfolio/strategy_position_store.py:145-148` builds
                 its returned dict by iterating `symbols: set[str]`. Make a
                 downstream reduction order-sensitive over it, then confirm the
                 **seed-0 oracle job stays green while this one fails**. That
                 contrast is the test's entire justification
COST:            CI-only (adds one replay to an existing job)
BUILD ORDER:     1 — before **every** remediation step. This is the guard that
                 detects collateral damage from all 45 gap fixes
PROMOTES:        the existing random-seed job at .github/workflows/ci.yml:100-115
```

```
TEST:            test_market_data_canonical_parity_baseline
                 tests/determinism/test_market_data_canonical_replay.py
INVARIANT:       Phase 1 §6.1; Inv-5; Phase 2 E1 test 1
KIND:            replay
FIXTURE:         none (fixed raw-frame tape)
PASS CONDITION:  A fixed raw-frame fixture through `MassiveNormalizer.on_message`
                 (`src/feelies/ingestion/massive_normalizer.py:280`) hashes to a
                 pinned value over the **full** declared field set, with
                 `Decimal` fields as exact strings rather than formatted floats.
                 Registered in the manifest as an entry, not an exemption.
FAILS TODAY:     yes — `NBBOQuote` and `Trade` have no hash helper at all, so
                 the platform's *input* stream has no baseline. An
                 ingestion-side change is invisible to the oracle until it moves
                 a downstream hash (G05, G11)
COST:            slow replay (fixture-scale, no session tape needed)
BUILD ORDER:     1 — before G05, G11; Phase 1 rates this the cheapest coverage
                 gain in the substrate and it needs no production change
```

```
TEST:            test_registration_order_independence
                 tests/determinism/test_registration_order_independence.py
INVARIANT:       Inv-1; Phase 1 §3; Phase 2 E2 test 4 and E4 test 2
KIND:            property
FIXTURE:         FIX-2 (needs >= 2 alphas and >= 2 mutually independent sensors)
PASS CONDITION:  Permuting the registration order of mutually independent
                 sensors leaves every `SensorReading` and
                 `HorizonFeatureSnapshot` stream identical. Permuting alpha load
                 order leaves every per-alpha `Signal` stream identical.
                 Removing alpha B leaves alpha A's stream identical.
FAILS TODAY:     **unknown, and that is the finding.** Phase 1 §3 established
                 that registration order is an output-determining input pinned
                 by nothing but six prose comments in `build_platform`. Whether
                 it currently matters has never been measured. The test must be
                 run to find out; either answer is worth having
COST:            slow replay (N! bounded to a sampled subset of permutations)
BUILD ORDER:     2 — before G02's wiring-manifest ordinals are relied on, and
                 before FIX-2 attachment, which changes the registration set
```

```
TEST:            test_alpha_manifest_content_moves_the_fingerprint
                 tests/conformance/test_fingerprint_totality.py
INVARIANT:       Inv-13 full provenance; Phase 1 §7; Phase 2 E4 test 3
KIND:            unit
FIXTURE:         FIX-1 (a manifest whose behaviour is a no-op isolates
                 provenance from output)
PASS CONDITION:  Editing one threshold in any `alphas/**/*.alpha.yaml` changes
                 both the emitted `Signal` provenance and
                 `config.snapshot().checksum`. Two runs with different alpha
                 parameters cannot share a config hash.
FAILS TODAY:     yes — `alpha_specs` is reduced to `sorted(spec.name for spec in
                 value)` at `src/feelies/core/platform_config.py:683`, so manifest
                 *content* moves no checksum, and a search for
                 `manifest_hash`/`spec_hash`/`yaml_hash` across
                 `src/feelies/alpha/` returns nothing (G06)
COST:            fast unit
BUILD ORDER:     2 — before G06, G30; before any promotion evidence is trusted
                 across runs
```

```
TEST:            test_schema_version_refusal_and_historical_replay
                 tests/conformance/test_schema_versioning.py
INVARIANT:       CORE §C.11; §F.7 conformance tests 1, 2 and 5
KIND:            replay
FIXTURE:         FIX-3 (the missing-version case)
PASS CONDITION:  Three assertions. A log stamped outside the declared-support
                 set is **refused, naming both versions and the supported
                 range**, with no partial output. An event with no
                 `schema_version` is refused at the receiving boundary with
                 provenance — never defaulted to v1. A vN log replays
                 bit-identically under any build declaring vN support.
FAILS TODAY:     yes — 2 of 21 event classes carry a version field
                 (`HorizonFeatureSnapshot`, `SensorReading`); every hot-path
                 event is unversioned. Worse, dispatch is exact-type only
                 (`src/feelies/bus/event_bus.py:65`), so an unknown type today
                 produces nothing at all: no exception, no counter, no log
                 (G07)
COST:            slow replay
BUILD ORDER:     4, atomic with the envelope field (§0.3) — before G07. Note
                 Phase 1 §8's warning: adding the field is silent across all 26
                 baselines, and bringing it into the hashed set re-pins them.
                 Two steps, two blast radii
```

```
TEST:            test_recovery_determinism_under_injected_fault
                 tests/conformance/test_recovery_determinism.py
INVARIANT:       Inv-1; §F.5 conformance test 3
KIND:            injected-fault
FIXTURE:         HARN-2; FIX-1 for the reset half
PASS CONDITION:  Same fault, same log, permuted subscription order yields an
                 identical recovery path and an identical post-fault stream.
                 Reset-then-replay equals fresh-construct-then-replay, bit for
                 bit (S16's dynamic half).
FAILS TODAY:     yes — no reset path exists for 32 stateful classes (G04), so
                 the second clause has nothing to call; and no fault-injection
                 harness exists, so the first has never been run
COST:            slow replay
BUILD ORDER:     3 — before G04, G36; before the engine extractions, which move
                 state between objects
```

```
TEST:            test_sensor_throttle_uses_event_time
                 tests/determinism/test_throttle_time_base.py
INVARIANT:       CORE §C.2 causality; Phase 2 E2 test 3
KIND:            replay
FIXTURE:         none
PASS CONDITION:  Replay the same event prefix with wall time advanced
                 differently between events; the `SensorReading` and
                 `HorizonFeatureSnapshot` streams are byte-identical.
FAILS TODAY:     no — **resolved this phase by reading the predicate.**
                 `src/feelies/sensors/registry.py:244` compares
                 `event.timestamp_ns - last_ns` against `binding.throttle_ns`,
                 which is event time throughout. Phase 2 called this "the single
                 highest-value test on this sheet" while its time base was
                 undetermined; it is a **guard**, and engine 2 is a pure
                 function of the event prefix on this axis
FALSIFIED BY:    Change `event.timestamp_ns` at
                 `src/feelies/sensors/registry.py:244` to a monotonic clock read
                 and run only this test. It must fail. Clear `__pycache__`
                 between mutation and restore — `AGENTS.md` records two rounds
                 of wrong answers from a stale `.pyc`
COST:            slow replay
BUILD ORDER:     2 — before G42, which changes how sensors are dispatched
```

```
TEST:            test_position_store_ordering_is_seed_independent
                 tests/determinism/test_store_ordering_seed_independence.py
INVARIANT:       Inv-1; Phase 1 determinism budget row 2a; Phase 2 E7 test 5
KIND:            property
FIXTURE:         FIX-2 (multi-symbol; a one-symbol book cannot vary in order)
PASS CONDITION:  Under permuted `PYTHONHASHSEED` the store's returned mapping
                 order and all downstream output are identical **without** a
                 consumer sorting. Iterating each of the 5 unsorted tick-path
                 set-iteration sites in reverse yields an identical parity hash.
FAILS TODAY:     no, on the shipped configuration — 2 of the 5 sites iterate
                 small-int horizon sets (int hashing is seed-independent), 1
                 clears distinct keys idempotently, and 2 build containers whose
                 insertion order varies but is not read in order (G08). The
                 second clause retires assumption A5.2, which is currently
                 verified by reading loop bodies and enforced by nothing
FALSIFIED BY:    Remove `keys = sorted(gross_by_family)` at
                 `src/feelies/composition/cross_sectional.py:78`, so the
                 `math.fsum` at `:79` accumulates in dict order over string
                 keys, and run under several seeds. It must fail at some seed.
                 This is the site Phase 5 do-not-change #13 names as the
                 platform's best determinism discipline, and FIX-2 is what puts
                 it on this test's path
COST:            slow replay (subprocess per seed, as
                 tests/determinism/test_hash_seed_independence.py already does)
BUILD ORDER:     2 — before G08, G21
PROMOTES:        the subprocess-per-seed pattern in
                 tests/determinism/test_hash_seed_independence.py
```

```
TEST:            test_parity_surface_closure
                 tests/determinism/test_parity_manifest.py (extend)
INVARIANT:       Phase 1 §6.1; Inv-5; Phase 2 E12 test 8
KIND:            static check over the manifest
FIXTURE:         FIX-1, FIX-2 (their streams must register too)
PASS CONDITION:  Every event type declared in `src/feelies/core/events.py` has
                 either a hash helper covering its full declared field set, or a
                 manifest exemption naming the reason and the host-sensitivity
                 class. Every exempt or data-gated baseline **reports as
                 unpinned** rather than as covered.
FAILS TODAY:     yes — 6 event classes have no hash helper at all (`Alert`,
                 `KillSwitchActivation`, `MetricEvent`, `NBBOQuote`,
                 `SensorReading`, `Trade`) and 15 carry fields in no hash (G05,
                 G29). Phase 0 P-1 names `OrderRequest.limit_price` and
                 `OrderRequest.is_moc` as unhashed fields whose values change
                 execution semantics — a change to where an order routes passes
                 all 26 baselines today
COST:            fast unit
BUILD ORDER:     1 — before G05, G29, and before S8, whose schema hash is the
                 other half of the same hole
PROMOTES:        tests/determinism/test_parity_manifest.py:261 and :288, which
                 already assert closure over registered hashes;
                 tools/arch/parity_coverage.py already prints the coverage table
```

### 5.3 Conservation (C1–C6)

```
TEST:            test_null_alpha_analytic_reference
                 tests/conformance/test_null_alpha_conservation.py
INVARIANT:       CORE §I fixture 1; Phase 2 E7 test 2
KIND:            replay
FIXTURE:         FIX-1
PASS CONDITION:  Over a full session tape with FIX-1 as the only alpha: zero
                 `Signal`s, zero `OrderRequest`s, zero fills, position 0 for
                 every symbol at every event, realized and unrealized P&L
                 exactly `Decimal("0")`, and the run completes without a
                 degraded-mode transition. Compared to a closed-form reference,
                 not to a previous run.
FAILS TODAY:     unknown — the fixture does not exist, so this has never been
                 run. It is the platform's **first** correctness oracle as
                 opposed to regression oracle, which is CORE §I's stated point
COST:            slow replay
BUILD ORDER:     0 with FIX-1 — before every remediation step, because it is
                 the cheapest way to detect a leak introduced by moving code
```

```
TEST:            test_accounting_conservation_identities_per_event
                 tests/conformance/test_accounting_identities.py
INVARIANT:       CORE §C.6; Phase 2 E7 test 1
KIND:            property
FIXTURE:         FIX-2 (multi-symbol), `sig_contra_fixture_v1` (two-sided)
PASS CONDITION:  Asserted **at every event, not at run end**: sum of per-strategy
                 position equals net position per symbol; delta position equals
                 sum of signed fill quantity; sum of lot quantities equals
                 position; delta P&L equals sum of fill cash flows plus sum of
                 (delta mark times position held). All in `Decimal`.
FAILS TODAY:     unknown — likely passes, because money is `Decimal` end to end
                 and A=1 means the per-strategy and net books nearly coincide.
                 It is the test that makes G21 *detectable*: 36 direct store
                 calls from the kernel (`self._positions` 23,
                 `self._strategy_positions` 13, re-measured today) means two
                 writers to one book, and `PositionUpdate` has no subscriber to
                 observe it
FALSIFIED BY:    Drop the per-strategy leg of one fill distribution in
                 `src/feelies/kernel/orchestrator.py:_distribute_fill_to_strategies`
                 and run only this test. It must fail at the first fill
COST:            slow replay
BUILD ORDER:     1 — before G21, G34, and before **any** engine-7 extraction.
                 A wrong boundary here shows up as a broken identity, which is
                 why engine 7 needs fewer structural tests than any other engine
```

```
TEST:            test_ingress_conservation_and_notification
                 tests/conformance/test_ingress_conservation.py
INVARIANT:       CORE §E.1 — "dropping is allowed; dropping without
                 notification is not"; Phase 2 E1 test 2
KIND:            property
FIXTURE:         FIX-3 (duplicate and malformed frames), FIX-1 (clean baseline)
PASS CONDITION:  Per symbol per run: `frames_in == emitted + rejected + dropped
                 + deduped`, and `|notifications| == |non-emitted|`. The
                 out-of-order counter is asserted non-silent under PAPER.
FAILS TODAY:     unknown — the duplicate policy itself is explicit and
                 fail-closed (`src/feelies/ingestion/massive_normalizer.py:777`
                 drops exact duplicates and transitions to `CORRUPTED` on a
                 sequence reused with a different payload, declared terminal at
                 `src/feelies/ingestion/data_integrity.py:58`), so the mechanism is
                 right. Whether the counts *close* has never been asserted
COST:            slow replay
BUILD ORDER:     2 — before G11, G33
```

```
TEST:            test_decline_totality
                 tests/conformance/test_decline_totality.py
INVARIANT:       CORE §C.9; Phase 2 E9 test 3; Phase 3 D.9
KIND:            property
FIXTURE:         FIX-2 (a min-size-rejectable leg), FIX-3
PASS CONDITION:  Per tick: `intents in == orders out + declines out`, each
                 decline naming its gate. Sum of planned absolute quantity does
                 not exceed the approved quantity per symbol per tick, across
                 every path including exits.
FAILS TODAY:     yes — the min-order-size rejection is silent, which is the
                 concrete case this makes impossible. That same code path is
                 the one whose change moved the parity hash, net PnL and fill
                 count with CI fully green, caught by hand (`AGENTS.md`) (G24,
                 G38)
COST:            slow replay
BUILD ORDER:     2 — before G24; before X10, whose shed response must be
                 observable as declines rather than as absence
```

```
TEST:            test_attribution_totality_and_reconciliation
                 tests/conformance/test_attribution_totality.py
INVARIANT:       CORE §C.6; Phase 2 E7 test 3, E12 test 3
KIND:            property
FIXTURE:         HARN-1; `sig_contra_fixture_v1` (two strategies contesting one
                 symbol is the only shape where attribution can be wrong)
PASS CONDITION:  Sum of attributed plus unattributed equals fill quantity,
                 always; a non-empty unattributed bucket alerts. Separately, the
                 sum of engine-12 attributed P&L equals engine 7's realized P&L
                 exactly, in `Decimal`.
FAILS TODAY:     unknown, and the ambiguity is itself the finding — fill
                 attribution exists in two places
                 (`src/feelies/kernel/orchestrator.py:_record_fill_attribution:4057`
                 and `src/feelies/alpha/fill_attribution.py`) and whether they are
                 one path or two is unmeasured. If two, engine 12 is
                 reconciling against a number computed twice (G21, G30)
COST:            slow replay
BUILD ORDER:     2 — before G21, G30; this test decides the one-path-or-two
                 question that Phase 2 registered from both sides
```

```
TEST:            test_composition_accounting_identity
                 tests/conformance/test_composition_identity.py
INVARIANT:       CORE §C.6; Phase 2 E6 tests 1 and 2
KIND:            property
FIXTURE:         FIX-2 (cross-sectional, >= 4 symbols, one never trading)
PASS CONDITION:  Per boundary per symbol: `contributors + exclusions ==
                 forecasts in scope`, with a reason on every exclusion.
                 Re-emitting an unchanged target produces zero orders
                 downstream. Permuting per-symbol forecast arrival order yields
                 an identical target portfolio.
FAILS TODAY:     yes for the exclusion-reason clause — no exclusion ledger
                 exists. The order-independence clause is a guard on the
                 platform's best determinism discipline: `math.fsum` over a
                 lex-sorted key list at
                 `src/feelies/composition/cross_sectional.py:75-79`, with Inv-5
                 named in the docstring. But Phase 1 measured 64 of 69 hot-path
                 reductions relying on deterministic input order with nothing
                 guaranteeing it (G19)
COST:            slow replay
BUILD ORDER:     3 — before G15, G19; needs FIX-2, so it cannot precede it
```

### 5.4 Fail-closed and injected fault (X1–X11)

```
TEST:            test_degradation_monotonicity
                 tests/conformance/test_degradation_monotonicity.py
INVARIANT:       CORE §C.5; §G.6 — every degradation has a test asserting
                 exposure <= nominal
KIND:            property
FIXTURE:         HARN-2, FIX-3
PASS CONDITION:  For every entry in the declared degradation set, resulting
                 gross and net exposure are <= the nominal run's at every event.
                 The set is enumerated from the gate registry, so a new
                 degradation with no monotonicity case fails S13.
FAILS TODAY:     yes — two degradations increase exposure. An unrecognised
                 `strategy_id` skips the entire per-alpha budget block
                 (`src/feelies/alpha/risk_wrapper.py:186-192`, G23) and a
                 position-lookup failure is reported to the optimizer as flat
                 (`src/feelies/composition/engine.py:384-389`, G20)
COST:            slow replay (one run per degradation)
BUILD ORDER:     3 — before G20, G23, G35, G43; **the enumeration depends on
                 S13**, so the gate registry precedes it
```

```
TEST:            test_risk_veto_is_monotone
                 tests/conformance/test_risk_monotonicity.py
INVARIANT:       CORE §E.8 "the veto is monotone"; Phase 2 E8 tests 1 and 4
KIND:            property
FIXTURE:         HARN-1 (the no-shadow-book clause)
PASS CONDITION:  For any input, permitted quantity <= requested quantity, and
                 |permitted| <= |current| for any reduction. Composed over both
                 vetoes and both scale factors: no composition produces a factor
                 exceeding either input's, and zero yields no order. Separately:
                 engine 8 computes no exposure not derived from a read of
                 engine 7 — any locally accumulated position or P&L fails.
FAILS TODAY:     yes — no such property test exists, and `RiskVerdict` is
                 published to zero subscribers in any mode (G10), so both of
                 today's vetoes are unobservable outside a trace. The
                 verdict-totality clause (every evaluation emits, including
                 ALLOW) is what makes the property checkable against a run
COST:            fast unit for the property; slow replay for the run assertion
BUILD ORDER:     2 — before G22; **after S11**, which makes `RiskVerdict`
                 observable
```

```
TEST:            test_reduction_is_always_permitted
                 tests/conformance/test_reduction_permitted.py
INVARIANT:       CORE §C.5; Inv-11; Phase 2 E8 test 2
KIND:            property
FIXTURE:         HARN-2
PASS CONDITION:  In every degraded state in the declared set — kill switch
                 active, data unhealthy, macro degraded, drawdown escalated,
                 budget exhausted, halted symbol, stale mark — a flattening
                 order is permitted.
FAILS TODAY:     no — the orchestrator re-ALLOWs reductions at
                 `src/feelies/kernel/orchestrator.py:1782`. This is a **guard**,
                 and it guards the one failure mode worse than permitting too
                 much: a risk engine that can block its own de-risk
FALSIFIED BY:    Delete the re-ALLOW branch at
                 `src/feelies/kernel/orchestrator.py:1782` and run only this test.
                 It must fail for every degraded state. If it still passes, a
                 second guard holds the same invariant — find it and say so in
                 the docstring, per AGENTS.md
COST:            fast unit
BUILD ORDER:     1 — before **every** risk and execution change. Cheap, and it
                 protects the platform's most important asymmetry
```

```
TEST:            test_per_alpha_budget_totality
                 tests/conformance/test_per_alpha_budget.py
INVARIANT:       CORE §C.5; Inv-11; Phase 2 E8 test 3 — **P0 (G23)**
KIND:            injected-fault
FIXTURE:         FIX-3 (unregistered `strategy_id` case), FIX-2 (A>1)
PASS CONDITION:  Every `strategy_id` reaching engine 8 resolves to a budget, or
                 to **zero-with-an-alert**. An id absent from the registry
                 produces no order and one emitted record. Synthetic
                 `__`-prefixed ids take the aggregate-only path **by declaring
                 synthetic-ness**, never by registry absence.
FAILS TODAY:     yes. `src/feelies/alpha/risk_wrapper.py:186-192` guards the
                 per-alpha block with `try` / `except KeyError: pass`, so a
                 `KeyError` falls past the whole `else` branch and the per-alpha
                 position limit, drawdown check and exposure check are all
                 skipped. The condition is registry absence, not
                 synthetic-ness — a config typo, a failed registration, or a
                 renamed manifest all take the fail-open path
COST:            fast unit
BUILD ORDER:     3 — **P0, before G23.** Blast radius today is near zero at A=1
                 because aggregate limits still bind; at A=10 an unregistered id
                 can consume the whole book's allowance, so the containment is a
                 property of the deployment, not the design
```

```
TEST:            test_position_read_fails_closed
                 tests/conformance/test_position_read_fails_closed.py
INVARIANT:       CORE §C.5; Inv-11; Phase 2 E6 test 4 — **P0 (G20)**
KIND:            injected-fault
FIXTURE:         HARN-2, FIX-2 (PORTFOLIO path)
PASS CONDITION:  Inject a position-store failure during construction. Assert:
                 construction **halts**, emits a named failure record, and
                 produces no target. Assert specifically that no symbol is
                 reported to the optimizer as flat when its position is unknown.
FAILS TODAY:     yes. `src/feelies/composition/engine.py:384-389` wraps each
                 lookup in `except Exception: current_positions[s] = 0.0`, and
                 the optimizer computes target minus current — so a failed
                 lookup on a held position sizes a fresh entry on top of it
                 rather than the increment, roughly doubling intended exposure.
                 The handler is marked `# pragma: no cover - defensive`, so it
                 is untested by construction and logs nothing
COST:            fast unit
BUILD ORDER:     3 — **P0, before G20.** Removing the `pragma` is part of the
                 fix; this test is what makes the removal safe
```

```
TEST:            test_pathological_input_refused_with_named_gate
                 tests/conformance/test_pathological_refusal.py
INVARIANT:       CORE §C.9; §I fixture 3; Phase 2 E5 test 4
KIND:            injected-fault
FIXTURE:         FIX-3 (all seven input classes, parametrised)
PASS CONDITION:  Each input class is refused by a **named** registered gate and
                 produces an emitted record. A silent skip fails even when the
                 exposure outcome is correct. No case reaches sizing.
FAILS TODAY:     yes — the fixture does not exist, and the unregistered-id case
                 is known to fail open (G23). The gate names it must bind to
                 come from S13's registry, which does not exist either
COST:            fast unit (parametrised, no session tape)
BUILD ORDER:     3 — before G17, G23, G36, G38; **after S13**
```

```
TEST:            test_no_exception_path_passes_a_gate_or_increases_exposure
                 tests/conformance/test_exception_containment.py
INVARIANT:       CORE §C.9, §F.5 conformance test 1; Inv-11
KIND:            injected-fault
FIXTURE:         HARN-2
PASS CONDITION:  Fault-inject at every declared containment unit. For each:
                 a failure record is emitted, exposure does not increase, and no
                 gate reports a pass it did not evaluate. `NOT_EVALUATED` is a
                 recorded outcome, never an implicit pass.
FAILS TODAY:     yes — this retires the 20-handler class rather than two sites.
                 The two on decision paths are G20 and G23; the remaining 18
                 are on cold or benign paths (import fallbacks, `queue.Empty`,
                 CLI parsing) and this test is what keeps that true (G36)
COST:            slow replay (one injection per containment unit)
BUILD ORDER:     3 — before G36; **after S6**, which enumerates the units
```

```
TEST:            test_cascade_depth_is_bounded
                 tests/conformance/test_cascade_depth.py
INVARIANT:       Inv-7; Phase 1 §3; §F.5 conformance test 4
KIND:            injected-fault
FIXTURE:         HARN-2
PASS CONDITION:  Publish-from-handler depth is bounded at a declared maximum. A
                 cycle raises a typed `INVARIANT_VIOLATION` **naming the
                 cycle** — not `RecursionError`, and not a silent stack
                 overflow.
FAILS TODAY:     yes — 16 of 32 subscribe sites reach `publish` from inside
                 their own dispatch, and `publish`
                 (`src/feelies/bus/event_bus.py:59-70`) has no depth counter, no
                 cycle detection and no seen-set (G02). Phase 1 §3 requires the
                 bound and nothing provides it
COST:            fast unit
BUILD ORDER:     2, atomic with the bound (§0.3) — before G02
```

```
TEST:            test_kill_switch_fail_closed_durable_and_observable
                 tests/conformance/test_kill_switch.py
INVARIANT:       CORE §E.11; Inv-11; Phase 2 E11 test 2
KIND:            injected-fault
FIXTURE:         HARN-2
PASS CONDITION:  Unreadable, uninitialized, or post-restart-uncleared state
                 resolves to **active**. The activation is observable by every
                 layer required to react — at least one subscriber exists in
                 every mode. Durability survives a simulated restart.
FAILS TODAY:     yes on two of three clauses. The switch itself works — it is
                 read directly on the tick path and returns early — but
                 `KillSwitchActivation` has **zero subscribers in any mode**
                 while `src/feelies/core/events.py:416` states it is "published on
                 the bus so all layers can react" (G28), and no durable store
                 exists (G03's mechanism, shared)
COST:            fast unit
BUILD ORDER:     2 — before G28, and with G03's durable-store work, which
                 Phase 2 E11 asks be "one mechanism rather than three"
```

```
TEST:            test_latency_budget_breach_reduces_exposure
                 tests/conformance/test_latency_budget.py
INVARIANT:       CORE §G.7, §C.5; Phase 4 §6 — **P0 (G43)**
KIND:            injected-fault
FIXTURE:         HARN-2 (a stall injected into one engine), FIX-1
PASS CONDITION:  A declared per-engine and per-event budget exists as data. A
                 measured breach produces a **stated, exposure-reducing,
                 replay-deterministic** response: new entries suppressed, exits
                 permitted, one emitted record naming the engine and the
                 measured value. The response is identical in backtest and live
                 for the same event sequence — a budget breach must not make
                 replay non-deterministic.
FAILS TODAY:     yes. **There is no budget in the code.** Of 60
                 latency-comparison sites, every one is event-time causality
                 logic, config sanity, a capital budget, or a connection
                 timeout. `_tick_timings` is written at 3 sites, read once at
                 `src/feelies/kernel/orchestrator.py:2128` and published as
                 metrics — and never compared to anything. The measured 4.2x
                 overrun (136.2 µs/quote against the platform's declared 10
                 µs/event) is invisible to the running system in every mode
COST:            fast unit for the predicate; slow replay for determinism
BUILD ORDER:     4 — **P0, before G43**, and after X1 establishes the
                 monotonicity property this response must satisfy. The
                 instrumentation already exists, so the gap is the comparison
```

```
TEST:            test_reconciliation_divergence_reduces_exposure_and_emits
                 tests/conformance/test_reconciliation.py
INVARIANT:       CORE §F.4; Inv-11
KIND:            injected-fault
FIXTURE:         HARN-2 (a stubbed broker reporting a divergent book)
PASS CONDITION:  Injected divergence beyond the declared tolerance produces the
                 stated exposure-reducing action and an emitted record naming
                 the divergence, at the declared cadence. Divergence within
                 tolerance emits at a lower severity — never nothing.
FAILS TODAY:     yes — reconciliation is 23 sites, 14 of them in the kernel
                 (`src/feelies/kernel/orchestrator.py:_reconcile_fills:4229`), with
                 no declared cadence, tolerance, or breach action (G34). It is
                 also the path that matters most on a live restart, which is
                 G03
COST:            fast unit
BUILD ORDER:     3 — before G34, and with H2, which shares the restart harness
```

### 5.5 Execution honesty and mode parity (H1–H4)

```
TEST:            test_passive_aggressive_fill_eligibility_parity
                 tests/execution/test_router_fill_timing_parity.py (extend)
INVARIANT:       CORE §J optimistic-fill anti-pattern; Phase 2 E10 test 1
KIND:            property
FIXTURE:         none (a fixed quote/trade tape with a resting order)
PASS CONDITION:  Passive and aggressive paths apply **one** eligibility rule on
                 the same tape: no fill from a market event predating
                 `max(clock.now, submit exchange time) + latency`. The two paths
                 agree fill-for-fill; a divergence fails naming both.
FAILS TODAY:     no. Both passive paths already enforce the gate in **exchange**
                 time, and the code says so: `quote.exchange_timestamp_ns <
                 pending.ack_timestamp_ns` at
                 `src/feelies/execution/passive_limit_router.py:527`, whose comment
                 at `:530` states it "mirrors the aggressive path's deferred-fill
                 gate" — the parity this test asserts is the stated intent,
                 verified by reading it today. Also `:242` for the trade-driven
                 queue drain and
                 `src/feelies/execution/moc_fill.py:83`, `:132` likewise), and 589
                 lines of
                 `tests/execution/test_router_fill_timing_parity.py` already pin
                 the passive half. **This test exists to keep it true.** It is
                 the highest-value regression test in the platform, because the
                 failure it guards is biased rather than noisy
FALSIFIED BY:    Change the comparison at
                 `src/feelies/execution/passive_limit_router.py:527` from exchange
                 time to `clock.now` and run only this test. It must fail on the
                 first pre-eligibility quote
COST:            fast unit
BUILD ORDER:     1 — before **any** router change. CORE §H requires this be
                 audited whenever a router changes, not only when a result looks
                 wrong
PROMOTES:        tests/execution/test_router_fill_timing_parity.py — adds the
                 aggressive path and the parity assertion between the two
```

```
TEST:            test_order_idempotency_across_restart_and_reconnect
                 tests/conformance/test_order_idempotency.py
INVARIANT:       CORE §E.10 "exactly-once submission across restart and
                 reconnect"; Inv-11 — **P0 (G03)**
KIND:            injected-fault
FIXTURE:         HARN-2 (kill mid-submission), FIX-3 (duplicate-ID case)
PASS CONDITION:  Kill the process between an order leaving the router and its
                 ack being processed; restart; assert **no duplicate reaches the
                 broker stub**, and that the platform refuses to submit any
                 order whose ID it cannot prove absent from a durable record.
                 Same assertion across a broker reconnect without a restart.
FAILS TODAY:     yes. `derive_order_id` is a pure function of provenance, so a
                 restart re-derives the same ID — correct — but nothing durable
                 records which IDs were *submitted*:
                 `src/feelies/execution/passive_limit_router.py:183` holds
                 `self._submitted_order_ids` as a bare `set()` whose comment says
                 "ever submitted" but whose lifetime is the object's; only
                 `InMemoryTradeJournal` is wired
                 (`src/feelies/bootstrap.py:358`); and
                 `src/feelies/storage/memory_event_log.py:7` states of the only
                 event log that there is "no persistence — all events are lost
                 on process exit". A stable key with nothing to look it up in
COST:            fast unit — **and this is a specification requirement, not an
                 observation.** It must run against a simulated broker backend,
                 never IB. A test marked `paper_rth` is deselected in CI
                 (`.github/workflows/ci.yml:98`) and would be enforced by nothing,
                 which is the exact defect AGENTS.md documents for the parity
                 oracle
BUILD ORDER:     3 — **P0, before G03.** Assumption A5.1 (that IB rejects a
                 duplicate ID server-side) is an unverified external backstop
                 and must not be this test's pass condition
```

```
TEST:            test_mode_parity_with_identically_stubbed_backend
                 tests/conformance/test_mode_parity.py
INVARIANT:       CORE §C.4, §G.8 — one code path, seam only at
                 `ExecutionBackend`
KIND:            replay
FIXTURE:         FIX-1, FIX-2
PASS CONDITION:  The same event sequence driven through the backtest and paper
                 paths, with `ExecutionBackend` stubbed identically, produces
                 identical `Signal`, `SizedPositionIntent`, `OrderRequest` and
                 gate-record streams. Any divergence fails naming the first
                 differing event.
FAILS TODAY:     unknown — no such harness exists. The static half (S7) fails
                 today with 7 mode branches outside the composition root, so a
                 divergence is plausible; but the seam itself is clean, with
                 zero branches inside `execution/` or `broker/`
COST:            slow replay
BUILD ORDER:     4 — after S7. This is CORE §G.8's "proven by a parity test",
                 and it is the only test that can prove it
```

```
TEST:            test_order_state_machine_is_total
                 tests/conformance/test_order_state_totality.py
INVARIANT:       CORE §E.10; Phase 2 E10 test 4
KIND:            property
FIXTURE:         FIX-3 (out-of-order and duplicate acks)
PASS CONDITION:  Every (state, event) pair is defined. An undefined pair
                 **raises** rather than proceeding or being ignored. Exhaustive
                 over the declared state and event enumerations.
FAILS TODAY:     yes — 6 order-lifecycle transitions are authored in the kernel
                 (`_submit_tracked_order:3831`, `_poll_order_router_acks:3793`,
                 `_apply_ack_to_order:4103`, `_transition_order:4086`,
                 `_drain_async_fills:3936`, `cancel_order:3438`, all in
                 `src/feelies/kernel/orchestrator.py`), so order state can be
                 advanced from two modules and no single place enumerates the
                 pairs (G27)
COST:            fast unit
BUILD ORDER:     2 — before G27
```

### 5.6 Purity and attachment (A1–A3)

```
TEST:            test_alpha_output_is_pure_wrt_portfolio_state
                 tests/conformance/test_alpha_purity.py
INVARIANT:       CORE §E.4 "alphas are pure w.r.t. portfolio state"; §C.2
KIND:            replay
FIXTURE:         FIX-2 and one live-shaped alpha
PASS CONDITION:  One feature and regime prefix run against two materially
                 different position books yields a **byte-identical** forecast
                 stream. Also: no engine-4 module reads position, P&L, fill or
                 order state (the static half).
FAILS TODAY:     no — `signals/` is a clean engine-4 package with three inputs,
                 none of them position, P&L or order state
                 (`src/feelies/signals/horizon_engine.py:196-198`). It is a
                 **guard**, it is the single highest-value test on engine 4's
                 sheet, and it is cheap precisely because engine 4 already takes
                 no position input
FALSIFIED BY:    Add a position read to `HorizonSignal.evaluate` that scales
                 edge by current exposure, and run only this test. It must fail
                 on the first boundary where the two books differ
COST:            slow replay
BUILD ORDER:     1 — before every engine-4 and composition change. This is the
                 boundary most likely to be eroded by a convenience read
```

```
TEST:            test_governance_and_forensics_zero_reads_on_tick_path
                 tests/conformance/test_cold_engines.py
INVARIANT:       CORE §C.10; Phase 2 E5 test 1, E12 tests 1 and 2
KIND:            property
FIXTURE:         HARN-1, FIX-1
PASS CONDITION:  Instrument the registry, lifecycle store and every engine-12
                 surface; run a full tick sequence; assert **zero reads** and,
                 for engine 12, zero writes to any engine-5 or engine-8 state.
                 Paired with S2's import-direction assertion.
FAILS TODAY:     **split, and the split is the point.** The read half passes —
                 `hotpath.json` measures `governance_evaluation` at 0 PROVEN and
                 0 per-event, and `promotion/` is correctly cold and append-only
                 (G16). The write half fails: `LIVE -> QUARANTINED` is driven
                 from engine-12 code at
                 `src/feelies/forensics/cost_circuit_breaker.py:159` (G18). Asserting
                 only the read half would report C.10 as satisfied
FALSIFIED BY:    (read half) Add a lifecycle-store lookup inside
                 `HorizonSignalEngine`'s evaluate path and run only this test. It
                 must fail with a non-zero read count
COST:            slow replay
BUILD ORDER:     2 — before G16, G18. The write half's resolution is a
                 re-routing (engine 12 emits a recommendation, engine 5
                 transitions), not a fix to a broken circuit breaker
```

```
TEST:            test_shape_adversarial_alpha_attaches_with_zero_core_edits
                 tests/conformance/test_attachment_cost.py
INVARIANT:       CORE §G.1, §I; Inv-6
KIND:            static check + replay
FIXTURE:         FIX-2
PASS CONDITION:  FIX-2 loads, registers, produces forecasts and reaches an
                 order or a named decline, with **zero diff** under `kernel/`,
                 `bus/`, `core/`, `composition/`, `risk/` and `execution/`
                 relative to the pre-attachment tree. The diff is asserted, not
                 reviewed.
FAILS TODAY:     yes, at minimum at one known point: core config names an alpha
                 as a default value (`moc_strategy_ids` at
                 `src/feelies/core/platform_config.py:108`, repeated at `:910`), so
                 the MOC execution path knows one alpha by name (G25). The
                 identity reduction in the kernel (G15) is the second candidate
                 and cannot be observed at A=1
COST:            slow replay
BUILD ORDER:     4 — after FIX-2 exists and after S3. This is the behavioural
                 half of alpha-agnosticism; S3 is the syntactic half, and a
                 branch on an alpha *characteristic* rather than its name passes
                 S3 and fails here
```

---

## 6. Build order

Ordinals are waves, not a strict sequence within a wave. Phase 7 sequences; this
states only what must exist before what.

| Wave | Contents | Must exist before |
|---|---|---|
| **0** | FIX-1, HARN-1, HARN-2, **S1** (registry closure), **C1** (null analytic reference) | Every other test. C1 is in wave 0 because it is the cheapest detector of a leak introduced by moving code, and it needs only FIX-1 |
| **1** | **S2, S3, S4, S6, S7, S8, S9, S10, S11, S15, R1, R2, R9, X3, H1, A1, C2** | Every remediation step. All are static or cheap, 8 are promotions, and the four guards here (R1, X3, H1, A1) are what detect collateral damage across all 45 gap fixes |
| **2** | **S5, S13, S14, S16, S17, R3, R7, R8, X2, X8, X9, H4, A2, C3** | The engine extractions (G11–G30). S13 and S14 gate wave 3 |
| **3** | **X1, X4, X5, X6, X7, X11, H2, C4, C5, C6, R6, S12** clause (a) | The four P0 fixes (G03, G20, G23) and the ownership moves. X4, X5, H2 are the P0 tests |
| **4** | **R4, R5, X10, H3, A3**, FIX-2, FIX-3 | G07 (schema envelope), G43 (latency budget), G25/G15 (attachment). These need an artifact or a fixture that earlier waves create |

**The one ordering constraint that is not negotiable:** wave 1's four guards
(R1 parity under random seed, X3 reduction always permitted, H1 fill-eligibility
parity, A1 alpha purity) must land before the first line of remediation. They
protect the four behaviours Phase 5 rates as already correct and most valuable —
and every one of them is a behaviour a refactor can silently break.

---

## 7. Cost

| Class | Tests | Marker | Runs in CI today |
|---|---|---|---|
| fast unit | 30 | none | yes |
| slow replay | 19 | `slow` | yes — `slow` stays selected (`.github/workflows/ci.yml:98`) |
| CI-only | 1 (R1) | dedicated job | R1 extends the existing random-seed job |
| **unenforced — forbidden** | 0 | `functional`, `paper_rth` | **No conformance test may carry `functional` or `paper_rth`.** Both are deselected in CI, and the parity oracle needed a dedicated job plus `FEELIES_REQUIRE_BASELINE_CACHE=1` to stop reporting success without executing |

Three tests have a mixed profile and are counted at their primary class: **S14**
(static half fast, dynamic half needs HARN-1), **X2** (property fast, run
assertion a replay) and **X10** (predicate fast, determinism assertion a replay).

Measured runtimes for the promotable static scans, this host, today: gapscan
0.717 s, gatescan 1.299 s, hotpath 2.143 s. The 17 static tests are AST scans
over 196 modules and should total well under 30 s. The 22 replay tests are the
budget: the existing suite is ~4,600 tests inside a 20-minute CI timeout, and
several of these tests run one replay per permutation or per injected fault.
**R3 (registration-order permutations) and X7 (one injection per containment
unit) must be bounded by sampling with a fixed seed**, or they will not fit — and
a sampled property test with an unfixed seed is a flaky test, not a conformance
test.

---

## 8. Findings raised in this phase

Recorded, not fixed, per CORE §H.

### 8.1 A gap Phase 5's table does not contain: zero unit declarations

CORE §C.8 states that "a field whose unit is not declared does not exist." **No
event type declares a unit for any field.** The string `unit` occurs once in
`src/feelies/core/events.py` — as prose in a docstring at `:557`. `SensorReading`
(`:607`) declares `value`, `confidence` and `warm` with no unit; the numeric
payload of `HorizonFeatureSnapshot` (`:631`) is a bare `dict[str, float]` with
`warm`, `stale`, `source_sensors` and `feature_versions` maps beside it and no
units map. `VERIFIED`.

Phase 2's engine-2 sheet flagged this at `docs/architecture/target/out/phase2_contracts.md:241`
as "a Phase 5 gap-table item," and Phase 5's table has no row for it — its
completeness check maps Phase 3's Axis C to G37 and G12 only. **Proposed as
G46, numbered here to avoid renumbering an accepted table.** Severity P1 on the
same grounds as G07: it is not a live safety defect, but it makes every boundary
validation unwritable, which is why S9 sits in wave 1 ahead of every extraction.

### 8.2 Three open questions closed by reading code

| Carried question | Resolution | Consequence for this suite |
|---|---|---|
| **U-4** — can `SensorSpec.subscribes_to` name a type outside the event closure? Phase 2 said "should be resolved before Phase 6" | **No.** `src/feelies/core/platform_config.py:1243` closes it to a hard-coded `{NBBOQuote, Trade}` map and `:1246-1251` raises `ConfigurationError` naming the valid set. `VERIFIED` | Engine 2's input contract is closed **and already enforced**. No test needed; this is a do-not-change entry, and the enforcement point is a model for S13's registry |
| **Throttle time base** — event time or wall time? Phase 2 called the deciding test "the single highest-value test on this sheet" | **Event time.** `src/feelies/sensors/registry.py:244` compares `event.timestamp_ns - last_ns` against `binding.throttle_ns`. `VERIFIED` | R7 is a **guard**, not a gap-closer, and engine 2 is a pure function of the event prefix on this axis. Its `FALSIFIED BY` field carries the value the test would otherwise have |
| **Dynamic imports** — does any exist under `src/feelies/`? Phase 3 carried this as unsettled | **One, and it is constrained.** `src/feelies/core/platform_config.py:1235` is the only `importlib.import_module` in src, and `:1229` requires the target to live under `feelies.sensors.impl.*`. `src/feelies/composition/turnover_optimizer.py:33` uses `find_spec` as an extras probe, not an import. `VERIFIED` | S2's import-graph contract is complete: one config-driven edge, prefix-constrained, so the static graph is the real graph |

Also confirmed: `enforce_layer_gates` appears **zero times** in `configs/`
(closes U-6 in favour of Phase 0 D-14), and `subscribe_all` still has zero call
sites — one occurrence in src, its own definition at
`src/feelies/bus/event_bus.py:55`. `VERIFIED`.

### 8.3 P6's "tests before refactors" is impossible for eleven tests, and the reason is structural

Stated in §0.3 rather than worked around. Eleven tests assert closure over an
artifact the target creates. Phase 7 must sequence those as artifact-plus-test
atomically, and must not report them as "conformance test first."

---

## 9. What this suite does not enforce

| Not covered | Why | What would decide it |
|---|---|---|
| Cross-host parity of the regime engine | Phase 1 §6.1 records both whole-platform stream baselines as exempt because the fixture builds the regime engine, "whose transcendental math is stable only for a fixed host + libm"; `tests/determinism/test_transcendental_determinism.py:70` pins `log`/`exp` intra-process only | A second CI host, and a decision about whether a libm difference is a defect or a portability fact. `.github/workflows/ci.yml:10-18` records that the matrix already answered this once for the *registered* corpus |
| That the 106 uncalled public methods are dead | Static analysis covers `src/` call sites only; A5.4 stays open | Cross-reference `tests/` and `scripts/`, then delete against the parity oracle |
| Live-path latency | Phase 4 A4.4: backtest constructs events before the replay loop, live constructs them per message inside it. A5.5 stays open | Instrument the live ingestion path, which no harness covers. **X10's budget is therefore specified against a measurement the live path does not yet produce** |
| IB's server-side duplicate-order rejection | A5.1. H2 deliberately does not depend on it | A deliberate duplicate submission against paper IB, which is `paper_rth` and so never runs in CI |
| Whether a static check survives an author who does not know the rule | Phase 3's own ranking: only M1 (constructor injection) and M4 (read-only types) survive ignorance. **Every S-group test is M2, M3 or M6 — "no, but loudly"** | Nothing. This is a stated limit of a conformance suite, and it is why Phase 2's sheets keep converging on injection and read-only views rather than on tests |

**The honest summary of that last row:** this suite raises the cost of violating
an invariant from zero to a failed build. It does not make violation
impossible. The 36 direct store calls from the orchestrator into two position
stores are currently held by "type annotations plus `mypy --strict`, not a
runtime check" — the weakest mechanism applied to the platform's strongest
invariant — and no test in this document changes that. Only the extraction does.

---

## 10. Verification performed on this document

- `tools/arch/gapscan.py`, `tools/arch/gatescan.py` and `tools/arch/hotpath.py`
  re-run this session. Every headline number reproduced Phase 5: orchestrator
  5,480 lines / 123 methods / 22 public; 27 mode branches all outside
  `execution/` and `broker/`; 3 alpha-id literals; 16 G-numbers with no detected
  no-op stub; 31 classes in `src/feelies/core/events.py` with 2 carrying a version
  field; 20 fail-quiet handlers; 329 runtime gate sites across 10 families; 13
  unconditional per-event prohibited hits; 310 of 1,478 functions executed inside
  `run_backtest`.
- Five carried questions closed by reading source, each cited at `path:line`
  (§8.2). None was resolved by inference.
- One gap absent from Phase 5's table found and recorded as proposed G46, not
  inserted into the accepted table (§8.1).
- Both existing fixture manifests read before specifying FIX-1 to FIX-3, per
  CORE §I's instruction, and the roles they cover stated in §4.1 — including the
  finding that neither covers FIX-2 as CORE §I defines it.
- Every test's `FAILS TODAY` value is a claim about measured current state.
  Where it is `unknown` it says so and says what would decide it; where it is
  `no` it carries a `FALSIFIED BY` mutation, per `AGENTS.md`.
- **Every `FALSIFIED BY` mutation target was opened and read, and two were wrong
  in the first draft.** R1 and R8 both named a `sorted()` at
  `src/feelies/composition/synchronizer.py:80`; that line is
  `for h in self._context_horizons:` — a validation loop over a frozenset that
  raises on a non-positive horizon, which is one of Phase 5 G08's *unsorted*
  iteration sites and not a sort at all. R8 now names the verified sort at
  `src/feelies/composition/cross_sectional.py:78`, and R1 is restated as an
  injection because Phase 5 established there is no sort whose removal breaks
  the hash today. A mutation instruction that does not compile is worse than no
  guard, because the guard reports green either way.
- `tools/arch/measure.py spotcheck -n 80` reports **57 distinct citations, 57
  sampled, 0 failures** — `n` exceeds the population, so this is the full set and
  no seed variation is required. One failure in the
  first draft was Phase 5's exact defect recurring — moc_fill.py:83 written
  package-relative rather than under `src/feelies/`. It is written unbracketed
  here for the reason Phase 5 records: inside backticks the checker reads an
  illustrative bad path as a live citation and fails it, which is how that note
  reintroduced three failures. Writing this sentence reintroduced the failure
  once before the path was unbracketed.
- Intended new paths are written unbracketed so `tools/arch/measure.py spotcheck`
  does not read them as citations — Phase 5's recorded defect.
- Scope guard run: `powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1`
  reports `scope: OK -- no protected-path changes`. No writes outside
  `docs/architecture/target/out/` and `tools/arch/`.

---

**HARD STOP** — Phase 6 complete. 50 tests, 3 fixtures and 2 harnesses
specified. No test written, no fixture built, no remediation sequenced.
