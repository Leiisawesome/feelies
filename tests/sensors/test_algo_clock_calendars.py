"""H12 Phase A — ALGO_CLOCK taxonomy + half-hour calendar authoring guards.

Exchange-schedule only. No market-data cache contact. Pins:

* ``WindowKind.ALGO_CLOCK`` round-trip / unknown-kind rejection;
* ``[M, M+1s)`` membership at half-hour marks;
* window-authoring determinism (bit-identical YAML + ``EventCalendar.hash``
  on re-run under the authoring script);
* ``scheduled_flow_window`` warms for {APP, RMBS} from authored calendars.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor
from feelies.storage.reference.event_calendar import (
    WindowKind,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR
from scripts.research.author_algo_clock_calendars import (
    DATES_ALL,
    HALF_HOUR_MARKS,
    author_all,
    calendar_hashes,
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


def test_algo_clock_kind_round_trip(tmp_path: Path) -> None:
    yaml_text = (
        "session_date: 2025-11-25\n"
        "windows:\n"
        "  - window_id: algo_clock_hh_1000_2025_11_25\n"
        "    kind: ALGO_CLOCK\n"
        "    symbol: null\n"
        "    start_et: '10:00'\n"
        "    end_et: '10:00:01'\n"
        "    flow_direction_prior: 0.0\n"
        "    meta:\n"
        "      card: sig_halfhour_clock_drift_h900_v1\n"
        "      mark_class: half_hour\n"
    )
    path = tmp_path / "2025-11-25.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    cal = load_event_calendar(path, expected_session_date=date(2025, 11, 25))
    assert len(cal.windows) == 1
    assert cal.windows[0].kind is WindowKind.ALGO_CLOCK
    assert cal.windows[0].flow_direction_prior == 0.0
    assert cal.windows[0].symbol is None


def test_algo_clock_half_open_mark_membership() -> None:
    """Boundary at M is in-window; M+1s and next :15 mark are out."""
    session = date(2025, 11, 25)
    path = EVENT_CALENDAR_DIR / "2025-11-25.yaml"
    cal = load_event_calendar(path, expected_session_date=session)
    mark = _et_ns(session, 10, 0, 0)
    assert any(w.kind is WindowKind.ALGO_CLOCK and w.contains(mark) for w in cal.windows)
    assert not any(w.kind is WindowKind.ALGO_CLOCK and w.contains(mark + _NS) for w in cal.windows)
    # 10:15 is the F2 off-clock mark — must not be inside any ALGO_CLOCK window.
    off = _et_ns(session, 10, 15, 0)
    assert not any(w.kind is WindowKind.ALGO_CLOCK and w.contains(off) for w in cal.windows)


def test_operative_grid_calendars_have_twelve_algo_clock_marks() -> None:
    for d in DATES_ALL:
        path = EVENT_CALENDAR_DIR / f"{d}.yaml"
        assert path.is_file(), f"missing authored calendar for {d}"
        cal = load_event_calendar(path, expected_session_date=date.fromisoformat(d))
        algo = [w for w in cal.windows if w.kind is WindowKind.ALGO_CLOCK]
        assert len(algo) == 12
        assert all(w.symbol is None for w in algo)
        assert all(w.flow_direction_prior == 0.0 for w in algo)
        # Exactly 1 s duration per mark.
        for w in algo:
            assert w.end_ns - w.start_ns == _NS
        session = date.fromisoformat(d)
        for hour, minute in HALF_HOUR_MARKS:
            mark = _et_ns(session, hour, minute, 0)
            assert sum(1 for w in algo if w.contains(mark)) == 1


def test_2026_01_15_preserves_opening_and_moc_rows() -> None:
    """Merge contract: pre-existing OPENING/MOC rows survive ALGO_CLOCK authoring."""
    cal = load_event_calendar(
        EVENT_CALENDAR_DIR / "2026-01-15.yaml",
        expected_session_date=date(2026, 1, 15),
    )
    kinds = {w.kind for w in cal.windows}
    assert WindowKind.OPENING_AUCTION in kinds
    assert WindowKind.MOC_IMBALANCE in kinds
    assert WindowKind.ALGO_CLOCK in kinds
    assert sum(1 for w in cal.windows if w.kind is WindowKind.ALGO_CLOCK) == 12


def test_window_authoring_determinism_bit_identical_yaml_and_hash(tmp_path: Path) -> None:
    """Census precondition: re-author under same schedule → bit-identical artifacts."""
    # Seed 2026-01-15 with non-ALGO rows so the merge path is exercised.
    seed_open = (
        "session_date: 2026-01-15\n"
        "windows:\n"
        "  - window_id: nyse_open_2026_01_15\n"
        "    kind: OPENING_AUCTION\n"
        "    symbol: null\n"
        "    start_et: '09:30'\n"
        "    end_et: '09:35'\n"
        "    flow_direction_prior: 0.0\n"
        "    meta:\n"
        "      description: opening\n"
        "  - window_id: moc_imbalance_2026_01_15\n"
        "    kind: MOC_IMBALANCE\n"
        "    symbol: null\n"
        "    start_et: '15:50'\n"
        "    end_et: '16:00'\n"
        "    flow_direction_prior: 1.0\n"
        "    meta:\n"
        "      description: moc\n"
    )
    (tmp_path / "2026-01-15.yaml").write_text(seed_open, encoding="utf-8", newline="\n")

    author_all(tmp_path, write=True)
    texts_a = {d: (tmp_path / f"{d}.yaml").read_bytes() for d in DATES_ALL}
    hashes_a = calendar_hashes(tmp_path)

    author_all(tmp_path, write=True)
    texts_b = {d: (tmp_path / f"{d}.yaml").read_bytes() for d in DATES_ALL}
    hashes_b = calendar_hashes(tmp_path)

    assert texts_a == texts_b
    assert hashes_a == hashes_b
    assert len(hashes_a) == 20


def test_scheduled_flow_window_warms_for_app_and_rmbs() -> None:
    """Warm-iff-calendar: authored calendars arm scheduled_flow_window for D."""
    for sym in ("APP", "RMBS"):
        for d in ("2025-11-25", "2026-01-15"):
            cal = load_event_calendar(
                EVENT_CALENDAR_DIR / f"{d}.yaml",
                expected_session_date=date.fromisoformat(d),
            )
            sensor = ScheduledFlowWindowSensor(calendar=cal)
            state = sensor.initial_state()
            session = date.fromisoformat(d)
            # Outside any window — still warm (calendar has symbol-eligible rows).
            ts_off = _et_ns(session, 10, 15, 0)
            from feelies.core.events import NBBOQuote
            from decimal import Decimal

            quote = NBBOQuote(
                timestamp_ns=ts_off,
                correlation_id="q",
                sequence=1,
                symbol=sym,
                bid=Decimal("10"),
                ask=Decimal("10.02"),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=ts_off,
            )
            reading = sensor.update(quote, state, {})
            assert reading is not None
            assert reading.warm is True
            assert reading.value[0] == 0.0  # active

            ts_on = _et_ns(session, 10, 0, 0)
            quote_on = NBBOQuote(
                timestamp_ns=ts_on,
                correlation_id="q2",
                sequence=2,
                symbol=sym,
                bid=Decimal("10"),
                ask=Decimal("10.02"),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=ts_on,
            )
            reading_on = sensor.update(quote_on, state, {})
            assert reading_on is not None
            assert reading_on.warm is True
            assert reading_on.value[0] == 1.0  # ALGO_CLOCK active


def test_fixture_2026_03_24_hash_baseline_untouched() -> None:
    """Non-operative fixture date must keep its locked Inv-13 hash (no ALGO_CLOCK)."""
    cal = load_event_calendar(EVENT_CALENDAR_DIR / "2026-03-24.yaml")
    assert not any(w.kind is WindowKind.ALGO_CLOCK for w in cal.windows)
    assert cal.hash() == ("0c76a8f8271330f0216ef781abd228fcdd423de4f4b0788c968ea9d044406974")


def test_load_rejects_unknown_kind_still(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "session_date: 2025-11-25\n"
        "windows:\n"
        "  - window_id: x\n"
        "    kind: NOT_A_KIND\n"
        "    start_et: '09:30'\n"
        "    end_et: '09:35'\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="WindowKind"):
        load_event_calendar(bad)
