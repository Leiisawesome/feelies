#!/usr/bin/env python3
"""Task T2-C — tranche-2 frontier characterization (census-legal).

Daily-bar midcap screen + capped RTH quote samples + floor/κ_req map.
NO forward returns, NO IC, NO signal evaluation, NO DiskEventCache grid
ingest, NO /v2 last-NBBO. Trial ledger N unchanged.

Frozen criteria live in
``docs/research/prompt_pack_13_tranche2_characterization.md`` §1 —
this script implements them; do not change constants without amending
that section first.

Usage
-----
    # Network pull + artifact write (PYTHONHASHSEED=0 required):
    PYTHONHASHSEED=0 uv run python \\
        scripts/research/tranche2_frontier_characterization.py \\
        --json docs/research/artifacts/tranche2_frontier_characterization_2026-07-18.json

    # Bit-identical rematerialization from a prior artifact (no network):
    PYTHONHASHSEED=0 uv run python \\
        scripts/research/tranche2_frontier_characterization.py \\
        --replay-artifact docs/research/artifacts/tranche2_frontier_characterization_2026-07-18.json \\
        --json /tmp/t2c_replay.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.cli.env import load_dotenv_optional, massive_api_key_from_env  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_RTH_SECONDS = 6 * 3600 + 30 * 60

# ── Frozen constants (§1) ────────────────────────────────────────────────

ASOF_DATE = "2026-04-24"
SAMPLE_DATES = ("2025-11-25", "2026-01-15", "2026-04-10")
PRIMARY_EXCHANGES = frozenset({"XNYS", "XNAS"})
CLOSED_GRID = frozenset({"APP", "RMBS", "OLN", "ENSG", "DIOD", "PCTY", "MLI", "CROX"})
MARKET_CAP_LO = 2.0e9
MARKET_CAP_HI = 12.0e9
PRICE_MIN = 10.0
ADV_MIN_USD = 15_000_000.0
TOP_N = 15
RV20_WINDOW = 20
HORIZONS = (30, 120, 300)

BUCKET_SECONDS = 5 * 60
QUOTES_PER_BUCKET = 40
MAX_QUOTES_PER_SESSION = 78 * QUOTES_PER_BUCKET  # 3120

FILL_SHARES = 80
COMMISSION = max(0.0035 * FILL_SHARES, 0.35)
TAKER_EXCHANGE = 0.003 * FILL_SHARES
PASSIVE_ADVERSE_BPS = 2.0
IMPACT_THIN_BPS = 1.0
IMPACT_WIDE_BPS = 2.0
STRESS = 1.5
INV12_MARGIN = 1.5
KAPPA_CEILING = 0.30
KAPPA_CENTRAL = 0.16
GO_MARGIN = 0.25
GO_KAPPA = KAPPA_CENTRAL * (1.0 - GO_MARGIN)  # 0.12
GO_MIN_NAMES = 5
CENTRAL_KAPPA_RANGE = (0.146, 0.190)


def _r4(x: float) -> float:
    return round(float(x), 4)


def _r6(x: float) -> float:
    return round(float(x), 6)


def cost_block(median_bid: float, median_spread: float) -> dict[str, Any]:
    notional = FILL_SHARES * median_bid
    fee_passive_bps = COMMISSION / notional * 1e4
    fee_taker_bps = (COMMISSION + TAKER_EXCHANGE) / notional * 1e4
    half_spread_bps = (median_spread / 2.0) / median_bid * 1e4
    impact_bps = IMPACT_THIN_BPS if half_spread_bps < 8.0 else IMPACT_WIDE_BPS
    c_ow_p = PASSIVE_ADVERSE_BPS + fee_passive_bps
    c_ow_t = half_spread_bps + impact_bps + fee_taker_bps
    return {
        "median_bid": _r4(median_bid),
        "median_spread": _r4(median_spread),
        "half_spread_bps": _r4(half_spread_bps),
        "impact_bps": impact_bps,
        "fee_passive_bps": _r4(fee_passive_bps),
        "fee_taker_bps": _r4(fee_taker_bps),
        "c_ow_passive_bps": _r4(c_ow_p),
        "c_ow_taker_bps": _r4(c_ow_t),
        "floor_passive_bps": _r4(INV12_MARGIN * STRESS * c_ow_p),
        "floor_taker_bps": _r4(INV12_MARGIN * STRESS * c_ow_t),
        "min_commission_trap": fee_passive_bps > PASSIVE_ADVERSE_BPS,
    }


def rv20_from_closes(closes: Sequence[float]) -> float | None:
    """Annualized % rv20 from adjusted closes; need RV20_WINDOW+1 closes."""
    if len(closes) < RV20_WINDOW + 1:
        return None
    window = closes[-(RV20_WINDOW + 1) :]
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    if len(rets) < 2 or any(not math.isfinite(r) for r in rets):
        return None
    return _r4(math.sqrt(252.0) * statistics.stdev(rets) * 100.0)


def dollar_adv_median(closes: Sequence[float], volumes: Sequence[float]) -> float | None:
    if len(closes) < RV20_WINDOW or len(closes) != len(volumes):
        return None
    dv = [closes[i] * volumes[i] for i in range(-RV20_WINDOW, 0)]
    return float(statistics.median(dv))


def _in_rth_ns(ts_ns: int) -> bool:
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


def _bucket_index(ts_ns: int, session_open_ns: int) -> int | None:
    if ts_ns < session_open_ns:
        return None
    off = (ts_ns - session_open_ns) // _NS
    if off >= _RTH_SECONDS:
        return None
    return int(off // BUCKET_SECONDS)


def sigma_h_from_mids(
    mid_ts: Sequence[int], mids: Sequence[float], horizon_s: int, session_open: int
) -> tuple[float | None, int]:
    if len(mids) < 2:
        return None, 0
    grid_mids: list[float | None] = []
    for k in range(0, _RTH_SECONDS // horizon_s + 1):
        t = session_open + k * horizon_s * _NS
        i = bisect_right(mid_ts, t) - 1
        grid_mids.append(mids[i] if i >= 0 else None)
    rets = [
        math.log(b / a)
        for a, b in zip(grid_mids, grid_mids[1:])
        if a is not None and b is not None and a > 0 and b > 0
    ]
    if len(rets) < 2:
        return None, len(rets)
    return _r6(statistics.stdev(rets) * 1e4), len(rets)


def name_opens_go(kappa_passive_by_h: dict[str, float | None]) -> bool:
    for h in (30, 120):
        k = kappa_passive_by_h.get(str(h))
        if k is not None and k <= GO_KAPPA:
            return True
    return False


def materialize(raw: dict[str, Any]) -> dict[str, Any]:
    """Pure κ-map construction from cached screen + samples (deterministic)."""
    candidates = raw["candidates"]
    samples = raw["samples"]
    per_name: dict[str, Any] = {}
    go_names: list[str] = []

    for row in candidates:
        sym = row["ticker"]
        sess_bids: list[float] = []
        sess_spreads: list[float] = []
        sess_sigma: dict[str, list[float]] = {str(h): [] for h in HORIZONS}
        sess_detail: list[dict[str, Any]] = []

        for d in SAMPLE_DATES:
            cell = samples[sym][d]
            mid_ts = cell["mid_ts_ns"]
            mids = cell["mids"]
            bids = cell["bids"]
            spreads = cell["spreads"]
            if not mids:
                sess_detail.append({"date": d, "status": "EMPTY"})
                continue
            session_open = rth_open_ns(mid_ts[0])
            med_bid = statistics.median(bids)
            med_spread = statistics.median(spreads)
            sess_bids.append(med_bid)
            sess_spreads.append(med_spread)
            sigmas: dict[str, Any] = {}
            for h in HORIZONS:
                s, n = sigma_h_from_mids(mid_ts, mids, h, session_open)
                sigmas[str(h)] = {"sigma_bps": s, "n_returns": n}
                if s is not None:
                    sess_sigma[str(h)].append(s)
            last_et = datetime.fromtimestamp(mid_ts[-1] / 1e9, tz=_TZ_ET)
            sess_detail.append(
                {
                    "date": d,
                    "n_quotes": len(mids),
                    "median_bid": _r4(med_bid),
                    "median_spread": _r4(med_spread),
                    "coverage_end_et": last_et.strftime("%H:%M:%S"),
                    "sigma_bps": {h: sigmas[h]["sigma_bps"] for h in sigmas},
                    "n_returns": {h: sigmas[h]["n_returns"] for h in sigmas},
                }
            )

        if not sess_bids:
            per_name[sym] = {
                "screen": row,
                "status": "NO_SAMPLES",
                "sessions": sess_detail,
            }
            continue

        costs = cost_block(statistics.median(sess_bids), statistics.median(sess_spreads))
        horizons_out: dict[str, Any] = {}
        kappa_p: dict[str, float | None] = {}
        for h in HORIZONS:
            vals = sess_sigma[str(h)]
            sig_med = _r4(statistics.median(vals)) if vals else None
            entry: dict[str, Any] = {
                "n_sessions_with_sigma": len(vals),
                "sigma_median_bps": sig_med,
            }
            for variant in ("passive", "taker"):
                floor = costs[f"floor_{variant}_bps"]
                if sig_med is None or sig_med <= 0:
                    k = None
                else:
                    k = _r4(floor / sig_med)
                entry[f"kappa_req_{variant}"] = k
                entry[f"feasible_{variant}_ceiling_0_30"] = (
                    k is not None and k <= KAPPA_CEILING
                )
                entry[f"open_central_0_16_{variant}"] = (
                    k is not None and k <= KAPPA_CENTRAL
                )
                if variant == "passive":
                    kappa_p[str(h)] = k
                    entry["open_go_bar_0_12"] = k is not None and k <= GO_KAPPA
            horizons_out[str(h)] = entry

        opens = name_opens_go(kappa_p)
        if opens:
            go_names.append(sym)
        per_name[sym] = {
            "screen": row,
            "status": "OK",
            "costs": costs,
            "sessions": sess_detail,
            "horizons": horizons_out,
            "opens_go_bar": opens,
        }

    go_names_sorted = sorted(go_names)
    verdict = "GO" if len(go_names_sorted) >= GO_MIN_NAMES else "NO-GO"
    return {
        "task": "T2-C",
        "asof_date": ASOF_DATE,
        "sample_dates": list(SAMPLE_DATES),
        "frozen": {
            "market_cap_band_usd": [MARKET_CAP_LO, MARKET_CAP_HI],
            "price_min": PRICE_MIN,
            "adv_min_usd": ADV_MIN_USD,
            "top_n": TOP_N,
            "go_kappa": GO_KAPPA,
            "go_min_names": GO_MIN_NAMES,
            "kappa_ceiling": KAPPA_CEILING,
            "kappa_central": KAPPA_CENTRAL,
            "central_kappa_range": list(CENTRAL_KAPPA_RANGE),
            "closed_grid_excluded": sorted(CLOSED_GRID),
            "primary_exchanges": sorted(PRIMARY_EXCHANGES),
            "quote_bucket_s": BUCKET_SECONDS,
            "quotes_per_bucket": QUOTES_PER_BUCKET,
            "max_quotes_per_session": MAX_QUOTES_PER_SESSION,
            "horizons_s": list(HORIZONS),
            "fill_shares": FILL_SHARES,
            "commission_usd": COMMISSION,
        },
        "screen_summary": raw.get("screen_summary", {}),
        "candidates": candidates,
        "per_name": per_name,
        "go_names": go_names_sorted,
        "n_go_names": len(go_names_sorted),
        "verdict": verdict,
        "multiple_testing_ledger": "N = 12, unchanged — characterization; no hypothesis",
        "legality": {
            "forward_returns": False,
            "ic": False,
            "disk_event_cache_ingest": False,
            "v2_last_nbbo": False,
            "grids_drawn": False,
        },
    }


# ── Network phase ────────────────────────────────────────────────────────


def _client() -> Any:
    load_dotenv_optional()
    key = massive_api_key_from_env()
    if not key:
        raise SystemExit("MASSIVE_API_KEY missing")
    from massive import RESTClient

    return RESTClient(key)


def _list_cs_primary(client: Any) -> list[str]:
    out: list[str] = []
    for t in client.list_tickers(market="stocks", type="CS", active=True, limit=1000):
        if getattr(t, "locale", None) != "us":
            continue
        if t.primary_exchange not in PRIMARY_EXCHANGES:
            continue
        if t.ticker in CLOSED_GRID:
            continue
        out.append(t.ticker)
    out.sort()
    return out


def _grouped_day(
    client: Any, day: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Return (close_by_ticker, dollar_volume_by_ticker) for grouped daily."""
    aggs = client.get_grouped_daily_aggs(day, adjusted=True, include_otc=False)
    closes: dict[str, float] = {}
    dvs: dict[str, float] = {}
    for a in aggs:
        t = getattr(a, "ticker", None)
        c = getattr(a, "close", None)
        v = getattr(a, "volume", None)
        if t and c is not None and c > 0:
            closes[str(t)] = float(c)
            if v is not None and float(v) > 0:
                dvs[str(t)] = float(c) * float(v)
    return closes, dvs


