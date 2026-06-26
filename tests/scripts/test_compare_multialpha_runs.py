"""Unit tests for compare_multialpha_runs.py (pure helpers; no disk cache)."""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "compare_multialpha_runs.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("compare_multialpha_runs", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["compare_multialpha_runs"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_compare_fill_legs_detects_price_and_strategy_drift() -> None:
    mod = _load_mod()
    benign = [
        mod.FillLeg(
            index=0,
            side="SELL",
            qty=50,
            price=Decimal("397.38"),
            strategy_id="sig_benign_midcap_v1",
            trading_intent="ENTRY_SHORT",
            realized_pnl=Decimal("0"),
            fees=Decimal("1"),
            fill_timestamp_ns=100,
        ),
        mod.FillLeg(
            index=1,
            side="BUY",
            qty=50,
            price=Decimal("396.93"),
            strategy_id="sig_benign_midcap_v1",
            trading_intent="EXIT",
            realized_pnl=Decimal("22.50"),
            fees=Decimal("1"),
            fill_timestamp_ns=200,
        ),
    ]
    multi = [
        mod.FillLeg(
            index=0,
            side="SELL",
            qty=50,
            price=Decimal("397.38"),
            strategy_id="sig_benign_midcap_v1",
            trading_intent="ENTRY_SHORT",
            realized_pnl=Decimal("0"),
            fees=Decimal("1"),
            fill_timestamp_ns=100,
        ),
        mod.FillLeg(
            index=1,
            side="BUY",
            qty=50,
            price=Decimal("396.00"),
            strategy_id="sig_inventory_revert_v1",
            trading_intent="EXIT",
            realized_pnl=Decimal("69.00"),
            fees=Decimal("1"),
            fill_timestamp_ns=150,
        ),
    ]
    diffs = mod.compare_fill_legs(benign, multi)
    assert len(diffs) == 1
    assert diffs[0].index == 1
    assert diffs[0].multi_strategy_id == "sig_inventory_revert_v1"
    assert diffs[0].short_pnl_impact == pytest.approx(46.50)


def test_detect_exit_hijacks_flags_inventory_exit() -> None:
    mod = _load_mod()
    multi = [
        mod.FillLeg(
            index=1,
            side="BUY",
            qty=50,
            price=Decimal("396.00"),
            strategy_id="sig_inventory_revert_v1",
            trading_intent="EXIT",
            realized_pnl=Decimal("69.00"),
            fees=Decimal("5"),
            fill_timestamp_ns=150,
        ),
    ]
    flags = mod.detect_exit_hijacks(
        multi,
        entry_alpha="sig_benign_midcap_v1",
        hijack_alpha="sig_inventory_revert_v1",
    )
    assert len(flags) == 1
    assert flags[0].fill_index == 1


def test_fill_count_mismatch_surfaces() -> None:
    mod = _load_mod()
    diffs = mod.compare_fill_legs(
        [],
        [
            mod.FillLeg(
                index=0,
                side="SELL",
                qty=1,
                price=Decimal("1"),
                strategy_id="a",
                trading_intent="ENTRY_SHORT",
                realized_pnl=Decimal("0"),
                fees=Decimal("0"),
                fill_timestamp_ns=None,
            )
        ],
    )
    assert any(d.multi_trading_intent == "FILL_COUNT_MISMATCH" for d in diffs)


def test_collision_kind_key_and_summary() -> None:
    mod = _load_mod()
    rows = (
        mod.ArbitrationCollisionRow(
            candidate_count=2,
            strategy_ids=("a", "b"),
            kinds=(
                ("a", "FLAT", "OFF"),
                ("b", "FLAT", "OFF"),
            ),
            harmless=True,
            kind_key=mod.collision_kind_key(
                (("a", "FLAT", "OFF"), ("b", "FLAT", "OFF")),
            ),
        ),
        mod.ArbitrationCollisionRow(
            candidate_count=2,
            strategy_ids=("a", "c"),
            kinds=(
                ("a", "SHORT", "ON"),
                ("c", "LONG", "ON"),
            ),
            harmless=False,
            kind_key=mod.collision_kind_key(
                (("a", "SHORT", "ON"), ("c", "LONG", "ON")),
            ),
        ),
    )
    assert rows[0].kind_key == "FLAT/OFF+FLAT/OFF"
    summary = mod.summarize_arbitration_collisions(rows)
    assert summary.post_filter_collision_ticks == 2
    assert summary.harmless_flat_gate_close_ticks == 1
    assert summary.actionable_collision_ticks == 1
    assert summary.kind_breakdown["FLAT/OFF+FLAT/OFF"] == 1
    assert summary.kind_breakdown["SHORT/ON+LONG/ON"] == 1
