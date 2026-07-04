# Kernel Audit — 2026-07-02

Scope: read-only, evidence-based audit of the feelies kernel spine — the
orchestrator (M1–M10 driver, bus subscribers, drains), the micro/macro state
machines, the generic `StateMachine` primitive, the event bus, the
signal→order trace, the per-mode component graph in `bootstrap.py`, and the
process entry shim. Focus is **ordering determinism, sequence/clock
semantics, single-writer discipline, and layer boundaries** (Inv-5/6/7/8/10).
No production code, tests, baselines, configs, or ledgers were changed.

Out of scope (audited elsewhere): internal math of sensors/signals/risk/
composition, and the orchestrator's decision/exit economics (stop/reverse/
flatten/edge-cost gates) — owned by `audit_position_management.md`. One
finding below (§1 item 1) sits at the boundary: its root cause is a
kernel-scope defect (a dropped constructor field in `orchestrator.py`) but
its consequence (stop-exit fill pricing) is exit-economics territory; it is
reported here because it was surfaced by this audit's mandated verification
run and the defect site is in scope.

This is a follow-up to `docs/audits/kernel_audit_2026-06-24.md` (all 9
backlog items from that pass were remediated in the same PR — see its §12).
This pass re-verifies each remediation against current code, audits every
kernel-scope change landed since, and re-runs both mandated verification
suites.

### Verification run

- `uv run pytest tests/kernel/ tests/bus/ tests/core/test_state_machine.py tests/bootstrap/ -q`
  → **358 passed, 5 failed** (363 total; the 06-24 audit's clean baseline was
  348/348). All 5 failures are the *same* root cause — see §1 item 1.
- `uv run pytest tests/causality/test_anti_lookahead.py tests/determinism/ -q`
  → **115 passed** (up from 89 on 06-24; the manifest grew from 12 to 17
  entries plus two new non-manifest determinism modules — see §10).

**No fixes were applied.** Unlike the 06-24 pass (which fixed a
collection-blocking `SyntaxError` under separate authorization), this pass's
instructions are read-only throughout, so the 5 failing tests are reported,
not repaired.

### Severity convention

- **P0** — a nondeterministic ordering on the tick path, a second writer to a
  parity event type, a hidden global, a wall-clock read in core decision
  logic, a causality leak, or a verified currently-failing regression in the
  audit's own mandated test scope with a safety/provenance-relevant blast
  radius.
- **P1** — fragile-but-correct tie-breaks, drain/idle ordering edge cases,
  layer/observability leakage, an enforcement-claim gap (documented rule not
  actually checked by tooling), or a material determinism test hole.
- **P2** — contract clarity, observability of transitions, documentation
  drift, defensive hardening.

Each finding is tagged **implementation bug** / **fragile-but-correct** /
**intentional design**.

---

## 1. Executive summary