def _daily_bars(
    client: Any, ticker: str, start: str, end: str
) -> tuple[list[str], list[float], list[float]]:
    aggs = client.get_aggs(
        ticker, 1, "day", start, end, adjusted=True, sort="asc", limit=50000
    )
    dates: list[str] = []
    closes: list[float] = []
    volumes: list[float] = []
    for a in aggs:
        ts = getattr(a, "timestamp", None)
        c = getattr(a, "close", None)
        v = getattr(a, "volume", None)
        if ts is None or c is None or v is None or c <= 0:
            continue
        d = datetime.fromtimestamp(ts / 1000.0, tz=_TZ_ET).date().isoformat()
        dates.append(d)
        closes.append(float(c))
        volumes.append(float(v))
    return dates, closes, volumes


def _shares_outstanding(client: Any, ticker: str) -> tuple[float | None, str | None, str]:
    td = client.get_ticker_details(ticker)
    pe = getattr(td, "primary_exchange", None)
    w = getattr(td, "weighted_shares_outstanding", None)
    s = getattr(td, "share_class_shares_outstanding", None)
    if w is not None and float(w) > 0:
        return float(w), pe, "weighted_shares_outstanding"
    if s is not None and float(s) > 0:
        return float(s), pe, "share_class_shares_outstanding"
    return None, pe, "missing"


