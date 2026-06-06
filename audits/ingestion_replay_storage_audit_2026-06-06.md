# Ingestion / Replay / Storage End-to-End Audit — 2026-06-06

Scope: market data ingestion, normalization, storage, replay, and the
backtest harness wiring that ties them together.

Tree audited: `origin/main` at `266df97` (post `8503310` BT-17 latency,
`cc07abd` BT-5 halt model, `0d70f9f` BT-18 raw-L1 / ex-date guard,
`d33a240` paper pipeline fixes, `fdea508` IB broker + paper backend +
idle-tick).

Audit modes used: contract review (skills + invariants), file-level
trace (every file in the scope inventory), call-graph trace for
`correlation_id` / `sequence` assignment and clock latency wiring,
targeted test run.

Test execution (recorded for evidence):

```
uv run pytest tests/ingestion/ tests/storage/test_memory_event_log.py \
  tests/storage/test_disk_event_cache.py tests/storage/test_cache_replay.py \
  tests/causality/test_anti_lookahead.py
  → 123 passed, 19 skipped (all marked "requires massive package" or live API)

uv run pytest tests/determinism/
  → 73 passed
```

Per Inv-5 reproducibility, both runs are deterministic on this tree.

Methodology summary:

- `Read` of every file under `src/feelies/ingestion/`,
  `src/feelies/storage/`, plus the integration files
  (`bootstrap.py`, `execution/backtest_backend.py`,
  `harness/backtest_runner.py`, `harness/backtest_prep.py`,
  `kernel/orchestrator.py` M1 path and DataHealth gate, the BT-5 halt
  controller, and `scripts/run_backtest.py`).
- `grep -n` cross-checks for every contract assertion: latency wiring,
  resequence call sites, normalizer construction, EventLog.append
  points, halt-handling parity.
- Findings carry `file:line` evidence.

Severity legend: **BLOCKER** (silent corruption / undelivered
contract) · **MAJOR** (real defect with plausible trigger) ·
**MINOR** (latent risk, observability, hardening).

The codebase has matured substantially since prior passes (passes 1–4
of `audits/2026-05-03-ingestion-robustness.md` are kept as
chronological record). Most of the BLOCKERs and many MAJORs identified
there are now closed. New surface area (BT-5 LULD halts, BT-17 latency
separation, multi-symbol global resequence, disk cache, paper backend,
ingestion-health propagation) introduces its own residuals.

---

## Executive summary

**Overall posture:** the ingestion / replay layer is now substantially
sound for backtest + paper paths. Three architectural improvements
deserve specific credit:

1. **BT-17 latency separation** is correctly wired end-to-end
   (`platform_config.py:36–37` defaults → `bootstrap.py:458, 894, 912`
   → `execution/backtest_backend.py:53–58, 115–120` →
   `replay_feed.py:60–66, 102–106`). Default is non-zero
   (`DEFAULT_MARKET_DATA_LATENCY_NS = 20_000_000` ns / 20 ms), avoiding
   the prior `0 ⇒ no causality buffer` failure mode.
2. **Multi-symbol global resequence** is enforced at every event-log
   construction site (`harness/backtest_runner.py:411`,
   `storage/cache_replay.py:129`,
   `ingestion/massive_ingestor.py:227–235`). The original concern that
   `scripts/run_backtest.py` could concatenate without a global sort
   no longer applies — that script is now a 81-line wrapper that
   delegates to `harness/backtest_runner.main`.
3. **`InMemoryEventLog` self-defends Inv-6** via `_enforce_market_order`
   (`memory_event_log.py:92–103`) and `_stabilize_market_slice`
   (`54–66`). Out-of-order market events raise `CausalityViolation`
   before they corrupt downstream state — both on `append()` and
   `append_batch()`. `ReplayFeed` re-checks the same invariant on the
   read side (`replay_feed.py:91–98`).

**Net residuals on this tree (count by severity):**

| | Active | Carry-over (open from pass 1–4) |
| --- | --- | --- |
| BLOCKER | 0 | 0 |
| MAJOR | 6 | 4 |
| MINOR | 9 | 6 |

**Backtest verdict: PASS with caveats.** The path is reproducible
(determinism suite 73/73), Inv-6 is enforced, BT-17 is wired. The
caveats: receipt-time semantics (`received_ns`) are populated but
batch-uniform in REST replay (B5 below); ingestion-health is surfaced
but the orchestrator gate ignores `HALTED` (A7 below).

**Live readiness verdict: PASS for paper, NOT YET for unattended
live.** Carry-over from prior passes that have actual fixes pending:
R3-INGEST-02 (Decimal `NaN`/`InvalidOperation` escapes the parser
catch — see C1) and R4-NEW-04 (silent thread death on out-of-catch
exceptions — see E1) together can still kill the live feed thread
without notifying the orchestrator. R3-INGEST-03 (sequence holes —
C2) is forensic, not safety-critical.

---

## A. Ingestion boundary integrity

### A1. Every market data path goes through `MassiveNormalizer` — **PASS**

