# Data Ingestion / Replay / Storage Audit — 2026-06-11

**Scope:** raw vendor messages → `MassiveNormalizer` → `EventLog` → `ReplayFeed`
→ orchestrator `_process_tick` / `_process_trade`. Storage (`EventLog`,
`DiskEventCache`, `cache_replay`, resequencing) and live feed (`MassiveLiveFeed`).
**Mode:** read-only, evidence-based. No fixes applied.
**Auditor:** quantitative systems / data-pipeline audit pass.
**Verdict:** **No P0 found.** Ingestion is rigorous: typed boundary, complete
fingerprints, fail-safe cache, deterministic resequence, BT-17 latency wiring,
and anti-lookahead guards on the replay path are all present and tested. The
sharpest issues are a **P1 live-parity/robustness gap** (the replay-grade
EventLog ordering guard is applied to arrival-ordered live appends) and a
**P1 latent sort-key inconsistency** in the single-symbol ingest path.

---

## 1. Remediation status

Read-only audit — no code changes made. No trivial doc fixes applied (skill/doc
drift is catalogued in §2 / Findings rather than edited, to keep this pass
non-mutating).

| ID | Status | Commit |
|----|--------|--------|
| — | (none — read-only) | — |

---

## 2. Executive summary (most severe first)

1. **[P1] Live/paper M1 `EventLog.append` enforces replay-grade exchange-time
   monotonicity against *arrival-ordered* data.** In PAPER/LIVE,
   `_events_prelogged` stays `False`, so the orchestrator appends every inbound
   quote/trade to `InMemoryEventLog` at M1 (`orchestrator.py:2142-2143`,
   `:1683-1684`). `InMemoryEventLog.append` → `_enforce_market_order` raises
   `CausalityViolation` whenever the new event's `event_merge_sort_key` is less
   than the previous one (`memory_event_log.py:92-103`). Across symbols (and even
   a single symbol fed from multiple exchanges/SIP), live quotes routinely arrive
   with non-monotonic `exchange_timestamp_ns`, which would trip the guard and
   crash the pipeline to `DEGRADED`. This is fail-safe (a crash, not silent
   corruption) and live is explicitly "not yet production-hardened" per the
   data-engineering skill — hence P1 not P0 — but it is a real backtest↔live
   parity defect: the same guard that is correct for the pre-sorted replay stream
   is hostile to the live stream.

2. **[P1] Single-symbol ingest pre-sort key ≠ canonical merge key.** The
   historical ingestor sorts raw rows by `(sip_timestamp, sequence_number,
   type_rank)` (`massive_ingestor.py:359-365`), but the canonical key is
   `(exchange_timestamp_ns, symbol, type_rank, sequence)`
   (`event_resequence.py:31-41`) — `type_rank` and `sequence` precedence are
   swapped. For a single-symbol direct ingest (`len(symbols)==1` skips
   `replace_events`, `massive_ingestor.py:245`), a run of same-nanosecond
   quote/trade rows split across a 5 000-row chunk boundary could yield a backward
   canonical key across the boundary and raise `CausalityViolation` during
   `append_batch`. Per-chunk stabilization (`memory_event_log.py:54-67`) and the
   harness's global `resequence_event_list` (`backtest_runner.py:424`) paper over
   it in practice, so real-world impact is low; it is a latent inconsistency, not
   an active bug.

3. **[P2 / parity] Backtest replay runs with `normalizer=None`, so the
   `DataHealth` gate is inert.** `_data_health_blocks_trading` short-circuits on
   `self._normalizer is None` (`orchestrator.py:5978-5979`). Backtest never
   constructs a normalizer (only PAPER/LIVE do, `bootstrap.py:448-457`), so
   CORRUPTED/GAP/HALTED → DEGRADED escalation that protects live is absent in
   backtest. Backtest instead relies on `DiskEventCache` checksums + optional
   `require_healthy_disk_cache_manifests` / `backtest_enforce_ingest_terminal_health`.
   Documented in the skill, but a genuine parity asymmetry worth surfacing.

4. **[P2 / Inv-10] Cache manifest `created_at` uses raw wall clock.**
   `disk_event_cache.py:270` calls `time.strftime(..., time.gmtime())` rather
   than the injected `Clock`. Provenance-only field; not read by replay and not
   part of the schema hash/checksum, so determinism is unaffected — but it is the
   single raw wall-clock read in the ingestion/storage core.