def _sip_ns(q: Any) -> int | None:
    for attr in ("sip_timestamp", "timestamp", "participant_timestamp"):
        v = getattr(q, attr, None)
        if v is None:
            continue
        v = int(v)
        # Massive REST quotes: sip_timestamp is ns; guard ms-scale.
        if v < 10**16:
            v *= 1_000_000
        return v
    return None


def _sample_session_quotes(client: Any, ticker: str, day: str) -> dict[str, Any]:
    """Time-stratified RTH quote sample → mid/bid/spread series."""
    day_dt = date.fromisoformat(day)
    # Inclusive UTC-ish bounds via date strings accepted by the client.
    start = f"{day}"
    # list_quotes timestamp filters: use ns bounds for RTH in ET.
    open_et = datetime(day_dt.year, day_dt.month, day_dt.day, 9, 30, tzinfo=_TZ_ET)
    close_et = datetime(day_dt.year, day_dt.month, day_dt.day, 16, 0, tzinfo=_TZ_ET)
    gte = int(open_et.timestamp() * 1e9)
    lt = int(close_et.timestamp() * 1e9)
    session_open = rth_open_ns(gte)

    bucket_counts: dict[int, int] = defaultdict(int)
    mid_ts: list[int] = []
    mids: list[float] = []
    bids: list[float] = []
    spreads: list[float] = []
    n_seen = 0
    n_kept = 0

    for q in client.list_quotes(
        ticker,
        timestamp_gte=gte,
        timestamp_lt=lt,
        order="asc",
        sort="timestamp",
        limit=50000,
    ):
        n_seen += 1
        ts = _sip_ns(q)
        if ts is None or not _in_rth_ns(ts):
            continue
        bid = getattr(q, "bid_price", None)
        ask = getattr(q, "ask_price", None)
        if bid is None or ask is None:
            continue
        b, a = float(bid), float(ask)
        if b <= 0.0 or a <= 0.0 or a < b:
            continue
        bi = _bucket_index(ts, session_open)
        if bi is None:
            continue
        if bucket_counts[bi] >= QUOTES_PER_BUCKET:
            continue
        if n_kept >= MAX_QUOTES_PER_SESSION:
            break
        bucket_counts[bi] += 1
        n_kept += 1
        mid_ts.append(ts)
        mids.append((b + a) / 2.0)
        bids.append(b)
        spreads.append(a - b)
        # Early exit if all buckets full.
        if len(bucket_counts) >= 78 and all(
            bucket_counts.get(i, 0) >= QUOTES_PER_BUCKET for i in range(78)
        ):
            break

    return {
        "date": day,
        "n_seen": n_seen,
        "n_kept": n_kept,
        "n_buckets_hit": len(bucket_counts),
        "mid_ts_ns": mid_ts,
        "mids": [_r6(x) for x in mids],
        "bids": [_r6(x) for x in bids],
        "spreads": [_r6(x) for x in spreads],
    }