REST: `MassiveHistoricalIngestor.ingest_symbol_parallel` calls
`self._normalizer.on_message(raw, received_ns, "massive_rest")` at
`massive_ingestor.py:334`. No other code in `src/feelies/ingestion/`
constructs `NBBOQuote`/`Trade` directly except inside the four normalizer
parse paths.

WS: `MassiveLiveFeed._consume` calls
`self._normalizer.on_message(raw_bytes, received_ns, "massive_ws")` at
`massive_ws.py:361`. Same contract.

Cache: `DiskEventCache.load` deserializes already-normalized events
(`disk_event_cache.py:74–92`) — by design they bypass the normalizer
because they were normalized once at the API path and the cache stores
the resulting `NBBOQuote`/`Trade`. Re-normalizing on every cache hit
would defeat the cache's purpose. Caching after normalization is
correct, but it does mean cache content provenance is "trust the prior
ingest's health" rather than "re-verify on load" — see A4 / D2.

Replay: `ReplayFeed` reads from `EventLog.replay()` and never invokes
the normalizer. Inv-9 holds because the orchestrator's M1 path
(`orchestrator.py:1748, 1832`) is identical in backtest and live: same
`_process_tick_inner`, same `_data_health_blocks_trading`, same bus
publish.

### A2. `correlation_id` / `sequence` assignment — **PASS with documented divergence**

Boundary assignment: `make_correlation_id(symbol, exchange_ts_ns,
internal_seq)` is called in all four normalizer parse paths
(`massive_normalizer.py:294, 359, 444, 499`). `SequenceGenerator` (now
starting at `1` per `massive_normalizer.py:183` to keep `sequence > 0`
a tautology downstream) is thread-safe via internal `threading.Lock`
(`core/identifiers.py:25–30`).

Live vs resequenced backfill: `storage/event_resequence.py:15–18`
documents explicitly that "this pass assigns fresh contiguous
`sequence` and `correlation_id` values for deterministic replay. Those
identifiers are not expected to match an incremental live ingest of
the same vendor events". Downstream code does not key off the
correlation_id for decisions — it is provenance only — so Inv-9 holds
at the decision-level.

The cache stores the *pre-resequence* `correlation_id` (per
`disk_event_cache.py:_event_to_dict`); `cache_replay.py:129` replaces
it via `resequence_event_list` after global merge. A consumer that
indexed the cache by correlation_id (none in tree) would see drift on
reload. Documented behaviour, not a defect.

### A3. REST vs WS gap detection — **PASS**

WS: `_check_gap` is unconditional in `_ws_quote` / `_ws_trade`
(`massive_normalizer.py:291, 356`).
REST: `_check_gap` is flag-gated behind
`_enable_rest_sequence_gap_detection`
(`massive_normalizer.py:440–441, 495–496`). Default `False` is set in
`__init__` (`203`) so thinned SIP historical rows don't spurious-fire.
The flag is surfaced through `harness/backtest_runner.ingest_data`
(line 303, 351) and `scripts/run_backtest.py` via the CLI wrapper.

Caveat: `_enable_rest_sequence_gap_detection=True` will fire `HEALTHY
→ GAP_DETECTED` on every historical thinned row, which then
`mark_done`'s a "completed (symbol, feed_type)" pair into the
checkpoint with the symbol marked `GAP_DETECTED` in the manifest.
Operators using the flag for experiments should know this lights up
the manifest health badge — see B1.

### A4. Dedup / sequence-reuse semantics — **PASS**

`_reject_sequence_reuse` (`massive_normalizer.py:560–594`) replaces
the old "match on seq alone" path. It now:

1. Skips when `seq_num == 0` (line 575–576) — **closes pass 3
   R3-INGEST-01** (silent dedup of seq-zero events).
2. Returns False when previous seq is also zero or differs (line
   581–582).
3. When sequence matches and **content fingerprint also matches**,
   counts as exact duplicate (line 583–585).
4. When sequence matches but **fingerprint differs**, logs warning
   and `_mark_corrupted(symbol, trigger="sequence_reuse_payload_mismatch")`
   (line 586–593).

Fingerprints cover every wire field that materially shapes a
canonical event:

- WS quote (`_fingerprint_ws_quote`, `62–89`): bp, ap, bs, as, bx, ax,
  z, conditions, indicators, participant_timestamp, trf_timestamp,
  ft, y.
- WS trade (`_fingerprint_ws_trade`, `92–108`): p, s, x, i, z,
  conditions, trfi, trft, participant_timestamp, ft, correction.
- REST quote (`_fingerprint_rest_quote`, `111–127`): bid_price,
  ask_price, bid_size, ask_size, bid_exchange, ask_exchange, tape,
  conditions, indicators.
- REST trade (`_fingerprint_rest_trade`, `130–144`): price, size,
  exchange, id, tape, conditions, trf_id, correction,
  participant_timestamp.

Minor gap (A4-MINOR): REST quote fingerprint omits
`participant_timestamp` and `trf_timestamp`, while WS quote
fingerprint includes both. A REST retransmission that only changes
the participant timestamp would be treated as exact-duplicate and
silently dropped. The omission may be intentional (SIP timestamp is
already in the dedup key indirectly), but the asymmetry deserves a
docstring note.

### A5. Timestamp normalization — **PASS**

