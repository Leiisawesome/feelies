# Phase 5 — Gap table: measured current state vs the Phase 1–4 target

**Scope.** One row per independently-addressable difference between the target
specified in Phases 1–4 and the state of `src/feelies` as measured today. No
proposed fixes appear in any row — a gap row states what differs, not what to do
about it. Sequencing and remediation are a later session.

**Re-verification, not carry-forward.** Every claim below was re-measured against
current source in this session. Phase 0's findings were treated as hypotheses to
re-test, not as evidence. Concretely:

- All seven Phase 0–4 measurement scripts were re-run
  (`tools/arch/substrate.py`, `tools/arch/contracts.py`,
  `tools/arch/clockscan.py`, `tools/arch/gatescan.py`,
  `tools/arch/parityscan.py`, `tools/arch/coupling.py`,
  `tools/arch/hotpath.py`). **Every count and every headline number reproduced
  exactly.**
  One non-numeric label differs from the committed artifact: `substrate.json`'s
  `publishes_via` for the re-entrant handler at `src/feelies/monitoring/horizon_metrics.py:87`
  now reads `_publish_metric` rather than `_publish_alert`. `_on_context` calls
  **both**, so the field is ambiguous by construction and the scanner reports
  whichever route its traversal reaches first; the re-entrancy verdict and the
  count of 16 re-entrant handlers are unchanged. `tools/arch/substrate.py` was confirmed
  deterministic across three consecutive process runs.
- A new script, `tools/arch/gapscan.py`, re-resolves the **28 `path:line:symbol`
  citations** that Phase 2's engine sheets rest on, plus the 5 line-only
  citations. **All 33 resolve** (27 at a `def`, 1 at a tick-path call site, 5 at a
  token). No citation carried into this table has drifted.
- Four claims severe enough to be marked P0 were additionally verified by reading
  the code directly rather than by script. Each P0 paragraph names the lines.

Two Phase 0/glossary claims did **not** survive re-verification and are recorded
under *Documentation disagreements* rather than being silently propagated.

**Evidence base.** `tools/arch/evidence/*.json` (23 files), regenerated this
session. `gapscan.json` is new. Labels follow CORE: `VERIFIED` = read the code or
measured it; `INFERRED` = derived from something verified; `ASSUMED` = not
checkable in this phase.

---

## Gap table

