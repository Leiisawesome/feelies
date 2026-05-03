"""Event-calendar adapter — scheduled-flow window registry (v0.3).

Loads, validates, and exposes the per-session list of *scheduled-flow
windows* consumed by ``feelies.sensors.impl.scheduled_flow_window``
(see ``docs/three_layer_architecture.md`` §20.4.2).

Calendar files live under ``storage/reference/event_calendar/<date>.yaml``
where ``<date>`` is an ISO-8601 ``YYYY-MM-DD`` session date.  The format
intentionally mirrors a YAML serialisation of :class:`CalendarWindow`
fields and is read once at bootstrap; downstream sensors index into the
:class:`EventCalendar` via ``windows_active_at(ts_ns)`` for O(log N)
event-time membership queries.

Determinism contract (Inv-5, Inv-13):

- Calendar contents are content-addressed: :meth:`EventCalendar.hash`
  returns a SHA-256 over the canonicalised window list.  This hash is
  surfaced into the bootstrap provenance bundle so replays can verify
  they used the same calendar snapshot.
- Window timestamps are pre-computed to integer nanoseconds at load
  time.  ``ZoneInfo("America/New_York")`` resolves the ET clock-time
  windows defined in the YAML; lookups are then pure integer
  comparisons.
- Window ordering is deterministic — ``windows`` is sorted by
  ``(start_ns, kind, window_id)`` after parse so two YAML files that
  differ only in row order produce the same hash.

This module is intentionally small in v0.3:

- ``WindowKind`` enum captures the five canonical window types.
- ``CalendarWindow`` is the immutable per-window record.
- ``EventCalendar`` aggregates the per-session window list, exposes
  the active-windows-at-ns lookup, and computes the canonical hash.
- ``load_event_calendar(path)`` is the YAML loader.

The downstream sensor (``scheduled_flow_window``) and any future
calendar consumers go through the public API only.  The on-disk YAML
schema is *part* of the public contract and any backwards-incompatible
change requires a versioned migration alongside a fresh
``EventCalendar.hash`` baseline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import yaml  # pyright: ignore[reportMissingModuleSource]

_NY_TZ = ZoneInfo("America/New_York")
_NS_PER_SECOND = 1_000_000_000


class WindowKind(str, Enum):
    """Canonical scheduled-flow window taxonomy (v0.3 §20.4.2)."""

    MOC_IMBALANCE = "MOC_IMBALANCE"
    OPENING_AUCTION = "OPENING_AUCTION"
    INDEX_REBALANCE = "INDEX_REBALANCE"
    EARNINGS_DRIFT = "EARNINGS_DRIFT"
    FOMC_BLACKOUT = "FOMC_BLACKOUT"


@dataclass(frozen=True, kw_only=True)
class CalendarWindow:
    """A single scheduled-flow window for a specific session date.

    All timestamps are stored as integer event-time nanoseconds since
    the UNIX epoch in UTC, pre-resolved at load time so the hot path
    on the sensor side is a pure integer compare.

    Fields:

    - ``window_id``: unique stable identifier within the calendar.
      Used by the sensor to emit a ``window_id_hash`` output.
    - ``kind``: which canonical family this window belongs to.
    - ``symbol``: ``None`` if window applies universe-wide (e.g.
      ``MOC_IMBALANCE``); otherwise the ticker (e.g. for
      ``EARNINGS_DRIFT``).
    - ``start_ns`` / ``end_ns``: half-open interval ``[start_ns,
      end_ns)`` in event time.  ``end_ns > start_ns`` by validation.
    - ``flow_direction_prior``: expected sign of net flow inside the
      window — ``+1.0``, ``-1.0``, or ``0.0`` (neutral).
    - ``meta``: opaque supplementary fields propagated through.
    """

    window_id: str
    kind: WindowKind
    symbol: str | None
    start_ns: int
    end_ns: int
    flow_direction_prior: float
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end_ns <= self.start_ns:
            raise ValueError(
                f"CalendarWindow {self.window_id!r}: end_ns "
                f"({self.end_ns}) must be > start_ns ({self.start_ns})"
            )
        if self.flow_direction_prior not in (-1.0, 0.0, +1.0):
            raise ValueError(
                f"CalendarWindow {self.window_id!r}: "
                f"flow_direction_prior must be -1, 0, or +1; "
                f"got {self.flow_direction_prior!r}"
            )

    def contains(self, ts_ns: int) -> bool:
        """Half-open membership: ``start_ns <= ts_ns < end_ns``."""
        return self.start_ns <= ts_ns < self.end_ns

    def to_canonical_dict(self) -> dict[str, Any]:
        """Round-trip-safe dict for hashing."""
        return {
            "window_id": self.window_id,
            "kind": self.kind.value,
            "symbol": self.symbol,
            "start_ns": int(self.start_ns),
            "end_ns": int(self.end_ns),
            "flow_direction_prior": float(self.flow_direction_prior),
            "meta": _canonicalise(self.meta),
        }


@dataclass(frozen=True)
class EventCalendar:
    """Per-session list of scheduled-flow windows.

    Construction goes through :func:`load_event_calendar` (or directly
    from a window list — useful in tests).  ``windows`` is already
    sorted by ``(start_ns, kind, window_id)`` and de-duplicated by
    ``window_id``.
    """

    session_date: date
    windows: tuple[CalendarWindow, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for w in self.windows:
            if w.window_id in seen:
                raise ValueError(
                    f"duplicate window_id {w.window_id!r} in calendar"
                )
            seen.add(w.window_id)

    def windows_active_at(self, ts_ns: int) -> tuple[CalendarWindow, ...]:
        """Return all windows whose half-open interval contains ``ts_ns``.

        Linear scan over the (small) per-session window list — the
        v0.3 reference calendar carries < 50 windows per date so the
        constant factor dominates over any indexing structure.  If the
        catalog ever grows by 10x, replace with bisect on a sorted
        ``end_ns`` array.
        """
        return tuple(w for w in self.windows if w.contains(ts_ns))

    def hash(self) -> str:
        """Deterministic SHA-256 of the canonicalised calendar.

        The hash spans:

        - ``session_date`` (ISO-8601 YYYY-MM-DD);
        - the *sorted* list of windows in canonical-dict form;
        - ``__schema_version__`` of the calendar format itself.

        Two YAML files that differ only in row order, key order, or
        formatting whitespace must produce the *same* hash.
        """
        payload = {
            "__schema_version__": 1,
            "session_date": self.session_date.isoformat(),
            "windows": [w.to_canonical_dict() for w in self.windows],
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


# ── Loader ─────────────────────────────────────────────────────────


def _canonicalise(value: Any) -> Any:
    """Sort-key-stable, JSON-safe deep copy of ``value``."""
    if isinstance(value, Mapping):
        return {k: _canonicalise(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalise(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return float(value)
    return str(value)


def _parse_clock_time(spec: str) -> time:
    """Parse a ``HH:MM`` or ``HH:MM:SS`` 24-hour ET clock string."""
    parts = spec.split(":")
    if len(parts) == 2:
        h, m = parts
        return time(hour=int(h), minute=int(m))
    if len(parts) == 3:
        h, m, s = parts
        return time(hour=int(h), minute=int(m), second=int(s))
    raise ValueError(f"clock time {spec!r} must be HH:MM or HH:MM:SS")


def _et_clock_to_ns(session_date: date, clock_str: str) -> int:
    """Resolve an ET clock-time on ``session_date`` to UTC nanoseconds."""
    t = _parse_clock_time(clock_str)
    local = datetime.combine(session_date, t, tzinfo=_NY_TZ)
    return int(local.timestamp() * _NS_PER_SECOND)


def _parse_window(
    raw: Mapping[str, Any], *, session_date: date,
) -> CalendarWindow:
    if "window_id" not in raw or "kind" not in raw:
        raise ValueError(
            f"calendar window missing required key (window_id, kind): {raw!r}"
        )
    kind_raw = raw["kind"]
    try:
        kind = WindowKind(kind_raw)
    except ValueError as exc:
        raise ValueError(
            f"unknown WindowKind {kind_raw!r}; expected one of "
            f"{sorted(k.value for k in WindowKind)}"
        ) from exc

    if "start_ns" in raw and "end_ns" in raw:
        start_ns = int(raw["start_ns"])
        end_ns = int(raw["end_ns"])
    elif "start_et" in raw and "end_et" in raw:
        start_ns = _et_clock_to_ns(session_date, str(raw["start_et"]))
        end_ns = _et_clock_to_ns(session_date, str(raw["end_et"]))
    else:
        raise ValueError(
            f"window {raw.get('window_id')!r}: must specify either "
            f"(start_ns, end_ns) or (start_et, end_et)"
        )

    flow_dir = float(raw.get("flow_direction_prior", 0.0))
    meta_raw = raw.get("meta", {})
    if not isinstance(meta_raw, Mapping):
        raise ValueError(
            f"window {raw['window_id']!r}: meta must be a mapping"
        )
    return CalendarWindow(
        window_id=str(raw["window_id"]),
        kind=kind,
        symbol=(str(raw["symbol"]) if raw.get("symbol") is not None else None),
        start_ns=start_ns,
        end_ns=end_ns,
        flow_direction_prior=flow_dir,
        meta=dict(meta_raw),
    )


def load_event_calendar(path: str | Path) -> EventCalendar:
    """Load a per-session calendar YAML from disk.

    Schema (top-level keys, all required unless noted):

    .. code-block:: yaml

        session_date: 2026-03-24            # ISO YYYY-MM-DD
        windows:
          - window_id: nyse_open_2026_03_24
            kind: OPENING_AUCTION
            symbol: null                     # null = universe-wide
            start_et: "09:30"                # OR start_ns: <int>
            end_et: "09:35"                  # OR end_ns: <int>
            flow_direction_prior: 0.0        # -1, 0, or +1
            meta: {}

    The function validates the schema, pre-computes integer
    nanosecond bounds, and returns a frozen :class:`EventCalendar`
    with windows sorted by ``(start_ns, kind, window_id)``.
    """
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{p}: top-level must be a mapping")
    if "session_date" not in raw or "windows" not in raw:
        raise ValueError(
            f"{p}: top-level keys 'session_date' and 'windows' are required"
        )
    sd_raw = raw["session_date"]
    if isinstance(sd_raw, date):
        session_date = sd_raw
    else:
        session_date = date.fromisoformat(str(sd_raw))

    windows_raw = raw["windows"]
    if not isinstance(windows_raw, list):
        raise ValueError(f"{p}: 'windows' must be a list")

    windows = tuple(
        sorted(
            (_parse_window(w, session_date=session_date) for w in windows_raw),
            key=lambda w: (w.start_ns, w.kind.value, w.window_id),
        )
    )
    return EventCalendar(session_date=session_date, windows=windows)


__all__ = [
    "CalendarWindow",
    "EventCalendar",
    "WindowKind",
    "load_event_calendar",
]