Helper `_optional_wire_ts_ns` (`massive_normalizer.py:43–59`)
auto-detects ms vs ns: values above `10**16` are treated as ns,
otherwise multiplied by `10**6`. Used for `participant_timestamp`,
`ft`, `trf_timestamp`, and `y` fields. The threshold `10**16`
corresponds to ~1970-04-26 in ns and ~317k years in ms — a clean
demarcation.

No `datetime.now()` is used in core ingestion logic. Verified by
`grep -rn "datetime.now" src/feelies/ingestion/ src/feelies/storage/`
— two hits both in `disk_event_cache.py:255` for a *manifest*
`created_at` ISO string (provenance metadata, not for decision logic).
Inv-10 holds.

### A6. Trade conditions across REST + WS — **PASS**

Both paths thread `conditions` (and `indicators` on quotes) through
the same tuple-of-int materialization
(`massive_normalizer.py:296–303, 361–362, 446–447, 501–502`). REST
trade `decimal_size` (`523`) and WS trade `ds` (`388`) are passed
through as raw strings; the `Trade` schema documents
`decimal_size: str | None` so no precision is lost.

### A7. `DataHealth` SM — **MAJOR finding: orchestrator gate ignores `HALTED`**

The state model is now four states (`data_integrity.py:31–34`):
HEALTHY, GAP_DETECTED, HALTED, CORRUPTED. CORRUPTED is formally
terminal (line 52: `frozenset()`). The HALTED state is correctly
fed from `_apply_halt_status` (`massive_normalizer.py:639–665`)
using the shared `classify_halt_status` utility
(`data_integrity.py:63–83`).

`MassiveNormalizer.health(symbol)` aggregates per-feed-type machines
via `merge_worst_health` (`ingest_health.py:27–31`), so a HALTED
trade-feed correctly bubbles up.

**The orchestrator's `_data_health_blocks_trading`
(`orchestrator.py:5093–5147`) gates only `CORRUPTED` (line 5119) and
`GAP_DETECTED` (line 5134).** A HALTED symbol returns False from the
gate. The orchestrator does its own halt tracking via
`_halted_symbols` (a `set[str]` populated by `_update_halt_state` at
`orchestrator.py:4944–4980`), and the M1 path skips ticks when
`quote.symbol in self._halted_symbols` (line 1921).

Net effect: HALTED is handled by **two parallel mechanisms** that
must stay in sync. Today they share the same condition-code utility
(`classify_halt_status`), so they emit identical signals from the
same trade tape. But the two side effects are decoupled:

- Normalizer-side HALTED appears in `normalizer.all_health()` and in
  the disk cache manifest's `ingestion_health` field.
- Orchestrator-side `_halted_symbols` drives the actual gating.

**Drift scenarios that would expose this:**

1. A code change to one halt path without the other (e.g., adding
   sub-second hysteresis to one side).
2. A `received_ns`-vs-`exchange_ts` ordering subtlety where the
   normalizer transitions on a trade but the orchestrator hasn't yet
   processed it (e.g., trade in flight on the bus).
3. An operator command that resets one side without the other.

**Severity: MAJOR.** Document the duality explicitly, or unify by
making `_data_health_blocks_trading` look up HALTED and let the
normalizer be the single source of truth.

---

## B. Deterministic ordering & resequencing (Inv-5 / Inv-6)

### B1. Canonical sort key applied everywhere — **PASS**

`event_merge_sort_key` (`storage/event_resequence.py:31–41`) returns
`(exchange_timestamp_ns, symbol, type_rank, sequence)` with quotes
ranked 0 and trades ranked 1. Call sites:

- `harness/backtest_runner.py:411` (post-ingest global resequence).
- `storage/cache_replay.py:129` (post-cache-load global resequence).
- `ingestion/massive_ingestor.py:227–235` (multi-symbol post-pass
  resequence inside `ingest()`).
- `storage/memory_event_log.py:21` (stabilization + invariant check).
- `ingestion/replay_feed.py:26, 90` (read-side invariant check).

The `_stabilize_market_slice` helper
(`memory_event_log.py:54–66`) re-sorts the in-batch market subset in
place by `event_merge_sort_key` before the monotonicity check, so a
caller that hands `append_batch` a *locally* out-of-order quote/trade
pair gets normalized rather than rejected. Non-market events in the
same batch keep their position. Documented at line 55.

### B2. `scripts/run_backtest.py` concatenation risk — **CLOSED**

`scripts/run_backtest.py` is now 81 lines (line count via `wc -l`),
all of which are imports + a `__main__` block delegating to
`harness.backtest_runner.main`. The historic concern that this script
might concatenate per-symbol event lists without a global merge sort
no longer applies — the actual ingest path is the harness function,
which calls `resequence_event_list` (`backtest_runner.py:411`).

### B3. Single-symbol ordering + parallel race — **PASS**

`ingest_symbol_parallel` (`massive_ingestor.py:247–348`) downloads
quotes and trades in parallel threads but resolves both futures
before merging. The merge is a deterministic Python `sorted` on
`(sip_timestamp, sequence_number, type_rank)` (line 321–325). Two
threads write to disjoint output lists (`raw_quotes` vs
`raw_trades`), then the merge is single-threaded. No race.