| ID | Engine / Axis | Target | Current | Evidence | Invariant at risk | Severity | Blast radius |
|---|---|---|---|---|---|---|---|
| G01 | Axis A — clock | All timestamps via injectable clock; wall-clock reads confined to a declared allowlist (P1.1) | 18 clock reads in tick-critical packages; **12 are absent from `evidence/clock.json`'s allowlist**, and 5 of the 22 allowlist entries are not clock reads at all | `gapscan`/`tools/arch/clockscan.py`; `core/state_machine.py:180,198`; `src/feelies/kernel/orchestrator.py:1524,1633,1635,1675,1677,1771,1773,2104,3940,3950` | Inv-10 clock abstraction | P2 | All 12 are `perf_counter_ns` timing instrumentation, never a decision input. The defect is that the allowlist does not bound what it claims to bound, so a future decision read would not be caught |
| G02 | Axis A — bus | Bus delivery semantics defined at every boundary that can duplicate; re-entrancy either forbidden or specified (P1.3) | 32 subscribe sites, of which **16 reach `publish` from inside a handler**. `publish` has no idempotency key, no seen-set, no dedup | `substrate.json`; `src/feelies/bus/event_bus.py:59-70` | Inv-7 typed event bus; Inv-1 replay | P1 | Delivery is exactly-once only because it is a synchronous call. The platform does redeliver by design (arbitration re-publishes the selected `Signal`) and compensates at the reader (`src/feelies/harness/backtest_report.py:74-83`) |
| G03 | Engine 10 — identity | Order IDs exactly-once **across process restart and broker reconnect**, which requires durability, not just derivation (P1.4) | Both halves are in-process. `_submitted_order_ids` is a bare `set()` rebuilt per construction; `_next_valid_id` starts `None` each process. **No durable submitted-order record exists in `src/feelies`** | `src/feelies/execution/passive_limit_router.py:183`; `src/feelies/broker/ib/connection.py:353-364`; `src/feelies/storage/memory_event_log.py:7`; only `InMemoryTradeJournal` is wired (`src/feelies/bootstrap.py:358`) | **Inv-11 fail-safe default** | **P0** | Live capital. A restart mid-submission re-derives the same stable `order_id` and can re-submit it; the broker may or may not reject the duplicate. Backtest unaffected (single process) |
| G04 | Axis A — state | Every engine declares a reset path; replay starts from a known state (P1.5) | 110 stateful classes; 38 mutate outside `__init__`; **32 of those have no reset path**. `Orchestrator` is the extreme: 104 `__init__` attributes, 38 mutated later, zero reset methods | `substrate.json:stateful_no_reset_top` | Inv-1 deterministic replay | P1 | Contained today by process-per-run: every entry point constructs a fresh object. Breaks the moment two runs share a process (parameter sweeps, notebooks, a long-lived paper session) |
| G05 | Axis A — parity | Every engine output inside a parity hash (P1.6, P1.6.1) | 120 hash helpers over 177 distinct fields, but **6 event classes have no hash helper at all** (`Alert`, `KillSwitchActivation`, `MetricEvent`, `NBBOQuote`, `SensorReading`, `Trade`) and **15 event classes carry fields in no hash** | `parityscan.json:event_classes_with_no_hash_helper_annotation`, `:fields_in_no_parity_hash` | Inv-5 deterministic replay | P1 | `NBBOQuote` and `Trade` are the *inputs* — engine 1's canonical stream has no baseline of its own, so an ingestion-side change is invisible to the oracle until it moves a downstream hash |
| G06 | Axis A — fingerprint | Config/manifest fingerprint covers everything that can change output (P1.7) | The run fingerprint binds sensor wiring and config, but **alpha manifest *content* moves no checksum** — the forecast is parameterised by manifest values the fingerprint does not cover | `phase1_plumbing.md:575-634`; `src/feelies/harness/backtest_report.py:593,633` | Inv-13 full provenance | P1 | Two runs with different alpha parameters can share a config hash. The trade parity hash still moves, so the oracle catches the *effect*; provenance cannot attribute it |
| G07 | Axis A — schema | Typed contracts versioned so a consumer can reject an unknown producer version (P1.8, CORE §F.7) | **2 of 21 event classes carry a version field** (`HorizonFeatureSnapshot`, `SensorReading`). Every hot-path event is unversioned: `NBBOQuote`, `Trade`, `Signal`, `SizedPositionIntent`, `OrderRequest`, `OrderAck` | `gapscan.json:events`; 83 `schema_version` sites are alpha-YAML versioning in `promotion/` (25) and `cli/` (19), not events | Inv-10 versioned contracts; CORE §J.6 | P1 | No consumer can detect a producer-shape change. Caught today only by `mypy --strict` at build time, which sees one version of the tree at a time |
| G08 | Axis A — hash order | Deterministic replay bit-identical; no output ordered by a hash-ordered container (P1 determinism budget row 7) | **5 unsorted set iterations on the tick path.** Two iterate small-int horizon sets (int hashing is seed-independent); one clears distinct keys idempotently (order-insensitive, `VERIFIED` by reading `src/feelies/kernel/orchestrator.py:2938-2940`); two build containers whose *insertion order* varies by seed | `substrate.json:unsorted_set_iteration`; `composition/synchronizer.py:80,83`; `src/feelies/kernel/orchestrator.py:2938`; `src/feelies/portfolio/strategy_position_store.py:148`; `src/feelies/signals/regime_gate.py:555` | Inv-1, Inv-5 | P2 | No site is order-sensitive today. The residual is structural: CI's random-seed job covers `tests/determinism/` only, while the parity oracle — the guard that pins the trade hash, net PnL and fill count — runs at `PYTHONHASHSEED: "0"` (`ci.yml:114` vs `:138`) |
| G09 | Axis A — sequencing | A single sequence authority per stream (P1.2) | **26 `SequenceGenerator` constructions**, 13 taking the `thread_safe=True` default and 12 setting it explicitly. No registry names which stream each owns | `substrate.json`; `src/feelies/core/identifiers.py:28` (itself a no-reset stateful class) | Inv-5 deterministic replay | P2 | Sequences are per-object and never compared across objects, so no collision is possible today. The gap is that nothing records the invariant, so a future cross-stream comparison would be silently wrong |
| G10 | Axis B — emissions | Every declared emission has at least one consumer, or is not an event (P3 C.1) | **6 event types are published to zero static subscribers**: `KillSwitchActivation`, `OrderAck`, `PositionUpdate`, `RiskVerdict`, `StateTransition`, `SymbolHalted`. Zero types are subscribed-never-published | `contracts.json:published_never_subscribed` | Inv-7 typed bus | P1 | Publish cost is paid per event for no consumer. Each is separately addressable; `KillSwitchActivation` is the one with a docstring promising otherwise (G28) |
| G11 | Engine 1 — market data | One engine owns the canonical market-data stream; its output is versioned, provenance-stamped and parity-pinned | Responsibility split across `ingestion/`, `storage/` and **5 orchestrator methods**. The canonical stream carries no schema version (G07), no producer version, and has no parity baseline of its own (G05) | `gapscan` citations E1: `src/feelies/kernel/orchestrator.py:_update_halt_state:5014`, `_verify_data_integrity:5379` | Inv-8 layer separation; Inv-13 provenance | P1 | The platform's first contract is its least pinned. Every downstream hash depends on it |
| G12 | Engine 2 — state/feature | Emissions are immutable value objects | `HorizonFeatureSnapshot` is `frozen=True` but carries **5 mutable container fields**; 8 event classes share the pattern (`Alert`, `CrossSectionalContext`, `HorizonFeatureSnapshot`, `MetricEvent`, `RiskVerdict`, `Signal`, `SizedPositionIntent`, `StateTransition`) | `contracts.json:mutable_containers_in_frozen_events` | Inv-7 typed schemas | P1 | Frozen-ness is advisory for the fields that carry the actual feature payload. Any holder can mutate a published event in place |
| G13 | Engine 2 — state | Reset and restore paths owned by the engine that owns the state | Feature checkpoint/restore is authored **in the kernel**, against a store that is always empty in the shipped configuration | `gapscan` citations E2: `src/feelies/kernel/orchestrator.py:_restore_feature_snapshots:5423`, `_checkpoint_feature_snapshots:5454`; `phase1_plumbing.md:391-472` | Inv-8 layer separation | P2 | Dead in the shipped path — the store being empty means restore is a no-op. Becomes live the moment persistence is wired |
| G14 | Engine 3 — regime | Exactly one regime classifier, owned by one engine (CORE §E.3) | The single read path is correct and declared (`src/feelies/bootstrap.py:289`), but **5 classification methods live in the kernel** | `gapscan` citations E3: `src/feelies/kernel/orchestrator.py:_calibrate_regime_engine:2335`, `_update_regime:2432`, `_maybe_publish_hazard_spike:2501`, `_regime_label_for:4556`, `_checkpoint_regime_snapshot:5460` | Inv-8; CORE §J.1 god orchestrator | P1 | The engine CORE §E most insists must be singular is authored in the module CORE §J names as the anti-pattern. Two parity baselines do pin its output |
| G15 | Engine 4/6 — reduction | N forecasts → one portfolio is engine 6's defining responsibility, performed in one place | Engine 4's output is reduced to **one surviving forecast per tick inside the kernel** | `gapscan` E4: def `src/feelies/kernel/orchestrator.py:4831`, tick-path call at `:1676` (Phase 0 hop 28) | Inv-8; CORE §F.6 single source of truth | P1 | With A=1 the reduction is an identity and cannot be wrong. It is the structural blocker to A>1, which is the platform's stated purpose |
| G16 | Engine 5 — governance | Governance is cold and off the tick path (Inv: governance off the tick path) | `promotion/` is correctly cold and append-only, **but it is in the import closure of every tick-path module** | `imports.json` cycle 2; re-measured `tools/arch/coupling.py` | Inv-8 layer separation | P2 | Import-time only: no governance code executes per event (`hotpath.json:governance_evaluation` = 0 PROVEN, 0 per-event). Cost is startup and coupling, not latency |
| G17 | Engine 5 — gate ladder | The gate ladder is enumerable and complete (CORE §G "enumerable gates") | **G13 has zero references anywhere in `src/feelies`.** `LayerValidator` calls G1–G12 then jumps to G14–G17; 16 gates implemented, no stub, no comment marking the hole | `src/feelies/alpha/layer_validator.py:306-341`; repo-wide scan for `\bG13\b|_g13` returns 0 hits | Inv-13 auditable provenance | P1 | An alpha author reading `alphas/SCHEMA.md` cannot tell which of G1–G17 ran. See *Documentation disagreements* — the glossary calls G13 "a no-op", which overstates what exists |
| G18 | Engine 5/12 — authority | State transitions are written by the engine that owns the state machine | The `LIVE → QUARANTINED` transition is written from **engine-12 code** | `src/feelies/forensics/cost_circuit_breaker.py:159` (`VERIFIED`, token resolves) | CORE §F.6 single source of truth | P1 | Demotion always commits, which is the exposure-reducing direction, so the safety outcome is correct. The authority boundary is what is violated |
| G19 | Engine 6 — composition | One reducer from N forecasts to one portfolio | The reduction exists in **three places**: `composition/`, `_select_bus_signal` in the kernel (G15), and `src/feelies/alpha/arbitration.py` in engine 5's package | `gapscan`; `coupling.json`; Phase 0 D0.2 | CORE §F.6; Inv-8 | P1 | Three implementations of one rule; nothing asserts they agree. `src/feelies/composition/cross_sectional.py:75-79` holds the best determinism discipline of the three |
| G20 | Engine 6 → 7 read | Reads of another engine's truth fail closed (Inv-11) | The position lookup is wrapped in `except Exception: current_positions[s] = 0.0` — a lookup failure is reported to the optimizer as **flat** | `src/feelies/composition/engine.py:384-389`, marked `# pragma: no cover - defensive` | **Inv-11 fail-safe default** | **P0** | PORTFOLIO layer only, and only when `_position_lookup` is wired. Reporting flat when actually long makes the optimizer size a delta from zero — it can re-buy a position already held. See paragraph below |
| G21 | Engine 7 — accounting | One owner per number; position and P&L truth is not duplicated (CORE §J.3) | **36 direct store calls from the kernel** (`self._positions` 23, `self._strategy_positions` 13, re-measured today), plus 3 accounting methods in the kernel and a 4th in engine 5's package | `gapscan.json:orchestrator.store_access` (23 + 13 = 36, reproducing Phase 0 C-6); `src/feelies/kernel/orchestrator.py:_reconcile_fills:4229`, `_distribute_fill_to_strategies:4577`, `_record_fill_attribution:4057`; `src/feelies/alpha/fill_attribution.py` | CORE §F.6 single source of truth; Inv-8 | P1 | Money is exactly `Decimal` throughout, so no rounding divergence. The risk is two writers to one book, and `PositionUpdate` has no subscriber to observe it (G10) |
| G22 | Engine 8 — risk | Sizing and risk policy are authored inside the risk engine | Sizing, escalation and emergency flatten are **in the kernel** | `gapscan` E8: `src/feelies/kernel/orchestrator.py:_compute_target_quantity:2718`, `_escalate_risk:2530`, `_emergency_flatten_all:2601`, `_maybe_flip_buying_power_at_rth_close:782` | Inv-8; CORE §J.4 policy in mechanics | P1 | Risk policy cannot be reviewed, tested or versioned as a unit. `risk/` additionally hosts 4 engine-9 exit authors |
| G23 | Engine 8 — per-alpha budget | Unknown states resolve to reduced exposure (Inv-11) | An unrecognised `strategy_id` hits `except KeyError: pass` and **the entire per-alpha budget block is skipped** — position limit, drawdown and exposure checks all bypassed | `src/feelies/alpha/risk_wrapper.py:186-192` (`VERIFIED` by reading) | **Inv-11 fail-safe default** | **P0** | Aggregate limits still bind, so exposure is not unbounded. With A=1 per-alpha ≈ aggregate and impact is near zero; the gap scales with alpha count. See paragraph below |
| G24 | Engine 9 — execution decision | Execution decision policy is owned by one engine | **9 of engine 9's methods sit in the kernel**; its policy modules sit in `execution/` beside engine 10's mechanics | `gapscan` E9: `src/feelies/kernel/orchestrator.py:_plan_for_signal:2814`, `_try_build_order_from_intent:3278`, `_resolve_order_route:3371`, `_filter_portfolio_orders_for_admission:3505`, `_execute_reverse:2984`, cost gates at `:2184,:2226,:2266,:2295` | Inv-8; CORE §J.1 | P1 | The most dispersed engine in the platform. Order-emission logic cannot be unit-tested without constructing the orchestrator |
| G25 | Engine 9 — alpha-agnosticism | No alpha-specific branch or literal in core (Inv-6; CORE §G "zero core edits to attach an alpha") | **`src/feelies/core/platform_config.py` names an alpha as a default value**: `moc_strategy_ids: tuple[str, ...] = ("sig_moc_imbalance_v1",)` at `:108`, repeated at `:910` | `gapscan.json:alpha_leaks`; 3 hits total, the third being a docstring in `src/feelies/research/forward_ic.py:10` | **Inv-6 alpha-agnosticism** | P1 | Core config knows one alpha by name, on the MOC execution path. Overridable by config, so the default is the defect rather than a hard branch. This is the platform's only alpha-id leak into core |
| G26 | Engine 10 — mode seam | Mode-specific code only behind `ExecutionBackend` (Inv-9 backtest/live parity) | **27 mode branches, all outside `execution/` and `broker/`** — 20 in `src/feelies/bootstrap.py`, plus `src/feelies/core/platform_config.py` (2), `src/feelies/forensics/cost_circuit_breaker.py` (2), `harness/` (2), `src/feelies/promotion/lifecycle.py` (1). Zero inside `execution/` or `broker/` | `gapscan.json:mode_branches` | Inv-9 backtest/live parity | P1 | The 20 in `src/feelies/bootstrap.py` are the composition root choosing the seam, which is where mode branching belongs. **The 7 outside bootstrap are the actual gap** — mode reaching config, forensics, harness and governance |
| G27 | Engine 10 — order state | Order lifecycle transitions authored by the engine owning the order state machine | **6 transitions in the kernel**; 3 of engine 10's classes are the largest no-reset state holders after the orchestrator | `gapscan` E10: `src/feelies/kernel/orchestrator.py:_submit_tracked_order:3831`, `_poll_order_router_acks:3793`, `_apply_ack_to_order:4103`, `_transition_order:4086`, `_drain_async_fills:3936`, `cancel_order:3438` | Inv-8; Inv-9 | P1 | Order state can be advanced from two modules. `execution/` itself is the cleanest seam instance in the platform (G26) |
| G28 | Engine 11 — safety | Safety state changes are observable by every layer that must react | `KillSwitchActivation` has **no subscriber in any mode**, while `src/feelies/core/events.py:416` states it is "published on the bus so all layers can react" | `contracts.json`; `gapscan` line citation E11 resolves | Inv-11 fail-safe default | P1 | **The kill switch itself works** — it is read directly on the tick path and returns early (Phase 0 hop 4). Only the announcement is inert, so this is a false promise in a docstring, not a broken safety control |
| G29 | Engine 11 — parity | Every engine output inside a parity hash (P1.6.1) | Engine 11's entire output stream is **outside the parity manifest**; `Alert`, `KillSwitchActivation` and `MetricEvent` have no hash helper | `parityscan.json`; `phase1_plumbing.md:527-574` | Inv-5 | P2 | Safety and observability output is not replay-pinned. A change to alerting cannot break the oracle — which is also why it is P2, not P1 |
| G30 | Engine 12 — forensics | Every forensic output traceable to a fingerprinted run (Inv-13) | Engine 12's outputs **carry no fingerprint**; its forensic trace is produced inside the kernel and owned by no engine | `phase1_plumbing.md:575-634`; Phase 0 D0.2 | Inv-13 full provenance | P1 | A forensic conclusion cannot be tied to the run that produced it, so the decay→quarantine loop rests on an unversioned artifact |
| G31 | §F.1 — universe | Universe definition has exactly one owner | **200 sites across 11 packages** (`composition` 79, root 35, `alpha` 30, `sensors` 21, `risk` 13, `core` 10). No single definition point | `gapscan` §F probe | CORE §F.1; Inv-8 | P1 | Every layer forms its own view of "the universe". Disagreement between them is undetectable |
| G32 | §F.2 — symbol identity | Symbol identity over time is owned and handled (splits, symbol changes, corporate actions) | **3 sites total** across 3 packages. No CUSIP/FIGI mapping, no symbol-change or corporate-action handling anywhere | `gapscan` §F probe (`cusip|figi|symbol_change|ticker_change|corporate_action`) | Inv-13 provenance; Inv-1 replay | P1 | Unimplemented rather than misplaced. Intraday single-day replay is unaffected; any multi-day series crossing a corporate action is silently wrong |
| G33 | §F.3 — session/halt | Session and halt state has one owner | **165 sites across 9 packages**, concentrated in `kernel` (65) and `ingestion` (52) | `gapscan` §F probe | CORE §F.3; Inv-8 | P1 | Two authorities on whether the market is tradeable. Halt handling is present and works; ownership is what is absent |
| G34 | §F.4 — broker reconciliation | Broker reconciliation is owned by one engine | **23 sites, 14 of them in the kernel** | `gapscan` §F probe; `src/feelies/kernel/orchestrator.py:_reconcile_fills:4229` | CORE §F.4; Inv-8 | P1 | Reconciliation logic lives in the god object alongside everything else it does, and is the path that matters most on a live restart (see G03) |
| G35 | §F.5 — backpressure | Backpressure behaviour is specified at every queue | **4 sites total** (`sensors` 2, `alpha` 1, `ingestion` 1). No queue-depth policy, no drop policy, no overflow handling | `gapscan` §F probe | Inv-11 fail-safe default | P1 | Backtest is synchronous and cannot experience backpressure. Live ingestion has an unbounded queue with no specified behaviour under a burst |
| G36 | §F.6 — exception propagation | Exception propagation is specified; errors resolve to reduced exposure (Inv-11) | **20 fail-quiet except handlers** — neither raise, return, nor log. 6 are bare `ONLY-PASS`; the two on decision paths are G20 and G23 | `gatescan.json:fail_quiet_except_handlers`, by package: ingestion 4, cli 3, composition 3, harness 3, root 2, alpha 2, broker 2, kernel 1 | Inv-11; CORE §J.5 silent degradation | P1 | 18 of 20 are on cold or clearly-benign paths (import fallbacks, `queue.Empty`, CLI parsing). The 2 on decision paths are separately P0 |
| G37 | Axis C — boundaries | Layer boundaries **enforced at runtime**, not only by review (CORE §G "runtime enforced boundaries") | **Zero sites.** No forbidden-read assertion, no boundary-violation check, no runtime guard anywhere in `src/feelies` | `gapscan` probe (`forbidden_read|assert_no_read|boundary_violation`) returns 0 | Inv-8 layer separation | P1 | Enforcement is entirely static: G1 at YAML load (downgradable to a warning) plus `mypy --strict`. Neither can see a cross-layer read performed through an object the type system permits |
| G38 | Axis D — gate registry | Single-source enumeration of every gate (P3 D.6) | **Two independent ladders with no common registry.** G1–G17 are string-keyed method calls in `LayerValidator` (16 implemented, G13 absent); `GateId` is a 7-member enum in `src/feelies/promotion/evidence.py:67`. Runtime gating is **329 call sites across 10 families** | `gapscan.json:gates`; `gatescan.json:family_totals` (regime_gate 56, alpha_load_gate 52, risk_verdict 48, data_health 43, macro_degrade 35, order_admission_block 29, escalation 27, kill_switch 22, lifecycle_quarantine 10, warmup_staleness 7) | Inv-13 auditable; CORE §G enumerable gates | P1 | No operator can enumerate what would block a trade. `GATE_EVIDENCE_REQUIREMENTS` does enforce completeness over `GateId` (`src/feelies/promotion/evidence.py:1720-1731`) — that half is solved |
| G39 | Axis B — construction | Contract-first boundaries; engines receive dependencies through declared interfaces | **45 external attribute assignments** and **10 cross-object private accesses**. `src/feelies/bootstrap.py` sets `orchestrator.config_snapshot`, `.live_feed`, `.ib_connection` after construction, and reaches into `metric_collector._store_raw_events` | `coupling.json`; `src/feelies/bootstrap.py:584,587,588,411,1543` | Inv-3 contract-first boundaries | P1 | Objects are not valid after `__init__`; validity depends on bootstrap completing a sequence nothing checks. Post-hoc private mutation is the strongest form of the coupling |
| G40 | Axis B — orchestrator | No god orchestrator (CORE §J.1) | `Orchestrator` is **5,480 lines, 123 methods (22 public), 104 `__init__` attributes**, and hosts responsibilities of engines 1, 2, 3, 4, 6, 7, 8, 9, 10 and 12 | `gapscan.json:orchestrator` | CORE §J.1; Inv-8 | P1 | This is the aggregate of G11–G14, G15, G21, G22, G24, G27 and G30 and is listed separately because "shrink the orchestrator" is a distinct piece of work from any single extraction |
| G41 | Axis E — total budget | Tick-critical path within a declared per-event budget | **136.2 µs/quote (42.2 µs/event)** measured, against the platform's own declared 10 µs/event — **4.2× over**. At full sensor registration, 103.9 µs/event, breaching even the "acceptable < 100 µs" bound | `perf.json`; `phase4_performance.md:7-19,197-268` | CORE §G measured latency budget | P1 | Measured on the shipped 4-sensor backtest, which is the *best* case the repo can produce. Live has no measurement at all (A4.4) |
| G42 | Engine 2 — scaling | Per-engine budget respected as sensors scale | Engine 2 is **6.1× over its budget share**; each additional sensor costs **+22.6 µs/quote — 70% of the entire per-quote budget for one sensor** | `perf_scale.json`, `perf_sensorscale.json`; `phase4_performance.md:333-346` | CORE §G; Inv-12 stress viability | P1 | Engine 2 alone reaches ~277 µs at full registration. This is the single dominant cost and it grows linearly with the thing the platform is designed to add |
| G43 | Axis E — breach behaviour | A budget breach has a defined, exposure-reducing response (Inv-11) | **There is no budget in the code.** Of 60 latency-comparison sites, every one is event-time causality logic, config sanity (`< 0`), a capital budget, or a connection timeout. `_tick_timings` is written at 3 sites, published as metrics at `src/feelies/kernel/orchestrator.py:2128-2149`, and **never compared to anything** | `gapscan` latency-comparison scan; `src/feelies/kernel/orchestrator.py:1525,1635,1677,1773,2128` | **Inv-11 fail-safe default** | **P0** | A 4.2× overrun (G41) is invisible to the running system in every mode. No degradation, no alert, no shed. See paragraph below |
| G44 | Axis E — dead compute | No compute whose output nothing reads | **~12.8 µs/quote (9.4%) provably unread**: 20 unread event fields of 179, 2 unread metric names of 9, 106 public methods with zero in-src call sites of 564 | `hotpath.json:dead_compute` | CORE §G justified net complexity | P2 | Pure waste, and the lowest-risk item in the table: removing it changes nothing computed, so the parity hash must not move — each item is independently verifiable against the oracle |
| G45 | Axis E — hot-path allow list | Only A1–A8 operations on the tick-critical path (P4.1) | Prohibitions violated with PROVEN per-event occurrences: **per-event dict construction 3, string formatting 3, wall-clock read 3, dynamic dispatch 2, per-event set construction 2**, plus `dataclass_replace` at 5 per-event sites. `regex`, `disk_io`, `serialization`, `deep_copy` and `governance_evaluation` are **clean at 0** | `hotpath.json` prohibition table | CORE §G measured budget; Inv-1 | P2 | Each is a small constant cost, individually addressable. The wall-clock reads overlap G01; the 5 prohibitions at 0 are on the do-not-change list |

