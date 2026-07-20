#!/usr/bin/env python3
"""Derive hour-only views from committed ``ALGO_CLOCK`` calendars.

The deterministic subset transform:

* retain only ``ALGO_CLOCK`` rows whose mark minute is ``:00``
  (``10:00 … 15:00`` America/New_York);
* ``:30`` marks remain in the committed files for H12 / platform use
  and are excluded so
  ``scheduled_flow_window_active`` encodes hour membership (non-
  tautological at H = 1800);
* non-``ALGO_CLOCK`` rows are also excluded from the injection view
  so opening and MOC windows do not contribute;
* exchange-schedule only — no market data, no σ, no IC, no forward
  returns.

Committed YAML is never rewritten. Sorted output and stable hashing make reruns
identical. The date set is the union of operative evidence sessions.

Usage
-----
    PYTHONHASHSEED=0 uv run python \\
        scripts/research/derive_hour_only_algo_clock_calendars.py \\
        [--calendar-dir src/feelies/storage/reference/event_calendar]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.storage.reference.event_calendar import (  # noqa: E402
    CalendarWindow,
    EventCalendar,
    WindowKind,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR  # noqa: E402

# Reuse the operative date set across all evidence symbols.
from scripts.research.author_algo_clock_calendars import (  # noqa: E402
    DATES_ALL,
    DATES_PREAMBLE,
)

_TZ_ET = ZoneInfo("America/New_York")

# On-the-hour marks.
HOUR_MARKS: tuple[tuple[int, int], ...] = (
    (10, 0),
    (11, 0),
    (12, 0),
    (13, 0),
    (14, 0),
    (15, 0),
)
HOUR_MARK_HOURS = frozenset(h for h, _ in HOUR_MARKS)


def is_hour_algo_clock_mark(window: CalendarWindow, session_date: date) -> bool:
    """True iff ``window`` is an on-the-hour ALGO_CLOCK mark for ``session_date``."""
    if window.kind is not WindowKind.ALGO_CLOCK:
        return False
    dt = datetime.fromtimestamp(window.start_ns / 1e9, tz=_TZ_ET)
    if dt.date() != session_date:
        return False
    if dt.minute != 0 or dt.second != 0 or dt.microsecond != 0:
        return False
    if dt.hour not in HOUR_MARK_HOURS:
        return False
    # Half-open [M, M+1s) duration lock (H12 convention).
    if window.end_ns - window.start_ns != 1_000_000_000:
        return False
    return True


def derive_hour_only_calendar(source: EventCalendar) -> EventCalendar:
    """Return the H13 injection view — ``:00`` ALGO_CLOCK subset only."""
    kept = tuple(
        w for w in source.windows if is_hour_algo_clock_mark(w, source.session_date)
    )
    # Preserve sort contract of EventCalendar loader.
    kept = tuple(sorted(kept, key=lambda w: (w.start_ns, w.kind.value, w.window_id)))
    return EventCalendar(session_date=source.session_date, windows=kept)


def load_hour_only_calendar(
    date_str: str,
    *,
    calendar_dir: Path = EVENT_CALENDAR_DIR,
) -> EventCalendar | None:
    """Load committed calendar and return its hour-only derived view."""
    path = calendar_dir / f"{date_str}.yaml"
    if not path.is_file():
        return None
    source = load_event_calendar(
        path, expected_session_date=date.fromisoformat(date_str)
    )
    return derive_hour_only_calendar(source)


def derive_all(
    calendar_dir: Path = EVENT_CALENDAR_DIR,
    *,
    dates: Sequence[str] = DATES_ALL,
) -> dict[str, EventCalendar]:
    """Derive hour-only views for ``dates``. Raises if any date is missing."""
    out: dict[str, EventCalendar] = {}
    for d in dates:
        cal = load_hour_only_calendar(d, calendar_dir=calendar_dir)
        if cal is None:
            raise FileNotFoundError(f"missing committed calendar for {d} under {calendar_dir}")
        if len(cal.windows) != len(HOUR_MARKS):
            raise ValueError(
                f"{d}: expected {len(HOUR_MARKS)} hour ALGO_CLOCK marks, got {len(cal.windows)}"
            )
        out[d] = cal
    return out


def derived_view_hashes(
    calendar_dir: Path = EVENT_CALENDAR_DIR,
    *,
    dates: Sequence[str] = DATES_ALL,
) -> dict[str, str]:
    """Content-addressed ``EventCalendar.hash`` of each hour-only view."""
    return {d: cal.hash() for d, cal in derive_all(calendar_dir, dates=dates).items()}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--calendar-dir",
        type=Path,
        default=EVENT_CALENDAR_DIR,
        help="Directory of committed <YYYY-MM-DD>.yaml calendars",
    )
    ap.add_argument(
        "--preamble-only",
        action="store_true",
        help="Restrict to the 10 preamble dates (ENSG/MLI evidence set)",
    )
    args = ap.parse_args(argv)
    dates = DATES_PREAMBLE if args.preamble_only else DATES_ALL
    views = derive_all(args.calendar_dir, dates=dates)
    hashes = {d: views[d].hash() for d in dates}
    print(f"derived {len(views)} hour-only calendars from {args.calendar_dir}")
    for d in dates:
        print(f"  {d}  hash={hashes[d][:16]}…  hour_algo_clock={len(views[d].windows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
