"""Massive normalizer (formerly Polygon.io) — transforms raw WebSocket and REST
wire formats into canonical NBBOQuote / Trade events.

Implements the MarketDataNormalizer protocol.  Single entry point for all
Massive market data.  Detects wire format via the ``source`` parameter
(``"massive_ws"`` vs ``"massive_rest"``).

Responsibilities (per data-engineering skill):
  - Parse raw JSON into typed events with full Massive field coverage
  - Assign correlation IDs at the ingestion boundary (invariant 13)
  - Track per-symbol sequence numbers for gap detection
  - Eliminate exact duplicates
  - Drive per-(symbol × feed-channel) DataHealth state machines, aggregated for API consumers
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.state_machine import StateMachine, TransitionRecord
from feelies.ingestion.data_integrity import (
    DataHealth,
    HaltSignal,
    classify_halt_status,
    create_data_integrity_machine,
)
from feelies.ingestion.ingest_health import merge_worst_health

logger = logging.getLogger(__name__)

_WS_SOURCE = "massive_ws"
_REST_SOURCE = "massive_rest"
_MS_TO_NS = 1_000_000


def _safe_price(value: object, *, allow_zero: bool = False) -> Decimal:
    """Parse a wire price into a finite, non-negative ``Decimal``.

    Raises ``ValueError`` on every failure mode the upstream catch tuple
    already understands:

    * ``decimal.InvalidOperation`` from malformed numerics (``"1.2.3"``,
      empty string) — wrapped so the parser thread does not die.
    * ``NaN`` / ``Infinity`` — silently propagating these into
      ``NBBOQuote.bid`` poisons ``bid > ask`` checks (NaN comparisons
      always return False) and ``(bid + ask) / 2`` mid-price math.
    * Negative prices — always invalid for both trade prints and NBBO
      sides.
    * Zero prices when ``allow_zero=False`` (the default, used for trade
      prints — equities never trade at zero and downstream cost / sizing
      math assumes ``price > 0``).  Callers parsing NBBO bid/ask must
      pass ``allow_zero=True``: auction snapshots and indicator quotes
      legitimately carry ``bid=0`` / ``ask=0`` on the wire.

    Wire fields are JSON-decoded as ``float`` / ``int`` / ``str``;
    ``str(...)`` round-trips int/Decimal cleanly but loses precision on
    floats.  We accept that float-round-trip is the caller's choice; this
    helper only enforces *value* validity, not encoding.
    """
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"unparseable Decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite price: {result}")
    if result < 0:
        raise ValueError(f"negative price: {result}")
    if not allow_zero and result == 0:
        raise ValueError(f"non-positive price: {result}")
    return result


def _safe_size(value: object) -> int:
    """Parse a wire size into a non-negative ``int``.

    ``int(...)`` already accepts strings and floats; we only reject
    negative results.  Zero is allowed (some wire feeds emit
    ``size=0`` for non-trade conditions or canceled prints).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"unparseable size: {value!r}")
    n = int(value)  # raises ValueError on garbage strings
    if n < 0:
        raise ValueError(f"negative size: {n}")
    return n


def _optional_wire_ts_ns(raw: object) -> int | None:
    """Coerce vendor timestamp to ns: values above 1e16 treated as ns, else ms."""
    if raw is None or isinstance(raw, bool):
        return None
    n: int
    if isinstance(raw, int):
        n = raw
    elif isinstance(raw, str):
        try:
            n = int(raw)
        except ValueError:
            return None
    else:
        return None
    if n > 10**16:
        return n
    return n * _MS_TO_NS