Per-thread `RESTClient` cloning is now safe-typed via
`_clone_parallel_clients` (`massive_ingestor.py:60–76`): falls back
to the shared client for test doubles (Massive instances detected via
module prefix). The pass-2 R-INGEST-06 concern about per-call client
duplication is partially mitigated for mocks but still creates fresh
real Massive clients per `ingest_symbol_parallel` call. Operational
nit (B3-MINOR), not a correctness issue.

### B4. `ReplayFeed` causality enforcement — **PASS**

`ReplayFeed.events()` (`replay_feed.py:84–98`) tracks `last_key`
and raises `CausalityViolation` when `key < last_key`. The message
points the operator at `resequence_event_list`. Same check is also
in `InMemoryEventLog._enforce_market_order` so a violating event
cannot enter the log in the first place — defense in depth.

### B5. Intra-batch equal-timestamp ordering — **PASS, documented**

Quotes precede trades at equal `(exchange_timestamp_ns, symbol)` ties
because of `type_rank = (NBBOQuote, Trade).index(type(event))`
(`event_resequence.py:35`). Inside a single batch passed to
`append_batch`, `_stabilize_market_slice` re-sorts before the
monotonicity check, so even mixed input is canonicalized. Documented
in `event_resequence.py:8–13`.

### B6. `InMemoryEventLog.append_batch` invariant parity — **PASS**

The `_enforce_market_order` predicate is shared by `append()`,
`append_batch()`, and `replace_events()`
(`memory_event_log.py:49–90`). All three use the same lock and the
same comparator. There is no path to enter an event that violates
the invariant short of bypassing the API entirely (e.g., directly
mutating `_events`).

---

## C. Replay model & causality (BT-17)

### C1. BT-17 latency wiring — **PASS**

End-to-end trace:

- `platform_config.py:36–37` — `DEFAULT_MARKET_DATA_LATENCY_NS =
  20_000_000` (20 ms), `DEFAULT_BACKTEST_FILL_LATENCY_NS =
  50_000_000` (50 ms). Both default non-zero.
- `platform_config.py:175, 177` — `PlatformConfig` exposes both as
  configurable fields with validation at `559–567` (non-negative).
- `bootstrap.py:458` — `_create_backend` receives
  `market_data_latency_ns=config.market_data_latency_ns`.
- `bootstrap.py:861, 894, 912` — `_create_backend` threads it into
  `build_passive_limit_backend` and `build_backtest_backend`.
- `execution/backtest_backend.py:39–58, 96–120` — backends construct
  `ReplayFeed(market_data_latency_ns=market_data_latency_ns, ...)`.
- `replay_feed.py:60–66` — `ReplayFeed.__init__` stores it.
- `replay_feed.py:100–106` — `events()` uses
  `market_data_visible_at_ns(ts, market_data_latency_ns)` to advance
  the SimulatedClock. Only advances when `visible_ns > now_ns()`.

Defaults are production-realistic and **not** zero, closing the
prior concern that `0` would silently disable BT-17. The two latency
legs (feed propagation, fill submission) are stored separately in
config (`platform_config.py:175, 177`), passed separately into
backend builders, and applied at *different* points in the pipeline:
market data → `ReplayFeed.set_time()`, fill submission → router
delay. No double-counting.

### C2. Latency leg separation — **PASS**

Confirmed by source inspection: `backtest_router` /
`passive_limit_router` consume `fill_latency_ns` only;
`ReplayFeed` consumes `market_data_latency_ns` only. The two
constants are wired through separate keyword args in
`bootstrap._create_backend` (`857–870`) and arrive at distinct
construction sites. No leakage.

### C3. Monotonic clock advance + equal visibility — **PASS**

`ReplayFeed` only calls `set_time` when `visible_ns > now_ns()`
(`replay_feed.py:105–106`). Equal-visibility events therefore do not
re-advance the clock — they all see the same `now_ns()` value. The
SimulatedClock guards against backward jumps at
`core/clock.py:46–47` (raises `ValueError`), so the absent equality
check above is correct by construction.

### C4. Anti-lookahead — **PASS**

`tests/causality/test_anti_lookahead.py` runs and passes (123-test
target suite included it). The check that sensor/feature/signal
layers cannot read exchange time before visibility time is exercised
by the orchestrator-level fingerprint stability tests
(`test_anti_lookahead.py:111, 173, 212`). Manual trace: `M1`
(`orchestrator.py:1925`) transitions on `tick_arrived`, and the
SimulatedClock has already been advanced to `visible_ns` before the
event was yielded (`replay_feed.py:105`). Any sensor reading
`clock.now_ns()` therefore sees a time `>=
exchange_timestamp_ns + market_data_latency_ns`.

### C5. Live vs replay clock parity — **PASS with one wrinkle**

Live mode uses `WallClock` (Inv-10). `_consume`
(`massive_ws.py:360`) captures `received_ns = self._clock.now_ns()`
per WS frame, threads it through `NBBOQuote.received_ns` /
`Trade.received_ns` (`core/events.py:69, 96`). This matches the
documented latency-annotation requirement
(`data-engineering/SKILL.md:192`).