def run_network() -> dict[str, Any]:
    client = _client()
    print("# listing CS primary XNYS/XNAS ...", file=sys.stderr, flush=True)
    tickers = _list_cs_primary(client)
    print(f"# {len(tickers)} tickers after exchange/grid filter", file=sys.stderr)

    print(f"# grouped daily {ASOF_DATE} ...", file=sys.stderr, flush=True)
    closes_asof, dv_asof = _grouped_day(client, ASOF_DATE)
    # Single-day DV prefilter (disclosed): shrinks details/bars calls only.
    # Binding ADV gate remains the trailing-20 median (U7).
    ASOF_DV_PREFILTER = 8_000_000.0
    price_pass = [
        t
        for t in tickers
        if t in closes_asof
        and closes_asof[t] > PRICE_MIN
        and dv_asof.get(t, 0.0) >= ASOF_DV_PREFILTER
    ]
    print(
        f"# {len(price_pass)} pass price > {PRICE_MIN} and asof DV "
        f">= {ASOF_DV_PREFILTER:.0f} (prefilter)",
        file=sys.stderr,
    )

    start = (date.fromisoformat(ASOF_DATE) - timedelta(days=45)).isoformat()
    survivors: list[dict[str, Any]] = []
    n_details = 0
    n_cap_fail = 0
    n_adv_fail = 0
    n_rv_fail = 0
    n_bars_fail = 0

    for i, t in enumerate(price_pass):
        if (i + 1) % 50 == 0 or i == 0:
            print(
                f"# details+bars {i + 1}/{len(price_pass)} (survivors={len(survivors)})",
                file=sys.stderr,
                flush=True,
            )
        try:
            shares, pe, shares_src = _shares_outstanding(client, t)
        except Exception as exc:  # noqa: BLE001 — vendor flakiness; skip ticker
            print(f"# skip {t} details: {exc}", file=sys.stderr)
            continue
        n_details += 1
        if pe not in PRIMARY_EXCHANGES:
            continue
        if shares is None:
            continue
        close = closes_asof[t]
        mcap = shares * close
        if not (MARKET_CAP_LO <= mcap <= MARKET_CAP_HI):
            n_cap_fail += 1
            continue
        try:
            dates, closes, volumes = _daily_bars(client, t, start, ASOF_DATE)
        except Exception as exc:  # noqa: BLE001
            print(f"# skip {t} bars: {exc}", file=sys.stderr)
            n_bars_fail += 1
            continue
        # Align to as-of: require last bar date == ASOF_DATE
        if not dates or dates[-1] != ASOF_DATE:
            n_bars_fail += 1
            continue
        adv = dollar_adv_median(closes, volumes)
        if adv is None or adv < ADV_MIN_USD:
            n_adv_fail += 1
            continue
        rv = rv20_from_closes(closes)
        if rv is None:
            n_rv_fail += 1
            continue
        survivors.append(
            {
                "ticker": t,
                "close_asof": _r4(close),
                "shares": shares,
                "shares_source": shares_src,
                "market_cap_usd": _r4(mcap),
                "adv20_median_usd": _r4(adv),
                "rv20_pct": rv,
                "primary_exchange": pe,
                "n_daily_bars": len(closes),
            }
        )

    survivors.sort(key=lambda r: (-r["rv20_pct"], r["ticker"]))
    candidates = survivors[:TOP_N]
    screen_summary = {
        "n_cs_primary_listed": len(tickers),
        "n_price_pass_after_asof_dv_prefilter": len(price_pass),
        "asof_dv_prefilter_usd": ASOF_DV_PREFILTER,
        "n_details_called": n_details,
        "n_cap_fail": n_cap_fail,
        "n_adv_fail": n_adv_fail,
        "n_rv_fail": n_rv_fail,
        "n_bars_fail": n_bars_fail,
        "n_survivors": len(survivors),
        "n_candidates": len(candidates),
        "underfill": len(candidates) < TOP_N,
    }
    print(f"# survivors={len(survivors)} candidates={len(candidates)}", file=sys.stderr)

    samples: dict[str, dict[str, Any]] = {}
    for row in candidates:
        sym = row["ticker"]
        samples[sym] = {}
        for d in SAMPLE_DATES:
            print(f"# quotes {sym} {d} ...", file=sys.stderr, flush=True)
            samples[sym][d] = _sample_session_quotes(client, sym, d)

    return {
        "candidates": candidates,
        "samples": samples,
        "screen_summary": screen_summary,
        "all_survivors_ranked": survivors,
    }


