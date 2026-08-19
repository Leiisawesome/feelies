"""Durable submitted-order journal — fsync-per-record, write-before-wire (G03).

Records submission ATTEMPTS, not in-memory occupancy. A reject appends an
outcome; it does not delete the attempt. Restart recovery treats UNKNOWN
(journaled, no outcome) as refuse and REJECTED as re-submittable.

Durability mode is fsync-per-record. A page-cached append survives
process kill and would pass a restart test without meeting power-loss
safety; ``os.fsync`` after each record is the discriminator.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from collections.abc import Sequence
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Any, BinaryIO

from feelies.core.clock import Clock
from feelies.core.events import OrderAck, OrderAckStatus, OrderRequest
from feelies.core.platform_config import ENGINE_LATENCY_BUDGETS, EngineLatencyBudget

_JOURNAL_ENGINE = "submitted_order_journal_ns"


class SubmissionJournalState(Enum):
    """Recovered occupancy of one order_id in the durable journal."""

    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    REJECTED = "REJECTED"


def _journal_budget() -> EngineLatencyBudget:
    for entry in ENGINE_LATENCY_BUDGETS:
        if entry.engine == _JOURNAL_ENGINE:
            return entry
    raise RuntimeError("ENGINE_LATENCY_BUDGETS has no submitted_order_journal_ns entry")


def _p99(samples: Sequence[int]) -> int:
    if not samples:
        raise ValueError("p99 of an empty window is undefined")
    ordered = sorted(samples)
    rank = max(1, ceil(0.99 * len(ordered)))
    return ordered[rank - 1]


class DurableSubmittedOrderJournal:
    """Append-only submitted-order journal. One fsync per record."""

    durability_mode: str = "fsync-per-record"

    def __init__(self, path: Path | str, *, clock: Clock) -> None:
        self._path = Path(path)
        self._clock = clock
        self._budget = _journal_budget()
        self._states: dict[str, SubmissionJournalState] = {}
        self._ib_next_valid_id: int | None = None
        self._latency_window: deque[int] = deque(maxlen=self._budget.window_events)
        self._latency_breaches: list[tuple[int, int]] = []
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw = self._path.read_bytes() if self._path.exists() else b""
        self._fh: BinaryIO = self._path.open("ab")
        self._replay(raw)

    def close(self) -> None:
        self._fh.close()

    def decision(self, order_id: str) -> SubmissionJournalState:
        return self._states.get(order_id, SubmissionJournalState.ABSENT)

    def must_refuse(self, order_id: str) -> bool:
        return self._states.get(order_id) is SubmissionJournalState.UNKNOWN

    def unknown_order_ids(self) -> frozenset[str]:
        return frozenset(
            oid for oid, state in self._states.items() if state is SubmissionJournalState.UNKNOWN
        )

    def record_attempt(self, order_id: str) -> None:
        self._append({"kind": "attempt", "order_id": order_id})
        self._states[order_id] = SubmissionJournalState.UNKNOWN

    def record_reject(self, order_id: str) -> None:
        self._append({"kind": "reject", "order_id": order_id})
        self._states[order_id] = SubmissionJournalState.REJECTED

    def record_ib_next_valid_id(self, value: int) -> None:
        self._append({"kind": "ib_next_valid_id", "value": value})
        if self._ib_next_valid_id is None:
            self._ib_next_valid_id = value
        else:
            self._ib_next_valid_id = max(self._ib_next_valid_id, value)

    def recovered_ib_next_valid_id(self) -> int | None:
        return self._ib_next_valid_id

    @property
    def latency_breach_count(self) -> int:
        return len(self._latency_breaches)

    def install_on(self, router: Any) -> None:
        """Bind first-class if the router exposes it; otherwise wrap submit."""
        bind = getattr(router, "bind_submitted_order_journal", None)
        if callable(bind):
            bind(self)
            return
        orig_submit = router.submit
        orig_poll = router.poll_acks
        journal = self

        def submit(request: OrderRequest) -> None:
            if journal.must_refuse(request.order_id):
                pending = getattr(router, "_pending_acks", None)
                seq = getattr(router, "_ack_seq", None)
                clock = getattr(router, "_clock", None)
                if pending is not None and seq is not None and clock is not None:
                    pending.append(
                        OrderAck(
                            timestamp_ns=clock.now_ns(),
                            correlation_id=request.correlation_id,
                            sequence=seq.next(),
                            order_id=request.order_id,
                            symbol=request.symbol,
                            status=OrderAckStatus.REJECTED,
                            reason=f"duplicate order_id: {request.order_id}",
                            request_sequence=request.sequence,
                        )
                    )
                return
            journal.record_attempt(request.order_id)
            orig_submit(request)

        def poll_acks() -> list[OrderAck]:
            acks: list[OrderAck] = list(orig_poll())
            for ack in acks:
                if ack.status is OrderAckStatus.REJECTED and not ack.reason.startswith(
                    "duplicate order_id:"
                ):
                    journal.record_reject(ack.order_id)
            return acks

        router.submit = submit
        router.poll_acks = poll_acks

    def _replay(self, raw: bytes) -> None:
        if not raw:
            return
        text = raw.decode("utf-8")
        chunks = text.split("\n")
        if not text.endswith("\n"):
            chunks = chunks[:-1]
        for line in chunks:
            if not line:
                continue
            rec = self._parse_line(line)
            if rec is None:
                continue
            kind = rec.get("kind")
            if kind == "attempt":
                self._states[str(rec["order_id"])] = SubmissionJournalState.UNKNOWN
            elif kind == "reject":
                self._states[str(rec["order_id"])] = SubmissionJournalState.REJECTED
            elif kind == "ib_next_valid_id":
                value = int(rec["value"])
                if self._ib_next_valid_id is None:
                    self._ib_next_valid_id = value
                else:
                    self._ib_next_valid_id = max(self._ib_next_valid_id, value)

    def _parse_line(self, line: str) -> dict[str, Any] | None:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(rec, dict) or "hash" not in rec:
            return None
        digest = rec["hash"]
        payload = {k: v for k, v in rec.items() if k != "hash"}
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != expected:
            return None
        return rec

    def _append(self, payload: dict[str, object]) -> None:
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        record = dict(payload)
        record["hash"] = digest
        line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        t0 = self._clock.now_ns()
        self._fh.write(line)
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._observe(self._clock.now_ns() - t0)

    def _observe(self, elapsed_ns: int) -> None:
        sample = elapsed_ns if elapsed_ns >= 0 else 0
        self._latency_window.append(sample)
        if len(self._latency_window) < self._budget.window_events:
            return
        observed = _p99(self._latency_window)
        if observed > self._budget.budget_ns:
            self._latency_breaches.append((observed, self._budget.budget_ns))
            # Do not activate the kill switch. Flatten-on-kill would enqueue
            # more per-leg journal writes on the same slow device, leaving
            # UNKNOWN outcomes that brick restart recovery.