REST historical path also threads `received_ns`
(`massive_ingestor.py:333`), **but** the value is the
SimulatedClock's frozen tick (`backtest_runner.py:348` creates a
`SimulatedClock(start_ns=1_000_000_000)` per (symbol, day) ingest,
and the clock never advances during ingest). So every REST event
gets the same `received_ns = 1_000_000_000`.

Severity: **MINOR** for backtest determinism (since `received_ns`
is now informational, not load-bearing), but it means any downstream
attempt to compute "ingestion latency" on a historical dataset
returns zero or a constant. Either re-capture `received_ns =
time.time_ns()` per record during ingest (breaks pure determinism),
or document the convention that REST `received_ns` is meaningless.

---

## D. Storage, cache, provenance (Inv-11, Inv-13)

### D1. `EventLog` contract — **PASS**

`append` and `append_batch` share `_enforce_market_order`
(`memory_event_log.py:92–103`). `replace_events`
(`memory_event_log.py:76–90`) resets `_last_market_key` before
re-validating — necessary because callers may legitimately reorder
the whole log (e.g., after global resequence in
`massive_ingestor.py:235`). Atomicity is guaranteed by a single
`threading.Lock`. Replay determinism: `replay` (`105–122`) takes a
snapshot of the slice under the lock and then `yield`s outside it,
so concurrent appends during replay see consistent state.

### D2. Disk cache fail-safe — **PASS**

`DiskEventCache.exists`, `.load`, `.read_manifest` all return
`None`/`False` on any error
(`disk_event_cache.py:113–204`). Specific defenses:

- **Schema hash** computed once at construction
  (`102, 38–49`), bumped via `_CACHE_SEMANTIC_VERSION = "2"`.
  Schema drift auto-invalidates (line 159–161).
- **Checksum** of the gzipped payload verified before deserialization
  (`165–177`). Any mismatch → warning + None.
- **Event-count cross-check** against manifest (`192–198`).
- **Atomic writes**: `.tmp` written, then `os.replace` (line 241–243,
  260–262). Crash between data and manifest leaves `exists()`
  returning False (line 132–133) so the cache is silently invalid
  rather than half-trusted.

`require_healthy_disk_cache_manifests` (CLI flag → config) raises
`CacheReplayError` on any day whose manifest reports
`ingestion_health != "HEALTHY"`
(`cache_replay.py:110–115`). Fail-closed is opt-in; default is
warn-and-continue (`backtest_runner.py:430–454`). Operators must
explicitly request fail-closed.

### D3. JSONL round-trip fidelity — **PASS with one omission**

`_event_to_dict` (`disk_event_cache.py:52–71`) walks every
dataclass field; Decimal → str (preserves precision), tuple → list
(JSON compat). `_dict_to_event` (`74–92`) reverses both. Test
coverage in `tests/storage/test_disk_event_cache.py` (in the 123
passing set).

**Omission**: `_dict_to_event` looks for the literal string `"tuple[int,
...]"` in the type annotation (`88`). The `NBBOQuote`
schema (`core/events.py:66–67`) has two such tuple fields
(`conditions`, `indicators`) typed exactly that way. If anyone
rewrites the annotation to e.g. `tuple[int, ...] | None`, the
match fails and the field round-trips as a list, breaking equality
checks. Brittle but currently correct.

### D4. Immutable raw log gap — **CARRY-OVER**

Skill says (`data-engineering/SKILL.md:39`) "original messages are
append-only and never mutated; all downstream representations derive
from this log." Implementation reality: the cache stores *normalized*
events, not raw vendor payloads. The four `_fingerprint_*`
functions compute a hash of select wire fields but don't persist the
raw bytes.

So a parser-bug discovery scenario — "we'd like to re-derive
canonical events from the original Massive payloads with a new
normalizer" — cannot be served from this cache. Operators would
need to re-hit the REST API or restore from a separate cold archive
that this codebase does not currently provide.

