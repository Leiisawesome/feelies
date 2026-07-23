"""Unit tests for T2-C pure arithmetic (no network)."""

from __future__ import annotations

import math

from scripts.research.tranche2_frontier_characterization import (
    GO_KAPPA,
    cost_block,
    dollar_adv_median,
    materialize,
    name_opens_go,
    rv20_from_closes,
    sigma_h_from_mids,
)


def test_go_kappa_is_central_with_25pct_margin() -> None:
    assert abs(GO_KAPPA - 0.12) < 1e-12


def test_cost_block_min_commission_trap_at_low_price() -> None:
    # $10 × 80 = $800 notional → fee 0.35/800 × 1e4 = 4.375 bps > 2.0
    c = cost_block(10.0, 0.02)
    assert c["min_commission_trap"] is True
    assert c["fee_passive_bps"] > 2.0
    # floor = 2.25 × C_ow on unrounded inputs; tolerate display rounding
    assert abs(c["floor_passive_bps"] - 2.25 * c["c_ow_passive_bps"]) < 5e-4


def test_cost_block_no_trap_at_mid_price() -> None:
    c = cost_block(80.0, 0.10)
    assert c["min_commission_trap"] is False
    assert c["fee_passive_bps"] < 2.0


def test_rv20_and_adv() -> None:
    # Constant path → rv20 = 0; need 21 closes
    closes = [100.0 + 0.01 * i for i in range(21)]
    vols = [1_000_000.0] * 21
    rv = rv20_from_closes(closes)
    assert rv is not None and rv > 0.0
    adv = dollar_adv_median(closes, vols)
    assert adv is not None
    assert math.isclose(adv, statistics_median_dv(closes, vols), rel_tol=0, abs_tol=1e-6)


def statistics_median_dv(closes: list[float], volumes: list[float]) -> float:
    import statistics

    return float(statistics.median([closes[i] * volumes[i] for i in range(-20, 0)]))


def test_name_opens_go_bar() -> None:
    assert name_opens_go({"30": 0.11, "120": 0.20, "300": 0.05}) is True
    assert name_opens_go({"30": 0.13, "120": 0.13, "300": 0.05}) is False
    assert name_opens_go({"30": None, "120": 0.12, "300": 0.05}) is True


def test_sigma_h_from_mids_constant_is_none_or_zeroish() -> None:
    # Two mids far apart, constant price → zero returns → stdev undefined (<2 rets
    # on a degenerate grid may yield None); non-decreasing timestamps required.
    open_ns = 1_700_000_000_000_000_000  # arbitrary
    # Build a dense constant mid series across one hour of synthetic stamps.
    mid_ts = [open_ns + i * 1_000_000_000 for i in range(100)]
    mids = [50.0] * 100
    s, n = sigma_h_from_mids(mid_ts, mids, 30, open_ns)
    assert n >= 2
    assert s is not None
    assert s == 0.0


def test_materialize_go_no_go() -> None:
    # One name with high synthetic sigma → low kappa → opens; need 5 for GO.
    # Build raw samples with large mid moves so sigma is large.
    def _busy_session(seed: float) -> dict:
        # 09:30 ET on 2026-01-15 ≈ use rth_open via first ts in RTH.
        from datetime import datetime
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        open_et = datetime(2026, 1, 15, 9, 30, tzinfo=et)
        open_ns = int(open_et.timestamp() * 1e9)
        mid_ts = []
        mids = []
        bids = []
        spreads = []
        px = 50.0
        for i in range(0, 390):  # ~ every minute
            ts = open_ns + i * 60 * 1_000_000_000
            px = 50.0 + seed * math.sin(i / 3.0)
            mid_ts.append(ts)
            mids.append(px)
            bids.append(px - 0.01)
            spreads.append(0.02)
        return {
            "date": "2026-01-15",
            "n_seen": len(mids),
            "n_kept": len(mids),
            "n_buckets_hit": 78,
            "mid_ts_ns": mid_ts,
            "mids": mids,
            "bids": bids,
            "spreads": spreads,
        }

    names = [f"T{i:02d}" for i in range(5)]
    candidates = [
        {
            "ticker": n,
            "close_asof": 50.0,
            "shares": 1e8,
            "shares_source": "weighted_shares_outstanding",
            "market_cap_usd": 5e9,
            "adv20_median_usd": 20e6,
            "rv20_pct": 80.0 - i,
            "primary_exchange": "XNAS",
            "n_daily_bars": 25,
        }
        for i, n in enumerate(names)
    ]
    samples = {
        n: {
            "2025-11-25": _busy_session(2.0),
            "2026-01-15": _busy_session(2.0),
            "2026-04-10": _busy_session(2.0),
        }
        for n in names
    }
    out = materialize({"candidates": candidates, "samples": samples, "screen_summary": {}})
    assert out["n_go_names"] >= 5
    assert out["verdict"] == "GO"
