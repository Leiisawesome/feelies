**Basis.** This phase has no repo access by design (P2), so every current-state claim below is carried from Phase 0 / Phase 1 at the label those documents assigned it; nothing is upgraded from `INFERRED` to `VERIFIED` here. New material is target-state specification and is labelled `specified`.

---

## ENGINE 1 — Market Data

**ENGINE:** 1. Market Data

**LATENCY CLASS:** `hot` (CORE §D — engine 1 is the ingress of the tick-critical chain).
Two engine-1 entry points execute off the tick loop and are not a local redefinition of §D: batch resequencing at ingest (`src/feelies/ingestion/massive_ingestor.py:283`) and cache-replay construction (`src/feelies/storage/cache_replay.py:150`). Both complete before the tick loop consumes an event; neither is reachable from a hop in Phase 0 D0.4.

**OWNS:**

1. **Wire→canonical translation.** Sole authority converting a vendor frame into `NBBOQuote` / `Trade`. No other engine parses a vendor payload.
2. **Time-base stamping.** Event time from the venue field; ingest time from the injected `Clock`; declares which envelope field carries which base. Target rule: `timestamp_ns == exchange_timestamp_ns` on every engine-1 emission, because Phase 1 §1 measured that 20 of 21 event classes document nothing about `timestamp_ns` and engine 1 is the first producer in the chain.
3. **Intra-stream total order.** `event_merge_sort_key = (exchange_timestamp_ns, symbol, event_type_rank, sequence)` (`src/feelies/storage/event_resequence.py:33`), quotes before trades. Engine 1 owns the ordering of its own stream and the monotonicity guard over it.
4. **Sequence stamping within the market-data sequence space**, reassigned contiguously on resequence together with correlation IDs (`src/feelies/storage/event_resequence.py:57-68`). It owns the stamping, not the generator: `SequenceGenerator` is kernel (`src/feelies/core/identifiers.py`).
5. **Duplicate rejection and corruption classification** — `(sequence_number, content_fingerprint)` comparison, terminal `CORRUPTED` on a reused vendor sequence carrying different bytes.
6. **Gap detection and notification** — feed interruption, queue shed, and reorder, each counted and surfaced as a health transition.
7. **Validation and quality flagging** — crossed, locked, zero/negative side, size anomaly, staleness beyond a declared tolerance. Engine 1 *classifies*; it never repairs, never interpolates, and never suppresses without emitting.
8. **Venue-published symbol status as observed** (halt, resume, SSR) — the observation only. Who publishes the *authoritative* halt state is CORE §F.3 and is not resolved on this sheet.
9. **Persistence and replay of the canonical market-data stream.**

**MUST NOT OWN:**

- **Derived price levels** — mid, micro-price, spread, imbalance. These are engine 2 estimators. This line is load-bearing: it is what makes Phase 0 D0.4's `if mid > 0` guard at `src/feelies/kernel/orchestrator.py:1607` a downstream symptom rather than a downstream fix.
- **The trading-blocked decision.** Engine 1 publishes health; it does not veto. `_data_health_blocks_trading` (`src/feelies/kernel/orchestrator.py:5263`) is a gate over engine 1's output and belongs to the gate ladder (Phase 3), not to this engine.
- **Marking, positions, P&L** — engine 7. Phase 0 D0.4 hops 9 and 11 perform marking inside engine 1's ingress handler; that is placement, not ownership, and the sheet does not grant it.
- **Universe membership** (CORE §F.1). Engine 1 emits what arrives; it does not decide what is in play.
- **Symbol identity across corporate actions** (CORE §F.2). Unowned platform-wide; see the assumption registered below.
- **Halt/SSR *policy*** — blackout windows, locate requirements, admission consequences (engines 9/10).
- **Backpressure policy.** Engine 1 owns the shed-and-notify *mechanism* at the wire; whether and when the platform sheds is CORE §F.6 and is deferred.
- **Any interpretation of what a quote means.** No feature math, no regime label, no signal semantics.

**CONSUMES:**


| Input                                                                        | Staleness / validity tolerance                                                                                                                                                                          |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Raw vendor frames (`bytes`)                                                  | None. A frame is parseable or rejected-with-emission.                                                                                                                                                   |
| Injected `Clock` (`src/feelies/core/clock.py:13`)                            | Ingest-time stamping only. In BACKTEST the simulated clock does not advance during batch ingest (`src/feelies/core/events.py:66`), so ingest time is emitted **absent**, never as a meaningless number. |
| Exchange calendar / session anchors (`src/feelies/core/session_clock.py:20`) | Declared per session; residual staleness is the host **tzdata** version, unpinned and unrecorded (Phase 1 budget row 13).                                                                               |
| Symbol identity map                                                          | **Does not exist** (Phase 0 F.2). Until it does, `symbol` is an unresolved bare `str` and that is a registered assumption, not a silent one.                                                            |


**EMITS:**


| Contract                  | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NBBOQuote`               | Prices `Decimal` in quote currency; sizes integer shares. `exchange_timestamp_ns` = event time, ns since epoch UTC; `received_ns` = ingest time or absent. Provenance: feed id, tape/venue, vendor sequence, `normalizer_version`, `schema_version`, `source_layer` (non-null). Quality flags present on every emission — clean is an explicit value, never an absence. |
| `Trade`                   | Same envelope and same obligations.                                                                                                                                                                                                                                                                                                                                     |
| Health / gap notification | Per-symbol state in `never-seen / stale / degraded / corrupted / healthy`, with transition cause and counts of frames dropped, reordered and deduped since the previous transition. `CORRUPTED` is terminal (`src/feelies/ingestion/data_integrity.py:58`).                                                                                                             |
| Rejection record          | Exactly one per non-emitted frame.                                                                                                                                                                                                                                                                                                                                      |
| Venue status observation  | Halt / resume / SSR as observed on the wire, with venue provenance. Authoritative state pending §F.3.                                                                                                                                                                                                                                                                   |


**Ordering guarantee published to consumers:** strictly increasing `event_merge_sort_key` within the market-data stream, in every mode. **No** ordering guarantee holds between an engine-1 emission and any other engine's emission — Phase 1 §2 established 26 sequence spaces and no global ordinal, and flagged this as the Phase 2 dependency. Any consumer that orders a quote against a non-market-data event is assuming something the substrate does not provide.

**FORBIDDEN READS:** positions, marks, P&L (7); risk state and limits (8); signals and forecasts (4); regime state (3); alpha registry, manifests, `alpha_id`, archetype, horizon (4/5); order state (9/10); any clock other than the injected `Clock`.

Enforcement, in order of strength: (a) **constructor injection at the composition root only** — engine 1 holds no reference through which any of the above is reachable, which is the only enforcement that does not depend on a test being written; (b) an **import-boundary test** failing on any import from those packages into `ingestion/`, using the AST-walk template that already exists at `tests/acceptance/test_no_walltime_outside_clock.py:72`; (c) the **alpha-literal static check** (CORE §I) run tree-wide — Phase 0 E-1 found 2 leaks and both are in `src/feelies/core/platform_config.py`, i.e. not in engine 1, which is exactly why the check must not be scoped to where leaks were already found; (d) a **call-granular** clock check, since the current allowlist skips whole files (Phase 1 §1).

**STATE:**

- Per-`(symbol, feed_type)` last-seen `(sequence_number, content_fingerprint)` — **one row deep**, which is the entire duplicate window in the platform (Phase 1 §4).
- Per-symbol integrity state, including terminal `CORRUPTED`.
- Drop / reorder / dedupe counters.
- Ingress queue occupancy.
- Resequence batch buffer (offline entry points only).
- Event-log tail key for the monotonicity guard.
- Observed venue-status set.

**Deterministic reset path: none today.** `MassiveNormalizer` sets 17 attributes in `__init__`, mutates 7 elsewhere, and has no reset/restore/clear/checkpoint method (Phase 1 §5). Target: one `reset()` restoring every unit above to its cold-start value, with **cold start declared as the only replay contract** (Phase 1 §5 call), proven by construct → feed → `reset()` → feed-same → identical stream.

**ON DEGRADED INPUT:** exposure-reducing, and in every branch it emits.


| Condition                                    | Behaviour                                                                                                                                                                                        |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Parse failure                                | Reject the frame, emit a rejection, increment counter. No canonical emission.                                                                                                                    |
| Duplicate vendor sequence, identical payload | Drop, count, emit on health transition.                                                                                                                                                          |
| Same vendor sequence, different payload      | Symbol → `CORRUPTED` (terminal), emit. Consumers fail closed.                                                                                                                                    |
| Gap / feed interruption / queue shed         | Health degrade plus notification. The ingress queue already does this correctly (`src/feelies/ingestion/massive_ws.py`, `notify_feed_interrupted`) and is the model every other path must match. |
| Out-of-order arrival within the stream       | Count and emit, **in every mode**. PAPER accepts silently today (`src/feelies/bootstrap.py:203`) — Phase 1 §2 `open defect`.                                                                     |
| Crossed / locked / zero-side quote           | Emit with the flag set; consumers gate. Engine 1 does not decide whether a flagged quote is tradeable.                                                                                           |
| Ingest time unavailable (BACKTEST)           | Absent, not zero.                                                                                                                                                                                |


**ON EXCEPTION:** contained per frame, and never silent. A raise while translating a frame rejects that frame with an emission and continues; a raise in the **persistence** path **halts** ingestion, because continuing to emit events that were not logged breaks replay quietly, which is the one failure this engine exists to prevent. Currently there is no engine-local boundary: the tick-wide `try/except` at Phase 0 D0.4 hop 2 catches an engine-1 raise as a generic tick failure, drives macro `DEGRADED`, and leaves partial mutation unrolled.

**SUBSTITUTABILITY:** a replacement must (i) emit the same canonical types with the same fields, units and time bases; (ii) satisfy the same total-order key and monotonicity guard; (iii) discharge the same notification obligations in full — the conservation identity below, not a subset; (iv) expose the same `reset()`; (v) read no clock but the injected one; (vi) be constructible at the composition root holding no other engine's reference. **The concrete boundary test:** the CORE §I fixture suite (null, shape-adversarial, pathological) must run against a synthetic market-data source with zero edits under `kernel/`, `bus/`, `core/`, `composition/`, `risk/`, `execution/` (CORE §G.1). If a synthetic tape cannot be substituted for the vendor adapter, this boundary is prose.

**CONFORMANCE TEST:**

1. `market_data_canonical` **parity baseline.** Fixed raw-frame fixture → `MassiveNormalizer.on_message` (`src/feelies/ingestion/massive_normalizer.py:280`) → hash the emitted stream over the **full declared field set**, `Decimal` fields as exact strings rather than `.6f`. No transcendental math, so it is portable and enters the manifest as an entry, not an exemption. Phase 1 §6.1 rates this the cheapest coverage gain in the substrate and it requires no production change.
2. **Ingress conservation.** `frames_in == emitted + rejected + dropped + deduped`, and `|notifications| == |non-emitted|`, per symbol per run. This is the test that makes "dropping without notification is not allowed" mechanical.
3. **Ordering.** Strictly increasing merge key on the emitted stream in every mode, with the out-of-order counter asserted non-silent under PAPER.
4. **Reset determinism.** As specified under STATE.
5. **Forbidden-read import/AST test.**
6. **Quality-flag totality.** Every emission carries a flag set; there is no clean-by-absence.

**GAP vs CURRENT:** engine-1 responsibility is split across `ingestion/`, `storage/` and five orchestrator methods (Phase 0 D0.2, `_update_halt_state:5014` through `_verify_data_integrity:5379`), and its canonical stream is the only hot-path output carrying no schema version (Phase 0 C-1), no producer version (Phase 1 §8), and no parity baseline of its own (Phase 0 D0.6 / Phase 1 §6.1) — so the platform's first contract is the least pinned one in it.

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** No clause above required naming the live alpha or any `alpha_id`. Clean.

`OWNS` **overlaps flagged, not split (CORE §C.6).** Three, all real:

1. **Sequence.** Engine 1 stamps; the kernel owns the generator. Resolved on this sheet by splitting *stamping* from *allocation* — the split holds because `resequence_event_list` already reassigns sequences within engine 1's stream.
2. **Ordering mechanism vs. ordering rule.** `event_merge_sort_key` is a platform-wide discipline that lives inside engine 1 and covers 2 of 21 event types (Phase 1 §2). **The call:** the *key protocol and monotonicity guard* are kernel; engine 1 is their first and currently only client. Leaving the mechanism inside engine 1 is what makes the other 19 types orderless — and that is the thing to fix in Phase 3, not by widening engine 1.
3. **Halt.** CORE §F.3 states the straddle explicitly. Engine 1 claims *observation* only; authoritative state is deferred to the §F pass, after all twelve sheets.

**Model finding: none on this sheet.** No engine-1 responsibility failed to fit, and no irreconcilable pair was found. The ordering-mechanism tension in (2) is a placement question with a clean answer, not a model defect.

**Open defects inherited that this contract does not create and must not be read as closing:** PAPER accepts reordering silently (Phase 1 §2); a data-health-blocked quote leaves no record at all when no normalizer is wired (Phase 0 D0.4 hop 5, `src/feelies/kernel/orchestrator.py:1586`); `SymbolHalted` has zero subscribers in any mode (Phase 0 C-4); `MassiveNormalizer` has no reset path (Phase 1 §5).

**Assumption registered.** Whether `NBBOQuote` carries a quality-flag field *today* is not established by Phase 0 or Phase 1 — Phase 1 §6.1 gives 7 of 19 field names reaching a hash but does not name the field set. The EMITS clause states the requirement regardless; confirming the current field is a Phase 5 gap-table item, not a claim made here.

## ENGINE 2 — State / Feature

**ENGINE:** 2. State / Feature

**LATENCY CLASS:** `hot` (CORE §D). Sensor fan-out is Phase 0 D0.4 hop 13 and carries one of the two always-on tick timers (`sensor_fanout_ns`, `src/feelies/kernel/orchestrator.py:2131`). One declared cold sub-surface: the shutdown checkpoint / boot restore pair (`_checkpoint_feature_snapshots:5454`, `_restore_feature_snapshots:5423`), which Phase 1 §5 found unreachable in practice.

**OWNS:**

1. **Event-time microstructure estimation.** Incremental estimators over the market-data stream, one per declared `SensorSpec`. Sole producer of every derived microstructure quantity — including mid, micro-price, spread and imbalance, which the engine-1 sheet declined precisely so that they land here and nowhere else.
2. **Horizon-boundary snapshot assembly.** Fan-in of per-sensor readings into one `HorizonFeatureSnapshot` per (symbol, horizon) boundary.
3. **Validity and staleness metadata.** `warm` and `stale` per feature, and the target addition of `valid` and `unit` per feature. This is the one engine whose CORE §E metadata obligation is already partly discharged in code (`src/feelies/core/events.py:650`).
4. **Producer versioning.** `SensorReading.sensor_version` (`src/feelies/core/events.py:622`) and `HorizonFeatureSnapshot.feature_versions` (`:650`) — the only producer versioning in the platform (Phase 1 §8), and the template the engine-1 sheet borrowed for `normalizer_version`.
5. **Warmup accounting.** `min_history` per sensor; a feature below it is `warm=False` and is never extrapolated to.
6. **The declared feature interface to the decision layer** — one interface per horizon boundary, carrying the metadata above.

**MUST NOT OWN:**

- **Trade decisions and thresholds with trading semantics.** A sensor may emit realized variance; it may not emit "vol is high." The distinction is that a threshold with a trading consequence is engine 4's or engine 8's, and a classification label is engine 3's.
- **Regime labels.** Engine 3 owns classification. Engine 2 must additionally *not read* regime output — see FORBIDDEN READS; the two would otherwise form a cycle, since classification consumes estimates.
- **Position, marks, P&L, fills** (7). Pure functions of the event prefix cannot be functions of the book.
- **The horizon grid definition** — pending, and this sheet does not claim it. See the §F-class finding below.
- **Session and halt state** (§F.3). Engine 2 consumes the session anchor; it does not produce it.
- **Peer sensor state.** No sensor reads another sensor's accumulator. See the independence test.

**CONSUMES:**


| Input                                                                      | Staleness / validity tolerance                                                                                                                                                                                                                                                                                                            |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NBBOQuote`, `Trade` from engine 1                                         | Per-sensor declared staleness bound; beyond it the affected features are `stale=True`, not dropped. A quality-flagged input (crossed, locked, zero-side, per the engine-1 sheet) is **either** excluded with the affected features marked, **or** included with the flag propagated into the snapshot metadata — never silently absorbed. |
| Horizon boundary trigger (`HorizonTick`)                                   | Boundary-driven, "usually zero ticks" per Phase 0 D0.4 hop 21. A missed boundary is a gap and must emit.                                                                                                                                                                                                                                  |
| `SensorSpec` set, resolved at composition                                  | Read once at composition, never re-read per event (CORE §C.10 discipline applied to features). Covered by the run fingerprint: `sensor_version`, `module.qualname`, `params`, `subscribes_to` sorted, `min_history`, `throttled_ms`, `stateful` (`src/feelies/core/platform_config.py:667-681`).                                          |
| Session anchor for boundary times (`src/feelies/core/session_clock.py:47`) | Residual staleness is the host **tzdata** version — unpinned and unrecorded, and Phase 1 budget row 13 states a tzdata change "would silently move every horizon grid."                                                                                                                                                                   |
| Injected `Clock`                                                           | **Not consumed on the estimator path at all.** Every time value engine 2 uses is the event's. See the throttle question registered below.                                                                                                                                                                                                 |


**EMITS:**


| Contract                  | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SensorReading`           | Per-feature value with a **declared unit** (target addition), `timestamp_ns` = the event time of the last event in the prefix that produced it, `sensor_version`, source event provenance. Intra-engine transport — see the interface finding below.                                                   |
| `HorizonFeatureSnapshot`  | Per-(symbol, horizon) map of feature → value, with **totality**: every feature present in `values` has an entry in `warm`, `stale`, `unit`, `valid` and `feature_versions`. `timestamp_ns` = the boundary event time, not the assembly time. Provenance: `source_sensors`, horizon id, boundary index. |
| Boundary-gap notification | A boundary that produced no snapshot, or a snapshot missing a configured sensor, emits. Absence is otherwise indistinguishable from "not configured."                                                                                                                                                  |


**FORBIDDEN READS:** positions, marks, P&L, fills (7); risk state and limits (8); signals and forecasts (4); order state (9/10); regime output (3) — forbidden in this direction specifically to keep the estimate → classify edge acyclic; alpha registry, manifests, `alpha_id`, archetype, horizon constants (4/5, CORE §C.7); any clock other than the event's own timestamps; **another sensor's internal state**.

Enforcement: (a) constructor injection at the composition root; (b) an import-boundary test over `sensors/` and `features/`; (c) the tree-wide alpha-literal check (CORE §I); (d) the sensor-independence test below, which is what makes (a)–(c) meaningful given that the subscriber set is config-derived at `src/feelies/sensors/registry.py:193`.

**STATE:** per-(symbol, sensor) incremental accumulators; warmup counters against `min_history`; throttle cursors; last-emitted reading per feature; the current boundary's fan-in buffer; the horizon boundary cursor.

**Deterministic reset path: none uniform.** Phase 1 §5 measured 32 of 38 state-mutating classes with no reset/restore/clear/checkpoint of any kind. Engine 2 additionally has a *misleading* one: the checkpoint/restore pair exists in the kernel against a store that is always empty — the only `FeatureSnapshotStore` is in-memory (`src/feelies/storage/memory_feature_snapshot.py:16`), constructed empty per boot (`src/feelies/bootstrap.py:359`), so the restore path is unreachable and the shutdown SHA-256 runs for nothing (Phase 1 §5). **Target: cold start is the only start**, stated in the type; `reset()` restores every unit above; warm start is admissible only if the snapshot is content-addressed and its identity enters the run fingerprint.

**ON DEGRADED INPUT:** exposure-reducing, and metadata-emitting rather than suppressing.


| Condition                            | Behaviour                                                                                                  |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| Below `min_history`                  | `warm=False`. Feature present, value not consumed by any gate that requires warmth.                        |
| Beyond staleness bound               | `stale=True`. Present, flagged, never extrapolated.                                                        |
| Quality-flagged input from engine 1  | Excluded-and-marked, or included-with-flag-propagated. Declared per sensor, not per call site.             |
| Input gap / missed boundary          | Emit the gap. A snapshot is never silently thinner.                                                        |
| A configured sensor produced nothing | Feature present with `valid=False`, **never absent**. Absence reads as "not configured" to every consumer. |


The suppression prohibition is load-bearing for engine 6: Phase 0 D0.7 F.1 records that a universe mismatch "degrades the barrier rather than failing the load," so a silently-thin snapshot degrades the composition barrier by exactly the same mechanism instead of failing it.

**ON EXCEPTION:** contained per sensor, and must emit. One raising sensor must not take down the fan-out; it is marked failed, its features are emitted `valid=False`, and a notification is published. Containment must not become fail-quiet — Phase 0 E-2 found two decision-path handlers that neither raise, return, nor log, and this engine's per-sensor containment is exactly the shape that invites a third. A raise in snapshot *assembly* (as opposed to one sensor) halts the boundary and emits, because a partially assembled snapshot with complete-looking metadata is worse than no snapshot.

**SUBSTITUTABILITY:** a replacement must (i) emit both canonical types with the same field set, units and time bases; (ii) satisfy metadata totality; (iii) be attachable and detachable **by configuration alone** — new `SensorSpec` entries, zero edits under `kernel/`, `bus/`, `core/`, `composition/`, `risk/`, `execution/` (CORE §G.1); (iv) expose `reset()`; (v) read no clock. **The concrete boundary test:** the CORE §I shape-adversarial fixture — different horizon, multi-symbol, different cadence — must attach here by config, and the null fixture must leave the platform stable with an empty feature set. Engine 2 is where §G.1 is most testable today, because `src/feelies/sensors/registry.py:193` already builds its subscription set from `spec.subscribes_to` rather than from code.

**CONFORMANCE TEST:**

1. **Prefix purity.** Same event prefix, cold start, two processes, `PYTHONHASHSEED=random` → identical `SensorReading` and `HorizonFeatureSnapshot` streams. Engine 2 already holds 5 of the 26 parity baselines (`level1_sensor_reading`, `level1_v03_sensor_reading`, `multi_symbol_sensor_reading`, `level2_horizon_tick`, `level3_horizon_feature_snapshot` — Phase 1 §6), the most of any engine; the extension needed is confirming which of them are inside the 8 streams covered by `tests/determinism/test_hash_seed_independence.py:61`.
2. **Metadata totality.** Every feature in `values` has `warm`, `stale`, `valid`, `unit` and `feature_versions`. This is the mechanical form of CORE §C.8 and it fails on the first undeclared unit.
3. **Throttle time-base test.** Replay the same prefix with wall time advanced differently between events; output must be byte-identical. This decides the `throttled_ms` question below and is the single highest-value test on this sheet.
4. **Sensor independence.** Permute registration order of mutually-independent sensors; output must be identical. Phase 1 §3 established that registration order is an output-determining input pinned by nothing but six prose comments in `build_platform`, and engine 2's order is config-derived — so this test is what converts "sensors happen not to read each other" into an enforced property.
5. **Immutability.** Snapshot containers must be tuples or frozen mappings. Phase 0 C-7 lists `HorizonFeatureSnapshot` with **five** mutable container fields — `values`, `warm`, `stale`, `source_sensors`, `feature_versions` — the most of any of the 21 event types, and `frozen=True` blocks none of it.
6. **Cascade depth.** Assert a stated maximum publish depth from a `HorizonTick`; Phase 1 §3 requires the bound and none exists.
7. **Config-attach.** Add a sensor by config only; assert zero diff outside `configs/`, and assert `config.snapshot().checksum` moves — engine 2's wiring is genuinely inside the fingerprint, which is the positive case Phase 1 §7 contrasts against alpha manifests.

**GAP vs CURRENT:** engine 2 is the best-instrumented engine in the platform — five parity baselines, real producer versioning, warm/stale metadata, sensor wiring inside the run fingerprint — and its structural gaps are the reverse of engine 1's: its principal emission is the most mutable event in the system (Phase 0 C-7, five container fields) and its state-management pair lives in the kernel against a store that is always empty (Phase 0 D0.2 `_restore_feature_snapshots:5423` / `_checkpoint_feature_snapshots:5454`; Phase 1 §5).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean. No clause required naming an alpha, symbol, archetype or horizon constant.

**§F-class finding — an eighth unassigned responsibility, not in CORE §F.1–7: the horizon grid.** Which horizons exist, when their boundaries fall, and what anchors them is a fact consumed by at least four places at the same event time, with no single producer:


| Consumer                          | Site                                                                                                                                               |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Scheduler that emits the boundary | `HorizonScheduler` in `sensors/` (Phase 0 D0.2), published from `src/feelies/kernel/orchestrator.py:1223`, `:1252`                                 |
| Snapshot assembly                 | `src/feelies/features/aggregator.py:253`                                                                                                           |
| Composition barrier               | `src/feelies/composition/synchronizer.py:130`, holding its own `_signal_horizons_sorted` at `:74` (Phase 1 budget row 3)                           |
| Anchor                            | `rth_open_ns` (`src/feelies/core/session_clock.py:47`), whose tzdata dependence Phase 1 row 13 names as able to "silently move every horizon grid" |


This is structurally identical to §F.1 (universe): several engines must see the same fact at the same event time, and none owns it. **Recommended owner: engine 2**, which already owns boundary snapshots and would publish the grid as a versioned contract — but §F resolutions belong to the pass after all twelve sheets, and this item is not in §F at all, so it is recorded for the operator rather than resolved here (CORE §A).

`OWNS` **overlaps flagged, not split (CORE §C.6):**

1. `HorizonTick` **publisher placement.** The scheduler is engine 2 and lives in `sensors/`, but the publish happens in the orchestrator (`:1223`, `:1252`). Placement, not an ownership contest — engine 2 owns the contract regardless of who currently calls `publish`.
2. **Two feature paths into engine 4.** `SensorReading` is subscribed directly by `src/feelies/signals/horizon_engine.py:197` *as well as* `HorizonFeatureSnapshot` at `:198`. The snapshot is where the warm/stale/unit metadata lives, so the reading path is a metadata-thinner route into the decision layer. **The call:** the snapshot is the decision interface; `SensorReading` is intra-engine-2 transport and should not be a decision input. The consequence of the current dual path is `INFERRED` — Phase 0 records the subscription, not what engine 4 does with it — so this is a Phase 3 flow item and a Phase 5 gap row, not a defect asserted here.
3. `storage/` **package overlap.** `src/feelies/storage/feature_snapshot.py` (engine 2) shares a package with the engine-1 event log and §F.2 reference data (Phase 0 D0.2). Per-module ownership is clear; the package boundary is not.

**Model finding: none.** The per-event estimation / boundary assembly seam is real but is already reflected in the `sensors/` ÷ `features/` split, and both halves share one purity and metadata contract. Not two irreconcilable jobs.

**Assumptions registered:**

- `throttled_ms` **time base is undetermined.** It is a declared per-sensor parameter inside the run fingerprint (`src/feelies/core/platform_config.py:667-681`), and whether it is evaluated in event time or wall time decides whether engine 2 is a pure function of the event prefix. Phase 0 and Phase 1 enumerate the 12 missed `perf_counter_ns` reads as being in `src/feelies/kernel/orchestrator.py` and `src/feelies/core/state_machine.py` only, but do not enumerate the 16 `time.monotonic` sites, so `sensors/` is neither cleared nor implicated. Resolved by conformance test 3, or by reading the throttle predicate.
- **Per-feature units are not known to exist today.** CORE §C.8 says a field whose unit is not declared does not exist; the EMITS clause requires the declaration. Whether `SensorReading` carries one now is a Phase 5 gap-table item.
- **U-4 remains open and is engine 2's boundary.** Whether `SensorSpec.subscribes_to` can name a type outside the 21-type closure in `src/feelies/core/events.py` (Phase 0 D0.8 U-4) determines whether engine 2's input contract is closed. It should be resolved before Phase 6.



## ENGINE 3 — Regime

**ENGINE:** 3. Regime

**LATENCY CLASS:** `hot` (CORE §D). Phase 0 D0.4 hop 19 sits on the quote leg — `_update_regime` at `src/feelies/kernel/orchestrator.py:1648` → `:2432`, publishing `RegimeState` at `:2476` — with the hazard spike at hop 20 (`:2515`). One declared cold sub-surface: calibration (`_calibrate_regime_engine:2335`) and the shutdown checkpoint (`_checkpoint_regime_snapshot:5460`).

**OWNS:**

1. **The single shared market-state classification.** One classifier, one worldview, published once. CORE §E states the reason in the prohibition itself — "three classifiers means three worldviews and no attribution" — and this is the engine where that is enforced rather than hoped for.
2. **Regime-break hazard.** The rate at which the current classification is expected to fail, published as its own contract (`RegimeHazardSpike`).
3. **Classifier versioning.** Which classifier, which parameter set, which calibration produced this label — travelling on the emission, not in a log line.
4. **Calibration lifecycle.** When calibration runs, on what window, and with what determinism guarantee; a recalibration is a versioned, recorded event, never an in-place parameter mutation.
5. **The single read path for a regime label.** `src/feelies/services/regime_state_cache.py` is already declared as this at `src/feelies/bootstrap.py:289` (Phase 0 D0.2) — the strongest existing instance of CORE §C.6 in the platform, and this sheet ratifies it rather than inventing it.

**MUST NOT OWN:**

- **Trading thresholds.** Engine 3 says "the state is X with hazard h"; it never says "therefore do not trade." Consumption thresholds belong to engines 4 and 8 and to the gate ladder (Phase 3).
- **Alpha-private regime state.** Explicitly prohibited by CORE §E. This is a *forbidden emission* as much as a forbidden read: engine 3 must not offer a per-alpha or per-archetype classification surface, because that is how three worldviews arrive by configuration rather than by code.
- **Session and halt state as a regime** (§F.3). Engine 3 may *consume* an authoritative session/halt state once §F.3 assigns a producer; it must not derive one from the tape and publish a competing answer. This is the specific straddle CORE §F.3 warns about.
- **Feature estimation** (2). Engine 3 classifies over engine-2 estimates; it does not compute its own microstructure quantities. A private estimator here is a second production path for a fact engine 2 owns (CORE §C.6).
- **Exit decisions.** `RegimeHazardSpike` is an observation. That `src/feelies/risk/hazard_exit.py:141` turns it into an `OrderRequest` at `:253` is engine 8/9 policy consuming engine 3's fact, and this sheet grants engine 3 no share of it.
- **Position, P&L, risk state, order state.**

**CONSUMES:**


| Input                                                                             | Staleness / validity tolerance                                                                                                                                                                            |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Engine-2 features (event-time estimates with `warm` / `stale` / `valid` / `unit`) | Declared per input feature. A `warm=False` or `valid=False` input must produce a classification of declared lower confidence or an explicit `unknown`, never a label computed as if the input were sound. |
| Engine-1 quality flags, propagated through the snapshot                           | A crossed or zero-side tick must not move a classification silently.                                                                                                                                      |
| Session anchor (§F.3, pending)                                                    | Consumed once assigned; not derived.                                                                                                                                                                      |
| Calibration window and parameters, resolved at composition                        | Read at composition, never re-read per event.                                                                                                                                                             |


**EMITS:**


| Contract                        | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RegimeState`                   | Label from a **closed, versioned enumeration**; confidence with a declared scale; `timestamp_ns` = the event time of the last input in the prefix, not the assembly time; provenance: `classifier_version`, calibration id, the feature set and versions it consumed, and an `unknown`/degraded marker. |
| `RegimeHazardSpike`             | Hazard with a **declared unit and horizon** — a rate is meaningless without both, and CORE §C.8 makes an undeclared unit a non-existent field. Same envelope and provenance obligations.                                                                                                                |
| Classification-gap notification | A tick whose classification could not be computed emits. Silence must not read as "state unchanged."                                                                                                                                                                                                    |