---

## P0 gaps — what breaks, when, and what contains it

### G03 — order idempotency does not survive a restart

**What breaks.** `derive_order_id` is a pure function of provenance, so the same
decision re-derives the same `order_id` after a restart. That is correct and
desirable. The defect is that nothing durable records which IDs were *submitted*:
`src/feelies/execution/passive_limit_router.py:183` holds `self._submitted_order_ids` as a
bare `set()` whose comment says "ever submitted" but whose lifetime is the
object's, and `src/feelies/broker/ib/connection.py:353-364` correctly refuses to regress
`_next_valid_id` across a reconnect it can observe, but starts from `None` each
process and rebuilds from the broker handshake. The only `TradeJournal` wired in
the composition root is `InMemoryTradeJournal` (`src/feelies/bootstrap.py:358`), and
`src/feelies/storage/memory_event_log.py:7` states of the only event log that there is "no
persistence — all events are lost on process exit". So a stable ID is a key with
nothing to look it up in.

**Under what conditions.** Live or paper trading, crash or deliberate restart
between an order leaving the router and its ack being processed. On restart the
platform replays to the same decision, derives the same ID, and cannot determine
whether that order is already working at the broker. The direction of the failure
is toward *more* exposure: it re-submits. Whether that becomes a duplicate
position depends on IB's own duplicate-ID handling, which the platform neither
configures nor asserts.

