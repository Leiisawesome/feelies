"""Unit tests + synthetic-fixture golden for H13 census (no cache contact).

Pins the frozen §1.1 predicate BOTH arms (in-hour ``W_hr=1`` and matched
:30 ``W_hr=0``) at build time — 8-C-H10 lesson. Includes an ENSG/MLI
evidence-only cell case (never-promotable; counts toward evidence-pool
power). Zero forward-return / IC / grid execution. N = 12 unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from feelies.storage.reference.event_calendar import EventCalendar
from scripts.research.derive_hour_only_algo_clock_calendars import (
    load_hour_only_calendar,
)
from scripts.research.hour_checkpoint_drift_census import (
    apply_warm_drop_rule,
    is_entry_eligible,
    ofi_quintile_side,
    quote_dropped_by_ofi,
    run_cell_from_events,
    sigma_min_bps,
)

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
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
    """Primary requires W_hr≥0.5; F2 :30 contrast requires W_hr<0.5."""
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hr=1.0, require_hour=True
    ) == (True, "LONG")
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hr=0.0, require_hour=True
    )[0] is False
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hr=0.0, require_hour=False
    ) == (True, "LONG")
    assert is_entry_eligible(
        ofi=1.0, pctl=0.85, rvz=1.0, p_breakout=0.2, w_hr=1.0, require_hour=False
    )[0] is False


def test_quote_dropped_by_ofi_matches_sensor_gate() -> None:
    assert quote_dropped_by_ofi(100.0, 100.02) is False
    assert quote_dropped_by_ofi(0.0, 100.02) is True
    assert quote_dropped_by_ofi(100.02, 100.00) is True
    assert quote_dropped_by_ofi(100.0, 100.0) is False


def test_warm_drop_rule() -> None:
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.2, 0.9], "RMBS": [0.9]}) == {"APP"}
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.9]}) == set()


def test_sigma_min_bps_matches_protocol_floors() -> None:
    """σ₁₈₀₀ min = floor/κ; APP 4.68/0.172 ≈ 27.21."""
    assert abs(sigma_min_bps("APP") - 27.2093) < 1e-3
    assert abs(sigma_min_bps("ENSG") - 29.3023) < 1e-3
    assert abs(sigma_min_bps("MLI") - 30.9302) < 1e-3


# ── §1.1 synthetic-fixture golden (both F2 arms; pinned at build time) ───
#
# Hand computation (fixed construction on 2026-01-15 + hour-only view):
#   session_open = 09:30 ET; H = 1800.
#   Tape 09:30 → 11:00 ⇒ h=1800 boundaries at 09:30, 10:00, 10:30, 11:00.
#   Session window = offset ≥ 300 s AND ET ≤ 15:50 ⇒ {10:00, 10:30, 11:00}
#   (n_in_window = 3).  Hour-only ALGO_CLOCK admits 10:00 and 11:00
#   ⇒ W_hr=1 at those; W_hr=0 at 10:30 (:30 F2 arm).
#   Quotes every 1 s at a flat mid with rising bid size ⇒ ofi_raw warm
#   (≥50) and Hazen ofi_integrated_percentile = (n−0.5)/n ≥ 0.80 under
#   equal +Δsize readings; ofi_integrated > 0; calm HMM (no mid trend);
#   rvz ≈ 0.  ⇒ exactly 2 in-hour LONG + 1 halfhour LONG episodes.


def _synth_tape(
    symbol: str,
    *,
    buy_pressure: bool = True,
    end_hour: int = 11,
    end_minute: int = 0,
) -> list:
    """Flat mid (calm HMM) with monotonic bid/ask *size* changes for signed OFI."""
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
                symbol=symbol,
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
    cal = load_hour_only_calendar(_DATE)
    assert cal is not None
    assert len(cal.windows) == 6

    cell = run_cell_from_events(
        _synth_tape("APP", buy_pressure=True), "APP", _DATE, calendar=cal
    )
    assert cell is not None
    assert cell.role == "deployable"
    assert cell.n_in_window == 3  # 10:00, 10:30, 11:00
    assert cell.episodes_in_hour == 2
    assert cell.episodes_in_hour_long == 2
    assert cell.episodes_in_hour_short == 0
    assert cell.episodes_halfhour == 1
    assert cell.episodes_halfhour_long == 1
    assert cell.episodes_halfhour_short == 0
    assert cell.calendar_warm_fraction_in_window == 1.0
    assert cell.calendar_missing_rate == 0.0
    assert cell.leakage_bug_flag is False
    assert cell.derived_view_hash is not None
    # Geometry among quintile-eligible in-session boundaries: 1/3 are :30.
    assert cell.halfhour_not_hour_cotravel_rate == 1 / 3


def test_section_1_1_synthetic_golden_ensg_evidence_only_cell() -> None:
    """ENSG evidence-only cell: same predicate counts; role never-promotable."""
    cal = load_hour_only_calendar(_DATE)
    assert cal is not None
    cell = run_cell_from_events(
        _synth_tape("ENSG", buy_pressure=True), "ENSG", _DATE, calendar=cal
    )
    assert cell is not None
    assert cell.role == "evidence_only"
    assert cell.symbol == "ENSG"
    assert cell.n_in_window == 3
    assert cell.episodes_in_hour == 2
    assert cell.episodes_halfhour == 1
    assert cell.calendar_missing_rate == 0.0
    # Evidence-only still gets σ / viability labels (diagnostic + power pool).
    assert cell.sigma1800_n_returns >= 0


def test_section_1_1_synthetic_golden_mli_evidence_only_cell() -> None:
    """MLI evidence-only mirror of the ENSG case (both arms)."""
    cal = load_hour_only_calendar(_DATE)
    assert cal is not None
    cell = run_cell_from_events(
        _synth_tape("MLI", buy_pressure=True), "MLI", _DATE, calendar=cal
    )
    assert cell is not None
    assert cell.role == "evidence_only"
    assert cell.episodes_in_hour == 2
    assert cell.episodes_halfhour == 1


def test_section_1_1_synthetic_golden_empty_calendar_suppresses() -> None:
    """Empty hour-only view ⇒ scheduled_flow_window cold ⇒ zero episodes."""
    empty = EventCalendar(session_date=date(2026, 1, 15), windows=())
    cell = run_cell_from_events(_synth_tape("APP"), "APP", _DATE, calendar=empty)
    assert cell is not None
    assert cell.n_in_window == 3
    assert cell.episodes_in_hour == 0
    assert cell.episodes_halfhour == 0
    assert cell.calendar_warm_fraction_in_window == 0.0
    assert cell.calendar_missing_rate == 1.0


def test_section_1_1_synthetic_golden_loads_hour_only_by_default() -> None:
    """calendar=None ⇒ committed YAML → hour-only derive (warm-iff-calendar)."""
    cell = run_cell_from_events(_synth_tape("APP"), "APP", _DATE, calendar=None)
    assert cell is not None
    assert cell.calendar_missing_rate == 0.0
    assert cell.derived_view_hash is not None
    assert cell.episodes_in_hour == 2
    assert cell.episodes_halfhour == 1
