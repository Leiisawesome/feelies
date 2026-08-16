# PHASE 1 — Axis A: the deterministic substrate (E1)

**The substrate is stronger than Phase 0 implied and weaker in a different
place than expected.** The parts that are enforced are enforced well — a closed
parity registry, an AST wall-clock guard with a stale-entry check, a single
canonical tie-break key, a subprocess hash-seed test. The gap is that
**enforcement granularity does not match the thing being enforced**: the
wall-clock ban is per *file* while the violation is per *call*; the determinism
oracle is per *field list* while the contract is per *schema*; the config
fingerprint covers the file that *selects* the alphas but not the alphas. Each
of those is a check that passes for a reason unrelated to the property it
claims.

Five items are `open defect` in the sense CORE §H means it — a named
nondeterminism source with no named neutralizer, or a target with no mechanism
at all: **exactly-once order submission across restart** (§4), **symbol
identity** (§8, inherited from Phase 0 F.2), **arrival-order discipline in
PAPER** (§2), **engine-state reset** (§5), and **contract versioning** (§8).

**Status vocabulary:** `specified` / `implemented` / `conformance-tested` /
`open defect`. **Evidence labels:** `VERIFIED` (read the code) / `INFERRED`
(derived from what was read) / `ASSUMED` (not checkable).

## Evidence base

Phase 0 measurements are re-used where this phase did not need to sharpen them,
and are re-cited to their own evidence file rather than to Phase 0 prose. New
measurement for this phase is `tools/arch/substrate.py` →
`tools/arch/evidence/substrate.json`.

| Evidence | Produced by | Used in |
|---|---|---|
| `tools/arch/evidence/clock.json` | `measure.py clock` | §1 — cited as P1 requires, and corrected |
| `tools/arch/evidence/clockscan.json` | `tools/arch/clockscan.py` | §1 — the corrected clock census |
| `tools/arch/evidence/substrate.json` | **new** `tools/arch/substrate.py` | §2–§5, determinism budget |
| `tools/arch/evidence/contracts.json` | `tools/arch/contracts.py` | §3, §8 |
| `tools/arch/evidence/parityscan.json` | `tools/arch/parityscan.py` | §6 |
| `tools/arch/evidence/nondet.json` | `measure.py nondet` | determinism budget |

`tools/arch/substrate.py` measures what no existing evidence file covers:
sequence-space count, bus re-entrancy (does a subscribed handler reach
`publish` from inside its own dispatch), identity-generation sites, per-class
reset paths, and the iteration-order / reduction-order / RNG / filesystem
sources the budget must enumerate. Two corrections were made to it during this
phase and are noted because they changed headline numbers:

- `ast.walk` shares a leaf name with `os.walk` and inflated filesystem
  enumeration from 1 to 10. Excluded at `tools/arch/substrate.py:213`.
- The first version counted dict and set iteration together and reported 125
  "unsorted iterations". **Dict iteration is insertion-ordered and therefore
  deterministic**; only set iteration is hash-ordered. Split at
  `tools/arch/substrate.py:279`. The real figure is **5** set iterations, all
  in tick-critical packages, and all five were then read individually (§ budget
  row 3). Publishing 125 would have been a measured number that meant nothing.

---

## 1. Clock discipline

**Target.** Three time bases, each named on the envelope and never
interchangeable: **event time** (when the market acted), **ingest time** (when
we learned), **wall time** (never an input to a decision, only to telemetry).
One clock authority, injected. No engine on the tick-critical path reads the
machine clock for any value that reaches an emission. The enforcement is a
check that fails the build, not a convention in a docstring.

**Current state.**

The clock authority exists and is narrow. `src/feelies/core/clock.py:13`
declares a one-method `Clock` protocol; `WallClock` (`:21`) is the only
sanctioned raw read and `SimulatedClock` (`:30`) refuses to move backward
(`:46`). Backend selection is composition-root work at
`src/feelies/bootstrap.py:650`. `VERIFIED`.

The census P1 asks for is `tools/arch/evidence/clock.json`, and that file is
**not a bound in either direction** — Phase 0 established this and it is
re-verified here. It reports 22 sites; 5 are `datetime.time(hour, minute)`
constructor calls, not clock reads, and 12 real reads are missed because
`tools/arch/measure.py:71` lists `time.perf_counter` but not
`perf_counter_ns`. The corrected census is
`tools/arch/evidence/clockscan.json`: **29 raw reads** — 16 `time.monotonic`,
12 `time.perf_counter_ns`, 1 `time.time_ns` — plus 10 `datetime.fromtimestamp`
conversions tracked separately. All 12 missed reads are on the tick path (10 in
`src/feelies/kernel/orchestrator.py`, 2 in
`src/feelies/core/state_machine.py`). `VERIFIED`.

**The enforcement mechanism, stated as P1 requires.** It is
`tests/acceptance/test_no_walltime_outside_clock.py:72`, an AST walk over every
file in `src/feelies/` that flags any call whose attribute is in
`_BANNED_ATTRS` (`:15`) on a receiver in `_BANNED_ROOTS` (`:28`), failing unless
the file appears in `_WALL_CLOCK_ALLOWLIST` (`:31`). A companion test at `:96`
fails on a stale allowlist entry, so the list cannot rubber-stamp a file that
no longer reads a clock. This is a real mechanism and it is the reason the 12
`perf_counter_ns` reads are known rather than discovered. `conformance-tested`.

**Gap — the allowlist is file-granular and the violation is call-granular.**
`tests/acceptance/test_no_walltime_outside_clock.py:83` reads
`if rel in _WALL_CLOCK_ALLOWLIST: continue` — it skips the **entire file**.
Allowlist keys are paths relative to `src/feelies`, and
`src/feelies/kernel/orchestrator.py` is one of them, justified for
`perf_counter_ns` telemetry. That module is 4 778 sloc and 11.8% of the
platform (`tools/arch/evidence/inventory.json`). A `datetime.now()` added
anywhere in it passes this check, and a `time.time_ns()` added to
`src/feelies/core/state_machine.py` likewise. The one module where a raw clock read would do the most damage is the
one module the guard does not read. `VERIFIED` by reading the skip. `gap`.

