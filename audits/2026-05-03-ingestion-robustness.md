# Ingestion Subsystem Audit — Data Manipulation Robustness & Logic Soundness

Date: 2026-05-03
Scope: `src/feelies/ingestion/` (7 files, 1,262 LOC)
Branch: `claude/audit-ingestion-robustness-41W81`
Files reviewed:

- `__init__.py`
- `data_integrity.py`
- `normalizer.py` (Protocol)
- `massive_normalizer.py`
- `massive_ingestor.py`
- `massive_ws.py`
- `replay_feed.py`

Severity legend: **BLOCKER** (silent data corruption / undelivered promise) ·
**MAJOR** (correctness or robustness defect with realistic trigger) ·
**MINOR** (latent risk / hardening) · **NIT** (style, observability).

---

## Executive summary

Ingestion is structurally sound: the normalizer is the single boundary, events
are typed, source/feed routing is clear, dedup is keyed correctly per
`(symbol, feed_type)`, and the replay path enforces causality. However, the
review found **three BLOCKERs and seven MAJORs** in data manipulation logic,
the most serious being:

1. `BackfillCheckpoint` is a documented public feature but **never read or
   written by the ingestor** — resumability is dead code.
2. `MassiveLiveFeed._authenticate` sends auth and validates the very next
   `recv()` as the auth response. If the Massive WS server emits an unsolicited
   status (e.g. `"connected"`) frame before the auth response — as the
   documented Polygon predecessor does — validation reads the wrong frame and
   the connection enters reconnect-with-backoff. **Severity is BLOCKER for
   live readiness pending confirmation against the current Massive WS
   contract / a wire capture.**
3. The `RECOVERING` health state has no producer in `MassiveNormalizer`. The
   state graph itself is *not* terminal — `data_integrity.py:34–39` explicitly
   permits `CORRUPTED → RECOVERING → HEALTHY` — but no code calls
   `transition(RECOVERING)`, so recovery is unimplemented. Operationally a
   `CORRUPTED` stream stays corrupted with no automated recovery, even though
   the enum/SM anticipates a recovery phase.

A handful of MAJORs concentrate on the WebSocket gap-detection logic, which is
not robust to out-of-order delivery, and on the parallel REST ingestor, where
checkpointing, timeout cleanup, and per-feed sequence-space ordering are weaker
than the surrounding code suggests.

---

## BLOCKERS

### B-INGEST-01 — `BackfillCheckpoint` is dead code
**File:** `massive_ingestor.py`
**Lines:** 89–191 (class `MassiveHistoricalIngestor`), checkpoint surface at
`57–86`, `106`, `114–120`, docstring promise at `14–17` and `143–144`.

The class accepts a `BackfillCheckpoint` and instantiates `InMemoryCheckpoint`
as a default. The module docstring (`14–17`) and the `ingest()` docstring
(`143–144`) both promise: *"On retry, already-completed pairs are skipped."*

In `ingest()` (`122–191`) and `ingest_symbol_parallel()` (`195–267`), there is
**no call** to `self._checkpoint.is_done(...)` and **no call** to
`self._checkpoint.mark_done(...)`. Verified via:

```
grep -n "checkpoint\|is_done\|mark_done" src/feelies/ingestion/massive_ingestor.py
```

Hits are limited to the class, slot, and constructor — no lookup, no write.

**Impact:** Interrupting a multi-day, multi-symbol backfill and re-running it
re-downloads everything, paying the full Massive REST cost a second time. This
is also a silent contract violation: callers will trust the documented
behavior.

**Fix sketch:** In `ingest()`, before invoking `ingest_symbol_parallel()`,
check `is_done(symbol, "quotes")` and `is_done(symbol, "trades")` and skip the
matching download branch in `_download_raw`. Mark the pair done immediately
after `append_batch` succeeds inside `ingest_symbol_parallel`. Note that the
current `ingest_symbol_parallel` couples quotes+trades into a single sorted
batch; either decompose it (one append per feed_type) or checkpoint at
symbol-granularity and rename the surface to match.

---

### B-INGEST-02 — `MassiveLiveFeed._authenticate` may desync with the Massive WS handshake
**File:** `massive_ws.py`
**Lines:** 173–188.

