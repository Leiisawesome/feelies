"""Append-only JSONL ledger of committed alpha lifecycle transitions.

The optional ledger is for offline provenance and never drives per-tick
decisions. Writes occur before lifecycle state commits, so a write failure
rolls back the transition instead of leaving a partial promotion.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

LEDGER_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class PromotionLedgerEntry:
    """Immutable record of one committed lifecycle transition.

    Mirrors :class:`feelies.core.state_machine.TransitionRecord` but is
    flattened for JSONL persistence and carries the
    ``schema_version`` field so future migrations can detect the entry
    format.

    Fields:
      schema_version  -- ledger entry format version (currently "1.0.0")
      alpha_id        -- the alpha being promoted/quarantined/etc.
      from_state      -- AlphaLifecycleState name before the transition
      to_state        -- AlphaLifecycleState name after the transition
      trigger         -- transition trigger string (e.g. "pass_paper_gate")
      timestamp_ns    -- clock-derived ns timestamp of the transition
      correlation_id  -- optional caller-supplied correlation token
      metadata        -- transition metadata (typically the evidence dict
                         for promotions, or a ``reason`` for quarantine
                         and decommission).  Persisted as-is.
    """

    schema_version: str = LEDGER_SCHEMA_VERSION
    alpha_id: str
    from_state: str
    to_state: str
    trigger: str
    timestamp_ns: int
    correlation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> str:
        """Serialise this entry as a single JSON line (no trailing newline)."""
        payload = {
            "schema_version": self.schema_version,
            "alpha_id": self.alpha_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "trigger": self.trigger,
            "timestamp_ns": self.timestamp_ns,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }
        return json.dumps(payload, sort_keys=True, default=_json_default)

    @classmethod
    def from_json_line(cls, line: str) -> PromotionLedgerEntry:
        """Parse a single JSONL line.  Raises ``ValueError`` on malformed data."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt promotion-ledger line (not valid JSON): {line!r}") from exc

        if not isinstance(payload, dict):
            raise ValueError(
                f"Promotion-ledger line must decode to an object, got "
                f"{type(payload).__name__}: {line!r}"
            )

        required = (
            "schema_version",
            "alpha_id",
            "from_state",
            "to_state",
            "trigger",
            "timestamp_ns",
        )
        missing = [k for k in required if k not in payload]
        if missing:
            raise ValueError(
                f"Promotion-ledger line missing required field(s) {missing}: {line!r}"
            )

        return cls(
            schema_version=str(payload["schema_version"]),
            alpha_id=str(payload["alpha_id"]),
            from_state=str(payload["from_state"]),
            to_state=str(payload["to_state"]),
            trigger=str(payload["trigger"]),
            timestamp_ns=int(payload["timestamp_ns"]),
            correlation_id=str(payload.get("correlation_id", "")),
            metadata=dict(payload.get("metadata", {})),
        )


def _json_default(obj: Any) -> Any:
    """JSON encoder hook — serialise ``Decimal`` to a canonical string.

    Forensic evidence packages (e.g. realised cost ratios, IC values) may
    contain :class:`decimal.Decimal` instances.  Persist them as
    canonical strings so equality round-trips exactly without binary-fp
    drift.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(
        f"Promotion-ledger entry contains non-JSON-serialisable value "
        f"of type {type(obj).__name__}: {obj!r}"
    )


class PromotionLedger:
    """Append-only JSONL store of :class:`PromotionLedgerEntry` records.

    Writes are line-buffered + flushed-per-append, so a crashing process
    leaves at most one truncated trailing line (which the reader will
    surface as a ``ValueError`` rather than silently swallow).

    Re-opening an existing ledger preserves prior content; new entries
    are appended at end-of-file.
    """

    __slots__ = ("_path",)

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> Path:
        return self._path

    # ── Write side ──────────────────────────────────────────────

    def append(self, entry: PromotionLedgerEntry) -> None:
        """Append one entry to the ledger.

        Each call opens the file in append mode, writes a single
        terminated line, flushes, and closes — so multiple ledger
        instances pointing at the same path interleave deterministically
        in call order.
        """
        line = entry.to_json_line() + "\n"
        with self._path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()

    # ── Read side ───────────────────────────────────────────────

    def entries(self) -> Iterator[PromotionLedgerEntry]:
        """Iterate over every entry in append order.

        Raises ``ValueError`` if any line is corrupt, naming the line
        number to help operators triage.
        """
        with self._path.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                stripped = raw.rstrip("\n")
                if not stripped:
                    continue
                try:
                    yield PromotionLedgerEntry.from_json_line(stripped)
                except ValueError as exc:
                    raise ValueError(
                        f"Corrupt promotion-ledger entry at {self._path}:{lineno}: {exc}"
                    ) from exc

    def entries_for(self, alpha_id: str) -> Iterator[PromotionLedgerEntry]:
        """Iterate over the entries belonging to a single alpha, in order."""
        for entry in self.entries():
            if entry.alpha_id == alpha_id:
                yield entry

    def latest_for(self, alpha_id: str) -> PromotionLedgerEntry | None:
        """Most recent entry for an alpha, or ``None`` if it has none."""
        latest: PromotionLedgerEntry | None = None
        for entry in self.entries_for(alpha_id):
            latest = entry
        return latest

    def __len__(self) -> int:
        count = 0
        for _ in self.entries():
            count += 1
        return count

    def __iter__(self) -> Iterator[PromotionLedgerEntry]:
        return self.entries()


__all__ = (
    "LEDGER_SCHEMA_VERSION",
    "PromotionLedger",
    "PromotionLedgerEntry",
)
