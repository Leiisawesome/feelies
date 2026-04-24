"""Unit tests for the EventCalendar adapter."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from feelies.storage.reference.event_calendar import (
    CalendarWindow,
    EventCalendar,
    WindowKind,
    load_event_calendar,
)

REFERENCE_CALENDAR_PATH: Path = (
    Path(__file__).resolve().parents[2]
    / "storage" / "reference" / "event_calendar" / "2026-03-24.yaml"
)


def test_window_validates_interval() -> None:
    with pytest.raises(ValueError, match="end_ns"):
        CalendarWindow(
            window_id="w",
            kind=WindowKind.OPENING_AUCTION,
            symbol=None,
            start_ns=10,
            end_ns=10,
            flow_direction_prior=0.0,
        )


def test_window_validates_flow_direction() -> None:
    with pytest.raises(ValueError, match="flow_direction_prior"):
        CalendarWindow(
            window_id="w",
            kind=WindowKind.MOC_IMBALANCE,
            symbol=None,
            start_ns=0,
            end_ns=1,
            flow_direction_prior=0.5,
        )


def test_calendar_rejects_duplicate_window_ids() -> None:
    w1 = CalendarWindow(
        window_id="dup",
        kind=WindowKind.OPENING_AUCTION,
        symbol=None,
        start_ns=0,
        end_ns=1,
        flow_direction_prior=0.0,
    )
    w2 = CalendarWindow(
        window_id="dup",
        kind=WindowKind.MOC_IMBALANCE,
        symbol=None,
        start_ns=2,
        end_ns=3,
        flow_direction_prior=0.0,
    )
    with pytest.raises(ValueError, match="duplicate window_id"):
        EventCalendar(session_date=date(2026, 3, 24), windows=(w1, w2))


def test_windows_active_at_half_open() -> None:
    w = CalendarWindow(
        window_id="w",
        kind=WindowKind.OPENING_AUCTION,
        symbol=None,
        start_ns=10,
        end_ns=20,
        flow_direction_prior=0.0,
    )
    cal = EventCalendar(session_date=date(2026, 3, 24), windows=(w,))
    assert cal.windows_active_at(9) == ()
    assert cal.windows_active_at(10) == (w,)
    assert cal.windows_active_at(19) == (w,)
    assert cal.windows_active_at(20) == ()


def test_load_reference_calendar() -> None:
    """The committed 2026-03-24 reference calendar loads cleanly."""
    cal = load_event_calendar(REFERENCE_CALENDAR_PATH)
    assert cal.session_date == date(2026, 3, 24)
    assert len(cal.windows) == 5
    ids = {w.window_id for w in cal.windows}
    assert ids == {
        "nyse_open_2026_03_24",
        "aapl_earnings_drift_2026_03_24",
        "fomc_blackout_2026_03_24_pre",
        "fomc_blackout_2026_03_24_post",
        "nyse_moc_2026_03_24",
    }


def test_load_reference_calendar_hash_is_deterministic() -> None:
    """Two loads of the same file produce byte-identical hashes."""
    cal1 = load_event_calendar(REFERENCE_CALENDAR_PATH)
    cal2 = load_event_calendar(REFERENCE_CALENDAR_PATH)
    assert cal1.hash() == cal2.hash()
    # Locked baseline — bumping this requires intentional content edit
    # to the YAML alongside a rationalised commit message (Inv-13).
    assert cal1.hash() == (
        "0c76a8f8271330f0216ef781abd228fcdd423de4f4b0788c968ea9d044406974"
    )


def test_hash_invariant_under_window_reordering(tmp_path: Path) -> None:
    """A window list re-sorted by the loader must yield the same hash."""
    a = CalendarWindow(
        window_id="a",
        kind=WindowKind.OPENING_AUCTION,
        symbol=None,
        start_ns=10,
        end_ns=20,
        flow_direction_prior=0.0,
    )
    b = CalendarWindow(
        window_id="b",
        kind=WindowKind.MOC_IMBALANCE,
        symbol=None,
        start_ns=30,
        end_ns=40,
        flow_direction_prior=0.0,
    )
    cal_ab = EventCalendar(session_date=date(2026, 3, 24), windows=(a, b))
    cal_ba_sorted = EventCalendar(
        session_date=date(2026, 3, 24),
        windows=tuple(sorted((b, a), key=lambda w: (w.start_ns, w.kind.value, w.window_id))),
    )
    assert cal_ab.hash() == cal_ba_sorted.hash()


def test_load_rejects_unknown_window_kind(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "session_date: 2026-03-24\n"
        "windows:\n"
        "  - window_id: x\n"
        "    kind: BOGUS_KIND\n"
        "    start_et: '09:30'\n"
        "    end_et: '09:35'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="WindowKind"):
        load_event_calendar(bad)


def test_load_rejects_missing_required_keys(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("session_date: 2026-03-24\n", encoding="utf-8")
    with pytest.raises(ValueError, match="windows"):
        load_event_calendar(bad)


def test_load_supports_explicit_ns_bounds(tmp_path: Path) -> None:
    f = tmp_path / "ns.yaml"
    f.write_text(
        "session_date: 2026-03-24\n"
        "windows:\n"
        "  - window_id: ns\n"
        "    kind: OPENING_AUCTION\n"
        "    start_ns: 1000\n"
        "    end_ns: 2000\n"
        "    flow_direction_prior: 0\n",
        encoding="utf-8",
    )
    cal = load_event_calendar(f)
    assert cal.windows[0].start_ns == 1000
    assert cal.windows[0].end_ns == 2000