`_authenticate()` does:

```python
auth_msg = json.dumps({"action": "auth", "params": self._api_key})
await ws.send(auth_msg)
raw = await ws.recv()                         # validates this as auth response
self._validate_status_response(raw, "auth_success", "authentication")
```

It sends auth and treats the *next* incoming frame as the auth response —
there is no drain of any pre-auth status frame. The Polygon predecessor
unconditionally pushes
`[{"ev":"status","status":"connected","message":"Connected Successfully"}]`
on socket open, before any client message; if Massive preserves that
behavior, the first `recv()` after the send returns the queued
`"connected"` frame, validation raises `ConnectionError`, and
`_connect_with_retry` enters exponential backoff. Whether the unsolicited
frame is still emitted by the current Massive WS endpoint should be pinned
with a wire capture or an explicit protocol note — `tests/ingestion/test_massive_functional.py`
is opt-in live, so its passing does not by itself prove the issue is absent
(it could be timing-masked).

**Impact (conditional on the protocol contract):** live feed cannot reliably
establish a stream; backoff up to 60s between retries delays the first tick.
Severity remains **BLOCKER** for live readiness until the contract is
confirmed or the code is hardened.

**Fix sketch:** Drain the initial status frame (or any pre-auth frames) before
sending auth, e.g.:

```python
preamble = await ws.recv()
self._validate_status_response(preamble, "connected", "connect_preamble")
await ws.send(auth_msg)
auth_resp = await ws.recv()
self._validate_status_response(auth_resp, "auth_success", "authentication")
```

Add an `asyncio.wait_for(..., timeout=10)` around each `recv()` so a silent
server can't wedge the loop.

---

### B-INGEST-03 — `RECOVERING` is unused; no path from `CORRUPTED` to recovery in the normalizer
**File:** `data_integrity.py` (`25–41`), `massive_normalizer.py` (`409–412`).

The state graph itself is *not* terminal: `data_integrity.py:34–39`
explicitly allows `CORRUPTED → RECOVERING` and `RECOVERING → HEALTHY`. The
defect is in the producer, not the SM. `MassiveNormalizer` only ever invokes:

- `HEALTHY → GAP_DETECTED` (`385–390`)
- `GAP_DETECTED → HEALTHY` (`395–399`)
- `* → CORRUPTED` (`409–412`, gated by `can_transition`)

No code calls `transition(RECOVERING)`. The recovery phase that the enum
and transition table anticipate is therefore unimplemented; once a symbol
is marked `CORRUPTED`, there is no automated path back to `HEALTHY`.

**Impact:** Operationally, a transient parse error is upgraded to a
prolonged symbol blackout with no programmatic recovery — even though the
state machine was designed to allow one. The runtime behavior is
"effectively terminal," but the enum value `CORRUPTED` is *not* a terminal
state in the formal SM.

**Fix sketch:** Either (a) add a recovery probe that, after N consecutive
clean ticks following corruption, calls `transition(RECOVERING)` then
`transition(HEALTHY)`; or (b) collapse `RECOVERING` from the schema and
document that `CORRUPTED` is terminal-by-design (and surface a runbook step
to restart the symbol). Option (a) is preferable; option (b) at least removes
the misleading dead state.

---

## MAJORs

### M-INGEST-01 — WS gap detector mis-handles out-of-order messages
**File:** `massive_normalizer.py`
**Lines:** 360–407.

When a WS message arrives with `seq_num < prev_seq` (legitimate out-of-order
delivery, common on multi-leg WS feeds):

1. `_is_duplicate` checks only `prev[0] == seq_num` (`368`); a regression to
   an *older* seq is not a duplicate, so it returns `False`.
2. `_check_gap` compares `seq_num > prev_seq + 1` (`385`) and
   `seq_num == prev_seq + 1` (`395`); both are false for a backward seq, so no
   transition is triggered, *but the message is also not dropped*.
3. `_update_last_seen` overwrites `prev` with the lower seq.
4. The next in-order message (e.g. `prev_seq+1` of the original chain) now
   appears as a forward gap, raising `GAP_DETECTED` spuriously, then
   immediately recovering.

