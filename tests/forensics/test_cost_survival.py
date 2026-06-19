"""Unit tests for the per-alpha cost-survival report (close-the-loop)."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import Side
from feelies.forensics.cost_survival import (
    format_cost_survival_report,
    per_alpha_cost_survival,
)
from feelies.storage.trade_journal import TradeRecord

_SEQ = 0


def _tr(
    strategy_id: str,
    realized_pnl: float,
    fees: float,
    *,
    cost_bps: float = 2.0,
    qty: int = 50,
    price: float = 100.0,
) -> TradeRecord:
    global _SEQ
    _SEQ += 1
    return TradeRecord(
        order_id=f"o{_SEQ}",
        symbol="APP",
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=qty,
        filled_quantity=qty,
        fill_price=Decimal(str(price)),
        signal_timestamp_ns=_SEQ * 1000,
        submit_timestamp_ns=_SEQ * 1000 + 1,
        fill_timestamp_ns=_SEQ * 1000 + 2,
        cost_bps=Decimal(str(cost_bps)),
        fees=Decimal(str(fees)),
        realized_pnl=Decimal(str(realized_pnl)),
        correlation_id=f"c{_SEQ}",
    )


def _app_2026_03_26_fills() -> list[TradeRecord]:
    """Reproduce the shape of the APP 2026-03-26 multialpha attribution.

    inventory: 3 fills, realized $148.00, fees $12.92, net +$135.08
    benign:    9 fills, realized  $39.50, fees $56.51, net  -$17.01
    kyle:      6 fills, realized   $0.00, fees $34.79, net  -$34.79
    """
    fills: list[TradeRecord] = []
    # inventory — 3 fills
    for pnl, fee in [(60.0, 4.31), (50.0, 4.31), (38.0, 4.30)]:
        fills.append(_tr("sig_inventory_revert_v1", pnl, fee))
    # benign — 9 fills summing to 39.50 / 56.51
    for i in range(9):
        fills.append(_tr("sig_benign_midcap_v1", 39.50 / 9, 56.51 / 9))
    # kyle — 6 fills, zero realized, fee bleed
    for i in range(6):
        fills.append(_tr("sig_kyle_drift_v1", 0.0, 34.79 / 6))
    return fills


def test_reproduces_app_table_and_verdicts() -> None:
    rows = per_alpha_cost_survival(_app_2026_03_26_fills())
    by_id = {r.strategy_id: r for r in rows}

    inv = by_id["sig_inventory_revert_v1"]
    assert inv.n_fills == 3
    assert inv.net == 148.0 - 12.92
    # 3 fills is below the min-fills floor -> not trusted despite +net.
    assert inv.verdict == "LOW_N"

    benign = by_id["sig_benign_midcap_v1"]
    assert benign.n_fills == 9
    assert round(benign.net, 2) == -17.01
    assert benign.verdict == "BLEED"

    kyle = by_id["sig_kyle_drift_v1"]
    assert kyle.n_fills == 6
    assert round(kyle.net, 2) == -34.79
    assert kyle.mean_edge_bps == 0.0
    assert kyle.verdict == "BLEED"


def test_rows_sorted_by_net_desc() -> None:
    rows = per_alpha_cost_survival(_app_2026_03_26_fills())
    nets = [r.net for r in rows]
    assert nets == sorted(nets, reverse=True)
    assert rows[0].strategy_id == "sig_inventory_revert_v1"


def test_survives_when_edge_clears_margin_with_enough_fills() -> None:
    # 25 fills, edge ~10 bps vs cost 2 bps (margin 5x), net positive.
    fills = [_tr("alpha_good", 5.0, 0.5, cost_bps=2.0) for _ in range(25)]
    rows = per_alpha_cost_survival(fills)
    assert rows[0].verdict == "SURVIVES"
    assert rows[0].realized_margin_ratio >= 1.5


def test_marginal_when_profitable_but_below_bar() -> None:
    # 25 fills, edge ~2.5 bps vs cost 2 bps (margin 1.25x < 1.5), net > 0.
    fills = [_tr("alpha_thin", 1.25, 0.1, cost_bps=2.0) for _ in range(25)]
    rows = per_alpha_cost_survival(fills)
    assert rows[0].verdict == "MARGINAL"


def test_low_n_overrides_even_when_edge_is_strong() -> None:
    fills = [_tr("alpha_lucky", 50.0, 0.1, cost_bps=2.0) for _ in range(5)]
    rows = per_alpha_cost_survival(fills)
    assert rows[0].verdict == "LOW_N"


def test_report_renders_with_verdicts_and_fleet_line() -> None:
    rows = per_alpha_cost_survival(_app_2026_03_26_fills())
    report = format_cost_survival_report(rows)
    assert "Per-Alpha Cost Survival" in report
    assert "FLEET" in report
    assert "BLEED" in report
    assert "LOW_N" in report
    # fleet net = 135.08 - 17.01 - 34.79 = 83.28
    assert "+83.28" in report
