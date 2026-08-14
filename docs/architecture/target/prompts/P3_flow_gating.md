# PHASE 3 — Axes B, C, D: Integration, Information flow, Gating

**Runs in:** a fresh Claude chat, **not Cursor.** Pure design.
**Output:** paste into `docs/architecture/target/out/phase3_flow_gating.md`
**Attach:** `00_CORE.md` + this file + `out/phase1_plumbing.md` + `out/phase2_contracts.md`

Three parts, each with its own hard stop. Do **not** run 3.2 until 3.1 is accepted.

---

## 3.1 — Axis B: Integration (composition without coupling)

- **Dependency direction rule.** The legal direction of dependence between engines, stated as an enforceable constraint over the import graph. Cycles are defects; name the tool that proves absence.
- **Lifecycle.** Construction order, readiness protocol, degraded state, shutdown. What each engine does when a dependency it needs is degraded or absent — specified per engine, not left to whatever the null case happens to do.
- **Extension points.** Precisely what must be true for the 2nd, 5th, and 20th alpha to attach with zero core edits (CORE §G.1). Design against this directly; do not hope it falls out.
- **Multiplicity.** Multi-symbol, multi-alpha, multi-horizon, multi-strategy. Per-strategy positions and net positions are different objects with different owners — state which engine reconciles them and how a discrepancy surfaces.

**HARD STOP.**

---

## 3.2 — Axis C: Information flow

- **Canonical path with payloads named at every hop**, including units, timestamp semantics, and provenance:

  `Market Data → State/Features → Regime + Alpha → Portfolio Construction → Risk & Capital → Execution Decision → Routing/Fills → Portfolio Accounting → Observability/Forensics → Alpha Governance`

- **Four-way separation, enforced by type.** *Forecast* (what alpha believes) ≠ *decision* (size, price, urgency) ≠ *action* (order) ≠ *fact* (fill, position, P&L). A type carrying two of these is a defect — name every place the current system carries two.

- **Feedback edges.** Legal: fills → accounting → risk; forensics → governance; regime → everyone; reconciliation divergence → safety. Illegal and to be designed out: P&L → alpha; realized outcome → feature computation; execution state → alpha; governance evaluation → tick path.

- **Staleness and provenance on every emission.** A consumer must determine, from the payload alone, how old the information is and what produced it. Scalar emissions without staleness metadata make fail-safe consumers unimplementable.

- **Recompute policy.** What must never be recomputed downstream (edge, cost, mark, position) vs. what must be independently recomputed as a declared conservation audit. Conservation audits are **level-based, not shape-based** — a shape test cannot detect a sign-symmetric error.

**Required artifact — the forbidden-reads matrix.** A 12×12 table: for each engine pair, whether a read is permitted and by what mechanism the prohibition is enforced. Non-negotiable seed rows: alpha reads no position/P&L/fill/execution state; features read nothing downstream of themselves; risk reads marks and positions, never raw quotes; routing reads a plan, never an edge; governance is read on the tick path only as an immutable snapshot resolved at composition.

**HARD STOP.**

---

## 3.3 — Axis D: Gating

Two ladders. Conflating them is a known failure mode. Specify each separately.

- **Governance ladder** (cold): alpha validation, layer checks, dependency resolution, promotion, quarantine. Decides what is *eligible* to run.
- **Runtime ladder** (tick-critical path): the ordered checks a decision passes from raw event to submitted order. Decides what happens *now*.

**Every gate, in both ladders, gets this record:**

```
GATE:            [stable ID + name]
LADDER:          [governance | runtime]
OWNER ENGINE:    [1-12, exactly one]
LATENCY CLASS:   [hot | cold]
POSITION:        [ordinal; total order, no ties]
INPUTS:          [named contracts, with staleness tolerance]
PREDICATE:       [exact pass condition]
ON FAIL:         [reject | degrade | quarantine | halt]
ON UNKNOWN:      [must be the exposure-reducing branch]
ON EXCEPTION:    [per CORE §F.5; must not be silent]
EXPOSURE EFFECT: [must be <= ungated path]
EMISSION:        [what observability records, always]
TESTED BY:       [test ID]
```

Plus:

- **Single-source enumeration.** The ladder is defined once, in code, as data; docs and tests are generated from it. A gate sequence existing in three prose descriptions and a fourth form in code is not a specification — it is four claims. If numbering has holes, either the hole is meaningful and documented, or the numbering is wrong.
- **Precedence.** Where two gates can fire on the same event, a total order resolves it. No implementation-defined ties — simultaneous-breach ambiguity biases results optimistically in exactly the scenarios that matter.
- **De-risking monotonicity.** No path through the ladder produces greater exposure than the ungated path. State the test.
- **Observability of every rejection.** A gate that silently rejects is indistinguishable from a gate that never fires.

**HARD STOP.**
