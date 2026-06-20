# Data Ingestion / Replay / Storage Audit - 2026-06-19

**Scope:** raw Massive REST/WS messages -> `MassiveNormalizer` -> `EventLog` /
`DiskEventCache` -> `ReplayFeed` -> orchestrator `_process_tick` /
`_process_trade`.

**Mode:** read-only, evidence-based audit. No code fixes were made.

**Verdict:** No P0 found. The replay and cache paths are substantially rigorous:
canonical resequencing is centralized and defended at write and replay time,
REST and WS converge through the normalizer, BT-17 latency is wired from
`PlatformConfig`, and targeted ingestion/storage/causality tests pass. The main
remaining risks are live-feed loss/partial-subscription handling and default
offline replay behavior for unhealthy-but-readable data.

## 0. Remediation Status

Read-only audit. No remediation changes were made in this pass.

| ID | Status | Notes |
|----|--------|-------|

## 1. Executive Summary

1. **[P1] Offline backtest defaults still replay non-HEALTHY ingestion days unless
   the operator opts into stricter gates.** The CLI warns and continues by
   default; fail-closed behavior exists but is disabled by default.
2. **[P1] Live WS queue overflow drops normalized market events without driving
   `DataHealth` or macro degradation.** This is observable via logs and
   `events_dropped`, but not coupled to the trading safety path.
3. **[P1] Partial WS subscription confirmation can run in degraded coverage with
   only a warning.** Because pre-registered symbols report `HEALTHY` before any
   message, a missing quote/trade channel may not trip runtime integrity.
4. **[P1] Live/paper forensic logs omit the bad/gappy market event that triggers
   `DataHealth` blocking.** This is fail-safe for trading, but weak for
   post-incident replay because there is no immutable raw vendor log.
5. **[P2] Malformed frames with no usable symbol cannot mark any stream
   `CORRUPTED`.** The normalizer logs and drops them; only oversized frames and
   non-dict WS elements have explicit counters.
6. **[P2] Cache `normalizer_version` is provenance only.** Load acceptance checks
   `event_schema_hash`; normalizer-version mismatch alone does not invalidate a
   cache.
7. **[P2] Residual wall-clock fallbacks exist in provenance/freshness paths.**
   They are not replay hot-path timestamps, but they are Inv-10/Inv-5 caveats.
8. **[P2] Reference-data validation is split across consumers rather than owned
   fully by `storage/reference`.** Event calendars and ex-dates are strong;
   factor-loadings and sector-map validation mostly lives in bootstrap and
   composition.
9. **[P2] Trade condition codes are preserved, but there is no general
   regular-sale/irregular-print eligibility policy at the ingestion boundary.**
   Halt/SSR codes are handled; other conditions flow downstream unfiltered.
10. **Verified strengths:** global multi-symbol ordering is fixed; `ReplayFeed`
   enforces causality; `JsonLineEventSerializer` exists and is used by
   `DiskEventCache`; default BT-17 latencies are non-zero; targeted tests passed.

## 2. Architecture Trace

```text
Massive REST /v3 quotes,trades
  -> MassiveHistoricalIngestor
  -> MassiveNormalizer(source="massive_rest")
  -> InMemoryEventLog append_batch
  -> per-symbol/day DiskEventCache JSONL.gz + manifest
  -> cache/API merge in backtest_runner.ingest_data
  -> resequence_event_list
  -> ReplayFeed
  -> ExecutionBackend.market_data.events()
  -> Orchestrator._run_pipeline
     NBBOQuote -> _process_tick -> M1 -> bus -> sensors/signals/risk/orders
     Trade     -> _process_trade -> bus/router trade hooks/scheduler

Massive WS Q.*,T.*
  -> MassiveLiveFeed background asyncio thread
  -> MassiveNormalizer(source="massive_ws")
  -> bounded queue
  -> ExecutionBackend.market_data.events()
  -> Orchestrator._run_pipeline
     NBBOQuote/Trade as above; IdleTick drains async fills only

Disk cache only
  -> DiskEventCache.load checksum/schema/count/deserialize checks
  -> load_event_log_from_disk_cache
  -> resequence_event_list
  -> ReplayFeed
  -> Orchestrator
```

## 3. Invariant Compliance Matrix