Severity: **MAJOR** at the design-contract level (skill promises a
capability that isn't implemented), MINOR in operational impact
because (a) the normalizer's track record is good, (b) Massive REST
data is idempotent on `timestamp_gte/lte` so re-ingest is cheap, and
(c) the cache invalidation via `_CACHE_SEMANTIC_VERSION` provides a
manual escape hatch.

Recommend either (a) add an optional `raw_jsonl.gz` companion alongside
each cache day, or (b) trim the skill text to match the implementation.

### D5. `EventSerializer` design gap — **CARRY-OVER**

Skill (`data-engineering/SKILL.md:256–260`) lists this as NOT YET
IMPLEMENTED. Current bit-identical persistence relies on `DiskEventCache`'s
`_event_to_dict` / `_dict_to_event` roundtrip plus the schema hash. As
long as Python `dict` insertion order is stable
(guaranteed >= 3.7) and `json.dumps` uses default sort behavior
(off), the gzipped bytes are deterministic.

Verified by `disk_event_cache.py:228–243`: the JSONL line ordering
follows `events`'s iteration order; within each line, dict key order
follows `__dataclass_fields__` (insertion order). Persistence is
bit-deterministic on this Python version. The gap is *contractual*
(no separate `EventSerializer` abstraction), not behavioral.

### D6. Provenance on backfills — **PASS**

`DiskEventCache.save` writes a manifest with `symbol`, `date`,
`event_count`, `quotes_count`, `trades_count`, `checksum`,
`event_schema_hash`, `created_at`, and (when supplied)
`ingestion_health` (`disk_event_cache.py:247–262`). The
`ingestion_health` field is populated from
`normalizer.all_health()` worst-case via
`backtest_runner.py:382–396`. `cache_replay.py:106–127` re-reads
the field on load and surfaces it through `IngestDayMeta`. Inv-13
holds at the cache level.

---

## E. Live feed robustness

### E1. WS reconnect / auth — **PASS** with one carry-over

Auth: `_authenticate` (`massive_ws.py:240–262`) drains the
unsolicited `"connected"` preamble, then sends auth, then validates
`auth_success`. Both `recv()` calls are wrapped with `asyncio.wait_for(timeout=10.0)`.
Closed in pass 4.

Subscribe: `_subscribe` (`264–314`) reads up to `len(channels)`
frames with a 5 s inter-frame timeout, counts `success` statuses,
raises only when zero are received, warns on partial.
Defensible for degraded-mode operation.

**Carry-over R-INGEST-01 / R4-NEW-04 (silent thread death) — STILL
ACTIVE.** `_run_loop`'s outer `except Exception`
(`massive_ws.py:200–201`) catches anything not in the inner
reconnect except. Three failure modes still hit it without notifying
the orchestrator:

1. `import websockets` failure (`209–215`).
2. Any exception raised before the `while not
   self._stop_event.is_set()` loop enters (e.g., asyncio teardown
   weirdness).
3. Exceptions raised by `_authenticate` or `_subscribe` between the
   outer `try` and the inner reconnect except — these are inside the
   inner `try` and would be caught by line 228, which DOES call
   `notify_feed_interrupted`. So actually this is mostly handled now.

Confirmed by re-read: the inner `except Exception` at line 228 does
call `self._normalizer.notify_feed_interrupted(self._symbols)` at
line 231. **The residual is narrower than pass 4 reported**: only
the pre-loop ImportError (case 1) and any asyncio-internal exceptions
not inside the inner try (case 2) reach the outer except without
notifying. Severity drops to **MINOR**.

### E2. Queue overflow — **PASS, with monitoring nit**

`_consume` drops events with a warning when the bounded queue is
full (`massive_ws.py:368–373`). The queue limit (`100_000`) and the
1-second `events()` get-timeout mean that downstream consumers will
either lag or trip the queue. Currently a dropped event has no
metric counter — operators must scrape logs. Add a
`_events_dropped_counter` next to `MassiveNormalizer.duplicates_filtered`.

### E3. Idle tick — **PASS**

`IdleTick` (`ingestion/idle_tick.py`) is intentionally not an `Event`
(line 10–18). It is never published to the bus or appended to the
log. `MassiveLiveFeed.events()` yields one each second when the
queue is empty (`massive_ws.py:104`). Documented purpose: drive the
async fill drain in `Orchestrator._drain_async_fills` so
broker-pushed fills are not stranded on illiquid symbols.

Replay parity: `ReplayFeed` does NOT yield `IdleTick`. This is
correct — replay events are dense and there's nothing to drain. The
orchestrator must not assume `IdleTick` arrives in backtest mode.
Verified by `grep IdleTick src/feelies/kernel/` — the orchestrator
handles them in the live-feed branch only.

### E4. Restart of `MassiveLiveFeed` — **PASS**

`start()` after `stop()` calls `_drain_stale_sentinels`
(`massive_ws.py:121, 145–170`) which removes leftover `_SENTINEL`
markers from the queue while preserving any buffered market events.
Closes pass-3 R3-INGEST-04.

### E5. Thread / async model — **PASS**

The asyncio event loop runs in a dedicated daemon thread
(`_run_loop`, `194–205`). `_loop.call_soon_threadsafe(self._loop.stop)`
on `stop()` cleanly shuts down the loop. The 10-second `join`
timeout is logged on overrun (`136–141`) so a stuck shutdown is at
least observable.

GIL: each WS frame triggers `json.loads` plus the normalizer's
parse + state-machine updates — all CPU work in Python land. With a
single subscriber thread this is fine; if the orchestrator's main
thread is CPU-bound, the WS thread can fall behind and the bounded
queue absorbs the burst. Working as designed.

---

## F. Backtest / live parity & operator paths

### F1. CLI / cache path — **PASS**

`feelies backtest` → `harness.backtest_runner.main` →
`ingest_data` → `MassiveHistoricalIngestor.ingest_symbol_parallel`
or `DiskEventCache.load`. Per-day cache vs API miss tracked via
`DaySource` records (`backtest_runner.py:334, 399`). Multi-day
ingest accumulates a single `all_events` list then global
`resequence_event_list` (`411`). Same path is invoked when using the
disk-only `main_cache_replay` entry (`cache_replay.py:129`).

### F2. Paper / backtest type parity — **PASS**

Both paths construct `MassiveNormalizer` (backtest via
`backtest_runner.py:349`; paper via `bootstrap.py:448–453`) with
the same constructor. Paper additionally calls
`normalizer.register_symbols(config.symbols)` so cold-start `all_health`
reports HEALTHY for every requested symbol
(`massive_normalizer.py:242–246`). Both produce the same
`NBBOQuote` / `Trade` types into the orchestrator's M1 path.

### F3. M1 EventLog.append — **PASS**

`orchestrator.py:1476` (`_process_trade`) and `1931` (`_process_tick`)
both gate on `if not self._events_prelogged: self._event_log.append(...)`.
In backtest the event log is pre-loaded with the resequenced events,
so `_events_prelogged = True` avoids double-append. In live/paper
`_events_prelogged = False` and every inbound event is logged.

Inv-9 holds: identical M1 path, only the conditional log-append
differs; the bus publish is unconditional.

---

## G. Test & determinism coverage gaps

### G1. Coverage gaps (priority-ordered)

| Behavior | Test coverage |
| --- | --- |
| `register_symbols` semantics | ☑ exercised inline in normalizer tests (`grep` confirmed) |
| `notify_feed_interrupted` behavior | ☑ `tests/ingestion/test_massive_normalizer.py:336`, `tests/integration/test_paper_rth_safety.py:53` |
| `HALTED` state transitions | ☑ `tests/ingestion/test_data_integrity.py:68–85` |
| BT-5 halt-on/off path through normalizer | ☑ `tests/ingestion/test_massive_normalizer.py:620–626` |
| `_reject_sequence_reuse` with payload mismatch | ☐ **GAP** — no test grepable for the warning path |
| `decimal.InvalidOperation` from malformed prices | ☐ **GAP** — see C2 below |
| Multi-symbol global resequence | ☑ `tests/ingestion/test_parallel_ingest_integration.py::TestMultiDayCacheResequence` but **all SKIPPED** (no `massive` SDK) |
| Cache schema-hash invalidation | ☑ in disk-cache test set (passing) |
| Cache checksum invalidation | ☑ in disk-cache test set (passing) |
| WS queue overflow (`queue.Full`) | ☐ **GAP** — only log; no behavior test |
| `_drain_stale_sentinels` restart path | ☐ **GAP** |
| `_data_health_blocks_trading` for HALTED | ☐ **GAP** — by inspection, no test asserts the gate behavior for HALTED specifically |

### G2. Targeted test execution

Recorded in the header. Net: 123 + 73 = 196 passed, 19 skipped (all
"requires massive package"). No failures.

The skipped block includes every multi-symbol global-ordering test
in `test_parallel_ingest_integration.py`. The infrastructure for the
test exists; only the `massive` SDK dependency keeps it from running
in CI. Add a `pip install massive` to the CI integration job, or
ship a recorded fixture that exercises the parallel path without
network.

---

## Net residual catalogue

### MAJORs (active on this tree)

**M1. HALTED is gated by two parallel mechanisms (A7).**
Normalizer's `DataHealth.HALTED` and orchestrator's `_halted_symbols`
are populated by the same utility but consumed independently.
Document explicitly or unify.

**M2. Silent thread death — narrowed scope (E1).** The pass-4
R4-NEW-04 finding is mostly closed by the inner reconnect-except
now calling `notify_feed_interrupted`. Residual: pre-loop
`ImportError` and asyncio-internal exceptions still hit the outer
broad `except` without notifying. Severity drops from MAJOR to MINOR
in practice; flagged here to track that the fix is partial.

**M3. R3-INGEST-02 — Decimal `NaN`/`InvalidOperation` parser-thread
crash (carry-over).** Verified at
`massive_normalizer.py:324, 382, 463, 517` (still
`Decimal(str(...))`) and catch tuples at `339, 397, 478, 532` (still
`(KeyError, ValueError, TypeError)` — no `decimal.InvalidOperation`).
Bad numeric payload still kills the parser thread, which combined
with the residual silent-thread-death window above is the surviving
liveness risk.

**M4. R3-INGEST-03 — sequence holes in `EventLog`
(carry-over).** Verified at `massive_normalizer.py:293, 358, 443,
498`: `_seq.next()` still runs before construction. Holes are
deterministic but the dense-sequence invariant is violated. Forensic
issue, not safety.

**M5. R4-NEW-02 / R4-NEW-03 — `on_health_transition` append vs.
replace (carry-over).** Verified at
`massive_normalizer.py:679–687`: `sm.on_transition(callback)` still
appends to existing machines while overwriting `_transition_callback`
for future machines. Inconsistent semantics; non-idempotent. Trips
when any caller hot-rebinds the metrics sink.

**M6. Immutable raw log absent (D4).** Cache holds normalized events,
not raw vendor payloads. Re-derivation under a new normalizer is
impossible from the cache. Either trim the skill claim or persist
the raw side-by-side.

### MINORs (active on this tree)

- **A4-MINOR.** Asymmetric REST quote fingerprint (omits
  `participant_timestamp` / `trf_timestamp`) vs WS quote
  fingerprint.
- **B3-MINOR.** Per-call `RESTClient` instantiation for real Massive
  clients (`_clone_parallel_clients`); 2N clients for N symbols.
- **C5-MINOR.** REST `received_ns` is constant per (symbol, day)
  ingest — informational latency is meaningless on historical
  replays.
- **D3-MINOR.** `_dict_to_event` literal-string type match
  (`tuple[int, ...]`) is brittle to annotation rewrites.
- **D5-MINOR.** No standalone `EventSerializer` abstraction; the
  contract is implicit in `DiskEventCache`.
- **E2-MINOR.** WS queue-overflow drops not surfaced as a
  per-instance counter.
- **G1-MINOR.** Test gaps: `_reject_sequence_reuse` payload-mismatch
  warning, `queue.Full` behavior, `_drain_stale_sentinels`
  restart path, `_data_health_blocks_trading` HALTED behaviour.
- **G2-MINOR.** Multi-symbol parallel-ingest integration tests all
  SKIP due to absent `massive` SDK in CI; the resequence assertion
  therefore isn't actually being exercised in pipeline runs.
- **(carry-over) r3-INGEST-09 — historical `received_ns` batch-uniform**
  (now corroborated; see C5-MINOR above).

### CLOSED since prior passes

| Finding | How closed |
| --- | --- |
| B-INGEST-01 (checkpoint dead code) | `is_done` checked, `mark_done` *only after `completed_ok`* via `_download_raw`'s third return value (`massive_ingestor.py:295–306`). R4-NEW-01's poisoned-checkpoint regression is also closed by `DataIntegrityError` raising. |
| B-INGEST-02 (WS handshake) | `_authenticate` drains `connected` preamble first. |
| B-INGEST-03 (RECOVERING) | Removed from enum; CORRUPTED is terminal. |
| R-INGEST-02 (mid-pagination loss) | Now returns explicit `completed_ok = False` and the caller raises. |
| R-INGEST-04 (callback ordering) | `prev_seq` captured before update, then `_check_gap` runs *after* `_update_last_seen`. |
| R-INGEST-06 (subscribe one-frame validation) | Loop with per-channel confirmations. |
| R-INGEST-07 (memory bound) | Stream-chunked `append_batch`; `del raw_quotes, raw_trades` after merge. |
| R3-INGEST-01 (seq-zero dedup trap) | `_reject_sequence_reuse` returns False on `seq_num == 0` (`massive_normalizer.py:575–576`). |
| R3-INGEST-04 (queue restart bug) | `_drain_stale_sentinels` on `start()`. |
| R3-INGEST-06 (UNKNOWN symbol collapse) | `_mark_corrupted` short-circuits on empty/UNKNOWN ticker (`massive_normalizer.py:667–673`). |

---

## Recommended next-cycle action queue

1. **M3 / M2 pair**: add `decimal.InvalidOperation` to the catch
   tuples at `massive_normalizer.py:339, 397, 478, 532` and add a
   `_safe_decimal(value)` helper that rejects `NaN`/`Infinity` /
   non-positive. Same change closes M3 and removes the most likely
   trigger for M2.
2. **M1**: rename `_data_health_blocks_trading` to
   `_normalizer_health_blocks_trading` and have it return True on
   `HALTED` as well. Remove the orchestrator-side `_halted_symbols`
   set in favor of `normalizer.health(symbol) == DataHealth.HALTED`,
   so the normalizer is the single source of truth.
3. **M5**: rewrite `on_health_transition` to clear existing callbacks
   on the per-(symbol, feed-type) machines before re-registering,
   and add an idempotency unit test.
4. **M4**: move `_seq.next()` to the last operation before each
   return statement in the four parse paths, so failed construction
   doesn't burn a sequence number.
5. **G2**: ship a recorded-fixture variant of
   `test_parallel_ingest_integration.py` so the multi-symbol global
   ordering assertion runs in CI without the `massive` SDK.
6. **D4**: decide whether to add a raw-vendor side-channel to
   `DiskEventCache` or trim the skill's "immutable raw log"
   language. Either is fine; the current ambiguity is what's
   uncomfortable.
7. **C5-MINOR**: drop a line into `DiskEventCache` (or the
   `data-engineering` skill) noting that `received_ns` is
   wall-time-only on live and constant on historical replay.

---

## Verdict

**Backtest: PASS.** Determinism suite green. Inv-5 / Inv-6 / Inv-13
hold. BT-17 latency separation correct. Multi-symbol global ordering
enforced at every event-log construction site, with defense-in-depth
checks on the read side.

**Paper: PASS.** WS handshake + restart path are correct; symbols
are pre-registered; ingestion-health is propagated through the
manifest into the runtime gate (when opt-in).

**Unattended live: NOT YET.** Residuals M2 (silent thread death
under the narrow surface), M3 (Decimal corruption killing the parser
thread), and M5 (callback double-fire) are individually low-frequency
but compound. Close M3 first — it's the most likely trigger.

No prior-pass finding was overturned. Six prior MAJORs and one
prior BLOCKER (R4-NEW-01) are closed. Three architectural
improvements (BT-17 wiring, multi-symbol resequence, `InMemoryEventLog`
self-defense) were verified and praised above.
