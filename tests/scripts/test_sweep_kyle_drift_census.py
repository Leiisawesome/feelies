"""Cache-free tests for the H10 sweep-Kyle census instrument.

The synthetic golden covers episode counts, warm-up, and filter boundaries
without forward returns, IC, or grid execution.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from scripts.research.sweep_kyle_drift_census import (
    apply_warm_drop_rule,
    integrity_pin_check,
    is_entry_eligible,
    run_cell_from_events,
    trade_fails_sfi_filter,
)

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_SYM = "APP"
_DATE = "2026-01-15"  # calm stratum — in frozen STRATUM map


def _et_ns(hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(2026, 1, 15, hour, minute, second, tzinfo=_TZ_ET).timestamp() * 1e9)


def _trade(
    *,
    conditions: tuple[int, ...] = (14,),
    correction: int | None = None,
) -> Trade:
    return Trade(
        timestamp_ns=1,
        correlation_id="t",
        sequence=1,
        symbol="APP",
        price=Decimal("100"),
        size=100,
        exchange_timestamp_ns=1,
        conditions=conditions,
        correction=correction,
    )


def test_entry_eligible_long_short_and_interior_null() -> None:
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=1.0, p_breakout=0.2) == (
        True,
        "LONG",
    )
    assert is_entry_eligible(sfi=-0.5, pctl=0.05, rvz=1.0, p_breakout=0.2) == (
        True,
        "SHORT",
    )
    assert is_entry_eligible(sfi=0.5, pctl=0.50, rvz=1.0, p_breakout=0.2) == (
        False,
        None,
    )


def test_entry_eligible_sign_disagreement_and_gates() -> None:
    assert is_entry_eligible(sfi=-0.1, pctl=0.95, rvz=1.0, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.1, pctl=0.05, rvz=1.0, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=3.1, p_breakout=0.2)[0] is False
    assert is_entry_eligible(sfi=0.5, pctl=0.95, rvz=1.0, p_breakout=0.7)[0] is False
    assert is_entry_eligible(sfi=None, pctl=0.95, rvz=1.0, p_breakout=0.2)[0] is False


def test_trade_fails_sfi_filter_boundaries() -> None:
    assert trade_fails_sfi_filter(_trade(conditions=(14,))) is False
    assert trade_fails_sfi_filter(_trade(conditions=(14, 37, 41))) is False
    assert trade_fails_sfi_filter(_trade(conditions=(8,))) is True
    assert trade_fails_sfi_filter(_trade(conditions=(12,))) is True
    assert trade_fails_sfi_filter(_trade(conditions=(14,), correction=10)) is True
    assert trade_fails_sfi_filter(_trade(conditions=(14,), correction=1)) is False


def test_warm_drop_rule() -> None:
    # 3 sessions below 0.5 → drop
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.2, 0.9], "RMBS": [0.9, 0.9]}) == {"APP"}
    # exactly 2 bad → keep
    assert apply_warm_drop_rule({"APP": [0.4, 0.3, 0.9]}) == set()


def test_integrity_pin_reproduces_overlapping_counts() -> None:
    prior = [
        {"symbol": "APP", "date": "2025-11-25", "n_events": 10, "n_quotes": 4, "n_trades": 6},
        {"symbol": "RMBS", "date": "2025-11-25", "n_events": 8, "n_quotes": 3, "n_trades": 5},
    ]
    cells = [
        {"symbol": "APP", "date": "2025-11-25", "n_events": 10, "n_quotes": 4, "n_trades": 6},
        {"symbol": "OLN", "date": "2025-11-25", "n_events": 99, "n_quotes": 1, "n_trades": 1},
    ]
    assert integrity_pin_check(cells, prior) == []
    cells[0]["n_trades"] = 7
    mism = integrity_pin_check(cells, prior)
    assert len(mism) == 1 and "n_trades" in mism[0]


# Synthetic golden: the tape has one in-window 900-second boundary at 09:45.
# Forty-five rising ISO prints warm SFI and its percentile; a calm regime and
# flat volatility then produce one LONG episode. Filtered or cold trades
# produce none.


def _synth_tape(
    *,
    n_iso: int = 45,
    conditions: tuple[int, ...] = (14,),
    correction: int | None = None,
) -> list[NBBOQuote | Trade]:
    """Minimal RTH tape for the hand-computable §1.1 golden."""
    events: list[NBBOQuote | Trade] = []
    open_ns = _et_ns(9, 30, 0)
    end_ns = _et_ns(9, 50, 0)
    seq = 0
    t = open_ns
    while t <= end_ns:
        seq += 1
        events.append(
            NBBOQuote(
                timestamp_ns=t,
                correlation_id=f"q-{seq}",
                sequence=seq,
                symbol=_SYM,
                bid=Decimal("100.00"),
                ask=Decimal("100.02"),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=t,
            )
        )
        t += _NS

    # Rising ISO (or variant) prints strictly inside (09:31, 09:45) so the
    # trailing-900 s window at the sole in-window boundary holds them all.
    # 12 s spacing × 45 ≈ 9 min — fits before 09:45.
    trade_start = _et_ns(9, 31, 0)
    for i in range(n_iso):
        seq += 1
        ts = trade_start + i * 12 * _NS
        px = Decimal(f"{100.00 + (i + 1) * 0.01:.2f}")
        events.append(
            Trade(
                timestamp_ns=ts,
                correlation_id=f"t-{seq}",
                sequence=seq,
                symbol=_SYM,
                price=px,
                size=100,
                exchange_timestamp_ns=ts,
                conditions=conditions,
                correction=correction,
            )
        )
    return events


def test_section_1_1_synthetic_golden_long_episode_count() -> None:
    """Frozen §1.1 through the real census path → exactly 1 LONG episode."""
    cell = run_cell_from_events(_synth_tape(), _SYM, _DATE)
    assert cell is not None
    assert cell.n_in_window == 1  # hand: only 09:45 in [09:35, 15:50]
    assert cell.episodes == 1
    assert cell.episodes_long == 1
    assert cell.episodes_short == 0
    assert cell.sfi_warm_fraction_in_window == 1.0
    assert cell.residual_bug_flag is False


def test_section_1_1_synthetic_golden_warm_gate_suppresses() -> None:
    """< 20 eligible ISO prints ⇒ SFI not warm ⇒ zero episodes (arm 2)."""
    cell = run_cell_from_events(_synth_tape(n_iso=5), _SYM, _DATE)
    assert cell is not None
    assert cell.n_in_window == 1
    assert cell.episodes == 0
    assert cell.sfi_warm_fraction_in_window == 0.0


def test_section_1_1_synthetic_golden_filter_exclusion_suppresses() -> None:
    """Class-B / non-id-14 prints do not enter SFI ⇒ zero episodes (filter)."""
    cell = run_cell_from_events(
        _synth_tape(conditions=(8,)),  # closing print — fails Class-A ∩ id-14
        _SYM,
        _DATE,
    )
    assert cell is not None
    assert cell.n_in_window == 1
    assert cell.episodes == 0
    assert cell.sfi_warm_fraction_in_window == 0.0


def test_section_1_1_synthetic_golden_correction_drop_suppresses() -> None:
    """correction ∈ {10,11,12} dropped at sensor ⇒ zero episodes."""
    cell = run_cell_from_events(
        _synth_tape(conditions=(14,), correction=10),
        _SYM,
        _DATE,
    )
    assert cell is not None
    assert cell.episodes == 0
    assert cell.sfi_warm_fraction_in_window == 0.0