5. **[P2 / doc drift] `EventSerializer` protocol exists but is unimplemented;
   disk cache uses ad-hoc `_event_to_dict` / `_dict_to_event`.**
   `core/serialization.py` defines the Protocol (bit-determinism, type/Decimal
   fidelity) but no concrete impl exists; the cache round-trips via
   `disk_event_cache.py:57-107`. Accurately disclosed by the skill — a documented
   limitation, listed for completeness.

6. **[P2 / doc drift] No immutable raw vendor log.** `EventLog` /
   `DiskEventCache` store *normalized* canonical events, not raw frames. The
   data-engineering skill's "Storage Design" table (raw-immutable = `EventLog`)
   contradicts the same skill's Invariant 1 ("not raw vendor frames"). The
   replay-from-raw guarantee in "Recovery & Replay" is therefore not literally
   achievable — re-deriving canonical events under a new normalizer requires
   re-hitting the REST API.

7. **[INFO / resolved] The skill's known multi-symbol ordering risk is STALE.**
   `backtest-engine`/`data-engineering` flag `scripts/run_backtest.py` as
   concatenating per-symbol streams without a global timestamp sort. Current code
   resequences globally in **both** API ingest (`backtest_runner.py:424`) and
   cache replay (`cache_replay.py:125`), and `ReplayFeed` + `InMemoryEventLog`
   both defend the invariant. The risk is closed; the skill text should be
   updated.

8. **[INFO] 3 ingestion tests fail in this environment only** because the
   `massive` vendor SDK is not installed (they `patch("massive.RESTClient")`).
   Not code defects — see §9.

---

## 3. Architecture trace

```
            ┌─────────────────────── EXTERNAL (untyped) ───────────────────────┐
            │                                                                   │
  REST /v3/quotes,/v3/trades                         WS Q.* / T.* frames
            │                                                   │
            ▼                                                   ▼
  MassiveHistoricalIngestor                          MassiveLiveFeed (bg thread,
  (_download_raw, parallel q/t,                       asyncio, bounded queue 100k,
   per-thread clients, merge-sort                     reconnect backoff 1→60s,
   by (sip_ts,seq,type_rank))                         overflow→drop+counter)
            │   raw dict → json.dumps                            │ raw bytes
            ▼                                                    ▼
        ┌──────────────────────  MassiveNormalizer.on_message  ───────────────────┐
        │  source="massive_rest"            │            source="massive_ws"       │
        │  parse → validate price/size      │  ms→ns coerce, ts-range guard,       │
        │  (NaN/Inf/neg reject)             │  dedup by (sym,feed,seq,fingerprint),│
        │  fingerprint dedup / seq-reuse→CORRUPTED, gap (WS; REST opt-in),         │
        │  halt on/off (BT-5), correlation_id @ boundary, internal sequence        │
        └──────────────────────────────┬──────────────────────────────────────────┘
                                        │ typed NBBOQuote | Trade
                 ┌──────────────────────┴───────────────────────┐
                 ▼ (backfill)                                    ▼ (live)
        EventLog.append_batch ──► [multi-symbol]         queue.Queue ─► events()
                 │               resequence_event_list           │  (+ IdleTick on
                 │               replace_events                   │   1s timeout)
                 ▼                                                ▼
        DiskEventCache.save (per sym/day JSONL.gz + manifest:           │
          checksum, event_schema_hash, _CACHE_SEMANTIC_VERSION,         │
          counts, ingestion_health, created_at)                         │
                 │ load: checksum+schema+count verify, else None→API    │
                 ▼ (cache_replay: merge all days+syms → resequence)     │
        InMemoryEventLog (append/append_batch/replace_events            │
          all run _stabilize_market_slice + _enforce_market_order)      │
                 │                                                       │
                 ▼ ReplayFeed.events()                                  │
        - filters NBBOQuote|Trade                                       │
        - re-checks event_merge_sort_key monotonic → CausalityViolation │
        - SimulatedClock.set_time(exchange_ts + market_data_latency_ns) │
          (BT-17 visibility time, monotonic)                            │
                 │                                                       │
                 └───────────────► ExecutionBackend.market_data ◄────────┘
                                          │ events()
                                          ▼
                            Orchestrator._run_pipeline
                   NBBOQuote → _process_tick → M1 append(quote)*  → M2 … SENSOR_UPDATE …
                   Trade     → _process_trade → append(trade)*    → bus.publish
                   IdleTick  → async fill drain only (never logged)
                   (* append skipped in backtest: _events_prelogged=True)
```

