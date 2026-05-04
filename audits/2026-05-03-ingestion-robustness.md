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

---

## Second-pass audit (2026-05-04)

Goal: re-read every file and its dependencies (`Clock`,
`SequenceGenerator`, `StateMachine`, `EventLog`, the `tests/ingestion/`
corpus) with fresh eyes and surface residuals the first pass missed.
Methodology: each first-pass finding was used as a seed and then deliberately
*not* re-walked, focusing review attention on the un-touched code paths,
the dependency contracts, and the test inventory.

Confirmed against dependencies:

- `SequenceGenerator.next()` is genuinely thread-safe (`identifiers.py:25–30`,
  uses `threading.Lock`) — first-pass concern m-INGEST-01 about cross-thread
  use of `_seq` is therefore a non-issue at the *generator* level. The
  surrounding mutable state (`_last_seen`, `_health_machines`,
  `_duplicates_filtered`) is **not** lock-protected, so the residual
  thread-safety risk lives there.
- `StateMachine.transition()` (`state_machine.py:125–163`) raises
  `IllegalTransition` on a forbidden target. The normalizer guards every
  invocation with `can_transition` or an explicit state check, so this
  cannot leak — but see R-INGEST-04 for a residual ordering hazard.
- `SimulatedClock.set_time` raises `ValueError` on backward jumps
  (`clock.py:46–47`). `ReplayFeed` already guards with `if ts >
  self._clock.now_ns()`, so the raise path is unreachable from inside
  ingestion. Confirms first-pass m-INGEST-07 is observability-only.

Residuals are numbered `R-INGEST-NN` to keep them distinct from the first
pass.

### New BLOCKER

#### R-INGEST-01 — `MassiveLiveFeed` silently swallows fatal feed termination
**File:** `massive_ws.py:128–139` and `141–171`.

```python
def _run_loop(self) -> None:
    self._loop = asyncio.new_event_loop()
    asyncio.set_event_loop(self._loop)
    try:
        self._loop.run_until_complete(self._connect_with_retry())
    except Exception:
        logger.exception("massive_ws: event loop terminated unexpectedly")
    finally:
        self._loop.close()
        self._loop = None
        self._queue.put(_SENTINEL)
```

Three independent failure modes terminate the feed *without notifying the
caller*:

1. `import websockets` inside `_connect_with_retry` raises `ImportError` if
   the optional extra is not installed. The exception is caught by the broad
   `except Exception` in `_run_loop`, logged, and the sentinel is enqueued —
   `start()` returned cleanly seconds earlier, so the caller believes the
   feed is up. Consumers see an empty `events()` iterator and silently exit
   their loops. (`massive_ws.py:144–149`.)
2. Any `Exception` raised by `_authenticate` / `_subscribe` / `_consume` that
   is *not* the expected `ConnectionError` (e.g., a `RuntimeError` from
   `asyncio`, an `OSError` from a lower-level socket bug, an unexpected
   `KeyError` in a server frame) bypasses the reconnect-with-backoff loop —
   that loop only catches *generic* `Exception` and only re-runs while
   `self._stop_event.is_set()` is False. Same outcome: log + sentinel.
   (`massive_ws.py:160–171`.)
3. The `try/except` block in `_connect_with_retry` is itself inside
   `_run_loop`'s `try/except`. If `_connect_with_retry` exits cleanly because
   stop was requested, that's correct. But if it returns due to
   `asyncio.CancelledError` originating from elsewhere, the outer block
   doesn't distinguish.

