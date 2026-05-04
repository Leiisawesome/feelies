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
  - Drive per-symbol DataHealth state machines
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.state_machine import StateMachine, TransitionRecord
from feelies.ingestion.data_integrity import (
    DataHealth,
    create_data_integrity_machine,
)

logger = logging.getLogger(__name__)

_WS_SOURCE = "massive_ws"
_REST_SOURCE = "massive_rest"
_MS_TO_NS = 1_000_000


class MassiveNormalizer:
    """Transforms raw Massive messages into canonical market events.

    Wire-format routing:
      ``massive_ws``   — JSON array, each element has ``ev`` (Q or T).
                         Timestamps in milliseconds.
      ``massive_rest`` — Single JSON object with verbose field names.
                         Timestamps in nanoseconds.
    """

    __slots__ = (
        "_clock",
        "_seq",
        "_health_machines",
        "_transition_callback",
        "_last_seen",
        "_duplicates_filtered",
    )

    _FEED_QUOTE = "quote"
    _FEED_TRADE = "trade"

    def __init__(
        self,
        clock: Clock,
        transition_callback: Callable[[TransitionRecord], None] | None = None,
    ) -> None:
        self._clock = clock
        self._seq = SequenceGenerator()
        self._health_machines: dict[str, StateMachine[DataHealth]] = {}
        self._transition_callback = transition_callback
        # Keyed by (symbol, feed_type) — quotes and trades have independent
        # Massive sequence_number spaces and must be tracked separately to
        # avoid false dedup and spurious gap detection when interleaved.
        self._last_seen: dict[tuple[str, str], tuple[int, int]] = {}
        self._duplicates_filtered: int = 0

    # ── MarketDataNormalizer protocol ────────────────────────────────

    def on_message(
        self,
        raw: bytes,
        received_ns: int,
        source: str,
    ) -> Sequence[NBBOQuote | Trade]:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("massive_normalizer: unparseable message from %s", source)
            return []

        if source == _WS_SOURCE:
            return self._parse_ws(data, received_ns)
        if source == _REST_SOURCE:
            return self._parse_rest(data, received_ns)

        logger.warning("massive_normalizer: unknown source %r", source)
        return []

    def health(self, symbol: str) -> DataHealth:
        sm = self._health_machines.get(symbol)
        if sm is None:
            return DataHealth.HEALTHY
        return sm.state

    def all_health(self) -> dict[str, DataHealth]:
        return {sym: sm.state for sym, sm in self._health_machines.items()}

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
        try:
            symbol: str = msg["sym"]
            exchange_ts_ns = int(msg["t"]) * _MS_TO_NS
            seq_num = int(msg.get("q", 0))

            if self._is_duplicate(symbol, self._FEED_QUOTE, seq_num, exchange_ts_ns):
                return None
            prev = self._last_seen.get((symbol, self._FEED_QUOTE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_QUOTE, seq_num, exchange_ts_ns)
            self._check_gap(symbol, self._FEED_QUOTE, seq_num, prev_seq)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

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

            return NBBOQuote(
                timestamp_ns=exchange_ts_ns,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                bid=Decimal(str(msg["bp"])),
                ask=Decimal(str(msg["ap"])),
                bid_size=int(msg["bs"]),
                ask_size=int(msg["as"]),
                bid_exchange=int(msg.get("bx", 0)),
                ask_exchange=int(msg.get("ax", 0)),
                exchange_timestamp_ns=exchange_ts_ns,
                conditions=conditions,
                indicators=indicators,
                sequence_number=seq_num,
                tape=int(msg.get("z", 0)),
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("massive_normalizer: bad WS quote: %s", exc)
            self._mark_corrupted(msg.get("sym", "UNKNOWN"))
            return None

    def _ws_trade(self, msg: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        try:
            symbol: str = msg["sym"]
            exchange_ts_ns = int(msg["t"]) * _MS_TO_NS
            seq_num = int(msg.get("q", 0))

            if self._is_duplicate(symbol, self._FEED_TRADE, seq_num, exchange_ts_ns):
                return None
            prev = self._last_seen.get((symbol, self._FEED_TRADE))
            prev_seq = prev[0] if prev is not None else 0
            self._update_last_seen(symbol, self._FEED_TRADE, seq_num, exchange_ts_ns)
            self._check_gap(symbol, self._FEED_TRADE, seq_num, prev_seq)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

            raw_c = msg.get("c")
            conditions = tuple(int(x) for x in raw_c) if isinstance(raw_c, list) else ()

            raw_trft = msg.get("trft")
            trf_ts = int(raw_trft) * _MS_TO_NS if raw_trft is not None else None

            return Trade(
                timestamp_ns=exchange_ts_ns,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                price=Decimal(str(msg["p"])),
                size=int(msg["s"]),
                exchange=int(msg.get("x", 0)),
                trade_id=str(msg.get("i", "")),
                exchange_timestamp_ns=exchange_ts_ns,
                conditions=conditions,
                decimal_size=msg.get("ds"),
                sequence_number=seq_num,
                tape=int(msg.get("z", 0)),
                trf_id=int(msg["trfi"]) if "trfi" in msg else None,
                trf_timestamp_ns=trf_ts,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError) as exc:
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
        # Detect type by field presence.
        event: NBBOQuote | Trade | None
        if "bid_price" in data or "ask_price" in data:
            event = self._rest_quote(data, received_ns)
            return [event] if event is not None else []
        if "price" in data:
            event = self._rest_trade(data, received_ns)
            return [event] if event is not None else []

        logger.warning(
            "massive_normalizer: unrecognized REST record (keys: %s)",
            sorted(data.keys()),
        )
        return []

    def _rest_quote(self, rec: dict, received_ns: int) -> NBBOQuote | None:  # type: ignore[type-arg]
        try:
            symbol: str = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            seq_num = int(rec.get("sequence_number", 0))

            if self._is_duplicate(symbol, self._FEED_QUOTE, seq_num, sip_ts):
                return None
            # REST historical responses are thinned: each row keeps the original
            # SIP sequence_number but omits intervening ticks, so consecutive rows
            # routinely jump by ≫1 — unlike the live WebSocket feed. Gap detection
            # would falsely flag almost every symbol (see AUDIT / data_integrity).
            self._update_last_seen(symbol, self._FEED_QUOTE, seq_num, sip_ts)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, sip_ts, internal_seq)

            raw_cond = rec.get("conditions")
            conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

            raw_ind = rec.get("indicators")
            indicators = tuple(int(x) for x in raw_ind) if isinstance(raw_ind, list) else ()

            raw_part = rec.get("participant_timestamp")
            part_ts = int(raw_part) if raw_part is not None else None

            raw_trf = rec.get("trf_timestamp")
            trf_ts = int(raw_trf) if raw_trf is not None else None

            return NBBOQuote(
                timestamp_ns=sip_ts,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                bid=Decimal(str(rec["bid_price"])),
                ask=Decimal(str(rec["ask_price"])),
                bid_size=int(rec["bid_size"]),
                ask_size=int(rec["ask_size"]),
                bid_exchange=int(rec.get("bid_exchange", 0)),
                ask_exchange=int(rec.get("ask_exchange", 0)),
                exchange_timestamp_ns=sip_ts,
                conditions=conditions,
                indicators=indicators,
                sequence_number=seq_num,
                tape=int(rec.get("tape", 0)),
                participant_timestamp_ns=part_ts,
                trf_timestamp_ns=trf_ts,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("massive_normalizer: bad REST quote: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    def _rest_trade(self, rec: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        try:
            symbol: str = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            seq_num = int(rec.get("sequence_number", 0))

            if self._is_duplicate(symbol, self._FEED_TRADE, seq_num, sip_ts):
                return None
            # Same thinned-stream semantics as quotes (``_rest_quote``).
            self._update_last_seen(symbol, self._FEED_TRADE, seq_num, sip_ts)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, sip_ts, internal_seq)

            raw_cond = rec.get("conditions")
            conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

            raw_part = rec.get("participant_timestamp")
            part_ts = int(raw_part) if raw_part is not None else None

            return Trade(
                timestamp_ns=sip_ts,
                correlation_id=cid,
                sequence=internal_seq,
                symbol=symbol,
                price=Decimal(str(rec["price"])),
                size=int(rec["size"]),
                exchange=int(rec.get("exchange", 0)),
                trade_id=str(rec.get("id", "")),
                exchange_timestamp_ns=sip_ts,
                conditions=conditions,
                decimal_size=rec.get("decimal_size"),
                sequence_number=seq_num,
                tape=int(rec.get("tape", 0)),
                trf_id=int(rec["trf_id"]) if "trf_id" in rec else None,
                trf_timestamp_ns=None,
                participant_timestamp_ns=part_ts,
                correction=int(rec["correction"]) if "correction" in rec else None,
                received_ns=received_ns,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("massive_normalizer: bad REST trade: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    # ── Gap detection / dedup / health ───────────────────────────────

    def _ensure_health_machine(self, symbol: str) -> StateMachine[DataHealth]:
        sm = self._health_machines.get(symbol)
        if sm is None:
            sm = create_data_integrity_machine(symbol, self._clock)
            if self._transition_callback is not None:
                sm.on_transition(self._transition_callback)
            self._health_machines[symbol] = sm
        return sm

    @property
    def duplicates_filtered(self) -> int:
        """Total number of exact-duplicate messages filtered across all symbols."""
        return self._duplicates_filtered

    def _is_duplicate(self, symbol: str, feed_type: str, seq_num: int, exchange_ts_ns: int) -> bool:
        prev = self._last_seen.get((symbol, feed_type))
        if prev is None:
            return False
        # Match on seq_num alone: REST retransmissions reuse the same
        # sequence number but may carry a different exchange timestamp,
        # so including exchange_ts_ns in the key would let retransmissions
        # pass dedup as new events.
        if prev[0] == seq_num:
            self._duplicates_filtered += 1
            return True
        return False

    def _check_gap(self, symbol: str, feed_type: str, seq_num: int, prev_seq: int) -> None:
        """Fire DataHealth transitions based on sequence-number continuity.

        ``prev_seq`` must be captured by the caller *before* calling
        ``_update_last_seen`` so that any ``on_transition`` callback
        observes the already-updated ``_last_seen`` state.
        """
        if seq_num == 0 or prev_seq == 0:
            return

        sm = self._ensure_health_machine(symbol)

        if seq_num > prev_seq + 1:
            if sm.state == DataHealth.HEALTHY:
                sm.transition(
                    DataHealth.GAP_DETECTED,
                    trigger=f"seq_gap:{feed_type}:{prev_seq}->{seq_num}",
                )
            logger.info(
                "massive_normalizer: gap detected for %s/%s: %d -> %d",
                symbol, feed_type, prev_seq, seq_num,
            )
        elif seq_num == prev_seq + 1 and sm.state == DataHealth.GAP_DETECTED:
            sm.transition(
                DataHealth.HEALTHY,
                trigger=f"seq_continuity_resumed:{feed_type}:{seq_num}",
            )
            logger.info(
                "massive_normalizer: gap resolved for %s/%s at seq %d",
                symbol, feed_type, seq_num,
            )

    def _update_last_seen(self, symbol: str, feed_type: str, seq_num: int, exchange_ts_ns: int) -> None:
        self._last_seen[(symbol, feed_type)] = (seq_num, exchange_ts_ns)
        self._ensure_health_machine(symbol)

    def _mark_corrupted(self, symbol: str) -> None:
        sm = self._ensure_health_machine(symbol)
        if sm.can_transition(DataHealth.CORRUPTED):
            sm.transition(DataHealth.CORRUPTED, trigger="parse_error")

    def on_health_transition(self, callback: Callable[[TransitionRecord], None]) -> None:
        """Register a callback for DataHealth state transitions on any symbol.

        Stores the callback for symbols registered in the future and registers
        it immediately on all currently-tracked symbol state machines.
        """
        self._transition_callback = callback
        for sm in self._health_machines.values():
            sm.on_transition(callback)

    def notify_feed_interrupted(self, symbols: Sequence[str]) -> None:
        """Transition HEALTHY symbols to GAP_DETECTED on feed connection loss.

        Called by the WS transport layer so that DataHealth escalates
        immediately rather than waiting for the next message to reveal
        the gap via sequence-number discontinuity.
        """
        for sym in symbols:
            sm = self._health_machines.get(sym)
            if sm is not None and sm.state == DataHealth.HEALTHY:
                sm.transition(DataHealth.GAP_DETECTED, trigger="feed_connection_lost")
