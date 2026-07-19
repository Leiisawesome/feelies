"""Tests for SweepFlowImbalanceSensor (H10 Phase-A; formal spec §1.1.1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.sweep_flow_imbalance import (
    DEFAULT_DROP_CORRECTION_RECORDS,
    INTERPRETED_TRADE_CONDITION_IDS,
    SweepFlowImbalanceSensor,
    is_class_a_intersect_id14,
    recompute_sfi_from_window,
    unknown_trade_condition_ids,
)

_NS = 1_000_000_000


def _trade(
    ts_ns: int,
    price: str,
    size: int = 100,
    *,
    conditions: tuple[int, ...] = (14,),
    correction: int | None = None,
) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol="APP",
        price=Decimal(price),
        size=size,
        exchange_timestamp_ns=ts_ns,
        conditions=conditions,
        correction=correction,
    )


def _quote(ts_ns: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol="APP",
        bid=Decimal("100.00"),
        ask=Decimal("100.02"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _drive(sensor: SweepFlowImbalanceSensor, events: list[Trade | NBBOQuote]):
    state = sensor.initial_state()
    last = None
    readings = []
    for ev in events:
        r = sensor.update(ev, state, params={})
        if r is not None:
            last = r
            readings.append(r)
    return last, state, readings


# ── constructor / filter helpers ──────────────────────────────────────────


def test_constructor_validates() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        SweepFlowImbalanceSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_eligible_prints"):
        SweepFlowImbalanceSensor(min_eligible_prints=-1)
    with pytest.raises(ValueError, match="max_gap_seconds"):
        SweepFlowImbalanceSensor(max_gap_seconds=0)
    with pytest.raises(ValueError, match="iso_id"):
        SweepFlowImbalanceSensor(iso_id=99, class_a_core_ids={14, 37})
    with pytest.raises(ValueError, match="epsilon"):
        SweepFlowImbalanceSensor(epsilon=0.0)


def test_filter_params_are_versioned_and_explicit() -> None:
    s = SweepFlowImbalanceSensor()
    p = s.filter_params()
    assert p["window_seconds"] == 900
    assert p["min_eligible_prints"] == 20
    assert p["max_gap_seconds"] == 60
    assert p["drop_correction_records"] == [10, 11, 12]
    assert p["iso_id"] == 14
    assert p["class_a_core_ids"] == [14, 37]
    assert p["overlay_ids"] == [41]
    assert p["retroactive_stamp_conditioning"] is False
    assert s.drop_correction_records == DEFAULT_DROP_CORRECTION_RECORDS


def test_class_a_intersect_id14_matrix() -> None:
    assert is_class_a_intersect_id14((14,))
    assert is_class_a_intersect_id14((14, 37))
    assert is_class_a_intersect_id14((14, 41))
    assert is_class_a_intersect_id14((14, 37, 41))
    assert not is_class_a_intersect_id14(())  # empty — no id-14
    assert not is_class_a_intersect_id14((37,))  # Class-A but no ISO
    assert not is_class_a_intersect_id14((12,))  # Form-T out of intersection
    assert not is_class_a_intersect_id14((14, 8))  # Class-B co-condition
    assert not is_class_a_intersect_id14((14, 999))  # unknown — no silent include


def test_unknown_id_guard_helper() -> None:
    assert unknown_trade_condition_ids((14, 37)) == frozenset()
    assert unknown_trade_condition_ids((14, 999)) == frozenset({999})
    assert 14 in INTERPRETED_TRADE_CONDITION_IDS


# ── hand-computed goldens ─────────────────────────────────────────────────


def test_golden_all_buy_iso_sweeps_sfi_plus_one() -> None:
    """Strictly rising ISO prints ⇒ all +1 aggressor ⇒ SFI = +1."""
    s = SweepFlowImbalanceSensor(window_seconds=900, min_eligible_prints=3)
    evs = [
        _trade((i + 1) * _NS, f"{100.00 + i * 0.01:.2f}", 100, conditions=(14,)) for i in range(5)
    ]
    last, state, _ = _drive(s, evs)
    assert last is not None and last.warm is True
    # First defaults +1; next four also buys → 500/500 = +1.0
    assert last.value == pytest.approx(1.0, abs=1e-12)
    assert recompute_sfi_from_window(list(state["window"])) == pytest.approx(last.value)


def test_golden_all_sell_iso_sweeps_sfi_minus_one() -> None:
    s = SweepFlowImbalanceSensor(window_seconds=900, min_eligible_prints=3)
    # First print defaults +1; subsequent falling ⇒ sells.
    evs = [
        _trade((i + 1) * _NS, f"{100.00 - i * 0.01:.2f}", 100, conditions=(14,)) for i in range(5)
    ]
    last, state, _ = _drive(s, evs)
    assert last is not None
    # +100 + 4*(-100) = -300 / 500 = -0.6
    assert last.value == pytest.approx(-0.6, abs=1e-12)
    assert recompute_sfi_from_window(list(state["window"])) == pytest.approx(last.value)


def test_golden_mixed_sizes_hand_computed() -> None:
    """Explicit sizes: buy 100, sell 300, buy 100 → signed = 100-300+100 = -100;
    vol = 500 → SFI = -0.2."""
    s = SweepFlowImbalanceSensor(window_seconds=900, min_eligible_prints=1)
    evs = [
        _trade(1 * _NS, "100.00", 100, conditions=(14,)),  # +1 default
        _trade(2 * _NS, "99.99", 300, conditions=(14, 37)),  # sell
        _trade(3 * _NS, "100.00", 100, conditions=(14, 41)),  # buy (overlay ok)
    ]
    last, state, _ = _drive(s, evs)
    assert last is not None
    assert last.value == pytest.approx(-0.2, abs=1e-12)
    assert recompute_sfi_from_window(list(state["window"])) == pytest.approx(-0.2)


# ── filter-boundary goldens (each excluded class) ─────────────────────────


@pytest.mark.parametrize(
    "conditions,label",
    [
        ((), "empty_no_iso"),
        ((37,), "odd_lot_only"),
        ((12,), "form_t"),
        ((8,), "closing_prints"),
        ((9,), "cross"),
        ((2,), "average_price"),
        ((14, 8), "iso_plus_class_b"),
        ((14, 999), "iso_plus_unknown"),
    ],
)
def test_filter_exclusion_golden_excluded_classes(conditions: tuple[int, ...], label: str) -> None:
    del label
    s = SweepFlowImbalanceSensor(min_eligible_prints=1)
    st = s.initial_state()
    # Seed with one eligible so a false-include would change state.
    assert s.update(_trade(1 * _NS, "100.00", 100, conditions=(14,)), st, {}) is not None
    before = (len(st["window"]), st["vol_sum"], st["signed_sum"])
    r = s.update(
        _trade(2 * _NS, "100.01", 500, conditions=conditions),
        st,
        {},
    )
    assert r is None
    assert (len(st["window"]), st["vol_sum"], st["signed_sum"]) == before


@pytest.mark.parametrize("correction", [10, 11, 12])
def test_filter_exclusion_golden_drop_correction_records(correction: int) -> None:
    s = SweepFlowImbalanceSensor(min_eligible_prints=1)
    st = s.initial_state()
    r = s.update(
        _trade(1 * _NS, "100.00", 100, conditions=(14,), correction=correction),
        st,
        {},
    )
    assert r is None
    assert len(st["window"]) == 0


@pytest.mark.parametrize("correction", [1, 7, 8, None, 0])
def test_no_retroactive_stamp_conditioning(correction: int | None) -> None:
    """correction ∈ {1,7,8} is future information — ingest as normal ISO print."""
    s = SweepFlowImbalanceSensor(min_eligible_prints=1)
    st = s.initial_state()
    r = s.update(
        _trade(1 * _NS, "100.00", 100, conditions=(14,), correction=correction),
        st,
        {},
    )
    assert r is not None
    assert len(st["window"]) == 1


def test_quote_returns_none() -> None:
    s = SweepFlowImbalanceSensor()
    assert s.update(_quote(1), s.initial_state(), params={}) is None


def test_non_positive_trade_ignored() -> None:
    s = SweepFlowImbalanceSensor()
    st = s.initial_state()
    assert s.update(_trade(1, "100.00", size=0), st, params={}) is None
    assert s.update(_trade(2, "0", size=100), st, params={}) is None


# ── warm / gap-flush ──────────────────────────────────────────────────────


def test_warm_gate_transitions() -> None:
    s = SweepFlowImbalanceSensor(window_seconds=900, min_eligible_prints=5)
    st = s.initial_state()
    r = None
    for i in range(4):
        r = s.update(
            _trade((i + 1) * _NS, f"{100.00 + i * 0.01:.2f}", conditions=(14,)),
            st,
            {},
        )
    assert r is not None and r.warm is False
    r = s.update(_trade(5 * _NS, "100.05", conditions=(14,)), st, {})
    assert r is not None and r.warm is True


def test_window_eviction_unwarms() -> None:
    """After eviction leaves < min prints, warm returns False."""
    s = SweepFlowImbalanceSensor(window_seconds=1, min_eligible_prints=2)
    st = s.initial_state()
    s.update(_trade(1 * _NS, "100.00", conditions=(14,)), st, {})
    r = s.update(_trade(1 * _NS + 500_000_000, "100.01", conditions=(14,)), st, {})
    assert r is not None and r.warm is True
    # Jump past the 1 s window — both prior prints evict; only the new one remains.
    r = s.update(_trade(3 * _NS, "100.02", conditions=(14,)), st, {})
    assert r is not None and r.warm is False
    assert len(st["window"]) == 1


def test_gap_flush_clears_window_and_rewarm() -> None:
    s = SweepFlowImbalanceSensor(window_seconds=900, min_eligible_prints=2, max_gap_seconds=60)
    st = s.initial_state()
    s.update(_trade(1 * _NS, "100.00", conditions=(14,)), st, {})
    r = s.update(_trade(2 * _NS, "100.01", conditions=(14,)), st, {})
    assert r is not None and r.warm is True
    assert len(st["window"]) == 2
    # 61 s gap → flush; current print starts a fresh (cold) window.
    r = s.update(_trade((2 + 61) * _NS, "100.02", conditions=(14,)), st, {})
    assert r is not None and r.warm is False
    assert len(st["window"]) == 1


def test_ineligible_prints_do_not_advance_gap_clock() -> None:
    """Gap is measured between successive *eligible* prints only."""
    s = SweepFlowImbalanceSensor(min_eligible_prints=1, max_gap_seconds=60)
    st = s.initial_state()
    s.update(_trade(1 * _NS, "100.00", conditions=(14,)), st, {})
    # 120 s of Class-B junk — must not flush.
    for i in range(5):
        assert (
            s.update(
                _trade((20 + i * 20) * _NS, "100.00", conditions=(8,)),
                st,
                {},
            )
            is None
        )
    r = s.update(_trade(50 * _NS, "100.01", conditions=(14,)), st, {})
    assert r is not None
    assert len(st["window"]) == 2  # no flush


# ── incremental vs recompute ──────────────────────────────────────────────


def test_incremental_matches_recompute_on_mixed_tape() -> None:
    s = SweepFlowImbalanceSensor(window_seconds=10, min_eligible_prints=1)
    st = s.initial_state()
    prices = [100.0, 100.01, 100.00, 99.99, 100.02, 100.02, 99.98]
    conds = [(14,), (14, 37), (14, 41), (8,), (14,), (12,), (14, 37, 41)]
    sizes = [50, 100, 200, 500, 75, 300, 125]
    for i, (px, cond, sz) in enumerate(zip(prices, conds, sizes)):
        ts = (i + 1) * _NS
        r = s.update(_trade(ts, f"{px:.2f}", sz, conditions=cond), st, {})
        if r is not None:
            assert r.value == pytest.approx(
                recompute_sfi_from_window(list(st["window"])), abs=1e-12
            )


# ── Hypothesis causality (truncation) ─────────────────────────────────────


_SLOT = st.tuples(
    st.sampled_from([-0.02, -0.01, 0.0, 0.01, 0.02]),
    st.integers(min_value=10, max_value=200),
    st.sampled_from(
        [
            (14,),
            (14, 37),
            (14, 41),
            (8,),  # excluded Class-B
            (12,),  # Form-T excluded
            (),  # empty excluded
        ]
    ),
    st.one_of(st.none(), st.sampled_from([1, 7, 8, 10, 11, 12])),
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(slots=st.lists(_SLOT, min_size=30, max_size=30))
def test_hypothesis_truncation_causality(
    slots: list[tuple[float, int, tuple[int, ...], int | None]],
) -> None:
    """Readings at ts ≤ T on the full tape match the truncated-tape run (Inv-6)."""
    s = SweepFlowImbalanceSensor(window_seconds=20, min_eligible_prints=3, max_gap_seconds=30)
    price = 100.0
    full: list[Trade] = []
    for i, (step, size, cond, corr) in enumerate(slots):
        price = max(0.01, price + step)
        full.append(
            _trade(
                (i + 1) * _NS,
                f"{price:.4f}",
                size,
                conditions=cond,
                correction=corr,
            )
        )
    t_cut = 15 * _NS
    truncated = [ev for ev in full if ev.timestamp_ns <= t_cut]

    def _emit(events: list[Trade]) -> dict[int, float]:
        st = s.initial_state()
        out: dict[int, float] = {}
        for ev in events:
            r = s.update(ev, st, {})
            if r is not None and ev.timestamp_ns <= t_cut:
                out[ev.timestamp_ns] = r.value
        return out

    assert _emit(truncated) == _emit(full)


def test_deterministic_replay() -> None:
    evs = [
        _trade(
            (i + 1) * _NS,
            f"{100.00 + ((i * 7) % 5 - 2) * 0.01:.2f}",
            100 + i,
            conditions=(14,) if i % 3 else (14, 37),
        )
        for i in range(40)
    ]
    a, _, _ = _drive(SweepFlowImbalanceSensor(min_eligible_prints=5), evs)
    b, _, _ = _drive(SweepFlowImbalanceSensor(min_eligible_prints=5), evs)
    assert a is not None and b is not None
    assert a.value == b.value and a.warm == b.warm


def test_sensor_id_version_overrides_and_is_eligible() -> None:
    s = SweepFlowImbalanceSensor(
        sensor_id="sfi_test",
        sensor_version="9.9.9",
        min_eligible_prints=1,
    )
    assert s.sensor_id == "sfi_test"
    assert s.sensor_version == "9.9.9"
    assert s.iso_id == 14
    assert s.class_a_core_ids == frozenset({14, 37})
    assert s.overlay_ids == frozenset({41})
    ok = _trade(1 * _NS, "100.00", conditions=(14,))
    bad = _trade(2 * _NS, "100.00", conditions=(8,))
    assert s.is_eligible(ok) is True
    assert s.is_eligible(bad) is False
    assert s.is_eligible(_trade(3 * _NS, "100.00", conditions=(14,), correction=10)) is False


def test_recompute_edge_cases() -> None:
    assert recompute_sfi_from_window([]) == 0.0
    assert recompute_sfi_from_window([(0, 0, 0)]) == 0.0