**Containment available.** Backtest is single-process and unaffected. Within one
live process the guarantee holds — the in-memory set is correct for every
duplicate it can see, and `nextValidId` handles broker reconnect without a
process restart. The exposure window is specifically process death mid-flight,
and IB's server-side duplicate-order-ID rejection is an unverified external
backstop (`ASSUMED` — the platform contains no test for it). Inv-11 would require
refusing to submit any order whose ID cannot be proven absent from a durable
record, which makes durability a precondition of trading rather than a feature;
no such refusal exists today.

### G20 — a position-lookup failure is reported to the optimizer as flat

**What breaks.** `src/feelies/composition/engine.py:384-389` builds `current_positions` for
the optimizer and wraps each lookup in `except Exception: current_positions[s] =
0.0`. The optimizer consumes this as the *current* book and computes target minus
current to produce turnover. Reporting flat for a symbol actually held means the
delta is computed from zero, so the engine sizes a fresh entry on top of an
existing position rather than the increment. A lookup failure therefore does not
degrade to inaction; it degrades to approximately doubling the intended position
in that symbol. The handler catches bare `Exception` and is marked `# pragma: no
cover - defensive`, so it is untested by construction and produces no log line —
the run looks normal.

**Under what conditions.** Only on the PORTFOLIO path, and only when
`_position_lookup` is wired (`self._position_lookup is not None`). It requires the
lookup to raise — a missing strategy key, a store not yet populated for a symbol
in `ctx.universe`, or any error inside `get_aggregate`. Because the guard is bare
`Exception` rather than the specific lookup failure, a programming error inside
the position store surfaces as a silent flat rather than a crash.