Net effect: out-of-order arrivals (a) bypass dedup if duplicated later,
(b) generate spurious gap/recovery transitions, and (c) corrupt `last_seen`
for the dedup invariant in the next tick.

**Fix sketch:** Track a high-watermark separately from the last-accepted seq.
Treat `seq_num < high_watermark` as either dropped-late (preferred) or pass it
through unchanged but do not regress the watermark. Consider a small
reorder-buffer keyed by seq if Massive guarantees eventual consistency over a
short window.

---

### M-INGEST-02 — Float→Decimal conversion through `str()` loses price precision
**File:** `massive_normalizer.py`
**Lines:** `163–164` (`bp`/`ap` WS quote), `205` (`p` WS trade), `281–282`
(REST quote), `325` (REST trade).

`json.loads` decodes JSON numbers as Python `float`. The code then does
`Decimal(str(msg["bp"]))`, which round-trips through float. For most equity
prices this is safe (two-decimal ticks survive `repr`), but for instruments
priced in fractional cents or for any field that exercises >15 significant
digits, the result silently differs from the wire value.

**Fix sketch:** Parse with `json.loads(raw, parse_float=Decimal)` once at the
top of `on_message` (line 85). Then `Decimal(msg["bp"])` is a no-op cast and
all numeric fields keep the wire representation. Verify no downstream
`int(msg.get("bs"))` calls choke on `Decimal`s — they don't, `int(Decimal("100"))`
works, but spot-check `bid_size`/`ask_size` which are conceptually integers.

---

### M-INGEST-03 — Parallel ingestor leaks worker threads on timeout
**File:** `massive_ingestor.py`
**Lines:** 221–235.

```python
with ThreadPoolExecutor(max_workers=2) as pool:
    quotes_future = pool.submit(_download_raw, ...)
    trades_future = pool.submit(_download_raw, ...)
    raw_quotes, q_pages = quotes_future.result(timeout=_DOWNLOAD_TIMEOUT_S)
    raw_trades, t_pages = trades_future.result(timeout=_DOWNLOAD_TIMEOUT_S)
```

If `quotes_future.result(timeout=900)` raises `TimeoutError`, the `with` block
exits via exception. `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`
— meaning the in-flight `_download_raw` thread (which is iterating a
`requests`-backed paginator with no internal timeout) will continue running
and *block the caller* until the REST iterator completes naturally. The
"timeout" therefore does not bound wall time.

**Fix sketch:** Use `pool.shutdown(wait=False, cancel_futures=True)` in an
`except TimeoutError` branch, and pass an HTTP-level timeout into
`list_fn(...)` (the `massive` SDK forwards request kwargs). Even better: have
`_download_raw` poll a stop event between pages.

---

### M-INGEST-04 — Merge-sort key relies on cross-feed sequence ordering that does not exist
**File:** `massive_ingestor.py`
**Lines:** 248–253.

```python
merged.sort(key=lambda d: (
    d.get("sip_timestamp", 0),
    d.get("sequence_number", 0),
    d.get("__type_rank__", 0),
))
```

Quotes and trades have **independent** `sequence_number` spaces — the
normalizer correctly keys `_last_seen` by `(symbol, feed_type)` for that exact
reason (see comment at `70–73`). Sorting them together by
`(ts, sequence_number, type_rank)` therefore interleaves the two streams in an
order that is not meaningful when multiple ticks share `sip_timestamp`. A
high-seq quote can end up after a low-seq trade with the same nanosecond,
which then breaks the per-feed monotonicity that `_check_gap` would otherwise
rely on (REST disables gap detection, so the runtime impact is bounded — but
the invariant is fragile and will break the moment gap detection is enabled
for REST replays).

The default `0` for missing `sip_timestamp` also silently sorts those records
to the front. They should be filtered or the key should raise.

**Fix sketch:** Sort by `(sip_timestamp, type_rank, sequence_number)` so
within a tied timestamp, all quotes precede all trades (or vice versa)
deterministically, and the per-feed seq still increases monotonically inside
its group. Drop or log records whose `sip_timestamp` is missing rather than
defaulting to `0`.

---

### M-INGEST-05 — Live-feed `_consume` cannot exit on stop while the WS is idle
**File:** `massive_ws.py`
**Lines:** 240–267 with `stop()` at `116–124`.