- **P0 (implementation bug, live regression) — `_try_build_order_from_intent`
  never stamps `OrderRequest.reason`, silently disabling stop-exit panic-fill
  pricing and breaking Inv-13 trade-journal provenance.**
  `orchestrator.py:4784-4803` constructs the `OrderRequest` used by every
  standalone SIGNAL entry/exit — including `__stop_exit__` — with **no**
  `reason=` keyword; the field defaults to `""`
  (`core/events.py:344`). The five lines immediately above the constructor
  call (`:4798-4801`) are an orphaned comment block — *"Stamp the panic-fill
  reason for forced exits (e.g. `__stop_exit__` → `STOP_EXIT`) so the fill
  model prices the stop with slippage / depleted depth"* — describing a
  `reason=_FORCED_EXIT_PANIC_REASON.get(...)` kwarg that no longer exists.
  `_FORCED_EXIT_PANIC_REASON` (`:318`) is consequently dead: `grep` finds
  **zero** remaining references anywhere in `src/` or `tests/`. Root cause
  traced via `git blame` + `git show`: merge commit `8fd8fc3` ("Merge branch
  'main'…", parents `4a90cd8` + `ba8430b`, 2026-06-25 15:52) dropped **both**
  candidate forms of the kwarg during conflict resolution (`_FORCED_EXIT_
  PANIC_REASON.get(...)` and the equivalent local-variable form), whereas the
  *immediately preceding* commit on this exact line, `1f0c1c0`
  ("fix(kernel): drop duplicate reason= kwarg…", by a prior Claude Code
  session), had correctly resolved an earlier duplicate-kwarg `SyntaxError`
  by keeping exactly one form. This is a second, silent recurrence of the
  same merge-conflict hotspot the 06-24 audit's verification run caught as a
  hard failure — this time it doesn't crash, it just quietly mis-prices.
  Verified failing on this audit's mandated run:
  `TestForcedExitReasonClassification::test_only_stop_exit_intent_is_tagged_as_panic`
  (`tests/kernel/test_orchestrator.py:1206`),
  `::test_stop_trigger_tags_order_and_journals_reason` (`:1233`),
  `TestForcedExitPanicReason::test_stop_exit_order_carries_stop_exit_reason`
  (`:3307`), `::test_stop_exit_fill_pays_panic_slippage_end_to_end` (`:3355`),
  `TestTradeJournalProvenance::test_stop_exit_fill_records_reason_in_journal_metadata`
  (`:3408`). **Does not break Inv-5**: `reason=""` is produced identically on
  every replay, so no locked parity hash is affected (confirmed: the
  determinism/causality suite is 115/115 green). It breaks Inv-13
  (`TradeRecord.metadata`/fill-model realism), and — because this audit's own
  mandated verification command surfaces it directly in kernel-scope code —
  it is reported here at P0 rather than deferred silently. See §10, §12 #1.
- **P1 (enforcement-claim gap, not a new hazard) — `time.time()` at
  `bootstrap.py:2298` is invisible to the CI rule that supposedly bans it.**
  `_enforce_factor_loadings_freshness` falls back to raw `time.time()` when
  `config.session_open_ns` is unset and a `factor_loadings_dir` is
  configured (`:2295-2304`); the function's own docstring already flags this
  as breaking bit-identical replay and the runtime path logs a `WARNING`
  when it fires. CLAUDE.md states *"DTZ rule: never use `datetime.now()` /
  `datetime.utcnow()` / `time.time()` in production code… enforced by ruff
  CI"*. `pyproject.toml:114,122` enables only `DTZ005`/`DTZ006`/`DTZ011`
  (specific `datetime.*` misuse rules) — flake8-datetimez has **no rule for
  the `time` module at all**, so this call cannot be caught by ruff
  regardless of configuration. Blast radius is narrow (opt-in gate, boot-time
  only, gated behind an operator omission of `session_open_ns`) and the code
  is self-aware, but the documented enforcement guarantee does not hold for
  this half of the rule. See §7, §12 #2.
- **Clean — every one of the 06-24 audit's 9 backlog items was re-verified
  against current code and holds**, with no regressions in the
  ordering/determinism domain: `_distribute_fill_to_strategies` still
  `sorted(strategy_ids())` (`:5905`, with an explicit Inv-5 comment); the
  Signal echo now only re-publishes synthetic forced-exit signals
  (`:2500-2501`); the hazard `OrderRequest` bridge imports the shared
  `HAZARD_EXIT_SOURCE_LAYER`/`HAZARD_EXIT_REASONS` constants from
  `risk/hazard_exit.py` instead of re-declaring them (`orchestrator.py:162,
  6279-6281`); bus-subscription order is now pinned by
  `tests/bootstrap/test_bus_subscription_order.py`; the dedicated
  `_regime_seq`/`_position_seq` split was evaluated and deliberately declined
  (shared `_seq` retained, StateTransition stream now itself parity-hashed —
  see below). See §2.
- **Clean, substantial coverage growth — the parity-hash suite grew from 12
  to 17 manifest-locked baselines plus two new non-manifest determinism
  modules since 06-24**, closing essentially every "missing" cell in the
  06-24 test-gap matrix: `test_orchestrator_replay.py` is the **first**
  determinism test to instantiate the full `Orchestrator` (closing "no
  parity hash exercises the orchestrator"); `test_state_transition_replay.py`
  pins the shared-`_seq` `StateTransition` interleave across two real SMs;
  `test_position_pnl_replay.py` closes the PnL clause of Inv-5;
  `test_cross_sectional_context_replay.py` drives the real
  `UniverseSynchronizer` (previously only hand-built contexts were hashed);
  `test_signal_fires_replay.py` and `test_multi_symbol_sensor_replay.py`
  replace two previously-vacuous empty-stream baselines with real, non-empty
  ones. See §10, §11.
- **Clean, and a materially better fix than the 06-24 remediation attempted
  — `test_hash_seed_independence.py` proves `PYTHONHASHSEED`-independence
  directly.** The 06-24 audit's remediation #3 (an `os.execv` re-exec pin)
  was rejected because it corrupted pytest's output capture, leaving only a
  `conftest.py` warning (unenforced). This pass instead re-runs four
  dict/set-iterating replays in **subprocesses** under three different
  `PYTHONHASHSEED` values and asserts identical hashes — a strictly stronger
  guarantee than pinning to `0`, since it proves the code doesn't depend on
  the seed at all rather than merely fixing one lucky value. It covers
  `regime`, `intent_off`, `intent_on`, `snapshot` — not yet the five newest
  manifest baselines or the orchestrator-replay streams (P2 follow-up, §10).
- **Clean (intentional design, self-documented, not new to this pass) — the
  regime-calibration prefix has an acknowledged "soft Inv-6 wrinkle."**
  `_calibrate_regime_engine` (`:3337-3479`) fits emission parameters once
  from a causal prefix, then the live run re-replays that same prefix, so
  early-prefix posteriors use emission moments estimated from later
  (still-prefix-bounded) ticks. The docstring itself labels this "Audit
  P2-4" and argues it preserves Inv-5 (pure deterministic function of the
  prefix) while being a narrow, documented Inv-6 nuance confined to warm-up.
  Carried forward for visibility since it wasn't called out in the 06-24
  report's findings list.
- **Clean — new forensic-provenance instance state is causally sound and
  parity-inert.** `_last_signal_mechanism` (`:773-780`) and `_regime_label_for`
  (`:5859-5878`), added since 06-24, stamp `TrendMechanism` /
  `expected_half_life_seconds` / a regime-state label onto each
  `TradeRecord`. Both are pure functions of already-published, ≤-current-time
  data (the mechanism side table is written from `_on_bus_signal`,
  `:6084-6091`; the regime label reads `RegimeEngine.current_state`, which for
  a resting-order fill reconciled at tick-start is necessarily the *prior*
  tick's M2 output, since `_reconcile_resting_fills` runs before
  `_update_regime` in `_process_tick_inner` — no lookahead). Neither is read
  on the order/intent decision path, and neither touches a locked parity
  stream (`TradeRecord` is not one of the 17). See §6.
- **Clean — the P0-1 gate-threshold-floor wiring (`platform_gate_threshold_
  overrides`, `bootstrap.py:332-334`) is deterministic, boot-time-only
  config plumbing** with direct test coverage
  (`tests/bootstrap/test_gate_thresholds_wiring.py::test_pinned_fields_
  propagate_as_floors` and `::test_per_alpha_loosening_below_platform_floor_
  refused_at_boot`, both added since 06-24). No ordering or per-tick
  implications.
- **Clean — `config.snapshot(ts_ns=clock.now_ns())` (`bootstrap.py:741`)
  tightens Inv-10 at the bootstrap edge.** Previously an implicit
  `WallClock()` fallback inside `PlatformConfig.snapshot()`; now the
  injected clock is threaded through explicitly. `platform_config.py:973-994`
  confirms `timestamp_ns` was never folded into the snapshot `checksum`, so
  this was a hygiene improvement, not a fix for a live Inv-5 defect.
- **Clean — the lazy `paper_backend` import (`bootstrap.py:1063-1067`) is
  packaging-only.** Deferring `from feelies.execution.paper_backend import
  build_paper_backend` into the PAPER branch of `_create_backend` keeps
  BACKTEST-only entry points free of the optional `ibapi` dependency; it
  does not change BACKTEST's component graph, construction order, or the
  mock-patch surface beyond updating the patch target
  (`tests/bootstrap/test_paper_branch.py`, correctly updated to patch
  `feelies.execution.paper_backend.build_paper_backend`).
- **Clean — construction-order determinism holds end to end, re-verified
  independent of the 06-24 pass.** Alpha discovery is explicitly
  `sorted(spec_dir.rglob("*.alpha.yaml"))` (`alpha/discovery.py:28-42`,
  docstring: *"sorted alphabetically for deterministic load order"*);
  `AlphaRegistry.signal_alphas()` / `.portfolio_alphas()` preserve
  registration order over an insertion-ordered `dict`
  (`alpha/registry.py:250-262,278`, docstring: *"Inv-C"*); every
  `set`/`frozenset` built in `bootstrap.py`'s composition functions is either
  membership-only or explicitly `sorted(...)` before being consumed for
  order-sensitive output (`_create_composition_layer:2049`,
  `_create_hazard_exit_controller:2130,2146`).
- **Clean — single-writer discipline re-verified platform-wide**, not just
  within `orchestrator.py`: a repo-wide `bus.publish(...)` grep confirms
  exactly one component publishes each of `RegimeState`, `RegimeHazardSpike`,
  `PositionUpdate`, `SizedPositionIntent`, `CrossSectionalContext`,
  `HorizonTick`, `SensorReading`, `HorizonFeatureSnapshot`, `Signal(layer=
  SIGNAL)`, and `StateTransition`; `OrderRequest` remains partitioned by
  `(reason, source_layer)` between the orchestrator's own paths and
  `HazardExitController` (whose sole `self._bus.publish(order)` call is at
  `risk/hazard_exit.py:308`). See §6.
- **P2 (documentation drift) — `.cursor/skills/testing-validation/SKILL.md`'s
  "Locked Parity Hashes" table still shows the pre-06-24-remediation 11
  entries.** It has not been updated for the 5 baselines added to
  `LOCKED_PARITY_BASELINES` since (`market_fill_acks` was already present
  but uncounted in the "eleven" framing; `position_pnl`, `state_transition`,
  `cross_sectional_context`, `signal_fires`, `multi_symbol_sensor_reading`
  are new) nor for `test_orchestrator_replay.py` /
  `test_hash_seed_independence.py`. The skill's own header defers to
  `tests/determinism/parity_manifest.py` as canonical, and
  `test_parity_manifest.py` cross-checks the manifest against its importing
  test modules — so the code stays self-consistent — but a reader of the
  skill alone would materially undercount coverage.
- **P2 (contract clarity, unchanged since 06-24, re-confirmed) — the
  micro-stage map's "single order/tick" note is a simplification for
  REVERSE.** `_execute_reverse` (`:4286-4674`) submits an EXIT leg then an
  ENTRY leg from the same tick, both drawing sequence numbers from the same
  monotonic `_seq` in a fixed exit-then-entry order
  (`seq_exit` at `:4313` always allocated before `seq_entry` at `:4478`) —
  deterministic, but two `OrderRequest`s, not one.
- **Clean — bootstrap mode-parity re-confirmed with no new mode-conditional
  branch found in the core decision graph.** BACKTEST/PAPER divergence
  remains confined to clock selection, `ExecutionBackend`, the normalizer,
  ingest order-guard strictness, and observability flags (§9) — none newly
  introduced since 06-24.

---

## 2. Remediation-status check (06-24 backlog → current)

| # | 06-24 finding | Current status | Evidence |
|---|---|---|---|
| 1 | P0: `_distribute_fill_to_strategies` frozenset iteration | **Holds** | `orchestrator.py:5901-5905`: explicit `sorted(self._strategy_positions.strategy_ids())` with an Inv-5 comment |
| 2 | P1: no orchestrator-level parity hash | **Holds, expanded** | `tests/determinism/test_orchestrator_replay.py` (new); see §1, §10 for its self-documented empty-stream caveat |
| 3 | P1: `PYTHONHASHSEED` claimed but unenforced | **Holds, superseded by a stronger fix** | `conftest.py` warning retained; `tests/determinism/test_hash_seed_independence.py` (new) proves seed-independence directly |
| 4 | P1: Signal published twice (echo) | **Holds** | `orchestrator.py:2493-2501`: re-publish gated to `strategy_id in _FORCED_MARKET_EXIT_STRATEGIES` only |
| 5 | P1: `OrderRequest` hazard filter not centralized | **Holds** | `orchestrator.py:162` imports `HAZARD_EXIT_REASONS, HAZARD_EXIT_SOURCE_LAYER` from `risk/hazard_exit.py`; `:6279-6281` uses them directly |
| 6 | P1: bus subscription order untested | **Holds** | `tests/bootstrap/test_bus_subscription_order.py` exists and is in the passing 358 |
| 7 | P1/P2: shared `_seq` coupling (RegimeState/PositionUpdate) | **Holds — declined by design, now itself parity-hashed** | `orchestrator.py:3513,5554,5748,5987` still draw from the shared `_seq`; `test_state_transition_replay.py` locks a multi-SM shared-sequence stream, so a future interleaving regression on this exact hazard now has a hash guard |
| 8 | P2: `SENSOR_UPDATE` one-way-door contract undocumented as a hard invariant | **Holds, unchanged** | `kernel/micro.py:120`: `MicroState.SENSOR_UPDATE: frozenset({MicroState.HORIZON_CHECK})`; `_dispatch_sensor_layer` (`:1912-1925`) always advances both transitions in the same call |
| 9 | P2: `_FORCED_EXIT_PANIC_REASON` module-level mutable dict | **Overtaken by events — now orphaned, not just mutable** | See §1 item 1: the dict's sole consumer was deleted by a later merge; the dict itself is dead code (0 references) rather than merely un-wrapped in `MappingProxyType` |

No prior finding regressed in the sense of "the same nondeterminism
reappeared." Item 9 evolved from a style nit into a symptom of the item-1
regression (the dict is now unused *because* its caller was deleted, not
because anyone acted on the 06-24 P2 recommendation).

---

## 3. Micro-stage map

Unchanged in structure from 06-24 (re-verified against current line numbers;
no stage was added, removed, or reordered since). `Orchestrator.
_process_tick_inner` (`orchestrator.py:2236`) remains the single per-tick
driver; it never inspects `backend.mode`.

| Stage (MicroState) | Writer / action | Inputs | Output event(s) | Ordering guarantee |
|---|---|---|---|---|
| M1 `MARKET_EVENT_RECEIVED` | orchestrator | `NBBOQuote` from feed | log append + `bus.publish(quote)` (`:2337`) | feed yields one quote at a time; synchronous |
| (router drain) | `_reconcile_resting_fills` → `_drain_async_fills` (`:2393`) | router pending acks | `OrderAck`, `PositionUpdate` | preserves `poll_acks()` list order (`:5066-5071`); **runs before M2**, so a fill reconciled here reads the *prior* tick's regime state (§7) |
| M2 `STATE_UPDATE` | `_update_regime` (**sole writer**) (`:2401,3480`) | quote + RegimeEngine | `RegimeState` (`:3534`), maybe `RegimeHazardSpike` (`:3584`) | `max()` tie-break lowest index (`:3491`); shared `_seq` / dedicated `_hazard_seq` |
| `SENSOR_UPDATE` | sensors via bus subscription (`:2410`) | quote | `SensorReading` (sensor layer) | `SensorRegistry` order; `_sensor_seq` |
| `HORIZON_CHECK`/`HORIZON_AGGREGATE` | scheduler+aggregator via bus (`:1927-1945`) | quote ts | `HorizonTick`, `HorizonFeatureSnapshot` | ticks ascending horizon (§7.4); `_horizon_seq`/`_snapshot_seq` |
| `SIGNAL_GATE` | `HorizonSignalEngine` via bus (`:1957-1965`) | snapshot+regime | `Signal(layer=SIGNAL)` | engine order; `_signal_seq` |
| `CROSS_SECTIONAL` | synchronizer→composition via bus; bookend (`:2411`) | signals+tick | `CrossSectionalContext`, `SizedPositionIntent` | synchronizer sorts `(boundary_ts,alpha_id,horizon)`; buffered into `_pending_sized_intents` |
| (PORTFOLIO flush) | `_flush_pending_sized_intents` (`:2412,1992`) | buffered intents | per-leg `OrderRequest`, `OrderAck`, `PositionUpdate` | FIFO `deque.popleft` (`:2002`); legs lex-sorted by risk engine |
| M3 `FEATURE_COMPUTE` | orchestrator (empty body) (`:2422`) | — | — | bookkeeping only (legacy hook) |
| M4 `SIGNAL_EVALUATE` | `_select_bus_signal` (`:2456,6143`) | `_signal_buffer` (list) | `bus.publish(signal)` only for synthetic forced-exit signals (`:2500-2501`) | arbitrator over ordered list; ties = buffer order |
| M5 `RISK_CHECK` | `risk_engine.check_signal` (`:2607`) | signal+positions | `RiskVerdict` | engine-owned sequence |
| M6 `ORDER_DECISION` | `_try_build_order_from_intent` + `check_order` (`:2779,2806`) | intent+verdict | `OrderRequest`, `RiskVerdict` | one order/tick on this path, **two** for REVERSE (§1, §4) |
| M7 `ORDER_SUBMIT` | `order_router.submit` + `bus.publish(order)` (`:2996,3028`) | order | `OrderRequest` | shared `_seq` / `derive_order_id` |
| M8 `ORDER_ACK` | `_poll_order_router_acks({order_id})` (`:3047`) | router | `OrderAck` | set used for membership only; list order preserved (`:5066-5084`) |
| M9 `POSITION_UPDATE` | `_reconcile_fills(acks)` (**sole writer**) (`:3058,5511`) | acks | `PositionUpdate`; also writes `TradeRecord` (forensic, non-parity) | iterates `acks` list in order; shared `_seq` |
| M10 `LOG_AND_METRICS` | `_finalize_tick` (`:3066,3070`) | timings | `MetricEvent` | `_tick_timings` insertion order (`:3095`); shared `_seq` |

Loop-backs: `LOG_AND_METRICS → {WAITING, RISK_CHECK, FEATURE_COMPUTE}`
(`micro.py:210-216`) support the PORTFOLIO multi-intent flush and resuming M3
after the flush — unchanged.

---

## 4. Ordering-determinism audit (Inv-5)

### 4.1 Iteration over collections on the tick path

Re-enumerated independently of the 06-24 list. All iterations on M1–M10 are
over deterministically-ordered structures:

- `self._signal_buffer` — `list`, fresh/stale partition preserves order
  (`:2261-2288`). Deterministic.
- `self._pending_sized_intents` — `deque`, FIFO `popleft` (`:2002`).
  Deterministic.
- `self._deferred_router_acks` / `acks` — `list`, prepended and iterated in
  order (`:5067-5084,5206`). Deterministic.
- `self._active_orders.items()`/`.values()` — `dict`, insertion-ordered
  (verified at every call site: `:1746,1759,4953,5010,5026,5039,5044,5972`).
  Deterministic.
- `strategy_ids = sorted(self._strategy_positions.strategy_ids())`
  (`:5905`) — the one prior P0, confirmed fixed and confirmed to be the
  **only** call site of `strategy_ids()` in the file (grep: single hit).
- `_emergency_flatten_all`: `for symbol in sorted(positions):` (`:3696`),
  explicitly commented *"so the emitted OrderRequest stream is bit-identical
  across replays even when the position store's insertion order differs
  (Inv-5)"*. The trailing `residual = {sym: p.quantity for sym, p in
  self._positions.all_positions().items() if ...}` (`:3770-3774`) iterates
  the position-store dict in whatever order it returns, but only to build an
  `Alert` message string — not a parity-hashed field, and not order-sensitive
  content (a dict, not a list).
- `_execute_reverse`: exit leg always constructed (and its `_seq.next()`
  drawn) before the entry leg (`:4313` vs `:4478`); both submitted
  sequentially (`:4573-4626`). Deterministic, see §1/§12 note on the
  micro-map annotation.
- Membership-only sets (never iterated for ordered output): `_net_shadow_
  transient_keys`, `_signal_order_trace_seen_sequences`, `_carryover_
  signal_sequences`, `_halted_symbols`, `_ssr_active`, `_alpha_symbols_with_
  fills`, `_hazard_submitted_order_ids`, `_consumed_by_portfolio_ids`
  (frozenset, `:6116`), and the `{s.upper() for s in ...}` /
  `set(trade.conditions) & self._ssr_codes` boolean-membership sets in
  `_data_health_blocks_trading` (`:6604-6609`) and `_update_ssr_state`
  (`:6471`). Deterministic in effect.
- `_poll_order_router_acks`: `expected_order_ids` is a `set`, used only for
  `in` membership; `matched`/`deferred` order comes from iterating the
  `all_acks` **list** (`:5078-5083`). Deterministic. (Re-verified at all
  three call-site shapes: single order `{order.order_id}`, PORTFOLIO batch
  `{o.order_id for o in orders}`, REVERSE's two-element set.)

**No new set/dict-iteration-order dependency was found on the tick path.**

### 4.2 Sequence and correlation-ID allocation

Unchanged from 06-24 and re-confirmed: `SequenceGenerator.next()` is a
lock-guarded monotonic counter (`core/identifiers.py`); on the synchronous
single-threaded bus, allocation order is imperative code order, a pure
function of the log. The six per-family generators (`_seq`, `_sensor_seq`,
`_horizon_seq`, `_snapshot_seq`, `_signal_seq`, `_hazard_seq`,
`orchestrator.py:628,656-667`) remain distinct per-instance objects, still
asserted by `tests/determinism/test_legacy_sequence_isolation.py` (in the
passing 115). RegimeState/PositionUpdate/StateTransition/MetricEvent remain
on the shared `_seq` — the 06-24 "declined, won't-fix" decision on splitting
it — but that interleaving is now itself locked by
`test_state_transition_replay.py` (closes part of the 06-24 §9 coupling
gap; see §10).

### 4.3 Bus delivery order

Unchanged: `EventBus._handlers` is a `defaultdict(list)`; `publish` calls
type-specific handlers in registration order, then global handlers in
registration order (`bus/event_bus.py:36,59-68`). No superclass dispatch, no
reordering. The canonical construction order is documented in
`bootstrap.py`'s module docstring (`:11-45`) and re-affirmed at each layer's
construction site (`:502-511,583-589,603-616`); `tests/bootstrap/
test_bus_subscription_order.py` (new since 06-24) now pins it mechanically
rather than by inspection alone.

### 4.4 Drain / flush order

Unchanged: signal buffer cleared/partitioned at tick start (`:2261-2288`);
`_pending_sized_intents` FIFO-drained in `_flush_pending_sized_intents`
(`:2001`); `_deferred_router_acks` prepended and re-consumed in order
(`:5067-5069`). All deterministic.

---

## 5. Micro-SM audit (transitions vs §7.3)

`_MICRO_TRANSITIONS` (`kernel/micro.py:100-217`) and `_MACRO_TRANSITIONS`
(`kernel/macro.py:42-108`) are **byte-identical in structure** to the 06-24
audit's citations — no state, edge, or guard was added, removed, or
reordered. Re-verified findings:

- **Stage advancement is correct and cannot skip illegally** —
  `StateMachine.transition` raises `IllegalTransition` for any edge not in
  the table (`core/state_machine.py:159-160`); construction validates enum
  completeness (`:90-101`). `test_state_transition_replay.py` now
  additionally proves, via a hash, that a real two-SM run's edge sequence
  hasn't drifted from a pinned baseline (new since 06-24).
- **The micro SM remains descriptive, not prescriptive (P2, fragile-but-
  correct, unchanged).** Sensors/signal-engine/composition run as bus
  subscribers during `bus.publish(quote)` / `bus.publish(tick)`; the
  `SENSOR_UPDATE`/`HORIZON_*`/`SIGNAL_GATE`/`CROSS_SECTIONAL` transitions are
  recorded after the work already ran (`:1912-1965`, comment: *"this
  transition is the authoritative record … sensors already ran"*).
- **`SENSOR_UPDATE` remains a one-way door (P2, unchanged).**
  `_MICRO_TRANSITIONS[SENSOR_UPDATE] = {HORIZON_CHECK}` (`micro.py:120`);
  safe only because `_dispatch_sensor_layer` always performs both
  transitions unconditionally in the same call (`:1915-1925`).
- **HorizonScheduler boundary math (§7.4) — pure integer, anchored.**
  Confirmed unchanged against the spec and
  `tests/determinism/test_horizon_tick_replay.py`.
- **UniverseSynchronizer barrier (§7.5).** Now additionally locked by
  `test_cross_sectional_context_replay.py` against a real synchronizer
  instance (previously only inferred from the glossary's prose claim — see
  §10).
- **Macro SM.** `BACKTEST_MODE` still has no edge to `RISK_LOCKDOWN`
  (`macro.py:74-79`); `SHUTDOWN` remains terminal (`:107`). Unchanged,
  consistent with the spec.
- **REVERSE's two-order submission is a real, minor gap in the map's
  "single order/tick" phrasing** (§1, §3) — not a legality issue (both
  orders walk legal M6→M10 edges sequentially, `:4550-4674`), just a
  documentation precision note carried into §12 as P2.

---

## 6. Single-writer & layer-separation audit (Inv-7, Inv-8)

### 6.1 Writer-per-event-type inventory (repo-wide, not just orchestrator.py)

| Event | Publisher(s) (`bus.publish` call sites) | Single writer? |
|---|---|---|
| `RegimeState` | `orchestrator.py:3534` (`_update_regime`) | **Yes** |
| `RegimeHazardSpike` | `orchestrator.py:3584` (`_maybe_publish_hazard_spike`); `services/regime_hazard_detector.py:245` returns a value object, does not itself touch a bus | **Yes** to the bus |
| `HorizonTick` | `sensors/horizon_scheduler.py:313` (constructed); published via `orchestrator.py:1887,1932` (the scheduler has no bus reference — orchestrator publishes what it returns) | **Yes** |
| `SensorReading` | `sensors/registry.py:339` | **Yes** |
| `HorizonFeatureSnapshot` | `features/aggregator.py:460` | **Yes** |
| `CrossSectionalContext` | `composition/synchronizer.py:396` | **Yes** |
| `SizedPositionIntent` | `composition/engine.py:334` (two constructor sites at `:314,504` both funnel through this one publish) | **Yes** |
| `PositionUpdate` | `orchestrator.py:5550,5744` (`_reconcile_fills`, both branches) | **Yes** |
| `Signal(layer=SIGNAL)` | `signals/horizon_engine.py:614` (sole `bus.publish` in the file) | **Yes** |
| `Signal` (synthetic forced-exit) | `orchestrator.py:2501` (only `strategy_id ∈ {__stop_exit__, __session_flat__}`, which `HorizonSignalEngine` never produces — disjoint namespaces) | **Yes**, disjoint from the above |
| `OrderRequest` | orchestrator (M7 main path `:3028`; PORTFOLIO leg fan-out `:2090,2144`; REVERSE exit+entry `:4600,4626`; emergency flatten `:3736`; working-exit fallback `:5297`) **+** `risk/hazard_exit.py:308` (`HazardExitController`) | **Partitioned** by `(reason, source_layer)` — orchestrator's own paths never emit `source_layer="RISK"` + `reason ∈ {HAZARD_SPIKE, HARD_EXIT_AGE}` |
| `StateTransition` | `orchestrator.py:5983` (`_emit_state_transition`) — the **sole** `on_transition` callback registered on every one of the 6 `StateMachine` instances in the codebase (macro, micro, risk escalation, per-order, alpha-lifecycle uses its own `_record_to_ledger`, normalizer uses `_dispatch_transition` — verified by `grep -rn "\.on_transition("`, 6 total call sites, one callback each) | **Yes**, for kernel-owned SMs |

No second writer was found for any parity-relevant event type. This extends
the 06-24 table (which was scoped to `orchestrator.py`) to a repo-wide
`bus.publish(...)` grep, independently confirming the same conclusion.

### 6.2 Hidden global state

None on the tick path, unchanged from 06-24. All mutable state remains
instance state (`self._…`). The new `_last_signal_mechanism` dict
(`:773-780`) is instance state, not module/global, and is written from
exactly one method (`_on_bus_signal:6084-6091`) and read from exactly one
(`_reconcile_fills:5817-5820`) — a private per-instance side table, not a
second writer of any bus event. `_FORCED_EXIT_PANIC_REASON` (`:318`) remains
a module-level `dict`, now provably dead code rather than merely read-only
(§1, §2 item 9).

### 6.3 `StateMachine.transition` multi-callback caveat (new docstring, no behavior change)

`core/state_machine.py:144-157` gained a docstring paragraph clarifying that
if `on_transition` has *multiple* registered callbacks and callback N raises,
callbacks 1..N-1's **external** side effects are not rolled back — only this
machine's own state/history. Verified this describes a latent property, not
a new risk: every `StateMachine` instance in the codebase registers exactly
one callback (§6.1 table), so the multi-callback scenario the docstring
warns about does not currently occur anywhere. Pure documentation
improvement (**intentional design**).

### 6.4 Cross-layer leakage

Unchanged from 06-24: the orchestrator consumes typed events off the bus;
the only direct reaches into another layer's object are duck-typed capability
probes on injected protocols (`getattr(self._risk_engine, "refresh_high_
water_mark"/"record_fill", None)` at `:2365,5684`; `getattr(self._regime_
engine, "discriminability_for_symbol", None)` at `:3503`; the new
`_regime_label_for` at `:5868-5877` reads `RegimeEngine.current_state`/
`.state_names`, both public accessors on the same injected protocol, not an
internal reach). Acceptable, consistent with existing pattern.

---

## 7. Clock & causality audit (Inv-6, Inv-10)

- **Clock discipline in the kernel — clean, re-confirmed.** `grep` for
  `datetime.now|time.time()|utcnow|perf_counter` in `src/feelies/kernel/`
  returns only `time.perf_counter_ns()` at 8 call sites
  (`:2241,2455,2457,2606,2608,3072,5205,5219`), all latency deltas feeding
  `_tick_timings` / `PaperSessionRecorder`, neither a parity-hashed stream.
  `signal_order_trace.py:43` uses `datetime.fromtimestamp` to render an
  already-known ns value as an ET string (observability), not a wall-clock
  read. `bootstrap.py`'s `_derive_session_id` (`:1096-1118`) does the same
  (renders `config.session_open_ns`, a config field, not `now()`).
- **One real gap found outside `kernel/` but inside this audit's `bootstrap.py`
  ownership: `time.time()` at `bootstrap.py:2298`** (§1 item 2). Distinguish
  clearly from the kernel/`orchestrator.py` `perf_counter_ns()` calls above:
  this one can change a **boot-time pass/fail decision**
  (`StaleFactorLoadingsError`), not just a telemetry value — the same config
  snapshot + data could raise on one day and not another if `session_open_ns`
  is left unset with `factor_loadings_dir` configured. It cannot affect an
  event-stream hash (a failed boot produces no stream), but it is a genuine
  reproducibility hazard for the "backtest reproducibility log" contract
  (testing-validation skill: *"check out … set seeds, run … all eleven
  parity hashes must match"* presumes the run **starts**).
- **`_ensure_session_open_ns_for_live_modes`'s wall-clock anchor
  (`bootstrap.py:793-819`) is gated correctly.** It only fires for PAPER/LIVE
  (`if config.mode == OperatingMode.BACKTEST: return config`, `:806-807`);
  BACKTEST is untouched, and PAPER/LIVE already run on `WallClock` by
  design, so this is not a new Inv-10 surface — consistent with H10's
  existing guard in `_create_sensor_layer` (`:1633-1647`) that hard-refuses
  to boot a non-BACKTEST deployment with unset `session_open_ns` when
  sensors/horizons are configured.
- **Causality on the traced path — clean, re-confirmed.** Traced one quote
  M1→M10 again independent of 06-24: the router drain (fills from prior-tick
  resting orders) runs *before* `_update_regime` in the same
  `_process_tick_inner` call (`:2393` vs `:2401`), so a fill reconciled at
  drain time and any `_regime_label_for` call it triggers reads the
  *previous* tick's regime posterior — never this tick's not-yet-computed
  one, never a future value. Sensors/aggregator/signal-engine consume only
  events already published at ≤ this quote's timestamp. `HorizonTick`
  carries the boundary's theoretical timestamp, not the triggering event's
  (§7.4), so a late trigger cannot leak a future timestamp.
- **`_calibrate_regime_engine`'s documented prefix-refit nuance** — see §1;
  carried forward for visibility, unchanged mechanism, not attributable to
  this window.
- **Coverage.** `tests/causality/test_anti_lookahead.py` (12 tests, in the
  passing 115) is unchanged in scope from 06-24 — still exercises component
  seams, not the full orchestrator. `test_orchestrator_replay.py`'s
  two-replay test (new) would catch an in-process nondeterminism leak but is
  not itself a causality (lookahead) test.

---

## 8. Shutdown/drain/idle audit

Unchanged in mechanism from 06-24; one additive step confirmed benign:

- **Shutdown (`:1710-1785`).** Order: `expire_pending_moc()` (new BT-8
  best-effort MOC cleanup, duck-typed via `getattr`, `:1735-1741`) →
  final `_drain_async_fills("shutdown")` (`:1742`) → checkpoint feature/
  regime snapshot (`:1743`) → resolve `CANCEL_REQUESTED → CANCELLED` over
  `list(_active_orders.items())` (insertion order, `:1746`) → prune →
  pending-orders `Alert` if any non-terminal remain (`:1757-1777`) → macro
  `SHUTDOWN` → `metrics.flush()`. `expire_pending_moc` is a duck-typed
  best-effort call with no return value consumed and no bus publish of its
  own visible from this call site — it does not introduce new ordering
  surface.
- **Idle tick (`:1812-1817`).** Unchanged: `_run_pipeline` dispatches
  `IdleTick` to `_drain_async_fills` only — no micro-SM transition, no
  `bus.publish`, no `EventLog` append. BACKTEST feeds never emit `IdleTick`.
- **Tick-failure recovery (`:2180-2234`).** Unchanged: micro `reset()` to M0,
  `_pending_sized_intents.clear()`, `MetricEvent`, then macro→`DEGRADED`;
  `_pipeline_abort_requested` fail-safe on a vetoed `DEGRADED` transition.
- **Checkpoint/restore (`:6784-6854`).** Unchanged: best-effort, regime-
  engine-only (the legacy per-tick feature-engine snapshot path was already
  deleted pre-06-24); failures never block boot or shutdown; matches the
  testing-validation skill's "no sensor-state checkpoint store exists yet"
  note.

---

## 9. Bootstrap & mode-parity audit (Inv-9)

`build_platform` (`bootstrap.py:206-784`) still constructs one component
graph per call; the mode-conditional surface is unchanged in shape from
06-24, re-verified line-by-line against the current file:

| Concern | BACKTEST | PAPER / LIVE | On tick-decision path? |
|---|---|---|---|
| Clock | `SimulatedClock` (`_select_clock:787-790`) | `WallClock` | Sanctioned divergence (with `ExecutionBackend`) |
| `ExecutionBackend` | `build_backtest_backend`/`build_passive_limit_backend` (`:992-1042`) | `build_paper_backend` (now lazily imported, `:1063-1067` — packaging-only, §1) | Sanctioned divergence |
| `session_open_ns` | may auto-bind from first event (warned, BACKTEST-only, `_create_sensor_layer:1633-1647`) | must be explicit, or auto-anchored to composition-time wall clock only when sensors/horizons are configured (`_ensure_session_open_ns_for_live_modes:793-819`) | Gate only, not decision |
| EventLog order guard | strict (`enforce_market_order=True`) | relaxed (`:290-293`) | Ingestion guard, not decision |
| `registry_clock` | `None` → lifecycle/ledger off (`:312`) | `clock` | No — ledger is forensic-only |
| `metric_collector._store_raw_events` | `False` (`:566`) | `True` | Observability only |
| `warn_on_inert_entry_gates` | `False` | `True` (`:428`) | Warning only |

The core sensor/scheduler/aggregator/`HorizonSignalEngine`/composition/
`BasicRiskEngine`(+`AlphaBudgetRiskWrapper`)/`HazardExitController`/sizer/
translator/position-manager graph (`:502-736`) is constructed identically
regardless of mode — **no new mode-conditional branch was introduced** since
06-24 in this region. New wiring since 06-24 (gate-threshold floors,
`metric_collector` threaded into the signal layer, `consumed_features`
provenance switch) is mode-independent config/observability plumbing, not a
decision-path fork:

- `platform_gate_threshold_overrides=config.gate_thresholds_overrides`
  (`:332-334`) — construction-time, feeds `AlphaRegistry`'s promotion-gate
  logic (alpha-lifecycle territory), not the tick loop.
- `metric_collector=metric_collector` now passed into `_create_signal_layer`
  (`:600,1771,1837`) — purely additive telemetry wiring into
  `HorizonSignalEngine`, mirrors the existing sensor-layer pattern.
- `_consumed_features_for_signal_registration` (`:1529-1545`) — prefers the
  bootstrap-computed `required_warm_feature_ids` over the loader's declared
  `consumed_features` for provenance stamping on `RegisteredSignal`; a
  construction-time choice between two already-deterministic sets, resolved
  identically on every boot for a fixed config.

Re-confirmed unchanged: single-writer wiring is mode-invariant; construction
is driven by a fixed statement sequence with `sorted()` applied wherever a
`set`/`frozenset` feeds order-sensitive output (§4.1, alpha discovery in
§1); conditional subsystems (`composition`, `hazard_exit_controller`,
`promotion_ledger`) still return cleanly-`None`/inert when unconfigured
(`:1949-1950,2137-2138,313-317`).

---

## 10. Parity-hash coupling map

The manifest (`tests/determinism/parity_manifest.py:LOCKED_PARITY_BASELINES`)
grew from **12 entries** (11 "level" baselines + `market_fill_acks`) at
06-24 to **17 entries** now. Two further determinism modules exist
**outside** the manifest by design (documented reasons below). Each is
driven by its **leaf component(s)** on a bare `EventBus`, except the two new
orchestrator-level tests.

| Hash / test | Driven by | Ordering assumption it locks | New since 06-24? |
|---|---|---|---|
| `level1_sensor_reading` | `SensorRegistry` | registry fan-out + `_sensor_seq` | No |
| `level1_v03_sensor_reading` | sensors | sensor compute determinism | No |
| `level2_horizon_tick` | `HorizonScheduler` | `sorted(horizons)` + `_horizon_seq` | No |
| `level2_signal` | registry+scheduler+aggregator+engine | engine eval order + `_signal_seq` (empty-stream baseline) | No |
| `level3_horizon_feature_snapshot` | aggregator | `sorted(feature_id)` + `_snapshot_seq` | No |
| `level3_sized_intent_decay_off`/`_on` | composition engine | synchronizer sorted emission | No |
| `level4_portfolio_order` | `BasicRiskEngine.check_sized_intent` | lex-sorted legs + `derive_order_id` | No |
| `level4_hazard_exit_order` | `HazardExitController` | SHA-256 order_id + `_hazard_seq` | No |
| `level5_regime_hazard_spike` | detector | pure 2-state function + `_hazard_seq` | No |
| `level6_regime_state` | `HMM3StateFractional` | posterior determinism | No |
| `market_fill_acks` | `BacktestOrderRouter` | fill-model economics | No |
| **`position_pnl`** | `MemoryPositionStore` (real FIFO cost-basis) | fill/mark → `PositionUpdate` reconciliation math (closes the Inv-5 "PnL" clause) | **Yes** |
| **`state_transition`** | real `RiskLevel` + `OrderState` SMs, one shared `SequenceGenerator` | multi-SM edge order + shared-sequence interleave (directly targets the 06-24 §3.2 coupling note) | **Yes** |
| **`cross_sectional_context`** | real `UniverseSynchronizer` | `_ctx_seq` + symbol-sorted maps + `completeness` under a partial-report boundary | **Yes** |
| **`signal_fires`** | real `HorizonSignalEngine` + `RegimeGate` | non-empty `_signal_seq` allocation, ON/OFF gate stamping, gate-close exit, mechanism/half-life propagation | **Yes** |
| **`multi_symbol_sensor_reading`** | real `SensorRegistry`, 3-symbol round robin | cross-symbol emission interleave + sequence allocation (previously only single-symbol fixtures existed) | **Yes** |
| `test_orchestrator_replay.py` (not in manifest by design — see its own docstring) | **full `build_platform` + `run_backtest`** | orchestrator `_seq` interleaving of Signal/SizedPositionIntent/OrderRequest/PositionUpdate; micro-state walk; `_pending_sized_intents` drain order; bus-subscriber registration order | **Yes** |
| `test_hash_seed_independence.py` (not in manifest — a meta-test over other replays) | subprocess re-runs of `regime`/`intent_off`/`intent_on`/`snapshot` under 3 `PYTHONHASHSEED` values | proves the `sorted(...)` canonicalization in each hash function is load-bearing, not incidentally-stable | **Yes** |

**Residual coupling gaps** (narrower than 06-24's, not closed by this
window):

1. `test_orchestrator_replay.py`'s **locked baseline** exercises only an
   empty Signal/Order/PositionUpdate stream — the fixture never crosses an
   entry threshold (self-documented at `:133-141`, *"a threshold-crossing
   fixture would lock a non-empty order/fill stream and exercise the M5–M10
   `_seq` interleaving more richly"*). The portable
   `test_two_full_orchestrator_replays_are_identical` test *would* catch any
   in-process nondeterminism on a real order-flow path if the fixture
   exercised one, but today it exercises a path that never fires the M6–M9
   order/fill sequence. Notably, **this is exactly the class of gap that a
   `reason`-field-asserting order-stream baseline would have caught the §1
   regression** — the hash function `_hash_orders` (`:103-111`) already
   includes `o.reason` in its serialization; it simply has nothing to hash
   today.
2. `test_hash_seed_independence.py` probes 4 of the (now) 17 manifest
   families (`regime`, `intent_off`, `intent_on`, `snapshot`) — not the 5
   newest ones, not `test_orchestrator_replay.py`'s streams. Given three of
   the newest five (`cross_sectional_context`, `signal_fires`,
   `multi_symbol_sensor_reading`) explicitly hash `sorted(...)`-canonicalized
   maps by their own docstrings, they are plausible (untested) candidates
   for the same class of hidden hash-seed dependency this test was built to
   catch.

---

## 11. Test gap matrix

| Invariant / property | Covered | Partial | Missing |
|---|---|---|---|
| Deterministic iteration on tick path | sorted legs (`test_portfolio_order_replay`); per-family seq isolation (`test_legacy_sequence_isolation`); frozenset-sort fix (§4.1) | — | — (06-24's one gap here is closed) |
| Sequence allocation = f(log) | per-family isolation; **new**: shared-`_seq` multi-SM interleave (`test_state_transition_replay`); **new**: full orchestrator `_seq` interleave (`test_orchestrator_replay`, on the paths it exercises — see §10 gap 1) | orchestrator baseline's order/fill streams are empty | — |
| Bus delivery order | `test_bus_subscription_order.py` (**new**, pins the canonical handler order) | — | — (06-24's gap closed) |
| Micro-stage ordering | `tests/kernel/test_micro*` (table legality, properties); `test_orchestrator_replay` (real walk, on its exercised paths) | — | no property test that the M-stage event *sequence* is invariant under sparse/idle interleavings through the full orchestrator (unchanged ask from 06-24) |
| Single-writer per event type | implicit (one publisher wired, re-verified repo-wide §6.1) | — | still no automated assertion (e.g. a counting `subscribe_all` recorder) that exactly one writer exists per parity event — the 06-24 Signal-echo class of bug would again go undetected by tooling alone, only by manual audit |
| Clock discipline (Inv-10) | ruff DTZ (partial — see below); `SimulatedClock` backward guard | — | **`time.time()` in `bootstrap.py:2298` is structurally outside DTZ's rule coverage** (§1 item 2) — no test or lint asserts wall-clock-freedom for the `time` module, only the `datetime` module |
| Causality (Inv-6) | `test_anti_lookahead` at component seams (unchanged, 12 tests) | — | no full-orchestrator anti-lookahead replay (unchanged ask) |
| Mode parity (Inv-9) | `tests/bootstrap/*` wiring tests (expanded: gate-threshold floor tests, paper-branch patch-target fix) | backend-swap wiring | no test asserting the BACKTEST/PAPER decision graph is identical except clock+backend+normalizer (unchanged ask) |
| PnL / fill reconciliation determinism | **new**: `test_position_pnl_replay` | — | order **construction-field** correctness (e.g. `reason=`) is exercised only by targeted unit tests (`TestForcedExitPanicReason` etc.), not by any parity hash — which is precisely why §1's regression passed the *entire* determinism suite while failing 5 targeted unit tests |
| Cross-symbol / multi-boundary interleave | **new**: `test_multi_symbol_sensor_replay`, `test_cross_sectional_context_replay` | — | — (06-24 didn't call this out explicitly, but it was a real prior gap; now closed) |
| Hash-seed independence | **new**: `test_hash_seed_independence.py`, 4 of 17 families | — | the 5 newest manifest families + orchestrator-replay streams not yet probed under multiple `PYTHONHASHSEED` values (§10 gap 2) |
| Documentation accuracy | — | — | `.cursor/skills/testing-validation/SKILL.md`'s parity-hash table is stale (§1, P2) |

### Proposed minimal new tests (specs only, per the audit's read-only mandate)

1. **Regression test for §1** (would already exist if the removed kwarg had
   parity/property coverage instead of only targeted unit tests): none
   needed beyond re-enabling the 5 already-written, already-correct tests by
   restoring the dropped `reason=` kwarg — this is a one-line fix, not a
   test-design gap. Flagged here only to note that a `reason`-inclusive
   *parity* hash (as opposed to unit assertions) would have caught this
   class of regression even without anyone running the specific unit test
   file, since parity hashes are asserted in the full suite by default.
2. **Threshold-crossing orchestrator-replay fixture.** Extend
   `test_orchestrator_replay.py` with a second fixture that crosses an entry
   *and* a stop-exit threshold, locking a non-empty Signal/Order/
   PositionUpdate baseline. This would immediately have caught §1 (its
   `_hash_orders` already serializes `o.reason`) and would close §10 gap 1.
3. **Extend `test_hash_seed_independence.py`'s probe set** to include
   `cross_sectional_context`, `signal_fires`, and `multi_symbol_sensor_
   reading` (all three explicitly `sorted(...)` a dict/set per their own
   docstrings — the exact class of risk the existing probe targets).
4. **Single-writer assertion (unchanged ask from 06-24).** A `subscribe_all`
   recorder over a fixture asserting no two identical `(event_type,
   sequence)` pairs appear, and that `Signal.sequence` never repeats across
   the standalone + synthetic-forced-exit paths — would catch a reintroduced
   echo without relying on manual audit.
5. **Skill-doc sync.** Update `.cursor/skills/testing-validation/SKILL.md`'s
   parity-hash table to list all 17 manifest entries plus
   `test_orchestrator_replay.py` / `test_hash_seed_independence.py` (doc-only
   change, no code/test risk).

---

## 12. Prioritized backlog

| # | Tier | Effort | Component | `file:line` | One-sentence fix | Impact |
|---|---|---|---|---|---|---|
| 1 | **P0** | S | `_try_build_order_from_intent` | `orchestrator.py:4784-4803` (+ dead `:318`) | Restore `reason=_FORCED_EXIT_PANIC_REASON.get(intent.signal.strategy_id, "")` as a kwarg on the `OrderRequest(...)` call (or fold `_FORCED_EXIT_PANIC_REASON`'s one entry inline); delete the dict if inlined | Re-greens 5 currently-failing tests; restores stop-exit panic-fill pricing realism and `TradeRecord.metadata["order_reason"]` / Inv-13 provenance. Does not touch any locked parity hash. |
| 2 | **P1** | S | `_enforce_factor_loadings_freshness` | `bootstrap.py:2298` | Either accept `clock: Clock` into the function and use `clock.now_ns()` (mirroring the `config.snapshot(ts_ns=...)` pattern at `:741`) so BACKTEST never touches wall time even in this fallback branch, or narrow the CLAUDE.md/AGENTS.md claim to say ruff DTZ only covers `datetime.*`, not `time.time()`, so the enforcement gap is documented rather than implied-covered | Removes the one remaining reproducibility hazard in an opt-in boot-time gate; or at minimum stops the docs from overstating CI coverage |
| 3 | **P1** | M | determinism suite | `tests/determinism/test_orchestrator_replay.py` | Add a threshold-crossing fixture variant (gap-test #2, §11) | Would have caught #1 automatically via the full test suite; closes the last real orchestrator-parity coverage hole from 06-24 |
| 4 | **P2** | S | `test_hash_seed_independence.py` | `tests/determinism/test_hash_seed_independence.py:38-48` | Add `cross_sectional_context`, `signal_fires`, `multi_symbol_sensor_reading` to the subprocess probe set | Extends the strongest determinism guarantee in the suite to the newest, most dict/set-heavy hash functions |
| 5 | **P2** | S | single-writer tooling | `tests/kernel/` (new module) | Add the `subscribe_all`-recorder single-writer assertion proposed in 06-24 and re-proposed here (gap-test #4) | Converts "single-writer holds" from an audit-verified claim into a CI-enforced one; would catch a reintroduced Signal echo automatically |
| 6 | **P2** | S | documentation | `.cursor/skills/testing-validation/SKILL.md` | Update the parity-hash table to the current 17-entry manifest + 2 non-manifest modules | Keeps the skill's own "canonical reference" framing honest |
| 7 | **P2** | S | contract clarity | `docs/audits/kernel_audit_2026-06-24.md` §2 map (and this report's §3) | Annotate the micro-stage map's M6/M7 row to note REVERSE emits two `OrderRequest`s (exit-then-entry, same `_seq`), not one | Prevents a future reader from treating "single order/tick" as a hard invariant when auditing REVERSE-adjacent changes |
| 8 | **P2** | S | style (carried from 06-24 #9, now more clearly dead) | `orchestrator.py:318` | If #1 is fixed by inlining, delete `_FORCED_EXIT_PANIC_REASON`; if fixed by restoring the kwarg, the dict becomes live again and the original 06-24 `MappingProxyType` suggestion still applies | Removes ambiguity about whether the dict is meant to be alive |

---

*Distinctions used above: **implementation bug** (#1); **fragile-but-correct
/ enforcement gap** (#2, #4, #5); **intentional design, self-documented**
(regime-calibration prefix nuance, `_ensure_session_open_ns_for_live_modes`,
the shared-`_seq` "declined" decision, the multi-callback SM docstring);
**clean, expanded coverage** (the 5 new parity baselines, the two new
non-manifest determinism modules, the bus-subscription-order test, the
gate-threshold-floor wiring and its tests). Every one of the 06-24 audit's 9
remediations was independently re-verified against current line numbers and
holds; none regressed in the ordering/determinism sense. The one live defect
found (§1) was introduced by a merge after the 06-24 audit's own remediation
commits landed, is structurally invisible to every locked parity hash, and
was caught only by actually executing this audit's mandated
`tests/kernel/` verification run — which is itself evidence for backlog
item #3 (parity coverage, not just unit coverage, is what would make this
class of regression self-detecting).*
