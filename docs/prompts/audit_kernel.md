# Kernel orchestrator & micro/macro state-ordering audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
determinism backbone — the `Orchestrator`, the macro/micro state machines, the event bus,
sequence allocation, single-writer enforcement, and the M1–M6 micro-state ordering that
makes replay bit-identical.

---

## Mission

You are a senior deterministic-systems architect and concurrency auditor. Perform a
**read-only, evidence-based audit** of the feelies kernel.

**Primary focus:** This is the spine the entire platform hangs on. Inv-5 (deterministic
replay), Inv-6 (causality), Inv-7 (typed events), and Inv-8 (layer separation) are
*enforced or violated here first*. A single nondeterministic iteration, a hidden global,
or a mis-ordered micro stage breaks every parity hash and every downstream guarantee.

**Goal:** Identify where ordering is provably deterministic vs. incidentally so, where the
single-writer and layer-separation contracts hold vs. leak, where sequence/clock semantics
could diverge on replay, and what changes would harden determinism — without changing
behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/system-architect/SKILL.md` end-to-end.
2. Read `docs/three_layer_architecture.md` §7 (Micro SM extension — §7.2 transitions,
   §7.3 formal rules, §7.4 HorizonScheduler, §7.5 UniverseSynchronizer), §12 (determinism
   & parity).
3. Read `.cursor/rules/platform-invariants.mdc` Inv-5, 6, 7, 8, 10.

**Architecture (contractual):**

```
M1  market event logged + bus published
M2  regime posterior (SOLE WRITER)
    SENSOR_UPDATE → HORIZON_AGGREGATE (HorizonScheduler boundaries)
M4  SIGNAL_EVALUATE (gate → HorizonSignal)
    UniverseSynchronizer barrier → CrossSectionalContext
