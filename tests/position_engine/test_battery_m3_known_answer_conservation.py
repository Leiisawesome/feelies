"""Member 3: known-answer conservation. Red until stage E."""

from __future__ import annotations

import pytest

from feelies.core.events import PositionClosed
from tests.position_engine.scenarios import (
    T0,
    Records,
    assert_no_risk_rejects,
    cell_economics,
    drawn_adverse_level,
    fixture_variant,
    mean_within_se,
    nonvacuous,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape

_MARK = pytest.mark.battery_member(member=3, green_from="E", red_reason="^NONVACUOUS: ")

# 120_000 quotes × 0.1s = 12_000s. Odd 30s boundaries: 200 entries.
# T_seconds exceeds that span (D-50). Spread is 1 tick, so u = X + 1 and d = L - 1.
_N = 120_000
_T_LONG = 16_000
_SEED_A = 11
_SEED_A2 = 17
_SEED_B = 19
_SEED_C = 23


def _base(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "horizon_seconds": 30,
        "fee_round_trip_ticks": 0,
        "T_seconds": _T_LONG,
        "centre_ticks": 11,
        "band_ticks": 0,
        "lo_ticks": 2,
        "target_ticks": 4,
    }
    params.update(overrides)
    return fixture_variant(**params)


def _tape(seed: int) -> list:
    return make_tape(seed=seed, n=_N, symbol="SYN", start_ns=T0, size=1000)


def _closed(records: Records) -> list:
    return [row for row in records if row.type_name == "PositionClosed"]


def _spread(records: Records, row: object) -> int:
    import json

    body = json.loads(row.canonical[row.canonical.index("{") :])  # type: ignore[attr-defined]
    entry = body["entry_fills"][0]
    quote = records.quotes[int(entry["sequence"])]
    return int(quote.ask * 100) - int(quote.bid * 100)


def _displacements(records: Records) -> list[float]:
    return [float(cell_economics(row, records.quotes)[1]) for row in _closed(records)]


@_MARK
def test_m3_barriers_only() -> None:
    """(a) no deadline. V3a is u:d = 5:10 = 1:2, expected favorable share 2/3."""
    records = run_synthetic(_tape(_SEED_A), symbols=("SYN",), variant=_base())
    nonvacuous(records, PositionClosed, scenario="m3_barriers")
    assert_no_risk_rejects(records)
    cells = _closed(records)
    assert len(cells) >= 200, f"m3_barriers closed cells {len(cells)} < 200"
    mean_within_se(_displacements(records), 0.0, label="displacement")
    flags = [1.0 if '"exit_reason":"FAVORABLE"' in row.canonical else 0.0 for row in cells]
    mean_within_se(flags, 2 / 3, label="favorable share")


@_MARK
def test_m3_barriers_swapped() -> None:
    """(a) second pair, V3a2, u:d = 10:5, expected share 1/3."""
    variant = _base(centre_ticks=6, target_ticks=9)
    records = run_synthetic(_tape(_SEED_A2), symbols=("SYN",), variant=variant)
    nonvacuous(records, PositionClosed, scenario="m3_barriers_swapped")
    assert_no_risk_rejects(records)
    cells = _closed(records)
    assert len(cells) >= 200, f"m3_barriers_swapped closed cells {len(cells)} < 200"
    mean_within_se(_displacements(records), 0.0, label="displacement")
    flags = [1.0 if '"exit_reason":"FAVORABLE"' in row.canonical else 0.0 for row in cells]
    mean_within_se(flags, 1 / 3, label="favorable share")


@_MARK
def test_m3_barriers_and_deadline() -> None:
    """(b) V3b. Realized moves of the three exit groups integrate to zero."""
    records = run_synthetic(
        _tape(_SEED_B),
        symbols=("SYN",),
        variant=_base(T_seconds=10),
    )
    nonvacuous(records, PositionClosed, scenario="m3_deadline")
    assert_no_risk_rejects(records)
    grouped = [
        float(cell_economics(row, records.quotes)[1])
        for row in _closed(records)
        if any(
            token in row.canonical
            for token in (
                '"exit_reason":"ADVERSE"',
                '"exit_reason":"HORIZON"',
                '"exit_reason":"FAVORABLE"',
            )
        )
    ]
    assert len(grouped) >= 200, f"m3_deadline grouped cells {len(grouped)} < 200"
    mean_within_se(grouped, 0.0, label="grouped displacement")


@_MARK
def test_m3_band_draw() -> None:
    """(c) V3c. Clause (a) averaged over per-cell draws."""
    records = run_synthetic(
        _tape(_SEED_C),
        symbols=("SYN",),
        variant=_base(band_ticks=8, lo_ticks=7, hi_ticks=15),
    )
    nonvacuous(records, PositionClosed, scenario="m3_band")
    assert_no_risk_rejects(records)
    cells = _closed(records)
    assert len(cells) >= 200, f"m3_band closed cells {len(cells)} < 200"
    mean_within_se(_displacements(records), 0.0, label="displacement")
    residuals: list[float] = []
    for row in cells:
        import json

        body = json.loads(row.canonical[row.canonical.index("{") :])
        spread = _spread(records, row)
        level = drawn_adverse_level(str(body["cell_id"]), 11, 8)
        favorable_ticks = 4 + spread
        adverse_ticks = level - spread
        expected = adverse_ticks / (favorable_ticks + adverse_ticks)
        hit = 1.0 if body["exit_reason"] == "FAVORABLE" else 0.0
        residuals.append(hit - expected)
    mean_within_se(residuals, 0.0, label="band share residual")