| Invariant | Verdict | Evidence |
|-----------|---------|----------|
| Inv-5 deterministic replay | **Pass** | Canonical key is `(exchange_timestamp_ns, symbol, type_rank, prior_sequence)` and resequence rebuilds contiguous sequences/correlation IDs (`src/feelies/storage/event_resequence.py:33`, `src/feelies/storage/event_resequence.py:46`). `backtest_runner.ingest_data()` globally resequences cache/API events before replay (`src/feelies/harness/backtest_runner.py:424`). Cache-only replay does the same (`src/feelies/storage/cache_replay.py:125`). |
| Inv-6 causality | **Pass** | `ReplayFeed` rejects backward merge keys (`src/feelies/ingestion/replay_feed.py:90`) and advances `SimulatedClock` only to visibility time when greater than current time (`src/feelies/ingestion/replay_feed.py:100`). `InMemoryEventLog` uses the same guard for strict logs (`src/feelies/storage/memory_event_log.py:110`). |
| Inv-9 backtest/live parity | **Partial** | Both modes share `ExecutionBackend.market_data.events()` and orchestrator dispatch (`src/feelies/execution/backend.py:34`, `src/feelies/kernel/orchestrator.py:1763`). Paper/live use `MassiveLiveFeed` with the same normalizer (`src/feelies/execution/paper_backend.py:43`). Gaps remain around live queue drops, partial subscriptions, and backtest health-gate asymmetry. |
| Inv-10 clock abstraction | **Partial** | Normalizer receipt timestamps use injected `Clock` (`src/feelies/ingestion/massive_ws.py:382`, `src/feelies/ingestion/massive_ingestor.py:433`). Replay uses `SimulatedClock` visibility time. Caveats: cache `created_at` can fall back to `time.gmtime()` (`src/feelies/storage/disk_event_cache.py:82`) and factor freshness can fall back to `time.time()` (`src/feelies/bootstrap.py:2226`). |
| Inv-11 fail-safe | **Partial** | Cache corruption/schema/count failures fail closed to `None` (`src/feelies/storage/disk_event_cache.py:119`). REST partial pagination refuses normalization/checkpoint (`src/feelies/ingestion/massive_ingestor.py:380`). Live queue overflow and partial subscription are warning/counter paths rather than health/degrade paths. Offline unhealthy ingestion is warning-only by default (`src/feelies/harness/backtest_runner.py:443`). |
| Inv-13 provenance | **Partial** | Boundary correlation IDs are assigned by normalizer (`src/feelies/ingestion/massive_normalizer.py:461`, `src/feelies/ingestion/massive_normalizer.py:529`, `src/feelies/ingestion/massive_normalizer.py:643`, `src/feelies/ingestion/massive_normalizer.py:707`). Cache manifests persist checksums, schema hash, counts, normalizer version, and ingestion health (`src/feelies/storage/disk_event_cache.py:238`). There is no raw vendor-frame archive; live bad/gappy events may be dropped before event-log append. |

## 4. Findings Table