**Containment available.** Downstream risk checks still bound the result: the
aggregate position limit and `check_sized_intent`'s per-leg veto apply to whatever
the optimizer produces, so the doubled intent is capped rather than unbounded.
No PORTFOLIO alpha is deployed in the shipped configuration, which is why this has
never fired. There is no containment for the *silence* — nothing distinguishes a
genuine flat from a failed lookup, so post-trade forensics cannot attribute the
resulting size either.

### G23 — an unknown strategy id skips the entire per-alpha budget

**What breaks.** `src/feelies/alpha/risk_wrapper.py:186-192` guards the per-alpha budget
block with `if strategy_id:` followed by `self._registry.get(strategy_id)` inside
`try` / `except KeyError: pass`. On a `KeyError` control falls past the whole
`else` branch, so the per-alpha position limit, the drawdown check and the
exposure check are all skipped for that order. The comment states the intent —
"Synthetic and net strategies use aggregate risk checks only" — and for
`__`-prefixed synthetic strategies that is deliberate and correct. The defect is
that the *condition* is registry absence, not synthetic-ness. Any `strategy_id`
missing from the registry for any reason takes the same path: a typo in a config,
an alpha whose registration failed earlier in bootstrap, a manifest renamed
without updating a reference.

**Under what conditions.** Any mode, any order carrying a non-empty
`strategy_id` that the registry does not know. It is a fail-open on a risk
control, which is the exact shape Inv-11 forbids: an unknown state resolving to
*fewer* constraints instead of reduced exposure.

