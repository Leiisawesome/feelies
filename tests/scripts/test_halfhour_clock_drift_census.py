"""Unit tests + synthetic-fixture golden for H12 census (no cache contact).

Pins the frozen §1.1 predicate BOTH arms (in-window ``W_hh=1`` and matched
out-window ``W_hh=0``) at build time — 8-C-H10 lesson. Zero forward-return /
IC / grid execution. N = 12 unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from feelies.storage.reference.event_calendar import (
    EventCalendar,
    WindowKind,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR
from scripts.research.halfhour_clock_drift_census import (
    apply_warm_drop_rule,
    is_entry_eligible,
    ofi_quintile_side,
    quote_dropped_by_ofi,
    run_cell_from_events,
)

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_SYM = "APP"
_DATE = "2026-01-15"


def _et_ns(hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(2026, 1, 15, hour, minute, second, tzinfo=_TZ_ET).timestamp() * 1e9)


def test_ofi_quintile_side_long_short_interior_and_gates() -> None:
    assert ofi_quintile_side(ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2) == (True, "LONG")
    assert ofi_quintile_side(ofi=-1.0, pctl=0.15, rvz=1.0, p_breakout=0.2) == (True, "SHORT")
    assert ofi_quintile_side(ofi=1.0, pctl=0.50, rvz=1.0, p_breakout=0.2) == (False, None)
    assert ofi_quintile_side(ofi=-1.0, pctl=0.85, rvz=1.0, p_breakout=0.2)[0] is False
    assert ofi_quintile_side(ofi=1.0, pctl=0.15, rvz=1.0, p_breakout=0.2)[0] is False
    assert ofi_quintile_side(ofi=1.0, pctl=0.85, rvz=3.1, p_breakout=0.2)[0] is False
    assert ofi_quintile_side(ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.7)[0] is False


def test_is_entry_eligible_both_clock_arms() -> None:
    """Primary requires W_hh≥0.5; F2 contrast requires W_hh<0.5."""
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hh=1.0, require_clock=True
    ) == (True, "LONG")
    assert (
        is_entry_eligible(
            ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hh=0.0, require_clock=True
        )[0]
        is False
    )
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hh=0.0, require_clock=False
    ) == (True, "LONG")
    assert (
        is_entry_eligible(
            ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hh=1.0, require_clock=False
        )[0]
        is False
    )


def test_quote_dropped_by_ofi_matches_sensor_gate() -> None:
    assert quote_dropped_by_ofi(100.0, 100.02) is False
    assert quote_dropped_by_ofi(0.0, 100.02) is True
    assert quote_dropped_by_ofi(100.02, 100.00) is True  # crossed
    assert quote_dropped_by_ofi(100.0, 100.0) is False  # locked OK for ofi_raw


def test_warm_drop_rule() -> None:
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.2, 0.9], "RMBS": [0.9]}) == {"APP"}
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.9]}) == set()


# Synthetic golden: 900-second boundaries fall at 09:45, 10:00, and 10:15.
# The calendar admits only 10:00. Warm positive OFI, a calm regime, and flat
# volatility therefore produce one in-window LONG episode and two outside it.


def _synth_tape(*, buy_pressure: bool = True, end_hour: int = 10, end_minute: int = 20) -> list:
    """Flat mid (calm HMM) with monotonic bid/ask *size* changes for signed OFI.

    Bid size rising at a fixed bid/ask level ⇒ positive CKS OFI without a
    mid trend that would trip ``P(vol_breakout)``.
    """
    events: list[NBBOQuote | Trade] = []
    open_ns = _et_ns(9, 30, 0)
    end_ns = _et_ns(end_hour, end_minute, 0)
    seq = 0
    t = open_ns
    step = 0
    bid = Decimal("100.00")
    ask = Decimal("100.02")
    while t <= end_ns:
        seq += 1
        # Monotone size path so successive same-level OFI contributions are
        # identical and the Hazen percentile of the latest sample is ~1.0
        # (buy) or the ask-side mirror for sell pressure.
        if buy_pressure:
            bid_sz = 100 + step
            ask_sz = 100
        else:
            bid_sz = 100
            ask_sz = 100 + step
        events.append(
            NBBOQuote(
                timestamp_ns=t,
                correlation_id=f"q-{seq}",
                sequence=seq,
                symbol=_SYM,
                bid=bid,
                ask=ask,
                bid_size=bid_sz,
                ask_size=ask_sz,
                exchange_timestamp_ns=t,
            )
        )
        step += 1
        t += _NS
    return events


def test_section_1_1_synthetic_golden_both_arms_long() -> None:
    """Frozen §1.1 through real census path — both F2 arms hand-computable."""
    cal = load_event_calendar(
        EVENT_CALENDAR_DIR / f"{_DATE}.yaml",
        expected_session_date=date(2026, 1, 15),
    )
    assert any(w.kind is WindowKind.ALGO_CLOCK for w in cal.windows)

    cell = run_cell_from_events(_synth_tape(buy_pressure=True), _SYM, _DATE, calendar=cal)
    assert cell is not None
    assert cell.n_in_window == 3  # 09:45, 10:00, 10:15
    assert cell.episodes_in_window == 1
    assert cell.episodes_in_window_long == 1
    assert cell.episodes_in_window_short == 0
    assert cell.episodes_out_window == 2
    assert cell.episodes_out_window_long == 2
    assert cell.episodes_out_window_short == 0
    assert cell.calendar_warm_fraction_in_window == 1.0
    assert cell.calendar_missing_rate == 0.0
    assert cell.leakage_bug_flag is False
    # Geometry among quintile-eligible in-session boundaries: 2/3 off-clock.
    assert cell.off_clock_cotravel_rate == 2 / 3


def test_section_1_1_synthetic_golden_empty_calendar_suppresses() -> None:
    """Empty calendar ⇒ scheduled_flow_window cold ⇒ zero episodes (arm 2)."""
    empty = EventCalendar(session_date=date(2026, 1, 15), windows=())
    cell = run_cell_from_events(_synth_tape(), _SYM, _DATE, calendar=empty)
    assert cell is not None
    assert cell.n_in_window == 3
    assert cell.episodes_in_window == 0
    assert cell.episodes_out_window == 0
    assert cell.calendar_warm_fraction_in_window == 0.0
    assert cell.calendar_missing_rate == 1.0


def test_section_1_1_synthetic_golden_loads_authored_calendar_by_default() -> None:
    """calendar=None loads EVENT_CALENDAR_DIR/{date}.yaml (warm-iff-calendar)."""
    cell = run_cell_from_events(_synth_tape(), _SYM, _DATE, calendar=None)
    assert cell is not None
    assert cell.calendar_missing_rate == 0.0
    assert cell.calendar_hash is not None
    assert cell.episodes_in_window == 1
    assert cell.episodes_out_window == 2
