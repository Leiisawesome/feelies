"""Tests for MultiHorizonAttributor — conservation + causal bucketing.

Closes audit P0-5: the attributor (the Inv-1 attribution vehicle) previously
had no test coverage.  These tests pin:

* conservation on every axis (Σ buckets [+ unattributed] == total realized PnL),
* per-trade mechanism provenance (Inv-1) preferred over the gross-share
  snapshot fallback — no KYLE→INVENTORY mis-bucketing, no smearing,
* causal regime bucketing from the recorded ``TradeRecord.regime_state``
  (deterministic — two audits over the same journal agree),
* the gross-share snapshot fallback for cross-sectional fills, and
* the ``unattributed`` residual that keeps the mechanism axis conserving
  (audit P1-12).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

import pytest

from feelies.core.events import Side, TrendMechanism
from feelies.forensics.multi_horizon_attribution import MultiHorizonAttributor
from feelies.portfolio.cross_sectional_tracker import CrossSectionalSnapshot
from feelies.storage.trade_journal import TradeRecord


def _rec(
    *,
    strategy_id: str = "s",
    symbol: str = "AAPL",
    qty: int = 100,
    price: str = "100.00",
    pnl: str = "0.00",
    fees: str = "0.00",
    mechanism: TrendMechanism | None = None,
    half_life: int = 0,
    regime: str = "",
    idx: int = 0,
) -> TradeRecord:
    return TradeRecord(
        order_id=f"o{idx}",
        symbol=symbol,
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=qty,
        filled_quantity=qty,
        fill_price=Decimal(price),
        signal_timestamp_ns=idx,
        submit_timestamp_ns=idx,
        fill_timestamp_ns=idx,
        cost_bps=Decimal("0"),
        fees=Decimal(fees),
        realized_pnl=Decimal(pnl),
        correlation_id=f"c{idx}",
        trend_mechanism=mechanism,
        expected_half_life_seconds=half_life,
        regime_state=regime,
    )


def _snap(strategy_id: str, breakdown: dict[TrendMechanism, float]) -> CrossSectionalSnapshot:
    return CrossSectionalSnapshot(
        strategy_id=strategy_id,
        horizon_seconds=300,
        timestamp_ns=0,
        boundary_index=1,
        gross_usd=0.0,
        net_usd=0.0,
        expected_turnover_usd=0.0,
        mechanism_breakdown=dict(breakdown),
    )


def _total(trades: Iterable[TradeRecord]) -> float:
    return sum(float(t.realized_pnl) for t in trades)


def test_horizon_axis_conserves() -> None:
    trades = [
        _rec(strategy_id="a", pnl="10.00", idx=0),
        _rec(strategy_id="a", pnl="-4.00", idx=1),
        _rec(strategy_id="b", pnl="7.00", idx=2),
    ]
    rep = MultiHorizonAttributor(horizon_by_strategy={"a": 300, "b": 120}).attribute(trades)
    assert sum(b.realized_pnl for b in rep.horizon.values()) == pytest.approx(_total(trades))
    assert rep.horizon[("a", 300)].realized_pnl == pytest.approx(6.0)
    assert rep.horizon[("b", 120)].realized_pnl == pytest.approx(7.0)


def test_per_trade_mechanism_conserves_and_is_not_smeared() -> None:
    # KYLE_INFO PnL must land in KYLE_INFO, INVENTORY in INVENTORY.
    trades = [
        _rec(strategy_id="a", pnl="10.00", mechanism=TrendMechanism.KYLE_INFO, idx=0),
        _rec(strategy_id="a", pnl="2.00", mechanism=TrendMechanism.INVENTORY, idx=1),
    ]
    rep = MultiHorizonAttributor(horizon_by_strategy={"a": 300}).attribute(trades)
    assert rep.mechanism[("a", TrendMechanism.KYLE_INFO)].realized_pnl_share == pytest.approx(10.0)
    assert rep.mechanism[("a", TrendMechanism.INVENTORY)].realized_pnl_share == pytest.approx(2.0)
    mech_sum = sum(b.realized_pnl_share for b in rep.mechanism.values())
    assert mech_sum + sum(rep.unattributed.values()) == pytest.approx(_total(trades))
    assert "a" not in rep.unattributed


def test_per_trade_mechanism_beats_stale_snapshot() -> None:
    # Trades carry KYLE_INFO; the (stale) snapshot says INVENTORY. Provenance wins.
    trades = [_rec(strategy_id="a", pnl="5.00", mechanism=TrendMechanism.KYLE_INFO, idx=0)]
    rep = MultiHorizonAttributor(
        horizon_by_strategy={"a": 300},
        intent_snapshots={"a": _snap("a", {TrendMechanism.INVENTORY: 1.0})},
    ).attribute(trades)
    assert ("a", TrendMechanism.KYLE_INFO) in rep.mechanism
    assert ("a", TrendMechanism.INVENTORY) not in rep.mechanism


def test_unattributed_residual_for_mixed_provenance() -> None:
    trades = [
        _rec(strategy_id="a", pnl="6.00", mechanism=TrendMechanism.KYLE_INFO, idx=0),
        _rec(strategy_id="a", pnl="4.00", mechanism=None, idx=1),
    ]
    rep = MultiHorizonAttributor(horizon_by_strategy={"a": 300}).attribute(trades)
    assert rep.mechanism[("a", TrendMechanism.KYLE_INFO)].realized_pnl_share == pytest.approx(6.0)
    assert rep.unattributed["a"] == pytest.approx(4.0)
    total_attr = sum(b.realized_pnl_share for b in rep.mechanism.values()) + sum(
        rep.unattributed.values()
    )
    assert total_attr == pytest.approx(_total(trades))


def test_no_provenance_no_snapshot_is_unattributed_not_dropped() -> None:
    # Audit P1-12: strategy PnL must not silently vanish from the mechanism axis.
    trades = [_rec(strategy_id="a", pnl="9.00", idx=0)]
    rep = MultiHorizonAttributor(horizon_by_strategy={"a": 300}).attribute(trades)
    assert rep.mechanism == {}
    assert rep.unattributed["a"] == pytest.approx(9.0)


def test_snapshot_fallback_conserves() -> None:
    # Cross-sectional strat: no per-trade mechanism, snapshot splits 60/40.
    trades = [_rec(strategy_id="p", pnl="10.00", idx=0)]
    rep = MultiHorizonAttributor(
        horizon_by_strategy={"p": 300},
        intent_snapshots={
            "p": _snap("p", {TrendMechanism.KYLE_INFO: 0.6, TrendMechanism.INVENTORY: 0.4})
        },
    ).attribute(trades)
    assert rep.mechanism[("p", TrendMechanism.KYLE_INFO)].realized_pnl_share == pytest.approx(6.0)
    assert rep.mechanism[("p", TrendMechanism.INVENTORY)].realized_pnl_share == pytest.approx(4.0)
    assert "p" not in rep.unattributed
    assert sum(b.realized_pnl_share for b in rep.mechanism.values()) == pytest.approx(10.0)


def test_regime_bucketing_is_causal_and_deterministic() -> None:
    # Each trade records the regime in effect at entry; bucketing uses that,
    # not a single global "current" regime — and two audits must agree.
    trades = [
        _rec(strategy_id="a", pnl="3.00", regime="normal", idx=0),
        _rec(strategy_id="a", pnl="5.00", regime="vol_breakout", idx=1),
        _rec(strategy_id="a", pnl="-1.00", regime="normal", idx=2),
    ]
    attr = MultiHorizonAttributor(horizon_by_strategy={"a": 300})
    rep1 = attr.attribute(trades)
    rep2 = attr.attribute(trades)
    assert rep1.regime[("a", "normal")].realized_pnl == pytest.approx(2.0)
    assert rep1.regime[("a", "normal")].trade_count == 2
    assert rep1.regime[("a", "vol_breakout")].realized_pnl == pytest.approx(5.0)
    assert {k: v.realized_pnl for k, v in rep1.regime.items()} == {
        k: v.realized_pnl for k, v in rep2.regime.items()
    }
    assert sum(b.realized_pnl for b in rep1.regime.values()) == pytest.approx(_total(trades))


def test_empty_regime_label_is_skipped() -> None:
    trades = [_rec(strategy_id="a", pnl="3.00", regime="", idx=0)]
    rep = MultiHorizonAttributor(horizon_by_strategy={"a": 300}).attribute(trades)
    assert rep.regime == {}
