**Basis.** Phase 3 has no repo access by design (P3: "Runs in a fresh Claude chat, not Cursor. Pure design."). Every current-state claim below is carried from Phase 0 / Phase 1 / Phase 2 at the label those documents assigned it; nothing is upgraded to `VERIFIED` here. New material is target-state specification, labelled `specified`.

---

# PHASE 3 — Axes B, C, D

## 3.1 — Axis B: Integration (composition without coupling)

**The result.** Integration reduces to one rule and two graphs.

The rule: **no engine depends on another engine.** An engine depends only on contracts, on kernel mechanism, and on handles injected at the composition root and typed by a protocol that lives with the contracts. That collapses "the legal direction of dependence between engines" from a 12×12 adjacency question into a tier question with a one-line check.

The two graphs are the **import graph**, which the tier rule constrains statically, and the **subscription graph**, which is the platform's actual integration graph. P3 asks for the first. The second is where this axis's real defect sits: 32 subscribe sites, 16 of them publishing from inside their own dispatch, delivery order output-determining, no depth bound, no cycle detection, and nothing hashing any of it (Phase 1 §3, `VERIFIED`). **A clean import graph over an unenumerated subscription graph is a proof about the wrong object**, so this axis specifies both.

---

### B.1 — Dependency direction

#### The tier rule

| Tier | Contents | May import | Imported by |
|---|---|---|---|
| **0 — Contracts** | Event types, protocols, units, identifiers, the `Clock` protocol, the config *schema*, the failure taxonomy (§F.5), `schema_version` (§F.7) | Nothing in tiers 1–4 | Everything |
| **1 — Mechanism** | Bus dispatch, sequencing and the total-order key protocol, state-machine framework, exception propagation mechanism, barrier mechanism, durable-store mechanism, parity oracle | Tier 0 | Tiers 2–4 |
| **2 — Engines** | The twelve, and their adapters | Tiers 0, 1. **Never another Tier-2 module** | Tier 3 |
| **3 — Composition root** | `src/feelies/bootstrap.py` | Everything | Tier 4 only |
| **4 — Entry** | `cli/` | Tier 3 | Nothing |