**Gap — `timestamp_ns` has no declared semantics.** CORE §C.8 requires every
inter-engine payload to declare timestamp semantics. `Event.timestamp_ns`
(`src/feelies/core/events.py:49`) is documented nowhere: the base docstring
(`:32`) covers `source_layer` and shallow immutability and says nothing about
which time base `timestamp_ns` carries. Measured: **1 of 21** event classes
documents it — `HorizonTick` at `:584` ("`timestamp_ns` is the event time that
caused the scheduler to…"). The concrete instruments do carry named bases
(`NBBOQuote.exchange_timestamp_ns` at `:81` is event time,
`received_ns` at `:88` is ingest time, and its docstring at `:66` discloses
that `received_ns` is meaningless in backtest because the `SimulatedClock` does
not advance during batch ingest), but the field every engine actually reads is
the undeclared one. `VERIFIED`. `gap`.

**Gap — two clock authorities, only one injected.** The allowlist legitimises a
second, non-injected time source on the tick path for telemetry. Phase 0
established that its *values* stay out of the parity hash and that
`_finalize_tick` routes always-on timers with `sequence=0`
(`src/feelies/kernel/orchestrator.py:2131`) so they cannot consume sequence
numbers. That is correct and load-bearing. It is still a second authority, and
nothing structurally prevents a telemetry value from being read into a
decision — the separation is upheld by the code as written, not by a type.
`INFERRED`. `gap` (design, not defect).

---

## 2. Sequencing and tie-breaking

**Target.** One total order over concurrent events, defined once, applied to
every event that can be concurrent with another. A deterministic tie-break key
with no residual dependence on arrival or concatenation order. A stated
resequencing window, and a stated, emitting, exposure-reducing action for a
late arrival outside it.

**Current state — the tie-break key matches target.**

`src/feelies/storage/event_resequence.py:33` `event_merge_sort_key` is the
single canonical key: `(exchange_timestamp_ns, symbol, event_type_rank,
sequence)`, quotes before trades via `_TYPE_RANK` (`:30`). Its module docstring
(`:6`) states exactly why the naive key is wrong — a key that ties only on
timestamp leaves symbol order dependent on concatenation order. It is applied
consistently at all three places that need it: `resequence_event_list` (`:46`),
the event-log monotonicity guard (`src/feelies/storage/memory_event_log.py:111`),
and the replay feed's re-check (`src/feelies/ingestion/replay_feed.py:90`).
`resequence_event_list` also reassigns contiguous sequences and rebuilds
correlation IDs (`:57-68`) so identity follows the order rather than the
arrival. `VERIFIED`. `matches target`, and it is the strongest single piece of
plumbing in this axis.

**Gap — the total order covers 2 of 21 event types.** `_TYPE_RANK`
(`src/feelies/storage/event_resequence.py:30`) has exactly two entries, and the
key's signature (`:33`) accepts only `NBBOQuote | Trade`. Everything else — all
19 remaining types in `tools/arch/evidence/contracts.json` — has no total order
rule; its order is whatever order `publish` was called in. That is deterministic
*given* the same code path, which is why replay works, but it is not a *rule*:
there is no key, so there is nothing to check a stream against, and no way to
merge two independently produced streams. `VERIFIED`. `gap`.

**Gap — there is no resequencing window.** The question P1 asks has an answer,
and the answer is that the concept is absent. `resequence_event_list` is a
whole-batch `sorted()` over an already-complete list
(`src/feelies/storage/event_resequence.py:53`), applied at ingest
(`src/feelies/ingestion/massive_ingestor.py:283`) and at cache replay
(`src/feelies/storage/cache_replay.py:150`). There is no buffer, no watermark,
no lateness bound. `VERIFIED` by absence. `gap`.

**Open defect — in the only non-replay mode, disorder is accepted silently.**
`src/feelies/bootstrap.py:203` sets `enforce_market_order = config.mode !=
OperatingMode.PAPER`. With it `False`, `_enforce_market_order`
(`src/feelies/storage/memory_event_log.py:109`) computes the key, skips the
comparison, and stores the new key — the log preserves arrival order. The class
docstring (`:48-55`) states the reasoning and it is sound as far as it goes: a
live feed is not exchange-timestamp monotonic across symbols, and rejecting a
benign out-of-order arrival would degrade the pipeline.

What is missing is the other half. A late arrival is not rejected, and it is
also **not counted, not logged, and not emitted**. There is no
`_out_of_order_count`, no `DataHealth` transition, no `Alert`. Contrast the
queue at ingress, which Phase 0 found does this correctly — bounded, counts
drops, warns, and degrades `DataHealth` via `notify_feed_interrupted`. The
event log does none of it. CORE §E engine 1 says "Dropping is allowed; dropping
without notification is not"; the same standard applied to reordering is not
met. And since `OperatingMode` has only `BACKTEST` and `PAPER`
(Phase 0 D-7), PAPER is the *only* mode where this branch is live. `VERIFIED`.
`open defect`.

**Sequence spaces — 26 generators, isolation is deliberate and tested.**
`tools/arch/evidence/substrate.json:n_sequence_generators` = **26**
`SequenceGenerator` constructions: 13 at the default `thread_safe=True`, 12
threaded through `thread_safe_sequences`, 1 setting `_seq_thread_safe`
directly (`src/feelies/bootstrap.py:273`). The isolation is intentional — the
comment at `src/feelies/bootstrap.py:272` says "Isolate risk alerts so they
cannot shift orchestrator event IDs" — and it is pinned by
`tests/determinism/test_legacy_sequence_isolation.py:12`. `implemented`.

The consequence to carry into Phase 2: `sequence` is unique *within a space*
and there are 26 spaces, so `sequence` alone does not order two events of
different types. Combined with the 2-of-21 coverage above, **the platform has
no global event ordinal.** `INFERRED`.

`SequenceGenerator` itself is honest about its own limits
(`src/feelies/core/identifiers.py:29-43`): the lock guarantees uniqueness, not
assignment order, and deterministic replay therefore requires single-threaded
allocation. That constraint is documented and is not checked anywhere — see
budget row 8.

---

## 3. Bus semantics

**Target.** Dispatch semantics chosen deliberately with the failure mode of the
choice made loud. Registration order either irrelevant to output or declared
and pinned as a determinism input. Re-entrancy either forbidden with a guard,
or permitted with a declared depth bound and cycle detection.

**Current state.** `src/feelies/bus/event_bus.py` is 71 lines and three public
methods. It is the narrowest contract in the platform, and every property below
is visible in `publish` (`:59-70`).

**Exact-type dispatch — `implemented`, and the failure mode is silence.**
`self._handlers.get(type(event))` (`:65`) is an exact-type lookup with no MRO
walk and no `isinstance`. `tools/arch/evidence/contracts.json` records
`exact_type_dispatch=True`, `subtype_dispatch=False`. On a miss, `handlers` is
`None`, the `if` falls through, and `publish` returns having done nothing:
**no exception, no counter, no log**. A subscriber registered against a base
class receives nothing forever, and the only symptom is absence. `VERIFIED`.

That is the right *choice* — subtype dispatch would make delivery order depend
on class hierarchy, which is worse — but a target-state bus must make the miss
audible. The cheapest form: count publishes with zero handlers, per type, and
let engine 11 alert on a type whose count is the whole run.

**Subscription order affects output — `open defect`, because it is a
determinism input that nothing pins.** Delivery is type-specific handlers in
registration order, then global handlers (`:62-63`, `:67-70`). Phase 0 found
`bootstrap` treats this as load-bearing, with six ordering comments in
`build_platform`; one of them is visible above the market-data wiring —
`src/feelies/bootstrap.py:355` "Subscribe the router before sensors so fills
retain their triggering quote". `tools/arch/evidence/substrate.json` counts
**32** subscribe sites. Nothing hashes the subscription graph, no test asserts
an order, and Phase 0 P-4 already recorded that registration order is outside
the parity surface. So the platform has a documented, output-determining input
whose only enforcement is six prose comments in one function. `VERIFIED`.

**Re-entrancy — permitted, unbounded, and the primary mechanism of the
pipeline.** Measured:
`tools/arch/evidence/substrate.json:n_reentrant_handlers` = **16 of 32**
subscribed handlers reach a `publish` from inside their own dispatch, by
transitive self-call within the handler's class. Examples, each `VERIFIED` by
the scan and each on the tick path:

| Subscription | Handler | Publishes via |
|---|---|---|
| `HorizonTick` → `src/feelies/features/aggregator.py:253` | `HorizonAggregator._on_horizon_tick` | itself |
| `HorizonFeatureSnapshot` → `src/feelies/signals/horizon_engine.py:198` | `HorizonSignalEngine._on_snapshot` | itself |
| `HorizonTick` → `src/feelies/composition/synchronizer.py:130` | `UniverseSynchronizer._on_tick` | `_emit_context` |
| `CrossSectionalContext` → `src/feelies/composition/engine.py:197` | `CompositionEngine._on_context` | `_dispatch_one` |
| `NBBOQuote` → `src/feelies/risk/stop_exit.py:172` | `StopExitController._on_quote` | `_emit_exit` |
| `RegimeHazardSpike` → `src/feelies/risk/hazard_exit.py:141` | `HazardExitController._on_spike` | `_maybe_emit_exit` |
| `OrderRequest` → `src/feelies/kernel/orchestrator.py:585` | `Orchestrator._on_bus_hazard_order` | itself |

**So the answer to "may an engine publish from within its own handler" is: it
must, or the pipeline does not run.** Phase 0's D0.4 hops 21→25 are exactly
this cascade — tick, snapshot, signal, context, intent — each stage publishing
from inside the previous stage's handler, all on one synchronous call stack.

The bus has no re-entrancy guard, no depth counter, and no cycle detection;
`publish` is 12 lines and holds no state (`src/feelies/bus/event_bus.py:59-70`).
`VERIFIED`. A publish cycle would therefore recurse until Python's recursion
limit and surface as `RecursionError` inside the tick's `try/except Exception`
(Phase 0 D0.4 hop 2), i.e. as a degraded macro state with no indication of the
cause. Today no cycle exists — the cascade is a DAG — but nothing enforces
that it stays one. `INFERRED`. **The target must state a maximum cascade depth
and assert it**, because "it is acyclic today" is exactly the property that a
twentieth alpha attaching a new subscriber silently breaks.

**Dead surface.** `subscribe_all` (`:55`) has 0 call sites in `src/`
(`tools/arch/evidence/contracts.json:call_site_counts`), and its
`_global_handlers` list (`:37`) is iterated on **every** publish (`:69`) to
walk an always-empty list. Phase 0 D-16 found a design document twice proposing
a concrete consumer that was never built. Flagged, not actioned — CORE §H
requires scoped authorization for removal.

---

## 4. Identity and idempotency

**Target.** Every ID replay-stable by construction: derived from event content
and provenance, never from a UUID, a salted hash, or an object address.
Duplicate delivery defined at every boundary that can duplicate. Order IDs
additionally exactly-once across process restart and broker reconnect, which
requires durability, not just derivation.

**Current state — generation matches target.**

`tools/arch/evidence/substrate.json:identity_by_kind` measures the whole
surface: **13** `make_correlation_id`, **11** `derive_order_id`, **6** builtin
`id()`, and — from a separate scan of `random` / `secrets` / `uuid` roots —
**2** RNG sites, both in `src/feelies/research/cpcv.py`. **There is no `uuid`
import anywhere in `src/feelies/`.** `VERIFIED`.

- `make_correlation_id` (`src/feelies/core/identifiers.py:9`) is
  `f"{symbol}:{exchange_timestamp_ns}:{sequence}"` — pure content. `VERIFIED`.
- `derive_order_id` (`:18`) is `sha256(seed)[:16]`, and its docstring puts the
  burden where it belongs: "Callers own the seed format." The 11 call sites use
  9 distinct namespaced formats — `f"emergency_flatten:{correlation_id}:{symbol}:{seq}"`
  (`src/feelies/kernel/orchestrator.py:2618`), `f"{cid}:{seq_exit}:exit"`
  (`:3012`), `f"{parent_order_id}:working_fallback"` (`:3996`),
  `f"degrade_flatten:{reason}:{symbol}:{seq}"` (`:5337`), and one per exit
  author (`src/feelies/risk/hazard_exit.py:236`,
  `src/feelies/risk/deferral_cap.py:362`,
  `src/feelies/risk/stop_exit.py:284`,
  `src/feelies/execution/sized_intent_legs.py:170`). `VERIFIED`.
- The 6 `id()` uses are **not** emitted identity. Four are AST-node bookkeeping
  in `src/feelies/alpha/dependency_graph.py`; two are
  `src/feelies/kernel/orchestrator.py:4840` and `:4842`, an intra-tick
  actionable-signal set. The report dedupe at
  `src/feelies/harness/backtest_report.py:88` is address-derived but safe: the
  input list holds a strong reference to every object for the loop's duration,
  so no address can be reused mid-scan. `VERIFIED` — recorded because a reader
  scanning for `id()` will find it and should not re-litigate it.

Two properties worth naming for Phase 2. First, `derive_order_id` truncates to
**64 bits**; at intraday order counts the birthday bound is not a concern, but
the truncation is a choice nothing records. Second, `derive_order_id` is
collision-*safe* only because the seed formats are namespaced by hand — no
registry of seed formats exists, so two authors adopting the same format is an
undetected duplicate-ID event, not a caught one. `INFERRED`.

**Duplicate delivery — defined at ingress, undefined on the bus.**

At ingress the policy is explicit and fail-closed.
`src/feelies/ingestion/massive_normalizer.py:777` `_reject_sequence_reuse`
compares the incoming `(sequence_number, content_fingerprint)` against
`_last_seen[(symbol, feed_type)]` (`:263`): an exact duplicate is dropped and
counted (`:800-802`), and the same vendor sequence carrying a **different**
payload transitions the symbol to `CORRUPTED` (`:809`), which
`src/feelies/ingestion/data_integrity.py:58` declares terminal. That is the
exposure-reducing branch on ambiguous input. `implemented`.

Its bound: `_last_seen` holds **one** row per `(symbol, feed_type)`, so the
comparison is against the immediately previous message only. A duplicate
separated by one intervening message is not detected. `VERIFIED` by reading
`:794-802`. This is the resequencing-window question of §2 wearing a different
hat — a one-deep window is the only window in the system.

On the bus there is no duplicate semantics at all: `publish` has no idempotency
key, no seen-set, no dedup (`src/feelies/bus/event_bus.py:59-70`). Delivery is
exactly-once because it is a synchronous function call, not because anything
enforces it. Phase 0 D0.4 recorded the consequence — the arbitration-selected
`Signal` is deliberately re-published on the same tick, and
`src/feelies/harness/backtest_report.py:74-83` documents the report having to
dedupe the resulting double-record. So the platform *does* redeliver, and the
compensation is at the reader. `VERIFIED`.

**Open defect — exactly-once submission does not survive restart or
reconnect.** Both halves of the mechanism are in-process:

- `src/feelies/execution/passive_limit_router.py:183`
  `self._submitted_order_ids: set[str] = set()` — the comment at `:182` calls
  it "Full set of order_ids ever submitted — used for idempotent reject", and
  "ever" means "since this object was constructed".
- `src/feelies/broker/ib/connection.py:353` `nextValidId` is correct about the
  reconnect it can see — it takes `max(self._next_valid_id, orderId)` (`:364`)
  so the counter never regresses, with the docstring at `:356` naming the
  reconnect case explicitly. But `_next_valid_id` starts as `None` each process
  and is rebuilt from the broker handshake.

There is no durable submitted-order journal anywhere in `src/feelies/`;
`src/feelies/storage/memory_event_log.py:7` states of the only event log in the
composition root that there is "No persistence — all events are lost on process
exit". So after a crash mid-submission the platform cannot distinguish an order
it sent from one it did not, and the derived `order_id` — which *is* stable
across the restart, since it is a pure function of provenance — is a key with
nothing to look it up in. `VERIFIED`. `open defect`.

Note the direction of the failure. A stable-but-unrecorded ID means a restart
that re-derives the same ID will re-submit it; the broker may or may not reject
it as a duplicate. Under CORE §C.5 the resolution must be exposure-reducing:
**refuse to submit any order whose ID cannot be proven absent from a durable
record**, which makes durability a precondition of trading rather than a
feature.

---

## 5. State ownership and reset

**Target.** Every engine declares its mutable state as a named, typed unit and
exposes one deterministic reset that restores it to the cold-start value.
Warm-start and cold-start are two declared contracts, and it is stated which
one replay uses and why.

**Current state — no reset protocol exists.**

Measured over all of `src/feelies/`
(`tools/arch/evidence/substrate.json`): **110** classes hold instance state;
**38** mutate it outside `__init__`; **32 of those 38 have no
reset / restore / clear / checkpoint method of any kind.** `VERIFIED`.

The concentration is where it hurts:

| Class | Attrs set in `__init__` | Mutated elsewhere | Reset path |
|---|---|---|---|
| `Orchestrator` (`src/feelies/kernel/orchestrator.py:324`) | 104 | 38 | **none** |
| `PassiveLimitOrderRouter` (`src/feelies/execution/passive_limit_router.py:93`) | 34 | 10 | **none** |
| `MassiveNormalizer` (`src/feelies/ingestion/massive_normalizer.py:190`) | 17 | 7 | **none** |
| `BacktestOrderRouter` (`src/feelies/execution/backtest_router.py:48`) | 21 | 5 | **none** |
| `IBGatewayConnection` (`src/feelies/broker/ib/connection.py:74`) | 16 | 5 | **none** |

The only uniform reset primitive is `StateMachine.reset`
(`src/feelies/core/state_machine.py:201`), and it is scoped correctly and
narrowly: it returns the machine's own pointer to `_initial_state`, preserves
history, and tags the record `metadata={"type": "reset"}` so a subscriber can
tell it from a transition. It does not, and should not, touch the owning
engine's state. So the framework has a reset for the 1 attribute that is a
state pointer and none for the other 103. `VERIFIED`. `gap`.

What stands in for reset today is the tick-failure path:
`_handle_tick_failure` (`src/feelies/kernel/orchestrator.py:1474`, reached from
the tick-wide `try/except` at `:1466`) resets the micro SM, clears
`_pending_sized_intents`, and drives macro to `DEGRADED`. Phase 0 recorded that
partial mutation before the raise is not rolled back — marks, log appends and
submitted orders persist. That is a *recovery* path over three named
attributes, not a reset over the declared state, and the difference is the gap.
`VERIFIED`.

**Warm-start is specified and unreachable; replay therefore uses cold start.**

The contract exists and is well written.
`src/feelies/storage/feature_snapshot.py:40` declares `FeatureSnapshotStore`
with the right failure policy — corrupt snapshots are "equivalent to missing
snapshots (cold-start), never silently loaded" (`:66`) — and the orchestrator
implements both directions: `_restore_feature_snapshots`
(`src/feelies/kernel/orchestrator.py:5423`) at boot (called from `:930`) and
`_checkpoint_feature_snapshots` (`:5454`) at shutdown (called from `:1114`),
with a SHA-256 over the blob (`:5466`) and a version key derived from the
engine class (`:5438`). The regime engine backs this with a real
`flags_fingerprint` compatibility check that rejects an incompatible
checkpoint (`src/feelies/services/regime_engine.py:598-602`).

**And none of it can fire, because the only implementation is in-memory.** The
sole `FeatureSnapshotStore` in the tree is
`src/feelies/storage/memory_feature_snapshot.py:16`, and
`src/feelies/bootstrap.py:359` constructs a fresh empty one on every
`build_platform`. The shutdown checkpoint writes into a dict that dies with the
process; the boot restore always finds nothing. The code says so about itself
at `src/feelies/services/regime_state_cache.py:14`: "today because no
disk-backed `FeatureSnapshotStore` exists to restore from". `VERIFIED`.

So the answer P1 asks for is: **replay uses cold start, and cold start is the
only start.** That is accidentally the correct choice for determinism — a warm
start whose contents depend on when the last process happened to stop is a
replay hazard — but it is not a decision anyone made, and the machinery to make
the other choice is fully built and load-bearing-looking. Two live consequences:
the restore path at `:5447` is unreachable and therefore untested against a real
blob, and `_checkpoint_regime_snapshot` runs its SHA-256 at every shutdown for
nothing. `INFERRED`. `gap`.

**Target-state call.** Keep cold start as the replay contract and say so in the
type: warm start is admissible only if the snapshot is content-addressed and
its identity enters the run fingerprint (§7), so a warm-started run cannot be
mistaken for a cold one. Until a disk-backed store exists, the checkpoint path
is dead weight on the shutdown path and should be flagged as a removal
candidate — flagged, not removed (CORE §H).

---

## 6. Parity surface

**Target.** A named, closed, single-source registry of exactly what is hashed;
per-stream field coverage that is measured rather than assumed; and an explicit,
reasoned exclusion list whose entries are timing and formatting only.

**Current state — this is the one item that substantially matches target.**

`tests/determinism/parity_manifest.py:133` `LOCKED_PARITY_BASELINES` holds
**26** `(hash_hex, event_count)` entries, each imported from the test that
computes it, so a baseline cannot exist without a producer. Two tests close the
registry: `test_every_locked_hash_is_registered_or_exempt`
(`tests/determinism/test_parity_manifest.py:261`) AST-scans the whole `tests/`
tree for any binding holding a 64-hex literal and fails unless it is either
referenced by the manifest or exempted with a reason, and
`test_every_exemption_names_a_binding_that_exists` (`:288`) fails on a stale
exemption. `manifest_fingerprint()`
(`tests/determinism/parity_manifest.py:234`) is one SHA-256 over the sorted
manifest, so a coordinated re-pin is one visible line.
`conformance-tested`. `matches target`.

**What is hashed, concretely.** The 26 keys, grouped by the engine whose output
they pin:

| Engine | Baselines |
|---|---|
| 2 State/Feature | `level1_sensor_reading`, `level1_v03_sensor_reading`, `multi_symbol_sensor_reading`, `level2_horizon_tick`, `level3_horizon_feature_snapshot` |
| 3 Regime | `level5_regime_hazard_spike`, `level6_regime_state` |
| 4 Alpha | `level2_signal`, `signal_fires`, `reference_alpha_signal_fires`, `decoupled_safety_state_change` |
| 6 Portfolio Construction | `level3_sized_intent_decay_off`, `level3_sized_intent_decay_on`, `cross_sectional_context`, `level4_portfolio_order` |
| 7 Portfolio Accounting | `position_pnl`, `forced_exit_attribution`, `halt_position_update` |
| 8 Risk & Capital | `risk_verdict`, `level4_hazard_exit_order`, `decoupled_risk_flatten_order` |
| 10 Execution Sim/Routing | `market_fill_acks`, `halt_ack` |
| 1 / 9 (halt path) | `symbol_halted`, `halt_order` |
| Kernel | `state_transition` |

**Granularity — field-selected, at a float tolerance.** Phase 0 P-1 measured
the format specifiers across all 120 hash helpers: `.6f` ×10 and `.2f` ×1, no
others. Two runs differing by 5e-7 hash identically. This is reproducibility at
a declared tolerance and is defensible; it is not "bit-identical", which is what
CORE §C.1 says, and the divergence is recorded nowhere in the manifest. The
target should either restate C.1 as "reproducible to a declared per-field
tolerance" and put the tolerance in the manifest, or move to exact
decimal/integer hashing. **Recommendation: state the tolerance in the manifest.**
Money is already `Decimal` end to end (`src/feelies/core/events.py:75-76`,
`:101`), so the `.6f` fields are derived floats where an exact hash would pin
libm, which Phase 0 showed is exactly why two orchestrator streams are exempt.

**Deliberately outside, and correctly so.** Timing values never reach a hash:
`_finalize_tick` routes always-on timers with `sequence=0`
(`src/feelies/kernel/orchestrator.py:2131`) precisely so they cannot shift
event IDs, and their values are wall-clock derived. Log formatting is outside
by construction. Both exclusions are right and should stay.

### 6.1 Engines whose output is outside the hash — the D0.6 constraint

P1 requires this in its own subsection because it bounds what Phase 7 may
touch. Phase 0 D0.6 established the coverage; what follows is its
engine-by-engine reading.

| Engine | In the hash? | Basis |
|---|---|---|
| **1 Market Data** | **No.** The canonical output stream has no baseline of its own. | `VERIFIED` (Phase 0 D0.6): `NBBOQuote` 7 of 19 field names reach any hash, `Trade` 5 of 19 — and `Trade`'s 5 are all generic envelope names because `Trade` has no helper of its own. `symbol_halted` pins the halt marker, not the quote/trade stream. |
| **5 Alpha Governance** | **No.** No manifest entry. | `VERIFIED` by the 26-key list. Cold path; loading, lifecycle and promotion outputs are unpinned. |
| **11 Observability & Safety** | **No.** | `VERIFIED` (Phase 0 D0.6): of `Alert`'s 9 fields, `severity`, `alert_name`, `message` and `context` are all unhashed — only the envelope is pinned. `MetricEvent` loses `metric_type` and `tags`. `KillSwitchActivation` loses `activated_by`. No baseline covers an alert or metric stream. |
| **12 Research/Forensics** | **Exempt, data-gated.** | `VERIFIED`: `_BASELINE_TRADE_PARITY_HASH` is in the exemption list because it requires the APP/2026-03-26 disk cache. |
| **Composed platform** | **Exempt by design.** | `VERIFIED`: `EXPECTED_ORCHESTRATOR_STREAMS` and `EXPECTED_STOP_EXIT_STREAMS` are exempt because the fixture builds the whole platform including the regime engine, whose transcendental math is stable only for a fixed host + libm. Per-engine parity is portable; whole-system parity is host-local. |

**What it would take to bring engine 1 in.** A `market_data_canonical` baseline
over normalizer output: feed a fixed raw-frame fixture through
`MassiveNormalizer.on_message` (`src/feelies/ingestion/massive_normalizer.py:280`)
and hash the emitted `NBBOQuote`/`Trade` sequence over the full declared field
set, `Decimal` fields as exact strings rather than `.6f`. No transcendental math
is involved, so unlike the orchestrator streams this one is portable and can be
a manifest entry rather than an exemption. It needs no production change — the
normalizer already takes an injected clock and a raw `bytes` frame — which makes
it the cheapest coverage gain available in this axis. `INFERRED`.

**What it would take to bring engine 11 in** is different in kind and should
not be bundled with it. Alert content is *supposed* to change when behaviour
changes, so pinning it wholesale converts every diagnostic improvement into a
parity break. The right unit is the alert **taxonomy** — `alert_name` and
`severity` per stream, not `message` — which is a smaller, stabler surface.
`INFERRED`.

**The structural gap under all of this.** The hash input is a hand-written
field list per helper, so **adding a field to any event cannot break parity**
(Phase 0 P-1). The oracle cannot detect schema growth. That is C-1's blast
radius, and it is why §8 is not cosmetic.

**Method caveat, carried forward.** Phase 0's per-event coverage table is a
*union-of-names* measure — a field counts as covered if its name appears in any
helper's field list, so shared envelope names inflate per-class coverage. The
numbers are an upper bound. Phase 0 registered this as U-8 and Phase 0 D-12
then demonstrated it: the APP trade-sequence hash `compute_parity_hash`
excludes `correlation_id` and the three timestamps by design and says so
(`src/feelies/harness/backtest_report.py:791-795`), even though those names are
inside the union. **U-8 remains open and should be resolved before Phase 5**,
because the gap table needs per-stream coverage, not an upper bound.

---

## 7. Configuration and manifest fingerprinting

**Target.** One fingerprint over everything that can change output, and nothing
that cannot. A run is reproducible if and only if its fingerprint matches.

**Current state.** `PlatformConfig.snapshot`
(`src/feelies/core/platform_config.py:645`) is SHA-256 over
`json.dumps(data, sort_keys=True, default=str)` (`:648`), stamped from the
injected clock at `src/feelies/bootstrap.py:583` — the comment at `:580` names
Inv-10 explicitly, so a backtest's provenance record is deterministic. The
fingerprint is logged at boot (`:621`). `implemented`.

**Inside the fingerprint** (`_to_dict`, `src/feelies/core/platform_config.py:658`):
every dataclass field, with `Path` reduced to `.name` (`:685`), `Enum` to
`.name` (`:686`), `frozenset` sorted (`:688`), and `sensor_specs` expanded to a
per-sensor record including `sensor_version`, the class's
`module.qualname`, its `params`, `subscribes_to` sorted by type name, and
`min_history` / `throttled_ms` / `stateful` (`:667-681`). Sensor wiring is
therefore covered well. Eight retired keys are pinned to constants (`:696-710`)
and four default-valued fields are omitted (`:712-720`), both to keep
established checksums valid — a legitimate compatibility shim, disclosed in
comments at `:696` and `:712`.

**Outside the fingerprint, in descending order of how much it matters.**

1. **Alpha manifest content.** `alpha_specs` is reduced to
   `sorted(spec.name for spec in value)`
   (`src/feelies/core/platform_config.py:683`) — names only. A search for
   `manifest_hash` / `spec_hash` / `yaml_hash` / `sha256` across
   `src/feelies/alpha/` returns **no matches**, so no other fingerprint covers
   them either. `VERIFIED`. Editing a threshold in an `alphas/**/*.alpha.yaml`
   changes what the platform trades and moves no checksum. This is the single
   largest hole in run provenance and it sits directly against CORE §C.13.
2. **Code and dependency versions.** Nothing in the snapshot names a git SHA,
   a package version, or the `uv.lock` hash. CI pins Python to `3.13`
   (`.github/workflows/ci.yml:70`) and installs with `uv sync --all-extras
   --locked` (`:79`), which fails on a stale lockfile — a real guarantee, but
   one that lives in CI and not in the artifact. A backtest report from a
   developer machine records neither. `VERIFIED`.
3. **`cache_dir`,** excluded deliberately at
   `src/feelies/core/platform_config.py:664` as "machine-specific, not
   provenance". Correct.
4. **The parity manifest fingerprint is a separate, unlinked artifact.**
   `manifest_fingerprint()` (`tests/determinism/parity_manifest.py:234`) covers
   the oracle; `config.snapshot().checksum` covers the run. Neither references
   the other, so "which oracle version accepted this run" is not recorded.
   `VERIFIED`.

**One latent risk, stated with its resolving test.** `default=str` in
`json.dumps` (`src/feelies/core/platform_config.py:648`) means any value not
handled by the branches above is serialized by `str()`, and for a plain object
that includes its memory address — which would make the checksum vary run to
run. Every field reachable today appears to be a primitive, `Path`, `Enum`,
`frozenset`, `tuple` or deep-copied container, so I did not observe a field that
reaches the fallback. I did not enumerate all fields to prove it, so this is
`ASSUMED`. It is decided by one assertion: build the same config twice in one
process and in two processes and compare `checksum`. That test does not exist.

---

## 8. Schema versioning mechanics — resolves CORE §F.7

**Target.** A contract version travels with the payload, not alongside it. One
compatibility rule, stated. A replay guarantee that survives evolution: a vN
log replays to its original output under vN+1 code, or the attempt fails loudly.

**Current state — `open defect`, and it is the §F item with the widest blast
radius.**

`tools/arch/evidence/contracts.json:events_with_version_field` is **empty**
across all **21** event classes. The base envelope
(`src/feelies/core/events.py:49`) is exactly four fields: `timestamp_ns`,
`correlation_id`, `sequence`, `source_layer`. There is no `schema_version` and
no per-type version. The evolution policy exists only as prose at
`src/feelies/core/events.py:15` — "All new types are strictly additive.
Existing events keep their schema" — which is a convention with no encoding and
no check. Events are appended to a replayable log
(`src/feelies/kernel/orchestrator.py:1601`), which makes this CORE §J's
"unversioned contracts persisted into a replayable event log". `VERIFIED`.

Producer versioning does exist and should not be confused with schema
versioning: `SensorReading.sensor_version`
(`src/feelies/core/events.py:622`) and
`HorizonFeatureSnapshot.feature_versions` (`:650`) record *which estimator*
produced a value. Neither records *what shape the record has*. `VERIFIED`.

**Which parity hashes survive a schema change — the answer P1 asks for, and it
is the uncomfortable one.**

| Change | Manifest outcome | Why |
|---|---|---|
| **Add a field to any event** | All 26 survive, silently | The hash input is a hand-written field list per helper. A new field is unhashed until a human edits a helper. `VERIFIED` (Phase 0 P-1). |
| **Change the value of an unhashed field** | All 26 survive, silently | Same mechanism. Phase 0 P-1 names two that change execution semantics: `OrderRequest.limit_price` and `OrderRequest.is_moc`. |
| **Rename a hashed field** | The owning helper raises `AttributeError` | Loud, but it surfaces as a test *error*, not a parity mismatch — the failure says "no attribute", not "output changed". `INFERRED`. |
| **Remove an unhashed field** | All 26 survive, silently | Same mechanism. |
| **Change a hashed value** | The owning baseline mismatches | This is the case the oracle is built for, and it works. |

So the oracle is strong against **behaviour** change and blind to **schema**
change, and those are the two failure modes versioning has to separate. The two
gaps compound: no version on the wire means a vN log cannot be identified, and a
field-list hash means the schema drift that identification would have caught is
invisible anyway.

**Resolution — the call, per CORE §H.**

- **Placement: on the base envelope**, one `schema_version: int` on `Event`
  (`src/feelies/core/events.py:30`), not per type. Twenty-one per-type versions
  is twenty-one things to forget; one envelope field is checkable at the
  boundary in one place. Per-type evolution is then expressed as an envelope
  version bump plus a migration entry, which keeps the log self-describing with
  one integer.
- **Compatibility rule: pinned-code-per-log, with refuse-and-fail-loud as the
  fallback.** Upgrade-on-read is the wrong choice here for a specific reason:
  it silently changes what a historical log replays to, which is precisely the
  guarantee CORE §C.11 exists to protect. A log records the schema version it
  was written under; replay under a code version that does not declare support
  for it **refuses**, naming both versions. Deliberate migration is then an
  explicit, recorded operation that produces a new log with a new fingerprint,
  never an implicit read-time rewrite.
- **Replay guarantee:** a vN log replays bit-identically under any code that
  declares vN support, and fails loudly under any that does not. There is no
  third outcome, and in particular no "mostly works".
- **Parity impact, stated up front because Phase 7 will need it:** adding
  `schema_version` to the base envelope adds a field to all 21 event types, and
  by the table above **that change breaks nothing** — every baseline survives,
  because a new field is unhashed until a helper is edited. That is convenient
  and it is also the defect. The step that adds the field and the step that
  brings it into the hashed field set are therefore two different steps with
  two different blast radii, and the second one re-pins baselines across the
  board.

---

## Required artifact — the determinism budget

Every source P1 names, with its neutralizer, the check that enforces the
neutralizer, and status. **A source with no named neutralizer is an open
defect, and is labelled as one in the status column** — not as accepted risk.
"No named check" in the third column means the neutralizer exists in code but
nothing prevents its removal.

| # | Source of nondeterminism | Neutralizer | Enforcing check | Status |
|---|---|---|---|---|
| 1 | **Hash seed** (`PYTHONHASHSEED` salts `str`/`bytes`/`tuple` hashing) | Canonical sorting at every hash site | `tests/determinism/test_hash_seed_independence.py:61` — 3 seeds × 8 streams in subprocesses, asserts one distinct output; CI runs `tests/determinism/` at `PYTHONHASHSEED: random` (`.github/workflows/ci.yml:114`) | `conformance-tested`, **scope gap**: 8 streams covered of 26 baselines. The `parity oracle` job runs at seed `0` (`.github/workflows/ci.yml:138`), so the APP baseline is never replayed under a random seed |
| 2 | **Dict iteration order** | Language guarantee — dicts are insertion-ordered. Not a source *unless* the dict was built from a set | Implicit in row 1 for covered streams | `implemented` for dicts built in deterministic order. One measured carrier: `src/feelies/portfolio/strategy_position_store.py:148` returns `{sym: … for sym in symbols}` over `symbols: set[str]` (`:145`), so the returned mapping's key order is seed-dependent |
| 2a | ↳ that dict reaching an ordered consumer | Sorting **at the consumer**: `src/feelies/kernel/orchestrator.py:2611` `for symbol in sorted(positions)`, with the comment at `:2608` naming Inv-5; other consumers reduce with exact `Decimal` sums (`src/feelies/risk/basic_risk.py:764`, `src/feelies/harness/backtest_report.py:193`) | **none** | **OPEN DEFECT** — the neutralizer is at three consumers, not at the source. A fourth consumer that iterates unsorted reintroduces seed dependence with no failing test |
| 3 | **Set iteration order** | `sorted()` before emission | **none** | `implemented`, **no named check**. Measured: **5** raw set iterations, all in tick-critical packages (`tools/arch/evidence/substrate.json:unsorted_set_iteration`). All five read and found order-insensitive: `src/feelies/composition/synchronizer.py:80` and `:83` are `h <= 0` validation predicates whose emission path uses the pre-sorted `_signal_horizons_sorted` (`:74`); `src/feelies/kernel/orchestrator.py:2938` deletes book entries, and deletion order does not affect the survivors; `src/feelies/signals/regime_gate.py:555` returns a `frozenset` (`:559`) used for membership; `src/feelies/portfolio/strategy_position_store.py:148` is row 2a. Nothing stops a sixth |
| 4 | **Float reduction order** | `math.fsum` over a lex-sorted key list — `src/feelies/composition/cross_sectional.py:78-79`, whose docstring at `:75` states the rule; money is `Decimal` end to end (`src/feelies/core/events.py:75`, `:101`) so PnL reductions are exact and order-free | `tests/determinism/test_transcendental_determinism.py:70` pins the `log`/`exp` sensor paths **intra-process only**; per-stream baselines catch a changed reduction where the stream is pinned | **partial** — 69 reduction sites in tick-critical packages, of which 5 use `fsum` (`tools/arch/evidence/substrate.json:float_reductions_hot`). The remaining 64 rely on deterministic *input* order, which rows 2 and 3 do not guarantee for a new call site |
| 5 | **Parallel reduction** | None exists on any decision path. The one pool, `ThreadPoolExecutor(max_workers=2)` at `src/feelies/ingestion/massive_ingestor.py:332`, fetches REST pages; its output is merge-sorted by `resequence_event_list` at `:283` before it reaches the log | The `CausalityViolation` raised by `src/feelies/storage/memory_event_log.py:117` if the sort is skipped | `implemented` |
| 6 | **RNG streams and seeding** | Local `random.Random(seed)` instances — `src/feelies/research/cpcv.py:457`, `:519`, default `seed=0` (`:439`). No global `random.seed()`, no `numpy.random`, no `secrets`, no `uuid` anywhere in `src/feelies/` | **none** | `implemented`, **no named check**. Cold path (engine 12) only. A `uuid4()` added to an event constructor fails nothing |
| 7 | **Wall-clock reads** | Injected `Clock` (`src/feelies/core/clock.py:13`); telemetry-only raw reads confined to an allowlist | `tests/acceptance/test_no_walltime_outside_clock.py:72` + stale-entry guard at `:96` | `conformance-tested`, **granularity gap** — the allowlist skips whole files (`:83`), including `src/feelies/kernel/orchestrator.py`. See §1 |
| 8 | **Thread and async scheduling** | Single-threaded tick path by construction; `SequenceGenerator` lock disabled in BACKTEST (`src/feelies/bootstrap.py:273`); `StateMachine` declares itself not thread-safe and names why it is currently safe (`src/feelies/core/state_machine.py:66-75`) | **none** | **OPEN DEFECT** — no test asserts the tick path is single-threaded. `SequenceGenerator`'s own docstring (`src/feelies/core/identifiers.py:31-39`) states that concurrent `next()` gives uniqueness but not reproducible order; nothing enforces the single-threaded precondition that makes replay valid |
| 9 | **Filesystem enumeration order** | `sorted(...)` wrapping the only `rglob` — `src/feelies/alpha/discovery.py:28`, with `discover_alpha_specs`'s docstring at `:42` stating "sorted alphabetically for deterministic load order" | **none** | `implemented`, **no named check**. Exactly 1 site in `src/feelies/` (`tools/arch/evidence/substrate.json:n_fs_enumeration`) |
| 10 | **Network arrival order** | Replay re-imposes order via `event_merge_sort_key`; BACKTEST enforces monotonicity in the log (`src/feelies/bootstrap.py:203`) and again in the feed (`src/feelies/ingestion/replay_feed.py:91`) | `CausalityViolation` at `src/feelies/storage/memory_event_log.py:117` and `src/feelies/ingestion/replay_feed.py:92` | **OPEN DEFECT for PAPER** — the guard is disabled in the only non-replay mode and disorder is neither counted nor emitted. See §2 |
| 11 | **ID generation** | Content-derived: `make_correlation_id` (`src/feelies/core/identifiers.py:9`), `derive_order_id` (`:18`). No UUID, no salted hash, no address-derived emitted identity | **none** | `implemented`, **no named check**. Nothing forbids `uuid`/`id()`/`hash()` in an event field — this is a two-line AST test of exactly the shape that already exists for wall-clock reads |
| 11a | ↳ **exactly-once submission across restart/reconnect** | In-process only: `src/feelies/execution/passive_limit_router.py:183`, `src/feelies/broker/ib/connection.py:364` | **none** | **OPEN DEFECT** — no durable submitted-order record. See §4 |
| 12 | **Dependency versions** | `uv sync --all-extras --locked` (`.github/workflows/ci.yml:79`) fails on a stale lockfile; Python pinned to `3.13` (`:70`) with the reason stated at `:67` | The CI step itself | **partial** — enforced in CI, absent from the run artifact. Neither `config.snapshot().checksum` nor `manifest_fingerprint()` records a code or dependency version (§7) |
| 12a | ↳ **libm / host math** | None possible in pure Python | The two whole-platform stream exemptions in `tests/determinism/test_parity_manifest.py:144` name it | `implemented` as a *declared* limit: per-engine parity is portable, whole-system parity is host-local. Honest, and it caps what any end-to-end oracle can assert |
| 13 | **Locale and timezone** | Explicit `ZoneInfo("America/New_York")` (`src/feelies/core/session_clock.py:20`); boundaries computed integer-exactly by splitting whole seconds from the sub-second remainder (`:41-44`), documented at `:36`. No `setlocale` anywhere; 1 locale/tz site total (`tools/arch/evidence/substrate.json:n_locale_tz_sites`) | **none** | `implemented`, **no named check**. The residual is the host **tzdata** version, which is unpinned and unrecorded — a tzdata change that moved a DST boundary would silently move every horizon grid anchored by `rth_open_ns` (`:47`) |
| 14 | **Cache and warm-start state** | Warm start is unreachable — the only `FeatureSnapshotStore` is in-memory (`src/feelies/storage/memory_feature_snapshot.py:16`) and constructed empty per boot (`src/feelies/bootstrap.py:359`), so replay always cold-starts | Nothing asserts it; the property holds by absence of an implementation | `implemented` **by accident**. See §5. The separate disk *event* cache is a data dependency, not a state carry: it gates `_BASELINE_TRADE_PARITY_HASH`, which is why that baseline is exempt |
| 15 | **Symbol-identity resolution** (splits, ticker changes, symbol reuse) | **none** | **none** | **OPEN DEFECT** — Phase 0 F.2 found no symbol-identity module, no ticker-change map, no corporate-action adjustment; symbols are bare `str` on every event. A replayed historical log cannot resolve identity the way it resolved then, and nothing can detect the divergence |

**Reading of the budget.** Fifteen sources; **6 open defects** (2a, 8, 10, 11a,
15, plus the PAPER half of 10 counted once); **5 sources whose neutralizer
exists in code with no check that keeps it there** (3, 6, 9, 11, 13); **3
conformance-tested with a named scope or granularity gap** (1, 4, 7).

The pattern is worth stating plainly, because it should shape the conformance
suite in Phase 6 more than any individual row: **the platform's determinism
rests largely on correct code rather than on enforced constraints.** The
sorted-before-emit discipline is real and consistently applied — the comments at
`src/feelies/kernel/orchestrator.py:2608`,
`src/feelies/composition/cross_sectional.py:75` and
`src/feelies/alpha/discovery.py:42` each name Inv-5 or determinism explicitly,
which means the authors knew. But five of those neutralizers have no test, so
the property is maintained by the same care that created it and will decay
exactly when that care is not present. Rows 3, 6, 9, 11 and 13 are each one
small AST test away from being enforced, and the template already exists in
`tests/acceptance/test_no_walltime_outside_clock.py`.

---

## Carried into later phases

- **U-8 (per-stream parity coverage) is still open** and Phase 5 needs it
  resolved; the union-of-names table is an upper bound, demonstrated as such by
  Phase 0 D-12.
- **Model finding: none.** No responsibility in this axis failed to fit an
  engine. Clocks, sequencing, the bus, identity and the parity oracle are
  kernel/cross-cutting per CORE §E, and each has a home.
- **Dead-code candidates flagged, not actioned** (CORE §H): `subscribe_all` and
  its `_global_handlers` loop (§3), and the shutdown checkpoint path whose store
  is always in-memory (§5).
- **Phase 2 dependency:** §2 established that the platform has no global event
  ordinal — `sequence` is unique within one of 26 spaces and the total-order key
  covers 2 of 21 types. Any contract sheet that assumes two events of different
  types can be ordered against each other is assuming something the substrate
  does not provide.

## Verification performed on this document

- `tools/arch/substrate.py` was written for this phase and its output committed
  as `tools/arch/evidence/substrate.json`. Two of its heuristics produced wrong
  headline numbers on the first run and were corrected before any number here
  was written — both corrections are recorded in the evidence base above rather
  than quietly fixed.
- Every claim marked `VERIFIED` was read at the cited line. The five set
  iterations in budget row 3 and the three consumers in row 2a were each read
  individually rather than counted, because the measurement can only find the
  sites and not tell whether order matters at them.
- The one claim I could not settle is labelled `ASSUMED` with the test that
  would settle it: the `default=str` fallback in `PlatformConfig.snapshot`
  (§7).
- **Citation check: full coverage, not a sample.** `measure.py spotcheck … -n
  200` over all **101** distinct citations, **0 failures**. Before that, 2 of
  101 failed — both the abbreviated-path defect Phase 0 hit, here caused by
  quoting the wall-clock allowlist's own keys, which are relative to
  `src/feelies`. Both were expanded to repo-root paths.
- **A correction to Phase 0's account of what `spotcheck` proves.** Phase 0's
  verification note says it "verifies that the file exists and the line is
  within EOF". It does not check the line. `cmd_spotcheck`
  (`tools/arch/measure.py:536`) reads `if sym and not sym.isdigit():` before
  the content check, so for a `path:line` citation it verifies **file existence
  only**; the substring check applies solely to `path:symbol` citations. A
  clean run is therefore weaker evidence than Phase 0 credited it with, which
  is why every `VERIFIED` line here was read directly.
- `tools/arch/measure.py` and its `CONFIG` block were not edited. Writes were
  confined to `docs/architecture/target/out/` and `tools/arch/`.
- Scope guard: `scope: OK -- no protected-path changes`.

**HARD STOP.** Phase 1 complete. Phase 2 not begun.