**Containment available.** Real and load-bearing: the aggregate risk checks still
run on every order, so total exposure remains bounded by
`platform_config.max_position_per_symbol` and the portfolio-level limits. The
alpha that escapes its own budget can only grow to the aggregate cap. With A=1 the
per-alpha budget and the aggregate budget are nearly the same number, so today's
blast radius is close to zero. The gap scales with alpha count — at A=10 an
unregistered id can consume the whole book's allowance — and the platform's stated
purpose is multi-alpha, so the containment is a property of the current
deployment rather than of the design.

### G43 — a latency budget breach has no response because no budget exists

**What breaks.** The platform measures per-stage tick latency and then does
nothing with it. `_tick_timings` is populated at `src/feelies/kernel/orchestrator.py:1635`, `:1677`
and `:1773`, read once at `:2128`, and emitted as `MetricEvent`s. A scan of all 60
latency-comparison sites in `src/feelies` finds no site comparing a measured
processing latency against a budget: every hit is event-time causality logic
(staleness windows, session bounds, fill deadlines — all correct and necessary),
config validation against zero, a *capital* budget (`max_drawdown_pct`), or the IB
connection timeout at `src/feelies/broker/ib/connection.py:167`. So the measured 4.2× overrun
in G41 is invisible to the running system, and there is no degraded mode to enter
because there is no threshold to cross. CORE §G's "tested degraded mode" and
Inv-11's requirement that stress resolve toward reduced exposure both have no
implementation on the latency axis.

**Under what conditions.** Any mode, continuously — this is the steady state, not
an edge case. It matters most in live trading during a volume burst, which is
precisely when per-event cost rises (more quotes, more sensor work) and when
falling behind the market means acting on stale prices. The platform will
continue emitting orders derived from increasingly old data with no signal that
anything is wrong.

**Containment available.** Partial and indirect. Nothing detects latency, but
several unrelated controls limit the damage: staleness gating (`stale=True`
suppresses entries, `warmup_staleness` at 7 sites) rejects decisions built on
data that is too old in *event* time, which catches the consequence of falling
behind even though it does not detect the cause; the kill switch remains
manually available; and backtest is unaffected because replay has no wall-clock
deadline — the run simply takes longer. The metrics needed to build the check are
already being recorded and published, so the gap is the absent comparison, not
absent instrumentation.

---

## Do-not-change candidate list — targets already met

These were specified as targets in Phases 1–4 and re-measured as already
satisfied. Each is recorded here rather than as a gap row, and each is a
regression risk during remediation.

**Determinism substrate**

1. **No `uuid` import anywhere in `src/feelies`**; identity is content-derived —
   `make_correlation_id` is `f"{symbol}:{exchange_timestamp_ns}:{sequence}"`,
   `derive_order_id` is `sha256(seed)[:16]` (`src/feelies/core/identifiers.py:9,18`). Only 2
   RNG sites exist, both in `src/feelies/research/cpcv.py` (cold). `VERIFIED`.
2. **Deterministic total order on merge** — `_TYPE_RANK` plus
   `event_merge_sort_key` give a total tie-break. `VERIFIED`.
3. **All 21 event classes are frozen dataclasses**; `contracts.json` reports
   `non-frozen: none`. (The mutable *contents* of 8 of them is G12.)
4. **Exact-type bus dispatch, no subtype dispatch**, and `subscribe_all` has **0
   call sites** — no global-handler fan-in exists in practice.
5. **Money is `Decimal` end to end**, which is what makes P&L reductions
   order-free (Phase 1 determinism budget row 4).
6. **120 parity hash helpers over 177 distinct fields, across 30 determinism test
   modules.** The parity surface that exists is substantial; G05 is about its
   edges.
7. **Ingress duplicate policy is explicit and fail-closed** —
   `src/feelies/ingestion/massive_normalizer.py:777` drops exact duplicates and transitions a
   symbol to `CORRUPTED` on a sequence reused with a different payload, which
   `src/feelies/ingestion/data_integrity.py:58` declares terminal. This is the
   exposure-reducing branch on ambiguous input.