---

## 4. Invariant compliance matrix

| Invariant | Verdict | Evidence |
|-----------|---------|----------|
| **Inv-5 — Deterministic replay** | **PASS** | `resequence_event_list` assigns contiguous `sequence` + deterministic `correlation_id` (`event_resequence.py:44-62`); `replay()` is sequence-ordered (`memory_event_log.py:105-124`); cache round-trips Decimal→str and tuple→list losslessly (`disk_event_cache.py:57-107`); `tests/determinism/*` parity hashes depend on this order; `tests/storage/test_event_resequence.py` locks order-independence. |
| **Inv-6 — Causality** | **PASS (replay) / PARTIAL (live)** | Replay: `ReplayFeed.events()` raises `CausalityViolation` on backward merge-key (`replay_feed.py:90-99`); `InMemoryEventLog._enforce_market_order` defends at insert (`memory_event_log.py:92-103`); BT-17 visibility-time gating (`replay_feed.py:100-108`); `tests/causality/test_anti_lookahead.py` (7 cases incl. fill-at-T immune to appended future quote, boundary snapshot excludes early-processed future reading). Live: the same guard is mis-applied to arrival order (Finding ING-01). |
| **Inv-9 — Backtest/live parity** | **PARTIAL** | Same `_process_tick`/`_process_trade` for all modes; `_events_prelogged` cleanly avoids double-append on replay (`orchestrator.py:1311`). Gaps: (a) backtest `normalizer=None` ⇒ DataHealth gate inert vs live (Finding ING-03); (b) M1 append guard asymmetry (Finding ING-01); (c) `received_ns` semantics differ by clock (documented in skill Inv-4). |
| **Inv-10 — Clock abstraction** | **PASS (1 carve-out)** | Normalizer uses injected `Clock` for `received_ns` and the ts-range heuristic (`massive_normalizer.py:757`); ReplayFeed/routers use `SimulatedClock`; no `datetime.now()`/`time.time()` in core paths. Carve-out: cache `created_at` via `time.gmtime()` (`disk_event_cache.py:270`, Finding ING-04) — provenance only. |
| **Inv-11 — Fail-safe default** | **PASS** | Cache `load()` returns `None` on unreadable manifest, schema mismatch, checksum mismatch, deserialize error, or count mismatch → caller falls through to API (`disk_event_cache.py:149-219`); `CORRUPTED` is terminal → macro DEGRADED + force-flatten (`orchestrator.py:5995-6010`); WS overflow drops with counter, never blocks reader (`massive_ws.py:388-396`); partial REST pagination refuses checkpoint + refuses to normalize (`massive_ingestor.py:330-341`); oversized/recursive frames dropped pre-`json.loads` (`massive_normalizer.py:313-326`). |
| **Inv-13 — Provenance** | **PARTIAL** | `correlation_id` + internal `sequence` assigned at boundary (`massive_normalizer.py:461,529,643,707`); manifest persists source/health/checksum/schema_hash/counts/created_at (`disk_event_cache.py:262-273`); `IngestDayMeta` carries source+health (`cache_replay.py:34-43`). Gaps: no raw vendor log (Finding ING-06); `EventSerializer` unimplemented (Finding ING-05); manifest lacks a normalizer/code version tag beyond the dataclass-derived `event_schema_hash`. |

---

## 5. Findings table