def _fingerprint_ws_quote(msg: dict) -> str:  # type: ignore[type-arg]
    """Stable hash of WS quote payload fields (sequence reuse detection)."""
    raw_c = msg.get("c")
    conditions: tuple[int, ...]
    if raw_c is not None and not isinstance(raw_c, list):
        conditions = (int(raw_c),)
    elif isinstance(raw_c, list):
        conditions = tuple(int(x) for x in raw_c)
    else:
        conditions = ()
    raw_i = msg.get("i")
    indicators = tuple(int(x) for x in raw_i) if isinstance(raw_i, list) else ()
    parts = (
        str(msg["bp"]),
        str(msg["ap"]),
        str(msg["bs"]),
        str(msg["as"]),
        int(msg.get("bx", 0)),
        int(msg.get("ax", 0)),
        int(msg.get("z", 0)),
        conditions,
        indicators,
        str(msg.get("participant_timestamp", "")),
        str(msg.get("trf_timestamp", "")),
        str(msg.get("ft", "")),
        str(msg.get("y", "")),
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def _fingerprint_ws_trade(msg: dict) -> str:  # type: ignore[type-arg]
    raw_c = msg.get("c")
    conditions = tuple(int(x) for x in raw_c) if isinstance(raw_c, list) else ()
    parts = (
        str(msg["p"]),
        str(msg["s"]),
        int(msg.get("x", 0)),
        str(msg.get("i", "")),
        int(msg.get("z", 0)),
        conditions,
        str(msg.get("trfi", "")),
        str(msg.get("trft", "")),
        str(msg.get("participant_timestamp", "")),
        str(msg.get("ft", "")),
        str(msg.get("correction", "")),
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def _fingerprint_rest_quote(rec: dict) -> str:  # type: ignore[type-arg]
    raw_cond = rec.get("conditions")
    conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()
    raw_ind = rec.get("indicators")
    indicators = tuple(int(x) for x in raw_ind) if isinstance(raw_ind, list) else ()
    # ``participant_timestamp`` and ``trf_timestamp`` are intentionally part
    # of the fingerprint so that a REST retransmission carrying the same
    # ``sequence_number`` but a corrected participant timestamp is treated
    # as a payload mismatch (CORRUPTED) rather than as an exact-duplicate
    # silent drop.  Mirrors the WS quote fingerprint (audit A4-MINOR).
    parts = (
        str(rec["bid_price"]),
        str(rec["ask_price"]),
        str(rec["bid_size"]),
        str(rec["ask_size"]),
        int(rec.get("bid_exchange", 0)),
        int(rec.get("ask_exchange", 0)),
        int(rec.get("tape", 0)),
        conditions,
        indicators,
        str(rec.get("participant_timestamp", "")),
        str(rec.get("trf_timestamp", "")),
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def _fingerprint_rest_trade(rec: dict) -> str:  # type: ignore[type-arg]
    raw_cond = rec.get("conditions")
    conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()
    parts = (
        str(rec["price"]),
        str(rec["size"]),
        int(rec.get("exchange", 0)),
        str(rec.get("id", "")),
        int(rec.get("tape", 0)),
        conditions,
        str(rec.get("trf_id", "")),
        str(rec.get("correction", "")),
        str(rec.get("participant_timestamp", "")),
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()


class MassiveNormalizer:
    """Transforms raw Massive messages into canonical market events.

    Wire-format routing:
      ``massive_ws``   — JSON array, each element has ``ev`` (Q or T).
                         Timestamps in milliseconds.
      ``massive_rest`` — Single JSON object with verbose field names.
                         Timestamps in nanoseconds.

    **Thread safety:** ``MassiveNormalizer`` is *not* thread-safe.  All
    mutable state (``_last_seen``, ``_health_machines``,
    ``_duplicates_filtered``, ``_unparseable_elements``, the per-(symbol,
    feed) ``StateMachine``s) is touched without locking.  Callers must
    invoke ``on_message`` and the management surface
    (``register_symbols`` / ``on_health_transition`` /
    ``notify_feed_interrupted``) from a single thread.  The two existing
    call sites — :class:`MassiveLiveFeed`'s asyncio thread and the
    historical ingestor's main thread — each own their normalizer
    instance.  (Audit r4-NEW-04.)
    """

    __slots__ = (
        "_clock",
        "_seq",
        "_health_machines",
        "_registered_symbols",
        "_transition_callback",
        "_last_seen",
        "_duplicates_filtered",
        "_unparseable_elements",
        "_oversized_frames",
        "_enable_rest_sequence_gap_detection",
        "_halt_on_codes",
        "_halt_off_codes",
        "_max_raw_frame_bytes",
        "_ts_lookback_ns",
        "_ts_lookahead_ns",
        "_warn_ambiguous_rest_logged",
    )

    _FEED_QUOTE = "quote"
    _FEED_TRADE = "trade"

    # Cap raw frame size before ``json.loads`` to bound parser memory and
    # rule out RecursionError from pathologically-nested upstream payloads
    # (audit r3-INGEST-01).  16 MB easily covers Massive's largest legitimate
    # WS batches; anything larger is treated as a feed bug.
    _DEFAULT_MAX_RAW_FRAME_BYTES = 16 * 1024 * 1024

    # Bound exchange timestamps to a window around the clock so a wire bug
    # producing ``t = 1e15`` (ms vs ns confusion) cannot inject events
    # 30,000 years in the future (audit r3-INGEST-02).  Defaults: 30 days
    # in the past, 1 hour in the future.
    _DEFAULT_TS_LOOKBACK_NS = 30 * 24 * 3600 * 1_000_000_000
    _DEFAULT_TS_LOOKAHEAD_NS = 3600 * 1_000_000_000

    def __init__(
        self,
        clock: Clock,
        transition_callback: Callable[[TransitionRecord], None] | None = None,
        *,
        enable_rest_sequence_gap_detection: bool = False,
        halt_on_codes: frozenset[int] | None = None,
        halt_off_codes: frozenset[int] | None = None,
        max_raw_frame_bytes: int = _DEFAULT_MAX_RAW_FRAME_BYTES,
    ) -> None:
        self._clock = clock
        self._seq = SequenceGenerator(start=1)
        # BT-5: tape condition codes that mark an LULD / regulatory halt
        # on (``halt_on_codes``) and resume (``halt_off_codes``).  Empty ⇒
        # halt detection is inert (no DataHealth.HALTED transitions).
        self._halt_on_codes: frozenset[int] = halt_on_codes or frozenset()
        self._halt_off_codes: frozenset[int] = halt_off_codes or frozenset()
        self._health_machines: dict[tuple[str, str], StateMachine[DataHealth]] = {}
        self._registered_symbols: frozenset[str] = frozenset()
        self._transition_callback = transition_callback
        # Keyed by (symbol, feed_type) — quotes and trades have independent
        # Massive sequence_number spaces and must be tracked separately to
        # avoid false dedup and spurious gap detection when interleaved.
        # Value: (sequence_number, exchange_timestamp_ns, content_fingerprint).
        self._last_seen: dict[tuple[str, str], tuple[int, int, str]] = {}
        self._duplicates_filtered: int = 0
        self._unparseable_elements: int = 0
        self._oversized_frames: int = 0
        # Historical REST rows are usually *thinned* (non-contiguous vendor
        # sequence_number).  Default False keeps ingest usable; set True only when
        # the REST stream is full-tick contiguous (or for experiments).
        self._enable_rest_sequence_gap_detection = enable_rest_sequence_gap_detection
        self._max_raw_frame_bytes = max_raw_frame_bytes
        # Live timestamp window — computed lazily against the injected
        # clock so that ``SimulatedClock(start_ns=0)`` deployments (replay)
        # keep a wide acceptance band rather than rejecting every event.
        self._ts_lookback_ns = self._DEFAULT_TS_LOOKBACK_NS
        self._ts_lookahead_ns = self._DEFAULT_TS_LOOKAHEAD_NS
        self._warn_ambiguous_rest_logged: bool = False

    # ── MarketDataNormalizer protocol ────────────────────────────────

    def on_message(
        self,
        raw: bytes,
        received_ns: int,
        source: str,
    ) -> Sequence[NBBOQuote | Trade]:
        # Cap raw payload size and catch ``RecursionError`` from
        # pathologically-nested JSON so a single bad frame never kills
        # the parser thread (audit r3-INGEST-01, M2/M3 follow-on).
        if len(raw) > self._max_raw_frame_bytes:
            self._oversized_frames += 1
            logger.warning(
                "massive_normalizer: %d-byte frame from %s exceeds limit %d — dropping",
                len(raw),
                source,
                self._max_raw_frame_bytes,
            )
            return []
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            logger.warning("massive_normalizer: unparseable message from %s", source)
            return []

        if source == _WS_SOURCE:
            return self._parse_ws(data, received_ns)
        if source == _REST_SOURCE:
            return self._parse_rest(data, received_ns)

        logger.warning("massive_normalizer: unknown source %r", source)
        return []

    def health(self, symbol: str) -> DataHealth:
        """Aggregate :class:`DataHealth` for a symbol (worst across feeds).

        Returns ``HEALTHY`` for symbols that have **never been seen** —
        unseen and "data flowing fine" are indistinguishable through this
        accessor (audit r3-INGEST-04).  Use :meth:`all_health` plus
        :meth:`register_symbols` to distinguish "subscribed but not yet
        receiving data" from "actively healthy" — registered symbols
        appear in ``all_health()`` even before their first message, while
        unregistered unseen symbols do not.
        """
        q = self._health_machines.get((symbol, self._FEED_QUOTE))
        t = self._health_machines.get((symbol, self._FEED_TRADE))
        states: list[DataHealth] = []
        if q is not None:
            states.append(q.state)
        if t is not None:
            states.append(t.state)
        if not states:
            return DataHealth.HEALTHY
        out = states[0]
        for st in states[1:]:
            out = merge_worst_health(out, st)
        return out

    def register_symbols(self, symbols: frozenset[str] | set[str]) -> None:
        """Pre-register symbols so they appear in ``all_health()`` as
        HEALTHY before any live data arrives (e.g. PAPER cold start).
        """
        self._registered_symbols = frozenset(symbols)

    def all_health(self) -> dict[str, DataHealth]:
        seen: set[str] = {k[0] for k in self._health_machines}
        symbols = seen | self._registered_symbols
        return {sym: self.health(sym) for sym in sorted(symbols)}

    # ── WebSocket parsing ────────────────────────────────────────────

    def _parse_ws(
        self,
        data: object,
        received_ns: int,
    ) -> list[NBBOQuote | Trade]:
        messages = data if isinstance(data, list) else [data]
        results: list[NBBOQuote | Trade] = []

        for msg in messages:
            if not isinstance(msg, dict):
                # Non-dict elements in a status/data array are wire-bug-
                # like (e.g. a stray string).  Count them so operators can
                # tell a clean-but-empty stream from a buggy one (audit
                # r3-INGEST-07).
                self._unparseable_elements += 1
                continue
            ev = msg.get("ev")
            event: NBBOQuote | Trade | None
            if ev == "Q":
                event = self._ws_quote(msg, received_ns)
                if event is not None:
                    results.append(event)
            elif ev == "T":
                event = self._ws_trade(msg, received_ns)
                if event is not None:
                    results.append(event)

        return results

    def _ws_quote(self, msg: dict, received_ns: int) -> NBBOQuote | None:  # type: ignore[type-arg]
        # Field-parsing order matters: everything that can raise on a bad
        # payload runs *before* we mutate dedup / SM state (closes the
        # "phantom gap transition for an event that never emitted" hazard
        # from pass-4 R4-NEW-05) and *before* the internal sequence is
        # consumed (closes pass-3 R3-INGEST-03 — sequence holes).
        try:
            symbol = msg["sym"]
            exchange_ts_ns = int(msg["t"]) * _MS_TO_NS
            self._check_exchange_ts_in_range(exchange_ts_ns)
            seq_num = int(msg.get("q", 0))
            fp = _fingerprint_ws_quote(msg)

            if self._reject_sequence_reuse(symbol, self._FEED_QUOTE, seq_num, fp):
                return None

            raw_c = msg.get("c")
            conditions: tuple[int, ...]
            if raw_c is not None and not isinstance(raw_c, list):
                conditions = (int(raw_c),)
            elif isinstance(raw_c, list):
                conditions = tuple(int(x) for x in raw_c)
            else:
                conditions = ()

            raw_i = msg.get("i")
            indicators = tuple(int(x) for x in raw_i) if isinstance(raw_i, list) else ()

            part_ns: int | None = None
            for key in ("participant_timestamp", "ft"):
                part_ns = _optional_wire_ts_ns(msg.get(key))
                if part_ns is not None:
                    break
            trf_quote_ns: int | None = None
            for key in ("trf_timestamp", "y"):
                trf_quote_ns = _optional_wire_ts_ns(msg.get(key))
                if trf_quote_ns is not None:
                    break

            # Price / size validation — raises on NaN, Infinity, negative
            # price, or unparseable Decimal.  ``allow_zero=True`` because
            # auction snapshots and indicator quotes legitimately carry
            # ``bid=0`` / ``ask=0`` on the wire.  All before state mutation.
            bid = _safe_price(msg["bp"], allow_zero=True)
            ask = _safe_price(msg["ap"], allow_zero=True)
            bid_size = _safe_size(msg["bs"])
            ask_size = _safe_size(msg["as"])
            bid_exchange = int(msg.get("bx", 0))
            ask_exchange = int(msg.get("ax", 0))
            tape = int(msg.get("z", 0))

            # All parsing succeeded — commit dedup state, fire SM transitions,
            # consume the internal sequence, build the canonical event.
            prev = self._last_seen.get((symbol, self._FEED_QUOTE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_QUOTE, seq_num, exchange_ts_ns, fp)
            self._check_gap(symbol, self._FEED_QUOTE, seq_num, prev_seq)
            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

            return NBBOQuote(
                timestamp_ns=exchange_ts_ns,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                bid_exchange=bid_exchange,
                ask_exchange=ask_exchange,
                exchange_timestamp_ns=exchange_ts_ns,
                conditions=conditions,
                indicators=indicators,
                sequence_number=seq_num,
                tape=tape,
                participant_timestamp_ns=part_ns,
                trf_timestamp_ns=trf_quote_ns,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            logger.warning("massive_normalizer: bad WS quote: %s", exc)
            self._mark_corrupted(msg.get("sym", "UNKNOWN"))
            return None

    def _ws_trade(self, msg: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        # See ``_ws_quote`` for the field-parsing-before-state-mutation
        # rationale (M3 / M4 / R4-NEW-05 from the cumulative audit).
        try:
            symbol = msg["sym"]
            exchange_ts_ns = int(msg["t"]) * _MS_TO_NS
            self._check_exchange_ts_in_range(exchange_ts_ns)
            seq_num = int(msg.get("q", 0))
            fp = _fingerprint_ws_trade(msg)

            if self._reject_sequence_reuse(symbol, self._FEED_TRADE, seq_num, fp):
                return None

            raw_c = msg.get("c")
            conditions = tuple(int(x) for x in raw_c) if isinstance(raw_c, list) else ()

            raw_trft = msg.get("trft")
            trf_ts = int(raw_trft) * _MS_TO_NS if raw_trft is not None else None

            part_trade: int | None = None
            for key in ("participant_timestamp", "ft"):
                part_trade = _optional_wire_ts_ns(msg.get(key))
                if part_trade is not None:
                    break
            corr_raw = msg.get("correction")
            correction = int(corr_raw) if corr_raw is not None else None

            price = _safe_price(msg["p"])
            size = _safe_size(msg["s"])
            exchange = int(msg.get("x", 0))
            tape = int(msg.get("z", 0))
            trf_id = int(msg["trfi"]) if "trfi" in msg else None

            # All parsing succeeded — commit dedup + halt status before
            # the SM transitions and sequence consumption fire.
            prev = self._last_seen.get((symbol, self._FEED_TRADE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_TRADE, seq_num, exchange_ts_ns, fp)
            self._check_gap(symbol, self._FEED_TRADE, seq_num, prev_seq)
            self._apply_halt_status(symbol, conditions)
            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

            return Trade(
                timestamp_ns=exchange_ts_ns,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                price=price,
                size=size,
                exchange=exchange,
                trade_id=str(msg.get("i", "")),
                exchange_timestamp_ns=exchange_ts_ns,
                conditions=conditions,
                decimal_size=msg.get("ds"),
                sequence_number=seq_num,
                tape=tape,
                trf_id=trf_id,
                trf_timestamp_ns=trf_ts,
                participant_timestamp_ns=part_trade,
                correction=correction,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            logger.warning("massive_normalizer: bad WS trade: %s", exc)
            self._mark_corrupted(msg.get("sym", "UNKNOWN"))
            return None

    # ── REST parsing ─────────────────────────────────────────────────

    def _parse_rest(
        self,
        data: object,
        received_ns: int,
    ) -> list[NBBOQuote | Trade]:
        if not isinstance(data, dict):
            return []

        # REST records are passed individually by the ingestor.
        # Detect type by field presence.  An ambiguous record carrying
        # *both* quote and trade fields is classified as a quote (the
        # historical default) but flagged at WARN level so diagnostic
        # tooling can pick it up (audit r3-INGEST-03).
        event: NBBOQuote | Trade | None
        has_quote_keys = "bid_price" in data or "ask_price" in data
        has_trade_keys = "price" in data
        if has_quote_keys and has_trade_keys and not self._warn_ambiguous_rest_logged:
            logger.warning(
                "massive_normalizer: ambiguous REST record carries both "
                "quote and trade fields (keys: %s) — classifying as quote "
                "and dropping trade-side data.  This warning is suppressed "
                "after the first occurrence per normalizer.",
                sorted(data.keys()),
            )
            self._warn_ambiguous_rest_logged = True
        if has_quote_keys:
            event = self._rest_quote(data, received_ns)
            return [event] if event is not None else []
        if has_trade_keys:
            event = self._rest_trade(data, received_ns)
            return [event] if event is not None else []

        logger.warning(
            "massive_normalizer: unrecognized REST record (keys: %s)",
            sorted(data.keys()),
        )
        return []

    def _rest_quote(self, rec: dict, received_ns: int) -> NBBOQuote | None:  # type: ignore[type-arg]
        # See ``_ws_quote`` for the field-parsing-before-state-mutation
        # rationale (M3 / M4 / R4-NEW-05 from the cumulative audit).
        try:
            symbol = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            # NOTE: ``_check_exchange_ts_in_range`` deliberately not invoked
            # on REST paths.  Historical REST rows carry exchange timestamps
            # for the requested session, which has no relationship to
            # ``clock.now_ns()`` for either a wall clock or a wall-like
            # ``SimulatedClock``.  Enforcing the 30-day past / 1-hour
            # future window here would reject every legitimate backfill
            # row outside that window.  The ms-vs-ns confusion guard
            # (r3-INGEST-02) remains active on the WS parse paths, which
            # is the regime where the heuristic applies.
            seq_num = int(rec.get("sequence_number", 0))
            fp = _fingerprint_rest_quote(rec)

            if self._reject_sequence_reuse(symbol, self._FEED_QUOTE, seq_num, fp):
                return None

            raw_cond = rec.get("conditions")
            conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

            raw_ind = rec.get("indicators")
            indicators = tuple(int(x) for x in raw_ind) if isinstance(raw_ind, list) else ()

            raw_part = rec.get("participant_timestamp")
            part_ts = int(raw_part) if raw_part is not None else None

            raw_trf = rec.get("trf_timestamp")
            trf_ts = int(raw_trf) if raw_trf is not None else None

            bid = _safe_price(rec["bid_price"], allow_zero=True)
            ask = _safe_price(rec["ask_price"], allow_zero=True)
            bid_size = _safe_size(rec["bid_size"])
            ask_size = _safe_size(rec["ask_size"])
            bid_exchange = int(rec.get("bid_exchange", 0))
            ask_exchange = int(rec.get("ask_exchange", 0))
            tape = int(rec.get("tape", 0))

            prev = self._last_seen.get((symbol, self._FEED_QUOTE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_QUOTE, seq_num, sip_ts, fp)
            if self._enable_rest_sequence_gap_detection:
                self._check_gap(symbol, self._FEED_QUOTE, seq_num, prev_seq)
            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, sip_ts, internal_seq)

            return NBBOQuote(
                timestamp_ns=sip_ts,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                bid_exchange=bid_exchange,
                ask_exchange=ask_exchange,
                exchange_timestamp_ns=sip_ts,
                conditions=conditions,
                indicators=indicators,
                sequence_number=seq_num,
                tape=tape,
                participant_timestamp_ns=part_ts,
                trf_timestamp_ns=trf_ts,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            logger.warning("massive_normalizer: bad REST quote: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    def _rest_trade(self, rec: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        # See ``_ws_quote`` for the field-parsing-before-state-mutation
        # rationale (M3 / M4 / R4-NEW-05 from the cumulative audit).
        try:
            symbol = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            # See ``_rest_quote`` for why ``_check_exchange_ts_in_range``
            # is not invoked on REST paths.
            seq_num = int(rec.get("sequence_number", 0))
            fp = _fingerprint_rest_trade(rec)

            if self._reject_sequence_reuse(symbol, self._FEED_TRADE, seq_num, fp):
                return None

            raw_cond = rec.get("conditions")
            conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

            raw_part = rec.get("participant_timestamp")
            part_ts = int(raw_part) if raw_part is not None else None

            raw_trf = rec.get("trf_timestamp")
            trf_ts = int(raw_trf) if raw_trf is not None else None

            price = _safe_price(rec["price"])
            size = _safe_size(rec["size"])
            exchange = int(rec.get("exchange", 0))
            tape = int(rec.get("tape", 0))
            trf_id = int(rec["trf_id"]) if "trf_id" in rec else None
            correction = int(rec["correction"]) if "correction" in rec else None

            prev = self._last_seen.get((symbol, self._FEED_TRADE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_TRADE, seq_num, sip_ts, fp)
            if self._enable_rest_sequence_gap_detection:
                self._check_gap(symbol, self._FEED_TRADE, seq_num, prev_seq)
            self._apply_halt_status(symbol, conditions)
            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, sip_ts, internal_seq)

            return Trade(
                timestamp_ns=sip_ts,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                price=price,
                size=size,
                exchange=exchange,
                trade_id=str(rec.get("id", "")),
                exchange_timestamp_ns=sip_ts,
                conditions=conditions,
                decimal_size=rec.get("decimal_size"),
                sequence_number=seq_num,
                tape=tape,
                trf_id=trf_id,
                trf_timestamp_ns=trf_ts,
                participant_timestamp_ns=part_ts,
                correction=correction,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            logger.warning("massive_normalizer: bad REST trade: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    # Heuristic threshold for "this clock looks like wall time" — only
    # then do we enforce the wire-timestamp sanity window.  ``2*10**17``
    # ns is ~1976, well after the Unix epoch and well below any plausible
    # SimulatedClock counter (most test fixtures use values < 1e10 ns).
    _WALL_CLOCK_HEURISTIC_NS = 2 * 10**17

    def _check_exchange_ts_in_range(self, ts_ns: int) -> None:
        """Raise ``ValueError`` when a wire timestamp is outside the
        plausible window around the current clock.

        Implements audit r3-INGEST-02 — a wire payload producing
        ``t = 1e15`` (ms-vs-ns confusion) would otherwise inject events
        ~30,000 years in the future, silently breaking any consumer that
        compares event time to wall time.  The window is generous on
        purpose: ``_DEFAULT_TS_LOOKBACK_NS`` (30 days) past +
        ``_DEFAULT_TS_LOOKAHEAD_NS`` (1 hour) future, both configurable.

        Inert when the injected clock is *not* a wall clock — a
        ``SimulatedClock`` initialized at a small counter (replay, test
        fixtures) has no relationship to the wire timestamps and the
        check would false-positive every event.  The heuristic
        ``_WALL_CLOCK_HEURISTIC_NS`` distinguishes the two regimes.
        """
        now = self._clock.now_ns()
        if now < self._WALL_CLOCK_HEURISTIC_NS:
            return
        if ts_ns < now - self._ts_lookback_ns:
            raise ValueError(
                f"exchange_timestamp_ns {ts_ns} is {(now - ts_ns) / 1e9:.0f}s "
                f"in the past (window: {self._ts_lookback_ns / 1e9:.0f}s)"
            )
        if ts_ns > now + self._ts_lookahead_ns:
            raise ValueError(
                f"exchange_timestamp_ns {ts_ns} is {(ts_ns - now) / 1e9:.0f}s "
                f"in the future (window: {self._ts_lookahead_ns / 1e9:.0f}s)"
            )

    # ── Gap detection / dedup / health ───────────────────────────────

    def _ensure_health_machine(
        self,
        symbol: str,
        feed_type: str,
    ) -> StateMachine[DataHealth]:
        key = (symbol, feed_type)
        sm = self._health_machines.get(key)
        if sm is None:
            sm = create_data_integrity_machine(
                symbol,
                self._clock,
                channel=feed_type,
            )
            # Always register the stable dispatcher; the live callback is
            # read lazily from ``self._transition_callback`` so that
            # :meth:`on_health_transition` can rebind without touching
            # any per-machine state (closes pass-4 R4-NEW-02 / R4-NEW-03 —
            # additive vs. replacing semantics and non-idempotency).
            sm.on_transition(self._dispatch_transition)
            self._health_machines[key] = sm
        return sm

    def _dispatch_transition(self, record: TransitionRecord) -> None:
        """Single per-SM callback that lazily reads the live subscriber.

        Registered once per ``DataHealth`` machine at creation time.
        Reading ``self._transition_callback`` here means
        :meth:`on_health_transition` rebinds the subscriber by mutating a
        single attribute; existing and future machines see the change
        identically.
        """
        cb = self._transition_callback
        if cb is not None:
            cb(record)

    @property
    def duplicates_filtered(self) -> int:
        """Total number of exact-duplicate messages filtered across all symbols."""
        return self._duplicates_filtered

    @property
    def unparseable_elements(self) -> int:
        """Non-dict elements seen inside WS batches (audit r3-INGEST-07).

        Distinguishes a clean-but-empty stream from a buggy one without
        scraping logs.
        """
        return self._unparseable_elements

    @property
    def oversized_frames(self) -> int:
        """Raw WS / REST frames exceeding ``max_raw_frame_bytes``.

        Counts payloads rejected before ``json.loads`` is called (audit
        r3-INGEST-01).  A non-zero value indicates either a feed bug or
        an upstream-side configuration mismatch.
        """
        return self._oversized_frames

    def _reject_sequence_reuse(
        self,
        symbol: str,
        feed_type: str,
        seq_num: int,
        content_fp: str,
    ) -> bool:
        """Drop replays of the same vendor sequence (exact dup) or flag corruption.

        When ``sequence_number`` matches the previous row for this feed but the
        fingerprint differs, the stream is inconsistent — emit nothing and
        transition to ``CORRUPTED``.

        Returns True when this message must not produce an event.
        """
        if seq_num == 0:
            return False
        prev = self._last_seen.get((symbol, feed_type))
        if prev is None:
            return False
        prev_seq, _prev_ts, prev_fp = prev
        if prev_seq == 0 or prev_seq != seq_num:
            return False
        if prev_fp == content_fp:
            self._duplicates_filtered += 1
            return True
        logger.warning(
            "massive_normalizer: sequence_number %s reused with differing payload (%s %s)",
            seq_num,
            symbol,
            feed_type,
        )
        self._mark_corrupted(symbol, trigger="sequence_reuse_payload_mismatch")
        return True

    def _check_gap(self, symbol: str, feed_type: str, seq_num: int, prev_seq: int) -> None:
        """Fire DataHealth transitions based on sequence-number continuity.

        ``prev_seq`` must be captured by the caller *before* calling
        ``_update_last_seen`` so that any ``on_transition`` callback
        observes the already-updated ``_last_seen`` state.
        """
        if seq_num == 0 or prev_seq == 0:
            return

        sm = self._ensure_health_machine(symbol, feed_type)

        if seq_num > prev_seq + 1:
            if sm.state == DataHealth.HEALTHY:
                sm.transition(
                    DataHealth.GAP_DETECTED,
                    trigger=f"seq_gap:{feed_type}:{prev_seq}->{seq_num}",
                )
            logger.info(
                "massive_normalizer: gap detected for %s/%s: %d -> %d",
                symbol,
                feed_type,
                prev_seq,
                seq_num,
            )
        elif seq_num == prev_seq + 1 and sm.state == DataHealth.GAP_DETECTED:
            sm.transition(
                DataHealth.HEALTHY,
                trigger=f"seq_continuity_resumed:{feed_type}:{seq_num}",
            )
            logger.info(
                "massive_normalizer: gap resolved for %s/%s at seq %d",
                symbol,
                feed_type,
                seq_num,
            )

    def _update_last_seen(
        self,
        symbol: str,
        feed_type: str,
        seq_num: int,
        exchange_ts_ns: int,
        content_fp: str,
    ) -> None:
        self._last_seen[(symbol, feed_type)] = (seq_num, exchange_ts_ns, content_fp)
        self._ensure_health_machine(symbol, feed_type)

    def _apply_halt_status(
        self,
        symbol: str,
        conditions: tuple[int, ...],
    ) -> None:
        """Transition the trade-feed DataHealth machine on halt-on / off (BT-5).

        Halts arrive on the trade tape, so only the trade-feed machine is
        driven; ``health(symbol)`` reports HALTED via ``merge_worst_health``
        regardless of the quote feed's state, and a resume cleanly returns
        the symbol to its quote-feed health.  Inert when no codes configured.
        """
        status = classify_halt_status(
            conditions,
            self._halt_on_codes,
            self._halt_off_codes,
        )
        if status is None:
            return
        sm = self._ensure_health_machine(symbol, self._FEED_TRADE)
        if status is HaltSignal.HALT_ON:
            if sm.state != DataHealth.HALTED and sm.can_transition(
                DataHealth.HALTED,
            ):
                sm.transition(DataHealth.HALTED, trigger="luld_halt_on")
        elif sm.state == DataHealth.HALTED and sm.can_transition(
            DataHealth.HEALTHY,
        ):
            sm.transition(DataHealth.HEALTHY, trigger="luld_halt_off")

    def _mark_corrupted(self, symbol: str, trigger: str = "parse_error") -> None:
        if not symbol or symbol == "UNKNOWN":
            logger.warning(
                "massive_normalizer: parse error for indeterminate symbol — "
                "skipping DataHealth CORRUPTED (no usable ticker/sym)",
            )
            return
        for ft in (self._FEED_QUOTE, self._FEED_TRADE):
            sm = self._ensure_health_machine(symbol, ft)
            if sm.can_transition(DataHealth.CORRUPTED):
                sm.transition(DataHealth.CORRUPTED, trigger=trigger)

    def on_health_transition(self, callback: Callable[[TransitionRecord], None]) -> None:
        """Bind the callback invoked on every :class:`DataHealth` transition.

        Replaces the previously-bound callback (including the one passed
        to ``__init__``).  Idempotent: calling twice with the same
        callable is a no-op.  Both already-created and future per-symbol
        state machines dispatch through a stable internal forwarder
        (:meth:`_dispatch_transition`) that lazily reads this attribute,
        so binding here applies uniformly without re-touching any
        machine's own callback list.
        """
        self._transition_callback = callback

    def notify_feed_interrupted(self, symbols: Sequence[str]) -> None:
        """Transition HEALTHY symbols to GAP_DETECTED on feed connection loss.

        Called by the WS transport layer so that DataHealth escalates
        immediately rather than waiting for the next message to reveal
        the gap via sequence-number discontinuity.
        """
        for sym in symbols:
            for ft in (self._FEED_QUOTE, self._FEED_TRADE):
                sm = self._ensure_health_machine(sym, ft)
                if sm.state == DataHealth.HEALTHY:
                    sm.transition(
                        DataHealth.GAP_DETECTED,
                        trigger="feed_connection_lost",
                    )