`_consume` does `async for raw_msg in ws:` and only checks `_stop_event` after
each received message. On an idle feed (no messages for several seconds), a
`stop()` call sets the event but `_consume` keeps awaiting the next frame.
`stop()` then calls `loop.call_soon_threadsafe(loop.stop)`, but the loop is
inside `run_until_complete(self._connect_with_retry())`; calling
`loop.stop()` while inside `run_until_complete` raises
`RuntimeError: cannot stop loop` in some asyncio versions, and at minimum
leaves the WS connection un-closed (no `ws.close()` call). The 10-second
`thread.join` then times out and the daemon thread leaks until interpreter
exit.

**Fix sketch:** Replace `loop.stop()` with cancelling the running task, e.g.
keep a reference to the task created by `run_until_complete` and call
`task.cancel()` via `call_soon_threadsafe`. In `_consume`, race the WS recv
against the stop event:

```python
async for raw_msg in ws:
    ...
```

becomes a manual loop with `asyncio.wait({ws.recv(), stop_waiter}, ...)`.

---

### M-INGEST-06 — `_authenticate` and `_subscribe` can hang the connect loop
**File:** `massive_ws.py`
**Lines:** 184–188, 205–208.

`await ws.recv()` has no timeout. A misbehaving server (or a TCP-level half-
open) blocks the connect attempt forever — the exponential-backoff loop only
runs after an exception, so an indefinite hang prevents recovery. Combined
with B-INGEST-02 (handshake desync), this also means a single bad startup can
wedge the live feed indefinitely without producing telemetry.

**Fix sketch:** Wrap each `ws.recv()` in `asyncio.wait_for(..., timeout=10)`
and propagate `TimeoutError` so the outer loop reconnects.

---

### M-INGEST-07 — Per-record JSON re-serialization in REST ingest is wasteful and fragile
**File:** `massive_ingestor.py`
**Lines:** 258–262.

```python
for rec_dict in merged:
    rec_dict.pop("__type_rank__", None)
    raw = json.dumps(rec_dict).encode("utf-8")
    events = self._normalizer.on_message(raw, received_ns, "massive_rest")
```

This dict→JSON→bytes→JSON.loads round-trip for every record:

1. **Performance:** doubles per-record CPU on what is already a hot ETL path.
2. **Correctness risk:** if any value in `rec_dict` is non-JSON-serializable
   (e.g. a `datetime` from a future SDK upgrade, a `Decimal`), `json.dumps`
   raises `TypeError`. The exception is **not** caught here — it propagates
   out of `ingest_symbol_parallel` and aborts the whole symbol mid-batch with
   any preceding `all_events` already collected but not yet appended. Partial
   ingestion is left unrecorded.

**Fix sketch:** Either widen the `MarketDataNormalizer` protocol to accept a
parsed dict for the REST path (since the protocol's "raw bytes" contract is
only meaningful for WS frames), or wrap `json.dumps` in a try/except that
logs and skips the record, and persist `all_events` accumulated so far before
re-raising.

---

## MINORs

### m-INGEST-01 — `_seq.next()` advances even for events that are later filtered
**File:** `massive_normalizer.py` `143`, `191`, `261`, `311`.

`SequenceGenerator.next()` is called *before* the canonical event is built;
since dedup happens earlier, this is fine, but if any future code adds a
post-build filter, sequences become non-contiguous in the `EventLog`. Document
the invariant or move the `_seq.next()` call into the event constructor path
so it's tied to actual emission.

### m-INGEST-02 — `_ws_quote` accepts `bid > ask` without validation
**File:** `massive_normalizer.py` `158–174`.