| ID | Severity | Effort | Component | Finding | Evidence | Recommendation | Test gap? |
|----|----------|--------|-----------|---------|----------|----------------|-----------|
| DI-01 | P1 | M | backtest_runner / PlatformConfig | Non-HEALTHY ingestion days replay by default. Strict gates exist, but defaults are `False`; the standard API replay path warns and continues. | Defaults: `require_healthy_disk_cache_manifests=False`, `backtest_enforce_ingest_terminal_health=False` (`src/feelies/core/platform_config.py:99`, `src/feelies/core/platform_config.py:114`). Warning says replay continues (`src/feelies/harness/backtest_runner.py:443`). Config only rejects when strict flags are set (`src/feelies/core/platform_config.py:744`, `src/feelies/core/platform_config.py:757`). | Make backtest CLI fail closed on non-HEALTHY day metadata by default, or require an explicit `--allow-unhealthy-ingest` / config waiver. | Partial; strict gate tests exist, default warning-to-replay should be explicitly covered. |
| DI-02 | P1 | S | MassiveLiveFeed | Queue overflow drops normalized events without setting `DataHealth.GAP_DETECTED` or degrading the macro state. | Queue full increments `_events_dropped` and logs (`src/feelies/ingestion/massive_ws.py:388`). Counter is exposed (`src/feelies/ingestion/massive_ws.py:129`). Test covers non-blocking drop/log (`tests/ingestion/test_massive_normalizer.py:762`). | On first overflow, notify the normalizer/feed-health path or publish a critical alert consumed by the orchestrator; treat as a recoverable data gap at minimum. | Yes: no test that overflow changes health/degrade behavior. |
| DI-03 | P1 | M | MassiveLiveFeed / normalizer health | Partial WS subscription confirmation runs with warning only; missing channel identity is not validated. Pre-registered symbols still report `HEALTHY` before first message. | Partial confirmation policy warns and continues (`src/feelies/ingestion/massive_ws.py:51`, `src/feelies/ingestion/massive_ws.py:332`). Registered symbols are included in `all_health()` and default to `HEALTHY` before data arrives (`src/feelies/ingestion/massive_normalizer.py:361`, `src/feelies/ingestion/massive_normalizer.py:367`). Bootstrap pre-registers live symbols (`src/feelies/bootstrap.py:468`, `src/feelies/bootstrap.py:473`). | Track expected `(symbol, channel)` subscriptions; fail connection or mark missing channels `GAP_DETECTED` until confirmed and flowing. | Yes: tests cover status parsing, not channel-level coverage/health. |
| DI-04 | P1 | M | orchestrator / provenance | Bad or gappy live events can be dropped before `EventLog.append`, so the forensic replay log lacks the boundary event that triggered the safety block. | Quote health gate runs before M1 append (`src/feelies/kernel/orchestrator.py:2273`, `src/feelies/kernel/orchestrator.py:2292`). Trade path drops CORRUPTED/GAP events before append, except HALTED provenance (`src/feelies/kernel/orchestrator.py:1816`, `src/feelies/kernel/orchestrator.py:1824`). Gap is set inside normalizer before the event is returned (`src/feelies/ingestion/massive_normalizer.py:879`). | Preserve a quarantine/audit log for rejected normalized events or raw vendor frames while still blocking trading. | Yes: no test asserts rejected event provenance. |
| DI-05 | P2 | S | MassiveNormalizer | Malformed frames with no symbol cannot mark any stream `CORRUPTED`; JSON parse failures are log-only. | JSON decode failure returns `[]` (`src/feelies/ingestion/massive_normalizer.py:322`). Parse exceptions call `_mark_corrupted(...UNKNOWN...)` (`src/feelies/ingestion/massive_normalizer.py:483`, `src/feelies/ingestion/massive_normalizer.py:551`), and `_mark_corrupted` skips unknown symbols (`src/feelies/ingestion/massive_normalizer.py:945`). | Add a global feed-health/corrupt-frame counter, and degrade when anonymous malformed frames exceed a small threshold. | Partial: symbol-known bad prices are tested; anonymous-frame health is not safety-gated. |
| DI-06 | P2 | S | DiskEventCache | `normalizer_version` is persisted but not part of load acceptance; only `event_schema_hash` invalidates. | Version comments say it is not part of schema-hash invalidation (`src/feelies/storage/disk_event_cache.py:32`). `exists()` and `load()` check only `event_schema_hash` (`src/feelies/storage/disk_event_cache.py:108`, `src/feelies/storage/disk_event_cache.py:134`). Manifest writes `normalizer_version` (`src/feelies/storage/disk_event_cache.py:246`). | Either fold normalizer semantic version into the hash or warn/reject when manifest version differs. | Yes: no normalizer-version mismatch test. |
| DI-07 | P2 | S | clock / provenance | Wall-clock fallbacks remain in cache provenance and factor-loading freshness. | Cache `created_at` falls back to `time.gmtime()` if no clock is injected (`src/feelies/storage/disk_event_cache.py:82`). Factor freshness falls back to `time.time()` if no `session_open_ns` (`src/feelies/bootstrap.py:2226`). | Pass clocks to cache construction in harnesses; require `session_open_ns` when factor loadings are configured for deterministic backtests. | Partial. |
| DI-08 | P2 | M | reference data | Reference loaders are unevenly owned: event calendars and ex-dates validate in `storage/reference`; factor loadings and sector maps validate in composition/bootstrap consumers. | Event calendar validates session date/schema (`src/feelies/storage/reference/event_calendar/__init__.py:267`). Ex-date loader validates schema and duplicates (`src/feelies/storage/reference/corporate_actions/__init__.py:268`). Factor and sector reference packages are marker modules only (`src/feelies/storage/reference/factor_loadings/__init__.py:1`, `src/feelies/storage/reference/sector_map/__init__.py:1`); consumer loaders validate JSON (`src/feelies/composition/factor_neutralizer.py:195`, `src/feelies/composition/sector_matcher.py:119`). | Centralize factor/sector loaders under `storage/reference` so provenance, schema, freshness, and consumer behavior share one contract. | Yes. |
| DI-09 | P2 | M | MassiveNormalizer / trade consumers | Trade conditions are parsed and persisted consistently, but the ingestion boundary does not define or apply a regular-sale/irregular-print eligibility filter beyond halt/SSR side effects. | WS trade conditions are parsed and attached to `Trade` (`src/feelies/ingestion/massive_normalizer.py:501`, `src/feelies/ingestion/massive_normalizer.py:531`). REST trade conditions follow the same path (`src/feelies/ingestion/massive_normalizer.py:684`, `src/feelies/ingestion/massive_normalizer.py:709`). Halt state uses configured condition codes (`src/feelies/ingestion/massive_normalizer.py:527`, `src/feelies/kernel/orchestrator.py:6246`); SSR uses configured codes (`src/feelies/kernel/orchestrator.py:6321`). No broader condition filter appears under ingestion/execution/sensors. | Define a shared trade-eligibility policy: either document “all prints pass through” as intentional, or centralize a regular-sale filter used consistently by sensors, passive queue-volume logic, and provenance. | Yes: REST/WS parity tests cover field preservation, not eligibility semantics. |