8. **CI runs `tests/determinism/` at `PYTHONHASHSEED: random`**
   (`ci.yml:100-115`), with a comment explaining that a pinned seed cannot catch
   newly introduced hash-order dependence and instructing against re-pinning.
   This is the guard that keeps G08 at P2.
9. **The parity oracle is CI-enforced and cannot pass without replaying** —
   `FEELIES_REQUIRE_BASELINE_CACHE=1` turns a cache-miss skip into a failure
   (`ci.yml:117-139`), with fork-PR skips stated rather than silent.

**Engine and layer structure**

10. **`signals/` is a clean engine-4 package** — three inputs, none of them
    position, P&L or order state (`src/feelies/signals/horizon_engine.py:196-198`).
11. **Zero mode branches inside `execution/` or `broker/`** — the seam itself is
    clean; every one of the 27 branches is outside it (G26).
12. **Both passive fill paths are gated in exchange time**, not wall clock
    (`src/feelies/execution/passive_limit_router.py:377,527`, `execution/moc_fill.py:83,132`).
13. **`src/feelies/composition/cross_sectional.py:75-79` holds the platform's best
    determinism discipline** — every sum is taken over a lex-sorted key list *and*
    accumulated with `math.fsum`, so float accumulation order is fixed regardless
    of dict or set iteration order. The docstring names Inv-5 as the reason.
14. **Engine 3 has a single declared read path** (`src/feelies/bootstrap.py:289`) and two
    parity baselines, and its regime gate is correctly off by default.
15. **The kill switch is read directly on the tick path and returns early**
    (Phase 0 hop 4) — the safety control works; only its event is inert (G28).
16. **`promotion/` is correctly cold and append-only**, and executes nothing per
    event (`hotpath.json:governance_evaluation` = 0 PROVEN, 0 per-event).
17. **`GATE_EVIDENCE_REQUIREMENTS` enforces its own completeness** — a module-level
    assertion fails if any `GateId` member lacks an entry
    (`src/feelies/promotion/evidence.py:1720-1731`). This is the pattern G38 lacks for G1–G17.
18. **The platform is alpha-agnostic except at one point.** Only 3 alpha-id
    literals exist in all of `src/feelies`, one of which is a docstring; the
    single real leak is G25.

**Performance**

19. **Five hot-path prohibitions are clean at zero PROVEN occurrences**: `regex`,
    `disk_io`, `serialization`, `deep_copy` (1 cold site only) and
    `governance_evaluation`. No disk or serialization touches the tick path.
20. **`mypy --strict` is clean on all of `src/feelies` with no `ignore_errors`
    overrides**, acceptance-locked by test.

---

## Completeness check

Every target statement extracted from Phases 1–4 maps to at least one gap row or
to the do-not-change list. Targets that decompose into separately-addressable
differences produce more than one row, which is why row count exceeds target
count in some sections.

