#!/usr/bin/env python3
"""Close-the-loop demonstration (why a single day shows no change, and what
the loop does once a real fill window has accumulated).

Reconstructs the APP 2026-03-26 per-alpha attribution, scales it to a
rolling multi-session window (so each alpha clears the 30-fill evidence
bar), runs the REAL ``reconcile_session`` to build the edge-realization
factors, then runs the REAL B4 edge-vs-cost gate (``entry_edge_clears_cost``)
with and without those factors to show the bleeders get gated out.

    python scripts/research/close_the_loop_demo.py
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import Side
from feelies.execution.position_manager import entry_edge_clears_cost
from feelies.forensics.session_reconcile import reconcile_session
from feelies.storage.trade_journal import TradeRecord

# Reported APP 2026-03-26 per-alpha attribution: per-day fill count, the
# realized ``edge_bps`` from the cost-survival report, and each alpha's
# disclosed ``cost_arithmetic.edge_estimate_bps``.
#   (per-day fills, reported realized edge_bps, disclosed edge_bps)
_PER_DAY = {
    "sig_inventory_revert_v1": dict(n=3, edge_bps=24.95, disclosed=8.8),
    "sig_benign_midcap_v1": dict(n=9, edge_bps=2.15, disclosed=9.0),
    "sig_kyle_drift_v1": dict(n=6, edge_bps=0.0, disclosed=11.7),
}
_QTY = 50
_PRICE = 100.0
_NOTIONAL = _PRICE * _QTY
_RT_COST_BPS = 11.0  # representative modeled round-trip cost
_MIN_RATIO = 1.5  # backtest_multialpha signal_min_edge_cost_ratio


def _records(sessions: int) -> list[TradeRecord]:
    out: list[TradeRecord] = []
    seq = 0
    for _ in range(sessions):
        for sid, p in _PER_DAY.items():
            # realized_pnl chosen so edge_bps = pnl/notional*1e4 matches the
            # report exactly.
            pnl = float(p["edge_bps"]) / 1e4 * _NOTIONAL
            for _ in range(int(p["n"])):
                seq += 1
                out.append(
                    TradeRecord(
                        order_id=f"o{seq}",
                        symbol="APP",
                        strategy_id=sid,
                        side=Side.BUY,
                        requested_quantity=_QTY,
                        filled_quantity=_QTY,
                        fill_price=Decimal(str(_PRICE)),
                        signal_timestamp_ns=seq * 1000,
                        submit_timestamp_ns=seq * 1000 + 1,
                        fill_timestamp_ns=seq * 1000 + 2,
                        cost_bps=Decimal("2"),
                        fees=Decimal("0.1"),
                        realized_pnl=Decimal(str(pnl)),
                        correlation_id=f"c{seq}",
                    )
                )
    return out


def _passes(edge_bps: float, factor: float) -> bool:
    return entry_edge_clears_cost(
        edge_bps=edge_bps * factor,
        rt_cost_bps=_RT_COST_BPS,
        min_ratio=_MIN_RATIO,
        basis="round_trip",
    )


def _run(sessions: int) -> None:
    disclosed = {sid: float(p["disclosed"]) for sid, p in _PER_DAY.items()}
    result = reconcile_session(_records(sessions), disclosed_edges=disclosed)
    cals = result.calibrations
    fills_each = {sid: int(p["n"]) * sessions for sid, p in _PER_DAY.items()}

    print(f"\n=== rolling window = {sessions} session(s) ===")
    print(f"  {'alpha':<26s}{'fills':>6s}{'realized_edge':>14s}{'disclosed':>10s}"
          f"{'lcb_factor':>11s}   gate w/o -> w/ calibration")
    for sid, p in _PER_DAY.items():
        cal = cals[sid]
        disc = float(p["disclosed"])
        before = _passes(disc, 1.0)
        after = _passes(disc, cal.lcb_factor)
        flip = "TRADES -> SUPPRESSED" if (before and not after) else (
            "trades" if after else "suppressed"
        )
        print(
            f"  {sid:<26s}{fills_each[sid]:>6d}{cal.realized_edge_bps_mean:>13.2f}b"
            f"{disc:>10.2f}{cal.lcb_factor:>11.3f}   "
            f"{'PASS' if before else 'fail'} -> {'PASS' if after else 'FAIL'}   {flip}"
        )


def main() -> int:
    print(__doc__)
    print("Disclosed edge is shrunk by the realized lower-bound factor before the "
          "B4 gate.\nFactor stays 1.0 until an alpha clears the 30-fill evidence bar "
          "(min_fills).")
    _run(sessions=1)   # like the user's single day: every alpha < 30 fills -> factor 1.0
    _run(sessions=6)   # a real rolling window: kyle/benign now clear 30 fills -> haircut
    print(
        "\nReading: at 1 session every factor is 1.0 (insufficient evidence) so the "
        "gate is unchanged — exactly the 'no improvement' you saw. At 6 sessions the "
        "bleeders clear the evidence bar, their realized edge shrinks the gate input, "
        "and kyle/benign flip from PASS to FAIL (gated out) while their fee bleed stops."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