A crossed/locked quote (`bid >= ask`) is accepted silently. For NBBO this is
usually invalid (it's filtered by SIP). Even a defensive `if bid > ask:
sm.transition(GAP_DETECTED)` style probe would catch a class of feed bugs.

### m-INGEST-03 — `Trade.trade_id` falls back to empty string
**File:** `massive_normalizer.py` `208`, `328`.

`trade_id=str(msg.get("i", ""))` and `str(rec.get("id", ""))` produce a
silent empty-string ID when the wire field is missing. That ID is critical
for downstream order/fill reconciliation (per `B5. Order-lifecycle &
idempotency`). Prefer raising a parse error and marking corrupt.

### m-INGEST-04 — `_validate_status_response` accepts the message anywhere in the array
**File:** `massive_ws.py` `230–238`.

Iterating `messages` and accepting *any* element with the expected status
means a server reply combining `[{"status":"connected"}, {"status":"auth_failed",...}]`
would pass an `expected_status="connected"` check despite a downstream
failure. Pair-check by index or require the *first* status message to match.

### m-INGEST-05 — `MassiveLiveFeed.start()` race and re-entry
**File:** `massive_ws.py` `104–114`.

The check `if self._thread is not None and self._thread.is_alive(): return`
is not protected by a lock. Two near-simultaneous `start()` calls can both
spawn a thread. Realistic only in test code, but cheap to fix with a
`threading.Lock`.

### m-INGEST-06 — `stop()` enqueues a sentinel that may already be in flight
**File:** `massive_ws.py` `121` and `139`.

`stop()` puts `_SENTINEL`; `_run_loop`'s `finally` also puts `_SENTINEL`. Two
sentinels in the queue are harmless for a single consumer but can hang a
multi-consumer test fixture. Either guard with a flag or move the sentinel
exclusively into the `finally`.

### m-INGEST-07 — `ReplayFeed` clock advance has no causality check on `now()`
**File:** `replay_feed.py` `76–78`.

`if ts > self._clock.now_ns(): self._clock.set_time(ts)`. If the clock
advanced past `ts` for an unrelated reason (a downstream component nudging
the simulated clock), the event is yielded *with the clock in the future
relative to `exchange_timestamp_ns`*, silently breaking the simulator's
"event time = clock time" invariant. Worth at least a `warning` log when
`self._clock.now_ns() > ts` by more than some epsilon.

### m-INGEST-08 — `_model_to_dict` prunes `None` values, masking required-field absence
**File:** `massive_ingestor.py` `352`.

Pruning means a `bid_price=None` from a malformed REST row becomes "missing
key", which the normalizer surfaces as a parse error (good). But it also
hides the difference between *explicit null on the wire* and *field never
sent*. If Massive ever uses `null` as a sentinel (e.g. a quote with no ask),
it's silently dropped. Acceptable today; document the assumption.

### m-INGEST-09 — Hard-coded `_DOWNLOAD_TIMEOUT_S = 900` not configurable
**File:** `massive_ingestor.py` `233`.

A 15-minute bound is reasonable for ETL but should be a constructor argument
so long backfills (full-session liquid names) can opt in to longer windows
without a code change.

### m-INGEST-10 — `_check_gap` does nothing when state is `GAP_DETECTED` and another forward gap arrives
**File:** `massive_normalizer.py` `385–394`.

The `if sm.state == DataHealth.HEALTHY` guard prevents re-transitioning,
but the function still does `logger.info(...)`. If consecutive gaps occur
without an intervening recovery, only the *first* drives a state transition
and subsequent gaps are observable only in the log. Consider a counter on the
state machine extras or a `GAP_DETECTED → CORRUPTED` escalation rule (e.g.
"more than N gap events without recovery").

---

## NITs / observability

- **`__init__.py`** re-exports cleanly; no issues.
- **`normalizer.py` Protocol** is well-documented but does not specify
  thread-safety expectations; given live and replay feeds are both
  single-threaded against one normalizer, this is implicit. Consider a one-
  line note.
- **Logging** uses `%`-style formatting consistently — good. The `warning`
  paths in `_ws_quote` and `_ws_trade` log the exception message but not
  the offending raw payload (truncated). Adding `extra={"sym": ...,
  "seq": ...}` would help post-mortem.
- **Metrics surface** is limited to `duplicates_filtered`. Consider also
  exposing `gaps_detected`, `parse_errors`, and per-symbol last-seq for
  monitoring without scraping logs.
- **`__slots__`** is used consistently — nice memory discipline.
- **`MassiveLiveFeed.events()`** uses a 1.0s `timeout` poll on `queue.get`;
  this is correct but adds up to 1s of shutdown latency. Coupling the
  sentinel with an unconditional return on `_stop_event.is_set()` is fine.

---

## Cross-cutting observations

1. **Boundary discipline is strong.** All raw data crosses through
   `MassiveNormalizer.on_message` and is converted to typed events with
   correlation IDs and sequence numbers. This matches invariant 13.
2. **Per-feed sequence-space separation is correctly modeled.** The
   `(symbol, feed_type)` keying in `_last_seen` (`73`) is the kind of
   subtlety that often gets wrong in market-data pipelines; the comment at
   `70–73` shows the author understood the failure mode.
3. **REST gap detection is correctly disabled** with a precise inline
   rationale (`255–258`, `307–308`). This is the right call given thinned
   historical responses.
4. **Documentation outpaces implementation** in two places (checkpoint
   resumability, RECOVERING state). Both should either be implemented or
   the docs trimmed — silent contract drift is worse than missing features.
5. **No fuzz / property tests** were inspected here, but the test directory
   has `test_massive_normalizer.py`, `test_massive_ingestor.py`, and
   `test_data_integrity.py` — a follow-up audit task should verify whether
   the BLOCKERS above have direct test coverage. (Quick spot check
   recommended: `grep -n "checkpoint\|RECOVERING\|connected" tests/ingestion/`.)

---

## Recommended action queue (priority order)

1. **B-INGEST-01** Wire the checkpoint into `ingest()` (or remove the
   feature). Add a regression test that calls `ingest()` twice and asserts
   the second call is a no-op for completed `(symbol, feed_type)` pairs.
2. **B-INGEST-02** Drain the connect-status frame before sending auth.
   Add a fake-WS unit test that emits the correct three-frame handshake.
3. **B-INGEST-03** Decide RECOVERING semantics; either implement the
   transition or remove the state and adjust the table + docstring.
4. **M-INGEST-05 / M-INGEST-06** Make `stop()` cancel the running task
   and bound `recv()` with `asyncio.wait_for`.
5. **M-INGEST-01** Make WS gap detection robust to out-of-order seq.
6. **M-INGEST-02** Switch JSON parsing to `parse_float=Decimal`.
7. **M-INGEST-03** Add `cancel_futures=True` and HTTP-level timeouts.
8. **M-INGEST-04** Fix sort key and reject missing `sip_timestamp`.
9. **M-INGEST-07** Either pass dicts through the protocol or guard the
   `json.dumps` and persist partial batches before re-raising.
10. Sweep the MINORs as cleanup once the BLOCKERS/MAJORS land.

---

## Verdict

**Conditional PASS** for the paths actually exercised today — historical
REST ingest + cache replay — with caveats M-INGEST-04 and M-INGEST-07.
**FAIL for unconditional "live trading ready"** until at least B-INGEST-02
is fixed or its protocol assumption confirmed by a wire capture, and
B-INGEST-01 is either wired through or descoped in the docs (operators
will reasonably believe resume works as written). B-INGEST-03 and
M-INGEST-05 are next-tier blockers for live: the live feed currently has
no automated recovery from a single corrupting message and cannot be
relied on to shut down cleanly while idle.

---

## Addendum — review-of-review (2026-05-03)

A peer review of the audit agreed with the overall posture and called out
two wording / framing issues, both incorporated above:

- **B-INGEST-03 wording.** The original phrasing ("`CORRUPTED` is terminal
  until process restart") was loose: the state machine in
  `data_integrity.py:34–39` explicitly allows `CORRUPTED → RECOVERING →
  HEALTHY`. The accurate finding is that **`RECOVERING` is unused — no
  producer in `MassiveNormalizer` transitions into it** — so recovery is
  unimplemented even though the SM anticipates it. Updated.
- **B-INGEST-02 protocol caveat.** The handshake-desync claim depends on
  the current Massive WS contract; the Polygon predecessor sends an
  unsolicited `"connected"` frame on open, but Massive's behavior should
  be pinned with a wire capture before declaring this a guaranteed
  failure. Severity remains BLOCKER for live readiness pending
  confirmation; the section now says so explicitly.

No MAJOR/MINOR findings were challenged on substance. The verdict block
was rephrased to emphasize "paths actually exercised" vs unconditional
live-readiness, matching the reviewer's framing.