| Source | Target statements extracted | Mapped to gap rows | Mapped to do-not-change | Gap rows produced |
|---|---|---|---|---|
| Phase 1 — §1 clock | 1 | 1 | — | G01 |
| Phase 1 — §2 sequencing / tie-break | 2 | 1 | 1 (#2) | G09 |
| Phase 1 — §3 bus semantics | 2 | 1 | 1 (#4) | G02 |
| Phase 1 — §4 identity and idempotency | 2 | 1 | 1 (#1) | G03 |
| Phase 1 — §5 state ownership and reset | 1 | 1 | — | G04 |
| Phase 1 — §6 parity surface (incl. §6.1) | 2 | 2 | 1 (#6) | G05, G29 |
| Phase 1 — §7 config / manifest fingerprint | 1 | 1 | — | G06 |
| Phase 1 — §8 schema versioning (§F.7) | 1 | 1 | — | G07 |
| Phase 1 — determinism budget rows | 4 | 1 | 3 (#5, #8, #9) | G08 |
| Phase 2 — engines 1–12 contract sheets | 12 | 12 | 6 (#10, #12, #13, #14, #15, #16) | G11–G15, G18–G25, G27, G28, G30 |
| Phase 2 — §F.1–§F.6 resolutions | 6 | 6 | — | G31–G36 |
| Phase 3 — Axis B integration (B.1–B.4) | 4 | 3 | 1 (#11) | G39, G40, G10 |
| Phase 3 — Axis C information flow (C.1–C.6) | 6 | 2 | 2 (#3, #7) | G37, G12 |
| Phase 3 — Axis D gating (D.1–D.9) | 9 | 2 | 2 (#17, #18) | G17, G38 |
| Phase 3 — mode seam / parity | 1 | 1 | 1 (#11) | G26 |
| Phase 3 — governance off tick path | 1 | 1 | 1 (#16) | G16 |
| Phase 4 — §1 hot-path allow list | 1 | 1 | 1 (#19) | G45 |
| Phase 4 — §2 per-engine budget | 2 | 2 | — | G41, G42 |
| Phase 4 — §4 sensor scaling | 1 | 1 | — | G42 |
| Phase 4 — §6 budget breach behaviour | 1 | 1 | — | G43 |
| Phase 4 — §7 deletion candidates | 1 | 1 | — | G44 |
| Phase 4 — strict typing acceptance | 1 | — | 1 (#20) | — |
| **Total** | **62** | **43** | **22 cited / 20 distinct** | **45** |

**Reconciliation.** 62 target statements were extracted, and every one maps to at
least one gap row, at least one do-not-change entry, or both. 43 targets map to a
gap row. 21 targets map to a do-not-change entry. 43 + 21 = 64, exceeding 62 by
**2**, which is exactly the number of targets appearing in *both* columns:

- **Phase 3's mode-seam target** is met inside `execution/` and `broker/`
  (do-not-change #11, zero branches) and missed outside them (G26, 27 branches).
- **The governance-off-tick-path target** is met at runtime (do-not-change #16,
  zero per-event governance evaluation) and missed at import time (G16).

The do-not-change column sums to 22 citations over **20 distinct numbered
entries**, because entries #11 and #16 are each cited by two target rows — the
same two overlaps.

45 gap rows arise from 43 targets because engine 5 produces three separately
addressable rows (G16 import coupling, G17 the G13 hole, G18 the cross-engine
quarantine write) and engine 2 produces two (G12 mutable containers, G13 kernel
checkpoint). G42 is cited twice in the last column — once against the per-engine
budget target and once against sensor scaling — but is one row.

**Severity distribution.** P0 = 4 (G03, G20, G23, G43). P1 = 33. P2 = 8
(G01, G08, G09, G13, G16, G29, G44, G45). Total 45.

---

## Documentation disagreements

Recorded, not resolved — code is truth, documentation is a claim.

| Source | Claim | Measured |
|---|---|---|
| `.cursor/rules/platform-invariants.mdc` glossary | "`LayerValidator` calls G1–G17"; "G13 is presently a no-op" | `LayerValidator` calls **16** gates: G1–G12 then G14–G17. **G13 has zero references anywhere in `src/feelies`** — there is no G13 function, no-op or otherwise. "No-op" implies a stub that runs and checks nothing; nothing exists to run. `VERIFIED` |
| `src/feelies/core/events.py:416` | `KillSwitchActivation` is "published on the bus so all layers can react" | Zero subscribers in any mode (G28). The kill switch is nonetheless honoured, because it is read directly rather than via the event. `VERIFIED` |
| `src/feelies/services/regime_state_cache.py:78` docstring | "risk and the sizer call this on every tick" | `RegimeStateCache.latest` measured at **0.001 calls/quote** (Phase 4, re-confirmed) |
| `.cursor/skills/performance-engineering/SKILL.md:93` | Single event processing < 10 µs | **42.2 µs/event** shipped; **103.9 µs/event** at full sensor registration (G41) |
| `.cursor/skills/performance-engineering/SKILL.md:72` | "16 sensors ship in v0.3; 13 registered in the reference `platform.yaml`" | `platform.yaml` declares **15** specs, 13 on `NBBOQuote`; the shipped backtest registers **4** |
| `docs/audits/performance_audit_2026-07-02.md:162` | Metric count per tick | 9 distinct names, 251,500 records — the audit figure does not match |

---

## Assumption register — carried forward unresolved

| ID | Assumption | Why not checkable here | What would decide it |
|---|---|---|---|
| A5.1 | IB rejects a re-submitted duplicate `order_id` server-side, bounding G03's blast radius | Requires a live IB Gateway session and a deliberate duplicate submission; `paper_rth` tests never run in CI | Submit a known-duplicate ID against paper IB and record the rejection |
| A5.2 | The 3 order-insensitive set-iteration sites in G08 remain order-insensitive | Verified by reading the loop bodies today; nothing enforces it | A test that iterates each site's container in reverse and asserts an identical parity hash |
| A5.3 | G20 has never fired in any recorded run | The handler logs nothing, so absence of evidence is not evidence of absence | Add a counter to the handler and replay the corpus — but that is a `src/` change, forbidden this phase |
| A5.4 | The 106 uncalled public methods in G44 are genuinely dead rather than reached by tests, CLI entry points or `getattr` | Static analysis covers `src/` call sites only | Cross-reference against `tests/` and `scripts/`, then delete against the parity oracle |
| A5.5 | Phase 4's 136.2 µs/quote is representative of the live path | Backtest constructs events before the replay loop; live constructs them per message inside it (A4.4) | Instrument the live/paper ingestion path, which no current harness covers |
| A5.6 | G41's 4.2× overrun would be worse at A>1 in proportion to alpha count | Measured with A=1; the engine-4 budget row is sized for growth but not measured under it | A replay with two SIGNAL alphas registered |

---

## Verification performed on this document

- All seven prior measurement scripts re-run; every headline number reproduced.
- 33 of 33 `path:line:symbol` citations re-resolved via `tools/arch/gapscan.py`.
  One apparent drift (`_select_bus_signal` at `:1676`) was diagnosed as a
  citation of the tick-path *call site*, with the definition at `:4831`; both
  resolve, and the script now distinguishes the two kinds.
- Phase 0's `self._positions` 23 / `self._strategy_positions` 13 figures were
  independently re-derived today (36 total) and the counting definition pinned to
  method calls *through* the store rather than bare attribute references — the
  looser definition gives 54.
- All 4 P0 claims read directly in source, not taken from a script or from
  Phase 0.
- Two glossary/docstring claims found to disagree with code; recorded rather than
  resolved.
- **Citation defect found and fixed after first submission.** The first draft
  wrote citations package-relative — *orchestrator.py:4831* and
  *ingestion/massive_normalizer.py:777* — rather than prefixing each with
  `src/feelies/`. `tools/arch/measure.py spotcheck`
  resolves every citation as `ROOT / path` (`tools/arch/measure.py:536`), so
  **45 of 46 failed as "file missing"** and the output was correctly rejected as
  untrusted. The claims themselves had been verified against the right files —
  `tools/arch/gapscan.py` resolves against `src/feelies/` internally — but a
  citation a reader cannot resolve is not evidence. All 36 cited paths were
  normalised to their unique real file. One name was genuinely ambiguous,
  matching both `tools/arch/contracts.py` and
  `src/feelies/broker/ib/contracts.py`, and was disambiguated by hand to the scan
  tool. Illustrative bad paths are written unbracketed here on purpose: inside
  backticks the checker reads them as live citations and fails them, which is how
  this note first reintroduced three failures.
- **All 47 distinct citations now resolve — the full population, not a sample:**
  `spotcheck -n 60` reports `0 failure(s)`, and `-n 20` is clean at seeds 0, 1, 7,
  42, 99, 777 and 12345. Because `spotcheck` validates only that a path exists and
  that a line is within EOF, the 13 citations not already opened during analysis
  were read directly and their content confirmed to match the claim they support —
  which caught one understatement, corrected in do-not-change #13.
- The five earlier phase outputs were spotchecked at `-n 40` and are all clean, so
  the package-relative format was this document's deviation, not the review's
  convention.
- Scope guard run; no writes outside `docs/architecture/target/out/` and
  `tools/arch/`.

---

**HARD STOP** — Phase 5 complete. No remediation proposed, sequenced, or begun.