**Emission discipline the contract must publish:** whether `RegimeState` is emitted every tick or only on change is a contract property, not an implementation detail, because it determines whether a consumer's staleness check is meaningful. **The call: emit on change plus a declared heartbeat**, so a consumer can distinguish "unchanged" from "not running" without reading engine 3's internals.

**FORBIDDEN READS:** positions, marks, P&L, fills (7); risk state and limits (8); signals and forecasts (4) — forbidden in this direction to keep classify → forecast acyclic, exactly as engine 2's regime prohibition keeps estimate → classify acyclic; order state (9/10); alpha registry, manifests, `alpha_id`, archetype, horizon constants (4/5, CORE §C.7); raw vendor frames (1) — engine 3 reads engine-2 output, never the wire; any clock other than the injected one, and none at all on the classification path.

Enforcement: (a) constructor injection at the composition root; (b) an import-boundary test over `services/`; (c) the tree-wide alpha-literal check (CORE §I); (d) a **singleton-classifier check** — assert exactly one construction of a regime classifier in the composition root and exactly one publisher of `RegimeState`, which is the only mechanical defence of the "one worldview" rule and does not exist today.

**STATE:** current label and confidence per symbol (or per market, if the classification is market-wide — see the assumption below); the classifier's own accumulators and history window; hazard estimator state; calibration parameters and their version; last-emitted label for change detection; heartbeat cursor.

**Deterministic reset path: none.** Phase 1 §5's measurement covers this engine — 32 of 38 state-mutating classes have no reset of any kind. Engine 3 additionally carries the misleading-checkpoint pattern the engine-2 sheet flagged, in its own form: `_checkpoint_regime_snapshot:5460` runs a SHA-256 at every shutdown against a restore path Phase 1 §5 found unreachable. **Target: cold start is the only replay contract**, one `reset()` over every unit above, and calibration state treated as configuration-in (fingerprinted) rather than state-carried-over.

**ON DEGRADED INPUT:** exposure-reducing, and the direction is fixed: degradation moves the classification toward `unknown` and hazard **upward**, never toward a benign label.


| Condition                        | Behaviour                                                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Input feature not warm           | Classification confidence reduced by a declared rule, or `unknown`. Never a full-confidence label from a cold input.                  |
| Input feature stale or invalid   | `unknown` plus notification.                                                                                                          |
| Insufficient history after reset | `unknown` until the declared warmup completes — not the prior label, and not a default label.                                         |
| Calibration missing or failed    | Retain the last **versioned** parameter set and emit; never fall back to an uncalibrated default silently.                            |
| Hazard uncomputable              | Emit the state with hazard absent-and-marked, not zero. Zero hazard is the least exposure-reducing possible substitute for "unknown." |


**ON EXCEPTION:** contained and emitting. A raise in classification yields `unknown` for that tick with a notification, and consumers fail closed against `unknown` per their own gate contracts. A raise in **calibration** must not be contained into a silent fallback: it halts calibration, retains the previous versioned parameters, and emits. The existing default matters here — Phase 0 D-3/D0.5 record that the regime gate defaults **off** and that sub-threshold completeness skips rather than extrapolates (`src/feelies/composition/engine.py:217`), which is the correct direction and should be preserved as the contract rather than left as a default someone may flip.

**SUBSTITUTABILITY:** a replacement must (i) emit both contracts with the same closed label enumeration, units and time bases; (ii) publish exactly once per event through the single read path; (iii) declare `unknown` and honour the degradation direction above; (iv) expose `reset()`; (v) read no clock and no engine's state but engine 2's; (vi) be **removable** — with the regime gate off, the platform must run and every consumer must take its declared no-regime branch. Removability is the sharper half of the test here: an engine whose absence breaks consumers is not consulted by them, it is fused to them.

**CONFORMANCE TEST:**

1. **Single-worldview test.** Exactly one classifier construction and one `RegimeState` publisher in the composed platform; any second publisher fails the build. Mechanical form of CORE §E's prohibition.
2. **Purity and portability.** Same feature prefix, cold start, two processes at `PYTHONHASHSEED=random` → identical `RegimeState` / `RegimeHazardSpike` streams. Engine 3 holds two baselines already (`level5_regime_hazard_spike`, `level6_regime_state`, Phase 1 §6), and Phase 0 corrected a drafted-from-recollection claim that regime output had no parity hash — it has two. **The constraint on this test is host-local math:** Phase 1 §6.1 records that both whole-platform stream baselines are *exempt* precisely because the fixture builds the regime engine, "whose transcendental math is stable only for a fixed host + libm," and `tests/determinism/test_transcendental_determinism.py:70` pins `log`/`exp` paths **intra-process only**. So per-engine parity is assertable; cross-host parity is not, and this sheet must not claim it.
3. **Degradation-direction test.** For every degraded-input branch above, assert hazard is non-decreasing and confidence non-increasing versus the nominal case. This is CORE §C.5 made mechanical for a non-trading engine.
4. **Removability.** Regime gate off → platform runs, every consumer takes its no-regime branch, and no consumer reads a stale label. Pairs with the `src/feelies/composition/engine.py:217` default.
5. **Label-enumeration closure.** The label set is a closed, versioned enumeration; an unrecognised label fails at the receiving boundary, loudly, with provenance (CORE §G.3).
6. **Change-plus-heartbeat contract.** Assert a consumer can distinguish unchanged from not-running using only the emission, without reading engine 3 state.
7. **Cascade depth.** `RegimeHazardSpike` → `src/feelies/risk/hazard_exit.py:141` → `OrderRequest` at `:253` → orchestrator at `:585` is a hot-path publish cascade re-entering from a handler; assert the stated maximum depth Phase 1 §3 requires and nothing provides.

**GAP vs CURRENT:** engine 3's *contract discipline* is the strongest in the platform — a declared single read path (`src/feelies/bootstrap.py:289`), two parity baselines, and a correctly-off-by-default gate — while its *placement* is the worst: five classification methods live inside the kernel (Phase 0 D0.2, `_calibrate_regime_engine:2335`, `_update_regime:2432`, `_maybe_publish_hazard_spike:2501`, `_regime_label_for:4556`, `_checkpoint_regime_snapshot:5460`), so the one engine CORE §E most insists must be singular is currently authored in the module CORE §J names as the god orchestrator.

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

`OWNS` **overlaps flagged, not split (CORE §C.6):**

1. **Classification authored in the kernel.** Five named methods (above) perform regime computation in `src/feelies/kernel/orchestrator.py`, which CORE §E requires to own "no trading-domain calculation," while `services/` holds the engine proper. Placement, not a contested owner — but it is the largest single instance of the pattern on this sheet, and it is why test 1 must assert on the composed platform rather than on the `services/` package.
2. `_regime_label_for:4556` **is a second reader.** The declared single read path is the cache (`src/feelies/bootstrap.py:289`); an orchestrator-local label resolver is a second one. Whether it delegates to the cache or recomputes is not established by Phase 0 — recorded as an assumption, not asserted as a duplicate path.
3. **Regime as a gate vs. regime as a fact.** Phase 0 D0.5 measured the `regime_gate` family at **56 sites** across `forensics` (19), `risk` (13), `signals` (12) and `core` (7) — the largest gate family in the platform, and `src/feelies/signals/regime_gate.py` is an AST DSL in engine 4's package. The fact is engine 3's; the *predicate over it* is the consumer's. That split is right, but 56 sites means the gate ladder (Phase 3) inherits the real work, and the `regime_gate_state` marker family is the thing Phase 6 must enumerate from a single source per CORE §G.5.

**Model finding: none.** Classification and hazard are one job with one output surface; calibration is its lifecycle, not a second job. No responsibility failed to fit.

**Assumptions registered:**

- **Classification granularity is undetermined.** Whether `RegimeState` is per-symbol or market-wide is not established by Phase 0 or Phase 1, and it decides whether engine 3's state is O(1) or O(universe) and whether a per-symbol halt affects a shared label. It matters most for CORE §I's untested axis, symbol cardinality, and should be resolved before Phase 3.
- **Whether** `_regime_label_for:4556` **reads the cache or recomputes.** Decides overlap (2) above. One read of the method settles it.
- **Hazard units and horizon are not known to be declared today.** Required by the EMITS clause; a Phase 5 gap-table item.
- **Calibration determinism is unmeasured.** Phase 1 budget row 6 places the only RNG in `src/feelies/research/cpcv.py` (engine 12) with no global seeding anywhere, so nothing suggests engine 3 draws randomly — but no measurement covers whether calibration output depends on input ordering, and Phase 1 row 4 leaves 64 of 69 hot-path float reductions relying on deterministic input order with no guarantee. Resolved by test 2 plus one read of the calibration reduction.



## ENGINE 4 — Alpha

**ENGINE:** 4. Alpha

**LATENCY CLASS:** `hot` (CORE §D). Phase 0 D0.4 hop 23 — `src/feelies/signals/horizon_engine.py:198` → `:505` — on the boundary leg of the quote tick, publishing from inside its own handler (Phase 1 §3 lists `HorizonSignalEngine._on_snapshot` among the 16 re-entrant handlers). No cold sub-surface: everything about *whether* an alpha is live is engine 5 and resolved at composition (CORE §C.10).

**OWNS:**

1. **The horizon-anchored forecast, and nothing else.** Direction, edge, mechanism, expected half-life, confidence, anchor timestamp — CORE §E's list is the complete field set, not a starting point.
2. **Its own alpha identity as data.** Engine 4 *is* the alpha layer, so `alpha_id`, archetype and horizon are legitimate content on its emissions. CORE §C.7 prohibits every engine *outside* this layer from branching on them; it does not prohibit engine 4 from declaring them, and attribution at N alphas is impossible if it does not.
3. **Forecast provenance.** Which alpha, which manifest content, which feature and regime versions produced this forecast — travelling on the emission.
4. **The alpha's own validity state.** `SafetyStateChange` is engine 4 declaring that its forecast has become unsound. It is an assertion about the forecast, never an instruction about the book — exactly the split the engine-3 sheet drew for `RegimeHazardSpike`.
5. **A deterministic tie-break key on every forecast.** See EMITS; this is the structural resolution of U-2 and it belongs to the producer.
6. **Per-alpha forecast state, isolated per alpha.**

**MUST NOT OWN:**

- **Sizing.** Engine 4 emits edge; engine 8 turns edge into quantity.
- **Position awareness.** No read of the book, in any form, including "am I already long."
- **Cost arithmetic.** An alpha may **declare** a static cost characteristic in its manifest; it must not **compute** cost from live spreads. That computation exists today at `_round_trip_cost_bps:2266` / `_edge_clears_round_trip_cost:2184` (Phase 0 D0.2) and is engine 9's.
- **P&L feedback.** No realized outcome may re-enter the forecast within the run. Decay detection and calibration against outcomes are engine 12, feeding engine 5 on a declared cadence (CORE §E, §G.9).
- **Arbitration between alphas.** Selecting which forecast wins is engine 6. Engine 4 has no concept of winning, and must not be given one — see the overlap below.
- **Cross-alpha state.** No alpha's forecast state is reachable from another's. Same property as engine 2's sensor independence, and the same reason: it is what makes the 20th alpha attach.
- **Metadata-free inputs.** Engine 4 must consume the snapshot, not the raw reading — `warm`, `stale`, `valid` and `unit` live on the snapshot, and a forecast computed from an input whose warmth it cannot see is a forecast that cannot fail closed.
- **Its own regime classification** (3) or its own estimators (2).

**CONSUMES:**


| Input                                                                          | Staleness / validity tolerance                                                                                                                                                                                        |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HorizonFeatureSnapshot` (`src/feelies/signals/horizon_engine.py:198`)         | Per-feature `warm` / `stale` / `valid`, per the engine-2 contract. A `warm=False` input either suppresses the forecast or reduces confidence by a declared rule — never a full-confidence forecast from a cold input. |
| `RegimeState` (`:196`)                                                         | Declared per alpha; `unknown` is an admissible and gateable value, not a missing one. The predicate over the label is the alpha's; the label is engine 3's.                                                           |
| `SensorReading` (`:197`)                                                       | **Should not be a decision input.** Flagged from the engine-2 side as the metadata-thinner route; restated here as a prohibition rather than an observation, because engine 4 is the consumer that makes it matter.   |
| Alpha manifest (`alphas/**/*.alpha.yaml`), resolved at composition by engine 5 | Read once at composition. Its **content hash** must be an input to this engine's provenance — see EMITS.                                                                                                              |


**EMITS:**


| Contract                 | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Signal`                 | Direction (closed enumeration); edge with a **declared unit** (bps of expected return over the stated horizon, or whatever unit the manifest declares — CORE §C.8 makes an undeclared unit a non-existent field); confidence with a declared scale; mechanism from a closed, versioned enumeration; expected half-life with unit; `anchor_timestamp_ns` = the boundary event time the forecast is anchored to, distinct from `timestamp_ns`. Provenance: `alpha_id`, `alpha_version`, `manifest_hash`, the feature and regime versions consumed, `schema_version`, `source_layer`. |
| `SafetyStateChange`      | The alpha's own validity state, from a closed enumeration, with cause. Consumed by `src/feelies/risk/exit_composer.py:289` and `src/feelies/risk/deferral_cap.py:237`, which decide what to do about it.                                                                                                                                                                                                                                                                                                                                                                           |
| Suppression notification | A boundary at which a live alpha produced no forecast, with the gate that suppressed it. Silence must not read as "no opinion" when it means "gated."                                                                                                                                                                                                                                                                                                                                                                                                                              |