## 5. Live vs Replay vs Backfill Parity

| Topic | REST backfill | Replay/cache | Live WS | Assessment |
|-------|---------------|--------------|---------|------------|
| Typed boundary | `MassiveHistoricalIngestor` calls `MassiveNormalizer.on_message(..., "massive_rest")` (`src/feelies/ingestion/massive_ingestor.py:430`). | Replay reads already-normalized `NBBOQuote` / `Trade`. | `MassiveLiveFeed` calls `MassiveNormalizer.on_message(..., "massive_ws")` (`src/feelies/ingestion/massive_ws.py:381`). | Pass. |
| Gap detection | REST gap detection disabled by default and opt-in (`src/feelies/core/platform_config.py:120`, `src/feelies/ingestion/massive_normalizer.py:640`). | Uses manifest health only. | WS `_check_gap` active (`src/feelies/ingestion/massive_normalizer.py:458`). | Correct asymmetry; offline strict gates should default safer. |
| Ordering | Single-symbol REST sorts by `(sip_timestamp, type_rank, sequence_number)` (`src/feelies/ingestion/massive_ingestor.py:419`). Multi-symbol finalizes through `resequence_event_list` (`src/feelies/ingestion/massive_ingestor.py:272`). | `ReplayFeed` re-checks canonical key (`src/feelies/ingestion/replay_feed.py:90`). | Arrival order is accepted in live logs (`src/feelies/storage/memory_event_log.py:48`). | Pass; forensic replay must resequence live logs before use. |
| Clock | REST `received_ns` from injected clock (`src/feelies/ingestion/massive_ingestor.py:433`). | Visibility time = exchange timestamp + configured latency (`src/feelies/ingestion/replay_feed.py:29`). | `received_ns` from live clock per frame (`src/feelies/ingestion/massive_ws.py:382`). | Pass, with documented semantics difference. |
| Latency | No latency injection during ingest. | `market_data_latency_ns` enters `ReplayFeed`; fill latency enters routers (`src/feelies/bootstrap.py:475`, `src/feelies/execution/backtest_backend.py:96`). Defaults are 20 ms / 50 ms (`src/feelies/core/platform_config.py:35`). | Live wall-clock receipt, no artificial data latency. | Pass; prompt concern that default is 0 is stale for `PlatformConfig`. |
| Health gate | Normalizer health becomes per-day `ingestion_health` (`src/feelies/harness/backtest_runner.py:393`). | Optional fail-closed manifest/terminal health gates. | Normalizer gates tick/trade processing (`src/feelies/kernel/orchestrator.py:6445`). | Partial due DI-01/DI-03/DI-04. |
| Idle behavior | n/a | Replay never yields `IdleTick` (`src/feelies/execution/backend.py:40`). | Queue timeout yields `IdleTick` to drain async fills (`src/feelies/ingestion/massive_ws.py:101`). | Intentional live-only control signal. |

## 6. Ordering & Causality Deep-Dive

The canonical merge key is implemented exactly as the prompt describes:
`(exchange_timestamp_ns, symbol, quote-before-trade, prior_sequence)`
(`src/feelies/storage/event_resequence.py:33`). `resequence_event_list()` sorts
by this key and rebuilds contiguous sequences/correlation IDs
(`src/feelies/storage/event_resequence.py:46`).