`specified`. Tier 1 is populated by calls already made in Phase 2: the ordering *key protocol* is kernel while engine 1 is its client (engine 1 sheet), the *barrier mechanism* is kernel-class while engine 6 owns the completeness policy (engine 6 overlap 4), the failure *taxonomy* is kernel while each engine owns its classification (§F.5), the parity *oracle* is kernel while engine 12 reports against it (engine 12 overlap 1). This axis adds two on the same pattern — the durable-store mechanism (engine 11's sheet already asks that kill-switch durability, the submitted-order journal and the book "be one mechanism rather than three") and the wiring manifest below.

**The trade-off, stated.** Everything a consumer needs from a producer must now be a Tier-0 contract or a Tier-1 mechanism, which pushes surface into `core/`. A fat contracts tier is its own failure. **Bound it:** Tier 0 holds declarations and no behaviour, and its module count and public-symbol count are reported in the net-complexity ledger (CORE §G.10). A Tier-0 module that executes a policy is a Tier-1 or Tier-2 module in the wrong place.

#### The engine-to-engine graph that survives: five handle edges

A handle is permitted only where a synchronous, as-of-event-time read is required and a published contract cannot supply it. Everything else is a bus contract.

| Edge | Purpose | Form |
|---|---|---|
| 6 → 7 | Positions as-of the boundary, for turnover control | Read-only view |
| 8 → 7 | Positions and marks as-of the tick, for the veto | Read-only view |
| 9 → 7 | Positions and marks as-of the tick, for plan construction | Read-only view |
| 12 → 7 | Positions, marks, P&L as-of, for attribution | Read-only view |
| 8 → 11 | Kill switch — the one hot read of a cold engine (CORE §D) | Read-only, total |

`specified`. **The acyclicity check is one line: no handle originates at engine 7 or engine 11.** Both are sinks; neither holds an outgoing handle. Every other engine-to-engine relationship in the twelve sheets is a published contract, which means it is subject to the subscription graph rather than the import graph.

Three edges that look like handles and are not, recorded so they are not re-argued: 7 → 8 for the high-water mark is today a duck-typed poke, `getattr(..., "refresh_high_water_mark", None)` at `src/feelies/kernel/orchestrator.py:1616`, where an absent attribute silently means drawdown escalates against a mark that never moves (Phase 0, `VERIFIED`; engine 7 overlap 4) — under the target engine 8 subscribes to engine 7's mark contract and the poke disappears. 9 → 10 for the cost estimate is a published estimate carrying its model version, not a reach into the model (engine 10 EMITS). 5 → everyone is a frozen artifact consumed once at composition, not a service (engine 5 OWNS 7).

#### The second graph: the wiring manifest

`specified`, and it is the artifact this axis is really for.

Subscriptions are declared **once, as data, at the composition root**: `(event_type, subscriber, ordinal, absent_by_config?)`. Docs and tests are generated from it, the manifest is hashed, and the hash enters `config.snapshot().checksum`. From it, four properties become checkable that today are not:

1. **Delivery order is pinned.** Phase 1 §3 measured registration order as an output-determining input whose only enforcement is six prose comments in `build_platform`, one of them `src/feelies/bootstrap.py:355` ("Subscribe the router before sensors so fills retain their triggering quote") — `VERIFIED`, `open defect`. A hashed manifest retires it.
2. **The cascade graph is enumerable and its depth is bounded.** 16 of 32 handlers publish from inside their own dispatch; the cascade is a DAG today and nothing enforces that it stays one, so a cycle surfaces as `RecursionError` inside the tick-wide `try/except` with no indication of cause (Phase 1 §3, `VERIFIED` / `INFERRED`). The manifest gives the graph; §F.5 already requires the bound and classifies a cycle as `INVARIANT_VIOLATION` rather than a degraded macro state.
3. **Unwired is distinguishable from wired.** `RiskVerdict`, `StateTransition`, `SymbolHalted` and `KillSwitchActivation` have no subscriber in any mode, and two of them carry docstrings describing consumers that were never built (Phase 0 C-4, `VERIFIED`). `PositionUpdate` and `OrderAck` gain consumers only in backtest, through a dynamic subscription reaching `orchestrator._bus`, a private attribute (`src/feelies/harness/backtest_runner.py:246`, Phase 0 C-5/C-9). An `absent_by_config` entry makes "nobody listens" a declared value rather than a typo, which is engine 11's `never-seen` rule applied to wiring instead of to streams.
4. **Publishes with zero handlers become audible.** Dispatch is exact-type, `self._handlers.get(type(event))` at `src/feelies/bus/event_bus.py:65`; on a miss `publish` returns having done nothing — no exception, no counter, no log (Phase 1 §3, `VERIFIED`). With a manifest, a zero-handler publish for a declared type is a contract violation, not silence.

**Trade-off.** The manifest is a net addition. It is admissible under CORE §G.10 as a contract definition plus conformance test, and it deletes the six ordering comments and the tacit knowledge they encode.

**Precedent for the ordering claim, and one correction it forces.** Where a subscription-order comment encodes a *semantic* requirement rather than a tie-break, the requirement must be re-expressed as a contract field. `bootstrap.py:355` is the instance: "fills retain their triggering quote" is fill provenance, which engine 10's EMITS clause already requires. Once provenance is on the payload, the ordering constraint is only a deterministic tie-break, which is what a manifest can honestly pin. `specified`.

#### Enforcement — the tool, and what it cannot see

**The call: `import-linter`, with `grimp` for evidence.** `import-linter` expresses the tier rule as a *layers* contract (tiers 0→4, no upward import) and the no-engine-imports-an-engine rule as *independence* contracts over the twelve engine module sets. It runs in CI and fails the build. `grimp` — the graph library beneath it — is called directly from a new `tools/arch/importgraph.py`, emitting `tools/arch/evidence/importgraph.json` per CORE §H's measure-don't-estimate rule. `specified`, not run: this phase has no repo access.

Be precise about what each proves. **A layers contract forbids upward imports, which forecloses every cycle that crosses a tier — but not a cycle inside one.** Intra-tier cycles need strongly-connected-component detection on the graph, which is `grimp`'s job, not the contract's. Naming one tool for both would repeat Phase 1's headline mistake in a new place: enforcement granularity not matching the property.

Three blind spots, each with the call:

- **`TYPE_CHECKING`-guarded imports count as real dependencies.** A guarded import of another engine's type is exactly the dependence Tier-0 protocols exist to remove, and excluding it lets the rule pass while the design fails. Configure `import-linter` to include them.
- **Dynamic imports are invisible.** Whether any exist under `src/feelies/` is unmeasured in Phase 0–2 as carried — registered below.
- **Private reach-through is invisible.** `harness/backtest_runner.py:246` creates a hard dependency on the orchestrator's internals that no import contract can see; Phase 0 C-5/C-9 measured ten cross-object private accesses. The import graph is necessary and insufficient, and the companion check is an AST test forbidding cross-object access to a name beginning with `_`, on the template already proven at `tests/acceptance/test_no_walltime_outside_clock.py:72` with its stale-entry guard at `:96`.

**Alternatives set aside:** `tach` (fewer contract types, newer, and the platform already has the AST-test idiom `import-linter` complements); a bespoke `tools/arch/` checker alone (rebuilds a solved graph problem and gives CI nothing to fail on); `pydeps` (visualization, not enforcement).

#### What the rule says about current state

- **Cycle 2 is caught by direction, not by cycle detection.** Phase 0 D0.1 measured `feelies.core.inv12_stress` → `feelies.core.platform_config` → `feelies.promotion.evidence`, putting the governance package in the import closure of anything that loads platform config (`VERIFIED`, engine 5 sheet). Under the tier rule the violation is Tier 0 → Tier 2 and is illegal whether or not it closes a loop. **Direction is the stronger check and it fires first**; SCC detection is the residual for cycles that stay inside one tier. The root cause is placement — a stress/validation module sits in the contracts tier — so the fix is a move, not an import rearrangement. `INFERRED` from the module name; CORE §J warns against assuming a name means what it says, so this is a hypothesis to check in Phase 5, not a finding.
- **Enforcement must be module-granular, not package-granular.** Three packages carry modules belonging to different tiers and must split for the rule to be checkable: `core/` (contracts plus `platform_config.py`, which reaches Tier 2), `kernel/` (mechanism plus the orchestrator's Tier-2 responsibilities), `storage/` (engine 1's event log and cache replay, engine 2's snapshot store, and §F.2 reference data — Phase 0 D0.2 lists the last "consumed by engines 6, 7, 10 and by `bootstrap`; owned by none"). Two more must split for *intra-tier* independence rather than for the tier rule: `alpha/`, which hosts work belonging to engines 4, 6, 7 and 8 across 14 modules and 4 652 sloc (Phase 0 D0.2, `VERIFIED`), and `execution/`, where the policy/mechanics line between engines 9 and 10 is drawn correctly at module level and enforced by nothing (engine 10 overlap 2).
- **The god orchestrator is a tier violation, not a size problem.** `src/feelies/kernel/orchestrator.py` is 4 778 sloc and 11.8% of the platform (Phase 1 §1, `tools/arch/evidence/inventory.json`, `VERIFIED`), and the twelve GAP lines of Phase 2 place inside it methods claimed by engines 1, 2, 3, 7, 8, 9, 10, 11 and 12. The tier rule *determines* where each of those belongs — the engine whose sheet claims it — so decomposition is not a negotiation. **Sequencing and blast radius are Phase 7's; this axis states only that the target placement is fixed and that what remains in Tier 1 is dispatch, sequencing, the clock, the state-machine framework, the exception taxonomy and the schema gate.**

---

### B.2 — Lifecycle

#### Five phases

| Phase | What happens | Failure |
|---|---|---|
| **0 Resolve** (cold) | Engine 5 produces the resolved registry, `UniverseSnapshot` (§F.1) and `IdentityMap` (§F.2); the kernel resolves the declared schema-support set (§F.7); the run fingerprint is computed over all of it | **Fail the boot.** Engine 5's sheet: "a platform that starts with a partial alpha set is trading a configuration nobody specified" |
| **1 Construct** | The composition root constructs all twelve, injecting only Tier-0-typed handles and frozen artifacts. No engine constructs another (CORE §E) | Raise. A constructed-but-unusable engine is the object-level form of `never-seen` reading as `healthy` |
| **2 Wire** | Subscriptions registered from the manifest, in declared ordinal order; manifest hash recorded | Any subscription not in the manifest, or any manifest entry with no subscriber and no `absent_by_config`, fails |
| **3 Arm** | Each engine declares readiness once; the platform accepts no market-data event until every engine is `READY` or `ABSENT_BY_CONFIG` | Refuse to arm, naming the engine and reason |
| **4 Run** | Per-engine state in `HEALTHY` / `DEGRADED(reason, exposure_effect)` / `FAULTED` | §F.5 taxonomy |
| **5 Quiesce** | Stop accepting, drain, durably commit, emit the session-close record | Below |

`specified`.

#### Construction order and subscription order are different problems

**Construction order is a topological sort of the handle graph and nothing more.** Engines 11 and 7 are sinks, so they construct first; the remaining ten construct in ordinal order. That order must be declared as data, and it must be asserted **not** to affect output: permuting the construction of any two engines with no handle edge between them must produce an identical stream. That property is already half-built — 26 sequence generators exist and their isolation is deliberate and pinned (`src/feelies/bootstrap.py:272`, "Isolate risk alerts so they cannot shift orchestrator event IDs"; `tests/determinism/test_legacy_sequence_isolation.py:12`, Phase 1 §2, `VERIFIED`). Sequence-space isolation is exactly what makes construction order non-load-bearing for event identity, and the permutation test generalizes one pinned instance into a property.

**Subscription order is load-bearing and must be pinned, not eliminated.** This is the split that matters: construction order is proven irrelevant, subscription order is declared, hashed, and made the *only* ordering input. Anything else that turns out to matter is a defect against the manifest.

#### Readiness

`readiness() → READY | NOT_READY(reason)`, total, **evaluated once at arm and never on the tick path** — a readiness check on the tick path is governance on the tick path and violates CORE §C.10 in a new costume.

**Warmup is not readiness.** Engine 2's `min_history` produces `warm=False` per feature, which is a property of the tape (engine 2 sheet). Folding warmup into readiness would make readiness a function of the event stream and therefore re-evaluated per event. The two must not share a vocabulary. `specified`.

**There is no re-arm.** A dependency that becomes absent after arm is a fault under §F.5, not a return to `NOT_READY`. Re-arming mid-session would make composition a runtime concern.

#### The absence rule

P3 asks what each engine does when a dependency it needs is degraded or absent. Phase 2 already specified *degraded input* per engine, input by input. What no sheet covers is **structural absence** — the dependency is not merely producing bad values, it is not there. That is the gap this axis fills, and it is governed by one rule:

> **Absence may remove an opportunity. It may never remove a truth, a constraint, or the ability to reduce.**

That is CORE §C.5 applied to composition rather than to input, and it generates the table rather than the table being twelve opinions.

| Engine | Absence removes | Behaviour | Basis |
|---|---|---|---|
| 1 Market Data | Truth (prices) | **Refuse to arm.** Running with no feed and running with a dead feed must never be one observable state | `specified`, on engine 11's four-way health rule |
| 2 State/Feature | Opportunity | Run. Empty feature set; alphas suppress; flat | Engine 2 substitutability: "the null fixture must leave the platform stable with an empty feature set" |
| 3 Regime | Opportunity | Run. Every consumer takes its declared no-regime branch | Engine 3 test 4 (removability) |
| 4 Alpha | Opportunity | Run. Engine 6 emits an **explicit flat target**, not silence | Engine 6 degraded table |
| 5 Governance | Constraint — but substitutable | Run with a fixed registry literal, identically. This is the proof that governance is off the tick path, and it is a test, not an operating mode | Engine 5 substitutability (absent-able) |
| 6 Portfolio Construction | Opportunity | Run. No new targets; de-risk still reaches engine 9 without passing through 6 | `specified` |
| 7 Accounting | **Truth** | **Refuse to arm.** No book means engine 8 cannot veto, engine 6 cannot compute turnover, engine 12 cannot attribute | Engine 7: "sole in-process truth" |
| 8 Risk & Capital | **Constraint** | **Refuse to arm.** Absence of the veto must mean no trading, never no vetoes | CORE §E: the veto is monotone and last before exposure |
| 9 Execution Decision | The ability to reduce | **Legal from flat only.** With any position open, refuse to arm — an undischargeable de-risk requirement is a requirement that expires quietly | Engine 9: "de-risk deadline missed ⇒ escalate, never expire quietly" |
| 10 Execution Sim/Routing | The ability to reduce | **Legal only in a declared non-trading mode.** A null backend must be a configuration, not an accident of wiring | CORE §C.4; engine 10 is the single mode seam |
| 11 Observability & Safety | **Constraint** | **Refuse to trade.** The platform must decline, not run unmonitored | Engine 11 substitutability — the sharpest of the twelve |
| 12 Research/Forensics | Opportunity, with a consequence | Run, trading identically. Engine 5's evidence starves, and alphas move toward quarantine rather than staying LIVE by inertia | Engine 12 substitutability |

Four engines are arm-blocking (1, 7, 8, 11), two are conditionally arm-blocking (9, 10), six are absent-able (2, 3, 4, 5, 6, 12).

**Trade-off.** Four hard blocks make casual partial-platform runs impossible, which is the point and is also a real cost to development. `ABSENT_BY_CONFIG` plus a declared non-trading mode is the mitigation, and the discipline that keeps it honest is that the mode is a config value entering the run fingerprint, not a wiring omission.

#### Engine-level degraded, and macro state derived rather than set

Each engine declares `DEGRADED(reason, exposure_effect)` with `exposure_effect ∈ {none, reduce_only, halt}`. **Platform macro state is the most restrictive of the twelve — a join over a lattice, computed in one place, monotone within a fault episode.**

Today it is *set*: the tick-wide handler at `src/feelies/kernel/orchestrator.py:1466` → `_handle_tick_failure:1474` drives macro to `DEGRADED` (Phase 0 D0.4, `VERIFIED`). The difference is not cosmetic. **A state that is set can be cleared by a subsequent success while the underlying engine is still broken; a state that is derived cannot.** `specified`.

#### Shutdown

Ordered, and the ordering is not the reverse of construction:

1. **Stop accepting** at engine 1. Shutting down under load is how a quiesce becomes an incident.
2. **Engine 8 to `reduce_only`.** Not flatten.
3. **Drain in-flight orders** to a terminal state or to a durably-recorded `UNKNOWN`, which under engine 10's degraded rule blocks the next boot from submitting that ID.
4. **Durable commit** — kill-switch state, submitted-order journal, promotion ledger, evidence record, book of record — through the one Tier-1 durable-store mechanism.
5. **Drop per-run state. Write no warm-start snapshot.** Cold start is the only replay contract (Phase 1 §5 call), which retires the SHA-256 computed at `src/feelies/kernel/orchestrator.py:5466` on every shutdown into a store that is always in-memory (`src/feelies/storage/memory_feature_snapshot.py:16`, constructed empty per boot at `src/feelies/bootstrap.py:359`, `VERIFIED`).
6. **Emit the session-close record.**

**The call on step 2, with its trade-off: shutdown does not flatten.** An operator who expects flat-on-exit will carry a position across a restart, and that must be an explicit operator action. The justification is the failure it prevents: coupling liquidation to process exit turns a crash-restart loop into repeated liquidation of the book, and a crash-restart loop is the failure mode the platform will actually experience.

**The governing property: clean shutdown and `SIGKILL` must leave the same *class* of state.** If a clean exit produces a safe state that a crash does not, the safety is decorative — the platform meets the second condition far more often than it plans for the first. Everything shutdown commits durably must therefore already be true continuously: journal-before-wire (Phase 1 §4 resolution), kill-switch durable on write (engine 11), book durable on update (engine 7). Shutdown's only unique jobs are *stop accepting* and *emit the close record*. Today neither half holds — `src/feelies/storage/memory_event_log.py:7` states all events are lost on process exit, `self._submitted_order_ids` at `src/feelies/execution/passive_limit_router.py:183` means "since this object was constructed", and `_next_valid_id` at `src/feelies/broker/ib/connection.py:353` is rebuilt from the broker handshake each process (Phase 1 §4, `VERIFIED`, `open defect`).

**Reset, and what shutdown does not fix.** Phase 1 §5 measured 110 classes holding instance state, 38 mutating it outside `__init__`, and **32 of those 38 with no reset path of any kind** (`VERIFIED`). Lifecycle cannot be specified over state that has no declared reset, so every sheet's `reset()` obligation is a precondition of this axis, not an adjacent nicety. What stands in for reset today is `_handle_tick_failure` clearing three named attributes — a recovery path over three fields, not a reset over declared state.

---

### B.3 — Extension points

**The 2nd, the 5th and the 20th alpha are three different questions, not one question three times.** CORE §I is explicit that the untested axes are symbol cardinality, horizon and archetype, and that "adding a twelfth alpha proves nothing the eleventh did not." Designing against §G.1 means designing against what each of those three numbers actually tests.

| | What it tests | What breaks first, measured |
|---|---|---|
| **2nd** | **Isolation and arbitration.** Does A's presence change B's stream? | `_select_bus_signal` at `src/feelies/kernel/orchestrator.py:1676` returns one `Signal` per tick and discards the rest (Phase 0 D0.4 hop 28, `VERIFIED`). At N=1 that is a no-op; at N=2 it is the entire behaviour. Registration order becomes an output-determining input with no test (Phase 1 §3) |
| **5th** | **Keying totality.** Five strategies × N symbols means budgets, position buckets, attribution rows and universes are all matrices | `except KeyError: pass` at `src/feelies/alpha/risk_wrapper.py:189` — an unregistered `strategy_id` skips **all** per-alpha budgets (Phase 0 E-2, `VERIFIED`). At N=1 an incidental hole; at N=5 a systematic one |
| **20th** | **Single-source enumeration.** Anything maintained by hand has drifted | The load-gate ladder is 52 sites with a hole at G13 that nothing enumerates (Phase 0 G-1, `VERIFIED`); the `regime_gate` family is 56 sites across four packages (Phase 0 D0.5) |

#### What must be true — six conditions

1. **One attachment surface.** An alpha is a manifest under `alphas/` plus a config selection. **The test is mechanical:** attach a fixture alpha, assert the change set touches nothing outside `alphas/` and `configs/`, and assert `config.snapshot().checksum` moves.
2. **One resolution point.** Engine 5, at composition. Nothing re-reads a manifest per event (CORE §C.10).
3. **Zero identity branches, and this is where §G.1 is measurably false today.** `moc_strategy_ids: tuple[str, ...] = ("sig_moc_imbalance_v1",)` at `src/feelies/core/platform_config.py:108`, with the same literal as the YAML fallback at `:910`, reaches `_moc_strategy_ids` at `src/feelies/kernel/orchestrator.py:876` and is tested at `:3386` to set `OrderRequest.is_moc`, which diverts an order from the continuous book to the closing auction (`src/feelies/core/events.py:288`). No file under `configs/` or `platform.yaml` sets it, so every deployment inherits the hardcoded default (Phase 0 E-1, `VERIFIED`; engine 9 sheet). **A second alpha needing a different route cannot be attached today without editing a Tier-0 module. That is not an example of a §G.1 risk; it is §G.1 falsified by measurement.**
4. **Declared-property resolution replaces identity lookup.** Every site that currently needs to know *which* alpha reads a declared property instead — urgency, style, horizon, archetype, cost characteristic, universe. Adding the 20th alpha then adds a *value*, never a *branch*.
5. **Branch-point count is invariant in N.** This is the mechanical form of alpha-agnosticism and it is falsifiable: measure branch points on the tick path with 1, 2 and 5 alphas loaded; the count must not move. `specified`, and it is the test CORE §C.7 has never had.
6. **Parity baselines are per fixture, not per alpha.** The pinned set is the three CORE §I fixtures — null, shape-adversarial, pathological — plus the optional second live-shaped alpha of a different archetype. **Trade-off:** an individual production alpha's stream is then not pinned by a baseline, and its regression coverage rests on the fixtures plus engine 7's conservation identities. The alternative is worse: a per-alpha baseline makes attaching the 20th alpha an edit to `tests/determinism/parity_manifest.py:133`, which is a core edit by any reading of §G.1.

#### Seven extension points, one contract shape

Alphas are the hardest instance of a general problem, and six others have the same shape: sensors (engine 2), limits (engine 8), monitored assumptions (engine 11), construction policies (engine 6), execution policies (engine 9), backends (engine 10).

**One contract shape — declare → validate → freeze → inject — instantiated per point, not one shared registry object.** A shared runtime registry would be an abstraction with no named problem and would edge toward the 13th engine CORE §A forbids. The reference implementation already exists and works: `src/feelies/sensors/registry.py:193` builds its subscription set from `spec.subscribes_to` rather than from code (`VERIFIED`), and `src/feelies/alpha/discovery.py:28` sorts the platform's only `rglob` with determinism named in its docstring at `:42`. **The named concrete problem is that six of the seven points do not exist**, so every one of them is currently a core edit.

**One call the operator should see, because it changes the shape of engine 4's boundary.** Whether an alpha's body is a manifest expression interpreted by a shared engine, or a code module loaded through an entry point, is not established by Phase 0–2 as carried. **The call: it is an alpha-layer choice that must not be visible outside engines 4 and 5.** The loading mechanism is a Tier-0 protocol with exactly one implementation site; no module under `src/feelies/**` may import a module under `alphas/`, and no module under `alphas/` may be imported outside `alpha/`. Both directions are single-line import contracts. This deliberately avoids mandating a declarative-only rewrite, which would exceed CORE §A's scope.

---

### B.4 — Multiplicity

**An amendment to P3's premise, recorded rather than quietly applied — the same discipline Phase 2 applied to its own sheets.** P3 states that per-strategy positions and net positions are "different objects with different owners." They are different objects; they must not have different owners. `Σ per-strategy = net` is a conservation identity, and an identity with two owners is two production paths for one number — CORE §C.6 and CORE §J's recompute-as-redundancy. CORE §E and engine 7's sheet already fix both to engine 7 with one writer, and `PositionUpdate` is specified to carry both "with the identity between them assertable from the payload alone."

**So "which engine reconciles them" has an answer that is a correction: none, because reconciliation implies two producers.** Engine 7 computes both and asserts the identity. The word *reconcile* belongs to the broker boundary (§F.4) and nowhere else.

What is genuinely asymmetric is verifiability, and that is what decides how a discrepancy surfaces:

| | Consumers | External oracle | Discrepancy surfaces as |
|---|---|---|---|
| **Net position** | Engine 8 (limits, buying power), §F.4 comparison | **Yes** — the broker reports net | `ReconciliationReport` → `DIVERGED` → engine 8 acts, engine 11 alerts |
| **Per-strategy position** | Engine 6 (turnover), engine 8 (budgets), engine 12 (attribution) | **None.** The broker is silent about it | Internal identity break → `INVARIANT_VIOLATION` under §F.5 → **halt** |

The residual is the designed one: the identity is `Σ per-strategy + unattributed = net`. A **non-empty** unattributed bucket is an alert (engine 7 test 3, and its degraded rule books an unknown `strategy_id` to net, holds it unattributed, and alerts). An **unexplained** difference is a halt. **Trade-off, stated plainly:** halting on an internal identity break will stop trading on a bug that may be cosmetic. There is no external authority that could adjudicate per-strategy allocation, so "cosmetic" is not a knowable category here, and CORE §C.5 admits no bounded exception.

#### The four axes

| Axis | Key | Conservation identity, asserted per event | What blocks it today |
|---|---|---|---|
| **Symbol** (N_sym) | `instrument_id` (§F.2), never the ticker | Every event's instrument is in `UniverseSnapshot` or is rejected-and-counted; every member has a health state, `never-seen` if silent | Whether `RegimeState` is per-symbol or market-wide is **unmeasured** (engine 3 assumption) and decides whether engine 3 is O(1) or O(N_sym). U-5: no multi-symbol whole-run baseline exists (Phase 0 D0.8), so the axis the platform exists to serve is pinned only in isolation |
| **Alpha** (N_alpha) | Opaque `strategy_id`. Keying permitted, branching forbidden | `contributors + exclusions = forecasts in scope` at each boundary, every exclusion carrying a reason (engine 6 test 2) | Top-1 discard at `orchestrator.py:1676`; fail-open budgets at `risk_wrapper.py:189`; unpinned registration order |
| **Horizon** (N_hor) | Horizon id + boundary index | Every configured `(symbol, horizon)` boundary yields a snapshot or a gap notification (engine 2) | **The horizon grid is unowned** — four consumers at the same event time with no producer, including engine 6's private `_signal_horizons_sorted` at `src/feelies/composition/synchronizer.py:74`, all anchored on `rth_open_ns` (`src/feelies/core/session_clock.py:47`) whose host tzdata is unpinned (Phase 1 row 13). At N_hor=1 four consumers agreeing is luck that holds; at N_hor=3 it is four independent grids |
| **Strategy** | `strategy_id` | `Σ per-strategy + unattributed = net`, per symbol, at every event | 36 direct calls into the stores from the orchestrator (`self._positions` 23, `self._strategy_positions` 13 — Phase 0 C-6); `PositionUpdate` has no static subscriber in any mode (C-4) |

**Archetype is a sub-axis of alpha and is where E-1 actually bites.** Two alphas of one archetype share a mechanism enumeration, a cost characteristic and a route; two archetypes do not. Route-by-identity is therefore not a stylistic defect — it is the specific mechanism by which the archetype axis cannot be exercised.

**The horizon grid is blocking for its axis, and the decision is the operator's.** Phase 2 recommended engine 2 and recorded it for the operator as an §F-class finding outside §F.1–7 (CORE §A). That recommendation stands, and the cost of leaving it open should be visible: multi-horizon cannot be attempted without it, and the four consumers will each be correct in isolation while disagreeing at the boundary.

**Cost is Phase 4's, not this axis's.** Engine 2 does O(N_sym × N_sensor) per event, engine 4 O(N_alpha × N_hor) per boundary, engine 6 O(N_sym) at boundaries and only at boundaries — which is why engine 6's budget must be a boundary-conditional tail rather than a mean (engine 6 sheet). Handed off, not computed here.

---

### Standing checks for this axis

**Alpha-naming (CORE §I).** Clean. One `alpha_id` literal appears above — `sig_moc_imbalance_v1` at `src/feelies/core/platform_config.py:108` — cited as the measured E-1 defect, not as a design justification. No rule in this axis is stated by naming an alpha, and none would change if the live alpha were removed.

**Overlaps flagged, not split.**

1. **The arm decision is a responsibility this axis creates.** It has multiple consumers and no §E owner. It goes to the cross-cutting kernel on the argument already made twice in Phase 2: it is framework aggregating twelve declarations with no trading-domain content, so the composition root computes it and engine 11 records and emits it. **This is the third instance of one pattern, not a new §F-class finding.**
2. **The wiring manifest overlaps engine 11's observability.** The manifest declares what *should* be wired; engine 11 reports what *is* observed. They must not merge — engine 11 aggregates and never recomputes (engine 11 overlap 3), and a manifest that derived itself from observed traffic would report a typo as a design.
3. **The durable-store mechanism has three Tier-2 clients** (engines 5, 7, 10, plus engine 11's kill switch). Mechanism in Tier 1, policy at each engine — consistent with the ordering key, the barrier and the exception taxonomy. Flagged so Phase 7 sizes it once rather than three times.

**Model finding: none, and the watch-line.** No responsibility in this axis failed to fit an engine, and no engine was found carrying two irreconcilable jobs. **The line to watch:** if the wiring manifest turns out to need knowledge of what an event *means* to a strategy in order to declare an ordinal — rather than declaring the ordinal as an opaque tie-break — the kernel would be acquiring trading-domain content and this becomes a model finding. The one live candidate is `bootstrap.py:355`, and the resolution above (move the requirement onto fill provenance) is what keeps it from firing.

**No new §F-class finding.** The count stays at two, both from Phase 2: the horizon grid and risk-model provenance.

**Assumptions registered.**

- **Whether any dynamic import exists under `src/feelies/`** is not established by Phase 0–2 as carried. It decides whether the import contract is a complete check or a partial one. One `importlib` grep settles it, and it should settle before Phase 6.
- **Whether alpha bodies are manifest expressions or loaded modules.** The call above is deliberately neutral, but the two import contracts it specifies differ in which direction actually fires.
- **Whether `RegimeState` is per-symbol or market-wide** — carried from engine 3's sheet, and blocking for the symbol axis rather than merely open.
- **Whether both the SIGNAL and PORTFOLIO paths can reach order construction on one boundary tick** — engine 6's overlap 2, `INFERRED`. It is a flow question (3.2), and it is also a multiplicity question, because two production paths for one desired portfolio multiply by N_sym.
- **`core/inv12_stress` as the root of cycle 2 is a placement hypothesis, not a finding.** Inferred from the module name; CORE §J's last two anti-patterns cut both ways here.
- **Whether any engine currently holds a mutable handle to another** is unmeasured. The five-edge handle graph is a target; the current graph is 36 direct store calls plus ten private accesses, which is a different shape.

**Carried into 3.2 (Axis C).** The read graph — what an engine may *read*, as distinct from what it may *import* — including the forbidden-reads matrix, is 3.2's and is not attempted here. Also carried: the read-surface design for the four never-subscribed contracts and engine 12's private-attribute observation path; the four-way separation of forecast, decision, action and fact, which the tier rule constrains structurally and does not enforce semantically; and the split of the 24 `OperatingMode` branches into composition-root selection versus in-engine branching (Phase 0 C-8) — the tier rule states that selection belongs to Tier 3 and branching does not belong to Tier 2, which is the criterion 3.2 applies to the 24.

**Carried into 3.3 (Axis D).** The arm decision produces an input to the governance ladder and is not itself a gate record; no `GATE:` records are written here. The cascade-depth bound is specified as a property of the wiring manifest and its *predicate and failure branch* belong to 3.3.

### Verification performed on this section

- No repo access this phase. Every citation above is re-quoted from Phase 0, Phase 1 or Phase 2 at the label that document assigned it; no claim is upgraded, and the two claims that are mine alone (`core/inv12_stress` placement, the current handle-graph shape) are labelled `INFERRED` and `ASSUMED` respectively.
- One correction to P3's own wording is recorded rather than applied, under the amendment discipline Phase 2 used for its own sheets: per-strategy and net positions have one owner, not two.
- No production code changed; no writes outside `docs/architecture/target/out/` and `tools/arch/` are proposed. The one new tool, `tools/arch/importgraph.py`, is `specified` and not run.
- Net complexity for this section: **adds** the wiring manifest (contract definition + conformance test), the import contracts (conformance test), and one dev dependency with its lockfile consequence; **deletes** six ordering comments in `build_platform` and the tacit knowledge they encode, the shutdown checkpoint path over an always-empty store, and — pending the scoped authorization CORE §H requires — `subscribe_all` and its `_global_handlers` loop, which is iterated on every publish over an always-empty list (`src/feelies/bus/event_bus.py:37`, `:55`, `:69`; zero call sites, Phase 0 C-3 / Phase 1 §3).

**Basis.** Unchanged from 3.1: no repo access this phase. Current-state claims are carried from Phase 0 / Phase 1 / Phase 2 at their assigned labels; new material is `specified`. 3.1 is treated as accepted and its two artifacts — the tier rule and the wiring manifest — are inputs here.

---

## 3.2 — Axis C: Information flow

**The result.** The path is not a line. It is a line of eight hot stages, one cold loop that closes through governance, and **one back-edge that lands before the first hop** — the kill-switch read at Phase 0 D0.4 hop 4 (`src/feelies/kernel/orchestrator.py:1561`, returns early, `VERIFIED`). Drawing it as a line is what makes the kill switch look like an afterthought instead of the first gate.

Three things make the flow enforceable rather than described, and only the first is in P3's list:

1. **Every payload declares the age of its *oldest contributing input*, not the time of the event that triggered it.** A derived value stamped with its trigger time reads fresh while resting on a stale feature, and no consumer can fail closed against it.
2. **Two channels, not one.** Every engine emits a domain contract channel and a notification channel. Without that split, "engine 11 observes everything" and "engine 11 reads no engine's payload" are contradictory, and the contradiction is currently resolved by 13 `_emit_*_alert` methods living in the kernel (Phase 0 D0.2, `VERIFIED`).
3. **The enforceable unit is (reader, contract), not (reader, engine).** P3 requires a 12×12 matrix and it is below — but four of its cells are genuinely partial, and a binary engine-pair cell cannot express "engine 8 may read `SessionState` from engine 1 and must never read `NBBOQuote`." The matrix is the readable summary; the register that generates it is the artifact that ships. **This is the third appearance of one lesson** — Phase 1's wall-clock allowlist was file-granular against a call-granular violation, 3.1's import rule must be module-granular against a package-shaped tree, and the read rule must be contract-granular against an engine-shaped model.

---

### C.1 — The canonical path, payloads named at every hop

**Stages 1–8 are the tick-critical path (CORE §D). Stages 9–10 are cold.** The only hot touch of the cold half is the kill-switch read, and it enters at the top.

| # | Stage → producer | Payload | Key fields and units | Timestamp semantics | Provenance | Staleness rule |
|---|---|---|---|---|---|---|
| 1 | **Market Data** (E1) | `NBBOQuote`, `Trade`, `SessionState` | Prices `Decimal`, quote currency; sizes integer shares; phase and per-instrument status from closed enumerations | `exchange_timestamp_ns` = event time; `received_ns` = ingest time **or absent**, never zero | feed id, tape/venue, vendor sequence, `normalizer_version`, `schema_version`, `source_layer` | Per-symbol declared bound; beyond it the health state moves, the quote is not suppressed |
| 2 | **State / Feature** (E2) | `HorizonFeatureSnapshot` | Per-feature value with **declared unit**; `warm`, `stale`, `valid`, `unit`, `feature_versions` — total over `values` | `timestamp_ns` = the **boundary** event time, not the assembly time | `source_sensors`, horizon id, boundary index, `sensor_version` | Per feature, on the payload. A configured sensor that produced nothing is `valid=False`, **never absent** |
| 3a | **Regime** (E3) | `RegimeState`, `RegimeHazardSpike` | Label from a closed versioned enumeration; hazard with declared unit and horizon | Event time of the last contributing estimate | classifier id, parameter set, calibration version | **Change plus declared heartbeat**, so unchanged and not-running are distinguishable from the payload alone |
| 3b | **Alpha** (E4) | `Signal`, `SafetyStateChange`, suppression notification | Direction (closed enum); edge with declared unit; confidence with declared scale; mechanism from a closed versioned enum; half-life with unit | `anchor_timestamp_ns` = the boundary the forecast is anchored to, **distinct from** `timestamp_ns` | `alpha_id`, `alpha_version`, `manifest_hash`, feature and regime versions consumed | Oldest contributing feature's as-of; a `warm=False` input suppresses or reduces confidence by a declared rule |
| 4 | **Portfolio Construction** (E6) | `CrossSectionalContext`, desired portfolio, arbitration record | Target per symbol **as a level**, declared unit; `factor_exposures` with loading-set version; `mechanism_breakdown`; exclusion list with reasons | Boundary event time | contributing forecast ids, completeness measured against the named universe | Oldest contributing forecast; completeness below threshold skips the boundary **and emits** |
| 5 | **Risk & Capital** (E8) | `RiskVerdict`, de-risk requirement, escalation state, budget-state record | Action from closed enum; scale factor in [0,1]; binding constraint named; requirement as "exposure in X to Y by event time T" | Causing event's time | the inputs bound against, **with their as-of times and staleness** | Stale mark ⇒ fail closed; emitted on **every** evaluation including ALLOW |
| 6 | **Execution Decision** (E9) | Executable plan, decline record, plan-to-requirement accounting | Side; quantity in shares; limit price `Decimal`; urgency, style, participation cap, TIF; **expiry in event time** | Causing event's time | originating approval, `strategy_id`, the cost estimate and version it cleared, the gates it passed | Cost estimate stale ⇒ decline new exposure; reductions proceed cost-unpriced-and-marked |
| 7 | **Routing / Fills** (E10) | `OrderAck`, fill, cost estimate, realized-cost report, rejection record | Price and fees `Decimal`; quantity shares; venue; liquidity flag | **Exchange execution time and receipt time distinguished and both carried** | parent `order_id`, broker identifiers, cost-model version and declared assumptions | An order past its declared expiry is rejected, never worked |
| 8 | **Portfolio Accounting** (E7) | `PositionUpdate`, mark record, attribution record, `ReconciliationReport` | Signed quantity integer shares; cost and marks `Decimal`; realized/unrealized P&L `Decimal`; per-strategy **and** net with the identity assertable from the payload | Event time of the causing event | causing fill or quote, **mark rule, mark side, mark staleness** | A retained mark is flagged; a consumer distinguishes fresh from retained without reading E7 state |
| 9 | **Observability / Forensics** (E11, E12) | `Alert`, `MetricEvent`, health, `KillSwitchActivation`, `LatencyBudgetState`; evidence, recommendation, attribution, parity report, forensic trace | `alert_name`/`severity` from a closed versioned enum; metrics with declared units; health in the four-way enumeration | E11 is the **one** engine whose emissions legitimately carry wall time — and must say so | E12 outputs carry **both fingerprints**: the run's and the oracle's | Health carries last-observation time **and the bound that would make it stale** |
| 10 | **Alpha Governance** (E5) | Resolved registry, `UniverseSnapshot`, `IdentityMap`, lifecycle transition, load-gate outcome | Members as an **ordered tuple**, sorted by symbol; adjustment factors `Decimal` | Composition-time; effective times in event time | `universe_hash`, `identity_hash`, `manifest_hash`, actor, evidence reference | Frozen for the session. Evidence older than a declared bound cannot justify promotion **or** continued LIVE |

#### The envelope every emission carries

`specified`. Beyond §F.7's `schema_version`, three fields the base envelope does not have today:

- **`as_of_ns` per input class** — the event time of the oldest input the value depends on. Distinct from `timestamp_ns`.
- **`validity_ns`** — the declared bound beyond which the value is stale, on the payload rather than in a consumer's constant.
- **`producer`** — engine id plus module version. Today one field gestures at this, `source_layer`, and engine 1's sheet has to specify it as "non-null", which implies it is nullable now. `INFERRED`.

The measured baseline this fixes: `Event.timestamp_ns` (`src/feelies/core/events.py:49`) has no declared semantics anywhere, and **1 of 21 event classes documents it** — `HorizonTick` at `:584` (Phase 1 §1, `VERIFIED`). The concrete instrument types do carry named bases; the field every engine actually reads is the undeclared one.

#### The two channels

| | Domain channel | Notification channel |
|---|---|---|
| Carries | The engine's contract payloads | Health transition, gap, rejection, decline, degrade, fault record, drop count |
| Governed by | The forbidden-reads matrix (C.6) | Addressed to engines 11 and 12 by construction; readable by no one else |
| Enforcement | Wiring manifest + injection | Wiring manifest; a notification with no recipient is a manifest error |

The named concrete problem this removes: engine 11 must hold four-way health for every stream, including `never-seen`, while being forbidden from reading domain payloads. Without a declared notification channel those two requirements contradict, and the contradiction currently resolves as 13 `_emit_*_alert` / `_publish_alert` methods in the kernel with `Alert` and `MetricEvent` holding exactly one static subscriber each, both the orchestrator (`:559`, `:563`), and `KillSwitchActivation` holding none (Phase 0 D0.2, D0.3, C-4, `VERIFIED`). The channel deletes those 13 methods; it does not add a mechanism.

#### Three flow calls made here, as Phase 2 deferred them

**1. `SensorReading` leaves the domain channel.** Engine 2's overlap 2 recorded that `SensorReading` is subscribed by `src/feelies/signals/horizon_engine.py:197` *alongside* `HorizonFeatureSnapshot` at `:198`, making it a metadata-thinner route into the decision layer, and left the resolution to Phase 3. **The call: `SensorReading` moves to the notification/observation channel — visible to engines 11 and 12, consumable by no decision path.** Engine 4's subscription at `:197` is removed. Consequence worth stating because it looks like a parity risk and is not: engine 2's three sensor-reading baselines (`level1_sensor_reading`, `level1_v03_sensor_reading`, `multi_symbol_sensor_reading`) are hashes over an emitted stream from a fixture, not over a bus subscription, so they survive unchanged.

**2. `SymbolHalted` is subsumed into `SessionState`, not retained as a derived notification.** §F.3 stated the choice was Phase 3's. Three reasons: it has no subscriber in any mode and its docstring at `src/feelies/core/events.py:123` describes a forensics consumer that was never built (Phase 0 C-4, `VERIFIED`); two types for one fact reintroduces the split F.3 exists to close; and `_TYPE_RANK` (`src/feelies/storage/event_resequence.py:30`) grows from two entries to three for `SessionState`, so a fourth type carrying the same fact would need its own rank and a tie-break against `SessionState` at an identical nanosecond — a tie nobody should have to adjudicate. **Trade-off and blast radius, declared:** `symbol_halted` and `halt_order` are two of the 26 parity baselines (Phase 1 §6), and both re-pin.

**3. There is one production path to a desired portfolio, and it is the PORTFOLIO path.** Engine 6's overlap 2 recorded two routes on the same boundary tick — SIGNAL at hops 26 → 28 → 29 → 30 and PORTFOLIO at hops 24 → 25 → 27 — with hop 32's admission gate "shared with the PORTFOLIO path", so two paths are `VERIFIED` and both reaching order construction is `INFERRED`. **The call: the SIGNAL path is the same job performed in Tier 1 and is deleted.** `_select_bus_signal` at `src/feelies/kernel/orchestrator.py:1676` is arbitration, which engine 6's sheet already resolved to a declared construction policy; `_compute_target_quantity` at hop 29 is engine 8 sizing, which under the target operates on engine 6's target rather than on a `Signal`. **Trade-off:** this is the largest single flow change in the review, and it re-pins engine 6's four baselines and engine 8's three. **The discriminator that must be read before the migration is sized** is the unit of `target_positions` — weights, notional, or shares — which decides whether engine 6 has already crossed into engine 8's job on the surviving path. One field read (engine 6 assumption, still open).

**One shape observation that belongs to this axis and is not a call.** The path is not the same shape in every mode: hop 14, the backtest router evaluating resting orders on every quote, is BACKTEST-only (`src/feelies/bootstrap.py:353`, Phase 0 D0.4, `VERIFIED`), so in that mode execution state advances against a quote *before* engine 2 sees it at hop 13. That is one of the 24 `OperatingMode` branches outside the seam (Phase 0 C-8) and it is the one that changes hop order rather than a parameter, which makes it the most consequential of the 24 to classify. Classification of all 24 into composition-root selection versus in-engine branching is 3.3's, under the criterion 3.1 fixed: selection belongs to Tier 3, branching does not belong to Tier 2.

---

### C.2 — Four-way separation, enforced by type

**Definitions, and the test that makes them operational.**

| | Meaning | Owner | Revisable? |
|---|---|---|---|
| **Forecast** | What an alpha believes will happen | 4 | Yes — it is an opinion |
| **Decision** | What the platform intends: size, price, urgency, permission | 6, 8, 9 | Yes — until acted on |
| **Action** | An instruction leaving the platform | 9 → 10 | **No** — it is emitted |
| **Fact** | What happened: fill, ack, position, mark, P&L | 10, 7 | **No** — it is recorded |

**The test:** can two consumers read one instance of the type and one treat it as an instruction while the other treats it as a record? If yes, the type carries two. Provenance attached to a payload is not a second payload — `mechanism_breakdown` on a desired portfolio is provenance for a decision, not a forecast riding along.

**Every place the current system carries two:**

| # | Type / site | Carries | Evidence | Resolution and its cost |
|---|---|---|---|---|
| 1 | **`OrderRequest`** | **Action + decision-command** | Carries the outbound record of hop 33 **and** the inbound command from engine 8's four exit authors, "disambiguated only by the free-text `reason` field" (`src/feelies/core/events.py:290`, Phase 0 D0.4, `VERIFIED`). Publishers: `risk/stop_exit.py:297`, `risk/hazard_exit.py:253`, `risk/deferral_cap.py:378`, `risk/exit_composer.py:486`; re-entry at `orchestrator.py:585` → `_on_bus_hazard_order:4919` | Engine 8 emits requirements; engine 9 emits orders. **Removes a use, adds no type.** Four baselines re-pin (engine 9 test 8) |
| 2 | **`Signal`, re-published on the same tick** | **Forecast + selection decision** | The arbitration-selected `Signal` is deliberately re-published, and `src/feelies/harness/backtest_report.py:74-83` documents the report having to dedupe the resulting double-record (Phase 1 §4, `VERIFIED`). The second publication *means* "this one won" and is distinguishable from the first only by being second | The winner is named in the **arbitration record**, which engine 6's sheet already requires and which today only traces losers (`_trace_buffered_signals_arbitration:638`). `Signal` is published once |
| 3 | **`OrderRequest.is_moc`** | **Action + governance** | Set from membership in `moc_strategy_ids` at `src/feelies/core/platform_config.py:108`, reaching `_moc_strategy_ids` at `orchestrator.py:876`, tested at `:3386`, diverting the order to the closing auction (`events.py:288`, Phase 0 E-1, `VERIFIED`) | Route follows a **declared property** — urgency, style, session — never an identity. This is E-1's target state, and it is a flow defect as much as an agnosticism one |
| 4 | **Desired portfolio (`SizedPositionIntent`)** | **Decision + a cost number of undetermined provenance** | Carries `disclosed_cost_total_bps_by_symbol` (Phase 0 C-7). If that is a manifest declaration it is provenance; if computed from live spreads it is engine 9/10 arithmetic on engine 6's type. Undetermined across engines 4, 6 and 9's sheets | Declare producer and unit on the field, or remove it. **The type's name is itself the discriminator** for the level-versus-shares question — a contract asserting it is "Sized" while engine 8 owns sizing is either a wrong name or a wrong owner |
| 5 | **The failure channel** | **Every class at once** | The tick-wide `try/except Exception` at `orchestrator.py:1466` → `_handle_tick_failure:1474` receives an engine-2 sensor fault, an engine-8 veto fault and an engine-10 submission fault identically (Phase 0 F.5, `VERIFIED`) | §F.5's taxonomy classifies at the raising engine's boundary; only unclassified escapes reach the tick-wide handler, where they are `INVARIANT_VIOLATION` rather than the normal case |

**Two boundary cases, recorded so they are not mistaken for defects.** `SafetyStateChange` is a *fact about a forecast* — engine 4 asserting its own forecast has become unsound — and stays clean provided `risk/exit_composer.py:289` and `risk/deferral_cap.py:237` treat it as a fact and decide separately, which their sheets already require. `RegimeHazardSpike` is a fact; the defect at `risk/hazard_exit.py:141` → `OrderRequest` at `:253` is not the type carrying two, it is a **fact becoming an action with no decision stage**, and it belongs in C.3.

---

### C.3 — Feedback edges

**Legal, with the mechanism that makes each legal.**

| Edge | Form | Mechanism |
|---|---|---|
| Fills → accounting → risk | Contract, then read-only handle | E10 publishes fills with economics; E7 books; E8 reads E7 through a read-only view. **The `getattr(..., "refresh_high_water_mark", None)` poke at `orchestrator.py:1616` is this edge implemented as a non-contract** — absent attribute means drawdown escalates against a mark that never moves, with no error (Phase 0, `VERIFIED`) |
| Forensics → governance | **Evidence + recommendation, on a declared cadence** | See the refinement below |
| Regime → everyone | Change-plus-heartbeat contract, single read path (`src/feelies/bootstrap.py:289`) | The consumer owns the predicate; engine 3 owns only the label. 56 `regime_gate` sites make the predicate side 3.3's work |
| Reconciliation divergence → safety | `ReconciliationReport` emitted on **every** check, not only on breach | Absence of a report must not read as agreement |

**Two of P3's legal edges are legal only in a form the platform does not currently use.**

- **Forensics → governance is legal as a recommendation and illegal as a write.** `src/feelies/forensics/cost_circuit_breaker.py:159` performs the `LIVE → QUARANTINED` transition from engine-12 code (Phase 0 D0.2, `VERIFIED`). The behaviour is correct and the mechanism is wrong: two forensic writers racing on one lifecycle state have no arbitration. Engine 12 emits evidence plus a recommendation; engine 5 performs the transition. **The migration step is a re-routing, not a fix to a broken circuit breaker.**
- **Fills → risk is legal through accounting and illegal directly.** The poke above is the instance.

**Illegal, with site and enforcement.**

| Edge | Current state | Enforcement in target |
|---|---|---|
| P&L → alpha | **Absent** — engine 4's subscription set is `RegimeState`, `SensorReading`, `HorizonFeatureSnapshot` and nothing else (`src/feelies/signals/horizon_engine.py:196-198`, `VERIFIED`). Enforced by what it is handed, and by nothing else | M1 injection + M2 import contract + the purity test (engine 4 test 1: one feature/regime prefix against two materially different books ⇒ **byte-identical** forecast stream) |
| Realized outcome → feature computation | Absent. Same enforcement gap | M1 + M2 + engine 2's prefix-purity test |
| Execution state → alpha | Absent — but adjacent: hop 3's horizon-age test on the signal buffer at `orchestrator.py:1530` applies an expiry decision to a forecast from Tier 1, and any constant in that path not read from the forecast is an alpha-shape leak (engine 4 test 6) | M1 + M2; expiry computed from the forecast's own anchor and half-life |
| Governance evaluation → tick path | Evaluation is off-path (Phase 0: the promotion ledger is "never read on the tick path"), **but the import edge exists** — `core.inv12_stress` → `core.platform_config` → `promotion.evidence` (Phase 0 D0.1 cycle 2), and no test asserts the zero-read property | M2 tier rule (Tier 0 → Tier 2 is illegal regardless of the cycle) + engine 5 test 1's dynamic zero-read assertion |
| **Risk → action** *(not in P3's list; required by the evidence)* | Four exit authors publish `OrderRequest` directly | M3 wiring manifest: engine 8 has no publish entry for the order contract |
| **Fact → action, skipping decision** *(not in P3's list)* | `risk/hazard_exit.py:141` turns `RegimeHazardSpike` into an `OrderRequest` at `:253` | Same. A hazard produces a requirement at most |

---

### C.4 — Staleness and provenance on every emission

**The rule that does the work: the staleness of a derived value is the age of its oldest contributing input, not the time of the event that triggered its computation.** Engine 2 can already satisfy this — it carries `warm` and `stale` per feature. Engines 6, 8 and 9 fan in from several sources and cannot, because nothing on their payloads records which input was oldest. A desired portfolio stamped with the boundary time, built from a forecast anchored three boundaries earlier, is indistinguishable from a fresh one.

**Absence is typed.** Engine 2's rule — a configured sensor that produced nothing yields `valid=False`, **never a missing key** — generalizes to every contract: the field set is closed and declared, and a missing value is `absent` with a reason. Absence otherwise reads as "not configured" to every consumer, which is how a silently-thin payload degrades a barrier instead of failing it (Phase 0 D0.7 F.1).

**The four undressed scalars.** P3's clause — scalar emissions without staleness metadata make fail-safe consumers unimplementable — has four measured instances, and each produces a specific unimplementable consumer:

| Scalar | Site | What cannot be written |
|---|---|---|
| High-water mark, poked | `getattr(..., "refresh_high_water_mark", None)`, `orchestrator.py:1616` | A drawdown consumer that can tell "mark refreshed" from "attribute absent" |
| Position substituted on failure | `except Exception: current_positions[s] = 0.0`, `src/feelies/composition/engine.py:388`, marked `# pragma: no cover` | A turnover calculation that can tell a real flat position from a failed read |
| `update_mark(mid, bid, ask)` | Hop 9, with the validity guard `if mid > 0` living **outside** engine 7 at `orchestrator.py:1607` | A consumer that can tell a fresh mark from a retained one, or see that a crossed quote was excluded |
| `disclosed_cost_total_bps_by_symbol` | On engine 6's event, producer undetermined | A cost gate that can audit which model version it cleared |

All four `VERIFIED` (Phase 0 D0.4, E-2, C-7). Each resolves the same way: the scalar becomes a payload with an as-of time, a validity flag and a producer.

---

### C.5 — Recompute policy

**Three categories, not two.**

1. **Owned numbers — never recomputed downstream.** Edge (4), regime label (3), desired level (6), permitted quantity and scale factor (8), cost estimate and realized cost and fill economics (10), mark, position, lot, realized and unrealized P&L (7), universe and identity (5). Independent recomputation is permitted **only** as category 2.
2. **Declared conservation audits — recomputed by declaration, level-based, compared and alerted.** Never a second production path (CORE §C.6).
3. **Monitoring statistics — engine 11 only.** A drift statistic over received values is not a recomputation of anyone's owned number, and engine 11 must be able to compute one or CORE §E's mandate to monitor latency drift, fill-rate drift and contract-rejection rate is unimplementable. **The bound that keeps this honest: a monitoring statistic feeds the kill switch and nothing else.** It never re-enters sizing, pricing, routing or a forecast.

**Level-based, not shape-based, stated with the reason.** A shape test compares series up to an affine or sign transform, so a sign-symmetric error survives it: two equal and opposite mis-signed legs, or a mark taken on the wrong side symmetrically across longs and shorts, preserve shape exactly and move level. The canonical instance is already specified — engine 7's null-alpha reference requires position, realized P&L and unrealized P&L to be **identically zero at every event**, not approximately zero at the end of the run, because "approximately zero at the end" is precisely what a pair of cancelling errors produces.

**The declared audit set:**

| Audit | Identity | Owner |
|---|---|---|
| Ingress conservation | `frames_in = emitted + rejected + dropped + deduped`, and `|notifications| = |non-emitted|` | 1 |
| Metadata totality | Every feature in `values` has `warm`, `stale`, `valid`, `unit`, `feature_versions` | 2 |
| Construction accounting | `contributors + exclusions = forecasts in scope at the boundary` | 6 |
| Book conservation | `Σ per-strategy + unattributed = net`; `Δposition = Σ signed fill quantity`; `Σ lots = position`; `ΔP&L = Σ fill cash flows + Σ(Δmark × position held)` — **at every event** | 7 |
| Decline totality | `intents in = orders out + declines out`, each decline naming its gate | 9 |
| Discharge identity | Every de-risk requirement is discharged by named orders, outstanding, or emitted as dropped — no fourth outcome | 9 |
| Attribution reconciliation | `Σ attributed P&L = engine 7 realized P&L`, exactly, in `Decimal` | 12 |

**The seven current duplicate-path candidates, all of which this policy either forbids or converts into a declared audit:**

| # | Candidate | Status |
|---|---|---|
| 1 | Two production paths to a desired portfolio (SIGNAL vs PORTFOLIO) | **Resolved in C.1** — one path |
| 2 | Attribution: `_record_fill_attribution:4057` vs `src/feelies/alpha/fill_attribution.py` | Unmeasured. If two, engine 12 reconciles against a number computed twice |
| 3 | Intent construction: planner vs `_intent_translator` fallback at `orchestrator.py:1740` | Unmeasured (engine 9 overlap 3) |
| 4 | Regime read: the declared single path (`bootstrap.py:289`) vs `_regime_label_for:4556` | Unmeasured whether it delegates or recomputes (engine 3 overlap 2) |
| 5 | Cost: engine 9's `_round_trip_cost_bps:2266` vs engine 10's model | Unmeasured which reads what |
| 6 | Mark validity: `if mid > 0` at `:1607`, outside engine 7 | `VERIFIED`. The rule moves into engine 7 and becomes emitting, covering crossed and locked, which `mid > 0` does not |
| 7 | Health: engine 1's `DataHealth`, the kernel's `_data_health_blocks_trading:5263`, engine 11's platform view | `VERIFIED`. Engine 11 **aggregates and never recomputes**; the kernel's evaluation is a gate and belongs to 3.3 |

Five of seven are unmeasured, and each is one read away from settling. That is the shape of this axis's evidence debt.

---

### C.6 — Required artifact: the forbidden-reads matrix

**Closure rule.** The matrix is closed: **a read not explicitly permitted is forbidden.** An open matrix cannot be enforced, because a new subscription is then permitted by default and the artifact records only what someone remembered to prohibit.

**Cell meaning.** May engine R consume any contract or handle produced by engine C. Symbols: `B` bus contract · `R` injected read-only view · `C` composition-time frozen artifact · `N` notification channel only · `—` forbidden · `·` self.

| Reader ↓ / Producer → | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **1** Market Data | · | — | — | — | C | — | — | — | — | — | — | — |
| **2** State / Feature | B | · | — | — | C | — | — | — | — | — | — | — |
| **3** Regime | B\* | B | · | — | C‡ | — | — | — | — | — | — | — |
| **4** Alpha | — | B | B | · | C | — | — | — | — | — | — | — |
| **5** Governance | — | — | — | — | · | — | — | — | — | — | — | B |
| **6** Portfolio Constr. | — | — | — | B | C | · | R | — | — | — | — | C† |
| **7** Accounting | B | — | — | — | C | — | · | — | — | B | — | — |
| **8** Risk & Capital | B\* | — | B | — | C | B | R | · | — | — | R | — |
| **9** Execution Decision | B\* | — | — | — | — | — | R | B | · | B | — | — |
| **10** Exec Sim / Routing | B | — | — | — | — | — | — | — | B | · | — | — |
| **11** Observability | N | N | N | N | N | N | N | B+N | N | N | · | N |
| **12** Research / Forensics | B | B | B | B | B | B | R | B | B | B | B | · |

\* `SessionState` only — **never `NBBOQuote` or `Trade`**. This is the seed row "risk reads marks and positions, never raw quotes", and it is the cell a binary engine-pair matrix cannot express.
† Risk-model outputs — factor loadings and sector map. **Pending the §F-class risk-model-provenance decision** raised on engine 6's sheet; today the source is `storage/reference/`, which Phase 0 D0.2 lists as consumed by engines 6, 7, 10 and `bootstrap`, owned by none.
‡ Conditional on whether `RegimeState` is per-symbol or market-wide — unmeasured (engine 3 assumption), and it decides whether engine 3 needs the universe at all.

**Counts.** 132 off-diagonal cells. **51 permitted, 81 forbidden.** Of the 51, engine 11's notification row accounts for 11 and engine 12's read-only row for 11, leaving **29 domain-channel edges among engines 1–10**. Engine 11 has exactly one domain-channel read — `RiskVerdict` from engine 8 — and it exists because the rejection rate is not derivable from the notification channel: an ALLOW is not a notification, and a veto record that only exists on denial cannot prove monotonicity.

**The five non-negotiable seed rows, checked against the grid:**

| Seed row | Cells | Holds |
|---|---|---|
| Alpha reads no position, P&L, fill or execution state | 4→7, 4→8, 4→9, 4→10 | All `—` |
| Features read nothing downstream of themselves | Row 2 | Only 1 and 5. **2→3 is forbidden specifically** to keep estimate → classify acyclic |
| Risk reads marks and positions, never raw quotes | 8→7 `R`, 8→1 `B*` | Holds, via the contract-level qualifier |
| Routing reads a plan, never an edge | 10→9 `B`, 10→4 `—` | Holds |
| Governance read on the tick path only as an immutable composition snapshot | Column 5 from hot engines | All `C`, never `B` |

**One amendment recorded, not quietly applied.** Engine 8's sheet lists as forbidden "`Signal` content beyond the fields it sizes on (4)", which permits a narrow direct read. The grid above sets **8→4 to forbidden outright**: everything engine 8 needs from the forecast arrives through engine 6's target, which carries `mechanism_breakdown` as provenance. This tightening follows from C.1's one-path resolution and should be applied to engine 8's sheet when the phase output is assembled. Until the two-path question is migrated, the narrow read is the current state, not the target.

**Enforcement mechanisms, and their honest ranking.**

| | Mechanism | Fails when | Survives an edit by someone who does not know the rule? |
|---|---|---|---|
| **M1** | Constructor injection — the engine is not handed the object | Composition | **Yes** |
| **M4** | Type — read-only views that cannot mutate and cannot fail into a value | Compile / call site | **Yes** |
| **M2** | Import contract (Tier-2 independence, from 3.1) | Build | No — but loudly |
| **M3** | Wiring manifest — the subscription does not exist and cannot be added silently | Build | No — but loudly |
| **M6** | AST checks — alpha literals, private access, forbidden symbols | Build | No — but loudly |
| **M5** | Runtime boundary rejection with provenance (CORE §G.3) | Runtime | No — and late |

**Only M1 and M4 survive ignorance**, which is why the sheets keep converging on injection and read-only views rather than on tests. The measured contrast: the single-source-of-truth invariant is currently upheld through **36 direct method calls from the orchestrator into two stores** (`self._positions` 23, `self._strategy_positions` 13), whose enforcement point is "type annotations plus `mypy --strict`, not a runtime check" (Phase 0 C-6, `VERIFIED`) — the weakest row in the table applied to the platform's strongest invariant.

**The largest violation of this matrix has no row in it.** A Tier-1 module performs Tier-2 reads on behalf of nine engines: regime classification in five kernel methods, three accounting methods, sizing and escalation and emergency flatten, nine engine-9 methods, six engine-10 transitions, thirteen engine-11 emit methods (Phase 0 D0.2, `VERIFIED` across the twelve GAP lines). There is no cell for "the kernel read engine 7 on engine 8's behalf", and there should not be — **the matrix is unenforceable until 3.1's tier rule holds**, which is why the two artifacts ship together or neither does.

---

### Standing checks for this axis

**Alpha-naming (CORE §I).** Clean. `moc_strategy_ids` appears as the E-1 site; no rule above is stated by naming an alpha.

**Overlaps flagged, not split.**

1. **The notification channel overlaps engine 12's observation interface.** Engine 12's overlap 4 asked for a declared observation interface rather than the private reach-through at `src/feelies/harness/backtest_runner.py:246`, and noted the same interface serves engine 11's unwired consumers, "so it should be designed once in Phase 3 rather than twice." **It is the notification channel plus engine 12's read-only row.** One design, two consumers, as that sheet asked.
2. **The staleness envelope overlaps §F.7's schema change.** Adding `as_of_ns`, `validity_ns` and `producer` to the base envelope touches all 21 types and rides F.7's mechanism — the field addition is silent, and bringing the fields into the hashed set is a coordinated re-pin. **Two steps, two blast radii**, exactly as F.2's `instrument_id` change.
3. **The two-channel split overlaps 3.3's gate emission requirement.** Every gate rejection must emit; the notification channel is where it emits *to*. The gate records themselves are 3.3's and none is written here.

**Model finding: none.** No flow responsibility failed to fit an engine, and the two new mechanisms — the notification channel and the staleness envelope — are contract machinery with no trading-domain content, which is the kernel's remit by §E's own text and the same argument that placed F.5 and F.7. **The watch-line:** if the notification channel turns out to need a payload's trading meaning to route it, the kernel acquires trading-domain content and this becomes a model finding.

**No new §F-class finding.** The count stays at two — the horizon grid and risk-model provenance — and the second now has a matrix cell waiting on it (6→12, marked †).

**Assumptions registered.**

- **Whether `source_layer` is nullable today.** `INFERRED` from engine 1's sheet requiring it non-null. It decides whether provenance is a new field or an unenforced one.
- **Five of the seven recompute candidates are unmeasured** (attribution paths, planner vs translator, `_regime_label_for`, the cost gate's input, and whether the four exit authors read engine 7 independently). Each is one read; together they decide how much of C.5 is a wiring task and how much is a build.
- **The unit of `target_positions`** — carried, and now blocking the migration shape for C.1's one-path call rather than only the engine 6/8 boundary.
- **Whether `RegimeState` is per-symbol or market-wide** — carried from 3.1; it decides cell 3→5.
- **Whether engine 10's queue-position model is documented anywhere.** Engine 10's sheet registers it; it matters here because the cost estimate's "declared assumptions" field is unimplementable against an undocumented model, and engine 9's gate is then unauditable by construction.

**Carried into 3.3 (Axis D).** The 56-site `regime_gate` family and the 52-site load-gate ladder; the classification of the 24 `OperatingMode` branches under 3.1's selection-versus-branching criterion, with hop 14 as the sharpest case because it reorders the path rather than parameterising it; `_data_health_blocks_trading:5263` as a gate over engine 1's output; the cascade-depth predicate and its failure branch; and the emission obligation for every rejection, whose destination this section defines and whose record 3.3 specifies.

### Verification performed on this section

- No repo access. Every citation is re-quoted from Phase 0, Phase 1 or Phase 2 at its assigned label; nothing upgraded. The one claim that is mine alone — `source_layer` nullability — is labelled `INFERRED`.
- Three deferrals that Phase 2 explicitly assigned to Phase 3's flow work are resolved rather than re-deferred: `SensorReading`'s dual path, `SymbolHalted`'s disposition, and the two production paths to a desired portfolio. One amendment to engine 8's sheet is recorded, not applied.
- Net complexity for this section: **adds** three envelope fields (contract definitions, admissible under §G.10) and the notification-channel declaration; **deletes** engine 4's `SensorReading` subscription, the `SymbolHalted` type, the inbound `OrderRequest` direction and its `_on_bus_hazard_order` entry, the kernel's SIGNAL path including `_select_bus_signal`, and the 13 `_emit_*_alert` methods in the kernel. Every addition is a declaration; every deletion is a code path.
- No production code changed; nothing proposed outside `docs/architecture/target/out/` and `tools/arch/`.

**Basis.** Unchanged: no repo access this phase. Current-state claims are carried from Phase 0 / Phase 1 / Phase 2 at their assigned labels; new material is `specified`. 3.1 and 3.2 are treated as accepted and their artifacts — the tier rule, the wiring manifest, the notification channel, the forbidden-reads matrix — are inputs here.

---

## 3.3 — Axis D: Gating

**The result.** The platform enumerates **16 gates**, all of them in the ladder that never touches the tick path, and the enumeration has a hole. `alpha_load_gate` runs G1…G17 with **G13 absent from the registry** (Phase 0 G-1, `VERIFIED`), concentrated 52-of-52 in `alpha/` (Phase 0 D0.5). The runtime ladder — the ordered checks a decision passes from raw event to submitted order — **is not an object at all.** It exists as control flow in one 4 778-sloc module, as a hop sequence in a Phase 0 trace, and as prose in `docs/`. That is precisely P3's failure condition: three descriptions and a fourth form in code are four claims, not a specification.

Target state is **53 declared gates** — 19 governance, 34 runtime spine — plus three per-boundary families whose instance count is *generated* from the wiring manifest rather than hand-counted. All 53 live in one registry, as data, from which ordinals, docs and test bindings are generated.

Two calls do most of the work in this section, and neither is in P3's list:

- **The G-numbering is not wrong because 13 is missing. It is wrong because ordinals were used as identity.** Under a scheme where a gate *is* its position, deleting a gate leaves a hole and reordering renames gates. P3's own record template already separates `GATE: [stable ID]` from `POSITION: [ordinal]`; adopting it dissolves the hole rather than documenting it.
- **Short-circuit evaluation is permitted for the decision and forbidden for the record.** When gate *k* fires, gates *k+1…n* must be recorded `NOT_EVALUATED`, never `PASS`. This is the whole content of P3's warning that simultaneous-breach ambiguity biases results optimistically in exactly the scenarios that matter: the bias is not that the wrong gate fired, it is that every gate downstream of it reads as having passed a stress case it never saw.

---

### D.1 — The two ladders, separated mechanically

| | Governance ladder | Runtime ladder |
|---|---|---|
| Decides | What is **eligible** to run | What happens **now** |
| Clock | Once, at composition | Per event |
| Latency class | `cold`, with **no exception** | `hot`, except where a leg is declared cold |
| Inputs | Manifests, evidence, config, reference data | Contracts on the bus, and frozen composition artifacts |
| `ON FAIL` vocabulary | `refuse` · `quarantine` · `halt-boot` | `reject` · `degrade` · `halt` |
| Output into the other | The **resolved registry**, frozen, consumed once | Nothing |

**The separation is checkable from the registry alone, which is the point.** Three one-line queries:

1. Zero entries with `LADDER=governance` **and** `LATENCY CLASS=hot`.
2. `quarantine` appears only under governance; `reject` only under runtime. A hot gate whose `ON FAIL` is `quarantine` is a defect by construction — it is an eligibility decision being taken per event, which is CORE §C.10 violated in the one costume that looks reasonable.
3. No runtime gate names an engine-5 *mutable* surface in `INPUTS`. Governance may appear on the tick path only as an immutable snapshot resolved at composition (3.2's matrix, column 5, all `C`).

**Where the conflation is measured today.** `enforce_layer_gates=False` is a governance switch whose reachability outside declared research configs is **unresolved** — Phase 0 registered it as U-6 and engine 5's sheet requires it closed before Phase 6. A governance ladder that can be switched off by configuration in production is not a cold ladder; it is a runtime-varying eligibility rule with no per-event record. **U-6 is now blocking for this axis**, not merely open: the registry cannot declare `DISABLEABLE` honestly until one grep over `configs/` settles it.

---

### D.2 — The gate record, and why 53 of them are not written out below

The record is P3's, with five fields added that the four "Plus" requirements make necessary:

```
GATE:             [stable string ID — never an ordinal]
LADDER:           [governance | runtime]
OWNER ENGINE:     [1-12, exactly one]
LATENCY CLASS:    [hot | cold]
LEG:              [E | Q | B | D | P | S | F]          ← new
POSITION:         [(leg, stage, rank) → dense ordinal, GENERATED]
FAMILY:           [none | per-receiving-boundary]       ← new
INPUTS:           [named contracts, with staleness tolerance]
PREDICATE:        [exact pass condition]
ON FAIL:          [reject | degrade | quarantine | halt]
ON UNKNOWN:       [the exposure-reducing branch]
ON EXCEPTION:     [F.5 class]
EXPOSURE EFFECT:  [<= ungated]
MONOTONE:         [yes | declared-exception(reason)]    ← new
REDUCTION-BLOCKING: [never | declared(reason)]          ← new
DISABLEABLE:      [no | research-only]                  ← new
EMISSION:         [verdict, reason, input as-of times — always]
TESTED BY:        [test ID; must resolve or the registry fails]
```

**Writing all 53 out in prose would violate the single-source rule this same section imposes.** The registry is the source; expansion is generated. What this document specifies is the schema, the complete enumeration in compact form, the generation rule, and full expansion **only for the gates where a design call is being made rather than a fact recorded** — seven of them, in D.5.

**`OWNER ENGINE: exactly one` and the kernel.** Three gates are contract-boundary checks that CORE §E places with the cross-cutting kernel, which is not an engine 1–12. Rather than extend P3's template, they are declared as **families instantiated at each receiving boundary, owned by the receiving engine** — the kernel owns the mechanism, the engine owns the contract it accepts. That is the same mechanism/policy split already used four times: the ordering key protocol (engine 1's sheet), the barrier (engine 6's), the exception taxonomy (§F.5), and schema versioning (§F.7). The registry itself is the fifth instance.

---

### D.3 — Governance ladder — 19 gates

Position is row order. `cold` throughout, with no exception.

| ID | Owner | Predicate, in brief | On fail | On unknown | Tested by |
|---|---|---|---|---|---|
| **Stage A — platform preconditions** |||||
| `GOV.CONFIG_RESOLVE` | 5 | Config parses; fingerprint computable | halt-boot | halt-boot | `E5.6` |
| `GOV.SCHEMA_SUPPORT` | 5† | Declared-support set present; replayed log's version ∈ set | halt-boot, **naming both versions** | halt-boot | `F7.2` |
| `GOV.IDENTITY_RESOLVE` | 5 | `IdentityMap` resolved; `identity_hash` computed; as-of declared | refuse | refuse | `F2.*` |
| `GOV.UNIVERSE_RESOLVE` | 5 | `UniverseSnapshot` ordered; `universe_hash` matches fingerprint | refuse to compose | refuse | `F1.*` |
| **Stage B — per-alpha admission** (the only stage implemented today) |||||
| `GOV.MANIFEST_PARSE` | 5 | Schema-valid against `alphas/SCHEMA.md` | refuse | refuse | `E5.4` |
| `GOV.MANIFEST_HASH` | 5 | Content hash computable | refuse | refuse | `E4.3` |
| `GOV.LAYER_VALIDATE` | 5 | Layer checks pass | refuse | refuse | `E5.3` |
| `GOV.DEPENDENCY_RESOLVE` | 5 | Dependency graph acyclic and resolvable | refuse | refuse | `E5.3` |
| `GOV.UNIVERSE_DISCLOSURE` | 5 | Declared universe ⊆ platform universe | **refuse the load**, naming symbols and alphas | refuse | `D.5` below |
| `GOV.CONTRACT_SHAPE` | 5 | Declared emission shape conforms: direction enum, edge unit, half-life unit, anchor | refuse | refuse | `E4.5` |
| `GOV.EVIDENCE_FRESHNESS` | 5 | Evidence within declared bound | no promotion; **toward quarantine, not LIVE by inertia** | quarantine | `E12.6` |
| `GOV.BUDGET_RESOLVE` | 5 | Budget resolvable | **zero budget**, emit | zero | `E8.3` |
| `GOV.LIFECYCLE_STATE` | 5 | Resulting state ∈ {LIVE, QUARANTINED, REFUSED} | quarantine | quarantine | `E5.5` |
| **Stage C — composition closure** |||||
| `GOV.REGISTRY_FREEZE` | 5 | Registry complete; post-composition mutation raises | halt-boot | halt-boot | `E5.5` |
| `GOV.WIRING_CLOSURE` | 5† | Every manifest entry has a subscriber or `absent_by_config`; every subscription is in the manifest; cascade graph acyclic within the declared depth bound | halt-boot | halt-boot | `D.6` |
| `GOV.HANDLE_GRAPH` | 5† | The five permitted handle edges; **no handle originates at 7 or 11** | halt-boot | halt-boot | `3.1/B.1` |
| `GOV.ABSENCE_RULE` | 5† | Engines 1, 7, 8, 11 present; 9 and 10 present or flat-and-declared | **refuse to arm** | refuse to arm | `3.1/B.2` |
| `GOV.READINESS` | 5† | All twelve `READY` or `ABSENT_BY_CONFIG` | refuse to arm, naming engine and reason | refuse to arm | `D.5` below |
| `GOV.FINGERPRINT_SEAL` | 5† | One hash over config, registry, `universe_hash`, `identity_hash`, wiring hash, declared-support set, parity manifest fingerprint | halt-boot | halt-boot | `F7.5` |

† Kernel mechanism; engine 5 is named as owner because it is the engine that publishes the composition-time artifact these gates close over, and P3's template admits exactly one engine. The mechanism/owner split is stated in the record itself.

**The measured position: Stage B exists, Stages A and C do not.** All 52 `alpha_load_gate` sites are per-alpha; nothing today refuses a boot over an unresolved universe, an unenumerated wiring graph, or an unready engine. That is not a criticism of the implemented ladder, which is the platform's strongest enumerable surface — it is the observation that **the ladder guards which alphas may run and nothing guards whether the platform may.**

---

### D.4 — Runtime ladder — 34 spine gates + 3 generated families

`hot` throughout. Legs: **E** every event · **Q** market data · **B** boundary · **D** decision · **P** plan · **S** submission · **F** fill simulation. Position is `(leg, rank)` flattened to a dense ordinal by the registry.

| ID | Leg | Owner | Predicate, in brief | On fail | On unknown |
|---|---|---|---|---|---|
| `RT.KILL_SWITCH` | E | 11 | Switch inactive | halt | **treat as active** |
| `RT.SCHEMA_SUPPORTED` ‖ | E | receiver | `schema_version` present and supported | reject | reject — **not v1 by default** |
| `RT.CONTRACT_CONFORM` ‖ | E | receiver | Units declared, staleness metadata present, `source_layer` non-null, enums valid | reject, with provenance | reject |
| `RT.IN_UNIVERSE` ‖ | E | receiver | `in_universe(instrument_id)`, total | reject, count, emit | reject |
| `RT.FRAME_PARSE` | Q | 1 | Frame parseable | reject + emit | reject |
| `RT.SEQUENCE_REUSE` | Q | 1 | Not a duplicate `(sequence_number, fingerprint)` | drop + count; **same seq, different bytes ⇒ CORRUPTED (terminal)** | CORRUPTED |
| `RT.STREAM_ORDER` | Q | 1 | Merge key strictly increasing | count + emit, **in every mode** | count + emit |
| `RT.QUALITY_CLASSIFY` | Q | 1 | Crossed / locked / zero-side / size / staleness classified | degrade + emit | degrade |
| `RT.MARK_VALIDITY` | Q | 7 | Quote may move a mark | retain last valid, flag stale, emit | retain + flag |
| `RT.FEATURE_WARMTH` | B | 4 | Input `warm=True`, or the declared reduced-confidence rule | suppress + emit | suppress |
| `RT.FEATURE_VALIDITY` | B | 4 | Input `valid` and within staleness bound | suppress + emit | suppress |
| `RT.REGIME_PREDICATE` | B | 4 | The alpha's declared predicate over engine 3's label | suppress + emit | declared no-regime branch |
| `RT.FORECAST_EXPIRY` | B | 6 | Within half-life from the forecast's **own** anchor | exclude + record | exclude |
| `RT.BARRIER_COMPLETENESS` | B | 6 | Completeness ≥ threshold against `UniverseSnapshot` members | skip boundary + emit | skip |
| `RT.NEUTRALITY_CERTIFIABLE` | B | 6 | Risk-model outputs present and versioned | reduced gross, constraint marked unverified, **or none** | as fail |
| `RT.BOOK_VERIFIED` | D | 8 | Book reconciled; divergence not `DIVERGED`/`UNDETERMINED` | no new exposure; reductions permitted | **treated as breach** |
| `RT.LATENCY_BUDGET` | D | 8 | `LatencyBudgetState ∈ {WITHIN, MARGINAL}` | stop opening; keep closing | **treated as breach** |
| `RT.DATA_HEALTH` | D | 8 | Per-instrument health `healthy` for **opening only** | no new exposure in that instrument | treated as degraded |
| `RT.MARK_FRESHNESS` | D | 8 | Mark fresh and valid | fail closed; reductions permitted | fail closed |
| `RT.BUDGET_RESOLVE` | D | 8 | `strategy_id` resolves to a budget | **zero budget**, alert | zero |
| `RT.EXPOSURE_LIMITS` | D | 8 | Per-symbol, per-strategy, gross, net, sector, factor | scale factor < 1 | zero |
| `RT.BUYING_POWER` | D | 8 | Sufficient buying power | scale down | **zero, not the previous value** |
| `RT.DRAWDOWN_TIER` | D | 8 | Tier permits; hysteresis declared | scale down / flat-only | more restrictive tier |
| `RT.VERDICT_COMPOSE` | D | 8 | Composed factor ≤ **min** of inputs; zero yields no order | no order | zero |
| `RT.SESSION_ADMISSION` | P | 9 | Halt, SSR, locate, blackout permit construction now | decline + emit | **decline** (`UNKNOWN` ≡ `HALTED`) |
| `RT.COST_GATE` | P | 9 | Edge clears round-trip cost at the declared model version | decline opening; reductions proceed cost-unpriced-and-marked | decline |
| `RT.LIMIT_PRICE_VALIDITY` | P | 9 | Book not crossed / zero-side at price derivation | decline, or plan a style needing no limit | decline |
| `RT.MIN_SIZE` | P | 9 | Quantity ≥ minimum | decline **and emit** | decline |
| `RT.DUPLICATE_INTENT` | P | 9 | No outstanding order for the same target | suppress + emit; **blocks only, never cancel-then-submit** | suppress |
| `RT.NO_INCREASE` | P | 9 | Σ\|planned\| ≤ approved, per symbol per tick, **including exits** | no orders from that plan | no orders |
| `RT.JOURNAL_ABSENCE` | S | 10 | Order id provably absent from the durable journal | **refuse to submit** | refuse |
| `RT.ORDER_EXPIRY` | S | 10 | Now ≤ the order's declared event-time expiry | reject with reason, never work it | reject |
| `RT.SESSION_SUBMIT` | S | 10 | Venue open, tick size valid, auction eligibility | do not submit + emit | do not submit |
| `RT.BROKER_STATE` | S | 10 | Connected and state known | no new submissions; reconcile on reconnect | no submissions |
| `RT.STATE_TRANSITION_TOTAL` | S | 10 | `(state, event)` pair defined | **raise** rather than proceed | raise |
| `RT.FILL_ELIGIBILITY` | F | 10 | Resting order was live and latency-eligible at or before the market event, **in exchange time** | no fill inferred | no fill |
| `RT.CROSSED_NO_FILL` | F | 10 | Book not crossed at the fill instant | no fill inferred | no fill |

‖ Family — one instance per receiving boundary; count generated from the wiring manifest.

**Two placements this ladder makes that Phase 2 explicitly deferred.**

`_data_health_blocks_trading:5263` was handed to Phase 3 by engine 1's sheet ("engine 1 publishes health; it does not veto"). **The call: owner is engine 8, and it applies to opening only.** It is a permission to take exposure conditioned on the reliability of our view, which is a risk input, not an execution constraint. Its overlap with `RT.MARK_FRESHNESS` is declared rather than collapsed: mark staleness governs the **valuation** of a position held, health governs **admission** of new exposure in an instrument — a symbol with no position has no mark, so one gate cannot cover both cases. Two facts, two gates, both exposure-reducing, precedence fixed by ordinal.

`RT.LATENCY_BUDGET` sits on the decision leg and **not** on the market-data leg, which is F.6's resolution made mechanical: under overload the platform gets slower and less willing to trade, never blinder. A latency gate placed on leg Q would shed information without reducing exposure — superficially satisfying CORE §C.5 and failing its direction test.

---

### D.5 — Seven expanded records

Written in full because each carries a call, a measured defect, or a declared exception. The remaining 46 are generated.

```
GATE:               RT.KILL_SWITCH
LADDER:             runtime          OWNER ENGINE: 11        LATENCY CLASS: hot
LEG / POSITION:     E / 1            FAMILY: none
INPUTS:             kill-switch state (11). No staleness tolerance — the read is
                    synchronous and total. CORE §D's single permitted hot read of
                    a cold engine.
PREDICATE:          is_active == False
ON FAIL:            halt — no dispatch, return early
ON UNKNOWN:         TREAT AS ACTIVE. The only fail-closed reading of an unreadable
                    safety authority.
ON EXCEPTION:       INVARIANT_VIOLATION. A raise in the switch read is treated as active.
EXPOSURE EFFECT:    == ungated for opening; > ungated when a reduction is blocked
MONOTONE:           DECLARED EXCEPTION — the only one in either ladder.
                    Reason: the switch fires when the platform's own correctness is in
                    doubt. A platform that cannot be trusted to size an order cannot be
                    trusted to flatten one; an incorrect flatten reverses a position, and
                    a reversed position is exposure. The exposure-reducing branch for
                    "we may be wrong" is stop acting, not act to reduce. Engine 11's
                    sheet already fixed the switch as binary and total and refused it a
                    partial-reduction lever; this record states the consequence that call
                    carries and that sheet did not name.
                    OPERATIONAL CONSEQUENCE, DECLARED: a killed platform holds its book
                    and requires an operator. That must be in the runbook, not discovered.
REDUCTION-BLOCKING: declared(as above)
DISABLEABLE:        no
EMISSION:           KillSwitchActivation — trigger, measured value, threshold, actor,
                    scope halted. Today this event has NO consumer in any mode despite a
                    docstring at src/feelies/core/events.py:416 stating it is "published
                    on the bus so all layers can react" (Phase 0 C-4, VERIFIED). The
                    wiring manifest makes that either a subscriber or an
                    absent_by_config declaration.
TESTED BY:          E11.2 (fail-closed incl. durability), D.MONO.EXC (exactly one
                    declared exception exists in the registry)
```

```
GATE:               RT.BUDGET_RESOLVE
LADDER:             runtime          OWNER ENGINE: 8         LATENCY CLASS: hot
LEG / POSITION:     D / 5
INPUTS:             per-alpha budgets from engine 5's frozen registry (composition-time,
                    immutable); budget-consumption state (8)
PREDICATE:          strategy_id resolves to an allocation in the resolved registry
ON FAIL:            reject — ZERO budget, alerted. Not aggregate-only.
ON UNKNOWN:         zero
ON EXCEPTION:       ENGINE_FAULT, contained per decision, emitting
EXPOSURE EFFECT:    <= ungated
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           RiskVerdict with the binding constraint named
TESTED BY:          E8.3 (budget totality)
MEASURED DEFECT THIS REPLACES: `except KeyError: pass` at
                    src/feelies/alpha/risk_wrapper.py:189 — an OrderRequest whose
                    strategy_id is not in the registry "skips ALL per-alpha risk budgets
                    and falls through to aggregate checks only" (Phase 0 E-2, VERIFIED).
                    Phase 0's assessment is exact: the direction on unknown input is
                    FEWER constraints, not more. Platform caps still apply, so it is
                    fail-open-but-bounded — and CORE §C.9 admits no bounded exception.
                    This is the single gate at which the 5th alpha converts an incidental
                    hole into a systematic one.
```

```
GATE:               RT.FILL_ELIGIBILITY
LADDER:             runtime          OWNER ENGINE: 10        LATENCY CLASS: hot
LEG / POSITION:     F / 1
INPUTS:             resting-order book with queue-position estimates (10); market events
                    IN EXCHANGE TIME (1); the order's live-and-latency-eligible instant
PREDICATE:          market_event.exchange_timestamp_ns >= order.latency_eligible_ns
ON FAIL:            reject — no fill inferred
ON UNKNOWN:         no fill
ON EXCEPTION:       ENGINE_FAULT per order; never contained across a submission boundary
EXPOSURE EFFECT:    <= ungated
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           per-evaluation counter; every inferred fill carries the market event
                    and the eligibility instant it was judged against
TESTED BY:          E10.1 — the highest-value regression test in the platform
CURRENT STATE, AND WHY THIS RECORD EXISTS: both passive paths already enforce the gate in
                    exchange time — src/feelies/execution/passive_limit_router.py:527 for
                    quote-driven fills and :242 for trade-driven queue drain — rated
                    `implemented` and checked directly by Phase 0. THE TEST EXISTS TO KEEP
                    IT TRUE, NOT TO DISCOVER IT. The failure it guards is biased rather
                    than noisy, so a regression is invisible in aggregate statistics and
                    flattering in the direction that matters. CORE §H requires this gate
                    be re-audited whenever a router or simulator component changes, not
                    only when a result looks suspicious.
                    RESIDUAL: engine 10's two parity baselines are `market_fill_acks` and
                    `halt_ack`; NEITHER IS A PASSIVE FILL SEQUENCE, so the property this
                    gate protects is not itself pinned by a baseline (Phase 1 §6, engine
                    10 test 7). Adding one is the cheapest coverage gain on that sheet.
```

```
GATE:               RT.MIN_SIZE
LADDER:             runtime          OWNER ENGINE: 9         LATENCY CLASS: hot
LEG / POSITION:     P / 4
INPUTS:             planned quantity (9); venue minimum (10's constraint set, read as a
                    published constraint, not by reaching into the router)
PREDICATE:          |quantity| >= venue_minimum
ON FAIL:            reject — decline AND EMIT the decline record naming this gate
ON UNKNOWN:         decline
ON EXCEPTION:       ENGINE_FAULT per intent, all-or-nothing per plan
EXPOSURE EFFECT:    <= ungated
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           decline record — one per intent that did not become an order
TESTED BY:          E9.3 (decline totality: intents in = orders out + declines out)
MEASURED DEFECT: hop 33's min-size gate PRODUCES NO RECORD today (Phase 0 D0.4, engine 9
                    sheet, VERIFIED). This is the plainest instance of P3's rule — a gate
                    that silently rejects is indistinguishable from a gate that never
                    fires — and it is why decline totality, not the gate itself, is the
                    binding conformance test.
```

```
GATE:               RT.REGIME_PREDICATE
LADDER:             runtime          OWNER ENGINE: 4         LATENCY CLASS: hot
LEG / POSITION:     B / 3
INPUTS:             RegimeState (3), change-plus-heartbeat, staleness on the payload
PREDICATE:          the ALPHA'S OWN declared predicate over engine 3's label.
                    The fact is engine 3's; the predicate is the consumer's.
ON FAIL:            reject — suppress the forecast and emit the suppression
ON UNKNOWN:         the alpha's declared no-regime branch, which must exist.
                    src/feelies/composition/engine.py:217 already skips rather than
                    extrapolating below threshold — correct direction, promoted here from
                    default to contract.
ON EXCEPTION:       ENGINE_FAULT contained PER ALPHA — one alpha raising must leave every
                    other alpha's stream bit-identical
EXPOSURE EFFECT:    <= ungated
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           suppression notification naming the gate. Silence must not read as
                    "no opinion" when it means "gated."
TESTED BY:          E3.4 (removability), E4.2 (alpha isolation)
THE ENUMERATION PROBLEM THIS GATE OWNS: the `regime_gate` marker family is the largest in
                    the platform at 56 sites — forensics 19, risk 13, signals 12, core 7
                    (Phase 0 D0.5, VERIFIED). 56 SITES ARE NOT 56 GATES. The family name
                    conflates a runtime gate with a plain regime read: engine 12
                    legitimately KEYS analysis on a regime label, and under 3.1's tier
                    rule and 3.2's matrix a runtime gate cannot live in a cold engine (19
                    sites) or in Tier 0 (7 sites). Splitting gate from read is the closure
                    check's first job and its result is a falsifiable prediction, not an
                    assertion made here.
```

```
GATE:               GOV.UNIVERSE_DISCLOSURE
LADDER:             governance       OWNER ENGINE: 5         LATENCY CLASS: cold
LEG / POSITION:     B / 5
INPUTS:             config symbol list; per-alpha `universe` disclosure validated at
                    src/feelies/alpha/layer_validator.py:326
PREDICATE:          declared universe is a subset of the resolved platform universe
ON FAIL:            refuse the load, NAMING THE SYMBOLS AND THE ALPHAS
ON UNKNOWN:         refuse
ON EXCEPTION:       halt the boot — engine 5's ON EXCEPTION is halt at composition, and
                    it is affordable precisely because nothing is in flight
EXPOSURE EFFECT:    <= ungated
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           load-gate outcome record, per alpha, per gate
TESTED BY:          E5.4 (pathological-fixture refusal), F1 failure table
WHAT THIS REVERSES: Phase 0 D0.7 F.1 records that today "a config/alpha-disclosure
                    mismatch degrades the barrier rather than failing the load." The
                    mismatch currently lowers engine 6's completeness denominator, so a
                    misconfigured universe presents as a slightly thinner cross-section
                    instead of as a refusal. This is the specific place F.1's resolution
                    either takes effect or does not.
```

```
GATE:               GOV.READINESS
LADDER:             governance       OWNER ENGINE: 5 (kernel mechanism)  LATENCY CLASS: cold
LEG / POSITION:     C / 5
INPUTS:             readiness() from all twelve engines, total, returning
                    READY | NOT_READY(reason); the wiring manifest's absent_by_config set
PREDICATE:          every engine is READY or ABSENT_BY_CONFIG
ON FAIL:            refuse to arm, naming the engine and the reason. No market-data event
                    is accepted.
ON UNKNOWN:         refuse to arm
ON EXCEPTION:       halt the boot
EXPOSURE EFFECT:    <= ungated (nothing has run)
MONOTONE:           yes            REDUCTION-BLOCKING: never
DISABLEABLE:        no
EMISSION:           durable session record naming the twelve states and the manifest hash
TESTED BY:          3.1/B.2 absence-rule table; E11's null-implementation test — with
                    engine 11 replaced by a null, the platform must REFUSE TO TRADE, which
                    is the only substitutability test in the twelve that asks whether the
                    platform correctly declines rather than whether it still works.
WARMUP IS NOT READINESS. Engine 2's min_history produces warm=False per feature, which is
                    a property of the tape. Folding it into readiness would make readiness
                    a function of the event stream and therefore re-evaluated per event —
                    which is a governance gate on the tick path. THERE IS NO RE-ARM: a
                    dependency lost after arm is an F.5 fault, not a return to NOT_READY.
```

---

### D.6 — Single-source enumeration

**One registry module, declaring 53 records as frozen data.** Ordinals are **generated** from `(ladder, leg, rank)`; identity is a stable string. Docs are generated; test bindings are generated and `TESTED BY` must resolve or the registry fails to build. The registry hash enters `config.snapshot().checksum` alongside `universe_hash`, `identity_hash`, the wiring hash and the declared-support set.

**The closure check.** `tools/arch/gatescan.py` — which already exists and already finds the fail-quiet sites (§F.5 conformance test 2) — becomes bidirectional: every `*_gate` marker site in `src/` maps to a registry entry, and every registry entry has at least one site or a declared exemption with a reason. **This exact pattern is already proven twice in this codebase**, at `tests/determinism/test_parity_manifest.py:261` (AST-scan the tree, fail unless referenced or exempted with a reason) and `:288` (fail on a stale exemption). It is being reused, not invented, which is the strongest available argument that it will hold.

**G13, resolved by making the question disappear.** P3 offers two outs — the hole is meaningful and documented, or the numbering is wrong. **The numbering is wrong, and structurally so:** G1…G17 uses position as identity, so a deleted gate leaves a hole and a reordering renames every gate after it. Under stable IDs the hole cannot recur. The old numbers survive as `ALIASES` so the existing audit trail stays resolvable — including the one Phase 0 D-22 found citing `layer_validator.py:760` for G13 at a location that no longer resolves, which is itself the second symptom of ordinal-as-identity: a document pinned to a position that moved.

Whether G13 was deleted or never existed is **unmeasured** and decides only whether the registry needs a `RETIRED` alias entry. One read closes it.

---

### D.7 — Precedence

**Three rules, in order of how much they matter.**

**1. One snapshot per tick.** All gate inputs are resolved at event ingress and every gate on that tick evaluates against that snapshot. §F.3 already requires this for halts — "the state applies from its declared effective event time, and every gate on that tick evaluates against one snapshot; partial application within a tick is a causality violation (CORE §C.2)" — and it generalizes without amendment. Without it, precedence is undefined not because two gates tie but because they saw different worlds.

**2. Short-circuit the decision; never the record.** On the first FAIL at position *k*, positions *k+1…n* are recorded `NOT_EVALUATED`. **The optimistic bias P3 names does not come from the wrong gate firing — it comes from every downstream gate reading as PASS in exactly the stress scenario it never saw.** Recorded as `NOT_EVALUATED`, coverage statistics stay honest at zero latency cost, because nothing extra is evaluated.

**3. Cross-ladder ties are impossible by construction.** Governance completes before the first event is accepted, so no governance gate can tie with a runtime gate. That is the mechanical form of "conflating the two ladders is a known failure mode": if a tie between the ladders is ever observable, an eligibility decision has moved onto the tick path.

**The scale-factor composition rule, called rather than left open.** Engine 8's sheet registers it as undetermined and states the stakes exactly: whether composition is multiplicative, minimum, or something else "determines whether monotonicity holds by construction or by coincidence." **The call: minimum.** Both min and product are monotone, and product is strictly more conservative — so the argument is not conservatism, it is two other properties. First, `RiskVerdict` must name a **binding constraint**; a product has no binding constraint, because neither input alone produced 0.25 from two 0.5s. Second, and decisively, **a product is not scale-invariant in N**: as alphas and limit types accumulate, the product of N sub-unit factors tends to zero, so the platform would trade less as it scales for a reason nobody chose and no alert would fire. `min(a, b) ≤ a` gives monotonicity by construction and preserves a nameable binding constraint. `_compose_scaled_quantity` at hop 35 is the site; what it does today is unmeasured.

---

### D.8 — De-risking monotonicity

**The property, stated so it can be tested rather than asserted.** Let `E(s)` be the declared exposure functional over book state `s` — per-instrument absolute signed quantity, summed. Using `|position|` rather than signed position is load-bearing: it makes an over-flatten into a reversed position count as exposure, which is what makes `RT.JOURNAL_ABSENCE` correctly classified as non-reduction-blocking even though it can refuse a flatten order.

For every event *e*, book state *s*, and gate subset *S* ⊆ ladder:

```
(1)  E(apply(ladder_S, e, s))  ≤  E(apply(∅, e, s))          no gated path exceeds ungated
(2)  S ⊆ S'  ⇒  E(apply(ladder_S', e, s)) ≤ E(apply(ladder_S, e, s))   adding a gate never increases exposure
```

(2) is the stronger statement and it is the one that matters when gates compose, because (1) alone can hold for each gate individually while a pair interacts.

**The test.** Property-based over generated event streams with a randomised subset lattice over the 34 runtime gates, asserted **at every event, not at run end** — the same reason engine 7's conservation identities are per-event: a pair of cancelling errors is approximately zero at the end of a run. Plus a targeted adversarial suite whose whole content is reduction-blocking: for every degraded state in every engine's sheet, assert a flattening order is permitted. Hop 31 already re-ALLOWs reductions at `src/feelies/kernel/orchestrator.py:1782`; this converts one code path into an asserted property across the ladder.

**Exactly one declared exception, and the count is itself a test.** `RT.KILL_SWITCH` carries `MONOTONE: declared-exception`. `D.MONO.EXC` asserts that the number of registry entries with that value is **one**. A second exception cannot be added quietly — it fails a test that names the count rather than the entry.

**The failure mode this catches that a per-gate review does not:** a risk engine that can block its own de-risk. Engine 8's sheet calls it "the one failure mode worse than permitting too much," and it is invisible to inspection because every individual gate looks conservative. Only the composed property sees it.

---

### D.9 — Observability of every rejection

**Every gate produces a verdict on every evaluation**, from a closed set: `PASS` · `FAIL(reason)` · `UNKNOWN(→ branch taken)` · `NOT_EVALUATED`.

| Outcome | Emission |
|---|---|
| `FAIL`, `UNKNOWN` | Individual record on the notification channel (3.2), **always**, naming the gate, the binding input, and every input's as-of time |
| `NOT_EVALUATED` | Recorded in the tick's gate record; counted per gate |
| `PASS` | Counted; counts emitted at declared cadence, **aggregated with exact counts, never dropped** — engine 11's own rate-limiting rule applied to the ladder |
| `PASS` where a sheet requires wire totality | Individually emitted — engine 8's `RiskVerdict` on **every** evaluation including ALLOW, because a veto record that exists only on denial cannot prove monotonicity |

**Gate health is four-way, and this is the half P3's clause does not name.** P3 says a gate that silently rejects is indistinguishable from a gate that never fires. The dual is sharper: **a gate that never fires is indistinguishable from a gate that is not wired.** Each gate carries `never-evaluated / stale / degraded / healthy` per run, on engine 11's enumeration. A gate with zero evaluations over a run is `never-seen` and alertable — never `healthy`. Without it, deleting a gate's call site and deleting a gate's effect look identical in every metric the platform emits.

The measured baseline this addresses: `RiskVerdict` is published to **zero subscribers in any mode** (Phase 0 C-4, `VERIFIED`), so both of today's vetoes are unobservable outside a trace. Every gate in leg D emits through that contract. Wiring it is a manifest entry, not a mechanism.

---

### Standing checks for this axis

**Alpha-naming (CORE §I).** Clean. `RT.REGIME_PREDICATE` and `GOV.CONTRACT_SHAPE` are the two gates where an alpha's declared properties are read; both key on declared properties and neither branches on identity. The one identity-branching gate in the platform — route selection from `moc_strategy_ids` — is not in this ladder, because under 3.2's resolution route follows a declared property and there is no gate to write.

**Overlaps flagged, not split.**

1. **The gate registry overlaps the wiring manifest.** Both are composition-time data hashed into the run fingerprint, and `GOV.WIRING_CLOSURE` is a gate over the manifest. They stay separate: the manifest declares *who receives what*, the registry declares *what is checked and in what order*. Merging them would put a gate's predicate and its transport in one object, which is the policy/mechanics conflation this review has separated five times.
2. **`RT.DATA_HEALTH` and `RT.MARK_FRESHNESS` overlap and are deliberately not merged**, for the reason given in D.4. Recorded so it is not re-litigated as recompute-as-redundancy in Phase 5.
3. **The 56-site `regime_gate` family spans the gate/read boundary**, and the split is unmeasured. Flagged as the closure check's first output, not asserted here.

**Model finding: none.** The one responsibility with no §E owner — the total order across gates belonging to different engines — is framework with no trading-domain content and goes to the cross-cutting kernel on the argument already used for the ordering key, the barrier, the exception taxonomy and schema versioning. **The watch-line:** if a gate's ordinal ever needs to depend on what an alpha *means* rather than on which leg it sits in, the registry acquires trading-domain content and this becomes a model finding.

**No new §F-class finding.** The count stays at two — the horizon grid and risk-model provenance. The second now gates `RT.NEUTRALITY_CERTIFIABLE`, which cannot state its input's version until an owner exists.

**Assumptions registered.**

- **U-6 is blocking, not merely open.** Whether `enforce_layer_gates=False` is reachable in any non-research config decides whether `DISABLEABLE` can be declared `no` for the 52-gate ladder. One grep over `configs/`.
- **Whether the scale-factor composition is multiplicative or minimum today.** Decides whether the monotonicity property currently holds by construction or by coincidence.
- **Whether G13 was retired or never existed.** Decides whether the registry needs a `RETIRED` alias.
- **How many of the 56 `regime_gate` sites are gates rather than reads.** Decides the runtime ladder's real site count and whether the tier rule is currently violated at 26 of them.
- **Whether any runtime path reads engine 5's mutable lifecycle state.** Engine 5 test 1's dynamic half is unmeasured; it is the direct test of ladder separation.
- **Whether `_resolve_order_route:3371` has any input other than `_moc_strategy_ids`** — carried from engine 9's sheet, and now a registry question: it decides whether route selection is a gate with a declared-property predicate or a lookup with no predicate at all.

**Carried into later phases.** **Phase 4:** the runtime ordinal is the index the per-engine latency budget is written against, and engine 6's leg-B gates need a boundary-conditional tail rather than a mean. **Phase 5:** every registry entry with no site is a gap-table row, which makes the gap table generated rather than assembled. **Phase 6:** the registry *is* the conformance suite's index — CORE §G.5 is satisfied when `TESTED BY` resolves for all 53, and the three CORE §I fixtures are what populate the negative half.

### Verification performed on this section

- No repo access. Every citation is re-quoted from Phase 0, Phase 1 or Phase 2 at its assigned label; nothing upgraded.
- Two Phase 2 deferrals are resolved rather than re-deferred: `_data_health_blocks_trading`'s owner, handed to Phase 3 by engine 1's sheet, and the scale-factor composition rule, registered as undetermined on engine 8's. One consequence of an existing Phase 2 call is newly declared: the kill switch's monotonicity exception.
- Net complexity, stated honestly: the registry is a **net add** — one data module plus a closure test — admissible under CORE §G.10 as a contract definition and conformance test. **What it deletes is claims, not code:** the prose gate sequences in `docs/`, the hand-maintained G-numbering, and the audit citation that no longer resolves. The code deletions this axis enables — the tick-wide catch-all as the normal case, the unrecorded min-size rejection — are consequences of the F.5 taxonomy and engine 9's decline totality, and belong to those items' migration steps rather than to this one.
- No production code changed; nothing proposed outside `docs/architecture/target/out/` and `tools/arch/`.