| ID | Sev | Effort | Component | Finding | Evidence | Recommendation | Test gap? |
|----|-----|--------|-----------|---------|----------|----------------|-----------|
| ING-01 | **P1** | M | orchestrator / memory_event_log | Live/paper M1 append enforces replay-grade exchange-time monotonicity on arrival-ordered data → `CausalityViolation` crash to DEGRADED on normal cross-symbol/cross-exchange out-of-order arrivals | `orchestrator.py:2142-2143`, `:1683-1684`; `memory_event_log.py:49-52,92-103`; `run_paper`/`run_live` never set `_events_prelogged` (`orchestrator.py:1329-1394`) | Decouple the live-append path from the replay monotonicity guard: either tolerate bounded out-of-order on append (append-as-arrived, sort only on replay/resequence) or gate the guard behind `_events_prelogged is False ⇒ relaxed`. Preserve the strict guard for ingest/replace_events. | **Yes** — no multi-symbol live/paper append-order test |
| ING-02 | **P1** | S | massive_ingestor | Raw pre-sort key `(sip_timestamp, sequence_number, type_rank)` swaps `type_rank`/`sequence` precedence vs canonical `event_merge_sort_key` `(ts, symbol, type_rank, sequence)`; single-symbol direct ingest could raise `CausalityViolation` at a same-ns chunk boundary | `massive_ingestor.py:359-365` vs `event_resequence.py:31-41`; chunk size `_CHUNK_SIZE=5000` (`:42`) | Align the raw sort with the canonical key (sort quotes-before-trades before sequence) or always route single-symbol ingest through `resequence_event_list` before persisting | **Yes** — no >5000 same-ns chunk-boundary test |
| ING-03 | P2 | M | orchestrator / bootstrap | Backtest replay has `normalizer=None`; DataHealth CORRUPTED/GAP/HALTED → DEGRADED gating is inert in backtest, present only in PAPER/LIVE | `orchestrator.py:5978-5979`; `bootstrap.py:448-457` | Document explicitly as designed; consider a replay-time health gate driven off cached `ingestion_health` (already plumbed via `backtest_enforce_ingest_terminal_health`) for tighter parity | Partial (manifest-health gates tested elsewhere) |
| ING-04 | P2 | S | disk_event_cache | Manifest `created_at` uses `time.gmtime()` (raw wall clock) outside injected Clock | `disk_event_cache.py:270` | Inject a clock or stamp via provenance helper; or document the Inv-10 carve-out inline | No |
| ING-05 | P2 | M | serialization / disk_event_cache | `EventSerializer` protocol defined but unimplemented; cache uses ad-hoc dict helpers; bit-determinism not protocol-guaranteed | `core/serialization.py`; `disk_event_cache.py:57-107` | Implement a concrete bit-deterministic serializer and route the cache through it; add round-trip property test | Partial (round-trip covered functionally, not bit-equality) |
| ING-06 | P2 | L | storage design | No immutable raw vendor log; skill "Storage Design" table contradicts skill Inv-1 | data-engineering SKILL.md lines 39 vs 274-280 | Reconcile skill text; if raw archival is desired, add a raw-frame sink in `MassiveLiveFeed._consume` / ingestor | n/a (doc) |
| ING-07 | P2 | S | skills | Stale "no global multi-symbol sort" risk in skills; code resequences globally | `backtest_runner.py:424`; `cache_replay.py:125` | Update both skills to mark the risk resolved and cite the resequence call sites | n/a (doc) |
| ING-08 | P2 | S | massive_normalizer | `enable_rest_sequence_gap_detection` toggles gap detection for **both** quote and trade channels globally; no per-channel granularity for partially-contiguous REST feeds | `massive_normalizer.py:640-641,703-704` | Acceptable as documented; note the all-or-nothing semantics | No |
| ING-09 | INFO | S | tests / env | 3 `test_massive_ingestor.py` cases fail only because `massive` SDK absent (they patch `massive.RESTClient`) | run log §9 | Mark these `@pytest.mark.massive` / skip-if-absent so a clean checkout reports green without the vendor extra | n/a |

---

## 6. Live vs replay vs backfill parity

| Dimension | Backfill (REST → EventLog) | Replay (EventLog → ReplayFeed) | Live (WS → orchestrator) | Parity note |
|-----------|---------------------------|-------------------------------|--------------------------|-------------|
| Boundary | `MassiveNormalizer` (`massive_rest`) | none (already normalized) | `MassiveNormalizer` (`massive_ws`) | Both live paths go through the single boundary; replay trusts the persisted stream ✔ |
| `correlation_id`/`sequence` | reassigned by `resequence_event_list` | as persisted | assigned per-frame in arrival order | **Intentionally divergent**, documented (`event_resequence.py:15-18`) ✔ |
| Gap detection | REST off by default (thinned SIP) | n/a | WS on (`_check_gap`) | Correct asymmetry per skill ✔ |
| Timestamp source | `sip_timestamp` (ns), no range guard | persisted `exchange_timestamp_ns` | `t` (ms→ns), range guard active | Range guard inert on REST/SimulatedClock by design (`massive_normalizer.py:596-611,757-758`) ✔ |
| Clock / latency | `SimulatedClock` does not advance during ingest (`received_ns` constant per batch) | `SimulatedClock` advanced to visibility time (BT-17) | `WallClock` per-frame `received_ns` | Documented `received_ns` semantics (skill Inv-4) ✔ |
| DataHealth gate | drives manifest `ingestion_health` | **inert (`normalizer=None`)** | active → DEGRADED on CORRUPTED | **Gap** (Finding ING-03) ⚠ |
| EventLog append | batch, stabilized + monotonic guard | n/a (read) | per-event, **monotonic guard on arrival order** | **Gap** (Finding ING-01) ⚠ |
| `_events_prelogged` | n/a | `True` (no re-append) | `False` (append each) | Correct: replay must not double-log; live must log ✔ |