Merge points:

| Merge point | Behavior |
|-------------|----------|
| `MassiveHistoricalIngestor.ingest_symbol_parallel()` | Downloads quotes/trades in parallel, sorts one symbol/day by SIP timestamp, type rank, sequence number, then normalizes sequentially (`src/feelies/ingestion/massive_ingestor.py:352`, `src/feelies/ingestion/massive_ingestor.py:419`). |
| `MassiveHistoricalIngestor.ingest()` multi-symbol | Accumulates multi-symbol output into an order-tolerant scratch log, then merges destination + scratch and calls `resequence_event_list()` + `replace_events()` (`src/feelies/ingestion/massive_ingestor.py:208`, `src/feelies/ingestion/massive_ingestor.py:272`). |
| Standard backtest CLI | Combines cache hits and API misses, then globally resequences before building the replay log (`src/feelies/harness/backtest_runner.py:330`, `src/feelies/harness/backtest_runner.py:424`). |
| Cache-only replay | Loads all requested symbol/day files, globally resequences, and append-batches (`src/feelies/storage/cache_replay.py:96`, `src/feelies/storage/cache_replay.py:125`). |
| RTH filter prep | If filtering, writes kept events to a fresh strict log via `append_batch()` (`src/feelies/harness/backtest_prep.py:173`). |
| `InMemoryEventLog` | `append_batch()` and `replace_events()` stabilize market rows within a batch and enforce monotonic keys against prior rows (`src/feelies/storage/memory_event_log.py:86`, `src/feelies/storage/memory_event_log.py:94`). |
| `ReplayFeed` | Re-checks every market event from `EventLog.replay()` and raises `CausalityViolation` on backward keys (`src/feelies/ingestion/replay_feed.py:84`). |

Equal `exchange_timestamp_ns` semantics are deterministic but not micro-batched:
quotes sort before trades, then symbols, then prior sequence. This matches the
backtest-engine skill’s stated “micro-batching design target not implemented”
model.

Anti-lookahead path:

1. `ReplayFeed.events()` sets `SimulatedClock` to visibility time before yielding
   (`src/feelies/ingestion/replay_feed.py:100`).
2. Orchestrator consumes the yielded event through the same market-data protocol
   (`src/feelies/kernel/orchestrator.py:1763`).
3. Quote processing publishes the quote only after M1 and event-log handling
   (`src/feelies/kernel/orchestrator.py:2286`).
4. Sensors/signals see the event after visibility time because the simulated
   clock was advanced before the event left `ReplayFeed`.

## 7. Storage & Cache Integrity

`DiskEventCache` is normalized-event storage, not raw-vendor storage. This now
matches the data-engineering skill’s current invariant: raw-vendor archival is
not part of the current contract.

Strengths:

| Area | Evidence |
|------|----------|
| Schema invalidation | `_compute_schema_hash()` includes dataclass fields plus `_CACHE_SEMANTIC_VERSION` (`src/feelies/storage/disk_event_cache.py:53`). |
| Corrupt cache rejection | `load()` rejects schema mismatch, checksum mismatch, gzip/deserialize failure, and event-count mismatch (`src/feelies/storage/disk_event_cache.py:134`, `src/feelies/storage/disk_event_cache.py:146`, `src/feelies/storage/disk_event_cache.py:157`, `src/feelies/storage/disk_event_cache.py:175`). |
| Atomic writes | Data and manifest write temp files then `os.replace()` (`src/feelies/storage/disk_event_cache.py:232`, `src/feelies/storage/disk_event_cache.py:252`). |
| Round-trip fidelity | `JsonLineEventSerializer` preserves Decimal strings and tuple/list conversion (`src/feelies/core/serialization.py:55`, `src/feelies/core/serialization.py:115`), and `DiskEventCache` uses the shared serializer (`src/feelies/storage/disk_event_cache.py:43`, `src/feelies/storage/disk_event_cache.py:222`). |
| Manifest provenance | Manifest records symbol/date/counts/checksum/schema hash/normalizer version/created_at/ingestion_health (`src/feelies/storage/disk_event_cache.py:238`). |

Fragile areas:

| Area | Assessment |
|------|------------|
| Unhealthy manifests | Load succeeds if bytes/schema/counts are valid; health enforcement is optional (`src/feelies/storage/cache_replay.py:108`). |
| Raw auditability | There is no immutable raw-frame archive; re-normalization under a new parser requires re-hitting REST or relying on vendor availability. |
| `normalizer_version` | Persisted but not enforced on load (DI-06). |
| Feature snapshots | In-memory snapshot store verifies checksums, but accepts stored checksums as short as 8 hex chars (`src/feelies/storage/memory_feature_snapshot.py:13`). This is acceptable for a volatile test/development store but not a durable provenance standard. |

## 8. Test Coverage Map

Targeted command run:

```bash
uv run pytest tests/ingestion/ tests/storage/test_memory_event_log.py \
  tests/storage/test_disk_event_cache.py tests/storage/test_cache_replay.py \
  tests/causality/test_anti_lookahead.py -q
```

Result: **178 passed, 4 skipped in 44.01s**.

| Behavior | Coverage |
|----------|----------|
| REST/WS normalizer parsing, dedup, gap, halt, timestamp, condition parity | Covered by `tests/ingestion/test_massive_normalizer.py` and `tests/ingestion/test_rest_ws_parity.py`. |
| Multi-symbol/multi-day resequence and correlation-id rebuild | Covered by `tests/ingestion/test_resequence_fidelity.py`, `tests/storage/test_event_resequence.py`, and ingestor tests. |
| `ReplayFeed` causality and visibility-time clock behavior | Covered by `tests/ingestion/test_replay_feed.py` and `tests/causality/test_anti_lookahead.py`. |
| `InMemoryEventLog` append/append_batch/replace ordering | Covered by `tests/storage/test_memory_event_log.py`. |
| Disk cache checksum/schema/count/round-trip | Covered by `tests/storage/test_disk_event_cache.py`. |
| Cache-only replay health gate | Covered by `tests/storage/test_cache_replay.py`. |
| Massive functional network behavior | Present but skipped without API/vendor conditions in `tests/ingestion/test_massive_functional.py`. |
| Live WS overflow | Covered for non-blocking drop/log only (`tests/ingestion/test_massive_normalizer.py:762`). Missing health/degrade integration. |
| Partial WS subscription channel coverage | Missing. |
| Rejected bad/gappy event forensic logging | Missing. |
| Trade-condition eligibility / irregular-print filtering | Missing; current tests cover preservation/parity, not whether consumers should ignore irregular prints. |
| Normalizer-version cache invalidation | Missing. |
| Default backtest behavior on non-HEALTHY day metadata | Partial; strict gates covered, default warning/replay should be pinned. |

Determinism tests likely to break if ordering semantics change:
`tests/determinism/test_parity_manifest.py`, `test_sensor_reading_replay.py`,
`test_horizon_tick_replay.py`, `test_signal_replay.py`,
`test_horizon_feature_snapshot_replay.py`, `test_sized_intent_replay.py`,
`test_portfolio_order_replay.py`, `test_hazard_exit_replay.py`,
`test_regime_hazard_replay.py`, `test_regime_state_replay.py`, and
`test_market_fill_replay.py`. These hash downstream streams and depend on the
canonical quote/trade order.

## 9. Prioritized Remediation Roadmap

1. **DI-01: Fail closed on unhealthy ingestion metadata by default.**
   Add tests for standard `feelies backtest` with `ingestion_health=GAP_DETECTED`
   and `CORRUPTED`: default should fail unless an explicit waiver is present.
2. **DI-02 / DI-03: Integrate live-feed loss and partial subscriptions into
   DataHealth.** Add channel-level subscription tracking and tests for missing
   `Q.<sym>` / `T.<sym>` confirmations, queue overflow, and subsequent macro
   behavior.
3. **DI-04 / DI-05: Add a rejected-event/raw-frame audit sink.** Keep trading
   fail-safe, but persist enough evidence to replay or explain the exact event
   that caused a data-health block.
4. **DI-06: Enforce normalizer semantic version in cache load.** Add tests for
   manifest `normalizer_version` mismatch and document whether mismatch warns or
   invalidates.
5. **DI-07: Remove deterministic wall-clock fallbacks from backtest paths.**
   Pass clocks into `DiskEventCache` in harnesses and require `session_open_ns`
   when factor loadings are configured.
6. **DI-08: Centralize factor/sector reference loaders.** Move schema/freshness
   rules into `storage/reference` and have consumers call those loaders.
7. **DI-09: Decide and test trade-condition eligibility.** If all prints are
   intentionally passed through, document that ownership sits downstream; if not,
   add a shared eligibility classifier and parity tests for REST and WS records.