**The tie-break key, stated as a contract obligation.** Every forecast carries a total-ordering key — `(anchor_timestamp_ns, symbol, horizon, alpha_id)` — under which any two concurrent forecasts are strictly orderable **without reference to emission order**. This is not decoration: Phase 1 §2 established that the platform has no global event ordinal (`sequence` is unique within one of 26 spaces, and the total-order key covers 2 of 21 types, both of them engine 1's), so two `Signal`s from two alphas on one tick are today orderable only by the order `publish` happened to be called in. Phase 0 registered the consequence as U-2 — whether arbitration is stable across equal-strength signals from different alphas. **Publishing the key resolves U-2 structurally rather than by inspecting a comparator**, and it is the producer's obligation because only the producer knows the anchor.

**FORBIDDEN READS:** positions, marks, P&L, lots, fills (7); risk state, limits, buying power (8); order state, acks, routing (9/10); the event log and raw vendor frames (1); **another alpha's forecast, state or manifest** (4); the alpha registry and lifecycle state (5) — whether an alpha is live is resolved at composition and must never be re-read per event (CORE §C.10); any clock.

Enforcement, and this engine has the strongest existing case: (a) **constructor injection at the composition root** — engine 4's current subscription set is `RegimeState`, `SensorReading`, `HorizonFeatureSnapshot` and nothing else (`src/feelies/signals/horizon_engine.py:196-198`), so the purity boundary is presently enforced by *what it is handed*, which is the only enforcement that survives a careless edit; (b) an import-boundary test over `signals/`; (c) the tree-wide alpha-literal check (CORE §I) — noting that the two measured leaks are in `src/feelies/core/platform_config.py` (Phase 0 E-1), i.e. outside this engine, which is the direction that matters: engine 4 may name itself, the platform may not name engine 4; (d) the purity test below.

**STATE:** per-(alpha, symbol, horizon) accumulators and warmup counters; per-alpha safety state; last-emitted forecast per key for change detection; regime-gate evaluation state, if any. **Deterministic reset path:** Phase 1 §5 measured 32 of 38 state-mutating classes with no reset of any kind but named only the top five, and `HorizonSignalEngine` is not among them — so this engine's reset status is *unmeasured*, not *clean*. Target: one `reset()` per alpha restoring to cold start, with cold start declared as the only replay contract, and **per-alpha reset isolation** — resetting alpha A must not perturb alpha B's stream.

**ON DEGRADED INPUT:** exposure-reducing, and the direction is fixed: degradation reduces conviction or suppresses. It never flips direction and never raises confidence.


| Condition                        | Behaviour                                                                                                                                                                                                                                                                                                       |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input feature not warm           | Suppress, or reduce confidence by a declared rule. Emit the suppression.                                                                                                                                                                                                                                        |
| Input feature stale or invalid   | Suppress and emit.                                                                                                                                                                                                                                                                                              |
| Regime `unknown`                 | The alpha's declared no-regime branch, which must exist. Phase 0 D-3 / D0.5 record the regime gate defaulting **off** with sub-threshold completeness skipping rather than extrapolating (`src/feelies/composition/engine.py:217`) — the right direction, and this sheet makes it contract rather than default. |
| Engine-1 quality flag propagated | Declared per alpha; never silently absorbed.                                                                                                                                                                                                                                                                    |
| Below warmup after reset         | No forecast, and say so. Not a zero-edge forecast — zero edge is an opinion.                                                                                                                                                                                                                                    |




**ON EXCEPTION:** contained **per alpha**, and must emit. One alpha raising suppresses that alpha's forecast for that boundary, emits, and leaves every other alpha's stream bit-identical — the isolation is the point, and it is what a shared `try/except` around the fan-out would destroy. Containment must not become fail-quiet: Phase 0 E-2 found two decision-path handlers that neither raise, return, nor log, one of them `except KeyError: pass` at `src/feelies/alpha/risk_wrapper.py:189` whose effect is that an unregistered `strategy_id` skips **all** per-alpha risk budgets. That is the failure shape this engine's containment must not reproduce.

**SUBSTITUTABILITY:** an alpha must be attachable and detachable **by files under** `alphas/` **plus config, with zero edits under** `kernel/`**,** `bus/`**,** `core/`**,** `composition/`**,** `risk/` **or** `execution/` — CORE §G.1, and engine 4 is where §G.1 is decided. A replacement must (i) emit both contracts with the same field set, units and time bases; (ii) publish the tie-break key; (iii) declare its own no-regime and degraded branches; (iv) expose per-alpha `reset()`; (v) read nothing outside its declared inputs. **The concrete boundary test:** the CORE §I fixture suite — null, shape-adversarial, pathological — attaches here and nowhere else. The shape-adversarial fixture is the sharp one, because it is the only test of the axes CORE §I names as untested: symbol cardinality, horizon and archetype. Adding a twelfth alpha of the eleventh's shape proves nothing about this boundary.

**CONFORMANCE TEST:**

1. **Portfolio-state purity.** Run one feature/regime prefix against two materially different position books; the forecast stream must be **byte-identical**. This is the mechanical form of "alphas are pure w.r.t. portfolio state," it is the single highest-value test on this sheet, and it is cheap because engine 4 already takes no position input.
2. **Alpha isolation.** With N alphas loaded: permuting load order leaves every per-alpha stream identical, and removing alpha B leaves alpha A's stream identical. Directly tests the property Phase 1 §3 showed is unpinned — registration order is an output-determining input guarded only by six prose comments in `build_platform`.
3. **Manifest provenance closure.** Edit one threshold in an `alphas/**/*.alpha.yaml`; assert both the emitted `Signal` provenance **and** `config.snapshot().checksum` change. This closes at the point of use what Phase 1 §7 calls "the single largest hole in run provenance": `alpha_specs` is reduced to `sorted(spec.name for spec in value)` (`src/feelies/core/platform_config.py:683`) and a search for `manifest_hash` / `spec_hash` / `yaml_hash` / `sha256` across `src/feelies/alpha/` returns no matches.
4. **Tie-break totality.** Two alphas, equal edge, same anchor, both emission permutations → identical downstream selection. Resolves U-2.
5. **Field-set closure.** Every CORE §E field present with a declared unit; `Signal.metadata` typed, closed and immutable. Phase 0 C-7 lists `Signal.metadata` among the eight frozen events with mutable containers — metadata is where an undeclared contract hides, and a mutable dict on a published event is how it escapes review.
6. **Anchor and half-life honoured downstream.** Expiry must be computed from the forecast's declared anchor and half-life. Phase 0 D0.4 hop 3 performs a horizon-age test on the buffer at `src/feelies/kernel/orchestrator.py:1530`; if any constant in that path is not read from the forecast, it is an alpha-shape leak in shared code (CORE §I).
7. **Parity.** Engine 4 holds four baselines — `level2_signal`, `signal_fires`, `reference_alpha_signal_fires`, `decoupled_safety_state_change` (Phase 1 §6) — and the extension needed is confirming which fall inside the 8 streams covered by `tests/determinism/test_hash_seed_independence.py:61`, since 8 of 26 baselines are seed-tested (Phase 1 budget row 1).

**GAP vs CURRENT:** engine 4's package boundary is the cleanest in the platform — `signals/` is `Clear` with three inputs, none of them position, P&L or order state (Phase 0 D0.2; `src/feelies/signals/horizon_engine.py:196-198`) — while the forecast it produces is parameterised by manifest content that moves no checksum (Phase 1 §7) and is then reduced to one surviving forecast per tick in the kernel (Phase 0 D0.4 hop 28, `_select_bus_signal:1676`).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean, and deliberately so: no clause required naming a live alpha, and the one place an ID legitimately appears — engine 4's own emission provenance — is stated as a general rule about the alpha layer, not about any alpha.

`OWNS` **overlaps flagged, not split (CORE §C.6):**

1. **Arbitration — engine 6's job, performed in two other places.** `_select_bus_signal` (`src/feelies/kernel/orchestrator.py:1676`) returns one `Signal | None` per tick and discards the rest (Phase 0 D0.4 hop 28), and `src/feelies/alpha/arbitration.py` selects between signals from inside engine 5's package (Phase 0 D0.2). CORE §E gives engine 6 "N forecasts → one desired portfolio," and a lossy per-tick winner-take-all is a portfolio-construction policy — not a kernel detail and not an alpha-package concern. **This is the overlap that most directly bears on CORE §A's "how cleanly the 2nd, 5th and 20th alpha attach":** the platform can load N alphas and acts on one per tick. Flagged, not split; the resolution is engine 6's sheet.
2. `src/feelies/alpha/signal_layer_module.py` **wraps engine-4 execution from inside engine 5's package** (Phase 0 D0.2). Placement, not a contested owner.
3. **Half-life expiry evaluated in the kernel** against the signal buffer (hop 3, `:1530`). Engine 4 declares the half-life; whoever enforces expiry must read it from the forecast. Test 6 is the discriminator.
4. **Regime-gate DSL in** `signals/`**.** Already resolved on engine 3's sheet — the fact is engine 3's, the predicate is the consumer's — and `src/feelies/signals/regime_gate.py` is correctly on the consumer side. Recorded once so it is not re-litigated.

**Model finding: none.** Forecast and self-validity are one job with one output surface. No engine-4 responsibility failed to fit.

**Assumptions registered:**

- `Signal`**'s declared field set is not enumerated by Phase 0 or Phase 1.** CORE §E requires direction, edge, mechanism, expected half-life, confidence and anchor timestamp; whether all six exist today, and with what units, is a Phase 5 gap-table item. Test 5 settles it.
- **Origin of the cost disclosure is undetermined.** `SizedPositionIntent` carries `disclosed_cost_total_bps_by_symbol` (Phase 0 C-7) on engine 6's event. If that value originates in an alpha manifest it is a legitimate static declaration; if it is computed per event from live spreads inside the alpha layer, engine 4 is performing the cost arithmetic CORE §E forbids it. One read of the field's producer decides it.
- **Whether** `HorizonSignalEngine` **holds cross-alpha state** — decides whether isolation (test 2) currently passes or is a gap.
- **Engine 4's reset status is unmeasured**, not clean; Phase 1 §5's named table stops at five classes.
- **U-2 stays open.** The tie-break key resolves it structurally for the target state; it says nothing about what today's comparator does, and Phase 0's resolution route — read the comparator and its tie-break, plus a test that constructs a tie — remains the way to close it for the current system.



## ENGINE 5 — Alpha Governance

**ENGINE:** 5. Alpha Governance

**LATENCY CLASS:** `cold` (CORE §D — engines 5, 11 except the kill-switch read, and 12 are cold). This is the strongest statement on the sheet: engine 5 has **no** hot sub-surface, and the mechanism is CORE §C.10 — whether an alpha is live is resolved at composition and never re-evaluated per event. Phase 0 D0.2 rates `promotion/` `Clear` and cold, and Phase 0's document check confirms the promotion ledger is "never read on the tick path (forensic only)."

**OWNS:**

1. **Loading and discovery.** Manifest discovery, parsing, and the deterministic load order — `src/feelies/alpha/discovery.py:28` already sorts the only `rglob` in the platform, with the docstring at `:42` naming determinism as the reason.
2. **The dependency graph and layer validation.** `src/feelies/alpha/dependency_graph.py`, `src/feelies/alpha/layer_validator.py`, `src/feelies/alpha/validation.py`.
3. **The load-gate ladder.** G1…G17 as implemented (Phase 0 D0.5), the largest single-package gate family in the platform at **52 sites** (`alpha_load_gate`, concentrated 52-of-52 in `alpha/`).
4. **Lifecycle state.** `LIVE`, `QUARANTINED` and the rest — one authoritative state machine, one writer.
5. **Promotion, quarantine, and the evidence record.** The append-only ledger in `promotion/`.
6. **Alpha-level budgets** — the per-alpha allocations engine 8 enforces. Engine 5 sets them; engine 8 applies them.
7. **The registry as a composition-time artifact.** The output of engine 5 is a resolved, frozen set handed to the composition root — not a service consulted at runtime.
8. **The manifest content hash.** Engine 4's provenance obligation requires a `manifest_hash`; the engine that reads and validates manifests is the one that must compute it.

**MUST NOT OWN:**

- **Anything on the tick path.** CORE §E states it flatly, and the entire value of this engine's cold classification depends on it.
- **What an alpha says.** Engine 5 decides *whether* an alpha is live, never *what it forecasts*. Not a single line of engine 5 may read a `Signal`'s content to alter a forecast.
- **Engine-4 execution.** `src/feelies/alpha/signal_layer_module.py` and `src/feelies/alpha/portfolio_layer_module.py` wrap engine-4 and engine-6 execution from inside this engine's *package* (Phase 0 D0.2). Package co-location is not ownership, and this sheet grants none.
- **Arbitration between signals.** `src/feelies/alpha/arbitration.py` selects between signals (Phase 0 D0.2) — engine 6 behaviour, in engine 5's package. Same disposition as the engine-4 sheet's overlap 1: flagged, resolved on engine 6's sheet.
- **Fill attribution** (`src/feelies/alpha/fill_attribution.py`) — engine 7. **Risk vetoes** (`src/feelies/alpha/risk_wrapper.py`) — engine 8. Both are in this engine's package and neither is its job.
- **Its own promotion decision.** Engine 5 executes lifecycle transitions; the *evidence* that justifies them is engine 12's. See the closed-loop item below.
- **Universe definition** (§F.1), which per-alpha `universe` disclosure at `src/feelies/alpha/layer_validator.py:326` currently contributes to. Engine 5 validates the disclosure; it does not thereby own the universe.

**CONSUMES:**


| Input                                                                | Staleness / validity tolerance                                                                                                                                                                                            |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Alpha manifests (`alphas/**/*.alpha.yaml`, `alphas/SCHEMA.md`)       | Read once at load. A manifest that fails schema, layer or dependency validation is **refused**, never partially loaded.                                                                                                   |
| Engine-12 evidence — attribution, decay detection, calibration, cost | On a **declared cadence**, off the tick path (CORE §E, §G.9). Staleness tolerance is explicit: evidence older than a stated bound cannot justify a promotion, and must not silently justify continued LIVE status either. |
| Platform config (`platform.yaml`, `configs/`)                        | Composition-time. Selects; does not branch.                                                                                                                                                                               |
| Operator action                                                      | Authenticated, recorded in the ledger with actor and reason.                                                                                                                                                              |


**EMITS:**


| Contract                        | Units, timestamp semantics, provenance                                                                                                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The **resolved alpha registry** | The composition-time artifact: alpha id, version, `manifest_hash`, declared archetype, horizon set, universe disclosure, budget, and lifecycle state as of composition. Frozen; consumed once.          |
| Lifecycle transition record     | From-state, to-state, cause, the evidence reference that justified it, actor, and **event time or wall time, declared** — this is a cold-path record and the time base must still be named (CORE §C.8). |
| Load-gate outcome record        | Per alpha, per gate, pass/fail with reason. A refused alpha produces a record; a silent absence from the registry is not acceptable.                                                                    |
| Governance alert                | A refusal, quarantine, or budget breach surfaces through engine 11.                                                                                                                                     |


**FORBIDDEN READS:** live positions, marks, P&L (7) — engine 5 reads engine 12's *analysis* of outcomes, never the book; risk state and limits (8); order state (9/10); market data and features (1/2); regime (3); `Signal` content (4). Any clock other than the injected one.

**Enforcement, and here the mechanism is unusually strong and unusually weak in different directions.** Strong: `promotion/` is cold and the ledger is append-only. Weak, and this is the sheet's central finding — `core/` **imports** `promotion/`. Phase 0 D0.1 measured import cycle 2 as `feelies.core.inv12_stress` → `feelies.core.platform_config` → `feelies.promotion.evidence`, and recorded the consequence: the governance package is in the import closure of anything that loads platform config. Engine 5 is declared off the tick path, and it is imported by the module every tick-path component transitively depends on. Enforcement must therefore be: (a) an **import-direction test** — nothing under `core/`, `kernel/`, `bus/`, `composition/`, `risk/` or `execution/` may import `promotion/` or `alpha/` governance modules, which fails today; (b) constructor injection of the resolved registry, never of the registry service; (c) an assertion that no engine-5 symbol is reachable from a tick-path call graph; (d) the tree-wide alpha-literal check (CORE §I).

**STATE:** the resolved registry; lifecycle state per alpha; the append-only evidence ledger; load-gate outcomes; budget allocations; the manifest content hashes.

**Deterministic reset path:** the registry is **immutable after composition** — that is the reset contract, and it is stronger than a `reset()` method. The ledger is append-only and durable by design; it is *not* reset, and a replay must not rewrite it. **The split to state explicitly: registry state is cold-start-per-run and enters the run fingerprint; ledger state is durable and cross-run.** Conflating them is how a replay silently acquires a promotion that happened after the log was recorded.

**ON DEGRADED INPUT:** exposure-reducing, and this engine has the widest latitude to be strict because it is off the tick path — there is no latency argument for leniency.


| Condition                                             | Behaviour                                                                                                        |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Manifest fails schema, layer or dependency validation | Refuse the alpha, emit, and **do not compose it**. Not degraded-live.                                            |
| Manifest hash unavailable                             | Refuse. Provenance is a load precondition, not a nice-to-have (engine 4 test 3).                                 |
| Evidence stale beyond the declared bound              | No promotion. An alpha whose evidence has expired moves toward quarantine, not toward continued LIVE by inertia. |
| Budget unresolvable                                   | Zero budget, emit. Not unlimited, not the platform default.                                                      |
| Registry incomplete at composition                    | **Fail the boot.** A platform that starts with a partial alpha set is trading a configuration nobody specified.  |
| `enforce_layer_gates=False`                           | Must be unreachable outside declared research configs — Phase 0 registered this as U-6, unresolved.              |


**ON EXCEPTION:** **halt**, not contained. Engine 5 runs at composition; a raise there means the platform's trading configuration is undetermined, and the exposure-reducing branch for an undetermined configuration is not to trade. This is the one engine on which "contained" is the wrong answer, and it is affordable precisely because engine 5 is cold — nothing is in flight. A raise on the *evidence-write* path is different: contained, emitting, and the transition it was recording is not applied.

**SUBSTITUTABILITY:** a replacement must (i) produce the same resolved-registry artifact with the same fields; (ii) run the same gate ladder with enumerable outcomes; (iii) append to the same ledger contract; (iv) be **absent-able** — with governance replaced by a fixed registry literal, the platform must compose and run identically, which is the test that proves nothing on the tick path consults it. Absence-ability is the sharp half here, exactly as removability was for engine 3. **The concrete boundary test:** the CORE §I fixtures load through this engine. The pathological fixture — NaN, stale timestamps, out-of-universe symbols, duplicate IDs, self-contradictory forecasts — is engine 5's acceptance test more than any other engine's, because CORE §I's stated purpose for it is proving gates are fail-closed rather than fail-quiet, and 52 of the platform's load gates are here.

**CONFORMANCE TEST:**

1. **Off-tick-path proof.** Static: no engine-5 symbol appears in the tick-path call graph. Dynamic: instrument the registry and lifecycle store, run a full tick sequence, assert **zero reads**. CORE §C.10 mechanised.
2. **Import-direction test.** `core/` → `promotion/` fails the build. Fails today (cycle 2, Phase 0 D0.1) and is the cheapest structural fix on this sheet.
3. **Gate-ladder enumerability.** Every load gate enumerable from one source, with docs and tests generated from it (CORE §G.5). Phase 0 G-1 found **G13 does not exist** in the registry — a hole in an enumeration that nothing enumerates — and Phase 0 D-22 found an audit citing `src/feelies/alpha/layer_validator.py:760` for it at a location that no longer resolves.
4. **Pathological-fixture refusal.** Each pathological input class is refused with a named gate and an emitted record. No silent skips.
5. **Registry immutability.** Any post-composition mutation attempt fails loudly.
6. **Determinism of load order.** Same manifest tree, `PYTHONHASHSEED=random`, two processes → identical registry and identical load-gate record. `src/feelies/alpha/discovery.py:28` already sorts; Phase 1 budget row 9 records that **nothing checks it stays sorted**.
7. **Ledger append-only-ness and replay isolation.** Replaying a historical log must not append to, read forward from, or be influenced by ledger entries written after that log.
8. **Closed loop, on cadence.** At least one governance decision driven by an engine-12 output on a declared cadence (CORE §G.9), with the evidence reference recorded on the transition.

**GAP vs CURRENT:** engine 5 is correctly cold, correctly append-only, and has the platform's largest gate ladder — and it is nonetheless in the import closure of every tick-path module (Phase 0 D0.1 cycle 2), its package hosts four responsibilities belonging to engines 4, 6, 7 and 8 (Phase 0 D0.2), its gate registry has a hole at G13 (Phase 0 G-1), and its `LIVE → QUARANTINED` write is performed from engine-12 code at `src/feelies/forensics/cost_circuit_breaker.py:159`.

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

`OWNS` **overlaps flagged, not split (CORE §C.6):**

1. `alpha/` **hosts four other engines' work.** `src/feelies/alpha/signal_layer_module.py` and `src/feelies/alpha/portfolio_layer_module.py` (4/6 execution), `src/feelies/alpha/arbitration.py` (6), `src/feelies/alpha/fill_attribution.py` (7), `src/feelies/alpha/risk_wrapper.py` (8) — all measured in Phase 0 D0.2, which rates `alpha/` **Mixed** for exactly this reason. The package is 14 modules and 4 652 sloc, the second largest in the platform. Governance proper is six of those modules. **The call: the boundary is real and the package is not** — this is a placement problem with a clean answer, and it is the cheapest large-scale ownership clarification available in the whole review.
2. **The** `LIVE → QUARANTINED` **write direction.** `src/feelies/forensics/cost_circuit_breaker.py:159` performs an engine-5 state write from engine-12 code. Phase 0 calls this CORE §G.9's closed loop, correctly — the loop *should* close — but a closed loop is a *decision driven by* forensics, not a *write performed by* forensics. **The call: engine 12 emits evidence and a recommendation; engine 5 performs the transition.** Same output, one writer, and it survives a second forensic input arriving later. Flagged here; the mirror-image entry belongs on engine 12's sheet.
3. **Per-alpha budgets: set here, enforced by engine 8.** Not contested — recorded so the engine-8 sheet does not re-open it. The live defect on that seam is engine 8's: `except KeyError: pass` at `src/feelies/alpha/risk_wrapper.py:189` means an unregistered `strategy_id` skips **all** per-alpha budgets (Phase 0 E-2). That the wrapper lives in `alpha/` is overlap 1; that it fails open is engine 8's.
4. **Universe disclosure.** Engine 5 validates each alpha's `universe` (`src/feelies/alpha/layer_validator.py:326`); §F.1 remains unowned and unresolved. No claim staked.

**Model finding: none, and one near-miss worth recording.** Engine 5 carries two jobs with genuinely different rhythms — *composition-time resolution* (runs once, must fail the boot) and *ongoing lifecycle management* (runs on an evidence cadence, must fail contained). They are reconcilable because they share one output surface, the registry, and one record, the ledger. But they must not share one exception policy, which is why ON EXCEPTION is split above. If a later phase finds they also require different determinism contracts, this becomes a model finding; on the evidence in Phase 0 and Phase 1, it does not.

**Assumptions registered:**

- **Registry content is outside the run fingerprint.** Phase 1 §7 measured `alpha_specs` reduced to names only (`src/feelies/core/platform_config.py:683`), with no `manifest_hash` / `spec_hash` / `yaml_hash` / `sha256` anywhere in `src/feelies/alpha/`. The `manifest_hash` this sheet assigns to engine 5 does not exist today; asserted as a target, not as current state.
- **U-6 is open and is engine 5's.** Whether `enforce_layer_gates=False` is reachable in any non-research config (Phase 0 D0.8) determines whether the 52-gate ladder can be switched off in production. One grep over `configs/` closes it, and it should close before Phase 6.
- **Engine 5's parity coverage is nil, by measurement.** Phase 1 §6.1 records no manifest entry for engine 5 — loading, lifecycle and promotion outputs are unpinned. Justifiable for a cold engine, *except* for the resolved registry, which determines what the hot path does. **The call: fingerprint the registry, do not parity-hash the ledger** — one is an input to the run, the other is a durable record of decisions and should not be expected to reproduce.
- **Ledger durability under replay is unverified.** Phase 1 §4 records that the only event log has no persistence; whether the promotion ledger is durably backed, and how a replay interacts with it, is not established by either phase. Test 7 is the discriminator, and until it runs, the registry/ledger split above is `specified`, not `implemented`.



## ENGINE 6 — Portfolio Construction

**ENGINE:** 6. Portfolio Construction

**LATENCY CLASS:** `hot` (CORE §D), and the **spikiest** hot engine: it fires only at horizon boundaries — Phase 0 D0.4 hop 21 records that a tick "usually" produces zero of them — and when it fires it does O(universe) work at hops 24–25 and 27–28. Phase 4's per-engine budget cannot be a mean; for this engine it has to be a boundary-conditional tail.

**OWNS:**

1. **The mapping from N forecasts to one desired portfolio.** Total and non-lossy *at the contract level*: every forecast in scope at a boundary is either a contributor or an exclusion with a named reason. Nothing is dropped without appearing in the record.
2. **The cross-sectional barrier and its completeness policy** — what constitutes a complete cross-section, and what happens below threshold.
3. **Ranking, neutralization, and exposure computation** over consumed risk-model outputs.
4. **Turnover control** against current positions read from engine 7.
5. **Target weights per symbol, as a level.** Phase 0 E-2 records that `SizedPositionIntent` carries a desired *book state* (`src/feelies/core/events.py:697`) with the per-leg delta recomputed downstream against the real store. That is the right shape and this sheet promotes it from an implementation property to a contract obligation: re-emitting an unchanged target must produce no second order.
6. **Attribution of the desired portfolio back to contributing forecasts** — `mechanism_breakdown` is engine 6's, and at N alphas it is the only thing that makes per-alpha attribution possible downstream.
7. **The arbitration policy**, declared and configured — see the resolution below.

**MUST NOT OWN:**

- **Actual positions, fills, marks** (7). Consumes them, never computes them, and — the sharp form — **never substitutes a value when the read fails**. Phase 0 E-2 measured `except Exception: current_positions[s] = 0.0` at `src/feelies/composition/engine.py:388`, marked `# pragma: no cover`: a failed per-strategy position lookup is silently reported as flat, with no log, metric or alert.
- **Risk-model estimation** — factor loadings, covariance, betas. CORE §E states this explicitly. See the §F-class finding below for who does own it, which is currently nobody.
- **Sizing into shares or currency.** Engine 6 emits target weight or target notional; engine 8 converts under buying power and limits. See the units assumption.
- **Risk vetoes** (8), **order construction, netting, urgency** (9), **fills and routing** (10).
- **Universe definition** (§F.1). Engine 6 is the most affected consumer of a fact it does not own — Phase 0 D0.7 F.1 records the consequence precisely: the barrier's completeness is measured against a universe supplied by config, "so a config/alpha-disclosure mismatch degrades the barrier rather than failing the load."
- **Alpha semantics.** No branch on `alpha_id`, archetype, horizon or symbol (CORE §C.7). Configuration selects the construction policy; code does not know which alpha it is ranking.
- **Regime classification** (3) or feature estimation (2).

**CONSUMES:**


| Input                                            | Staleness / validity tolerance                                                                                                                                                                |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Signal` from engine 4, per symbol per boundary  | Expiry computed from the forecast's own anchor and half-life. An expired forecast is **excluded and recorded**, never carried.                                                                |
| Current positions from engine 7                  | **As-of the boundary event time, and total.** A failed read is a construction failure, not a zero.                                                                                            |
| Risk-model outputs — factor loadings, sector map | Versioned. Unavailable or stale ⇒ neutrality cannot be certified; see ON DEGRADED INPUT. Currently sourced from `storage/reference/`, which Phase 0 D0.2 lists under "Unowned by any engine." |
| Universe as-of the boundary (§F.1, pending)      | Consumed; a mismatch against the disclosed universe must fail loudly rather than lower completeness.                                                                                          |
| `HorizonTick` boundary                           | The barrier's trigger; a missed boundary is a gap and must emit.                                                                                                                              |


**EMITS:**


| Contract                                          | Units, timestamp semantics, provenance                                                                                                                                                                                                                             |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Cross-sectional context (`CrossSectionalContext`) | The assembled cross-section at a boundary, with completeness measured and the universe it was measured against named. `timestamp_ns` = boundary event time.                                                                                                        |
| Desired portfolio (`SizedPositionIntent`)         | Target per symbol as a **level**, with declared unit; `factor_exposures` with the **loading-set version** that produced them; `mechanism_breakdown` accounting for every contributing forecast; exclusion list with reasons; `timestamp_ns` = boundary event time. |
| Barrier / completeness notification               | Below-threshold, missing symbol, universe mismatch — each emitted, never absorbed into a quieter portfolio.                                                                                                                                                        |
| Arbitration record                                | Which forecasts competed, which won, under which declared policy. Today the losers are traced (`_trace_buffered_signals_arbitration:638`) rather than published.                                                                                                   |


**FORBIDDEN READS:** fills, P&L, lots, realized outcomes (7 — positions only, and only as a level); risk state, limits, buying power (8); order state, acks, routing (9/10); alpha registry and lifecycle (5); raw market data and vendor frames (1); any clock.

Enforcement: (a) constructor injection at the composition root, with a **read-only positions view** — the strongest available fix for E-2 is a handle that cannot fail into a value; (b) import-boundary test over `composition/`; (c) tree-wide alpha-literal check (CORE §I); (d) the determinism tests below, since engine 6's inputs arrive by fan-in and order-independence is the property that fails first.

**STATE:** per-boundary fan-in buffers keyed by symbol; per-symbol forecast slots; completeness counters; last-emitted target portfolio per symbol; turnover state; `_signal_horizons_sorted` (`src/feelies/composition/synchronizer.py:74`).

**Deterministic reset path: per boundary, and it is stricter than a** `reset()`**.** The fan-in buffer must be provably empty at every boundary open; a forecast surviving into the next boundary is a causality violation (CORE §C.2), not a stale-data annoyance. Engine 6 is not among Phase 1 §5's five named no-reset classes, so its status is **unmeasured, not clean**. Cold start remains the only replay contract.

**ON DEGRADED INPUT:** exposure-reducing, and for this engine the direction is toward **less gross, never toward a portfolio that claims a property it did not verify**.


| Condition                           | Behaviour                                                                                                                                                                                |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Completeness below threshold        | Skip the boundary and emit. `src/feelies/composition/engine.py:217` already skips rather than extrapolates (Phase 0 D0.9e) — correct direction, promoted here from default to contract.  |
| Position read fails                 | **Halt construction for that boundary and emit.** No target is produced. This is the contract form of the E-2 fix.                                                                       |
| Risk-model outputs stale or missing | Neutrality cannot be certified. Emit a reduced-gross target with the neutrality constraint marked unverified, or none — never a target carrying `factor_exposures` it could not compute. |
| Universe mismatch                   | Fail loudly (§F.1 resolution pending); do not lower completeness silently.                                                                                                               |
| Forecast expired or gated           | Excluded with reason, present in the record.                                                                                                                                             |
| Zero contributing forecasts         | Emit an explicit flat target, not silence. Silence and "go flat" must be distinguishable to engine 9.                                                                                    |


**ON EXCEPTION:** contained **per boundary**, emitting, and **all-or-nothing**. A partially constructed cross-sectional portfolio is worse than none, because neutrality and turnover are properties of the whole set — a half-built portfolio is not a conservative version of the full one, it is a different and unvalidated one. Containment must not become fail-quiet; the E-2 handler above is the precise failure this clause exists to prohibit.

**SUBSTITUTABILITY:** a replacement must (i) emit both contracts with the same fields, units and level semantics; (ii) satisfy the non-lossy accounting identity; (iii) be swappable between construction policies — top-1 concentration, equal-weight, optimizer — **by configuration alone**, zero edits under `kernel/`, `bus/`, `core/`, `risk/`, `execution/` (CORE §G.1); (iv) degrade to identity for the single-name case. **The concrete boundary test:** the CORE §I shape-adversarial fixture — cross-sectional rather than single-name, multi-symbol, different cadence — attaches here, and this engine is where the symbol-cardinality axis CORE §I names as untested is actually exercised.

**CONFORMANCE TEST:**

1. **Level idempotence.** Re-emit an unchanged target ⇒ zero orders downstream.
2. **Accounting identity.** `contributors + exclusions == forecasts in scope at the boundary`, per symbol, with a reason on every exclusion. The conservation test that makes "non-lossy" mechanical.
3. **Order-independence at the barrier.** Permute per-symbol forecast arrival order ⇒ identical target portfolio. Engine 6 already holds the platform's reference implementation of the underlying discipline — `math.fsum` over a lex-sorted key list at `src/feelies/composition/cross_sectional.py:78-79`, with the rule stated in the docstring at `:75` (Phase 1 budget row 4) — but Phase 1 also measured 64 of 69 hot-path reductions relying on deterministic *input* order with nothing guaranteeing it.
4. **Position-read totality.** Inject a position-store failure; assert construction halts, emits, and produces no target. Kills E-2 and removes the `# pragma: no cover`.
5. **Neutrality certification.** `factor_exposures` must be traceable to a versioned loading set; a missing loading set must prevent the claim rather than zero it.
6. **Immutability.** Engine 6 owns the two most mutable events in the platform — `SizedPositionIntent` with 4 container fields and `CrossSectionalContext` with 3 (Phase 0 C-7) — and both are published to three subscribers each, so in-place mutation by any consumer is invisible to the others.
7. **Symbol cardinality.** N=1 and N=many through the same code path, no branch.
8. **Parity.** Engine 6 holds four baselines — `level3_sized_intent_decay_off`, `level3_sized_intent_decay_on`, `cross_sectional_context`, `level4_portfolio_order` (Phase 1 §6). Phase 0 U-5 records that these "pin Layer-3 mechanics in isolation" and that **no multi-symbol equivalent of the whole-run baseline was found**, which is the gap test 7 exists to close.

**GAP vs CURRENT:** `composition/` is rated `Clear` and contains the platform's best determinism discipline (Phase 0 D0.2; `src/feelies/composition/cross_sectional.py:75-79`), yet engine 6's defining responsibility — reducing N forecasts to one portfolio — is executed in two other places, `_select_bus_signal` in the kernel (Phase 0 D0.4 hop 28, `src/feelies/kernel/orchestrator.py:1676`) and `src/feelies/alpha/arbitration.py` in engine 5's package (Phase 0 D0.2), while the one read it legitimately makes of engine 7 fails silently to flat.

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

**Overlap 1 — RESOLVED here, as promised on the engine-4 and engine-5 sheets. Arbitration is engine 6's.**

The argument, not the assertion: selecting one forecast from N and sizing it is not a different job from constructing a portfolio — it is portfolio construction with a concentration constraint of one. Treating it as a separate mechanism is what allowed it to be implemented twice, in two packages, neither of them engine 6's. **The call:**

- Arbitration is a **declared construction policy**, configured, not a kernel default. Top-1 remains available as a policy; it stops being the only reachable behaviour.
- The losing forecasts are **published in the arbitration record**, not only traced. At N alphas, a discarded forecast that appears in no contract cannot be attributed against, and CORE §A judges the design by how cleanly the 2nd, 5th and 20th alpha attach.
- The tie-break is the key engine 4 was assigned to publish, so the resolution requires no comparator archaeology — it makes U-2 structurally answerable rather than empirically checked.

**Overlap 2 — two production paths to a desired portfolio.** `INFERRED`, and the highest-value open question on this sheet. Phase 0 D0.4 traces a SIGNAL route (hops 26 → 28 → 29 → 30) and a PORTFOLIO route (hops 24 → 25 → 27) on the **same** boundary tick, and hop 32 states that the admission gate is "shared with the PORTFOLIO path" — so `VERIFIED` that two paths exist, `INFERRED` that both can reach order construction on one tick. If both can produce orders for one symbol at one boundary, that is CORE §J's recompute-as-redundancy applied to the desired portfolio itself: two production paths for one number, differing quietly. Flagged, not split — the discriminating question is registered below and belongs to Phase 3's flow spec.

**Overlap 3 — engine 6 reading positions is legitimate.** Recorded so it is not re-litigated on engine 7's sheet: turnover control cannot be computed without the current book, CORE §E permits the read and forbids only ownership, and the defect at `src/feelies/composition/engine.py:388` is the **substitution on failure**, not the read.

**Overlap 4 — the barrier mechanism vs the completeness policy.** Consistent with the call made on engine 1 for the ordering key: the *synchronization mechanism* (fan-in, boundary alignment, buffer lifecycle) is kernel-class machinery that any engine needing a cross-sectional barrier should be able to use; the *completeness policy* (what threshold, what happens below it) is engine 6's. Today both live in `src/feelies/composition/synchronizer.py`, which is why no other engine can have a barrier.

**§F-class finding — a ninth unassigned responsibility: risk-model provenance.** CORE §E says engine 6 "consumes risk-model outputs; does not produce them," and no engine in §E is given their production. Phase 0 D0.2 lists factor loadings and the sector map under "Unowned by any engine," in `storage/reference/`, "consumed by engines 6, 7, 10 and by `bootstrap`; owned by none." So engine 6 emits `factor_exposures` (Phase 0 C-7) derived from an unowned, unversioned input, and no contract records which loading set produced them. This is structurally identical to §F.1 (universe) and to the horizon-grid finding on engine 2's sheet: a fact several engines must share at one event time, with no producer. **Recommended owner: engine 12**, which already owns calibration, with engine 5-style versioned publication — but §F resolutions come after the twelve sheets and this item is not in §F.1–7, so it is recorded for the operator (CORE §A), not resolved.

**Model finding: none.** Ranking, neutralization, turnover control and arbitration are one job under one output contract. The barrier is machinery, not a second job.

**Assumptions registered:**

- **The unit of** `SizedPositionIntent.target_positions` **is undetermined** — weights, notional, or shares. It decides whether engine 6 has crossed into engine 8's sizing. The circumstantial evidence points that way: `_compute_target_quantity` (engine 8, Phase 0 D0.2) appears on the SIGNAL path at hop 29 and at no hop on the PORTFOLIO path, and the event's own name says "Sized." One read of the field settles it, and it should be settled before engine 8's sheet.
- **Whether both paths can emit orders for one symbol on one boundary tick** — overlap 2's discriminator.
- **Whether engine 6 has any reset path** — unmeasured; Phase 1 §5's named table stops at five classes.
- **U-5 is engine 6's and stays open.** No multi-symbol whole-run baseline was found (Phase 0 D0.8), which means the axis this engine exists to serve is pinned only in isolation.
- `disclosed_cost_total_bps_by_symbol` **producer.** Flagged as an assumption on engine 4's sheet; it is a field on engine 6's event, so whichever engine computes it, engine 6 is the one publishing a cost number and must declare its provenance and unit.



## ENGINE 7 — Portfolio Accounting

**ENGINE:** 7. Portfolio Accounting

**LATENCY CLASS:** `hot` (CORE §D), and hot on **both** legs — marking at Phase 0 D0.4 hops 9 and 11 on every quote, reconciliation at hops 17 and 41 on every fill. It is the only engine that does work on every market-data event *and* every execution event, which makes it the engine whose latency budget Phase 4 cannot treat as conditional.

**OWNS:**

1. **The book of record, in process.** Lots, per-strategy positions, net positions. One writer.
2. **Marks, and the mark rule.** Which price values a position — mid, opposing side, or last — with the rule declared on the emission, not implied by the caller. The rule is a valuation policy with downstream consequences in engines 8 and 9, so it must be readable from the contract rather than inferred from an argument list.
3. **Realized and unrealized P&L**, in `Decimal`, exactly.
4. **Fill attribution** — which strategy owns which fill, totally and exactly once.
5. **The mark-before-publish ordering guarantee.** Hop 9 precedes hop 12: the book is marked before any subscriber sees the quote. Phase 0 verified this against `docs/reviews/12_engine_review.md:122-124` and rated it "correct, and load-bearing" — without it, drawdown is evaluated against a stale mark. It is a published guarantee, not an implementation accident.
6. **Divergence detection against the broker**, with cadence and tolerance — see the near-miss below for where detection stops and decision begins.
7. **Durability of the book of record**, which is a precondition of the above rather than a feature of it.

**MUST NOT OWN:**

- **Decisions of any kind.** CORE §E is absolute. Engine 7 does not block, veto, escalate, flatten, or size. It publishes numbers that cause other engines to do those things.
- **Cost and fee *modelling*.** Engine 10 owns fill and cost modelling; engine 7 accrues what engine 10 reports. Realized P&L must be net of reported fees, and engine 7 must not derive a fee it was not told.
- **Derived microstructure prices** (2). Engine 7 selects *which* price marks a position; it does not compute mid or micro-price. This is the direct continuation of the line drawn on the engine-1 sheet.
- **Mark-validity policy located anywhere but here.** The `if mid > 0` guard at `src/feelies/kernel/orchestrator.py:1607` is engine 7's rule, executed outside engine 7 — see overlap 3.
- **Risk state, high-water marks, drawdown escalation** (8).
- **Desired positions** (6). Engine 7 holds what *is*; engine 6 emits what *should be*.
- **Order state** (9/10). A pending order is not a position.
- **Alpha semantics.** `strategy_id` is an opaque key. No branch on it, no default derived from it (CORE §C.7).

**CONSUMES:**


| Input                                                                           | Staleness / validity tolerance                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NBBOQuote` for marking                                                         | Quality flags from the engine-1 contract are **binding here**: a crossed, locked or zero-side quote must not move a mark. Fail-passive — retain the last valid mark, flag it stale, emit. A single crossed tick moving a mark propagates into drawdown escalation and stop distances, so this is the highest-consequence use of engine 1's flags anywhere in the platform.          |
| Fills from engine 10, with economics (price, quantity, fees, venue, timestamps) | A fill missing economics is **unattributable, not zero-cost**. Held in a declared pending state and emitted, never booked at an assumed price.                                                                                                                                                                                                                                      |
| Broker position report                                                          | On a declared cadence (§F.4 policy pending). Absent or stale beyond the bound ⇒ divergence undetermined, which must be emitted as its own state, not as agreement.                                                                                                                                                                                                                  |
| Corporate actions (§F.2)                                                        | **Does not exist.** Phase 0 F.2 found no symbol-identity module, no ticker-change map, no split or dividend adjustment anywhere in `src/feelies/`, and symbols are bare `str` on every event. Engine 7 is where that absence becomes a wrong number rather than a wrong label: an unadjusted split silently doubles or halves a position's valuation. Registered, not assumed away. |


**EMITS:**


| Contract           | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PositionUpdate`   | Signed quantity in shares (integer); average cost and marks in `Decimal`, account currency; realized and unrealized P&L in `Decimal`; per-strategy and net, with the identity between them assertable from the payload alone. `timestamp_ns` = the event time of the causing event. Provenance: causing fill or quote, mark rule, mark side, mark staleness. |
| Mark record        | The mark, its rule, its side, its source quote, and its validity — so a consumer can tell a fresh mark from a retained one without reading engine 7's state.                                                                                                                                                                                                 |
| Attribution record | Fill → strategy, with the residual **unattributed** bucket explicit.                                                                                                                                                                                                                                                                                         |
| Divergence record  | Broker versus book, per symbol, with tolerance, cadence and the as-of times of both sides. Emitted on every check, not only on breach — a check that ran and agreed is information, and its absence must not look like agreement.                                                                                                                            |


**FORBIDDEN READS:** signals and forecasts (4); desired portfolio and target weights (6) — engine 7 must not know what the platform *intends*, or its record becomes a function of intent; risk state and limits (8); regime (3); alpha registry and lifecycle (5); features (2); raw vendor frames (1); any clock other than the injected one, and none on the marking path.

Enforcement: (a) constructor injection at the composition root; (b) import-boundary test over `portfolio/`; (c) **a read-only view type for every consumer** — engine 7's contract is "everything reads this; nothing else computes it," and a mutable handle is how the second computation starts; (d) the conservation tests below, which are the only enforcement that catches a wrong number rather than a wrong dependency.

**STATE:** lots per (strategy, symbol); net and per-strategy positions; marks and their validity; realized and unrealized P&L; attribution ledger including the unattributed residual; broker-divergence state; high-water inputs published to engine 8.

**Deterministic reset path:** unmeasured — the position stores are not among Phase 1 §5's five named no-reset classes, so their status is unknown rather than clean. **Target: cold start is the only replay contract**, one `reset()` restoring every unit above, and the ordering property fixed *at the source*: `src/feelies/portfolio/strategy_position_store.py:148` returns `{sym: … for sym in symbols}` over `symbols: set[str]` (`:145`), whose key order is seed-dependent. Phase 1 budget row 2a rates this an **open defect** because the neutralizer sits at three consumers — `src/feelies/kernel/orchestrator.py:2611` (with the comment at `:2608` naming Inv-5), `src/feelies/risk/basic_risk.py:764`, `src/feelies/harness/backtest_report.py:193` — and "a fourth consumer that iterates unsorted reintroduces seed dependence with no failing test." **The call: return an ordered mapping from the store.** One line at the producer retires an open defect that three consumers currently carry.

**Durability, stated as contract rather than aspiration.** There is no durable event log — `src/feelies/storage/memory_event_log.py:7` states all events are lost on process exit — and Phase 1 §4 records no durable submitted-order journal either. So after a restart the platform knows neither what it holds nor what it sent. **Under CORE §C.5 the exposure-reducing branch is: refuse to trade until the book is reconciled against the broker's position report.** That makes durability and reconciliation preconditions of trading rather than features of it, and it is the same shape as Phase 1's resolution for exactly-once submission — refuse to act on a key you cannot prove the state of.

**ON DEGRADED INPUT:** exposure-reducing, and the direction is fixed: uncertainty in the book must never be resolved in the direction of *more* apparent capacity.


| Condition                                          | Behaviour                                                                                                                  |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Quality-flagged quote (crossed, locked, zero-side) | Do not mark. Retain last valid, flag stale, emit.                                                                          |
| No valid mark within the staleness bound           | Position marked `stale`; consumers fail closed against a stale mark. Never a mark that silently ages.                      |
| Fill with unknown `strategy_id`                    | Booked to net, held in the **unattributed** bucket, alerted. Never dropped, never silently absorbed into another strategy. |
| Fill missing economics                             | Pending-and-emitted, not booked at an assumed price.                                                                       |
| Broker divergence beyond tolerance                 | Emit the divergence with both as-of times, and **stop asserting the book is truth**. The action is engine 8's.             |
| Broker report unavailable                          | Divergence state = undetermined, emitted. Not "agreed."                                                                    |
| Reconstruction after restart, unreconciled         | Book state = unverified; engine 8's veto is what prevents trading, not engine 7.                                           |




**ON EXCEPTION:** **halt**, not contained, on any write path. A raise mid-update leaves the book of record in an unknown state, and every downstream number — sizing, buying power, drawdown, stops, attribution — is then computed against a value nobody can vouch for. Phase 0 D0.4 records that on a tick failure "partial mutation before the raise is not rolled back — marks (hop 9), log append (hop 8) and any submitted order (hop 38) persist," which is exactly the condition this clause exists to make loud rather than survivable. A raise on a **read** path is different: it propagates to the caller and is never substituted with a value. Phase 0 E-2's `except Exception: current_positions[s] = 0.0` at `src/feelies/composition/engine.py:388` is the consumer-side instance already assigned to engine 6; the producer-side obligation is to make that substitution impossible rather than merely discouraged.

**SUBSTITUTABILITY:** a replacement must (i) satisfy every conservation identity below, which is the whole contract — an accounting engine that reproduces the identities *is* the engine; (ii) publish the same contracts with the same units and `Decimal` exactness; (iii) preserve the mark-before-publish ordering guarantee; (iv) expose `reset()` and an ordered read surface; (v) offer read-only views only. **The concrete boundary test:** CORE §I fixture 1, the null alpha, run against an analytic reference — under zero signal, position, realized P&L and unrealized P&L must be identically zero at every event, not approximately zero at the end of the run. CORE §I names this fixture's purpose as proving "level-based conservation under zero signal," and engine 7 is the engine it proves it about.

**CONFORMANCE TEST:**

1. **Conservation identities, asserted at every event, not at run end.** Σ per-strategy position = net position, per symbol. Δposition = Σ signed fill quantity. Σ lot quantities = position. ΔP&L = Σ fill cash flows + Σ (Δmark × position held). This is the test that makes "sole in-process truth" mechanical, and it is the reason engine 7 needs fewer *structural* tests than any other engine: a wrong boundary here shows up as a broken identity.
2. **Null-alpha analytic reference** (CORE §I fixture 1), as above.
3. **Attribution totality.** Σ attributed + unattributed = fill quantity, always. A non-empty unattributed bucket alerts.
4. **Mark validity.** A crossed, locked or zero-side quote moves no mark; the retained mark is flagged; the emission says which.
5. **Seed-independence at the source.** Permute `PYTHONHASHSEED`; the store's returned mapping order and all downstream output are identical **without** relying on a consumer sorting. Retires budget row 2a.
6. `Decimal` **closure on the money path.** No float reaches P&L. Money is already `Decimal` end to end (`src/feelies/core/events.py:75-76`, `:101`), which Phase 1 credits as making PnL reductions "exact and order-free" — so this test protects an existing strength rather than establishing a new one. Note the asymmetry it exposes: the arithmetic is exact while the parity hash is tolerant at `.6f`/`.2f` (Phase 1 §6), so a P&L identity can break by less than the oracle can see. The identity test, not the hash, is the guard.
7. **Read-only consumer surface.** No consumer can mutate; no read can fail into a value.
8. **Restart reconciliation.** Cold start plus broker position report ⇒ book matches, or trading is refused. Pairs with Phase 1 §4's durable-submission resolution.
9. **Parity.** Engine 7 holds three baselines — `position_pnl`, `forced_exit_attribution`, `halt_position_update` (Phase 1 §6) — and the extension is confirming which fall inside the 8 seed-tested streams (Phase 1 budget row 1).

**GAP vs CURRENT:** `portfolio/` is rated `Clear` and the money path is exactly `Decimal` (Phase 0 D0.2; Phase 1 budget row 4), but the engine's authority is exercised almost entirely outside it — three accounting methods in the kernel (`_reconcile_fills:4229`, `_distribute_fill_to_strategies:4577`, `_record_fill_attribution:4057`), a fourth in engine 5's package (`src/feelies/alpha/fill_attribution.py`), 36 direct calls into the stores from the orchestrator (`self._positions` 23, `self._strategy_positions` 13 — Phase 0 C-6), and `PositionUpdate` published to zero static subscribers (Phase 0 C-4).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

**Overlap 1 — the single source of truth is real, and it is not reached through a contract.** CORE §E's "everything reads this" is implemented as 36 direct method calls from the orchestrator into two stores, while the event that *is* the published contract, `PositionUpdate`, has no static subscriber in any mode and gains one only in backtest through the harness's dynamic subscription (Phase 0 C-4, `src/feelies/harness/backtest_runner.py:218-225`). So the invariant holds — one owner, one computation — by direct coupling rather than by boundary, and the enforcement point for those 36 calls is type annotations plus `mypy --strict`, not a runtime check (Phase 0 C-6). Flagged; the read-surface design is Phase 3's.

**Overlap 2 — accounting authored in two other packages.** The three kernel methods above, plus `src/feelies/alpha/fill_attribution.py` in engine 5's package. Same disposition as engine 5's overlap 1: placement, not a contested owner. The one open question is whether `_record_fill_attribution:4057` and `src/feelies/alpha/fill_attribution.py` are one path or two — if two, it is CORE §J's recompute-as-redundancy on attribution itself. Registered below.

**Overlap 3 — the mark-validity guard lives outside engine 7.** `if mid > 0` at `src/feelies/kernel/orchestrator.py:1607` decides whether the book gets marked, and Phase 0 D0.4 records the consequence: a quote with a non-positive mid marks nothing and still reaches hop 12, so subscribers see a quote the position store has not been marked against — a silent break in the mark-before-publish guarantee that engine 7 owns. **The call: the validity rule moves into engine 7 and becomes emitting.** The guard then covers the crossed and locked cases too, which `mid > 0` does not.

**Overlap 4 — engine 8's high-water mark is refreshed by a duck-typed poke.** Hop 10 is `getattr(..., "refresh_high_water_mark", None)` at `src/feelies/kernel/orchestrator.py:1616`. If the attribute is absent the refresh silently does not happen, and drawdown escalation then runs against a high-water mark that never moved. The seam is engine 7 → engine 8; the fix is on engine 7's side of it — publish marks as a contract that engine 8 subscribes to, rather than a value engine 8 is poked with. Recorded here, actioned on engine 8's sheet.

**Overlap 5 —** `src/feelies/portfolio/cross_sectional_tracker.py` **is permitted.** Phase 0 D0.2 rates it a 7/12 boundary but read-only, a bus observer feeding forensics. Consistent with this sheet; recorded so it is not re-litigated on engine 12's.

**§F.4 — ownership is already fixed by §E; only the policy is open.** CORE §F says none of the seven falls cleanly out of §E, but §E engine 7 explicitly reads "Owns broker reconciliation and the divergence policy." So the §F.4 turn has no owner to decide, only cadence, tolerance and action on breach. The residual is real: Phase 0 F.4 found no periodic position-of-record comparison at all, so divergence is detectable "only through the fill stream, so a fill the platform never received leaves the two out of sync indefinitely," and U-3 remains open on whether `broker/ib/` does any such comparison. No policy is set here.

**Model finding: none, and one near-miss with the call made.** CORE §E gives engine 7 "the divergence policy" and simultaneously forbids it "decisions of any kind" — and §F.4 requires the action on breach to be exposure-reducing, which is a decision. **The call: engine 7 owns the *declaration* of divergence — cadence, tolerance, the record — and engine 8 owns the *action*.** Read that way §E is consistent, engine 7 stays decision-free, and the veto stays monotone in one place. If a later phase finds engine 8 cannot act without accounting-internal state, this becomes a model finding; on the current evidence it does not.

**Assumptions registered:**

- **The mark rule is unmeasured.** `_positions.update_mark(mid, bid, ask)` receives all three (Phase 0 D0.4 hop 9), so the rule is decided inside engine 7 — correctly — but which rule is not established by Phase 0 or Phase 1. It determines unrealized P&L, drawdown escalation and stop distances, and it should be settled before engine 8's sheet.
- **Whether P&L is net of fees**, and whether engine 10 reports them per fill.
- **Whether attribution has one path or two** (overlap 2).
- **Whether the position stores have any reset path** — unmeasured.
- **U-3 stays open** — position-of-record reconciliation in `broker/ib/` (Phase 0 D0.8).
- **§F.2 is engine 7's largest silent-wrong-number exposure.** Symbol identity is unowned platform-wide; here it is not a labelling problem but a valuation one. Recorded for the §F.2 turn, not resolved.



## ENGINE 8 — Risk & Capital

**ENGINE:** 8. Risk & Capital

**LATENCY CLASS:** `hot` (CORE §D), on both legs and at four distinct points: sizing at Phase 0 D0.4 hop 29, `check_signal` at hop 31, `check_order` at hop 34, scale composition at hop 35, plus the high-water refresh at hop 10 and the buying-power phase flip at hop 16 on every quote. Two vetoes on one tick is the shape of this engine's budget.

**OWNS:**

1. **The veto, and it is monotone.** CORE §E: "risk may only reduce." Every path through this engine yields `min(what was asked, what is permitted)` and no path yields more. This is the single property from which the rest of the sheet follows, and it is the one that must be provable rather than reviewed.
2. **Sizing** — target level to permitted quantity, under buying power, exposure limits and per-alpha budgets.
3. **Exposure limits and their composition** — per-symbol, per-strategy, gross, net, sector, factor.
4. **Buying power** and its session-phase transitions.
5. **Drawdown state and escalation**, including the high-water mark.
6. **Mandatory de-risk** — the decision to reduce, and to flatten.
7. **The action on accounting divergence**, per the near-miss call made on engine 7's sheet: engine 7 declares divergence, engine 8 acts on it.
8. **The veto record** — every verdict, including every ALLOW, as an emitted contract.

**MUST NOT OWN:**

- **Accounting truth** (7). CORE §E: "Consumes positions and marks; never recomputes them." No shadow book, no locally maintained exposure that could disagree with engine 7's.
- **Forecasts and edge** (4). Engine 8 sizes an edge; it does not judge one.
- **Desired portfolio construction** (6). Engine 8 constrains a target; it does not rank, neutralize or select.
- **Cost arithmetic and the edge-versus-cost gate.** That is engine 9 policy — `_edge_clears_round_trip_cost:2184`, `_signal_passes_edge_cost_gate:2226`, `_round_trip_cost_bps:2266` (Phase 0 D0.2). A trade rejected for insufficient edge is not a risk veto, and conflating the two makes the veto non-monotone in a way no test would catch.
- **Order construction, netting, urgency, style** (9); **routing, fills, order state** (10).
- **Exit *authoring*.** Engine 8 decides that exposure must fall; the executable plan is engine 9's. Today four exit authors in `risk/` publish `OrderRequest` directly — see overlap 1.
- **The kill switch** (11). Engine 8 reads it; engine 11 owns it.
- **Alpha semantics.** `strategy_id` is an opaque budget key. No branch on it, no default derived from it (CORE §C.7).
- **Regime classification** (3) — consumed as a fact, never derived.

**CONSUMES:**


| Input                                               | Staleness / validity tolerance                                                                                                                                                                                                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Positions, marks, P&L from engine 7                 | **As-of the event time, total, and never substituted.** A stale mark ⇒ fail closed. An undetermined book (post-restart, unreconciled) ⇒ refuse to permit new exposure; this is where engine 7's durability precondition becomes an enforced behaviour rather than a stated one. |
| Divergence declaration from engine 7                | On the declared cadence. Undetermined ⇒ treated as breach, not as agreement.                                                                                                                                                                                                    |
| Desired target from engine 6                        | A level, with its unit declared.                                                                                                                                                                                                                                                |
| Per-alpha budgets from engine 5's resolved registry | Composition-time, immutable (CORE §C.10). An unregistered `strategy_id` ⇒ zero budget, not aggregate-only — see the E-2 fix below.                                                                                                                                              |
| `RegimeState` / `RegimeHazardSpike` from engine 3   | Declared per limit. `unknown` gates toward less exposure, per engine 3's fixed degradation direction.                                                                                                                                                                           |
| Kill-switch state from engine 11                    | The one permitted hot read of a cold engine (CORE §D). Read directly at `src/feelies/kernel/orchestrator.py:1561`.                                                                                                                                                              |
| Session and halt state (§F.3, pending)              | Consumed for buying-power phase; not derived.                                                                                                                                                                                                                                   |


**EMITS:**


| Contract                | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                                               |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RiskVerdict`           | Action from a closed enumeration; the **scale factor** applied, in [0, 1]; the binding constraint named; the inputs it bound against, with their as-of times and staleness. Emitted for **every** evaluation including ALLOW, because a veto record that only exists on denial cannot prove monotonicity. `timestamp_ns` = the causing event's time. |
| Escalation state change | Drawdown tier, high-water mark, the threshold crossed, and whether the transition is entering or leaving escalation — with hysteresis declared.                                                                                                                                                                                                      |
| De-risk requirement     | "Exposure in X must fall to Y by this event time" — a **requirement**, not an order. Engine 9 constructs the plan.                                                                                                                                                                                                                                   |
| Budget-state record     | Per-strategy consumption against allocation, so engine 5's next lifecycle decision reads a number rather than infers one.                                                                                                                                                                                                                            |


**FORBIDDEN READS:** raw market data and vendor frames (1); features (2); `Signal` content beyond the fields it sizes on (4); alpha registry and lifecycle state at runtime (5) — budgets arrive resolved at composition; order state, acks, routing, fill mechanics (9/10); any clock other than the injected one, and none on the veto path.

Enforcement: (a) constructor injection at the composition root with **read-only** engine-7 views — the read-only view type specified on engine 7's sheet is what structurally prevents a shadow book; (b) import-boundary test over `risk/`; (c) tree-wide alpha-literal check (CORE §I); (d) the monotonicity property test below, which is the only enforcement that catches a veto that increases exposure rather than a veto that reads the wrong thing.

**STATE:** high-water mark and drawdown tier; buying-power state and session phase; per-strategy budget consumption; escalation state and hysteresis; limit configuration resolved at composition.

**Deterministic reset path:** unmeasured — none of the `risk/` classes appear in Phase 1 §5's five named no-reset classes. Target: one `reset()`, cold start as the only replay contract, and one property that must hold across reset: **the high-water mark is monotone within a run and starts cold at the run's opening equity, never at a carried-over value.** A high-water mark that survives a restart un-fingerprinted makes drawdown escalation a function of when the process last stopped.

**ON DEGRADED INPUT:** exposure-reducing, and here it is definitional rather than aspirational: every degraded branch must produce a scale factor no greater than the nominal one.


| Condition                                      | Behaviour                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Stale or invalid mark from engine 7            | Fail closed. No new exposure; reductions still permitted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Book undetermined (post-restart, unreconciled) | Refuse new exposure; permit flattening only.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Divergence beyond tolerance, or undetermined   | De-risk requirement, emitted.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Unregistered `strategy_id`                     | **Zero budget**, alerted. Today the branch is `except KeyError: pass` at `src/feelies/alpha/risk_wrapper.py:189` — an `OrderRequest` whose `strategy_id` is not in the registry "skips **all** per-alpha risk budgets and falls through to aggregate checks only" (Phase 0 E-2). Phase 0's assessment is precise: the direction on unknown input is *fewer* constraints, not more; platform caps still apply, so it is fail-open-but-bounded. Bounded fail-open is still fail-open, and CORE §C.9 admits no bounded exception. |
| Regime `unknown`                               | The declared conservative branch per limit.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Buying power unresolvable                      | Zero, not the previous value.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Unknown `RiskAction`                           | Raise. Already correct — hop 36's exhaustiveness guard at `src/feelies/kernel/orchestrator.py:1984` "raises rather than submitting," which is the right direction and is promoted here from behaviour to contract.                                                                                                                                                                                                                                                                                                             |


**ON EXCEPTION:** **halt the decision, contained to the tick, and emit.** A raise inside a veto means the constraint was not evaluated, and an unevaluated constraint must never resolve to permission. The failure branch is: no order, `RiskVerdict` emitted with action `INDETERMINATE`, macro degraded. Containment must not become fail-quiet — this engine already owns one of the platform's two measured fail-quiet decision-path handlers (E-2 above), and it is the one whose direction is fail-open.

**SUBSTITUTABILITY:** a replacement must (i) satisfy monotonicity under composition — see test 1 — which is the whole contract; (ii) emit `RiskVerdict` on every evaluation with the same fields; (iii) consume engine 7 read-only and maintain no book; (iv) expose `reset()`; (v) be **strengthenable without core edits** — a new limit type attaches by configuration, zero edits under `kernel/`, `bus/`, `core/`, `composition/`, `execution/` (CORE §G.1). **The concrete boundary test:** CORE §I fixture 3, the pathological alpha — NaN, stale timestamps, out-of-universe symbols, duplicate IDs, self-contradictory forecasts — must produce a denial or a zero scale on every input class, each with a named binding constraint. CORE §I's stated purpose for that fixture is proving gates are fail-closed rather than fail-quiet, and engine 8 holds the last gate before exposure.

**CONFORMANCE TEST:**

1. **Monotonicity, as a property test.** For any input, permitted quantity ≤ requested quantity, and |permitted| ≤ |current| for any reduction. Composed over both vetoes and both scale factors: `_compose_scaled_quantity` at hop 35 must never produce a factor exceeding either input's, and zero must yield no order. This is the mechanical form of "the veto is monotone" and it does not exist today.
2. **Reduction-always-permitted.** In every degraded state above, a flattening order is permitted. A risk engine that can block its own de-risk is the one failure mode worse than permitting too much. Hop 31 already re-ALLOWs reductions at `src/feelies/kernel/orchestrator.py:1782`; this makes it an asserted property rather than a code path.
3. **Budget totality.** Every `strategy_id` reaching engine 8 resolves to a budget or to zero-with-an-alert. Retires E-2.
4. **No shadow book.** Instrument engine 7's stores; assert engine 8 computes no exposure not derived from a read. Any locally accumulated position or P&L fails.
5. **Verdict totality.** Every evaluation emits, including ALLOW. Enables test 1 to be checked against a run rather than only against unit inputs — and closes the gap that `RiskVerdict` is published to zero subscribers in any mode (Phase 0 C-4), which makes both of today's vetoes unobservable outside a trace.
6. **Escalation hysteresis.** No oscillation at a threshold; entering and leaving are distinct, declared transitions.
7. **High-water determinism.** Same event prefix ⇒ identical high-water and drawdown trajectory, including across the duck-typed refresh at hop 10.
8. **Parity.** Engine 8 holds three baselines — `risk_verdict`, `level4_hazard_exit_order`, `decoupled_risk_flatten_order` (Phase 1 §6). Note what the second and third are: both are *orders*, so engine 8's parity coverage today partly pins output that overlap 1 says belongs to engine 9. Whichever way the operator resolves that overlap, those two baselines re-pin.

**GAP vs CURRENT:** engine 8's most consequential behaviours are authored outside `risk/` — sizing, escalation and emergency flatten in the kernel (`_compute_target_quantity:2718`, `_escalate_risk:2530`, `_emergency_flatten_all:2601`, `_maybe_flip_buying_power_at_rth_close:782`, Phase 0 D0.2) and the per-alpha budget wrapper in engine 5's package (`src/feelies/alpha/risk_wrapper.py`) — while its own package additionally holds four engine-9 exit authors, its verdict contract has no subscriber in any mode (Phase 0 C-4), and its per-alpha budget check fails open on an unknown key (Phase 0 E-2).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

**Overlap 1 — the largest ownership contest in the review, flagged and not split.** `risk/` contains four modules that construct and publish `OrderRequest` directly: `src/feelies/risk/stop_exit.py:297`, `src/feelies/risk/hazard_exit.py:253`, `src/feelies/risk/deferral_cap.py:378`, `src/feelies/risk/exit_composer.py:486` — with `src/feelies/risk/sized_intent_orders.py` turning an approved target into per-leg orders. Phase 0 D0.2 rates these engine 9 by responsibility, in engine 8's package. The mechanism is measurable: those orders re-enter through the bus at `src/feelies/kernel/orchestrator.py:585` → `_on_bus_hazard_order:4919`, so `OrderRequest` **carries both the outbound record of hop 33 and the inbound command from engine 8, disambiguated only by a free-text** `reason` **field** (`src/feelies/core/events.py:290`, Phase 0 D0.4). Two jobs on one type distinguished by prose is the sharpest single instance of CORE §C.8 being unmet in the platform. **The direction this sheet takes, without splitting it:** engine 8 emits a *de-risk requirement*; engine 9 constructs the plan. That converts four `OrderRequest` publishers into four requirement publishers and gives the type one job. Resolved on engine 9's sheet.

**Overlap 2 — the high-water refresh is a duck-typed poke.** `getattr(..., "refresh_high_water_mark", None)` at `src/feelies/kernel/orchestrator.py:1616` (hop 10): if the attribute is absent, drawdown escalation runs against a high-water mark that never moves, with no error. Flagged on engine 7's sheet as a seam problem; the fix belongs here — engine 8 subscribes to engine 7's mark contract rather than being poked with a value. Cheap, and it removes a silent-wrong-number path from the escalation ladder.

**Overlap 3 —** `_compute_target_quantity` **sits on the SIGNAL path only.** Hop 29 has no counterpart on the PORTFOLIO path (Phase 0 D0.4), which is the evidence behind the engine-6 assumption about what `SizedPositionIntent.target_positions` actually carries. If the portfolio path arrives pre-sized, engine 6 has performed engine 8's job for that path and engine 8's monotonicity guarantee covers only half the platform. **This is the discriminating question for both sheets** and it is one field read.

**Overlap 4 — engine 8's package holds the buying-power and escalation modules while the kernel calls them.** Placement, consistent with engines 5 and 7. Recorded once.

**Model finding: none, and one near-miss with the call made.** CORE §E gives engine 8 both a *per-decision veto* (hot, synchronous, per-order) and a *portfolio-state manager* role (drawdown, buying power, budgets — stateful, session-scoped, cross-tick). They pull opposite ways on state: the veto should be as close to a pure function of (request, current state) as possible so it is testable and monotone; the state manager necessarily accumulates. **The call: they are one engine with two declared surfaces** — a pure `evaluate(request, state) → verdict` and a state-advancing `observe(event) → state`, with the veto never mutating. That keeps test 1 tractable, and it is why `reset()` above is specified over the state surface only. If a later phase finds the veto cannot be written without mutation, this becomes a model finding.

**Assumptions registered:**

- **Whether engine 8 maintains any exposure state independently of engine 7.** Decides whether test 4 currently passes or is a defect. Phase 0 rates `risk/` **Mixed** but on engine 8/9 grounds, not on a shadow-book finding — so this is unmeasured, not cleared.
- **The composition rule for the two vetoes.** Hops 31 and 34 each publish a verdict and hop 35 composes both scale factors; whether composition is multiplicative, minimum, or something else determines whether monotonicity holds by construction or by coincidence.
- **Whether** `_escalate_risk:2530` **and** `_emergency_flatten_all:2601` **are reachable from anything other than the kernel** — bears on how much of the veto surface a substituted engine 8 would actually control.
- **Whether the four exit authors read engine 7 directly.** If they do, overlap 1 is not only a placement problem: engine 9 work reading engine 7 state is permitted, but four independent readers with four independent staleness policies is a recompute-as-redundancy risk on exit timing.
- **§F.5 is engine 8-adjacent and stays open.** Phase 0 F.5 found no platform-wide taxonomy of recoverable versus fatal, and this engine's ON EXCEPTION clause assumes one exists to fail into. Recorded for the §F.5 turn.



## ENGINE 9 — Execution Decision

**ENGINE:** 9. Execution Decision

**LATENCY CLASS:** `hot` (CORE §D), and it is the last engine that can decline. Phase 0 D0.4 puts it at hops 30 (intent construction), 32 (admission), 33 (order construction with the min-size gate), and 37 (duplicate-pending suppression), plus the exit-authoring paths at hop 15 and via the bus at `src/feelies/kernel/orchestrator.py:585`.

**OWNS:**

1. **Policy: approved target delta → executable plan.** Everything between "engine 8 permits X" and "engine 10 has an order to work."
2. **Netting.** Legs, opposing intents, and the reduction of a set of requirements to a minimal order set.
3. **Urgency, style and participation** — passive versus aggressive, limit versus market, participation rate — as **declared policy inputs to engine 10**, never as mechanics performed here.
4. **The edge-versus-cost gate.** A trade whose expected edge does not clear its round-trip cost is declined *here*, and the decline is an execution-policy decision, not a risk veto. This is the placement the engine-8 sheet reserved for it.
5. **Admission.** Halt blackout, flatten windows, SSR, locate — the regulatory and session preconditions on *whether this order may be constructed now*.
6. **Exit plan construction.** Engine 8 emits "exposure in X must fall to Y"; engine 9 turns that into orders. This is the resolution promised on engine 8's sheet.
7. **Duplicate-intent suppression** — the policy on an outstanding order for the same target.
8. **The decline record.** Every intent that does not become an order emits, with the gate that stopped it.

**MUST NOT OWN:**

- **Mechanics.** CORE §E is one word for a reason: no order state machine, no fill modelling, no venue selection, no submission, no acks, no retries. Those are engine 10 and the mode seam lives there.
- **Sizing or the veto** (8). Engine 9 may reduce a plan to zero orders through its own gates; it must never *increase* a permitted quantity, and it must not re-evaluate a risk limit.
- **Whether exposure should fall** (8). Engine 9 plans the reduction; it does not decide one is needed.
- **Accounting truth** (7) — consumed, never computed. **Desired portfolio** (6) — consumed as approved target.
- **Cost *modelling*** (10). Engine 9 consumes a cost estimate to gate on; engine 10 owns the model that produces it and the realized cost that comes back.
- **Alpha semantics.** No branch on `alpha_id`, archetype or horizon (CORE §C.7). This engine hosts the platform's one measured live violation — see the defect below.
- **The kill switch** (11) or session state as a producer (§F.3).

**CONSUMES:**


| Input                                                                                       | Staleness / validity tolerance                                                                 |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Approved target / permitted quantity from engine 8                                          | As-of the tick. An approval is consumed once; re-consuming it is duplicate exposure.           |
| De-risk requirement from engine 8                                                           | Carries a deadline in event time; unmet by it ⇒ escalate to engine 11, never silently drop.    |
| Positions and marks from engine 7                                                           | Read-only, as-of event time. Stale mark ⇒ no new plan; reductions still plannable.             |
| Cost estimate from engine 10's model                                                        | Versioned, with its assumptions declared. **Unavailable ⇒ decline, not proceed at zero cost.** |
| Session, halt, SSR, locate state (§F.3 pending; `src/feelies/execution/trading_session.py`) | Binding at construction time. Undetermined ⇒ decline.                                          |
| Engine-1 quality flags via the mark                                                         | A crossed or zero-side book must not set a limit price.                                        |


**EMITS:**


| Contract                         | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Executable plan / `OrderRequest` | Side, quantity in shares, order type, limit price in `Decimal`, urgency, style, participation cap, time-in-force, and a **declared expiry in event time**. Provenance: originating approval, `strategy_id`, the cost estimate and version it cleared, the gates it passed. `timestamp_ns` = the causing event's time. |
| Decline record                   | One per intent that did not become an order, naming the binding gate. Emitted, not traced.                                                                                                                                                                                                                            |
| Plan-to-requirement accounting   | For a de-risk requirement: the orders that discharge it, so engine 8 and engine 11 can see whether the requirement was met.                                                                                                                                                                                           |


**The one-job rule for** `OrderRequest`**.** Today the type carries both the outbound record of hop 33 and the inbound command from engine 8's four exit authors, "disambiguated only by the free-text `reason` field" (`src/feelies/core/events.py:290`, Phase 0 D0.4). Under this sheet the inbound direction disappears: engine 8 emits requirements, engine 9 emits orders, and `OrderRequest` means exactly one thing. That is the resolution of engine 8's overlap 1, and it requires no new event type — it removes a use, not adds one.

**FORBIDDEN READS:** raw market data and vendor frames (1); features (2); regime (3) — engine 9 consumes urgency implications through engine 8's approval, not by classifying; `Signal` internals beyond the declared edge and horizon it gates on (4); alpha registry and lifecycle (5); order state machine internals, acks, fills (10) — engine 9 knows *that* an order is outstanding, not its mechanics; any clock other than the injected one.

Enforcement: (a) constructor injection at the composition root; (b) an import-boundary test splitting `execution/` — engine 9 modules must not import router, backend, broker or fill-model symbols, which is the only mechanical defence of the policy/mechanics line given both engines share a package by design (CORE §B); (c) tree-wide alpha-literal check (CORE §I) — see the defect; (d) the no-increase property test below.

**STATE:** outstanding-intent set for duplicate suppression; pending de-risk requirements and their deadlines; per-tick netting buffer; admission state as-of the tick.

**Deterministic reset path:** unmeasured. What *is* measured is the recovery path: `_handle_tick_failure` clears `_pending_sized_intents` (Phase 1 §5, `src/feelies/kernel/orchestrator.py:1474`) — three named attributes, not a declared reset over declared state. Target: one `reset()`; cold start as the only replay contract; and an explicit rule that **an outstanding de-risk requirement does not survive a reset silently** — it is either re-derived from engine 8 or emitted as dropped.

**ON DEGRADED INPUT:** exposure-reducing, and asymmetric by design — the bar to *open* is higher than the bar to *close*.


| Condition                                        | Behaviour                                                                                                                          |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Cost estimate unavailable or stale               | Decline new exposure. Reductions proceed with cost unpriced-and-marked.                                                            |
| Mark stale or quality-flagged                    | No limit price derived from it. Decline, or plan a style that does not require one.                                                |
| Admission state undetermined (halt, SSR, locate) | Decline and emit.                                                                                                                  |
| Duplicate pending for the same target            | Suppress, emit. Hop 37 already "blocks only; never cancel-then-submit" (Phase 0 D0.4) — the right direction, promoted to contract. |
| De-risk deadline missed                          | Escalate to engine 11. Never expire quietly.                                                                                       |
| Below min size                                   | Decline and emit; hop 33's min-size gate today produces no record.                                                                 |


**ON EXCEPTION:** contained per intent, emitting, and **all-or-nothing per plan**. A partially constructed multi-leg plan is not a smaller version of the intended one — it is an unhedged fragment, and for a netted or paired plan the fragment can be the opposite of exposure-reducing. The failure branch is: no orders from that plan, decline record emitted, and any de-risk requirement it was discharging remains outstanding and visible rather than silently consumed.

**SUBSTITUTABILITY:** a replacement must (i) emit the same plan contract with the same fields and expiry semantics; (ii) satisfy no-increase (test 1) and the discharge identity (test 2); (iii) be **policy-swappable by configuration** — passive-first, aggressive-on-urgency, participation-capped — with zero edits under `kernel/`, `bus/`, `core/`, `composition/`, `risk/` (CORE §G.1); (iv) emit orders through the same contract regardless of mode, since the mode seam is engine 10's alone. **The concrete boundary test:** engine 9 must be substitutable *without touching engine 10*, and vice versa. If changing the passive/aggressive policy requires editing a router, the policy/mechanics boundary is a package comment.

**CONFORMANCE TEST:**

1. **No-increase.** Σ|planned quantity| ≤ approved quantity, per symbol per tick, across every path including exits. Engine 8 proves monotone permission; this proves engine 9 does not spend more than it was given.
2. **Discharge identity.** Every de-risk requirement is either discharged by named orders, or outstanding, or emitted as dropped. No fourth outcome.
3. **Decline totality.** Intents in = orders out + declines out, per tick, each decline naming its gate. The conservation test that makes hop 33's silent min-size rejection impossible.
4. **Policy/mechanics import split.** As above; fails today only if engine-9 modules import router symbols, which is unmeasured.
5. **Expiry in event time.** No plan expiry computed from wall clock. Directly at risk here: `src/feelies/kernel/orchestrator.py` is on the wall-clock allowlist as a whole file (Phase 1 §1), 10 of the 12 missed `perf_counter_ns` reads are in it, and hop 30's planner lives in it.
6. **Idempotent replan.** Same approval delivered twice ⇒ one order set. Pairs with duplicate suppression.
7. **Alpha-agnosticism.** Route and order type must not vary with `alpha_id` — see the defect.
8. **Parity.** Engine 9's outputs are pinned today under engine 8's baselines (`level4_hazard_exit_order`, `decoupled_risk_flatten_order`) and engine 1/9's halt path (`symbol_halted`, `halt_order` — Phase 1 §6). Moving exit authoring to engine 9 re-pins both; the operator should expect that as a declared step, not a surprise.

**GAP vs CURRENT:** engine 9 is the most dispersed engine in the platform — nine of its methods sit in the kernel (`_plan_for_signal:2814`, `_try_build_order_from_intent:3278`, `_resolve_order_route:3371`, `_filter_portfolio_orders_for_admission:3505`, `_execute_reverse:2984`, and the four cost-gate methods at `:2184`, `:2226`, `:2266`, `:2295`), four exit authors and a per-leg order builder sit in engine 8's package, and its policy modules sit in `execution/` alongside engine 10's mechanics (Phase 0 D0.2) — and it is the only engine carrying a `VERIFIED` alpha-agnosticism violation on a live execution path.

---



### Standing checks for this sheet

**Defect recorded (CORE §I): E-1 is engine 9's.** Phase 0's escalated finding lands squarely inside this engine's ownership. `moc_strategy_ids: tuple[str, ...] = ("sig_moc_imbalance_v1",)` at `src/feelies/core/platform_config.py:108`, with the same literal as the YAML fallback at `:910`, reaches `_moc_strategy_ids` at `src/feelies/kernel/orchestrator.py:876` and is tested at `:3386` to set `OrderRequest.is_moc`, "which diverts the order from the continuous book to the closing auction" (`src/feelies/core/events.py:288`). Measured blast radius: no file under `configs/` or `platform.yaml` sets it, so every deployment inherits the hardcoded default.

CORE §I states the test twice, and this fails both: a rule that cannot be stated without naming the alpha is a defect, and no `alpha_id` literal may exist outside `alphas/` and configuration. **Route selection is engine 9 policy; a route selected by a string literal in platform config is that policy being expressed as an identity check.** The target-state statement is route-by-declared-property — an order's route follows from urgency, style and session, all of which the alpha's manifest may *declare* — never from membership in a hardcoded ID list. Phase 0's proposed containment (default to `()`, fail loudly on an unknown `alpha_id`) is a containment, not the target; recorded, and this phase does not fix.

**Overlap 1 — RESOLVED here, as promised on engine 8's sheet. Exit authoring is engine 9's.** The argument: engine 8's job is to decide exposure must fall; deciding *how* — which legs, what urgency, what limit price, whether to net against a pending order — is the same job engine 9 does for entries, and doing it twice in two packages is why `OrderRequest` currently carries two meanings. Under the resolution, `src/feelies/risk/stop_exit.py`, `src/feelies/risk/hazard_exit.py`, `src/feelies/risk/deferral_cap.py` and `src/feelies/risk/exit_composer.py` emit **requirements**; engine 9 constructs the plan; the inbound `OrderRequest` path at `src/feelies/kernel/orchestrator.py:585` → `_on_bus_hazard_order:4919` disappears. Two consequences to state up front: four parity baselines re-pin (test 8), and the four authors' independent engine-7 reads collapse into one, which retires the staleness-divergence risk registered on engine 8's sheet.

**Overlap 2 — the policy/mechanics line inside** `execution/`**.** CORE §B states both engines live there by design and Phase 0 rates it **Mixed by design**, with `src/feelies/execution/order_admission.py`, `intent*.py`, `src/feelies/execution/portfolio_netter.py`, `src/feelies/execution/min_cost_policy.py` as policy and routers, fill models, session/MOC constraints and backends as mechanics. The line is drawn correctly at module level; nothing enforces it, which is what test 4 is for. Not a contest — a missing check.

**Overlap 3 — two intent-construction paths.** Hop 30 uses a planner "or `_intent_translator` fallback at `:1740`" (Phase 0 D0.4). Whether the fallback produces an identical plan to the planner is unmeasured; if not, it is CORE §J's recompute-as-redundancy on the executable plan itself. Registered.

**Overlap 4 — admission is shared with the PORTFOLIO path.** Hop 32 states `admission_block_reason` is "shared with the PORTFOLIO path," which is correct and is the one place the two paths demonstrably converge on one gate. Recorded as a positive; it is also the strongest evidence that the two paths both reach order construction, which is engine 6's open overlap 2.

**Model finding: none.** Netting, urgency, admission, cost-gating and exit planning are one job — turning permitted exposure change into an executable plan — under one output contract.

**Assumptions registered:**

- **Whether the cost gate reads live spreads or declared manifest cost.** It is engine 9's either way; the answer determines whether `_round_trip_cost_bps:2266` is a legitimate engine-9 computation or a duplicate of an engine-10 model. Bears on the `disclosed_cost_total_bps_by_symbol` question already open on engines 4 and 6.
- **Whether the four exit authors read engine 7 directly** — carried from engine 8's sheet; overlap 1 makes it moot if resolved.
- **Whether** `_resolve_order_route:3371` **has any input other than** `_moc_strategy_ids`**.** Decides whether E-1's fix is a one-line default change plus a config contract, or a route-policy design.
- **Whether the planner and** `_intent_translator` **agree** (overlap 3).
- **Engine 9's reset status is unmeasured**; `_pending_sized_intents` clearing is a recovery path, not a reset.
- **CORE §J's passive-fill anti-pattern is explicitly *not* an engine-9 finding.** Phase 0 checked it directly and found both passive paths enforce the timing gate in **exchange** time (`src/feelies/execution/passive_limit_router.py:527` for quote-driven fills, `:242` for trade-driven queue drain), rated `implemented`. Recorded here so the engine-10 sheet inherits the verified state rather than re-litigating it.



## ENGINE 10 — Execution Simulation / Routing

**ENGINE:** 10. Execution Simulation / Routing

**LATENCY CLASS:** `hot` (CORE §D). Phase 0 D0.4 puts it at hops 14 (backtest router evaluating resting orders on every quote), 38 (submit), 39 (poll and publish acks), 40 (apply ack), and the fill-reconciliation trigger at 17. It is the only engine whose hot work is *mode-shaped* — hop 14 is BACKTEST-only — which is exactly why the seam has to be selection, not branching.

**OWNS:**

1. **The single mode seam.** CORE §C.4: backtest, paper and live share core logic and mode differences live behind `ExecutionBackend` and nowhere else. Engine 10 is that "nowhere else."
2. **The order state machine** — every transition, and the fact that transitions are total.
3. **Fill and cost modelling**, including queue position and fill eligibility in simulation.
4. **Exactly-once submission across restart and reconnect** — durable, not in-process.
5. **Session and regulatory constraints as mechanics** — auction eligibility, MOC cutoffs, tick-size rules, venue hours.
6. **Broker adapters and routing.**
7. **The realized-cost report** back to engines 7 and 12 — what the fill actually cost, as distinct from what engine 9's gate assumed it would.

**MUST NOT OWN:**

- **Policy.** CORE §E: "Must not decide size, urgency, or whether to trade." Engine 10 may decline for a *mechanical* reason — venue closed, order rejected, tick-size invalid — and must emit; it may never decline for an economic one.
- **Route selection by alpha identity.** The E-1 defect recorded on engine 9's sheet reaches its consequence here, at `OrderRequest.is_moc` (`src/feelies/core/events.py:288`). Engine 10 executes the route; it must not be the place a route is chosen by ID.
- **Accounting** (7). Engine 10 reports fills with economics; engine 7 books them. No P&L computed here.
- **The cost *gate*** (9). Engine 10 owns the cost model and publishes estimates; the decision to trade on one is engine 9's.
- **Order construction, netting, sizing** (9/8). An arriving order is executed as specified or rejected with a reason.
- **Retry-as-policy.** A mechanical retry after a transient disconnect is mechanics; deciding to re-attempt a trade whose conditions have changed is engine 9's.
- **Alpha semantics** (CORE §C.7).

**CONSUMES:**


| Input                                    | Staleness / validity tolerance                                                                                                                 |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `OrderRequest` from engine 9             | Carries its own expiry in event time. An order arriving past expiry is rejected with a reason, never worked.                                   |
| Market data for simulation fills         | **In exchange time, and only at or after the order was live and latency-eligible.** This is the load-bearing input; see the anti-pattern note. |
| Broker acks, fills, rejects, disconnects | Duplicate-safe by construction; an ack for an unknown order is a divergence event, not a discard.                                              |
| Durable submitted-order journal          | **Does not exist** (Phase 1 §4). See the defect.                                                                                               |
| Session, halt, SSR state (§F.3 pending)  | Binding at submission; undetermined ⇒ do not submit.                                                                                           |


**EMITS:**


| Contract                            | Units, timestamp semantics, provenance                                                                                                                                                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OrderAck` / order state transition | From-state, to-state, cause, venue, broker identifiers. `timestamp_ns` = the causing event's time; broker times carried separately and labelled.                                                                                                      |
| Fill                                | Price and fees in `Decimal`, quantity in shares, venue, liquidity flag, **exchange execution time and receipt time distinguished**, and the parent `order_id`. A fill without economics is not a fill — it is a pending report (engine 7's contract). |
| Cost model estimate                 | Per candidate order, with **model version and declared assumptions** — latency, queue-position method, participation. Consumed by engine 9's gate; without the version the gate cannot be audited after the fact.                                     |
| Realized-cost report                | Estimated versus realized, per fill, feeding engine 12's calibration. This closes the loop CORE §G.9 requires and is the only mechanism by which a wrong cost model becomes visible rather than merely expensive.                                     |
| Rejection record                    | Every mechanical decline, with reason.                                                                                                                                                                                                                |


**FORBIDDEN READS:** positions, marks, P&L (7) — a router that knows the book will eventually use it; risk state and limits (8); `Signal` and forecasts (4); features (2); regime (3); alpha registry and lifecycle (5); `alpha_id` as a routing input (see E-1); any clock other than the injected one on any path that affects fill eligibility.

Enforcement: (a) constructor injection at the composition root; (b) the `execution/` import split specified on engine 9's sheet, in the other direction — engine 10 modules must not import policy symbols; (c) the mode-branch check below, which is the enforcement CORE §C.4 currently lacks; (d) tree-wide alpha-literal check (CORE §I).

**STATE:** order state machine per order; submitted-order journal; resting-order book in simulation with queue-position estimates; broker connection and `nextValidId` state; venue and session constraint state; fill and cost model parameters.

**Deterministic reset path: none, and the state is the largest of any engine after the orchestrator.** Phase 1 §5 names three engine-10 classes in its top five: `PassiveLimitOrderRouter` (34 attributes in `__init__`, 10 mutated elsewhere, **no reset**), `BacktestOrderRouter` (21 / 5, none), `IBGatewayConnection` (16 / 5, none). Target: one `reset()` per component, cold start as the only replay contract, and — the part that is not a reset — the submitted-order journal is **durable and must not be reset by replay**, exactly the registry/ledger split made on engine 5's sheet.

**ON DEGRADED INPUT:** exposure-reducing, and here that means *do not submit* rather than *submit carefully*.


| Condition                                                 | Behaviour                                                                                                                                                               |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Order ID cannot be proven absent from the durable journal | **Refuse to submit.** Phase 1 §4's stated resolution, and it makes durability a precondition of trading rather than a feature.                                          |
| Broker disconnected or state unknown                      | No new submissions; reconcile on reconnect before resuming.                                                                                                             |
| Ack for an unknown order                                  | Divergence event to engines 7 and 11. Never discarded.                                                                                                                  |
| Market data stale or quality-flagged in simulation        | No fill inferred from it. A crossed book must not fill a resting passive order.                                                                                         |
| Session or halt state undetermined                        | Do not submit.                                                                                                                                                          |
| Cost model unavailable                                    | Emit the absence; engine 9 declines. Engine 10 must not substitute a default cost — a zero-cost default is the fill-eligibility anti-pattern wearing different clothes. |


**ON EXCEPTION:** contained per order, emitting, and **never contained across a submission boundary**. A raise after the wire and before the journal write is the one case with no safe containment: the platform may have an order it cannot prove it sent. The required behaviour is halt-and-reconcile, not continue. Phase 0 D0.4 records the current shape — partial mutation before a raise is not rolled back and "any submitted order (hop 38) persists" — which is precisely why the journal write must precede the wire, not follow it.

**SUBSTITUTABILITY:** this is the platform's most consequential boundary, because CORE §G.8 turns it into a falsifiable criterion: research and production share one code path, seam only at `ExecutionBackend`, **proven by a parity test**. A replacement must (i) implement the same backend interface with the same order state machine and the same transition totality; (ii) report fills with the same economics and time bases; (iii) expose `reset()` and honour journal durability; (iv) require **zero** mode branches anywhere outside itself. **The concrete boundary test:** swapping backtest for paper changes the backend construction at the composition root and nothing else. Today that is 24 branches away from true — see overlap 1.

**CONFORMANCE TEST:**

1. **Fill-eligibility parity between passive and aggressive paths.** CORE §J names the anti-pattern and Phase 0 checked it directly: both passive paths enforce the timing gate in **exchange** time — `src/feelies/execution/passive_limit_router.py:527` for quote-driven fills, `:242` for trade-driven queue drain — rated `implemented`. **This test exists to keep it true**, not to discover it. It is the highest-value regression test in the platform, because the failure it guards is biased rather than noisy, and CORE §H requires it be audited whenever a router changes rather than only when a result looks wrong.
2. **Mode-branch closure.** Zero `OperatingMode` branches outside `execution/` and `broker/`. Phase 0 C-8 measured **24** such branches, all outside those packages, and made the sharp observation that `execution/` itself contains zero — "the seam does not branch, it is selected." So the seam is correct and the platform routes around it. This test is CORE §C.4's missing enforcement.
3. **Exactly-once across restart.** Kill mid-submission, restart, assert no duplicate reaches the broker. Retires Phase 1 §4's open defect. Note the failure direction Phase 1 states: the derived `order_id` is stable across restart, so a restart re-derives the same ID and **re-submits** it — a stable key with nothing to look it up in.
4. **Order state machine totality.** Every (state, event) pair defined; unknown pairs raise rather than proceed — the same discipline as hop 36's exhaustiveness guard on engine 8's side.
5. **Cost model calibration.** Estimated versus realized, reported per fill, with drift surfaced to engine 12. Without it, engine 9's gate is unfalsifiable.
6. **Backend substitution.** As above; assert zero diff outside the composition root.
7. **Parity.** Engine 10 holds two baselines — `market_fill_acks`, `halt_ack` (Phase 1 §6). The gap is that neither is a *passive* fill sequence, so the property test 1 protects is not itself pinned by a baseline. Adding one is the cheapest coverage gain on this sheet.



**GAP vs CURRENT:** engine 10's own package is the cleanest instance of the seam pattern in the platform — zero mode branches inside `execution/`, both passive fill paths correctly gated in exchange time (Phase 0 C-8, D0.4) — while 24 mode branches sit outside it, three of its classes are the largest no-reset state holders after the orchestrator (Phase 1 §5), six of its transitions are authored in the kernel (`_submit_tracked_order:3831`, `_poll_order_router_acks:3793`, `_apply_ack_to_order:4103`, `_transition_order:4086`, `_drain_async_fills:3936`, `cancel_order:3438` — Phase 0 D0.2), and its exactly-once guarantee is in-process only (Phase 1 §4).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean. E-1's consequence is visible here at `OrderRequest.is_moc`, but the rule that names the alpha lives in platform config and is recorded against engine 9.

**Overlap 1 — the seam is right and the platform routes around it.** 24 `OperatingMode` branches outside `execution/` and `broker/` (Phase 0 C-8), against a seam that itself contains none. Two of them are already visible in this review's own evidence and are worth naming because they are not cosmetic: `src/feelies/bootstrap.py:203` sets `enforce_market_order = config.mode != OperatingMode.PAPER`, which is Phase 1's open defect on silent reordering; and hop 14's backtest-only router subscription (`src/feelies/bootstrap.py:353`) means the resting-order evaluation path exists in one mode only. **The call: composition-root selection is legitimate, in-engine mode branching is not.** Those two are different things and the 24 need splitting on that line before any of them is called a defect — which is Phase 3's flow work, not this sheet's.

**Overlap 2 — order mechanics authored in the kernel.** Six named methods above. Placement, consistent with engines 5, 7, 8 and 9, and the largest remaining block of the god orchestrator after engine 9's nine methods. Recorded once.

**Overlap 3 —** `OrderAck` **and** `PositionUpdate` **gain consumers only in backtest**, via a dynamic subscription that reaches through `orchestrator._bus`, a private attribute (Phase 0 C-4, C-5, `src/feelies/harness/backtest_runner.py:246`). So engine 10's two principal published contracts are observable in one mode, through an encapsulation break, and the subscriber set is not statically enumerable. Flagged; the read-surface design is Phase 3's, and it is the same shape as engine 7's `PositionUpdate` finding.

**Overlap 4 — §F.4 reconciliation is jointly held.** Engine 7 owns divergence declaration (already settled); engine 10 owns the fill and order stream that feeds it. Phase 0 F.4 found no periodic position-of-record comparison, and U-3 — whether `broker/ib/` performs one beyond the fill stream — remains open and belongs to this engine. Recorded for the §F.4 turn.

**Model finding: none, and one near-miss with the call made.** Engine 10 carries *simulation* and *routing* in one engine, which look like two jobs: one models a counterparty, the other talks to one. **They are one job under CORE §G.8** — the whole point of the seam is that both implement the same backend interface and the same order state machine, and separating them into two engines would give the platform two order state machines and reintroduce exactly the research/production divergence §G.8 exists to forbid. The near-miss is worth recording because it is the most plausible-looking wrong split available in the 12-engine model.

**Defect recorded (CORE §I / CORE §J): exactly-once submission is in-process only.** Both halves are non-durable — `self._submitted_order_ids: set[str] = set()` at `src/feelies/execution/passive_limit_router.py:183`, whose own comment calls it the set "ever submitted" where *ever* means since construction; and `nextValidId` at `src/feelies/broker/ib/connection.py:353`, correct about the reconnect it can see (`max(self._next_valid_id, orderId)` at `:364`) but rebuilt from the broker handshake each process. There is no durable submitted-order journal anywhere in `src/feelies/`, and `src/feelies/storage/memory_event_log.py:7` states all events are lost on process exit. Phase 1 §4 rates it `open defect`; this sheet makes the target behaviour explicit — journal before wire, refuse on unprovable absence.

**Assumptions registered:**

- **Whether the cost model is versioned or reported at all.** The EMITS clause requires both; neither is established by Phase 0 or Phase 1. Determines whether engine 9's gate is auditable and whether test 5 is a new capability or a new assertion.
- **Whether fills carry fees.** Carried from engine 7's sheet; it is engine 10 that must supply them.
- **U-3 stays open** — position-of-record reconciliation in `broker/ib/`.
- **Whether the queue-position model is documented anywhere.** Test 1 protects the timing gate; nothing yet establishes what the fill probability model *is*, and an undocumented queue model is an unfalsifiable one.
- **Whether** `cancel_order:3438` **has a policy caller.** Hop 37 states duplicate suppression "blocks only; never cancel-then-submit," so cancellation exists as mechanics with no measured policy path into it. If engine 9 gains a cancel-replace policy, this is the seam it must use.



## ENGINE 11 — Observability & Safety

**ENGINE:** 11. Observability & Safety

**LATENCY CLASS:** `cold`, **except the kill-switch read** — CORE §D grants exactly one hot exception and it is measured at Phase 0 D0.4 hop 4: a direct `is_active` read at `src/feelies/kernel/orchestrator.py:1561` that returns early. Metrics recording is also hot in practice (hop 42, `_finalize_tick:2092`), but it is hot *emission* off the decision path, not hot *decision-making* — a distinction this sheet has to hold, because it is what keeps the exception to one.

**OWNS:**

1. **The kill switch.** The single fail-closed authority that can stop the platform, and the only engine-11 surface any hot path may read.
2. **Health state**, with the four-way distinction CORE §E mandates: `never-seen` / `stale` / `degraded` / `healthy`. Three-way collapse — where never-seen reads as healthy — is CORE §J's silent-degradation anti-pattern and this engine is where it is prevented.
3. **Assumption-violation monitoring.** CORE §E is explicit that kill switches monitor latency drift, fill-rate drift, regime break, contract rejection rate and reconciliation divergence "as well as P&L." The ordering matters: P&L is the last signal to arrive, not the first.
4. **Metrics and alerts** as durable contracts, not log lines.
5. **Durable operator and session records.**
6. **The alert taxonomy** — `alert_name` and `severity` as a closed, versioned enumeration.
7. **Escalation routing** — which condition reaches a human, on what latency.

**MUST NOT OWN:**

- **Trading logic.** CORE §E. Engine 11 stops trading; it never sizes, prices, routes or selects.
- **De-risking as a plan.** The kill switch is binary and total: halt. A graduated reduction is engine 8's de-risk requirement discharged by engine 9. Giving engine 11 a partial-reduction lever would create a second, uncoordinated risk authority.
- **Accounting truth** (7), **risk state** (8) — both consumed, neither recomputed. A monitoring engine that recomputes P&L to check P&L is CORE §J's recompute-as-redundancy with a safety label on it.
- **Regime classification** (3). Engine 11 alerts on a regime *break* reported by engine 3; it does not detect one.
- **Health of a fact it does not receive.** Engine 11 cannot infer that a stream is healthy from the absence of a complaint — which is precisely the mechanism that makes `never-seen` a required state rather than a nicety.
- **Alpha semantics** (CORE §C.7) — alerts are keyed by `strategy_id` as an opaque label.

**CONSUMES:**


| Input                                            | Staleness / validity tolerance                                                                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Health and gap notifications from engine 1       | Per-stream heartbeat; absence beyond the bound ⇒ `stale`, never `healthy`.                                                                                   |
| Latency measurements from the tick path          | Wall-clock derived, telemetry-only, and by construction excluded from every parity hash (Phase 1 §6).                                                        |
| Fill-rate and cost-drift reports from engine 10  | On a declared cadence; absence ⇒ `never-seen`, which is an alertable state.                                                                                  |
| Divergence declarations from engine 7            | Undetermined ⇒ treated as breach, matching engine 8's rule so the two authorities cannot disagree.                                                           |
| `RiskVerdict` and escalation state from engine 8 | The rejection-rate signal.                                                                                                                                   |
| Contract-rejection counts from every boundary    | Requires the loud-failure behaviour CORE §G.3 mandates; today most boundaries are annotations plus `mypy --strict` rather than runtime checks (Phase 0 C-6). |
| Operator action                                  | Authenticated, recorded with actor and reason.                                                                                                               |


**EMITS:**


| Contract               | Units, timestamp semantics, provenance                                                                                                                                                                                                                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Alert`                | `alert_name` and `severity` from a **closed, versioned enumeration**; message as free text that no consumer may parse; `context` typed and immutable; the assumption violated and its measured versus expected value. Time base declared — engine 11 is the one engine whose emissions legitimately carry wall time, so it must say so. |
| `MetricEvent`          | Name, value with a **declared unit**, `metric_type`, tags.                                                                                                                                                                                                                                                                              |
| Health state           | Per stream, per symbol, per engine, in the four-way enumeration, with the as-of time of the last observation and the bound that would make it stale.                                                                                                                                                                                    |
| `KillSwitchActivation` | Trigger, measured value, threshold, actor, and the scope halted.                                                                                                                                                                                                                                                                        |
| Durable session record | Survives process exit — this is the one emission whose value is entirely in its durability.                                                                                                                                                                                                                                             |


**FORBIDDEN READS:** `Signal` content (4); features (2); raw market data (1) — engine 11 consumes engine 1's *health*, not its stream; alpha registry and lifecycle (5); order construction internals (9); anything engine 11 would have to recompute rather than receive. The wall clock **is** permitted here and nowhere else on the emission path, provided the value never re-enters a decision.

Enforcement: (a) constructor injection at the composition root; (b) a **one-way-read test** — engine 11 is read by exactly one hot-path caller (the kill-switch check) and reads no engine's internals; (c) the no-decision test below; (d) tree-wide alpha-literal check (CORE §I).

**STATE:** kill-switch state and its trigger history; per-stream and per-engine health with last-observation times; metric accumulators; alert dedupe and rate-limit state; escalation state; the durable session record.

**Deterministic reset path — and the split matters more here than anywhere except engine 5.** Metric accumulators and health state are per-run and cold-start. **The kill switch and the operator record are not.** A kill switch that resets on restart is a kill switch that can be cleared by crashing, and Phase 1 §4 establishes that nothing in the platform is durable — `src/feelies/storage/memory_event_log.py:7` states all events are lost on process exit. **The call: kill-switch state is durable and survives restart; clearing it is an authenticated operator action, recorded.** That is the same durability precondition already stated for engine 10's submission journal and engine 7's book, and the three should be one mechanism rather than three.

**ON DEGRADED INPUT:** exposure-reducing, and inverted relative to every other engine — for a safety engine, *missing information is the alarm*, not a reason to stay quiet.


| Condition                        | Behaviour                                                                                                                                      |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Expected stream not observed     | `never-seen`, alertable. Never `healthy`.                                                                                                      |
| Observation older than the bound | `stale`, alertable.                                                                                                                            |
| Metric source unavailable        | The metric is absent-and-marked, not zero. A zeroed latency metric reads as a healthy platform.                                                |
| Kill-switch state unreadable     | **Treat as active.** The only fail-closed reading of an unreadable safety authority.                                                           |
| Alert sink unavailable           | Buffer durably and degrade the platform; an unalertable platform is an unmonitored one.                                                        |
| Alert volume beyond rate limit   | Aggregate with counts — never drop silently. Rate limiting that discards is the anti-pattern this engine exists to prevent, applied to itself. |


**ON EXCEPTION:** contained, emitting, and **never fail-open on the safety path**. A raise in metrics or alerting must not take down a tick; a raise in the kill-switch read is treated as active. Engine 11 is the engine most tempted toward broad `try/except` — it is peripheral to trading and nobody wants monitoring to break the platform — and that temptation is exactly how Phase 0 E-2's twenty fail-quiet handlers accumulate.

**SUBSTITUTABILITY:** a replacement must (i) expose the same kill-switch read with the same fail-closed semantics; (ii) emit the same alert taxonomy and health enumeration; (iii) honour kill-switch durability; (iv) be **addable without core edits** — a new monitored assumption attaches by configuration, zero edits under `kernel/`, `bus/`, `core/`, `composition/`, `risk/`, `execution/` (CORE §G.1). **The concrete boundary test, and it is the sharp one:** with engine 11 replaced by a null implementation, the platform must **refuse to trade** — not run unmonitored. Every other engine's substitutability test asks whether the platform still works without it; this one asks whether the platform correctly declines to. An unmonitored platform that keeps trading has a monitoring boundary that is decorative.

**CONFORMANCE TEST:**

1. **Four-way health.** Each of the four states reachable and distinguishable per stream; `never-seen` must never present as `healthy`. Phase 0 checked the ingress case and found it correct — the one queue counts drops, warns, and degrades `DataHealth` via `notify_feed_interrupted`, rated `implemented` and explicitly **not** the silent-drop anti-pattern. This test generalizes that one good instance to every stream.
2. **Kill-switch fail-closed.** Unreadable, uninitialized, or post-restart-uncleared ⇒ active. Includes the durability assertion.
3. **Assumption-violation coverage.** One monitor per named assumption in CORE §E — latency drift, fill-rate drift, regime break, contract rejection rate, reconciliation divergence — each with a threshold and a test that fires it. This is the test that makes the engine's mandate enumerable, and it is where Phase 1's determinism budget becomes operational: the five neutralizers with no enforcing check (rows 3, 6, 9, 11, 13) are assumptions in exactly this sense.
4. **No-decision test.** Engine 11 emits alerts, health and the kill switch, and nothing else. No sizing, no order, no target.
5. **Alert taxonomy closure.** Closed, versioned enumeration; an unrecognised `alert_name` fails at the boundary. Phase 1 §6.1 makes the parity call that pairs with this: pin the **taxonomy** — `alert_name` and `severity` per stream — not `message`, because "alert content is *supposed* to change when behaviour changes, so pinning it wholesale converts every diagnostic improvement into a parity break."
6. **Immutability.** `Alert.context` and `MetricEvent.tags` are both mutable containers on frozen events today (Phase 0 C-7), and alert context is precisely what an incident review reads after the fact.
7. **Telemetry isolation.** Wall-clock-derived values never reach a decision or a hash. Currently correct and load-bearing: `_finalize_tick` routes always-on timers with `sequence=0` at `src/feelies/kernel/orchestrator.py:2131` "so they cannot shift kernel event IDs," while conditional timers publish with `self._seq.next()` at `:2147`, and the conditional set is a function of deterministic control flow (Phase 0 D0.4). This test keeps that true.
8. **Metric unit declaration.** Every metric carries a unit (CORE §C.8).

**GAP vs CURRENT:** engine 11's package is rated `Clear` (Phase 0 D0.2) and its most safety-critical behaviour is present and correct — the kill switch is read directly on the tick path and returns early (hop 4) — but the *event* that announces it is inert: `KillSwitchActivation` has no consumer in any mode despite a docstring at `src/feelies/core/events.py:416` saying it is "published on the bus so all layers can react," and it is one of four never-subscribed types alongside `RiskVerdict`, `StateTransition` and `SymbolHalted` (Phase 0 C-4), while engine 11's entire output stream sits outside the parity manifest (Phase 1 §6.1).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean.

**Overlap 1 — engine 11's observability is the platform's most-published, least-subscribed surface.** Thirteen `_emit_*_alert` / `_publish_alert` methods in the kernel (Phase 0 D0.2), five `Alert` publishers and five `MetricEvent` publishers across bootstrap, kernel, risk and monitoring (Phase 0 D0.3) — and of engine 11's four event types, `Alert` and `MetricEvent` have exactly one static subscriber each, both of them the orchestrator (`:563`, `:559`), while `KillSwitchActivation` has none. The safety behaviour is real because it is read directly; the *observability* contract is largely unwired. Flagged; the read-surface design is Phase 3's.

**Overlap 2 — four of the platform's engine-11 emissions are inert, and two of them describe consumers that do not exist.** `KillSwitchActivation` ("published on the bus so all layers can react") and `SymbolHalted` ("lets post-trade forensics reconstruct which fills were suppressed", `src/feelies/core/events.py:123`) are both code-vs-docstring disagreements, `VERIFIED` in code's favour (Phase 0 C-4). Recorded here rather than on engine 1's sheet because both are cases of a *safety or forensic* consumer being described and not built, which is one pattern rather than two.

**Overlap 3 — health is produced in three places.** Engine 1 produces `DataHealth` at ingress, the kernel evaluates `_data_health_blocks_trading:5263`, and engine 11 owns platform health. The engine-1 sheet already assigned the *gate* to the gate ladder rather than to engine 1; the residual question is whether engine 11 aggregates engine 1's health or maintains a parallel view. **The call: engine 11 aggregates and never recomputes** — the same rule applied to engine 7's numbers, applied to health.

**Overlap 4 — U-1 is engine 11's and stays open.** Whether the four never-subscribed types are consumed by out-of-tree operator tooling (Phase 0 D0.8) determines whether "inert" means unused or means used through an unrecorded path. Either answer is actionable; not knowing is not.

**Model finding: none, and a near-miss worth recording precisely.** Engine 11 holds *observability* (cold, best-effort, must never break trading) and *safety* (the kill switch — hot-read, fail-closed, must break trading). Those have opposite failure directions, and CORE §E puts them in one engine. **They are reconcilable, and the reconciliation is already how the code works:** the kill switch is a single boolean read directly at hop 4, structurally separate from the metrics and alert machinery, so the fail-open discipline of one never touches the fail-closed discipline of the other. The contract must state that separation as a rule — **the safety surface holds no dependency on the observability surface** — rather than leaving it as a property of the current implementation. If a later phase finds the kill switch needs metric state to decide activation, that dependency inverts and this becomes a model finding.

**Assumptions registered:**

- **Whether kill-switch state is durable today.** Phase 1 §4 establishes nothing else is; engine 11 is not measured. Decides whether test 2's durability half is an assertion or a build.
- **Which assumption violations are actually monitored.** CORE §E names five; Phase 0 measured the kill switch as present and read, but no phase enumerates its triggers. Test 3 is the discriminator and this is the largest unmeasured surface on the sheet.
- **Whether health distinguishes four states today.** `DataHealth` exists at ingress with a terminal `CORRUPTED` (`src/feelies/ingestion/data_integrity.py:58`); whether the platform-wide health view has `never-seen` is unestablished.
- **U-1** (above).
- **U-7 is engine 11's operational blind spot.** Actual tick-path latency distribution is unmeasured, and perf tests are per-host gated (Phase 0 D0.8) — so "latency drift" cannot currently be monitored against a baseline that exists. It should be resolved before Phase 4 sets the performance budget, not after.



## ENGINE 12 — Research, Evaluation & Forensics

**ENGINE:** 12. Research, Evaluation & Forensics

**LATENCY CLASS:** `cold` (CORE §D), with no exception — engine 11 gets the kill-switch read, engine 12 gets nothing. The one apparent counter-example is read-only and belongs to engine 7: `src/feelies/portfolio/cross_sectional_tracker.py` is a bus observer feeding forensics (Phase 0 D0.2), which is engine 12 *receiving* on the hot path, not deciding on it.

**OWNS:**

1. **Backtest harnesses** and the runner that composes them.
2. **Replay parity reporting** — the report, not the oracle. See overlap 1.
3. **Hypothesis testing machinery** — CPCV, DSR, forward IC, decouple gates (`research/`, Phase 0 D0.2).
4. **Post-trade attribution** — what each alpha, each mechanism and each cost component actually contributed.
5. **Decay detection** — that an alpha's realized edge is deteriorating, as a measured claim with a stated confidence.
6. **Calibration** — including the estimated-versus-realized cost loop engine 10 feeds.
7. **The signal→order forensic trace** — currently produced inside the kernel (`src/feelies/kernel/signal_order_trace.py`, sink injected at `src/feelies/bootstrap.py:564`) and listed by Phase 0 as unowned by any engine.
8. **The declared interface and cadence** through which its outputs reach engines 5 and 8 (CORE §E).

**MUST NOT OWN:**

- **Live decisions taken directly.** CORE §E. Engine 12 produces evidence and recommendations; engines 5 and 8 act. This is the sheet's central prohibition and the platform currently violates it — see the defect.
- **Lifecycle state writes** (5). The `LIVE → QUARANTINED` transition is engine 5's, on engine 12's evidence.
- **Accounting** (7). Attribution is engine 12's *analysis*; the fill→strategy assignment and the P&L are engine 7's numbers, read not recomputed.
- **The parity oracle itself.** The manifest, its closure tests and its fingerprint are the determinism substrate — kernel-class, per Phase 1. Engine 12 reports against it; it does not define it.
- **Cost *modelling*** (10). Engine 12 calibrates a model it does not own.
- **Alpha-shaped code paths.** No branch on `alpha_id`, archetype or horizon (CORE §C.7) — and this engine is the most tempting place to violate it, because per-alpha analysis legitimately *keys* on identity. Keying is permitted; branching is not.
- **Anything on the tick path.**

**CONSUMES:**


| Input                                                                          | Staleness / validity tolerance                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The replayable event log                                                       | The primary input, and the constraint that shapes the engine: `src/feelies/storage/memory_event_log.py:7` states there is "No persistence — all events are lost on process exit," so today engine 12 analyses only what is in the current process or in a disk cache. |
| Fills with economics, and realized cost, from engine 10                        | Missing economics ⇒ excluded and counted, never imputed.                                                                                                                                                                                                              |
| Positions, marks, P&L from engine 7                                            | Read-only, as-of. Never recomputed — a second P&L computed for research purposes is CORE §J's recompute-as-redundancy with the most plausible-sounding justification available.                                                                                       |
| Verdicts and escalation from engine 8; alerts and health from engine 11        | For attribution of *non*-trades, which is half of what post-trade analysis is for.                                                                                                                                                                                    |
| The resolved registry and `manifest_hash` from engine 5                        | Provenance for every reported result.                                                                                                                                                                                                                                 |
| Run fingerprint (`config.snapshot().checksum`) and parity manifest fingerprint | Both required on every report — see the emission rule.                                                                                                                                                                                                                |


**EMITS:**


| Contract           | Units, timestamp semantics, provenance                                                                                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Evidence record    | The measured claim, its unit, its sample, its confidence, the method and method version, and **both fingerprints** — the run's and the oracle's. Consumed by engine 5's lifecycle gates. |
| Recommendation     | A named lifecycle or risk action, with the evidence reference that justifies it and an expiry. Advisory by contract: engine 12 emits it, engine 5 or 8 executes it.                      |
| Attribution report | Per alpha, per mechanism, per cost component, reconciling to engine 7's realized P&L exactly.                                                                                            |
| Parity report      | Pass/fail per stream against the manifest, with the manifest fingerprint.                                                                                                                |
| Forensic trace     | Signal→order, **total and dual-path**: every signal reaches an order or a named decline, and the trace is an audit object rather than a success log.                                     |


**The emission rule that makes the rest work:** no engine-12 output is valid without the run fingerprint and the oracle fingerprint it was produced under. Phase 1 §7 records that these are two unlinked artifacts today — `manifest_fingerprint()` covers the oracle, `config.snapshot().checksum` covers the run, "neither references the other, so *which oracle version accepted this run* is not recorded." Engine 12 is the engine that needs both, so it is the engine that should carry the link.

**FORBIDDEN READS:** nothing that would let it decide — no write handle to engine 5's lifecycle state, no risk-limit mutation, no order path. Engine 12 may read everything and write nothing outside its own records. That inversion is the whole security model of a forensics engine: broad read, zero write authority elsewhere.

Enforcement: (a) **write-capability injection** — engine 12 is constructed with read-only views and no mutating handle, which is the only defence that survives a well-intentioned edit; (b) an import-boundary test forbidding `forensics/`, `research/` and `harness/` from importing engine-5 lifecycle writers or engine-8 mutators; (c) the off-tick-path test below; (d) tree-wide alpha-literal check (CORE §I).

**STATE:** analysis windows and accumulators; calibration parameters and versions; decay estimators; the durable evidence record; harness run state.

**Deterministic reset path:** analysis state is per-run and cold-start; **the evidence record is durable and cross-run**, matching engine 5's ledger split and engine 10's journal. Engine 12 holds the platform's only RNG — two sites, both `local random.Random(seed)` in `src/feelies/research/cpcv.py:457`, `:519`, default `seed=0` at `:439`, with no global `random.seed()`, no `numpy.random`, no `secrets` and no `uuid` anywhere in `src/feelies/` (Phase 1 budget row 6). **The seed is therefore part of the evidence record**, not an implementation detail: a CPCV result is not reproducible without it, and the budget rates this `implemented` with **no named check** — nothing prevents a `uuid4()` or an unseeded draw appearing tomorrow.

**ON DEGRADED INPUT:** exposure-reducing in the form that applies to an advisory engine — **the failure direction is toward no recommendation, never toward a permissive one**.


| Condition                                        | Behaviour                                                                                                                                                                                                                                                         |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Insufficient sample                              | No claim. Not a low-confidence claim, not a provisional pass.                                                                                                                                                                                                     |
| Missing fills or unattributable economics        | Excluded, counted, and the exclusion count reported alongside the result.                                                                                                                                                                                         |
| Fingerprint mismatch between runs being compared | Refuse the comparison and say which fingerprint differs.                                                                                                                                                                                                          |
| Parity baseline exempt or data-gated             | Report as unpinned, not as passing. `_BASELINE_TRADE_PARITY_HASH` is exempt because it requires the APP/2026-03-26 disk cache (Phase 1 §6.1) — an exemption is a known hole, and a report that renders it as a pass converts a known hole into a false assurance. |
| Evidence stale beyond engine 5's bound           | Emit as expired. Engine 5's rule is that expired evidence cannot justify continued LIVE status; engine 12's obligation is to make expiry visible rather than let a stale record read as current.                                                                  |


**ON EXCEPTION:** contained and emitting — a failed analysis must never degrade the platform, and equally must never resolve to a pass. The failure branch is: no evidence record, no recommendation, and an alert through engine 11. This is the one engine where "contained" is unambiguously right, because it has no live authority to contain.

**SUBSTITUTABILITY:** a replacement must (i) emit the same evidence and recommendation contracts with both fingerprints; (ii) reconcile attribution exactly to engine 7; (iii) hold no write handle; (iv) be **removable** — with engine 12 absent, the platform trades identically and engine 5's lifecycle simply receives no new evidence, which by engine 5's own degraded rule moves alphas toward quarantine rather than leaving them LIVE by inertia. **The concrete boundary test:** engine 12's removal must change no live behaviour on the tick path and must not silently extend any alpha's LIVE status. That second half is what distinguishes a genuinely advisory engine from one the platform has quietly come to depend on.

**CONFORMANCE TEST:**

1. **Off-tick-path proof.** Instrument engine-12 surfaces; run a full tick sequence; assert zero reads and zero writes from any hot-path engine. Same shape as engine 5's test 1, and the two should share a harness.
2. **No-write-authority test.** Static and dynamic: engine 12 holds no mutating handle to engine 5 or engine 8. **Fails today** — see the defect.
3. **Attribution reconciliation.** Σ attributed P&L = engine 7's realized P&L, exactly, in `Decimal`. Engine 12's version of engine 7's conservation identities, and the test that proves engine 12 is reading rather than recomputing.
4. **Fingerprint totality.** No report emitted without both fingerprints; a comparison across mismatched fingerprints refuses.
5. **RNG discipline.** Every stochastic method takes an explicit seed recorded in the evidence record; an unseeded draw fails. Retires the "no named check" on Phase 1 budget row 6.
6. **Closed loop on cadence** (CORE §G.9). At least one governance or risk decision driven by an engine-12 output on a declared cadence, with the evidence reference on the transition. Phase 0 found the loop exists — it just closes through a write rather than a recommendation.
7. **Trace totality.** Every signal reaches an order or a named decline; a trace that records only successes fails. Pairs with engine 9's decline-totality test, which is what makes the trace's negative half populatable.
8. **Exemption honesty.** Every exempt or data-gated baseline reports as unpinned.

**GAP vs CURRENT:** engine 12's machinery is real and correctly cold — CPCV, DSR, forward IC and decouple gates in `research/`, harnesses in `harness/`, attribution and decay in `forensics/`, all rated `Clear` or `Mixed` on one specific ground (Phase 0 D0.2) — but its outputs carry neither fingerprint (Phase 1 §7), its one closed loop is implemented as a cross-engine state write (`src/feelies/forensics/cost_circuit_breaker.py:159`), and its forensic trace is produced inside the kernel and owned by no engine (Phase 0 D0.2).

---



### Standing checks for this sheet

**Alpha-naming (CORE §I).** Clean at the contract level. One note the operator should have: engine 12 is the engine whose *fixtures* legitimately reference specific alphas, and Phase 0 D0.6 records the consequence — the end-to-end trade baseline is "one symbol, one day, and data-gated" (P-3). That is a fixture limitation, not a design rule naming an alpha, and CORE §I's own instruction is to treat the current configuration as a test-flight payload rather than a specification.

**Defect recorded (CORE §I / CORE §E): the closed loop is implemented as a cross-engine write.** `src/feelies/forensics/cost_circuit_breaker.py:159` drives `LIVE → QUARANTINED` — an engine-5 state write performed from engine-12 code. Phase 0 D0.2 records it exactly this way: it is CORE §G.9's closed loop, and the write direction crosses the engine boundary. **The resolution, as promised on engine 5's sheet: engine 12 emits evidence plus a recommendation; engine 5 performs the transition.** Same outcome, one writer, and it survives a second forensic input arriving later — which the current shape does not, because two forensic writers racing on one lifecycle state have no arbitration. The behaviour is *correct* today and the mechanism is wrong; that is worth stating plainly, because the migration step is a re-routing, not a fix to a broken circuit breaker.

**Overlap 1 — the parity oracle is not engine 12's.** The manifest at `tests/determinism/parity_manifest.py:133`, its two closure tests at `tests/determinism/test_parity_manifest.py:261` and `:288`, and `manifest_fingerprint()` at `:234` are the determinism substrate, and Phase 1 rated this "the one item that substantially matches target" and "the only responsibility in Phase 0 that is enumerable from a single source." **The call: the oracle is kernel-class, engine 12 reports against it.** Recorded because the natural drift is for a research engine to absorb the oracle it reports on, and an oracle owned by the engine it grades is not an oracle.

**Overlap 2 — the forensic trace is produced in the kernel and owned by nobody.** `src/feelies/kernel/signal_order_trace.py`, sink injected at `src/feelies/bootstrap.py:564`; Phase 0 lists it under "Unowned by any engine." This sheet claims it for engine 12, with the placement question — trace *collection* is necessarily on the hot path, trace *assembly and analysis* is not — resolved the same way as engine 11's metrics: emission on the hot path, ownership of the contract off it. It is also the engine-12 surface that most needs test 7, since Phase 0 D0.4 records that hop 28's arbitration discards forecasts and traces them, so the trace already carries the platform's only record of what did *not* happen.

**Overlap 3 —** `src/feelies/portfolio/cross_sectional_tracker.py` **is permitted.** Settled on engine 7's sheet; restated once from this side so it is not re-opened. Read-only bus observer, engine 7's package, engine 12's consumer.

**Overlap 4 — the harness reaches through a private attribute.** `src/feelies/harness/backtest_runner.py:246` subscribes dynamically via `orchestrator._bus`, one of the platform's ten cross-object private accesses (Phase 0 C-5, C-9), and it is how `OrderAck` and `PositionUpdate` gain their backtest-only consumers. So engine 12's observation of engine 10's output depends on an encapsulation break. **The call: engine 12 needs a declared observation interface**, not privileged access — and the same interface serves engine 11's unwired alert and metric consumers, so it should be designed once in Phase 3 rather than twice.

**Model finding: none, and the last near-miss.** Engine 12 carries *research* (offline, exploratory, seeded, may fail freely) and *live forensics* (continuous, in-session, feeding governance on a cadence). They differ in rhythm and in consequence — a failed CPCV run costs nothing, a missed decay signal keeps a dead alpha live. They are reconcilable because they share one evidence contract and one write-authority rule, which is the property that actually matters: both produce records, neither acts. Recorded because it is the second-most plausible wrong split in the model after engine 10's simulation/routing near-miss.

**Assumptions registered:**

- **Whether the evidence record is durable.** Engine 5's ledger is append-only (Phase 0 D0.2); whether engine 12's own evidence is durably backed is unmeasured, and it decides whether test 4's cross-run comparisons are possible at all.
- **Whether attribution reconciles exactly today.** Test 3 is unmeasured; engine 7's overlap 2 — whether `_record_fill_attribution:4057` and `src/feelies/alpha/fill_attribution.py` are one path or two — is the same question from the other side, and if they are two, engine 12 is reconciling against a number computed twice.
- **U-8 is engine 12's and Phase 5 needs it.** Per-stream parity coverage is a union-of-names upper bound; Phase 1 §6 states it "remains open and should be resolved before Phase 5," and Phase 0 D-12 demonstrated the inflation directly.
- **U-5 stays open** — no multi-symbol whole-run baseline was found, so engine 12's end-to-end evidence covers one symbol on one day.
- **Whether decay detection exists as a measured claim or as a threshold.** CORE §E names decay detection; nothing in Phase 0 or Phase 1 establishes its method, and engine 5's promotion gates depend on it.

---



## RESPONSIBILITY: F.1 — Universe definition

**RESPONSIBILITY:** 1. Universe definition — what symbols are in play, as of when, who publishes mid-session changes. Engines 2, 4, 6, 8 must see the same universe at the same event time.

**OWNER ENGINE:** 5 — Alpha Governance.

**WHY THIS ENGINE:**

The consumer list decides it. Engines 2, 4, 6 and 8 span the tick-critical path from the first estimator to the last veto, so the producer must be upstream of engine 2 and off the tick path — otherwise the universe becomes a per-event computation and four engines can observe four answers within one tick. That eliminates every hot engine, including the two that currently hold pieces of it.

Engine 6 looks like the natural owner and is the wrong one for a specific reason: it is the *last* of the four consumers to run (Phase 0 D0.4 hops 24–25, after engine 2 at hop 13 and engine 4 at hop 23), so a universe owned there would be defined after two of its own consumers had already used it. That is a cycle, not a layering preference. `UniverseSynchronizer` (`src/feelies/composition/synchronizer.py:30`) is correctly named for what it does — Phase 0 describes it as "a barrier that *waits on* a universe it is handed, not one that defines it."

Engine 1 is the other plausible candidate and is wrong in the other direction: a symbol appearing in the feed is a *consequence* of the universe, not its definition. Engine 1's sheet already declined it on those grounds.

That leaves engine 5, and three properties make it the right home rather than the residual one. It is cold, so a composition-time fact cannot decay into a per-event one. It already reads both inputs the universe is currently assembled from — the config symbol list and the per-alpha `universe` disclosure validated at `src/feelies/alpha/layer_validator.py:326`. And it already publishes exactly this shape of artifact: a resolved, frozen set handed to the composition root and consumed once, which is what engine 5's sheet specified for the alpha registry. The universe is a second field on that artifact, not a second mechanism.

**On "who publishes mid-session changes" — the premise does not survive the analysis, and the alternative is stated.** Under CORE §C.10 governance is resolved at composition and never re-evaluated per event; the universe is governance. **The call: universe membership is resolved at composition and is immutable for the session.** What looks like a mid-session universe change is always one of three other facts, each with a different owner:


| Apparent change                       | What it actually is                | Owner                             |
| ------------------------------------- | ---------------------------------- | --------------------------------- |
| Symbol stops being tradeable          | Halt, SSR, session state           | §F.3 (pending)                    |
| Symbol becomes a different instrument | Split, ticker change, symbol reuse | §F.2 (next)                       |
| Symbol stops producing data           | Feed health                        | Engine 1 → engine 11 `never-seen` |


**Membership and tradability are different facts and must not share a channel.** A halted symbol is *in* the universe and *not* tradeable; collapsing the two makes the barrier's denominator move whenever a symbol halts, which silently changes what completeness means mid-session.

**The trade-off, stated plainly:** a genuine intraday universe expansion requires a declared session boundary and a re-composition, producing a new run fingerprint. For a seconds-to-minutes intraday platform that is a real constraint, and the honest defence of it is that the alternative — a mutable universe on a synchronous bus with no global event ordinal (Phase 1 §2) — cannot give four engines one answer at one event time without a coordination mechanism the platform does not have.

**CONTRACT PUBLISHED:**

A `UniverseSnapshot`, resolved at composition, frozen, consumed once:

- **Members as an ordered tuple**, sorted by symbol — not a set. Phase 1 measured set iteration as a live nondeterminism source with **no named check** (budget row 3, five sites, two of them in `src/feelies/composition/synchronizer.py:80` and `:83`), and budget row 2a rates the seed-dependent mapping out of `src/feelies/portfolio/strategy_position_store.py:148` an **open defect** because the neutralizer sits at three consumers rather than at the source. Publishing the universe as a set would create a fourth carrier of the same defect.
- **As-of semantics:** session id and the event time the snapshot takes effect, which is the session's opening boundary.
- `universe_hash` over the ordered members, and a `universe_version`.
- **Provenance per member:** config-declared, alpha-disclosed, or both — so a mismatch is diagnosable from the artifact rather than from four grep results.
- **Per-alpha resolved universe**, keyed by opaque `strategy_id`. Consumers outside the alpha layer read only the platform universe. Keying on an opaque id is permitted; branching on it is not (CORE §C.7).
- `in_universe(symbol) → bool`, total. There is no third answer and no "not yet known."

**FAILURE BEHAVIOR:**


| Condition                                                   | Behaviour                                                                                                                                                                                                                           |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config symbol list and alpha `universe` disclosure disagree | **Fail the load**, naming the symbols and the alphas. This directly reverses the measured consequence — Phase 0 D0.7 F.1 records that today "a config/alpha-disclosure mismatch degrades the barrier rather than failing the load." |
| Universe empty or unresolvable                              | Refuse to compose. The platform does not trade an undetermined universe.                                                                                                                                                            |
| Event arrives for an out-of-universe symbol                 | Rejected at the receiving boundary, loudly, with provenance (CORE §G.3); counted and emitted. This is one of the input classes CORE §I fixture 3 exists to exercise.                                                                |
| Member present with no data                                 | Engine 11 `never-seen`, alertable. Engine 6's completeness reports it as a **missing member**, never by shrinking the denominator — otherwise a dead feed reads as a complete cross-section.                                        |
| `universe_hash` disagrees with the run fingerprint          | Refuse to start.                                                                                                                                                                                                                    |
| Any attempt to mutate the snapshot post-composition         | Raise.                                                                                                                                                                                                                              |


Every branch is exposure-reducing in the same direction: an undetermined universe produces no trading rather than trading over the subset that happened to resolve.

**DETERMINISM NOTE:**

1. **The resolved universe must enter the run fingerprint, and half of it currently cannot.** Phase 1 §7 measured `alpha_specs` reduced to `sorted(spec.name for spec in value)` at `src/feelies/core/platform_config.py:683` — names only — with no `manifest_hash` / `spec_hash` / `yaml_hash` / `sha256` anywhere under `src/feelies/alpha/`. So editing an alpha's declared `universe` moves no checksum today. `universe_hash` closes this for the universe specifically; the general case is engine 4's manifest-provenance test and remains the same root cause.
2. **One ordering rule, stated once:** members sorted by symbol at publication. Downstream consumers inherit a deterministic iteration order rather than each applying `sorted()` — which is the structural fix budget row 2a asks for, applied prospectively instead of retroactively.
3. **Replay resolves the universe from the log's own recorded fingerprint, never from today's config.** Under the pinned-code-per-log rule Phase 1 §8 selected for §F.7, the universe is part of what a log pins; replaying a vN log against a changed universe must refuse, not silently re-scope.
4. **The residual, flagged not resolved:** a universe is a set of symbol *identities*, and identity is unowned (§F.2). `universe_hash` is therefore stable only to the extent that `symbol` means the same instrument across the replay boundary — and Phase 0 F.2 found no symbol-identity module, no ticker-change map, and bare `str` symbols on every event. F.1 is not sound without F.2, which is the next turn.

---



### Standing checks

**Amendment to my own engine-5 sheet, recorded rather than quietly applied.** That sheet's MUST NOT OWN listed "Universe definition (§F.1)," on the narrow ground that validating a disclosure does not confer ownership of the fact. That ground still holds — the argument for ownership above is not "engine 5 validates the disclosure," it is the ordering and composition-time argument. But the line as written now contradicts this resolution and needs a one-line revision when the phase output is assembled: **engine 5 owns universe *definition* and publishes** `UniverseSnapshot`**; it does not own *tradability*.** Recorded so the Phase 2 document is internally consistent (CORE §H's amendment discipline, applied to my own output).

**Alternatives set aside, with reasons:** engine 6 (cycle — defines a fact two of its own upstream consumers need); engine 1 (feed presence is downstream of membership, and engine 1 is hot); a dedicated universe engine (CORE §A forbids inventing a 13th).

**Alpha-naming (CORE §I).** Clean. Note the asymmetry this resolution depends on: engine 5 may read alpha manifests because it *is* the governance layer, and the artifact it publishes is alpha-agnostic in shape — an ordered symbol tuple plus a mapping keyed by opaque id.

**Model finding: none.** The responsibility fits engine 5 on a positive argument, not by elimination.

**One consumer obligation created, for Phase 3.** Engine 6's completeness threshold must be evaluated against `UniverseSnapshot` members and must treat a missing member as missing rather than absent. That is a flow-and-gating item, and it is the specific place where F.1's resolution either takes effect or does not.

## RESPONSIBILITY: F.2 — Symbol identity over time

**RESPONSIBILITY:** 2. Symbol identity over time — splits, ticker changes, symbol reuse, corporate actions. Both an accounting-truth problem and a determinism problem: a replayed historical log must resolve identity the way it resolved *then*.

**OWNER ENGINE:** 5 — Alpha Governance.

**WHY THIS ENGINE:**

The two halves of the problem statement pull toward different engines, and reading them carefully is what decides it.

The **accounting-truth** half argues for engine 7. It is where an unadjusted split becomes a wrong number rather than a wrong label — engine 7's sheet already registered this as its largest silent-wrong-number exposure. But engine 7 is a *consumer* of identity, not a producer: it needs to know that today's `APP` is the same instrument as yesterday's, and it cannot derive that from lots, marks or fills. Owning identity there would also make it hot, and identity resolution on the tick path is a lookup that must never miss.

The **determinism** half is decisive and points elsewhere. "A replayed historical log must resolve identity the way it resolved *then*" means identity is a **pinned input to a run**, not a live state. That is the same shape as the universe, the alpha registry and the schema version: resolved before the first event, immutable for the session, entering the run fingerprint. Every fact with that shape belongs to the cold engine that publishes composition-time artifacts.

Engine 1 is the tempting alternative — the symbol arrives on the wire, so the translator seems like the place to canonicalize it. It is wrong for the same reason it was wrong for F.1: what the feed calls a symbol is a *vendor's* naming as of a moment, and resolving it against corporate-action history is a reference-data judgment, not a wire translation. Engine 1's sheet already declined it and consumes an identity map it does not own.

Engine 12 owns calibration and reference-style analysis and is the third candidate. It is wrong on write-authority grounds: engine 12's sheet fixed the rule that it emits records and holds no handle that changes what the platform does. An identity map changes what every engine trades and books.

So engine 5, and on a positive argument: **identity resolution is governance of what an instrument *is*, exactly as the universe is governance of which instruments are in play, and they are the same artifact resolved at the same moment.** F.1's `UniverseSnapshot` is a tuple of symbols; without F.2 those symbols are strings that may mean different instruments on different days. Splitting the two owners would give the platform a membership list and an identity map resolvable to different as-of dates, which is the exact failure the pairing exists to prevent.

**The scope line, drawn explicitly.** Engine 5 owns identity **resolution and the adjustment factors**; it does not own **applying** them. Engine 7 applies price and quantity adjustments to lots and marks; engine 12 applies them to historical series. One producer, several appliers, and the appliers read rather than derive (CORE §C.6).

**CONTRACT PUBLISHED:**

An `IdentityMap`, resolved at composition alongside `UniverseSnapshot`, frozen, consumed once:

- **A stable** `instrument_id` distinct from the ticker. This is the substance of the resolution: today "symbols are bare `str` throughout" (Phase 0 F.2, `src/feelies/core/events.py`, every event), which means the platform has no name for the thing that persists across a ticker change. Every engine keys on `instrument_id`; the ticker becomes a display and wire-matching attribute.
- `resolve(ticker, as_of_event_time) → instrument_id`, total. No third answer, no "probably."
- **Adjustment factors** per (instrument, effective event time): price factor and quantity factor, `Decimal`, with the action type.
- **Effective times in event time**, at the corporate action's effective instant — not the date it was announced and not the date the map was built.
- `identity_hash` over the resolved map, and the **as-of date the map was resolved to**. Both enter the run fingerprint.
- **Reuse guard:** a ticker that has referred to more than one instrument resolves only with an `as_of` inside a declared validity window; outside it, no answer.

**FAILURE BEHAVIOR:**


| Condition                                                      | Behaviour                                                                                                                                                                                                                                |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticker does not resolve at the run's as-of time                | **Refuse to compose.** An unresolvable member of the universe is not a symbol to skip; it is a configuration that cannot be trusted to mean what it says.                                                                                |
| Ambiguous resolution (reuse, overlapping windows)              | Refuse, naming both candidates. Never pick the more recent.                                                                                                                                                                              |
| Corporate action effective inside the session                  | Refuse to compose for that instrument. Applying a split mid-session would change the meaning of every mark, lot and fill already booked, and the platform has no mechanism to re-base them atomically.                                   |
| Identity source unavailable or stale beyond its declared bound | Refuse. Trading on an unknown identity is the one degradation with no exposure-reducing version — a stale map does not make positions smaller, it makes them *wrong*, and a wrong position can be arbitrarily large in either direction. |
| Log's `identity_hash` disagrees with the loaded map on replay  | Refuse and name both, per the pinned-code-per-log rule.                                                                                                                                                                                  |
| Adjustment factor missing for a known action                   | Refuse. Not 1.0 — a defaulted factor is a silent misvaluation.                                                                                                                                                                           |


Every branch is refusal, and that is the finding as much as the design: **F.2 has no graceful degradation.** Every other §F item has a reduced-exposure middle path; this one does not, because identity is not a quantity that can be scaled toward zero.

**DETERMINISM NOTE:** *(mandatory for F.2 per P2)*

1. **The map is pinned to a log, not to today.** A replayed log resolves identity through the `identity_hash` it recorded, never through the current map. Under Phase 1 §8's pinned-code-per-log rule — chosen precisely because upgrade-on-read "silently changes what a historical log replays to" — an identity map that resolved differently when the log was written is a version mismatch and must refuse, naming both hashes. This is the mechanism that satisfies the problem statement's "the way it resolved *then*."
2. `identity_hash` **enters the run fingerprint.** Without it, two runs over the same log under different corporate-action histories produce different marks, positions and P&L with identical checksums. Phase 1 §7 already names alpha-manifest content as "the single largest hole in run provenance"; identity is the same hole for a different fact, and both close through the same fingerprint.
3. **The map is ordered and content-addressed** — resolved entries in a sorted, deterministic structure, hashed over that ordering. Same rule as F.1's ordered member tuple, and the same reason: Phase 1 budget rows 2a and 3 leave set-and-dict ordering as a live nondeterminism source with no enforcing check.
4. **Resolution is a pure function of (ticker, as_of) against a frozen map** — no clock read, no network call, no lazy fetch. A lookup that can fall back to a live source is a lookup that can differ between two replays of one log.
5. **Determinism is the *whole* of what this resolution buys, and it must not be oversold.** Pinning identity makes replay reproducible; it does not make a historical log *correct* if the map was wrong when the log was written. Phase 0 states the current position exactly: "On a split or ticker change, cached event logs and live data diverge silently; nothing in the platform can detect it." An `identity_hash` makes that divergence *detectable*; correcting a historical log remains a deliberate, recorded migration producing a new log with a new fingerprint — never an implicit re-read.

---



### Standing checks

**Second amendment to the engine-5 sheet, recorded not applied.** That sheet's MUST NOT OWN did not list F.2, so no contradiction arises — but its OWNS list needs `IdentityMap` added alongside `UniverseSnapshot` when the phase output is assembled, and its CONSUMES table needs the identity source. Recorded under the same discipline as F.1's amendment.

**A boundary note on** `storage/reference/`**.** Phase 0 D0.2 places corporate actions there, in the `storage/` package, under "Unowned by any engine" — "consumed by engines 6, 7, 10 and by `bootstrap`; owned by none." This resolution does not move the *data*; it assigns the *responsibility*. Engine 5 resolves and publishes; the reference store remains a data source it reads. Where the files live is Phase 3's placement question, and it is the same shape as the risk-model provenance finding raised on engine 6's sheet — reference data with consumers and no owner, of which corporate actions are the second instance.

**Alternatives set aside, with reasons:** engine 7 (consumer of identity, cannot derive it, and would make resolution hot); engine 1 (vendor naming is not instrument identity, and engine 1 is hot); engine 12 (holds no write authority by its own sheet's rule); a dedicated reference-data engine (CORE §A forbids a 13th).

**Alpha-naming (CORE §I).** Clean.

**Model finding: none.** F.1 and F.2 are one artifact resolved at one moment by one engine, which is a strong fit rather than a forced one.

**Consumer obligations created, for Phase 3:**

- Every event's `symbol` field becomes `instrument_id` plus a display ticker. This touches all 21 event types (Phase 0 C-1's closure) and is therefore a **schema change** — which lands it squarely on §F.7's mechanism, and on Phase 1 §8's observation that adding a field to any event breaks nothing while bringing it into the hashed set re-pins baselines across the board. Two steps, two blast radii.
- Engine 7 applies adjustment factors to lots and marks at the declared effective time; engine 12 applies them to historical series. Neither derives them.

**Assumption registered.** Whether any corporate-action data exists in `storage/reference/` in a usable form is not established — Phase 0 names the sub-package but also states flatly that there is "no split or dividend adjustment anywhere in `src/feelies/`," so the data may be present with no consumer, or the sub-package may be a name describing an abandoned intent (CORE §J's last anti-pattern). One read of `storage/reference/` settles it, and it decides whether F.2 is a wiring task or a build.

## RESPONSIBILITY: F.3 — Session and halt state

**RESPONSIBILITY:** 3. Session and halt state — pre-open, open, auction, halt, resume, close, after-hours. Straddles 1 (observed), 3 (a regime), 10 (a constraint). Pick the producer.

**OWNER ENGINE:** 1 — Market Data.

**WHY THIS ENGINE:**

CORE §F names three candidates and the words it uses for each already do most of the work: *observed*, *a regime*, *a constraint*. Only one of those is a production verb. A regime is an interpretation of an observation; a constraint is an application of one. Neither can exist before the fact is produced, so the producer is engine 1 and the other two are consumers.

The two rejections are worth making on their merits rather than on that reading alone.

**Engine 3 is wrong, and this is the sharper of the two.** Halt and session state are *venue-published facts* — the exchange declares them, they are not inferred. Engine 3's contract is online classification with a confidence and an `unknown` state, and its degradation direction is toward `unknown` with hazard rising. Routing a known, published, discrete fact through a classifier that is entitled to say "unknown" converts certainty into probability for no gain. It would also give engine 3 a second input class — raw venue status alongside engine-2 features — which its own sheet's FORBIDDEN READS prohibits precisely to keep estimate → classify acyclic. Engine 3 may legitimately *consume* session state as a conditioning variable; that is a different thing from producing it.

**Engine 10 is wrong for the reason CORE §E states in one word: "Mechanics."** Engine 10 owns session and regulatory constraints *as mechanics* — auction eligibility, MOC cutoffs, venue hours — which is applying the fact at the point of submission. Making it the producer would mean engines 2, 3, 8 and 9 read session state from the router, i.e. the last engine in the chain publishing a fact the first engine needs. That is the same cycle argument that disqualified engine 6 from F.1, and it fails the same way.

**The positive case for engine 1** is that it is already the engine that translates wire to canonical, and halt and session indicators arrive on the same wire as quotes and trades. Phase 0 rates this the one §F item with a clean owner and records the current split: `src/feelies/execution/trading_session.py` owns session/RTH state, and halts are owned jointly by `ingestion` (detection → `DataHealth`) and `kernel` (`_halted_symbols`, `SymbolHalted` at `src/feelies/kernel/orchestrator.py:5074`). Engine 1's own sheet already claimed the *observation* and explicitly deferred the authoritative state to this turn. **This resolution grants it.**

**The distinction that makes it work, and it is the same one F.1 turned on.** Engine 1 owns the **state**; it does not own the **consequence**. A halted symbol is in the universe, has a state of `HALTED`, and is not tradeable — but *not tradeable* is a gate outcome owned by the gate ladder, not a property of the market-data fact. Engine 1's sheet already refused the trading-blocked decision (`_data_health_blocks_trading` at `src/feelies/kernel/orchestrator.py:5263`), and refusing it is what keeps this resolution consistent with "no interpretation of what a quote means."

**SSR travels with halt, and it is worth saying why:** it is likewise venue-published, likewise binary per symbol, likewise consumed as a constraint by engine 9 at admission. Splitting it from halt would create two producers for one class of fact.

**CONTRACT PUBLISHED:**

A `SessionState` stream, on engine 1's normal emission discipline — **change plus declared heartbeat**, the same rule engine 3's sheet adopted, so a consumer can distinguish *unchanged* from *not running* without reading engine 1's internals:

- **Market-level phase** from a closed, versioned enumeration: `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `POST_CLOSE`, `AFTER_HOURS`, `UNKNOWN`.
- **Per-instrument status**: `TRADING`, `HALTED`, `PAUSED`, `RESUMED`, plus the venue's halt reason code, keyed by `instrument_id` per F.2.
- **SSR status** per instrument, with its effective and expiry event times.
- **Timestamps in event time**, at the venue's declared effective instant — not the receipt time and not a boundary computed from a calendar.
- **Provenance and quality flags** on the same terms as `NBBOQuote`: feed, venue, `normalizer_version`, `schema_version`, and whether the value is observed, inferred from a calendar, or unknown.
- **Staleness metadata**: the as-of time of the last observation and the bound beyond which the state is stale.

**The one hard rule on this contract: observed and calendar-derived states must be distinguishable on the payload.** A calendar says the market opens at 09:30; the venue says whether it did. Collapsing them is how a platform trades through an unopened session believing it is `CONTINUOUS`.

**FAILURE BEHAVIOR:**


| Condition                                                       | Behaviour                                                                                                                                                                                     |
| --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Halt indicator absent or unparseable                            | `UNKNOWN` for that instrument, emitted. **Consumers treat** `UNKNOWN` **as** `HALTED` — the only fail-closed reading, and the same shape as engine 11's unreadable-kill-switch rule.          |
| Session phase undetermined                                      | `UNKNOWN`, emitted. Engine 9 declines at admission; engine 10 does not submit.                                                                                                                |
| Observation stale beyond bound                                  | Flagged stale, retained, emitted. Never silently aged into a fresh-looking value.                                                                                                             |
| Resume without a preceding halt, or a halt while already halted | Emit the anomaly; adopt the more restrictive state.                                                                                                                                           |
| Calendar and venue disagree                                     | Venue wins; emit the divergence. A calendar is a prediction and the venue is the fact.                                                                                                        |
| Halt effective mid-tick                                         | The state applies from its declared effective event time, and every gate on that tick evaluates against one snapshot. Partial application within a tick is a causality violation (CORE §C.2). |


Every branch reduces exposure, and the direction is uniform: uncertainty about whether a symbol may trade resolves to *may not*.

**DETERMINISM NOTE:** *(not mandatory for F.3 — P2 requires it for F.2 and F.7 — but three properties here are determinism-load-bearing and belong in the record.)*

1. `SessionState` **enters the replayable event log and the total order.** It is a market-data emission and inherits engine 1's `event_merge_sort_key`, which means `_TYPE_RANK` (`src/feelies/storage/event_resequence.py:30`) grows from two entries to three. That is a small change with a real consequence: session transitions become orderable against quotes and trades, which today they are not — Phase 1 §2 measured the total order as covering **2 of 21** types.
2. **The tie-break rank must be declared, not defaulted.** A halt effective at the same nanosecond as a quote must resolve one way, always. **The call: session state ranks *before* quotes and trades at equal timestamp** — the market's permission to trade precedes the price it trades at.
3. **The lazy-bind caveat is a determinism hazard, not a curiosity.** Phase 0 F.3 records that `session_open_ns` "may lazy-bind in BACKTEST only" (`src/feelies/bootstrap.py:1180`), which is a mode-conditional binding of a value that anchors every session boundary — and, per engine 10's sheet, one of the 24 `OperatingMode` branches outside the seam (Phase 0 C-8). Under this resolution the session anchor is observed or explicitly calendar-derived, published on the contract, and identical in shape across modes.
4. **Session boundaries currently depend on unpinned host tzdata.** `src/feelies/core/session_clock.py:20` uses `ZoneInfo("America/New_York")` with boundaries computed integer-exactly (`:41-44`), which is correct arithmetic over an input nobody records — Phase 1 budget row 13 states a tzdata change "would silently move every horizon grid anchored by `rth_open_ns`." Publishing the anchor as a provenance-carrying observation does not fix tzdata; it makes the dependency visible on the payload instead of implicit in the host.

---



### Standing checks

**Amendment to the engine-1 sheet, recorded not applied.** That sheet's OWNS item 8 claimed "venue-published symbol status as observed… observation only," with authoritative state deferred here. It is now granted: **engine 1 owns** `SessionState` **as an authoritative published contract**; the MUST NOT OWN entry "halt/SSR *policy*" stands unchanged. Same amendment discipline as F.1 and F.2.

**This resolution moves an owner, and the move should be seen clearly.** Phase 0 rates F.3 the one §F item with a clean owner — but that owner is `src/feelies/execution/trading_session.py`, i.e. engine 10's package, with halts split between `ingestion` and the kernel. So F.3 is the first §F item where the resolution *relocates* a working responsibility rather than assigning an unowned one. The migration cost is real and belongs in Phase 7; the reason to pay it is that three engines currently hold pieces of one fact and none publishes it as a contract.

**Overlap consequences, for Phase 3:**

- `SymbolHalted` has **no subscriber in any mode**, and its docstring at `src/feelies/core/events.py:123` describes a forensics consumer that does not exist (Phase 0 C-4). Under this resolution it is either subsumed into `SessionState` or retained as a derived notification — one of the two, not both, and the choice is Phase 3's flow work.
- `_update_halt_state:5014`, `_update_ssr_state:5089` and `_emit_symbol_halted:5063` are engine-1 methods in the kernel (Phase 0 D0.2) and move with the responsibility.
- Engine 9's admission gate (hop 32) and engine 10's submission check read one contract instead of `_halted_symbols` plus a session object plus an SSR set.
- Engine 8's buying-power phase flip (hop 16) reads the published phase rather than computing from an anchor.

**Alternatives set aside, with reasons:** engine 3 (interpretation of a published fact; would admit `unknown` where the venue is certain; second input class breaks its own read prohibition); engine 10 (applies the constraint; producing it would invert the chain, last engine publishing a fact the first needs); engine 11 (health is *our* view of the feed, session state is the *venue's* view of the market — different facts, and conflating them would make a healthy feed reporting a halt look like a degraded feed).

**Alpha-naming (CORE §I).** Clean.

**Model finding: none.** The straddle CORE §F identifies is real and resolves cleanly once produce/interpret/apply are separated — which is the same separation F.1 made between membership and tradability, and F.2 made between resolving identity and applying adjustments. Three §F items, one pattern.

**Assumption registered.** Whether the vendor feed publishes halt, resume and SSR indicators with venue-declared effective timestamps — as opposed to the platform inferring them from data absence — is not established by Phase 0 or Phase 1. Phase 0 records that `ingestion` performs halt *detection* feeding `DataHealth` (`src/feelies/ingestion/massive_normalizer.py`, `src/feelies/ingestion/data_integrity.py`), and *detection* is a word that could describe either. It decides whether `SessionState` is a translation or an inference — and if it is an inference, the observed/derived flag on the contract is not a nicety but the whole of its honesty.

## RESPONSIBILITY: F.4 — Broker reconciliation

**RESPONSIBILITY:** 4. Broker reconciliation — cadence, divergence tolerance, action on breach. Must be exposure-reducing and must emit.

**OWNER ENGINE:** 7 — Portfolio Accounting.

**WHY THIS ENGINE:**

This is the one §F item whose owner CORE §E already fixes: engine 7 "owns broker reconciliation and the divergence policy." So the argument here is not *which engine* but *how that survives contact with §E's other clause* — engine 7 must not own "decisions of any kind" — and §F's requirement that the action on breach be exposure-reducing, which is a decision.

**The resolution, made on engine 7's sheet and ratified here: split declaration from action.** Engine 7 owns cadence, tolerance, comparison and the record. Engine 8 owns what the platform does about a breach. Read that way §E is consistent, engine 7 stays decision-free, and the veto stays monotone in one place. The alternative readings both fail:

- Giving engine 8 the whole item makes risk maintain its own view of the broker's book — a second position record, which is exactly what CORE §E forbids it and what CORE §J calls recompute-as-redundancy.
- Giving engine 7 the action creates a second de-risk authority that engine 8 does not coordinate with. Two engines that can both reduce exposure, on different triggers, with no arbitration, is how a platform double-flattens.

**Why engine 10 is not the owner, though it is the obvious candidate for half of it.** Engine 10 talks to the broker and owns the fill and order streams. But reconciliation is a comparison between the *book of record* and the *broker's report*, and only engine 7 holds the first. Engine 10 supplies the broker side; engine 7 performs the comparison. That division also keeps the mode seam clean: in backtest there is no broker, so reconciliation degenerates to a self-consistency check, and the engine that owns the book is the one that can still run it.

**What the ownership actually has to fix.** Phase 0 F.4 rates the current state `Mixed`: order and fill reconciliation is owned (`src/feelies/broker/ib/` plus D0.4 hops 17 and 41), but "no periodic position-of-record comparison against the broker's own position report" exists, so "divergence between `PositionTracker` and the broker is detectable only through the fill stream, so a fill the platform never received leaves the two out of sync indefinitely." That is the gap: the platform reconciles *events* and never reconciles *state*. An event stream can only detect divergences that announce themselves.

**CONTRACT PUBLISHED:**

A `ReconciliationReport`, emitted on **every** check — not only on breach:

- **Per-instrument comparison**: book quantity, broker quantity, signed difference; book average cost and broker average cost where the broker reports one. Keyed by `instrument_id` per F.2.
- **Both as-of times, separately.** The book's as-of event time and the broker's report timestamp are different clocks measuring different things, and a comparison that collapses them cannot distinguish a real divergence from a timing artifact.
- **In-flight set**: orders submitted and unacked, acked and unfilled, at the moment of comparison. A divergence explained by a known in-flight order is a different fact from an unexplained one, and the report must say which.
- **Outcome** from a closed enumeration: `AGREED`, `AGREED_WITHIN_TOLERANCE`, `DIVERGED`, `UNDETERMINED`.
- **Tolerance and cadence** as declared values on the payload, so a reader can tell whether a pass means agreement or a loose bound.
- **Divergence classification**: quantity, cost basis, or unknown-instrument — the broker reporting a position the platform has never held is a different failure from a quantity mismatch, and it is the one that means the platform is not the only thing trading this account.

**Emitting on agreement is the load-bearing choice**, for the reason engine 11's sheet gave in general form: a check that ran and agreed is information, and its absence must not look like agreement. A report emitted only on breach makes "no divergence" and "reconciliation stopped running" indistinguishable, which is precisely the failure mode this item exists to close.

**FAILURE BEHAVIOR:**


| Condition                                            | Behaviour                                                                                                                                                                                                          |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Divergence beyond tolerance                          | `DIVERGED` emitted; engine 7 **stops asserting the book is truth** and marks positions unverified. Engine 8 acts: no new exposure; reductions permitted. Engine 11 alerts.                                         |
| Broker report unavailable or stale beyond bound      | `UNDETERMINED`, emitted. **Treated as breach by engine 8**, matching the rule already set on engines 8 and 11 so the three authorities cannot disagree about what silence means.                                   |
| Broker reports an instrument the book has never held | `DIVERGED`, classified unknown-instrument, alerted at higher severity.                                                                                                                                             |
| Divergence fully explained by in-flight orders       | `AGREED_WITHIN_TOLERANCE`, with the explanation on the payload. Not silently netted away.                                                                                                                          |
| Reconciliation itself raises                         | Contained, `UNDETERMINED` emitted, alert. Never a missing report.                                                                                                                                                  |
| Post-restart, first reconciliation not yet run       | Book unverified; engine 8 refuses new exposure. This is engine 7's durability precondition — "refuse to trade until the book is reconciled against the broker's position report" — reaching its enforcement point. |
| No broker (BACKTEST)                                 | Self-consistency check only: engine 7's conservation identities against the simulated fill stream. Reported as `AGREED` with the broker side declared absent, never as a passing broker reconciliation.            |


Every branch is exposure-reducing in one direction, and the direction is the one that matters here: **an unverified book permits closing and forbids opening.**

**DETERMINISM NOTE:** *(not mandatory for F.4 — P2 requires it for F.2 and F.7 — but reconciliation touches replay in two ways that must be stated.)*

1. **Cadence must be event-time-driven, not wall-clock-driven.** A reconciliation triggered by a wall-clock timer fires at a different point in a replayed stream than in the original run, which changes when the book is marked unverified and therefore which orders engine 8 permits. That makes replay non-deterministic through a monitoring path. **The call: cadence is expressed in event time or in event counts, and the trigger enters the deterministic control flow.** The precedent is exact — Phase 0 D0.4 records that `_finalize_tick` routes always-on timers with `sequence=0` at `src/feelies/kernel/orchestrator.py:2131` specifically "so they cannot shift kernel event IDs," while conditional timers publish with `self._seq.next()` at `:2147` because the conditional set is a function of deterministic control flow. Reconciliation must sit on the second side of that line.
2. **The broker's report is an external input and must enter the event log to be replayable.** Otherwise a live run and its replay diverge at the first `UNDETERMINED`. This is a genuine addition to the log's surface, and it is also the honest place to note the limit: the report is only replayable if it was recorded, and Phase 1 §4 establishes the platform's only event log has "No persistence — all events are lost on process exit" (`src/feelies/storage/memory_event_log.py:7`).

---



### Standing checks

**No amendment needed.** Engine 7's sheet already stated the split as its recorded near-miss and specified the divergence record's fields; this turn ratifies it and adds cadence, the in-flight set and the classification. Engine 8's sheet already lists "the action on accounting divergence" in OWNS and "undetermined ⇒ treated as breach" in CONSUMES. The two sheets and this resolution agree without revision — the first §F item where that is true.

**U-3 remains open and is now blocking.** Whether `broker/ib/` performs any position-of-record reconciliation beyond the fill stream is unresolved (Phase 0 D0.8 U-3), and Phase 0 registered it as an unknown rather than a defect precisely because the IB adapter was not exhaustively read. It decides whether F.4 is a wiring task or a build, and the resolution route Phase 0 named — read `src/feelies/broker/ib/` end to end, check for a positions-request call — is one session's work. **It should close before Phase 5**, because the gap table cannot size this item without it. Compounding the difficulty: `paper_rth`-gated tests never run in CI, so even a present implementation is unexercised.

**A scope note on what reconciliation cannot see.** Reconciling to the broker proves the platform agrees with its counterparty. It does not prove either is right about *what the instrument is* — a mis-resolved split makes book and broker disagree in a way that looks like a quantity divergence and is actually an identity failure (F.2). The classification field exists so the report does not mislabel the second as the first.

**Alternatives set aside, with reasons:** engine 10 (owns the broker connection but not the book; comparison requires both sides); engine 8 (would need a second position record, forbidden by §E and §J); engine 11 (would make a monitoring engine the arbiter of accounting truth, and its sheet's own rule is aggregate-never-recompute); engine 12 (holds no write authority and runs on an analysis cadence, not a session one).

**Alpha-naming (CORE §I).** Clean. Reconciliation is per-instrument and account-level; per-strategy attribution of a divergence is not attempted, and should not be — an unexplained broker position has no strategy.

**Model finding: none.** The §E clause that appeared to conflict — "owns the divergence policy" against "decisions of any kind" — resolves through the same produce/apply separation used in F.1, F.2 and F.3. Four §F items, one pattern, and that consistency is itself evidence the 12-engine model is holding.

**Assumptions registered:**

- **Whether the broker reports positions at all, on request or on schedule.** U-3, above.
- **Whether the broker reports average cost**, which determines whether cost-basis divergence is detectable or only quantity divergence.
- **Whether the platform is the sole trader on the account.** If not, an unknown-instrument divergence is expected rather than alarming, and the tolerance policy is a different design. Nothing in Phase 0 or Phase 1 establishes it, and it is the kind of assumption that is obvious to the operator and invisible to the code.



## RESPONSIBILITY: F.5 — Exception propagation

**RESPONSIBILITY:** 5. Exception propagation — what happens when an engine raises mid-chain on a synchronous bus. A determinism hazard (partial mutation, order-dependent recovery) and an exposure hazard (a swallowed exception is a gate that silently passed).

**OWNER ENGINE:** Kernel — cross-cutting, per CORE §E.

**WHY THIS ENGINE:**

This is the first §F item that does not fit an engine, and forcing it into one would be the error CORE §A warns against. The reasoning, not the assertion:

Exception propagation is a property of the **call chain**, not of any participant in it. When engine 4 raises inside engine 2's handler inside engine 1's publish — which is the literal shape of Phase 0 D0.4 hops 21→25, "each stage publishing from inside the previous stage's handler, all on one synchronous call stack" (Phase 1 §3) — no engine on that stack can define what happens, because each one is a frame in someone else's dispatch. The policy has to be owned by whoever owns the stack.

That is the kernel, and CORE §E already places the qualifying machinery there: "contracts, clocks, deterministic sequencing, the state-machine framework, causal orchestration, composition — and **no trading-domain calculation**." An exception taxonomy and a propagation rule are exactly that: framework with no trading-domain content. This is the same call already made twice in this phase — the ordering *key protocol* is kernel while engine 1 is its client (engine 1's sheet), the cross-sectional *barrier mechanism* is kernel-class while engine 6 owns the completeness policy (engine 6's sheet). Propagation is the third instance of one pattern: mechanism in the kernel, policy at the engine.

**The split that keeps it honest.** The kernel owns the **taxonomy, the propagation rule, and the containment mechanism**. Each engine owns its **classification** — which of its failures is recoverable and which is fatal — and each engine's sheet already states it. The kernel does not decide that an engine-7 write failure is fatal; engine 7 does, and the kernel guarantees that a fatal classification actually halts and that a contained one actually emits.

**Why not engine 11.** It is the tempting alternative, since a swallowed exception is an observability failure. But engine 11 is cold except for the kill-switch read, and propagation is decided synchronously inside the raising frame. Engine 11 is the *recipient* of every exception record; making it the owner would put a cold engine in the control flow of a hot one.

**CONTRACT PUBLISHED:**

Three things, and the first is the one that does not exist today.

**1. A failure taxonomy**, closed and versioned, with the exposure consequence attached to each class rather than left to the site:


| Class                 | Meaning                                                       | Required behaviour                                                                                                           |
| --------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `CONTRACT_VIOLATION`  | A payload failed at a receiving boundary                      | Reject the payload, emit, continue. The rejection is the outcome, not an error.                                              |
| `DEGRADED_INPUT`      | Input present but unusable                                    | The engine's declared degraded branch, emitting. Not an exception path at all — listed so it stops being implemented as one. |
| `ENGINE_FAULT`        | An engine failed at its own job                               | Contained per the engine's declared unit (per sensor, per alpha, per intent), emitting, exposure unchanged or reduced.       |
| `TRUTH_FAULT`         | State that other engines' correctness depends on may be wrong | **Halt.** Engine 7 write paths, engine 10 post-wire-pre-journal, engine 5 composition.                                       |
| `INVARIANT_VIOLATION` | A CORE §C invariant is provably broken                        | Halt, and refuse to resume without an operator action.                                                                       |


**2. A propagation rule.** An exception crosses at most one engine boundary before it is classified. Unclassified escapes are themselves `INVARIANT_VIOLATION` — because an exception that reached the tick-wide handler without a class means some engine's containment did not run.

**3. A failure record**, mandatory on every branch including contained ones: class, raising engine, the event and correlation id being processed, the containment unit, and **what was mutated before the raise**. That last field is the one that makes the record an audit object rather than a log line, and it is the field the current recovery path cannot populate.

**FAILURE BEHAVIOR:**


| Condition                                          | Behaviour                                                                                                                                                                                                                                                                                                                |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Contained fault, no emission                       | **This is the failure this item exists to eliminate.** A containment that does not emit is reclassified as `INVARIANT_VIOLATION` at the next boundary.                                                                                                                                                                   |
| Fault inside the recovery path                     | Halt. Already the current behaviour and correct: `_handle_tick_failure:1474` sets `_pipeline_abort_requested` and the pipeline raises at `src/feelies/kernel/orchestrator.py:1174` if the degraded transition itself fails.                                                                                              |
| Fault after partial mutation                       | Halt if the mutation is truth-bearing (`TRUTH_FAULT`); otherwise emit the mutation set with the record. Phase 0 D0.4 states the current position exactly: "Partial mutation before the raise is not rolled back — marks (hop 9), log append (hop 8) and any submitted order (hop 38) persist."                           |
| `RecursionError` from an unbounded publish cascade | `INVARIANT_VIOLATION`. Phase 1 §3 traced this precisely: no re-entrancy guard, no depth counter, no cycle detection, so a cycle "would recurse until Python's recursion limit and surface as `RecursionError` inside the tick's `try/except Exception`, i.e. as a degraded macro state with no indication of the cause." |
| Exception in a cold engine (5, 11, 12)             | Never propagates to a hot path. Contained, emitted, and for engine 5 at composition, halts the boot.                                                                                                                                                                                                                     |


**DETERMINISM NOTE:** *(not mandatory for F.5, but the problem statement names determinism first, and one property here is load-bearing.)*

**Recovery must be a deterministic function of the failure, not of the arrival path.** The hazard §F names — order-dependent recovery — is live: 16 of 32 subscribed handlers publish from inside their own dispatch (Phase 1 §3), so an engine can raise at different stack depths for the same logical fault depending on which subscriber ran first, and subscription order is itself an unpinned determinism input guarded only by six prose comments in `build_platform`. Two runs of the same log can therefore take different recovery paths. **The rule: recovery is determined by the failure class and the raising engine, never by depth or by which handler was mid-flight**, and the recovery action must consume no sequence numbers conditionally.

The second property is bounded and worth stating because it limits what any resolution can promise: **the platform has no rollback.** A synchronous bus with no transaction boundary means containment can prevent *further* mutation and cannot undo prior mutation. Halting on `TRUTH_FAULT` is therefore not a recovery mechanism — it is the acknowledgment that recovery is unavailable, and that continuing to trade against possibly-wrong state is worse than stopping.

---



### Standing checks

**No amendment needed.** Every engine sheet already declared its own ON EXCEPTION classification, and each maps onto the taxonomy without revision: engines 2, 4, 6, 9, 11, 12 contained per declared unit; engines 5, 7, and engine 10's post-wire case halt. The taxonomy formalizes what twelve sheets independently converged on, which is the strongest available evidence that the classification is right rather than invented for this turn.

**The measured baseline this must fix.** Phase 0 F.5 rates the current state `Mixed`: the tick path has a stated policy — hop 2's tick-wide `try/except` at `src/feelies/kernel/orchestrator.py:1466` → `_handle_tick_failure`, macro `DEGRADED`, `_pipeline_abort_requested` — and "that is the only place a policy is declared. Elsewhere it is per-site: 20 fail-quiet handlers, 9 of them bare `pass`. There is no platform-wide taxonomy of recoverable vs fatal and no single module defining it."

Two of those 20 sit on decision paths, and both are already assigned:

- `src/feelies/composition/engine.py:388` — `except Exception: current_positions[s] = 0.0`, silently reporting a failed position lookup as flat, marked `# pragma: no cover` so it is also untested. Engine 6's sheet: construction halts for that boundary and emits.
- `src/feelies/alpha/risk_wrapper.py:189` — `except KeyError: pass`, so an unregistered `strategy_id` "skips **all** per-alpha risk budgets and falls through to aggregate checks only." Engine 8's sheet: zero budget, alerted.

Phase 0's assessment of the second is the general principle stated at a single site: "the direction on unknown input is *fewer* constraints, not more." Under this taxonomy neither is a containment at all — both are `DEGRADED_INPUT` handled as if it were `ENGINE_FAULT`, which is how a degraded branch acquires an exception handler and loses its emission.

**The tick-wide boundary is too coarse and this resolution narrows it.** Hop 2 wraps the *entire* tick, so an engine-2 sensor fault, an engine-8 veto fault and an engine-10 submission fault all arrive at one handler as `Exception` and receive one response. Under the propagation rule each is classified at its own engine boundary first, and only unclassified escapes reach the tick-wide handler — where they are now a named invariant violation rather than the normal case.

**Conformance tests, since this responsibility has no engine sheet to carry them:**

1. **Emission totality.** Fault-inject at every declared containment unit; assert a failure record on every branch. Retires the 20-handler class rather than the two sites.
2. **Fail-quiet static check.** No `except` whose body neither raises, returns, nor logs, outside a declared allowlist with per-entry justification — the template exists at `tests/acceptance/test_no_walltime_outside_clock.py:72`, including its stale-entry guard at `:96`, and `tools/arch/gatescan.py` already finds the sites.
3. **Recovery determinism.** Same fault, same log, permuted subscription order ⇒ identical recovery path and identical post-fault stream.
4. **Cascade depth bound.** Assert the maximum; a cycle raises `INVARIANT_VIOLATION` naming the cycle, not `RecursionError`. Phase 1 §3 requires the bound and nothing provides it.
5. **Halt-on-truth-fault.** Fault-inject an engine-7 write; assert halt, not degraded-and-continue.

**Alternatives set aside, with reasons:** engine 11 (cold; would sit in a hot control flow, and it is the recipient not the arbiter); engine 8 (would make risk the arbiter of framework failures, and its veto must stay a pure function of request and state); per-engine ownership with no central rule (the current state, and the reason 20 handlers each decided independently).

**Alpha-naming (CORE §I).** Clean.

**Model finding: none — but this is the closest the model has come, and the reason it does not fire is worth recording.** F.5 fits no engine in §E, which is exactly CORE §A's trigger condition. It does not become a model finding because §E's cross-cutting kernel is part of the model, not an exception to it, and this responsibility is framework with no trading-domain calculation — the kernel's stated remit. **The line to watch:** if a later phase finds the taxonomy needs to know an engine's *trading* semantics to classify a fault, the kernel would be acquiring trading-domain content and this becomes a model finding.

**Assumption registered.** Whether the 18 handlers Phase 0 rated benign — parse fallbacks, `queue.Empty`, `ImportError` capability probes — are all genuinely off decision paths is `VERIFIED` for the two that are not and `INFERRED` for the rest, since Phase 0 read the two and classified the remainder. Test 1 settles it mechanically rather than by re-reading.

## RESPONSIBILITY: F.6 — Backpressure

**RESPONSIBILITY:** 6. Backpressure — a synchronous bus has no queue; the latency budget is the only control. State what happens when event rate exceeds budget in live.

**OWNER ENGINE:** Split — 1 (ingress shed) and 11 (budget breach). One responsibility, two mechanisms, and forcing them onto one engine is the error.

**WHY THIS SPLIT:**

§F's own framing contains the reason. "A synchronous bus has no queue; the latency budget is the only control" is not one statement — it is two facts about two different places. There is exactly one queue in the platform and it is at the wire; everywhere inside, overload has no queue to grow into and manifests as tick latency. Those need different mechanisms because the overload is observable at different points and the exposure-reducing action differs.

**At ingress, backpressure is engine 1's and it already works.** Phase 0 F.6 rates it **owned,** `Clear` **where present**: `src/feelies/ingestion/massive_ws.py` owns the only queue in the system — bounded, drops on full, counts drops (`_events_dropped`), logs a warning, and notifies the normalizer via `notify_feed_interrupted` so the drop surfaces as a `DataHealth` degradation rather than a silent gap. Phase 0 checked it directly against CORE §J's silent-drop anti-pattern and rated it `implemented`, explicitly not the anti-pattern. Engine 1's sheet already called this "the model for every other path," and this resolution ratifies it rather than redesigning it.

**Inside the platform, overload is a latency-budget breach and it is nobody's today.** Phase 0 F.6: "Everywhere else the answer is 'there is no queue': the bus is synchronous (`src/feelies/bus/event_bus.py:65`), so backpressure inside the platform manifests as tick latency, not queue growth." Nothing measures a per-tick budget against a bound, and nothing acts when it is exceeded.

**Why engine 1 cannot own the second half, which is where the naive answer fails.** Shedding at the wire when the *inside* is slow is a cure applied at the wrong end. Dropping quotes reduces the tick rate, but it degrades exactly what the platform needs most under stress — a current view of the market — and it does so blind: engine 1 cannot tell whether the queue is filling because the venue got busy or because engine 6 is slow. Worse, a shed at ingress while a position is open reduces *information* without reducing *exposure*, which fails CORE §C.5's direction test while superficially satisfying it.

**Why engine 11 owns the second half.** A budget breach is an assumption violation, and CORE §E names latency drift first in engine 11's list of what kill switches monitor. Engine 11 already holds the platform's only hot-readable safety authority, so the escalation path from *measured breach* to *stop trading* exists and needs no new mechanism. It is also the only engine positioned to observe the breach without being on the decision path.

**The action, and it is the part that must be right.** When ticks exceed budget, the exposure-reducing response is not to drop market data. It is:

1. Continue processing market data at full rate — marks stay current, engine 7 stays truthful.
2. **Stop opening.** Engine 8 refuses new exposure on a sustained breach.
3. **Keep closing available.** Reductions remain permitted, on the same asymmetry engine 9's sheet established: the bar to open is higher than the bar to close.
4. Escalate to kill switch on a declared, more severe threshold.

That ordering is the whole content of this resolution: **under overload the platform gets slower and less willing to trade, never blinder.**

**CONTRACT PUBLISHED:**

**Engine 1 — ingress shed record.** Already substantially present; formalized as a contract: queue depth and capacity, drops since last transition, the resulting `DataHealth` state, and the affected symbols. Emitted on transition, not only counted.

**Engine 11 —** `LatencyBudgetState`**:**

- **Per-tick elapsed and per-engine attribution**, in nanoseconds, against declared budgets.
- **Breach state** from a closed enumeration: `WITHIN`, `MARGINAL`, `SUSTAINED_BREACH`, `SEVERE` — with sustained defined over a declared window of ticks, not one tick. A single slow tick is noise; a run of them is a regime.
- **The declared budget and window on the payload**, so a reader can tell whether `WITHIN` means comfortable or means the bound is loose.
- **Consequence state**: whether new exposure is currently permitted, so engine 8's behaviour is readable from the contract rather than inferred.

**FAILURE BEHAVIOR:**


| Condition                       | Behaviour                                                                                                                                                              |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ingress queue full              | Drop, count, warn, degrade `DataHealth`. Current behaviour, retained.                                                                                                  |
| Sustained budget breach         | Engine 8 refuses new exposure; reductions permitted; engine 11 alerts.                                                                                                 |
| Severe breach                   | Kill switch. Halt, flat-only.                                                                                                                                          |
| Latency measurement unavailable | **Treated as breach.** Same rule as engine 11's unreadable-kill-switch case and engine 8's undetermined-divergence case: an unmeasurable assumption is a violated one. |
| Breach during an open position  | Never resolved by shedding market data. Marks stay current; the veto tightens.                                                                                         |
| Breach in BACKTEST              | Not a breach. The concept is live-only — see the determinism note.                                                                                                     |


**DETERMINISM NOTE:** *(not mandatory for F.6, but the resolution is unsound without one property, and it is the property most easily got wrong.)*

**Backpressure must be a live-only behaviour with zero effect on replayed output, and this is harder than it sounds.** Latency is wall-clock derived, so any control loop that reads it is nondeterministic by construction. If a budget breach can change what the platform trades, then replaying a live log reproduces the trades only if it also reproduces the timings — which it cannot.

The resolution is to make backpressure a **recorded input rather than a computed reaction**. The breach state and the resulting consequence are emitted into the event log as engine-11 events, and replay consumes them as data. A replayed run does not re-measure latency and does not re-decide; it reads what was decided and reproduces the same behaviour. This is the same shape as F.4's requirement that the broker's report enter the log — an external, non-reproducible input is replayable only if recorded.

The existing machinery is exactly right and must be preserved: Phase 0 D0.4 records that `_finalize_tick` routes always-on timers to `self._metrics.record` with `sequence=0` (`src/feelies/kernel/orchestrator.py:2131`) "precisely so they cannot shift kernel event IDs," while conditional timers publish with `self._seq.next()` at `:2147`, and the conditional set is a function of deterministic control flow — so sequence consumption stays deterministic even though the timer *values* are wall-clock derived. Phase 0 rates this `implemented` and correct. **A backpressure controller that consumed timer values into a decision would break that property**, which is why the decision is recorded rather than recomputed.

Ingress shedding is deterministic-by-irrelevance for a different reason: it happens before the log, so a replayed log contains what survived and the drop notification is itself a logged event.

---



### Standing checks

**Amendment to the engine-1 sheet, recorded not applied.** That sheet listed backpressure under MUST NOT OWN as "engine 1 owns the shed-and-notify *mechanism* at the wire; whether the platform sheds is policy — §F.6 pending." Resolved: **engine 1 owns ingress shed policy and mechanism both**; the internal budget-breach half is engine 11's. Engine 11's sheet already lists latency drift under assumption-violation monitoring, so it needs the `LatencyBudgetState` contract added but no revision.

**This is the first §F item resolved to two owners, and the justification has to clear CORE §C.6.** Single source of truth per fact — and there are two facts here, not one: *the wire is producing faster than we can accept* and *we are processing slower than budget*. They are independently observable, independently caused, and have opposite correct responses. Splitting them is not splitting the difference; treating them as one fact would be. **The test that keeps the split honest:** neither owner may act on the other's signal. Engine 1 does not shed because ticks are slow; engine 11 does not tighten the veto because the queue is full.

**A dependency Phase 4 must resolve first, and it is blocking.** This resolution assumes a measured per-engine latency budget exists to breach. It does not. Phase 0 U-7 records that the actual tick-path latency distribution is unmeasured, that no profiling run was performed, and that perf tests are per-host gated. Engine 11's sheet already flagged the consequence: "latency drift cannot currently be monitored against a baseline that exists." So F.6's engine-11 half is `specified` and cannot become `implemented` until Phase 4 produces the budget — which is why CORE §L states the phase order is load-bearing and that "the performance budget needs the hot/cold assignment those produce."

**One small artifact worth naming.** Phase 0 C-3 and Phase 1 §3 both record that `subscribe_all` has zero call sites while its `_global_handlers` list is iterated on **every** publish to walk an always-empty list. That is per-publish overhead on the tick path serving a dead API — relevant to a latency budget, flagged not actioned, since CORE §H requires scoped authorization for removal.

**Alternatives set aside, with reasons:** engine 1 alone (would shed information under internal overload — reduces visibility without reducing exposure); engine 8 alone (has the right action but cannot observe the breach without a wall-clock read on the veto path, which would make its verdict nondeterministic); a queue inside the bus (would convert a latency problem into an unbounded-memory problem and break the synchronous-dispatch semantics 16 of 32 handlers depend on, per Phase 1 §3); dropping the budget concept and relying on the ingress queue (the failure this item names is *internal*, and the ingress queue cannot see it).

**Alpha-naming (CORE §I).** Clean. Worth noting the axis this becomes real on: CORE §I names symbol cardinality as untested, and internal budget breach is a function of universe size — a platform that never exceeds budget at N≈1 symbol has not been tested, it has been under-loaded.

**Model finding: none.** Two mechanisms under one responsibility, each fitting an engine whose §E mandate already covers it — engine 1's "gap detection and notification," engine 11's assumption-violation monitoring. No engine carries an irreconcilable job.

**Assumption registered.** Whether the ingress queue's bound and drop policy are configured or hardcoded is not established. It determines whether ingress shed behaviour enters the run fingerprint — and under this resolution it must, since a differently-bounded queue drops differently and produces a different log.

## RESPONSIBILITY: F.7 — Contract and schema versioning

**RESPONSIBILITY:** 7. Contract and schema versioning — replaying a vN log under vN+1 code. Upgrade-on-read, pinned-code-per-log, or refuse-and-fail-loud. State which parity hashes survive a schema change.

**OWNER ENGINE:** Kernel — cross-cutting, per CORE §E.

**WHY THIS ENGINE:**

The argument is the same one that placed F.5, and it is stronger here. CORE §E gives the kernel "contracts" by name, and all 21 event types are declared in one module (`src/feelies/core/events.py`) with `events_with_version_field` empty and `event_classes_outside_core_events` empty — so the contract surface is already kernel-owned and already closed. Versioning is a property *of* that surface, not of any producer on it.

Every engine alternative fails on the same point: a version that only the producer understands is not a version. Engine 1 produces the log but does not own the types in it; engine 12 reads it but holds no write authority by its own sheet's rule; engine 5 versions *alphas*, which is a different fact. The one engine-shaped case worth naming and rejecting is per-type ownership — each engine versions its own contracts — which fails because a replay must decide whether it can proceed *before* dispatching to any engine, and twenty-one independently versioned types give it twenty-one answers.

**The resolution itself was made in Phase 1 §8**, which explicitly states it "resolves CORE §F.7." This turn ratifies that call, assigns the owner, and states the failure behaviour and the parity consequence §F asks for. I am not re-deriving it — Phase 1's reasoning holds and re-litigating a settled call would be the confirmation-bias failure this review's evidence discipline exists to prevent.

**CONTRACT PUBLISHED:**

**One** `schema_version: int` **on the base envelope** (`src/feelies/core/events.py:30`), not per type. Phase 1's reason, quoted in substance: twenty-one per-type versions is twenty-one things to forget; one envelope field is checkable at the boundary in one place, and per-type evolution becomes an envelope bump plus a migration entry, keeping the log self-describing with one integer.

The envelope today is exactly four fields — `timestamp_ns`, `correlation_id`, `sequence`, `source_layer` — and this makes it five. Note what already exists and must not be confused with it: `SensorReading.sensor_version` (`:622`) and `HorizonFeatureSnapshot.feature_versions` (`:650`) record *which estimator* produced a value. Neither records *what shape the record has*. Producer versioning exists; schema versioning does not.

**Compatibility rule: pinned-code-per-log, with refuse-and-fail-loud as the fallback.** Phase 1's rejection of upgrade-on-read is the load-bearing part: it "silently changes what a historical log replays to, which is precisely the guarantee CORE §C.11 exists to protect." A log records the version it was written under; replay under code that does not declare support for it **refuses, naming both versions**. Deliberate migration is an explicit, recorded operation producing a new log with a new fingerprint — never an implicit read-time rewrite.

**Replay guarantee:** a vN log replays bit-identically under any code declaring vN support, and fails loudly under any that does not. There is no third outcome, and in particular no "mostly works."

**The declared-support set is itself an artifact** — the versions this build can replay, entering the run fingerprint alongside `universe_hash` (F.1), `identity_hash` (F.2) and the parity manifest fingerprint. A build that cannot say which versions it supports cannot refuse honestly.

**FAILURE BEHAVIOR:**


| Condition                                             | Behaviour                                                                                                                                                                                                                                           |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Log version outside the declared-support set          | **Refuse, naming both versions and the supported range.** No partial replay, no best-effort.                                                                                                                                                        |
| Event arrives with no `schema_version`                | Refuse at the receiving boundary, loudly, with provenance (CORE §G.3). A missing version is not v1 by default — defaulting it is upgrade-on-read wearing a different name.                                                                          |
| Version present but the type is unknown to this build | Refuse. Dispatch is exact-type only (`self._handlers.get(type(event))` at `src/feelies/bus/event_bus.py:65`), so an unknown type today produces *nothing*: no exception, no counter, no log. Silence is the current answer and it is the wrong one. |
| Migration produces a new log                          | New log, new fingerprint, both recorded. The original is never mutated in place.                                                                                                                                                                    |
| A field is added without a version bump               | Caught by the conformance test below, not by the oracle — see the determinism note.                                                                                                                                                                 |


**DETERMINISM NOTE:** *(mandatory for F.7 per P2 — and it is the item where the note is the substance.)*

**Which parity hashes survive a schema change — the answer §F asks for, and it is the uncomfortable one.** Phase 1 §8 measured it directly:


| Change                                | Manifest outcome                                                                                           |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Add a field to any event              | **All 26 survive, silently**                                                                               |
| Change the value of an unhashed field | **All 26 survive, silently**                                                                               |
| Remove an unhashed field              | **All 26 survive, silently**                                                                               |
| Rename a hashed field                 | The owning helper raises `AttributeError` — loud, but it surfaces as a test *error*, not a parity mismatch |
| Change a hashed value                 | The owning baseline mismatches — the case the oracle is built for, and it works                            |


The mechanism is that the hash input is a hand-written field list per helper, so a new field is unhashed until a human edits a helper. **So the oracle is strong against behaviour change and blind to schema change**, and those are exactly the two failure modes versioning must separate. The two gaps compound: no version on the wire means a vN log cannot be identified, and a field-list hash means the schema drift that identification would have caught is invisible anyway.

Two of the silently-surviving cases are not hypothetical. Phase 0 P-1 names `OrderRequest.limit_price` and `OrderRequest.is_moc` as unhashed fields whose values change execution semantics — so a change to *where an order routes* passes all 26 baselines today.

**The consequence for migration, stated up front because Phase 7 needs it:** adding `schema_version` to the base envelope adds a field to all 21 types, and by the table above **that change breaks nothing** — every baseline survives, because a new field is unhashed until a helper is edited. Phase 1 puts it exactly right: that is convenient and it is also the defect. **The step that adds the field and the step that brings it into the hashed field set are two different steps with two different blast radii, and the second re-pins baselines across the board.**

**A second-order consequence this turn adds.** F.2's resolution replaces `symbol` with `instrument_id` plus a display ticker on every event — a schema change across all 21 types, arriving through this mechanism. It is the first real customer of F.7 and it exercises both steps: the field addition (silent) and the hash inclusion (a coordinated re-pin, visible as one line through `manifest_fingerprint()` at `tests/determinism/parity_manifest.py:234`).

---



### Standing checks

**No amendment needed.** Engine 1's sheet lists `schema_version` in its EMITS provenance; engines 2–12 inherit it from the envelope. Phase 1 §8 already made the call and this turn assigns the owner it did not name.

**The blast radius §F predicted is confirmed by measurement.** Phase 0 F.7 rates this "the §F item with the widest blast radius," and Phase 1 §8 independently calls it "the §F item with the widest blast radius." Both are right, and the reason is that it is the only §F item whose absence corrupts the *evidence* rather than the behaviour: an unversioned log cannot be trusted to prove anything about a past run, including the runs the other six resolutions would be validated against.

**Conformance tests, since this responsibility has no engine sheet to carry them:**

1. **Envelope totality.** Every event carries `schema_version`; a missing one fails at the receiving boundary.
2. **Refusal.** Replay a log stamped outside the supported range; assert refusal naming both versions, and assert no partial output.
3. **Schema-drift detection** — the test that closes the real gap. AST-scan every event class's declared field set, hash it, and pin that hash. A field added, removed or renamed on any of the 21 types then fails a test *by construction*, without anyone remembering to edit a helper. This is the structural fix for "the oracle cannot detect schema growth," and it is the same AST-test shape already proven twice in this codebase — `tests/acceptance/test_no_walltime_outside_clock.py:72` with its stale-entry guard at `:96`, and the parity manifest's own closure test at `tests/determinism/test_parity_manifest.py:261`.
4. **Version-bump coupling.** A changed schema hash without a `schema_version` bump fails.
5. **Fingerprint linkage.** The declared-support set enters `config.snapshot().checksum`, and the run records the parity manifest fingerprint it was accepted under. Phase 1 §7 measured these as two unlinked artifacts — "neither references the other, so *which oracle version accepted this run* is not recorded."

**Alternatives set aside, with reasons:** per-type versioning (twenty-one answers to a question replay must settle once, before dispatch); upgrade-on-read (silently changes what a historical log replays to — the guarantee CORE §C.11 exists to protect); engine 1 as owner (produces the log, does not own the types; and it is hot, while refusal is a composition-time decision); engine 12 (reads the log, holds no write authority); a version file alongside the log (Phase 1's framing is that the version must travel *with* the payload, not alongside it — a sidecar can be lost, copied wrong, or edited).

**Alpha-naming (CORE §I).** Clean.

**Model finding: none, and the same watch-line as F.5.** F.7 fits no §E engine, which is CORE §A's trigger. It does not fire because the cross-cutting kernel owns contracts by §E's own text and versioning is contract machinery with no trading-domain content. If a later phase finds the compatibility rule needs to branch on what an event *means* to a strategy, the kernel would be acquiring trading-domain content and this becomes a model finding.

**Assumption registered.** Whether any log is durable enough for cross-version replay to arise in practice is unestablished — `src/feelies/storage/memory_event_log.py:7` states there is "No persistence — all events are lost on process exit," and the one durable artifact is a disk *event cache*, which gates the exempt `_BASELINE_TRADE_PARITY_HASH`. If that cache is the only cross-version surface, F.7's urgency is lower than its blast radius suggests and its scope is narrower. Either way the schema-drift test (3) is worth building first: it is the half that pays off immediately, with or without durable logs.

---

**All seven §F resolutions complete.** Together with the twelve engine contract sheets, deliverable **B** is finished — every §F item has exactly one named owner (F.6 by a justified two-mechanism split), and CORE §M's requirement that each be resolved is met for Phase 2's share of it.

**Carried into Phase 3**, as flagged across the sheets and not resolved here: two production paths to a desired portfolio (engine 6 overlap 2); the read-surface design for the four never-subscribed contracts plus engine 12's private-attribute observation path; the 24 mode branches split into composition-root selection versus in-engine branching; the gate ladder over the 56-site `regime_gate` family. **Two §F-class findings recorded for the operator** (CORE §A), neither in §F.1–7 and neither resolved: the horizon grid (engine 2's sheet) and risk-model provenance (engine 6's sheet).

---

## ADDENDUM (post-Phase-7, pre-execution): F.8 — Horizon grid

**Provenance of this section.** Phase 2 closed with seven §F resolutions and recorded the horizon grid as an unresolved §F-class finding on engine 2's sheet (`:217-228`). Phase 7's §K.1.4 promoted it to a model finding, its Definition-of-Done item M2 called for it to be "added as §F.8 and resolved on the produce/interpret/apply pattern the other seven used, **before execution rather than during it**", and its closing section listed it as one of three things that should close before execution begins. This addendum discharges that. It is written in Phase 2's §F template because §F resolutions are Phase 2's deliverable; it is marked as an addendum rather than folded into the body so the audit trail shows Phase 2 concluded seven and the eighth arrived later.

**RESPONSIBILITY:** 8. Horizon grid — which horizons exist, when their boundaries fall, and what anchors them. Engines 2, 4 and 6 must see the same grid at the same event time.

**OWNER ENGINE:** 2 — Feature Estimation.

**WHY THIS ENGINE:**

The consumer list decides it, exactly as it did for F.1. Four places hold a view of the grid today and none produces it, and three of the four hold a *separately derived* view:

| Holder | Site | What it holds |
|---|---|---|
| Boundary scheduler | `src/feelies/sensors/horizon_scheduler.py:97` | its own `_horizons_sorted` |
| Composition barrier | `src/feelies/composition/synchronizer.py:68-75` | its own `_context_horizons`, `_signal_horizons` and `_signal_horizons_sorted` |
| Snapshot assembly | `src/feelies/features/aggregator.py:153-157` | features sorted by `(feature_id, horizon_seconds, feature_version)` |
| Anchor | `src/feelies/core/session_clock.py:47` | `rth_open_ns` |

All four are handed their inputs by the composition root — `horizons=config.horizons_seconds` at `src/feelies/bootstrap.py:1206`, and a separately computed signal subset via `_composition_signal_horizons` at `:1471` — so the grid is assembled at composition and immediately forgotten. There is no artifact, no version and no hash, which is why a disagreement between the four is undetectable rather than merely unlikely.

Engine 2 is the owner for the reason its own sheet gave: it already owns boundary snapshots, so the grid is a second field on an artifact it already publishes rather than a second mechanism. Three alternatives, rejected:

- **The composition root**, which is what assembles the grid today. It selects and wires; it does not own facts, and it publishes no versioned artifact. Leaving ownership there is what produced three private sorted views.
- **Engine 6**, by the same cycle argument that removed it from F.1: the composition barrier is the *last* consumer of the grid, so a grid owned there would be defined after two of its own consumers had used it.
- **The session clock**, which produces `rth_open_ns`. The anchor is an *input* to the grid, not the grid — the same produce/interpret distinction F.3 drew between observing session state and constraining on it.

**Membership and anchoring are different facts and must not share a channel**, on F.1's pattern: which horizons exist is governance resolved at composition, while where a boundary falls is derived from the anchor. Collapsing them would make a tzdata change look like a grid change.

**CONTRACT PUBLISHED:**

A `HorizonGrid`, resolved at composition, frozen, consumed once — deliberately the same shape as F.1's `UniverseSnapshot`:

- **Horizons as an ordered tuple**, sorted, not a set. Phase 1 budget row 3 measured set iteration as a live nondeterminism source with no named check, and the three private sorts above are three independent chances to disagree. Consumers read the published order and must not re-sort.
- **The signal-horizon subset as a declared field**, not a value derived at the composition root. Today `_composition_signal_horizons` (`bootstrap.py:1471`) computes it and `UniverseSynchronizer` re-derives a sorted copy; one of those two is redundant and neither is recorded.
- **As-of semantics:** session id and the anchor event time, which is the session's opening boundary.
- **The anchor's own provenance, including the host tzdata version.** Phase 1 budget row 13 states that a tzdata change "would silently move every horizon grid", and it is currently unpinned and unrecorded. A grid that does not record what anchored it cannot prove two runs used the same boundaries.
- `grid_hash` over the ordered horizons plus the anchor, and a `grid_version`, entering the run fingerprint alongside `universe_hash` (F.1) and `identity_hash` (F.2).
- `is_boundary(horizon, timestamp) → bool`, total. There is no third answer and no "not yet known."

**FAILURE BEHAVIOR:**

| Condition | Behaviour |
|---|---|
| A consumer requests a horizon not in the grid | Refuse at the boundary, naming the horizon and the grid version. Not an empty result — an absent horizon is a wiring error, and returning nothing makes it look like a quiet session. |
| A boundary is missed | Emit the gap, per engine 2's existing rule that "a missed boundary is a gap and must emit". |
| Host tzdata differs from the version the grid recorded | Refuse at load, naming both. This is the one condition the platform cannot currently detect at all. |
| Two consumers observe different grids | Impossible by construction once the grid is published rather than assembled per consumer — which is the point of the resolution, and what the conformance test below asserts. |

**DETERMINISM NOTE:**

Declaring the grid moves no baseline. It is composition-time data and enters no hash helper's field list, so by Phase 1 §8's table it is an addition the oracle is blind to — the same property, and the same caveat, as `schema_version` under F.7. **The acceptance condition is therefore not "the hashes hold" but "the three private views are gone":** if `_horizons_sorted`, `_signal_horizons_sorted` and the composition-root derivation still exist after the step, the contract was added without removing what it replaced, and the disagreement it exists to prevent is still possible.

**Conformance test:** one grid per run, asserted structurally — no module outside engine 2 may hold a sorted horizon collection, on the AST-scan pattern already proven by `tests/acceptance/test_no_walltime_outside_clock.py:72`.

**Alpha-naming (CORE §I).** Clean — the grid is a set of integers with no alpha, symbol or archetype in it. Note that the canonical horizon set is a platform constant and the CORE §C.7 prohibition is on *branching* on a horizon, not on declaring which exist.

**Model finding: none.** Engine 2 owning the grid is a strong fit rather than a forced one: it already owns the boundary artifact the grid describes.

**Step placement is an operator call, and this addendum does not make it.** Phase 7 §K.5 ruled "no new step — the grid is a config constant today, so this is a contract to declare rather than a capability to build", which implies folding it into an existing wave-C contract step. Which one is not derivable from anything written down, so the plan must name it before S-01 rather than during wave C.

---

## UNRESOLVED: F.9 — Risk-model provenance

**Not resolved here, and recorded so that §F's incompleteness is not understated.** Phase 2's engine-6 sheet (`:687`) records "**a ninth unassigned responsibility: risk-model provenance**" — factor loadings, covariance and betas, which CORE §E has engine 6 consume and gives no engine the production of. Phase 0 D0.2 places factor loadings and the sector map in `storage/reference/` under "Unowned by any engine", "consumed by engines 6, 7, 10 and by `bootstrap`; owned by none". Phase 2's closing paragraph above lists it alongside the horizon grid; its recommended owner is engine 12.

**Phase 7 did not carry it.** §K.1.4 treats the horizon grid as the sole eighth item and reasons that "a seven-item list that turns out to have eight items invites the question of whether it has nine, and nothing in Phases 0–7 was designed to answer that"; the Definition-of-Done repeats that "no phase had a method for finding an eighth, so none has a method for finding a ninth". **A phase did find the ninth** — Phase 2, in the same document, using that word — so the correct statement is narrower and worse: the method existed and the finding was recorded, and the later phase that enumerated §F-class gaps read one of the two sheets that carried one.

**Two reasons this needs an operator rather than an addendum.** First, the recommended owner is in tension with a rule Phase 2 applied elsewhere: engine 12 was rejected as owner of F.2 because it "holds no write authority by its own sheet's rule" (`:1573`), and that objection is not obviously weaker here. Second, unlike the horizon grid, this may be a capability to build rather than a contract to declare — the loadings are unowned and unversioned reference data, so §K.5's "no new step" reasoning does not transfer, and resolving it could add scope to a locked plan.