---

## 7. Ordering & causality deep-dive

**Canonical sort key** (`event_resequence.py:31-41`):
`(exchange_timestamp_ns, symbol, type_rank, sequence)` with `type_rank`
`NBBOQuote=0 < Trade=1`. Quotes precede trades at equal exchange time; symbol is
the secondary tie-break; `prior_sequence` (the pre-reassignment sequence)
preserves intra-batch order. Applied at every merge point below.

**Resequence / replace_events / append call graph:**

- `resequence_event_list` (sorts + assigns fresh seq/cid):
  - `backtest_runner.ingest_data:424` — global, all symbols × days (API path) ✔
  - `cache_replay.load_event_log_from_disk_cache:125` — global (cache path) ✔
  - `massive_ingestor.ingest:246-250` — multi-symbol only, via `replace_events` ✔
- `replace_events` (`memory_event_log.py:76-91`) — resets watermark, restabilizes,
  re-checks monotonicity. Only multi-symbol ingest. ✔ (`test_resequence_fidelity.py:138`)
- `append_batch` (`memory_event_log.py:68-75`) — `_stabilize_market_slice`
  (per-batch canonical re-sort) then per-event monotonic guard. Used by ingestor
  chunks, cache replay, RTH-filter rebuild (`backtest_prep.py:174-176`). ✔
- `append` (single) — orchestrator M1/`_process_trade`. **Strict guard, no
  stabilization** — correct for pre-sorted replay, fragile for live (ING-01).

**Merge points** (where independent streams combine):
1. Quote+trade streams within one symbol/day — `massive_ingestor.py:357-365`
   (raw sort — see ING-02 key mismatch).
2. All days/symbols into the run log — `backtest_runner.py:422-427` /
   `cache_replay.py:114-127` (global resequence). ✔
3. RTH-filter rebuild — `backtest_prep.py:153-176` (preserves resequenced order;
   filters out-of-RTH rows). ✔

**Equal-timestamp micro-batch semantics:** at equal `exchange_timestamp_ns`,
order is quote→trade, then by symbol, then by pre-reassignment sequence. Stable
(`sorted` is stable; key is total within a batch). Tested:
`test_event_resequence.py:50-58`, `test_replay_feed.py:164-186`,
`test_resequence_fidelity.py:95`.

**`ReplayFeed` responsibility split:** the caller (resequence/ingest) must
pre-sort; `ReplayFeed` and `InMemoryEventLog` both *defend* the invariant by
raising `CausalityViolation` rather than silently reordering. No production call
site replays an unsorted log — every path that reaches `ReplayFeed` has been
through `resequence_event_list` or `append_batch` stabilization. ✔

**BT-17 visibility:** clock advances only forward (`replay_feed.py:106`
`if visible_ns > now`), so equal/earlier visibility times never move time
backward. Anti-lookahead trace: a quote at exchange time T becomes visible at
`T + market_data_latency_ns`; the orchestrator's decision clock is at visibility
time when M1→SENSOR_UPDATE runs, so no sensor/feature can read T before
`T + latency`. Verified by `tests/acceptance/test_bt17_market_data_latency.py:51-86`
and `tests/causality/test_anti_lookahead.py:297` (boundary snapshot excludes a
future reading processed early). Market-data latency (decision clock) and
fill/submit latency (`backtest_fill_latency_ns`, deferred inside routers) are
independent legs — no double-counting.

---

## 8. Storage & cache integrity