**Impact:** for a *live trading* deployment this is worse than B-INGEST-02:
when the feed dies for *any* reason, the orchestrator keeps running with
zero new ticks. The kill-switch / data-integrity escalation path described
in `data_integrity.py:1–6` ("if CORRUPTED during LIVE_TRADING_MODE, the
global macro state transitions to DEGRADED — execution stops") only fires
on parse-driven `_mark_corrupted`. Silent thread death does **not** mark any
symbol corrupted, so DEGRADED is never reached.

**Fix sketch:** accept a `on_terminated: Callable[[BaseException | None],
None]` callback in `__init__` and invoke it from `_run_loop`'s `finally`.
For the `import websockets` case, perform the import in `__init__` so
construction fails fast. Promote one-symbol corruption (or even a global
corruption marker) when the feed thread exits abnormally.

### New MAJORs

#### R-INGEST-02 — `_download_raw` does not catch mid-iteration errors; partial batch is lost
**File:** `massive_ingestor.py:285–324`.

The `try/except Exception` only wraps the *first* `list_fn(...)` call, which
returns a paginator. The subsequent `for obj in records_iter:` is
unprotected. If the underlying HTTP iterator raises on page 73 of 100
(network blip, 5xx after retries exhausted, JSON decode of a corrupted
response), the exception propagates out of `_download_raw`, then out of
`future.result(...)` in `ingest_symbol_parallel`, then out of `ingest()` —
**and the partial `raw_dicts` accumulated so far are discarded**. Combined
with B-INGEST-01 (no checkpoint), the next retry re-downloads from page 1.

**Fix sketch:** wrap the iteration in a per-page try/except, log the
failing page, return what you have (with `pages` reflecting actual
completion), and let the caller decide whether partial-OK is acceptable.
Pair with checkpointing so the next attempt can pick up where pagination
broke.

#### R-INGEST-03 — `received_ns` is a required Protocol parameter that nobody uses
**File:** `normalizer.py:41–59`, `massive_normalizer.py:78–96`,
`massive_ingestor.py:256`, `massive_ws.py:254–259`.

`MarketDataNormalizer.on_message` requires `received_ns`, the docstring says
it's used for latency tracking. `MassiveNormalizer.on_message` accepts the
parameter but **never reads it** — it's not stored on the event, not logged,
not fed into health metrics, not added to dedup state. `received_ns` is
pure dead weight in the only implementation.

This matters because the Protocol contract is the boundary advertised in
the module docstring (`normalizer.py:1–15`). Downstream code that *does*
care about ingestion latency (e.g., a future `tick_to_decision_latency_ns`
budget enforcer) cannot extract it from the canonical events because the
event schemas (`events.py:NBBOQuote`, `Trade`) have no `received_ns` field.
The audit trail is therefore missing the moment-of-ingest timestamp on
every tick.

**Fix sketch:** add an optional `received_ns: int | None = None` field to
`Event` (or to `NBBOQuote`/`Trade`), populate it in the normalizer, and
update the protocol docstring. Or — if the parameter is genuinely
unnecessary — remove it from the Protocol so the contract matches reality.

#### R-INGEST-04 — `_check_gap` reads pre-update `_last_seen` but `_update_last_seen` rewrites it before the SM transition's callback fires
**File:** `massive_normalizer.py:138–141`, `186–189`, `373–407`.

Sequence in `_ws_quote`:

```python
if self._is_duplicate(...): return None
self._check_gap(symbol, feed_type, seq_num)              # may transition SM
self._update_last_seen(symbol, feed_type, seq_num, ts)
```

`_check_gap` (correctly) reads `_last_seen` *before* updating. But the SM
transition fires its registered callback synchronously inside
`_check_gap` — and that callback (when wired, see R-INGEST-05) sees a
normalizer whose `_last_seen` for `(symbol, feed_type)` still points at the
*previous* sequence, not the current one. A naive callback that does
`normalizer._last_seen[(sym, ft)]` to capture "current seq" would log the
*prior* seq.

**Impact:** subtle, only matters once the `transition_callback` is actually
used. Worth flagging because the wiring is already in place
(`massive_normalizer.py:69, 350–351`).

**Fix sketch:** either move `_update_last_seen` *before* `_check_gap` (and
have `_check_gap` accept the prior seq as an argument), or document the
ordering invariant in `MassiveNormalizer`'s class docstring.

#### R-INGEST-05 — `transition_callback` constructor parameter is dead in production
**File:** `massive_normalizer.py:62–70, 349–352`. Verified across the repo:

```
grep -rn "MassiveNormalizer(" src tests scripts
```

shows three callsites: `scripts/run_backtest.py:749`,
`tests/ingestion/test_massive_functional.py:161,192`. None pass
`transition_callback`. The optional surface for routing
`GAP_DETECTED → HEALTHY` and `* → CORRUPTED` transitions to the metrics
pipeline / alert bus is therefore inert. Health changes are observable
*only* via `health(symbol)` polling and log scraping.

This is the inverse of B-INGEST-01: the API is implemented but no caller
uses it. For live trading, it means the operator dashboard cannot react in
real time to a symbol going CORRUPTED — they discover it on the next
polling tick.

**Fix sketch:** wire the callback in the orchestrator's bootstrap, route
the `TransitionRecord` to the metrics bus, and add an integration test that
asserts the callback fires on a forced corruption.

#### R-INGEST-06 — `MassiveLiveFeed._subscribe` only validates the first response, but Massive sends one status frame per channel
**File:** `massive_ws.py:190–208`.

For N symbols, `_subscribe` sends `2*N` channels in one comma-joined
message. The server replies with up to `2*N` `{"ev":"status","status":"success"}`
frames (Polygon's behavior is one-per-channel). `_subscribe` reads exactly
one frame and validates it; the remaining `2*N - 1` frames are then
delivered to `_consume` and routed through `MassiveNormalizer.on_message`,
which does not recognize `ev == "status"` and silently drops them
(`massive_normalizer.py:121–128`).

Two consequences:

1. A *partial* failure (e.g., `Q.AAPL` succeeds, `T.AAPL` returns
   `auth_required`) is invisible — the first `success` short-circuits
   validation.
2. Every subscription leaks `2*N - 1` parser warnings? No — actually the
   normalizer doesn't warn on unknown `ev`, it silently drops, so this is
   only a missed-error class, not log spam. Still: the "subscription
   succeeded" guarantee is much weaker than the docstring implies.

**Fix sketch:** loop `recv()` until you've seen exactly one status per
channel or exhausted a timeout; require *all* of them to match
`expected_status`.

#### R-INGEST-07 — `ingest_symbol_parallel` has no streaming path; whole-symbol-day held in memory
**File:** `massive_ingestor.py:195–267`.

`raw_quotes` and `raw_trades` are full dict lists, then `merged = raw_quotes
+ raw_trades` doubles the footprint, then `all_events` accumulates the
full list of canonical events, then `append_batch(all_events)` is called
once at the end. For a liquid name on a full session, quotes + trades can
be **tens of millions of dicts**, each ~10 keys. Easily 5–20 GB of Python
heap before any persistence, with all four lists alive simultaneously.

The class is called "batch ETL" so memory is "expected to be large", but
the path has no graceful degradation — there is no chunked merge-sort, no
on-disk sort spill, no incremental `append_batch` per K events. The
`_CHUNK_SIZE = 5_000` constant at the top of the module is used only to
shape the page-callback cadence, not to bound memory.

**Impact:** running this against a 30-symbol universe over a month-long
window will OOM on a 32 GB box. There is no early warning — `_download_raw`
just keeps appending until the OS kills the process.

**Fix sketch:** either (a) cap to a per-day window and externalize day-loop
to the caller, (b) stream merge-sort with a heap that pulls from both
paginators directly, or (c) `append_batch` per K events and let the
EventLog handle ordering at read time.

### New MINORs

#### r-INGEST-01 — Per-page timeout on the REST iterator is missing
**File:** `massive_ingestor.py:288–295`.

`list_fn(symbol, ..., limit=50000)` does not pass an HTTP timeout. The
upstream `massive` SDK defaults vary by version. A stalled TCP connection
on page 50 will hang the worker indefinitely; the `_DOWNLOAD_TIMEOUT_S`
on `future.result()` doesn't cancel the worker thread (M-INGEST-03).

#### r-INGEST-02 — `_validate_status_response` accepts the expected status anywhere in the array
**File:** `massive_ws.py:230–238`.

(First pass m-INGEST-04 noted this in summary form; flagging again as a
*hard* finding because R-INGEST-06 multiplies the impact: with multiple
status frames in one reply, a single `success` masks a colocated
`auth_required` or `error` frame.)

#### r-INGEST-03 — No date-format / range validation in `ingest()`
**File:** `massive_ingestor.py:122–145`.

`start_date` and `end_date` are interpolated directly into
`f"{start_date}T00:00:00Z"`. A typo (`"2025-13-01"`, `"2025/05/01"`,
empty string) becomes a malformed REST URL and surfaces as an opaque API
error inside `_download_raw`. Add an `fromisoformat` round-trip and assert
`start <= end`.

#### r-INGEST-04 — Symbol-key case sensitivity is not enforced
**File:** `massive_normalizer.py` throughout (`134, 182, 249, 302`).

`msg["sym"]` and `rec["ticker"]` are used verbatim as dict keys for
`_last_seen` and `_health_machines`. Polygon symbols are uppercase by
convention, but the normalizer accepts whatever the wire produces. A
mixed-case stream (`"aapl"` vs `"AAPL"`) would create two independent
state machines and dedup tables. Cheap fix: `.upper()` at the boundary.

#### r-INGEST-05 — `make_correlation_id` uses `:` as separator without quoting
**File:** `identifiers.py:8–15` (used by all four `*_quote` / `*_trade`
constructors in `massive_normalizer.py`).

If a symbol ever contains `:` (CME futures, OTC tickers like `BRK:A`), the
correlation ID becomes ambiguous to parse. No current symbol triggers
this; document the precondition or switch to a length-prefixed format.

#### r-INGEST-06 — `_rest_trade` hard-codes `trf_timestamp_ns=None`
**File:** `massive_normalizer.py:335`.

REST trade records do carry `trf_timestamp` (`/v3/trades/{ticker}`); the
quote variant reads it (`273–274`). The trade variant ignores the field
entirely. Likely an oversight rather than a deliberate omission — the
event schema has the field (`events.py:Trade.trf_timestamp_ns`).

#### r-INGEST-07 — `_ensure_health_machine(symbol)` is called twice per accepted message
**File:** `massive_normalizer.py:383, 407`.

`_check_gap` calls it (when sequence machinery fires) and
`_update_last_seen` calls it unconditionally. For a symbol that already
has a machine, it's a single dict lookup either way — micro. But it does
mean the SM creation path runs twice on the very first message for a
symbol; not a correctness issue, but a small defensive simplification.

#### r-INGEST-08 — `MassiveLiveFeed` has no upper bound on subscription size
**File:** `massive_ws.py:190–208`.

For a 1,000-symbol universe, `subscribe` sends a 2,000-channel
comma-joined string in one frame. WebSocket frame size is typically
capped (Polygon historical limit ~4 KB per subscribe; modern Massive
unclear). For large universes, batch the subscribe into multiple frames.

#### r-INGEST-09 — No `ping_interval` / `ping_timeout` on the WS connection
**File:** `massive_ws.py:155`.

`websockets.connect(self._ws_url)` uses library defaults (20s ping,
20s timeout in modern `websockets`). Explicit configuration would make the
liveness contract part of the source of truth and immune to library
version drift.

#### r-INGEST-10 — `queue.Full` drops in `_consume` are not counted
**File:** `massive_ws.py:262–267`.

Drops are logged at `WARNING` per event, but no counter is exposed on
`MassiveLiveFeed`. Compare to `duplicates_filtered` on the normalizer.
During an overload, log volume becomes a denial-of-service vector and the
operator can't quantify what's actually being dropped.

### Test-coverage gaps reconfirmed

`tests/ingestion/` was inventoried against the (now nine) BLOCKER /
MAJOR findings. Concrete gaps:

| Finding | Test coverage |
| --- | --- |
| B-INGEST-01 (checkpoint) | `InMemoryCheckpoint` is *imported* in `test_massive_ingestor.py:13` but never instantiated or asserted on. **Zero behavioural coverage.** |
| B-INGEST-02 (handshake)  | `TestMassiveLiveFeedValidation` (`test_massive_normalizer.py:328–356`) tests `_validate_status_response` in isolation, never tests the recv-order in `_authenticate`. |
| B-INGEST-03 (RECOVERING) | `test_data_integrity.py:17` only asserts the enum value is distinct. No test exercises a CORRUPTED → RECOVERING → HEALTHY transition. |
| M-INGEST-01 (out-of-order WS seq) | `test_massive_normalizer.py` covers gap detection and recovery but **no test feeds a backward seq.** |
| M-INGEST-02 (Decimal precision) | All test prices are well-behaved (`150.0`, `400.05`); no test exercises a price that would round through float (`0.1+0.2`, `42.123456789`). |
| M-INGEST-03 (executor timeout cleanup) | None. |
| M-INGEST-04 (cross-feed sort) | `test_parallel_ingest_integration.py` exists but does not assert on sort order across tied `sip_timestamp`. |
| M-INGEST-05 / M-INGEST-06 (live shutdown) | None — only validation helpers tested in isolation. |
| R-INGEST-01 (silent feed death) | None. |
| R-INGEST-02 (partial download) | None. |

### Updated action queue

Insertions (priority within their tier):

- **R-INGEST-01** added at BLOCKER tier 4 (after B-INGEST-01..03), before
  the existing M-INGEST-05 — silent feed death is a strict superset of
  "shutdown is messy".
- **R-INGEST-02** added immediately after M-INGEST-03 — partial-download
  loss should be fixed *with* the executor-timeout cleanup.
- **R-INGEST-07** (memory bound) added at MAJOR tier; depends on the
  EventLog supporting incremental append (already true) and on whoever
  consumes the result tolerating eventual sort.

### Updated verdict

The first pass said "PASS for paths actually exercised today; FAIL for
unconditional live readiness." The second pass does **not** change the
backtest verdict — the new MAJORs around live shutdown, silent feed
termination, and the unwired `transition_callback` are all on the live
path. R-INGEST-07 (memory bound) is the one new caveat for the backtest
path: large universes / long windows will OOM with no early warning, so
the conditional PASS is now narrowed to "single-symbol, single-day or
short-window backfills" until streaming or chunked persistence lands.

No first-pass finding was overturned. Three first-pass findings were
strengthened by new evidence:

- M-INGEST-03 (executor timeout) ↔ R-INGEST-02 (partial download loss)
  compound: timeout doesn't cancel the worker, *and* mid-stream errors
  discard partial state.
- M-INGEST-05 (shutdown can't exit on idle socket) ↔ R-INGEST-01 (silent
  thread death) compound: even when shutdown *is* triggered cleanly, the
  caller has no signal that the feed is dead vs. just quiet.
- B-INGEST-02 (handshake) ↔ R-INGEST-06 (subscribe validates only first
  status) compound: both stem from the same "single recv() then assume
  the rest of the stream is data" pattern.

---

## Third-pass audit (2026-05-04)

**Status of prior fixes:** None. Verified by `git diff HEAD origin/main --
src/feelies/ingestion/` (empty) and `git log --all --since="2026-05-03 12:00"
-- src/feelies/ingestion/` (no commits). Every finding from passes 1 and 2
still applies verbatim against the code on disk. This third pass is
therefore a *deepening* exercise — searching for residuals that the first
two passes did not exercise — rather than a delta verification.

Methodology: focused on (a) malformed-payload defense, (b) internal-state
ordering across the SM ↔ normalizer boundary, (c) lifecycle restart paths,
(d) silent dedup / sequence-assignment traps, and (e) numerical edge cases
in `Decimal` construction. Findings are numbered `R3-INGEST-NN`.

### New MAJORs

#### R3-INGEST-01 — Missing `q` field silently drops every event after the first
**File:** `massive_normalizer.py:136, 184` (`seq_num = int(msg.get("q",
0))`) interacting with `_is_duplicate` (`360–371`).

`_check_gap` early-returns when `seq_num == 0` (`373–375`) and again when
`prev_seq == 0` (`380–381`) — the author understood that `0` is a
"sequence unknown" sentinel for the gap path. **`_is_duplicate` has no
matching guard.**

Trace, for a feed (or a malformed payload) where the `q` field is omitted
on every WS quote:

1. Frame 1: `seq_num = 0`. `prev` is `None` → not a duplicate. `_check_gap`
   returns early. `_update_last_seen` sets `prev = (0, ts1)`. **Event
   emitted.**
2. Frame 2: `seq_num = 0`. `prev[0] == seq_num` → `0 == 0` → **`True`.
   `_duplicates_filtered += 1`. Event silently dropped.**
3. Every subsequent frame: same outcome.

Net behavior: when the wire omits `q`, **only the very first event for
each `(symbol, feed_type)` is emitted, and `duplicates_filtered`
inexplicably climbs by one per tick** — visible as a metric anomaly but
not as a parse error or health transition. The symbol stays HEALTHY.

This is the worst kind of silent corruption: the orchestrator receives
plausible-looking traffic, makes decisions on stale prices, and the
data-integrity SM never fires because nothing was malformed at the
parser level — the dedup *is* the bug.

The same trap applies to any feed whose first event happens to carry
`q == 0` (legitimate sequence-zero on session start), with the next
non-zero `q` being treated as a forward gap and a `GAP_DETECTED → HEALTHY`
flap on the next tick — but the silent-drop path above is the dangerous
one.

**Fix sketch:** in `_is_duplicate`, mirror the `_check_gap` guard:

```python
if seq_num == 0:
    return False  # 0 is "unknown", cannot be used for dedup
```

Then `_update_last_seen` should *not* persist `(0, ts)` either — keep
`_last_seen[(sym, ft)]` absent until a real seq arrives, so the dedup
state isn't poisoned by sentinel zeros. Add a regression test feeding
two identical messages without `q`.

---

#### R3-INGEST-02 — `Decimal(str(msg["bp"]))` accepts `"NaN"`, `"Infinity"`, and negative prices without validation
**File:** `massive_normalizer.py:163–164, 205, 281–282, 325`.

`Decimal` is *more permissive* than `float`:

```python
>>> from decimal import Decimal
>>> Decimal(str("NaN"))
Decimal('NaN')
>>> Decimal(str("Infinity"))
Decimal('Infinity')
>>> Decimal(str(-1.5))
Decimal('-1.5')
```

Wire-level pathologies — a server bug emitting `null` (caught — None
→ `str(None)` → `Decimal("None")` raises `InvalidOperation`, propagated
to the catch block as `ValueError`? actually `decimal.InvalidOperation`
is a subclass of `ArithmeticError`, **not** `ValueError`, so it would
escape the `(KeyError, ValueError, TypeError)` catch and crash the
parser thread), `"NaN"` (silently constructs an NaN Decimal, emitted as
a "valid" event), or a negative bid — are not handled. Each creates a
different failure shape:

- **`"NaN"` / `"Infinity"`**: `Decimal("NaN")` succeeds; the resulting
  `NBBOQuote` carries a NaN bid, which compares `bid > ask` to `False`
  (NaN comparisons are always False). Downstream "is the book crossed?"
  guards fail-open. Position sizing and signal logic that does
  `mid = (bid + ask) / 2` propagates the NaN into PnL.
- **Negative prices**: silently accepted. `bid_size`, `ask_size`,
  trade size — all `int(...)` — also accept negatives without
  complaint.
- **`InvalidOperation` from genuine garbage** (e.g., `Decimal("abc")`)
  bypasses the `(KeyError, ValueError, TypeError)` catch at `175` /
  `217` / `295` / `339` and crashes the parser thread, which in
  `MassiveLiveFeed` propagates up through `_consume` → `_run_loop`'s
  broad `except` → silent feed termination (R-INGEST-01).

**Fix sketch:** add a `_safe_decimal(value)` helper that:
1. Catches `decimal.InvalidOperation` and re-raises as `ValueError`
   (so the existing catch handles it).
2. Rejects `is_nan()` and `is_infinite()`.
3. Rejects values `<= 0` for prices (not for `decimal_size` etc).

Apply at all four call sites. Include `decimal.InvalidOperation` in the
existing exception tuples regardless, as defense in depth.

---

#### R3-INGEST-03 — `_seq.next()` advances on parse failures, leaving holes in the EventLog sequence space
**File:** `massive_normalizer.py:143, 191, 261, 311`.

Sequence assignment in `_ws_quote`:

```python
internal_seq = self._seq.next()
cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)
...
return NBBOQuote(
    ...
    bid=Decimal(str(msg["bp"])),  # ← may raise KeyError / InvalidOperation
    ...
)
```

`_seq.next()` is at line 143; the `NBBOQuote(...)` constructor at 158
materializes the dataclass *after* the counter has already advanced. If
construction raises (missing `"bp"`, `"ap"`, `"bs"`, `"as"`, or
`InvalidOperation` from a bad numeric), the catch at 175 returns `None` —
**but the sequence number is permanently burned.** The EventLog
therefore has gaps in the `Event.sequence` field that do not correspond
to any real event.

Replay determinism is preserved (the gaps are deterministic given
deterministic inputs), but invariant 13 (every event has a unique,
contiguous sequence) is violated, and any tooling that audits
"events ordered by sequence with no holes" will flag false positives.

The same hole-creation pattern applies in the REST paths (`261`, `311`).

**Fix sketch:** move `_seq.next()` to be the **last operation before
`return`**, after all field accesses and `Decimal` construction have
succeeded. Equivalently, wrap construction first and then assign the
sequence in a tiny success-path helper.

---

#### R3-INGEST-04 — `MassiveLiveFeed.start()` after `stop()` reuses a queue with a stale sentinel and possibly stale events
**File:** `massive_ws.py:104–124`, queue lifetime at `76–78`.

`stop()` enqueues `_SENTINEL` (`121`), and `_run_loop`'s `finally` enqueues
*another* `_SENTINEL` (`139`). After `_thread.join()`, the queue still
contains:

- 0+ stale events the consumer never drained
- 1–2 `_SENTINEL` markers

`start()` (`104–114`) does **not** drain the queue and does **not** create
a new one. It only:

- checks `_thread.is_alive()`
- clears `_stop_event`
- spawns a new thread

The new feed thread starts producing events into the same queue. The
consumer's next `events()` call:

1. Yields the stale events from the prior session as if they were new
   (timestamps potentially hours behind clock time — replay-feed-like
   causality violation, but no `CausalityViolation` is raised because
   the live feed has no monotonicity check).
2. Hits the stale `_SENTINEL` and the consumer iterator **terminates
   cleanly**, even though the feed is healthy and producing.

This is a real restart bug. Triggered by any code path that does
`feed.stop()` then `feed.start()` — e.g., reconnect-on-config-change,
test fixture reuse, or a healthcheck-driven restart.

**Fix sketch:** in `start()`, after the alive check, drain the queue with
a non-blocking loop:

```python
while True:
    try:
        self._queue.get_nowait()
    except queue.Empty:
        break
```

Or replace `_queue` with a fresh `queue.Queue(maxsize=_MAX_QUEUE_SIZE)`
on each `start()`. The latter is simpler and avoids a reordering hazard
with concurrent producers.

---

#### R3-INGEST-05 — `StateMachine.transition()` callback contract: callbacks observe the *pre-transition* state
**File:** `core/state_machine.py:144–163`.

The docstring (`135–143`) calls the sequence "atomic" with steps:
*validate → build → notify → commit*. The implementation, however,
runs callbacks at step 3 (line 158) **before** appending to history
(`161`) and **before** updating `self._state` (`162`). Inside any
registered callback:

- `sm.state` returns the **old** state.
- `sm.history[-1]` is the **previous** transition, not the current one.
- The `record` parameter contains the new `to_state` (correct).

This is internally consistent and well-defended (if a callback raises,
no side effects — exactly as the docstring promises). But it is
**surprising**, and it directly affects the ingestion layer: when the
`transition_callback` constructor parameter on `MassiveNormalizer`
(`62–70, 350–351`) is finally wired (R-INGEST-05 from pass 2), naïve
callback authors will write code like:

```python
def on_health_change(record):
    log_metric("data_health.transition", labels={
        "symbol": record.machine_name,
        "to": record.to_state,
        "current_sm_state": sm.state.name,  # ← will print the OLD state
    })
```

— and observe a contradiction between `record.to_state` and `sm.state`.
Subtler: a callback that *queries* `_last_seen` to enrich the metric
will also see the pre-update tuple, because `_check_gap` is called
*before* `_update_last_seen` in the normalizer.

**Fix sketch:** either reorder the SM (`history.append` and
`self._state = target` *before* the callback loop, then revert on
exception — at the cost of mutability) or document the contract
explicitly in `StateMachine.on_transition`'s docstring with a note that
`record` is the source of truth, not `self.state`. Pair with a
normalizer-level docstring noting that `_check_gap` runs *before*
`_update_last_seen` so callbacks see the prior `(seq, ts)` for the
symbol.

---

#### R3-INGEST-06 — `_mark_corrupted("UNKNOWN")` collapses unrelated parse failures into one synthetic stream
**File:** `massive_normalizer.py:177, 219, 297, 341`.

The fallback when a parse error happens *before* `symbol` could be
extracted:

```python
self._mark_corrupted(msg.get("sym", "UNKNOWN"))
```

Any frame missing `"sym"` (or `"ticker"` in the REST paths) creates or
updates a single `_health_machines["UNKNOWN"]` state machine. A burst
of garbage from one upstream incident — say, the WS server briefly
emits status frames in an unexpected shape — flips `"UNKNOWN"` to
`CORRUPTED` once, then `can_transition(CORRUPTED)` returns False from
the state graph for subsequent calls (the gate at `411`), so further
errors are silent.

Real symbols are unaffected (they have their own machines), but the
operator dashboard now shows a permanent `UNKNOWN: CORRUPTED` symbol
that does not correspond to any tradable instrument and cannot be
acknowledged or recovered. The only actionable signal — "*which*
symbol just broke" — is destroyed.

**Fix sketch:** when `symbol` cannot be extracted, *do not* drive the
SM at all. Emit a counter (`_unattributable_parse_errors += 1`) and a
log line, leaving the per-symbol state space clean. Optionally include
a hash of the offending raw bytes for triage.

---

### New MINORs

#### r3-INGEST-01 — No defense against deeply nested or oversized JSON payloads
**File:** `massive_normalizer.py:84–88`.

`json.loads(raw)` is unbounded. A WS frame containing `{"a": [[[…]]]}`
nested past `sys.getrecursionlimit()` (~1000) raises `RecursionError`,
which is **not** in the `(json.JSONDecodeError, UnicodeDecodeError)`
catch — it propagates through `on_message`, into `_consume`, and then
into `_run_loop`'s broad `except`, killing the live feed silently
(R-INGEST-01). A 100 MB frame allocates 100 MB of Python objects. In a
trusted-feed deployment this is not a high-priority concern, but in
any deployment that proxies untrusted upstream (TLS-MITM debugging,
test harnesses replaying captured fuzzed traffic) it's a one-frame
liveness kill.

**Fix sketch:** cap raw frame size before `json.loads` (`if len(raw) >
_MAX_FRAME_BYTES: log + return []`). Add `RecursionError` to the catch
tuple.

#### r3-INGEST-02 — No range / sanity validation on `exchange_ts_ns`
**File:** `massive_normalizer.py:135, 183, 250, 303`.

`int(msg["t"]) * _MS_TO_NS` is unchecked. A wire-level bug producing
`t == 1e15` (a large but valid integer) yields a nanosecond timestamp
~30,000 years from now. The replay-feed causality check still passes
(monotonic), but downstream comparators that subtract event time from
wall time produce nonsense latencies.

**Fix sketch:** sanity-bound to `[clock.now_ns() − 30 days, clock.now_ns() +
1 hour]` or similar; on out-of-range, mark CORRUPTED with a precise
reason.

#### r3-INGEST-03 — REST classifier collapses ambiguous records silently
**File:** `massive_normalizer.py:233–244`.

```python
if "bid_price" in data or "ask_price" in data:
    event = self._rest_quote(data)
elif "price" in data:
    event = self._rest_trade(data)
```

A record with **both** `bid_price` and `price` is classified as a
quote and the `price` field is silently discarded. Real-world cause
for this is unlikely, but if Massive ever introduces a hybrid record
(unlikely) or a test fixture is malformed (likely), the silent drop
makes diagnosis hard. Add a `logger.warning` for the ambiguous case.

#### r3-INGEST-04 — `MassiveNormalizer.health(symbol)` returns `HEALTHY` for unseen symbols
**File:** `massive_normalizer.py:98–102`.

```python
def health(self, symbol: str) -> DataHealth:
    sm = self._health_machines.get(symbol)
    if sm is None:
        return DataHealth.HEALTHY
    return sm.state
```

A kill-switch / liveness watchdog that loops over the requested symbol
universe and asks `normalizer.health(sym)` cannot distinguish "data
flowing fine" from "we never received a single tick for this symbol."
Both return HEALTHY.

**Fix sketch:** add `DataHealth.NEVER_SEEN` (or rename the default to
`UNKNOWN`) and return it for absent machines. Update the SM transition
table to allow `NEVER_SEEN → HEALTHY` on first successful event.

#### r3-INGEST-05 — REST ingest does not validate that returned ticker matches requested symbol
**File:** `massive_ingestor.py:303–312` paired with `massive_normalizer.py:249, 302`.

`_download_raw` requests `symbol = "AAPL"` from the SDK; `_model_to_dict`
preserves whatever `ticker` the SDK returned, falling back to the
requested symbol only when the field is absent (`354–355`). If the
upstream returns `ticker = "MSFT"` for an `AAPL` request (Massive bug,
proxy misconfig, cache poisoning), the normalizer will key state under
`"MSFT"` and pollute the live `MSFT` machine with `AAPL` data. Defense
in depth: assert `rec_dict["ticker"] == symbol` in `_model_to_dict`
and drop+log on mismatch.

#### r3-INGEST-06 — `decimal.InvalidOperation` is not in the catch tuple
**File:** `massive_normalizer.py:175, 217, 295, 339`.

`(KeyError, ValueError, TypeError)` — `decimal.InvalidOperation` is an
`ArithmeticError`, not a `ValueError`. A wire payload like
`{"bp": "1.2.3"}` raises `InvalidOperation` from `Decimal(str("1.2.3"))`
and skips the catch entirely, killing the parser thread. See
R3-INGEST-02 for the broader Decimal-validation fix; this one is the
narrow defensive minimum.

#### r3-INGEST-07 — `_parse_ws` silently skips non-dict elements with no metric
**File:** `massive_normalizer.py:113–129`.

```python
for msg in messages:
    if not isinstance(msg, dict):
        continue
```

A malformed batch like `[{"ev":"Q",...}, "garbage", {"ev":"T",...}]`
processes the first and third, drops the second silently. No counter,
no log. Add a `_unparseable_elements` counter analogous to
`_duplicates_filtered`.

#### r3-INGEST-08 — `int(msg["bs"])` accepts negative sizes silently
**File:** `massive_normalizer.py:165–166, 206, 283–284, 326`.

`bid_size = -1` passes `int()`. The event schema does not constrain
non-negativity. Downstream depth aggregations that sum sizes will
produce nonsense. Reject `< 0` at the boundary.

#### r3-INGEST-09 — `received_ns` is captured once per `ingest_symbol_parallel` batch
**File:** `massive_ingestor.py:256`.

Already noted at architecture level (R-INGEST-03 / `received_ns`
unused). Concrete additional wrinkle: even if R-INGEST-03 is fixed by
plumbing `received_ns` into the event, the historical path hands
*every* record in a batch the same `received_ns`. Latency analysis
based on `received_ns - exchange_timestamp_ns` therefore returns the
batch wall-clock duration as a constant offset, not per-record
ingestion latency. Document or re-capture per-record.

#### r3-INGEST-10 — `_subscribe`'s comma-joined channel list duplicates per-symbol entries with no de-dup
**File:** `massive_ws.py:197–204`.

```python
for sym in self._symbols:
    channels.append(f"Q.{sym}")
    channels.append(f"T.{sym}")
```

If the caller passes `symbols = ["AAPL", "AAPL", "MSFT"]` (an honest
mistake from upstream config), the subscribe message contains
duplicate `Q.AAPL` entries. Massive may accept, error, or silently
double-charge. Defensive `list(dict.fromkeys(self._symbols))` at
construction would fix.

---

### Concurrency / contract observations

These are not bugs in the current single-threaded usage but are worth
recording since they're load-bearing assumptions the code does not
state explicitly:

- `MassiveNormalizer._last_seen`, `_health_machines`,
  `_duplicates_filtered` are mutated without locking. The Protocol
  docstring (`normalizer.py`) does not state thread-safety
  expectations. If a future caller shares one normalizer between the
  WS feed thread and a side ingest, races on the dict and integer
  produce silently incorrect dedup / counters.
- `StateMachine` itself is not thread-safe (`history` and `_state`
  mutation in `transition()` is unguarded). The data-integrity SMs
  inherit this.
- `ThreadPoolExecutor` workers in `ingest_symbol_parallel` invoke
  `client.list_quotes` / `list_trades` from two threads on a single
  client. The `massive` SDK's thread-safety is undocumented in this
  repo. Worth a constructor-time assertion or an explicit two-client
  pattern.

### Determinism cross-check

Verified that, given deterministic inputs and a fixed symbol-iteration
order:

- `_seq.next()` advances deterministically (R3-INGEST-03 holes are
  themselves deterministic).
- The merge-sort key in `ingest_symbol_parallel` is total-ordering on
  inputs that follow the per-feed sequence-space invariant; ties are
  broken by `(type_rank, list-position)` via Python's stable sort.
- `make_correlation_id` is pure.
- `received_ns` capture point is fixed.

So replay determinism appears to hold *despite* the holes — but the
EventLog's `Event.sequence` is no longer dense, which any auditor
checking "no skipped sequences" will flag.

### Updated finding inventory

| Pass | BLOCKER | MAJOR | MINOR |
| --- | --- | --- | --- |
| 1 | 3 (B-INGEST-01..03) | 7 (M-INGEST-01..07) | 10 (m-INGEST-01..10) |
| 2 | 1 (R-INGEST-01) | 6 (R-INGEST-02..07) | 10 (r-INGEST-01..10) |
| 3 | 0 | 6 (R3-INGEST-01..06) | 10 (r3-INGEST-01..10) |
| **Total** | **4** | **19** | **30** |

R3-INGEST-01 (silent dedup of seq-zero events) is functionally a
BLOCKER — silent stale-data delivery — but is graded MAJOR here because
its trigger requires either a malformed payload or a session-start
edge case (legitimate `q == 0`). If a wire capture confirms `q == 0`
ever occurs in normal operation, escalate.

### Updated verdict

The backtest verdict from passes 1 + 2 (conditional PASS, narrowed
to short-window single-symbol runs) is **further weakened**:

- R3-INGEST-01 means *any* historical record where `sequence_number`
  defaults to `0` (e.g., REST records with the field absent or
  zero-valued at session boundary) would be dropped after the first.
  The risk that a REST page legitimately contains `sequence_number:
  0` should be checked against actual cache fixtures.
- R3-INGEST-03 (sequence holes) does not break replay determinism
  but does break the "EventLog has dense sequence" invariant any
  audit-trail tool will assume.

The live verdict (FAIL) is **reinforced** by R3-INGEST-04 (queue
restart bug) and R3-INGEST-06 (UNKNOWN-symbol error collapse), both
of which break operational recovery without affecting the parse path.

No first-pass or second-pass finding was overturned. Two were
strengthened by new evidence:

- R-INGEST-01 (silent feed termination) ↔ R3-INGEST-02 (Decimal
  errors escape catch) ↔ r3-INGEST-01 (RecursionError escapes catch):
  three concrete failure modes that all funnel through the same
  silent-thread-death path. Fixing the broad `except` in
  `_run_loop` is now triple-justified.
- M-INGEST-01 (out-of-order watermark regression) ↔ R3-INGEST-01
  (seq-zero dedup trap): both stem from `_last_seen` being trusted
  unconditionally. A unified fix (treat `seq == 0` and `seq < high
  watermark` as "do not poison `_last_seen`") closes both.

---

## Fourth-pass audit (2026-05-04, post-fix)

**Tree audited:** `origin/main` at `dbb1cf5` (`fix: resolve all confirmed
ingestion audit findings`), pulled into the working branch via fast-forward.
Diff against the pre-fix tree is +185 / −68 across `data_integrity.py`,
`massive_normalizer.py`, `massive_ingestor.py`, `massive_ws.py`,
`core/events.py`, plus a one-line test addition.

This pass has two halves:

1. **Fix verification** — for every B-/R-/R3- finding the fix commit
   claims, was it actually delivered, partially delivered, or
   side-effectful?
2. **New residuals introduced by the fixes** — graded `R4-NEW-NN`.

### Part 1 — Fix verification

| Finding | Status | Evidence / caveat |
| --- | --- | --- |
| B-INGEST-01 (checkpoint dead) | **Mostly fixed** | `is_done` checked at `massive_ingestor.py:161–168`, `mark_done` called at `289–290`. **But:** `mark_done` runs unconditionally — see R4-NEW-01 below. |
| B-INGEST-02 (handshake) | **Fixed** | `massive_ws.py:191–198` drains the `connected` preamble first, validates it, then sends auth, validates auth response. Both `recv()`s wrapped in `asyncio.wait_for(timeout=10.0)`. Clean. |
| B-INGEST-03 (RECOVERING) | **Fixed cleanly** | `data_integrity.py:24–39`: `RECOVERING` removed from the enum entirely; `CORRUPTED` is now formally terminal (`frozenset()`). Test at `tests/ingestion/test_data_integrity.py:18–20` asserts the invariant. |
| R-INGEST-01 (silent feed termination) | **Partial** | `massive_ws.py:167` calls `notify_feed_interrupted` from the **inner** except inside `_connect_with_retry`. The **outer** `_run_loop` `except Exception` (line 136) — which catches `ImportError`, `RecursionError`, and any uncaught `decimal.InvalidOperation` — does **not** call it. See R4-NEW-04. |
| R-INGEST-02 (mid-pagination loss) | **Fixed** | `massive_ingestor.py:328–345`. Try/except wraps the iteration; partial `raw_dicts` is logged and returned. The post-loop `if buf:` cleanup (`347–354`) still drains the partial buffer. |
| R-INGEST-03 (received_ns unused) | **Fixed structurally; semantically partial** | `received_ns` added to `NBBOQuote`/`Trade` (`core/events.py:69, 96`) and threaded through all four parse paths. **But:** `massive_ingestor.py:271` still captures `received_ns` once per *batch*, so historical events all share one value (r3-INGEST-09 from pass 3 is therefore confirmed and not fixed). |
| R-INGEST-04 (callback ordering) | **Fixed** | `massive_normalizer.py:141–144, 192–195`: `prev_seq` captured **before** `_update_last_seen`; `_check_gap` is then called **after** the update, so any callback fired by a gap transition observes a fully-updated `_last_seen`. |
| R-INGEST-05 (transition_callback dead) | **Functionally fixed; two new bugs** | `on_health_transition()` added on `MassiveNormalizer` (`424–432`) and `MassiveLiveFeed` (`101–103`). Replaces the dead constructor surface. **But** the implementation has the inconsistencies in R4-NEW-02 and R4-NEW-03. |
| R-INGEST-06 (subscribe one-frame validation) | **Fixed** | `massive_ws.py:200–250`: loops up to `len(channels)` frames with a 5 s inter-frame timeout, counts `success` statuses, raises only when **zero** are received, warns on partial. The "warn-on-partial" choice is more permissive than the original suggestion ("require all"); defensible for degraded-mode operation but worth a one-line comment in the docstring. |
| R-INGEST-07 (memory bound) | **Improved ~2x; not eliminated** | `massive_ingestor.py:264, 273–290`: `del raw_quotes, raw_trades` after building `merged`; events now stream to `EventLog` in `_CHUNK_SIZE`-sized batches via `chunk`. **Peak memory** still includes `merged` (the full N+M sorted list) plus a 5 K-event chunk — a ~2× footprint vs. the prior ~4× peak, not the streaming heap merge that R-INGEST-07 sketched. |

**Fix-side summary:** all three pass-1 BLOCKERs are addressed (B-01 with a
caveat, B-02 + B-03 cleanly). All seven pass-2 R-INGEST findings are
addressed at least nominally; R-01 and R-07 are partial. **None of the
sixteen pass-3 findings (R3-INGEST-01..06, r3-INGEST-01..10) are
addressed** — the fix commit predates pass 3 by 45 minutes, so this is
chronological, not adversarial.

**Test coverage of the fixes:** zero. Verified mechanically:

```
grep -c "notify_feed_interrupted\|on_health_transition\|is_done\|mark_done\
\|received_ns\|preamble\|InMemoryCheckpoint(" tests/ingestion/*.py
```

every file returns `0` matches. The only test addition in the fix
commit is `test_corrupted_is_terminal` (good — proves the invariant).
Every other behavioral fix ships without a regression test.

### Part 2 — New residuals introduced by the fixes

#### R4-NEW-01 — `mark_done` runs unconditionally; failed downloads poison the checkpoint with permanent silent data loss
**File:** `massive_ingestor.py:175–186, 289–290`.

```python
ev_count, pg_count = self.ingest_symbol_parallel(
    client, symbol, start_date, end_date, on_page=on_page,
)
total_events += ev_count
total_pages += pg_count
completed_symbols.add(symbol)
```

…and inside `ingest_symbol_parallel`:

```python
if chunk:
    self._event_log.append_batch(chunk)
    total_events_local += len(chunk)

self._checkpoint.mark_done(symbol, "quotes")
self._checkpoint.mark_done(symbol, "trades")

return total_events_local, total_pages
```

`mark_done` is called **after** the chunk loop unconditionally, with no
check of how many records actually flowed. Three pathological inputs
all reach this point and corrupt the checkpoint:

1. **Auth/network failure at iteration start.** `_download_raw`'s
   *outer* try/except (`312–325`) returns `([], 0)` and logs the
   exception. `merged` is empty. The chunk loop runs zero iterations.
   `mark_done` is then called for both feed types. Next retry skips the
   symbol entirely.
2. **Mid-pagination failure** (paired with the R-INGEST-02 fix). The
   inner try/except (`328–345`) retains partial pages and logs them as
   "partial data retained." Then `merged` contains the partial set,
   `chunk`s flush, and `mark_done` is called as if the run was
   complete. The missing pages are never re-fetched, even though the
   log line said they were retained for retry.
3. **Empty result for a real symbol on a no-trading date.** Indistinguishable from
   case 1 from the checkpoint's perspective; harmless in this one case
   but worth noting because the code can't distinguish.

Severity: **BLOCKER** for any production backfill that relies on
checkpoint correctness — the two passes that fixed B-INGEST-01 created
a worse failure mode (silent permanent loss) than the original
no-resume behavior (visible re-download).

**Fix sketch:** mark done only when the call returned successfully **and**
yielded > 0 events, **or** distinguish "mark feed-type done" from
"mark symbol done" so partial completion is recoverable. The cleanest
shape: `_download_raw` returns a `tuple[list, int, bool]` where the
third element is "iteration ran to completion"; `ingest_symbol_parallel`
only marks per-feed done when that flag is True. (The R-INGEST-02 fix
swallows the mid-iteration exception, so this flag *must* be plumbed
through — a caller-side check on `len(raw_dicts)` is insufficient.)

---

#### R4-NEW-02 — `on_health_transition()` has inconsistent semantics for already-created vs. future symbols
**File:** `massive_normalizer.py:424–432`.

```python
def on_health_transition(self, callback) -> None:
    self._transition_callback = callback
    for sm in self._health_machines.values():
        sm.on_transition(callback)
```

If the normalizer was constructed with `transition_callback=A` and a
caller then runs `on_health_transition(B)`:

- **Already-created symbol machines** had `A` registered at creation
  time (`350–351`). `sm.on_transition(B)` *appends* — so both `A` and
  `B` fire on every transition.
- **Symbols seen for the first time after the call** get only `B`
  (the constructor callback was overwritten in `_transition_callback`,
  and `_ensure_health_machine:350–351` looks at the *current* value of
  that field).

Operators see the same transition reported either once or twice
depending on when the symbol first arrived. A monitoring system that
counts events will be off by a factor of two for symbols active before
the late wiring.

**Fix sketch:** either (a) clear the prior callback list on existing
machines before re-registering, or (b) document that
`on_health_transition` is single-shot, must be called before any
message is processed. (a) is friendlier; (b) matches the dependency
injection pattern already used elsewhere in the codebase.

---

#### R4-NEW-03 — `on_health_transition()` is not idempotent
**File:** `massive_normalizer.py:424–432`.

Calling the method twice with the *same* callback registers it twice
on every existing machine via `sm.on_transition(callback)` (which is
an `append`, not a `set`). Each transition then fires the callback
twice. This is a separate bug from R4-NEW-02 — even with no
constructor callback, the second call doubles up.

Realistic trigger: a caller that hot-rebinds the metrics sink (e.g., a
test harness re-running the same fixture, an operator dashboard
re-attaching after reconnect). The deduplication burden is pushed
onto the callback.

**Fix sketch:** clear `sm._on_transition_callbacks` before each
re-registration, or maintain a registry on the normalizer and replace
in-place. Add an idempotency unit test.

---

#### R4-NEW-04 — `notify_feed_interrupted` is not called for the fatal-thread-death paths
**File:** `massive_ws.py:130–141, 143–174`.

The R-INGEST-01 fix wires `notify_feed_interrupted` into the **inner**
`except Exception` of `_connect_with_retry` (line 164–172), which
handles the connection-loss-with-retry case. But three real failure
modes reach the **outer** `_run_loop`'s broad `except` (line 136)
without entering that inner block:

1. `import websockets` fails at line 146, raises `ImportError`,
   propagates out of `_connect_with_retry` directly to `_run_loop`.
   No `notify_feed_interrupted` call.
2. A coroutine inside `websockets.connect` itself raises a
   `RuntimeError` (asyncio teardown edge case, OS-level error).
3. The normalizer raises an exception that escapes its
   `(KeyError, ValueError, TypeError)` catch — most importantly
   `decimal.InvalidOperation` (R3-INGEST-02) and `RecursionError`
   (r3-INGEST-01). These propagate up through `_consume` → out of the
   `async with websockets.connect(...) as ws:` block → out of
   `_connect_with_retry`'s outer body (note: the inner `try:` at line
   156 wraps the `async with` and would catch this; verify by re-read
   below).

Re-read of `_connect_with_retry`:

```python
while not self._stop_event.is_set():
    try:                                          # ← inner try
        async with websockets.connect(...) as ws:
            ...
            await self._consume(ws)
    except asyncio.CancelledError:
        return
    except Exception:                             # ← inner except
        if self._stop_event.is_set():
            return
        self._normalizer.notify_feed_interrupted(self._symbols)
        ...
```

So **(3)** does enter the inner except. Good — the normalizer-escaped
exceptions will trigger `notify_feed_interrupted`. But **(1)** and
**(2)** (and any exception raised *before* line 153 `backoff =
_INITIAL_BACKOFF_S` or *between* the import and the while loop) bypass
the inner try entirely. The outer `except` in `_run_loop` is the only
catcher, and it does not call notify.

**Severity:** MAJOR. The orchestrator can be told the feed was
"interrupted" for one class of failure but silently dies for another,
including the exact path the dependency-extra installation hint was
designed to prevent.

**Fix sketch:** call `notify_feed_interrupted` from `_run_loop`'s
`except` block as well, right before logging. Consider adding an
`on_terminated` callback so the orchestrator can degrade the macro
state machine, not just per-symbol DataHealth.

---

#### R4-NEW-05 — Pre-emission gap transitions: `_check_gap` fires before event construction; failures leave SM history with phantom transitions
**File:** `massive_normalizer.py:141–146, 192–197`.

The new ordering inside `_ws_quote`:

```python
if self._is_duplicate(...): return None
prev = self._last_seen.get((symbol, self._FEED_QUOTE))
prev_seq = prev[0] if prev is not None else 0
self._update_last_seen(symbol, self._FEED_QUOTE, seq_num, exchange_ts_ns)
self._check_gap(symbol, self._FEED_QUOTE, seq_num, prev_seq)

internal_seq = self._seq.next()
cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)
...
return NBBOQuote(...)        # ← can still raise on bp / ap / Decimal
```

If construction at `161–178` raises (missing `"bp"`, malformed
`Decimal`), the function falls into the catch and calls
`_mark_corrupted(symbol)`. **By that point:**

- `_last_seen` has already been updated to `(seq_num, ts)`.
- The SM may have already transitioned `HEALTHY → GAP_DETECTED`
  (recorded in history with `trigger="seq_gap:..."`).
- A `_mark_corrupted` then transitions `GAP_DETECTED → CORRUPTED`.

History now reads:

```
HEALTHY -> GAP_DETECTED (seq_gap:quote:N->N+5)
GAP_DETECTED -> CORRUPTED (parse_error)
```

— for an event that **never appeared in the EventLog**. Operator
forensics correlating SM history with EventLog records will hit a
phantom: history says we *saw* and gap-detected `seq=N+5`; the log
has nothing.

This is a regression vs. the pre-fix behavior. Pre-fix: `_check_gap`
ran *before* `_update_last_seen`, so the gap transition implied a
real prior event mismatch, and a parse failure on the *current* event
left `_last_seen` untouched (so the next valid event would still see
the gap). Post-fix: gap is recorded eagerly, but the triggering event
may never have existed.

**Severity:** MAJOR for forensic / audit-trail consumers; benign for
the trading path because CORRUPTED is terminal anyway.

**Fix sketch:** either (a) move `_check_gap` and `_update_last_seen`
*after* successful event construction (revert the order change for
WS only — REST already runs without `_check_gap` for thinned-stream
reasons documented at `263–266`), or (b) record the gap-detection
intent and *commit* it only when the event constructs cleanly. (a)
is simpler.

---

#### R4-NEW-06 — Per-call `RESTClient` duplication: 2N pool teardowns for an N-symbol ingest
**File:** `massive_ingestor.py:233–234`.

```python
client_q = type(client)(api_key=self._api_key)
client_t = type(client)(api_key=self._api_key)
```

Two new `RESTClient`s per call to `ingest_symbol_parallel`, each with
its own urllib3 connection pool, TLS context, etc. For a 100-symbol
ingest this constructs and destroys 200 pools sequentially. The
parent `client` parameter (`206`) is now used only as a type token —
its constructed pool is never used inside this function.

The fix is correct in solving the "pool full" warning; the cost is a
real (small) memory and connection-establishment overhead per
symbol. For a single-day single-symbol run it's negligible; for a
multi-day backfill universe it's measurable.

**Fix sketch:** create the two `RESTClient`s once at
`MassiveHistoricalIngestor.__init__` time (or lazily on first call),
keep them on `self`, reuse across symbols. Drop the `client` parameter
from `ingest_symbol_parallel` since it's unused.

---

#### R4-NEW-07 — `client` parameter is now dead in `ingest_symbol_parallel`
**File:** `massive_ingestor.py:204–207`.

The parameter is read once at line 233 (`type(client)`) and otherwise
unused. Two callers pass it in (`ingest()` at `175–177`). Cleanup:
either delete the parameter and inline the import, or actually use
the passed-in client (one of the two threads can use it without
duplication).

Severity: MINOR (clarity).

---

#### R4-NEW-08 — `notify_feed_interrupted` does not record the reason on already-non-HEALTHY symbols
**File:** `massive_normalizer.py:434–444`.

```python
for sym in symbols:
    sm = self._health_machines.get(sym)
    if sm is not None and sm.state == DataHealth.HEALTHY:
        sm.transition(DataHealth.GAP_DETECTED, trigger="feed_connection_lost")
```

Symbols already in `GAP_DETECTED` (from a prior sequence gap) get no
trigger update — the SM history still attributes their state to
`seq_gap:...`, even though a connection drop is now also true. An
operator triaging the dashboard sees a stale reason.

**Fix sketch:** for non-HEALTHY symbols, append a `MetricEvent` (or
similar) recording that a connection drop also occurred. Don't try to
re-transition; the SM is correct. Just don't lose the audit trail.

Severity: MINOR.

---

#### R4-NEW-09 — Pass-3 findings remain unaddressed
**Files:** `massive_normalizer.py` (R3-INGEST-01, -02, -03, -06),
`massive_ws.py` (R3-INGEST-04), `core/state_machine.py` (R3-INGEST-05),
all r3-INGEST-NN MINORs.

Verified by direct inspection:

- `_is_duplicate` (`370–381`) still has no `seq_num == 0` guard ⇒
  R3-INGEST-01 (silent dedup of seq-zero events) **still active**.
- `Decimal(str(...))` (`166–167, 211, 289–290, 334`) is unchanged;
  `decimal.InvalidOperation` is not in the catch tuple at `179, 224,
  304, 349` ⇒ R3-INGEST-02 (NaN/Infinity acceptance, parser-thread
  crash on bad numerics) **still active**.
- `internal_seq = self._seq.next()` at `146, 197, 269, 320` still runs
  *before* event construction ⇒ R3-INGEST-03 (sequence holes) **still
  active**.
- `MassiveLiveFeed.start()` (`106–116`) does not drain `_queue` ⇒
  R3-INGEST-04 (queue restart bug) **still active**.
- `core/state_machine.py:158–162` still appends to history and
  reassigns `_state` *after* the callback loop ⇒ R3-INGEST-05
  (callback observes pre-transition state) **still active** (and is
  now reachable via R-INGEST-05's new `on_health_transition` wiring,
  so the hazard window is wider than before).
- `_mark_corrupted(msg.get("sym", "UNKNOWN"))` at `181, 226, 306, 351`
  still falls back to `"UNKNOWN"` ⇒ R3-INGEST-06 (synthetic stream
  collapse) **still active**.

This is not a "regression" — the fix commit was authored before the
pass-3 audit was written. But for purposes of the post-fix verdict,
all six MAJORs and ten MINORs from pass 3 carry over unchanged.

Severity: tracking.

---

### New MINORs

#### r4-NEW-01 — Stylistic: `on_health_transition` defined without surrounding blank lines
**File:** `massive_ws.py:99–104`.

```python
            yield item  # type: ignore[misc]
    def on_health_transition(self, callback: Callable[..., None]) -> None:
        """Register a callback for DataHealth transitions on any ingested symbol."""
        self._normalizer.on_health_transition(callback)
    # ── Lifecycle ────────────────────────────────────────────────────
```

No blank line between `events()` and `on_health_transition()`, and the
section comment that originally separated `events()` from the lifecycle
methods is now visually attached to `on_health_transition` rather than
the next method. Minor, but the reading flow suffers.

#### r4-NEW-02 — `_subscribe`'s "warn-on-partial" is undocumented in the `MarketDataSource` contract
**File:** `massive_ws.py:241–250`.

The new behavior — accept any non-zero number of channel
confirmations, log a warning if fewer than expected — is a real
operational choice (degraded-mode operation is preferable to
hard-failing the whole feed when one of 200 symbols is briefly
unsubscribable). It should be documented in the class docstring so
operators don't assume "subscribe succeeded" implies "all channels
confirmed."

#### r4-NEW-03 — `received_ns` is now a public field on `NBBOQuote` / `Trade` but is `None` for events constructed outside the normalizer
**File:** `core/events.py:69, 96`.

The default `int | None = None` preserves backward compatibility, but
any consumer that does `event.received_ns - event.exchange_timestamp_ns`
must guard against `None`. There is no documented contract that
ingestion always populates the field — only the convention that
`MassiveNormalizer` does so. Tests / fixtures elsewhere in the codebase
that construct events directly will produce `None` values that
propagate. Worth a docstring note (or, more strictly, making the field
required and updating call sites).

#### r4-NEW-04 — `notify_feed_interrupted` ignores the `_health_machines` lock (which doesn't exist)
**File:** `massive_normalizer.py:434–444`.

The method iterates `self._health_machines.get(sym)` from the WS
thread (the asyncio loop thread). Other writers — `_ws_quote`,
`_ws_trade` running in the same thread — are concurrent only with
themselves, so this is single-threaded by construction. **However**,
the *future* wiring of `on_health_transition` callbacks introduces a
plausible scenario where a callback synchronously enqueues a metric
event into a thread-safe sink, the sink's consumer runs on another
thread, and a subsequent reader of `normalizer.all_health()` from the
orchestrator thread observes a partially-mutated `_health_machines`
dict. None of this is reachable today; the constraint should be
documented in the normalizer's docstring before the surface ossifies.

---

### Updated finding inventory

| Pass | Verdict | BLOCKER | MAJOR | MINOR |
| --- | --- | --- | --- | --- |
| 1 | initial | 3 | 7 | 10 |
| 2 | residual | 1 | 6 | 10 |
| 3 | deepening | 0 | 6 | 10 |
| 4 | post-fix | 1 (R4-NEW-01) | 6 (R4-NEW-02..05, R4-NEW-08 + carry-over R4-NEW-09 ≡ pass-3 set) | 4 (r4-NEW-01..04) |

Carry-over: R3-INGEST-01..06 + r3-INGEST-01..10 from pass 3 (all
unchanged). Resolved by the fix commit: B-INGEST-01..03 (caveats above)
and R-INGEST-01..07 (caveats above).

**Net active findings on the post-fix tree:**

- 1 BLOCKER (R4-NEW-01: poisoned checkpoint on download failure).
- 12 MAJORs (six R4-NEW + six R3-INGEST carry-over).
- 14 MINORs (four r4-NEW + ten r3-INGEST carry-over).

### Updated verdict

The fix commit makes meaningful progress: every BLOCKER from pass 1 is
addressed, and the live-feed handshake is now correct. **But the
checkpoint logic now has a worse failure mode than before** (R4-NEW-01),
and the silent-feed-death class is only half-fixed (R4-NEW-04). The
backtest path therefore drops from "conditional PASS for short
windows" to **"FAIL until R4-NEW-01 is patched"** — a poisoned
checkpoint silently loses data on every retry, which is strictly
worse than the pre-fix "every retry re-downloads everything."

The live-readiness verdict is unchanged from pass 3: **FAIL** —
B-INGEST-02 and the live shutdown / queue-restart paths are still
gating, and R3-INGEST-02 (Decimal NaN / `InvalidOperation`) still
silently kills the parser thread, with R4-NEW-04 ensuring the
orchestrator isn't told.

Of the 19 MAJORs across all four passes, **the fix commit closed five
cleanly (R-INGEST-04, R-INGEST-06, plus the three pass-1 BLOCKERs
which were graded above MAJOR), partially closed two (R-INGEST-01,
R-INGEST-07), and introduced six new ones**. Net pre/post: roughly
unchanged in volume, but the *types* of bugs have shifted from
"documented contract not met" toward "recently-introduced state
poisoning and call-graph gaps" — a profile that is harder to detect
without targeted regression tests, of which there are zero.

### Recommended next-cycle priority order

1. **R4-NEW-01** (BLOCKER, checkpoint poisoning) — gate any backfill
   re-run on this. Trivial to fix, catastrophic if shipped.
2. **R4-NEW-04** (silent thread death gap) — call
   `notify_feed_interrupted` from `_run_loop`'s outer except.
3. **R3-INGEST-02** (Decimal NaN + InvalidOperation) — sole reason
   R4-NEW-04 matters today; both must land together.
4. **R3-INGEST-01** (seq-zero dedup trap) — silent stale-data
   delivery is still possible.
5. **R4-NEW-02 / R4-NEW-03** (callback semantics) — ship before any
   metrics consumer is wired.
6. **R4-NEW-05** (phantom SM transitions) — forensics / audit-trail
   correctness.
7. Tests for everything in the fix commit. **Zero regression coverage
   was added** for the eleven behavioral fixes.
