"""Forensic session recorder for PAPER-mode runs.

Write-only buffer flushed to JSONL at session end.  Never read on the
hot path during trading — Inv-5 / A-DET-02 safe.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from feelies.core.events import (
    Alert,
    Event,
    OrderAck,
    OrderRequest,
    Side,
    Signal,
)
from feelies.storage.trade_journal import TradeRecord


def _event_to_dict(event: Event) -> dict[str, Any]:
    """Best-effort serialisation of a bus event."""
    data: dict[str, Any] = {
        "type": type(event).__name__,
        "timestamp_ns": event.timestamp_ns,
        "correlation_id": event.correlation_id,
        "sequence": event.sequence,
    }
    if isinstance(event, Signal):
        data.update(
            {
                "symbol": event.symbol,
                "strategy_id": event.strategy_id,
                "direction": event.direction.name,
                "strength": event.strength,
                "edge_estimate_bps": event.edge_estimate_bps,
            }
        )
    elif isinstance(event, OrderRequest):
        data.update(
            {
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side.name,
                "order_type": event.order_type.name,
                "quantity": event.quantity,
                "strategy_id": event.strategy_id,
            }
        )
    elif isinstance(event, OrderAck):
        data.update(
            {
                "order_id": event.order_id,
                "symbol": event.symbol,
                "status": event.status.name,
                "filled_quantity": event.filled_quantity,
                "fill_price": (str(event.fill_price) if event.fill_price is not None else None),
            }
        )
    elif isinstance(event, Alert):
        data.update(
            {
                "alert_name": event.alert_name,
                "severity": event.severity.name,
                "message": event.message,
                "context": event.context,
            }
        )
    return data


@dataclass
class PaperSessionRecorder:
    """Buffers typed events and timing rows for JSONL export."""

    run_dir: Path
    emit_signals: bool = False
    emit_order_acks: bool = False
    emit_timing: bool = False
    _signals: list[dict[str, Any]] = field(default_factory=list)
    _order_acks: list[dict[str, Any]] = field(default_factory=list)
    _timing: list[dict[str, Any]] = field(default_factory=list)
    _idle_tick_count: int = 0

    def on_event(self, event: Event) -> None:
        if self.emit_signals and isinstance(event, Signal):
            self._signals.append(_event_to_dict(event))
        if self.emit_order_acks and isinstance(event, OrderAck):
            self._order_acks.append(_event_to_dict(event))

    def record_timing(
        self,
        *,
        kind: str,
        duration_ns: int,
        correlation_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self.emit_timing:
            return
        row: dict[str, Any] = {
            "kind": kind,
            "duration_ns": duration_ns,
            "correlation_id": correlation_id,
        }
        if extra:
            row.update(extra)
        self._timing.append(row)

    def record_idle_tick(self) -> None:
        self._idle_tick_count += 1

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "metadata.json"
        path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def flush(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.emit_signals and self._signals:
            self._write_jsonl("signals.jsonl", self._signals)
        if self.emit_order_acks and self._order_acks:
            self._write_jsonl("order_acks.jsonl", self._order_acks)
        if self.emit_timing and self._timing:
            self._write_jsonl("timing.jsonl", self._timing)
        if self.emit_timing and self._idle_tick_count:
            self._timing.append(
                {
                    "kind": "idle_tick_total",
                    "duration_ns": self._idle_tick_count,
                    "correlation_id": "",
                }
            )
            self._write_jsonl("timing.jsonl", self._timing)

    def write_fills(self, records: list[dict[str, Any]]) -> None:
        if records:
            self._write_jsonl("fills.jsonl", records)

    def _write_jsonl(self, name: str, rows: list[dict[str, Any]]) -> None:
        path = self.run_dir / name
        sorted_rows = sorted(
            rows,
            key=lambda r: (r.get("timestamp_ns", 0), r.get("sequence", 0)),
        )
        with path.open("w", encoding="utf-8") as fh:
            for row in sorted_rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")


def trade_records_to_dicts(records: list[Any]) -> list[dict[str, Any]]:
    """Convert TradeRecord objects to JSON-serialisable dicts.

    ``realized_pnl`` and ``fees`` are the two fields post-trade cost analysis
    cannot work without: ``per_alpha_cost_survival`` computes an alpha's net as
    ``sum(realized_pnl) - sum(fees)``, and the cost circuit breaker trips on that
    net.  Omitting them made the persisted session forensically incomplete — the
    breaker could not run against a finished paper session at all.

    Decimals are serialised as strings so cent-level PnL survives the round-trip
    without float drift.
    """
    out: list[dict[str, Any]] = []
    for rec in records:
        out.append(
            {
                "order_id": rec.order_id,
                "symbol": rec.symbol,
                "strategy_id": rec.strategy_id,
                "side": rec.side.name if hasattr(rec.side, "name") else str(rec.side),
                "requested_quantity": rec.requested_quantity,
                "filled_quantity": rec.filled_quantity,
                "fill_price": str(rec.fill_price),
                "fill_timestamp_ns": rec.fill_timestamp_ns,
                "cost_bps": float(rec.cost_bps) if rec.cost_bps is not None else None,
                "realized_pnl": str(rec.realized_pnl),
                "fees": str(rec.fees),
            }
        )
    return out


def trade_records_from_dicts(rows: Iterable[Mapping[str, Any]]) -> list[TradeRecord]:
    """Rebuild ``TradeRecord``s from a persisted ``fills.jsonl``.

    The inverse of :func:`trade_records_to_dicts`, for operator tooling that
    analyses a finished session (see ``feelies forensics circuit-breaker``).
    Fields the session file does not carry are reconstructed as neutral defaults;
    only those cost analysis actually reads are load-bearing.
    """
    out: list[TradeRecord] = []
    for row in rows:
        fill_price = row.get("fill_price")
        cost_bps = row.get("cost_bps")
        out.append(
            TradeRecord(
                order_id=str(row.get("order_id", "")),
                symbol=str(row.get("symbol", "")),
                strategy_id=str(row.get("strategy_id", "")),
                side=Side[str(row["side"])] if row.get("side") else Side.BUY,
                requested_quantity=int(row.get("requested_quantity", 0)),
                filled_quantity=int(row.get("filled_quantity", 0)),
                fill_price=Decimal(str(fill_price)) if fill_price is not None else None,
                signal_timestamp_ns=int(row.get("fill_timestamp_ns") or 0),
                submit_timestamp_ns=int(row.get("fill_timestamp_ns") or 0),
                fill_timestamp_ns=int(row.get("fill_timestamp_ns") or 0),
                cost_bps=Decimal(str(cost_bps)) if cost_bps is not None else Decimal("0"),
                fees=Decimal(str(row.get("fees", "0"))),
                realized_pnl=Decimal(str(row.get("realized_pnl", "0"))),
                correlation_id=str(row.get("correlation_id", "")),
            )
        )
    return out