- **Serialization** (`disk_event_cache.py:57-107`): Decimal→`str`, tuple→`list`;
  reverse uses **substring** type matching (`"Decimal"`, `"tuple[int"`) so it is
  robust to `from __future__ import annotations` stringized types and to
  `| None` unions (`indicators: tuple[int, ...]` and `decimal_size: str | None`
  both map correctly). Round-trip preserves the *already-normalized* Decimal
  exactly (no float re-entry on reload). ✔
- **Checksums / schema** (`disk_event_cache.py:43-54,164-211`):
  `event_schema_hash` = sha256 over sorted dataclass field names+types +
  `_CACHE_SEMANTIC_VERSION` ("2"); `checksum` = sha256 of the gzip bytes;
  `event_count` cross-check. Any mismatch → `load` returns `None` → API fallback.
  Atomic writes via `.tmp` + `os.replace`, data-before-manifest ordering so a
  crash leaves `exists()==False`. ✔
- **Recovery protocol** (Inv-11): corrupt/stale/partial cache is *fail-closed to
  re-ingest*, never silently accepted. `require_healthy_disk_cache_manifests`
  additionally fails the run when any manifest `ingestion_health != HEALTHY`
  (`cache_replay.py:108-113`). ✔
- **Provenance gaps**: manifest captures source/health/checksum/schema/counts/
  created_at but **not** a normalizer code-version or git SHA; re-derivation under
  a future normalizer requires API re-hit (no raw log — ING-06). `created_at` is
  wall-clock (ING-04). `EventSerializer` bit-determinism is unenforced (ING-05).
- **`append`/`append_batch`/`replace_events` atomicity**: `InMemoryEventLog` is
  list-backed under a `threading.Lock`; `append_batch`/`replace_events` build and
  validate the slice before mutating, so a mid-batch `CausalityViolation` leaves
  the prior `_events`/watermark for `replace_events` only after `clear()` — note
  `replace_events` clears *after* the per-event guard loop
  (`memory_event_log.py:83-90`), so a bad input raises before any mutation. ✔

---

## 9. Test coverage map

Targeted run (this environment):

```
uv run --extra dev pytest tests/ingestion/ tests/storage/test_memory_event_log.py \
  tests/storage/test_disk_event_cache.py tests/storage/test_cache_replay.py \
  tests/causality/test_anti_lookahead.py -q
→ 151 passed, 18 skipped, 3 failed
```

The **3 failures are environment-only**: `test_massive_ingestor.py`
(`test_ingest_with_mocked_rest_client`, `test_ingest_delegates_to_parallel`,
`test_reports_duplicates_from_normalizer`) `patch("massive.RESTClient")`, which
raises `ModuleNotFoundError: No module named 'massive'` because the optional
vendor SDK is not installed. No code defect (Finding ING-09). The 18 skips
include the network-backed `test_massive_functional.py` (no `MASSIVE_API_KEY`).

| Behavior | Status | Where |
|----------|--------|-------|
| Multi-symbol global ordering | **Covered** | `test_resequence_fidelity.py:69-104`, `test_event_resequence.py` |
| Quote-before-trade at equal ts | Covered | `test_event_resequence.py:50`, `test_replay_feed.py:174`, `test_anti_lookahead.py:145` |
| Cache corruption / checksum / schema / count fallback | Covered | `test_disk_event_cache.py:125-175` |
| WS queue overflow / `events_dropped` | Covered | `test_massive_normalizer.py:724-801,1258` |
| BT-17 clock latency wiring | Covered | `test_bt17_market_data_latency.py:51-86`, `test_replay_feed.py:126` |
| `replace_events` watermark reset | Covered | `test_resequence_fidelity.py:138` |
| `append_batch` rejects backward / stabilizes intra-batch | Covered | `test_resequence_fidelity.py:117-123` |
| Sequence-reuse → CORRUPTED, dup filtering | Covered | `test_massive_normalizer.py`, `test_data_integrity.py` |
| Halt on/off (BT-5) DataHealth | Covered | `test_data_integrity.py` |
| Anti-lookahead (fill-at-T, prefix-ack, SSR/halt future) | Covered | `test_anti_lookahead.py:161-437` |
| Determinism / parity hashes vs event order | Covered | `tests/determinism/*` (e.g. `test_signal_replay.py`, `test_sensor_reading_replay.py`) |
| **Live/paper multi-symbol arrival-order append** | **Missing** | — (Finding ING-01) |
| **Single-symbol >5000 same-ns chunk boundary** | **Missing** | — (Finding ING-02) |
| **REST↔WS field parity (same logical event)** | **Partial** | per-side parse tested; no cross-source equivalence assertion |
| **EventSerializer bit-equality** | **Missing** | functional round-trip only |

