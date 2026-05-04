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
