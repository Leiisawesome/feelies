"""Corporate-action ex-date calendar for replay integrity (BT-18).

The platform ingests **raw, unadjusted** L1 NBBO. Splits and dividend
ex-dates produce genuine price discontinuities; a replay window that
crosses an ex-date for a universe symbol without an explicit adjustment
policy will corrupt level-anchored sensors (Kyle-lambda, realized vol).

This module does **not** apply adjustment factors — it only loads a
reference ex-date table and flags replay windows that intersect known
ex-dates at bootstrap time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import yaml  # pyright: ignore[reportMissingModuleSource]

from feelies.core.events import NBBOQuote, Trade
from feelies.storage.event_log import EventLog

from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000

# Canonical policy string recorded in docs and error messages.
RAW_UNADJUSTED_L1_POLICY = (
    "RAW_UNADJUSTED_L1: backtests use unadjusted L1 within a single session; "
    "replays must not span a known split/dividend ex-date for a universe "
    "symbol unless prices are explicitly adjusted at the boundary."
)


class CorporateActionKind(str, Enum):
    """Supported ex-date kinds for the integrity guard."""

    SPLIT = "SPLIT"
    DIVIDEND = "DIVIDEND"


@dataclass(frozen=True, kw_only=True)
class ExDateEntry:
    """A single symbol ex-date row."""

    symbol: str
    ex_date: date
    kind: CorporateActionKind
    note: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ex_date": self.ex_date.isoformat(),
            "kind": self.kind.value,
            "note": self.note,
        }


@dataclass(frozen=True, kw_only=True)
class ExDateCalendar:
    """Immutable ex-date table loaded from YAML."""

    entries: tuple[ExDateEntry, ...]

    @property
    def hash(self) -> str:
        """SHA-256 over canonical JSON (Inv-13 provenance)."""
        payload = [e.to_canonical_dict() for e in self.entries]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def entries_for_symbols(
        self,
        symbols: frozenset[str],
    ) -> tuple[ExDateEntry, ...]:
        sym_u = {s.upper() for s in symbols}
        return tuple(e for e in self.entries if e.symbol in sym_u)


@dataclass(frozen=True, kw_only=True)
class ExDateReplayViolation:
    """A universe symbol whose ex-date falls inside the replay date span."""

    symbol: str
    ex_date: date
    kind: CorporateActionKind
    replay_start_date: date
    replay_end_date: date
    note: str = ""

    def message(self) -> str:
        base = (
            f"{self.symbol} has {self.kind.value} ex-date "
            f"{self.ex_date.isoformat()} inside replay span "
            f"{self.replay_start_date.isoformat()}.."
            f"{self.replay_end_date.isoformat()}"
        )
        if self.note:
            return f"{base} ({self.note})"
        return base


def exchange_timestamp_to_ny_date(timestamp_ns: int) -> date:
    """ET calendar date for an exchange-time nanosecond stamp."""
    return datetime.fromtimestamp(
        timestamp_ns / _NS_PER_SECOND,
        _NY_TZ,
    ).date()


def replay_calendar_date_span(
    event_log: EventLog,
) -> tuple[date, date] | None:
    """Inclusive ET date span covered by market events in ``event_log``.

    Returns ``None`` when the log contains no ``NBBOQuote`` / ``Trade``
    rows (guard is a no-op).
    """
    min_ns: int | None = None
    max_ns: int | None = None
    for event in event_log.replay():
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        ts = event.exchange_timestamp_ns
        min_ns = ts if min_ns is None else min(min_ns, ts)
        max_ns = ts if max_ns is None else max(max_ns, ts)
    if min_ns is None or max_ns is None:
        return None
    return (
        exchange_timestamp_to_ny_date(min_ns),
        exchange_timestamp_to_ny_date(max_ns),
    )


def replay_calendar_date_span_by_symbol(
    event_log: EventLog,
) -> dict[str, tuple[date, date]]:
    """Inclusive ET date span covered by market events, keyed by symbol.

    Only symbols with at least one ``NBBOQuote`` / ``Trade`` row in the
    log appear in the result. Symbol keys are uppercased to match the
    casing convention used by :class:`ExDateCalendar`.
    """
    spans_ns: dict[str, tuple[int, int]] = {}
    for event in event_log.replay():
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        sym = event.symbol.upper()
        ts = event.exchange_timestamp_ns
        existing = spans_ns.get(sym)
        if existing is None:
            spans_ns[sym] = (ts, ts)
        else:
            spans_ns[sym] = (min(existing[0], ts), max(existing[1], ts))
    return {
        sym: (
            exchange_timestamp_to_ny_date(lo),
            exchange_timestamp_to_ny_date(hi),
        )
        for sym, (lo, hi) in spans_ns.items()
    }


def find_ex_date_violations(
    symbols: frozenset[str],
    replay_start: date,
    replay_end: date,
    calendar: ExDateCalendar,
) -> tuple[ExDateReplayViolation, ...]:
    """Return ex-date rows that intersect ``[replay_start, replay_end]``."""
    if replay_start > replay_end:
        raise ValueError(f"replay_start {replay_start} must be <= replay_end {replay_end}")
    violations: list[ExDateReplayViolation] = []
    for entry in calendar.entries_for_symbols(symbols):
        if replay_start <= entry.ex_date <= replay_end:
            violations.append(
                ExDateReplayViolation(
                    symbol=entry.symbol,
                    ex_date=entry.ex_date,
                    kind=entry.kind,
                    replay_start_date=replay_start,
                    replay_end_date=replay_end,
                    note=entry.note,
                )
            )
    return tuple(violations)


def check_ex_date_replay_window(
    symbols: frozenset[str],
    event_log: EventLog,
    calendar: ExDateCalendar,
    *,
    precomputed_spans: dict[str, tuple[date, date]] | None = None,
) -> tuple[ExDateReplayViolation, ...]:
    """Run the BT-18 guard for a populated replay log.

    A symbol can only be flagged for an ex-date that falls inside *its
    own* per-symbol replay date span. Symbols listed in ``symbols`` but
    absent from the event log produce no violations — without quotes or
    trades on the tape they cannot introduce a price discontinuity that
    the guard exists to prevent.

    When ``precomputed_spans`` is supplied (e.g. from a fused pre-replay
    scan), the event log is not rescanned.
    """
    spans = (
        precomputed_spans
        if precomputed_spans is not None
        else replay_calendar_date_span_by_symbol(event_log)
    )
    if not spans:
        return ()
    violations: list[ExDateReplayViolation] = []
    for entry in calendar.entries_for_symbols(symbols):
        span = spans.get(entry.symbol)
        if span is None:
            continue
        start, end = span
        if start <= entry.ex_date <= end:
            violations.append(
                ExDateReplayViolation(
                    symbol=entry.symbol,
                    ex_date=entry.ex_date,
                    kind=entry.kind,
                    replay_start_date=start,
                    replay_end_date=end,
                    note=entry.note,
                )
            )
    return tuple(violations)


def _parse_kind(raw: object, source: str) -> CorporateActionKind:
    if not isinstance(raw, str):
        raise ValueError(f"{source}: kind must be a string, got {type(raw).__name__}")
    try:
        return CorporateActionKind(raw.upper())
    except ValueError as exc:
        raise ValueError(f"{source}: unknown kind {raw!r}; expected SPLIT or DIVIDEND") from exc


def _parse_entry(raw: Mapping[str, Any], source: str) -> ExDateEntry:
    sym = raw.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise ValueError(f"{source}: symbol must be a non-empty string")
    ex_raw = raw.get("ex_date")
    if ex_raw is None:
        raise ValueError(f"{source}: ex_date is required")
    ex_date = ex_raw if isinstance(ex_raw, date) else date.fromisoformat(str(ex_raw))
    kind = _parse_kind(raw.get("kind"), source)
    note = str(raw.get("note", ""))
    return ExDateEntry(
        symbol=sym.strip().upper(),
        ex_date=ex_date,
        kind=kind,
        note=note,
    )


def load_ex_date_calendar(path: str | Path) -> ExDateCalendar:
    """Load ``ex_dates.yaml`` (or equivalent) from disk."""
    p = Path(path)
    raw_data: Mapping[str, Any] = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw_data, Mapping):
        raise ValueError(f"{p}: top-level YAML must be a mapping")
    version = raw_data.get("schema_version", "1.0")
    if str(version) != "1.0":
        raise ValueError(f"{p}: unsupported schema_version {version!r}; expected '1.0'")
    entries_raw = raw_data.get("entries", [])
    if not isinstance(entries_raw, list):
        raise ValueError(f"{p}: entries must be a list")
    entries: list[ExDateEntry] = []
    seen: set[tuple[str, date, str]] = set()
    for idx, row in enumerate(entries_raw):
        if not isinstance(row, Mapping):
            raise ValueError(f"{p}: entries[{idx}] must be a mapping, got {type(row).__name__}")
        entry = _parse_entry(row, f"{p}: entries[{idx}]")
        key = (entry.symbol, entry.ex_date, entry.kind.value)
        if key in seen:
            raise ValueError(
                f"{p}: duplicate ex-date entry {entry.symbol} "
                f"{entry.ex_date.isoformat()} {entry.kind.value}"
            )
        seen.add(key)
        entries.append(entry)
    entries.sort(key=lambda e: (e.ex_date, e.symbol, e.kind.value))
    return ExDateCalendar(entries=tuple(entries))


__all__ = [
    "RAW_UNADJUSTED_L1_POLICY",
    "CorporateActionKind",
    "ExDateCalendar",
    "ExDateEntry",
    "ExDateReplayViolation",
    "check_ex_date_replay_window",
    "exchange_timestamp_to_ny_date",
    "find_ex_date_violations",
    "load_ex_date_calendar",
    "replay_calendar_date_span",
    "replay_calendar_date_span_by_symbol",
]
