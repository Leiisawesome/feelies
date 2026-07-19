"""H13 Phase A — hour-only ALGO_CLOCK derivation bit-identity (JC-10).

Census precondition: re-running the ``:00``-filter transform under
``PYTHONHASHSEED=0`` on the same committed calendars must produce
bit-identical derived-view content / content-addressed hash per date.
``:30`` marks are excluded from the injection view. Exchange-schedule
only — no market-data cache contact. N = 12 unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor
from feelies.storage.reference.event_calendar import (
    WindowKind,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR
from scripts.research.author_algo_clock_calendars import DATES_ALL, HALF_HOUR_MARKS
from scripts.research.derive_hour_only_algo_clock_calendars import (
    HOUR_MARKS,
    derive_all,
    derive_hour_only_calendar,
    derived_view_hashes,
    load_hour_only_calendar,
)

_TZ_ET = ZoneInfo("America/New_York")
_NS = 1_000_000_000


def _et_ns(session: date, hour: int, minute: int, second: int = 0) -> int:
    return int(
        datetime(
            session.year,
            session.month,
            session.day,
            hour,
            minute,
            second,
            tzinfo=_TZ_ET,
        ).timestamp()
        * 1e9
    )


def test_hour_only_retains_six_on_the_hour_marks() -> None:
    for d in DATES_ALL:
        view = load_hour_only_calendar(d)
        assert view is not None
        assert len(view.windows) == 6
        assert all(w.kind is WindowKind.ALGO_CLOCK for w in view.windows)
        session = date.fromisoformat(d)
        for hour, minute in HOUR_MARKS:
            mark = _et_ns(session, hour, minute, 0)
            assert sum(1 for w in view.windows if w.contains(mark)) == 1


def test_hour_only_excludes_half_hour_marks() -> None:
    """``:30`` marks must not admit contains(boundary) under the injection view."""
    session = date(2025, 11, 25)
    view = load_hour_only_calendar("2025-11-25")
    assert view is not None
    for hour, minute in HALF_HOUR_MARKS:
        if minute == 0:
            continue
        mark = _et_ns(session, hour, minute, 0)
        assert not any(w.contains(mark) for w in view.windows)


def test_hour_only_excludes_non_algo_clock_rows() -> None:
    """OPENING/MOC survive in committed files but not in the H13 injection view."""
    source = load_event_calendar(
        EVENT_CALENDAR_DIR / "2026-01-15.yaml",
        expected_session_date=date(2026, 1, 15),
    )
    assert any(w.kind is WindowKind.OPENING_AUCTION for w in source.windows)
    assert any(w.kind is WindowKind.MOC_IMBALANCE for w in source.windows)
    view = derive_hour_only_calendar(source)
    assert all(w.kind is WindowKind.ALGO_CLOCK for w in view.windows)
    assert len(view.windows) == 6


def test_hour_only_derivation_bit_identical_hashes() -> None:
    """Census precondition (JC-10): identical derived views / hashes on re-run."""
    views_a = derive_all()
    hashes_a = {d: views_a[d].hash() for d in DATES_ALL}
    window_ids_a = {d: tuple(w.window_id for w in views_a[d].windows) for d in DATES_ALL}

    views_b = derive_all()
    hashes_b = derived_view_hashes()
    window_ids_b = {d: tuple(w.window_id for w in views_b[d].windows) for d in DATES_ALL}

    assert hashes_a == hashes_b
    assert window_ids_a == window_ids_b
    assert len(hashes_a) == 20
    # Derived hash differs from the committed full-calendar hash (:30 excluded).
    for d in DATES_ALL:
        committed = load_event_calendar(
            EVENT_CALENDAR_DIR / f"{d}.yaml",
            expected_session_date=date.fromisoformat(d),
        )
        assert hashes_a[d] != committed.hash()


def test_scheduled_flow_window_hour_only_active_at_hour_not_half() -> None:
    """W_hr via hour-only injection: active at :00, inactive at :30."""
    view = load_hour_only_calendar("2025-11-25")
    assert view is not None
    sensor = ScheduledFlowWindowSensor(calendar=view)
    state = sensor.initial_state()
    session = date(2025, 11, 25)

    def _quote(ts: int, seq: int) -> NBBOQuote:
        return NBBOQuote(
            timestamp_ns=ts,
            correlation_id=f"q-{seq}",
            sequence=seq,
            symbol="APP",
            bid=Decimal("10"),
            ask=Decimal("10.02"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=ts,
        )

    r_hour = sensor.update(_quote(_et_ns(session, 10, 0, 0), 1), state, {})
    assert r_hour is not None
    assert r_hour.warm is True
    assert r_hour.value[0] == 1.0

    r_half = sensor.update(_quote(_et_ns(session, 10, 30, 0), 2), state, {})
    assert r_half is not None
    assert r_half.warm is True
    assert r_half.value[0] == 0.0


def test_evidence_pool_date_surface_covers_all_twenty_operative_dates() -> None:
    """Eight-symbol pool calendars: 20 D dates (ENSG/MLI use the preamble 10)."""
    views = derive_all()
    assert set(views) == set(DATES_ALL)
    assert len(DATES_ALL) == 20