M5  risk: check_signal / check_sized_intent + sizing
M6  risk: check_order + HazardExitController
M7  ORDER_SUBMIT → M8 ORDER_ACK → M9 POSITION_UPDATE (fill reconcile) → M10 LOG_AND_METRICS
```

> **NOTE — shorthand:** "M1–M6" is an abbreviation. The implemented micro SM is the
> 16-state `MicroState` enum (`src/feelies/kernel/micro.py`): WAITING_FOR_MARKET_EVENT
> → MARKET_EVENT_RECEIVED → STATE_UPDATE → SENSOR_UPDATE → HORIZON_CHECK →
> HORIZON_AGGREGATE → SIGNAL_GATE → CROSS_SECTIONAL → FEATURE_COMPUTE →
> SIGNAL_EVALUATE → RISK_CHECK → ORDER_DECISION → ORDER_SUBMIT → ORDER_ACK →
> POSITION_UPDATE → LOG_AND_METRICS, with branch/loop-back edges (PORTFOLIO
> multi-intent flush, session-flatten and working-exit paths reach the order stages
> too). **Audit transitions against the enum and `_MICRO_TRANSITIONS`, not this
> shorthand.** Other prompts (`audit_regime.md`, `audit_performance.md`,
> `audit_signal_alpha.md`) use the same abbreviation and defer to this note.

- **Macro SM:** session/lifecycle (open → trading → close).
- **Micro SM:** per-event stage ordering M1–M6; strictly sequenced.
- **Single-writer:** exactly one component writes each event type (e.g. regime at M2).

**Hard invariants (non-negotiable):**

- Inv-5: same event log + params → bit-identical signals/orders/PnL.
- Inv-6: stage T uses only events with ts ≤ T; processing delay explicit.
- Inv-7: typed events on the bus; no untyped cross-layer messages.
- Inv-8: every line belongs to exactly one layer; no hidden global state.
- Inv-10: timestamps via injectable clock; no raw `datetime.now()` in core.

---

## Scope — files to audit

### Kernel

- `src/feelies/kernel/orchestrator.py` — M1–M6 driver, bus subscribers, drains
- `src/feelies/kernel/micro.py` — micro state machine (stage ordering)
- `src/feelies/kernel/macro.py` — macro/session state machine
- `src/feelies/kernel/signal_order_trace.py` — provenance trace
- `src/feelies/bus/event_bus.py` — event bus (delivery order, typing)
- `src/feelies/core/state_machine.py` — generic SM primitive

### Bootstrap & wiring (component graph — owned here)

- `src/feelies/bootstrap.py` — per-mode component construction & dependency injection
  (the wiring point every other audit treats as a *touchpoint*; this audit **owns** it)
- `src/feelies/__main__.py` — process entry shim

### Tests (spec + gap analysis)

- `tests/kernel/test_orchestrator.py`, `test_micro.py`, `test_micro_extended.py`,
  `test_micro_sm_signal_gate.py`, `test_micro_sm_signal_props.py`, `test_macro.py`
- `tests/kernel/test_orchestrator_bus_signal.py`,
  `test_orchestrator_bus_sized_intent.py`, `test_orchestrator_hazard_exit_routing.py`,
  `test_orchestrator_idle_tick.py`, `test_orchestrator_shutdown_drain.py`,
  `test_orchestrator_async_fill_latency.py`, `test_orchestrator_cost_gate.py`
- `tests/kernel/test_signal_order_trace.py`
- `tests/bus/test_event_bus.py`, `tests/core/test_state_machine.py`
- Bootstrap wiring: `tests/bootstrap/test_execution_backend_wiring.py`,
  `test_composition_wiring.py`, `test_paper_branch.py`,
  `test_promotion_ledger_wiring.py`, `test_enforce_layer_gates.py`,
  `test_gate_thresholds_wiring.py`, `test_per_alpha_risk_budget_wiring.py`
- Determinism: `tests/determinism/` (all parity hashes depend on kernel ordering)
- Causality: `tests/causality/test_anti_lookahead.py`

**Out of scope:** the internal math of sensors/signals/risk/composition (audited
separately), and the orchestrator's **decision/exit economics** (stop-exit, reverse,
flatten, B4/B5 edge-cost gates, session flatten, working exits — owned by
`audit_position_management.md`); focus on **ordering, sequencing, writer discipline,
and layer boundaries**.

---

## Audit dimensions (answer each with evidence)

### A. Determinism of ordering (Inv-5) — highest priority

1. Enumerate every iteration over a collection in the M1–M6 path. Is each over a
   deterministically-ordered structure (sorted / insertion-ordered), never a `set` or
   unordered `dict` view that could vary?
2. Sequence allocation: how are `sequence` / correlation IDs assigned, and is allocation
   order a pure function of the event log?
3. Bus delivery: are subscribers invoked in a deterministic order? Multiple subscribers to
   one event type — tie-break defined?
4. Drains (signal buffer, sized-intent, hazard exit): deterministic flush order?

### B. Micro-state ordering (§7)

1. Map the implemented micro SM transitions to §7.3 formal rules. Any stage that can run
   out of order, or be skipped, under sparse/idle ticks?
2. HorizonScheduler boundary detection: pure integer math anchored to `session_open_ns`?
   Off-by-one at boundaries?
3. UniverseSynchronizer barrier: deterministic emission even when symbols report in
   varying order?

### C. Single-writer & layer separation (Inv-7, Inv-8)

1. Confirm exactly one writer per event type (regime at M2; signals; intents; orders).
   Grep for any second writer.
2. Hidden global state: module-level mutables, class attributes used as caches, singletons
   that survive across replays?
3. Cross-layer leakage: does the orchestrator reach into a layer's internals rather than
   consuming its typed events?

### D. Clock & causality (Inv-6, Inv-10)

1. Is every timestamp sourced from the injectable clock? Grep `datetime.now`,
   `time.time`, `perf_counter` in core.
2. Trace one event M1→M6: can any stage read data with ts > current sim-time?
3. Processing delay: modeled explicitly where claimed?

### E. Shutdown / drain / idle semantics

1. Shutdown drain: does it flush deterministically without dropping or reordering events?
2. Idle-tick injection: parity between replay and live; does it perturb ordering?

### F. Bootstrap, wiring & mode parity (Inv-9)

1. `bootstrap.py` constructs the component graph per mode (BACKTEST / PAPER / LIVE). Is
   the **only** divergence behind `ExecutionBackend`, or does mode selection branch core
   wiring (sensors, signals, risk, composition) in ways that could break parity?
2. Single-writer wiring: is exactly one writer per event type wired, regardless of mode?
3. Construction determinism: is the component graph built in a deterministic order (no
   import-order or dict-iteration dependence that leaks into runtime ordering)?
4. Conditional subsystems (`has_portfolio_alphas()`, hazard-exit, promotion ledger): are
   they wired only when configured, and does their absence leave a clean, fail-safe graph?
5. `registry_clock=None` in backtest (lifecycle disabled): confirm it does not perturb
   replay and that ledger/forensic paths stay off the per-tick path.

### G. Test & validation gaps + prioritized recommendations

1. Map invariants (deterministic iteration, single-writer, micro ordering, clock
   discipline, layer separation) to tests — **covered / partial / missing**.
2. Which parity hashes would break if a specific ordering assumption changed? Note the
   coupling.
3. Propose **minimal** new tests (iteration-order fuzz under fixed log, single-writer
   assertion, micro-ordering property) — specs only.
4. Tiers:
   - **P0:** any nondeterministic ordering, second writer, hidden global, wall-clock in
     core, causality leak.
   - **P1:** fragile tie-breaks, idle/drain ordering edge cases, layer leakage.
   - **P2:** clearer stage contracts, observability of micro transitions.

Each item: component, `file:line`, one-sentence fix, expected impact on determinism.

---

## Working method

1. Build a **micro-stage map** (M1–M6: writer, inputs, outputs, ordering guarantee).
2. Grep the hot path for `set(`, unordered dict iteration, `datetime.now`, `time.`,
   `random`, singletons.
3. Audit single-writer discipline per event type.
4. Trace one event end-to-end for causality.
5. Audit `bootstrap.py` mode wiring: diff the BACKTEST / PAPER / LIVE component graphs and
   confirm divergence is confined to `ExecutionBackend`.
6. Run **read-only** checks only:
   - `uv run pytest tests/kernel/ tests/bus/ tests/core/test_state_machine.py tests/bootstrap/ -q`
   - `uv run pytest tests/causality/test_anti_lookahead.py tests/determinism/ -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/kernel_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top determinism/causality risks first.
2. **Micro-stage map** (markdown table: stage, writer, inputs, ordering guarantee).
3. **Ordering determinism audit** (iteration, sequencing, bus delivery — deep dive).
4. **Micro-SM audit** (transitions vs §7.3).
5. **Single-writer & layer-separation audit**.
6. **Clock & causality audit**.
7. **Shutdown/drain/idle audit**.
8. **Bootstrap & mode-parity audit** (component-graph diff across modes).
9. **Parity-hash coupling map** (which hashes depend on which ordering assumptions).
10. **Test gap matrix**.
11. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **fragile-but-correct** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("orchestrator iterates `self._subscribers` which is a
  plain dict populated by import order → delivery order is import-dependent") over
  adjectives.
- Treat any nondeterministic ordering on the M1–M6 path as a P0 (breaks all parity).
- Any second writer to an event type, or any `datetime.now()` in core, is a P0.
- Do not propose fixes that change observable behavior; harden determinism only.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for any nondeterministic iteration on the hot
  path as a follow-up PR plan."*
- *"List every component that publishes each event type and prove single-writer per type —
  audit commentary only."*
- *"Design an iteration-order fuzz test (shuffle internal collections, assert identical
  parity hash) — spec only, no code."*