**Determinism sensitivity:** the `tests/determinism/*` parity hashes are
ordering-sensitive by construction (they lock sequence allocation + emission
order). Any change to `event_merge_sort_key`, the resequence tie-break, or the
quote-before-trade rule would re-bake every Level-N parity hash — these tests are
the regression tripwire for §7 changes and must be updated deliberately, never
auto-rebaselined.

---

## 10. Prioritized remediation roadmap

**P1 — do first**

1. **ING-01 (live append guard).** Separate the live-append contract from the
   replay-ordering contract. Option A (preferred): in PAPER/LIVE, append events
   as-arrived without the strict monotonic guard, and rely on resequence at
   forensic-replay time; keep the strict guard for `append_batch`/
   `replace_events`/`ReplayFeed`. Option B: relax the single-`append` guard to a
   bounded out-of-order tolerance window. *Tests:* add a multi-symbol +
   multi-exchange arrival-order PAPER append test that today would throw; assert
   the live EventLog is forensically resequencable to the canonical order.

2. **ING-02 (ingest sort-key mismatch).** Change the raw pre-sort to
   `(sip_timestamp, type_rank, sequence_number)` (or always resequence
   single-symbol before persist). *Tests:* construct a single-symbol stream with
   >`_CHUNK_SIZE` events sharing one nanosecond timestamp interleaving quotes and
   trades; assert no `CausalityViolation` and canonical final order.

**P2 — parity & provenance hardening**

3. **ING-03**: document the backtest `normalizer=None` health-gate gap in the
   skill; optionally wire a replay-time health gate off cached `ingestion_health`.
4. **ING-05**: implement a concrete `EventSerializer` and route the disk cache
   through it; add a bit-equality property test (`serialize(deserialize(x))`).
5. **ING-06 / ING-07**: reconcile the data-engineering skill — mark the raw-log
   "Storage Design" row as aspirational and the multi-symbol-sort risk as
   resolved (cite `backtest_runner.py:424`, `cache_replay.py:125`).
6. **ING-04**: stamp manifest `created_at` from an injected clock/provenance
   helper; add a normalizer code-version field to the manifest for Inv-13.

**P2 — test hygiene**

7. **ING-09**: gate the 3 vendor-SDK tests behind a `massive`-present marker so a
   clean checkout is green without the extra; add an explicit REST↔WS field-parity
   test asserting a logically-identical quote normalizes to equal canonical fields
   from both sources.

---

### Appendix — audit-question quick answers

- **A1** All live paths go through `MassiveNormalizer.on_message`; replay reads
  pre-normalized events. No bypass.
- **A2** `correlation_id`/`sequence` assigned at the boundary via
  `make_correlation_id`; live vs resequenced backfill intentionally differ
  (documented `event_resequence.py:15-18`).
- **A3** REST gap detection off by default (thinned SIP), WS on;
  `enable_rest_sequence_gap_detection` flips REST globally (ING-08).
- **A4** Fingerprints include participant/TRF timestamps so a corrected retransmit
  with the same `sequence_number` → CORRUPTED, not silent dup
  (`massive_normalizer.py:163-203`).
- **A5** ms→ns coercion + range guard on WS; REST trusts `sip_timestamp`; no raw
  `datetime.now()` in core (one provenance carve-out, ING-04).
- **A6** Condition codes parsed on both sources; halt codes drive BT-5; no
  asymmetric condition filtering found.
- **A7** GAP_DETECTED→HEALTHY recovers on contiguous sequence; CORRUPTED is
  terminal (`data_integrity.py:37-59`); orchestrator degrades on CORRUPTED always,
  on GAP only when `degrade_on_data_gap` (`orchestrator.py:5995-6020`).
- **B1-B6** see §7. **C1-C5** see §7 + BT-17 (default latency is 20 ms md / 50 ms
  fill via `PlatformConfig`, not 0 — the `0` is only the bare constructor default;
  bootstrap always threads config). **D1-D6 / E1-E4 / F1-F3** see §6/§8.
