# PHASE 6 — Conformance suite specification

**Runs in:** Cursor, Agent mode, Opus. Must fit the existing test harness.
**Output:** `docs/architecture/target/out/phase6_conformance.md`
**Attach:** `00_CORE.md` + this file + `out/phase1` … `out/phase5` + `@tests` + `@tools/arch`

---

A target architecture that depends on discipline will decay. Specify the tests that make each invariant mechanical.

**These are built first.** Conformance tests come *before* the refactors they protect, and Phase 7 must sequence them that way.

## Required coverage

| Invariant | Enforcing test |
|---|---|
| Dependency direction, acyclicity | Import-graph contract test in CI |
| Boundary contracts | Runtime payload validation at bus dispatch, provenance in the error |
| Gate ladder integrity | Enumeration parity: code-defined ladder vs. generated docs vs. tests |
| Determinism | Bit-identical replay under `PYTHONHASHSEED=random`, manifest fingerprint, stated parity surface |
| Schema evolution | Historical log replays to its original output under the CORE §F.7 policy |
| Conservation | Null-tape, level-based, analytic reference |
| Execution honesty | Passive/aggressive fill-eligibility parity |
| Order idempotency | Duplicate-submission test across simulated restart and reconnect |
| Alpha-agnosticism | Static check: no alpha ID / symbol literal / archetype name outside `alphas/` and config |
| No wall clock on tick path | Static check over the hot-path module set |
| Degraded monotonicity | Property test: for every degradation, exposure ≤ nominal |
| Exception containment | Injected-fault test: no exception path increases exposure or passes a gate silently |
| Single owner per fact | Producer-uniqueness test over the emitted-type registry |
| Mode parity | Backtest vs. paper equivalence with the backend stubbed identically |
| Reconciliation | Injected divergence produces the stated exposure-reducing action and an emission |

Add any invariant from CORE §C or a Phase 1–4 target that this table misses. **Every invariant in CORE §C must map to at least one row** — state which rows cover which invariants.

## Per-test specification

```
TEST:            [name and intended file path in tests/]
INVARIANT:       [CORE §C number, or target statement + phase]
KIND:            [static check | unit | property | replay | injected-fault]
FIXTURE:         [which of the CORE §I fixtures it needs, if any]
PASS CONDITION:  [exact]
FAILS TODAY:     [yes/no — run it mentally against Phase 5; a test that cannot
                  fail today protects nothing]
COST:            [runtime class: fast unit | slow replay | CI-only]
BUILD ORDER:     [ordinal — which gaps it must exist before]
```

## Reuse before you invent

Several Phase 0 measurement scripts under `tools/arch/` are already most of a static check. Say explicitly which conformance tests are a promotion of an existing script rather than net-new code — this is what keeps CORE §G.10 honest.

## Fixtures

Specify the three required fixtures from CORE §I concretely enough to build: null alpha, shape-adversarial alpha, pathological alpha. For each: what it emits, what it proves, and which tests consume it.

**HARD STOP.** Write the file, then stop.
