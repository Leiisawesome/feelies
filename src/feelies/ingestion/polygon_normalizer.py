"""Polygon.io normalizer — transforms raw WebSocket and REST wire formats
into canonical NBBOQuote / Trade events.

Implements the MarketDataNormalizer protocol.  Single entry point for all
Polygon market data.  Detects wire format via the ``source`` parameter
(``"polygon_ws"`` vs ``"polygon_rest"``).

Responsibilities (per data-engineering skill):
  - Parse raw JSON into typed events with full Polygon.io field coverage
  - Assign correlation IDs at the ingestion boundary (invariant 13)
  - Track per-symbol sequence numbers for gap detection
  - Eliminate exact duplicates
  - Drive per-symbol DataHealth state machines
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from decimal import Decimal

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.state_machine import StateMachine
from feelies.ingestion.data_integrity import (
    DataHealth,
    create_data_integrity_machine,
)

logger = logging.getLogger(__name__)

_WS_SOURCE = "polygon_ws"
_REST_SOURCE = "polygon_rest"
_MS_TO_NS = 1_000_000


class PolygonNormalizer:
    """Transforms raw Polygon.io messages into canonical market events.

    Wire-format routing:
      ``polygon_ws``   — JSON array, each element has ``ev`` (Q or T).
                         Timestamps in milliseconds.
      ``polygon_rest`` — Single JSON object with verbose field names.
                         Timestamps in nanoseconds.
    """

    __slots__ = (
        "_clock",
        "_seq",
        "_health_machines",
        "_last_seen",
    )

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._seq = SequenceGenerator()
        self._health_machines: dict[str, StateMachine[DataHealth]] = {}
        # Per-symbol dedup + gap state: (last_sequence_number, last_exchange_ts_ns)
        self._last_seen: dict[str, tuple[int, int]] = {}

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
            logger.warning("polygon_normalizer: unparseable message from %s", source)
            return []

        if source == _WS_SOURCE:
            return self._parse_ws(data, received_ns)
        if source == _REST_SOURCE:
            return self._parse_rest(data, received_ns)

        logger.warning("polygon_normalizer: unknown source %r", source)
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

            if self._is_duplicate(symbol, seq_num, exchange_ts_ns):
                return None
            self._check_gap(symbol, seq_num)
            self._update_last_seen(symbol, seq_num, exchange_ts_ns)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

            raw_c = msg.get("c")
            if raw_c is not None and not isinstance(raw_c, list):
                conditions = (int(raw_c),)
            elif isinstance(raw_c, list):
                conditions = tuple(int(x) for x in raw_c)
            else:
                conditions = ()

            raw_i = msg.get("i")
            indicators = tuple(int(x) for x in raw_i) if isinstance(raw_i, list) else ()

            return NBBOQuote(
                timestamp_ns=received_ns,
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
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("polygon_normalizer: bad WS quote: %s", exc)
            self._mark_corrupted(msg.get("sym", "UNKNOWN"))
            return None

    def _ws_trade(self, msg: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        try:
            symbol: str = msg["sym"]
            exchange_ts_ns = int(msg["t"]) * _MS_TO_NS
            seq_num = int(msg.get("q", 0))

            if self._is_duplicate(symbol, seq_num, exchange_ts_ns):
                return None
            self._check_gap(symbol, seq_num)
            self._update_last_seen(symbol, seq_num, exchange_ts_ns)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, exchange_ts_ns, internal_seq)

            raw_c = msg.get("c")
            conditions = tuple(int(x) for x in raw_c) if isinstance(raw_c, list) else ()

            raw_trft = msg.get("trft")
            trf_ts = int(raw_trft) * _MS_TO_NS if raw_trft is not None else None

            return Trade(
                timestamp_ns=received_ns,
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
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("polygon_normalizer: bad WS trade: %s", exc)
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
        if "bid_price" in data or "ask_price" in data:
            event = self._rest_quote(data, received_ns)
            return [event] if event is not None else []
        if "price" in data:
            event = self._rest_trade(data, received_ns)
            return [event] if event is not None else []

        return []

    def _rest_quote(self, rec: dict, received_ns: int) -> NBBOQuote | None:  # type: ignore[type-arg]
        try:
            symbol: str = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            seq_num = int(rec.get("sequence_number", 0))

            if self._is_duplicate(symbol, seq_num, sip_ts):
                return None
            self._check_gap(symbol, seq_num)
            self._update_last_seen(symbol, seq_num, sip_ts)

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
                timestamp_ns=received_ns,
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
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("polygon_normalizer: bad REST quote: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    def _rest_trade(self, rec: dict, received_ns: int) -> Trade | None:  # type: ignore[type-arg]
        try:
            symbol: str = rec["ticker"]
            sip_ts = int(rec["sip_timestamp"])
            seq_num = int(rec.get("sequence_number", 0))

            if self._is_duplicate(symbol, seq_num, sip_ts):
                return None
            self._check_gap(symbol, seq_num)
            self._update_last_seen(symbol, seq_num, sip_ts)

            internal_seq = self._seq.next()
            cid = make_correlation_id(symbol, sip_ts, internal_seq)

            raw_cond = rec.get("conditions")
            conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

            raw_part = rec.get("participant_timestamp")
            part_ts = int(raw_part) if raw_part is not None else None

            return Trade(
                timestamp_ns=received_ns,
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
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("polygon_normalizer: bad REST trade: %s", exc)
            self._mark_corrupted(rec.get("ticker", "UNKNOWN"))
            return None

    # ── Gap detection / dedup / health ───────────────────────────────

    def _ensure_health_machine(self, symbol: str) -> StateMachine[DataHealth]:
        sm = self._health_machines.get(symbol)
        if sm is None:
            sm = create_data_integrity_machine(symbol, self._clock)
            self._health_machines[symbol] = sm
        return sm

    def _is_duplicate(self, symbol: str, seq_num: int, exchange_ts_ns: int) -> bool:
        prev = self._last_seen.get(symbol)
        if prev is None:
            return False
        return prev == (seq_num, exchange_ts_ns)

    def _check_gap(self, symbol: str, seq_num: int) -> None:
        if seq_num == 0:
            return
        prev = self._last_seen.get(symbol)
        if prev is None:
            return
        prev_seq = prev[0]
        if prev_seq == 0:
            return
        if seq_num > prev_seq + 1:
            sm = self._ensure_health_machine(symbol)
            if sm.state == DataHealth.HEALTHY:
                sm.transition(
                    DataHealth.GAP_DETECTED,
                    trigger=f"seq_gap:{prev_seq}->{seq_num}",
                )
                logger.info(
                    "polygon_normalizer: gap detected for %s: %d -> %d",
                    symbol, prev_seq, seq_num,
                )

    def _update_last_seen(self, symbol: str, seq_num: int, exchange_ts_ns: int) -> None:
        self._last_seen[symbol] = (seq_num, exchange_ts_ns)
        self._ensure_health_machine(symbol)

    def _mark_corrupted(self, symbol: str) -> None:
        sm = self._ensure_health_machine(symbol)
        if sm.can_transition(DataHealth.CORRUPTED):
            sm.transition(DataHealth.CORRUPTED, trigger="parse_error")