def _dump(obj: Any, path: Path) -> str:
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    # Platform-stable newlines.
    text = text.replace("\r\n", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument(
        "--replay-artifact",
        type=Path,
        default=None,
        help="Skip network; rematerialize map from a prior artifact's raw block",
    )
    ap.add_argument(
        "--raw-cache",
        type=Path,
        default=None,
        help="Optional path to write/read the network raw payload separately",
    )
    args = ap.parse_args(argv)

    if os.environ.get("PYTHONHASHSEED") != "0":
        print("WARNING: PYTHONHASHSEED!=0; evidence runs require 0", file=sys.stderr)

    if args.replay_artifact is not None:
        prior = json.loads(args.replay_artifact.read_text(encoding="utf-8"))
        raw = prior["raw"]
        out = materialize(raw)
        out["raw"] = raw
        digest = _dump(out, args.json)
        print(f"wrote {args.json} sha256={digest} verdict={out['verdict']}", flush=True)
        return 0

    raw = run_network()
    if args.raw_cache is not None:
        _dump(raw, args.raw_cache)
    out = materialize(raw)
    out["raw"] = raw
    digest = _dump(out, args.json)
    print(f"wrote {args.json} sha256={digest} verdict={out['verdict']}", flush=True)
    print(f"go_names={out['go_names']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
