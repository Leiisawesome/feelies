#!/usr/bin/env python3
"""Task 11-A-H10 step 2 — statistics for ``sig_sweep_kyle_drift_h900_v1``.

Consumes the extraction artifact from
``sweep_kyle_drift_validation_extract.py`` plus the committed census
artifact, and scores frozen protocol §2.2 / §2.3 / JC-5 exactly once.
NO parameter is varied (tuning prohibition, protocol §9).

Order lock and stopping rule:
  stage 0 (integrity) → 2b → (on 2b PASS only) 2.3 + JC-5.
On first FAIL at 2b, §9 consequence REJECTED is assigned and later
stages are NOT computed.

Binding evidence set (§2.2): census eligible episodes on viable_long
sessions, pooled {APP ∪ RMBS} (expect n = 152 = APP 94 + RMBS 58).
IC pair: x = sweep_flow_imbalance (signed), y = signed forward 900 s
mid log-return.  Statistics via ``feelies.research.forward_ic``.

Determinism: PYTHONHASHSEED=0; bit-identical JSON on re-run (P0-4).
First step-2 outcome contact advances ledger N 11 → 12.

Usage
-----
    $env:PYTHONHASHSEED=0; uv run python `
        scripts/research/sweep_kyle_drift_validation_stats.py `
        --extract docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/`
boundaries_extract_YYYY-MM-DD.json `
        --json docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/`
validation_stats_YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts" / "research") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "research"))

import sweep_kyle_drift_census as census  # noqa: E402

from feelies.research.forward_ic import (  # noqa: E402
    bucketed_forward_return,
    long_short_edge_bps,
    spearman_ic,
)

# Frozen floors / power (protocol §1.2 / §2.2 / §2.3).
FLOOR_LONG_BPS = dict(census.FLOOR_LONG_BPS)
FLOOR_SHORT_BPS = dict(census.FLOOR_SHORT_BPS)
POWER_FLOOR = census.POWER_FLOOR
POOLED_VIABLE_EXPECTED = 152  # APP 94 + RMBS 58 (census PROCEED)
N_LEDGER_AT_STEP2 = 12  # first outcome contact: 11 → 12

STAGE_CONSEQUENCE = {
    "2b": "REJECTED (F1/F2 dead — no conditional continuation edge, or F2 attribution fail)",
    "2.3": "PARKED (economics below floor everywhere — D empty)",
    "JC-5": "primary 2b PASS stands; failing symbol leaves D; pool recheck vs ≥ 100",
}

STAGE0_FIELDS = (
    "n_boundaries",
    "n_in_window",
    "n_warm_eligible",
    "episodes",
    "episodes_long",
    "episodes_short",
    "sigma900_bps",
    "viable_long",
    "viable_short",
    "sfi_warm_fraction_in_window",
)


# ── Small stats helpers ───────────────────────────────────────────────────


def _mean_se(xs: Sequence[float]) -> tuple[float, float, int]:
    n = len(xs)
    if n == 0:
        return (float("nan"), float("nan"), 0)
    m = statistics.fmean(xs)
    if n < 2:
        return (m, float("nan"), n)
    se = statistics.stdev(xs) / math.sqrt(n)
    return (m, se, n)


def _tstat(xs: Sequence[float]) -> float:
    m, se, n = _mean_se(xs)
    if n < 2 or se == 0.0 or math.isnan(se):
        return float("nan")
    return m / se


def _ic_block(xs: list[float], ys: list[float]) -> dict[str, Any]:
    if len(xs) < 3:
        return {"n": len(xs), "rank_ic": None, "p": None}
    r = spearman_ic(xs, ys)
    return {"n": r.n, "rank_ic": r.rho, "p": r.p_value}


def _crit(
    name: str,
    value: Any,
    threshold: str,
    ok: bool,
    *,
    n_class: str,
) -> dict[str, Any]:
    return {
        "criterion": name,
        "value": value,
        "threshold": threshold,
        "pass": bool(ok),
        "n_class": n_class,
    }


def _ycont(b: dict) -> float | None:
    """Continuation-signed forward 900 s log-return (matched to SFI sign)."""
    y = b["fwd"]["900"]
    sfi = b["sfi"]
    if y is None or sfi is None or sfi == 0.0:
        return None
    return y if sfi > 0.0 else -y


def contrast_material(
    elev: Sequence[float], base: Sequence[float]
) -> tuple[float | None, bool]:
    """Mean(elev) − mean(base); material iff contrast > 0 and > 1 SE of diff."""
    me, se_e, ne = _mean_se(elev)
    mb, se_b, nb = _mean_se(base)
    if ne == 0 or nb == 0 or math.isnan(me) or math.isnan(mb):
        return None, False
    contrast = me - mb
    if ne >= 2 and nb >= 2 and not math.isnan(se_e) and not math.isnan(se_b):
        se_diff = math.sqrt(se_e**2 + se_b**2)
        material = contrast > 0.0 and (se_diff == 0.0 or contrast > se_diff)
    else:
        material = contrast > 0.0
    return contrast, material


# ── Population selectors ──────────────────────────────────────────────────


def _viable_cells(cells: list[dict]) -> list[dict]:
    return [c for c in cells if c.get("viable_long") is True]


def primary_eligible(cells: list[dict]) -> list[tuple[str, dict]]:
    """Census §1.1 eligible episodes on viable_long sessions."""
    out: list[tuple[str, dict]] = []
    for c in _viable_cells(cells):
        for b in c["boundaries"]:
            if b["eligible"]:
                out.append((c["symbol"], b))
    return out


def interior_boundaries(cells: list[dict]) -> list[tuple[str, dict]]:
    """Warm in-window, pctl ∈ (0.10, 0.90), viable_long — no full entry gates."""
    lo, hi = census.SFI_PCTL_LO, census.SFI_PCTL_HI
    out: list[tuple[str, dict]] = []
    for c in _viable_cells(cells):
        for b in c["boundaries"]:
            if not (b["in_window"] and b["all_warm"]):
                continue
            p = b["sfi_pctl"]
            if p is None or not (lo < p < hi):
                continue
            out.append((c["symbol"], b))
    return out


def baseline_warm(cells: list[dict]) -> list[tuple[str, dict]]:
    """Warm in-window non-eligible on viable_long (F2 baseline)."""
    out: list[tuple[str, dict]] = []
    for c in _viable_cells(cells):
        for b in c["boundaries"]:
            if b["in_window"] and b["all_warm"] and not b["eligible"]:
                out.append((c["symbol"], b))
    return out


def _ic_pairs(bnds: list[tuple[str, dict]]) -> tuple[list[float], list[float], int]:
    xs: list[float] = []
    ys: list[float] = []
    dropped = 0
    for _sym, b in bnds:
        x = b["sfi"]
        y = b["fwd"]["900"]
        if x is None or y is None:
            dropped += 1
            continue
        xs.append(float(x))
        ys.append(float(y))
    return xs, ys, dropped


# ── Stage 0 — integrity pin ───────────────────────────────────────────────


def stage0_integrity(extract: dict, census_art: dict) -> dict[str, Any]:
    census_cells = {(c["symbol"], c["date"]): c for c in census_art["cells"]}
    mismatches: list[str] = []
    checked = 0
    for c in extract["cells"]:
        key = (c["symbol"], c["date"])
        cc = census_cells.get(key)
        if cc is None:
            mismatches.append(f"{key}: missing in census artifact")
            continue
        bs = c["boundaries"]
        from_bnd = {
            "n_in_window": sum(1 for b in bs if b["in_window"]),
            "n_warm_eligible": sum(1 for b in bs if b["in_window"] and b["all_warm"]),
            "episodes": sum(1 for b in bs if b["eligible"]),
            "episodes_long": sum(1 for b in bs if b["eligible"] and b["side"] == "LONG"),
            "episodes_short": sum(1 for b in bs if b["eligible"] and b["side"] == "SHORT"),
        }
        for fld, val in from_bnd.items():
            if c[fld] != val:
                mismatches.append(
                    f"{key}: boundary-derived {fld}={val!r} != cell={c[fld]!r}"
                )
        for field in STAGE0_FIELDS:
            extract_val = c[field]
            census_val = cc[field]
            if extract_val != census_val:
                mismatches.append(
                    f"{key}: {field} extract={extract_val!r} census={census_val!r}"
                )
        checked += 1

    app_n = len(primary_eligible([c for c in extract["cells"] if c["symbol"] == "APP"]))
    rmbs_n = len(primary_eligible([c for c in extract["cells"] if c["symbol"] == "RMBS"]))
    pooled = app_n + rmbs_n
    if app_n != 94:
        mismatches.append(f"pooled viable APP episodes {app_n} != 94")
    if rmbs_n != 58:
        mismatches.append(f"pooled viable RMBS episodes {rmbs_n} != 58")
    if pooled != POOLED_VIABLE_EXPECTED:
        mismatches.append(f"pooled viable episodes {pooled} != {POOLED_VIABLE_EXPECTED}")

    return {
        "cells_checked": checked,
        "mismatches": mismatches,
        "evidence_counts": {"APP": app_n, "RMBS": rmbs_n, "pooled": pooled},
        "ok": not mismatches,
    }


# ── Stage 2b — RankIC gate ────────────────────────────────────────────────


def stage_2b(app: list[dict], rmbs: list[dict]) -> dict[str, Any]:
    grid = app + rmbs
    extreme = primary_eligible(grid)
    interior = interior_boundaries(grid)
    base = baseline_warm(grid)

    ex, ey, edrop = _ic_pairs(extreme)
    ix, iy, idrop = _ic_pairs(interior)
    e_ic = _ic_block(ex, ey)
    i_ic = _ic_block(ix, iy)
    contrast = (
        e_ic["rank_ic"] - i_ic["rank_ic"]
        if e_ic["rank_ic"] is not None and i_ic["rank_ic"] is not None
        else None
    )

    # Interior continuation-signed mean ≤ 0 within 2 SE (not sig positive).
    iy_cont = [y for _s, b in interior if (y := _ycont(b)) is not None]
    im, ise, in_ = _mean_se(iy_cont)
    interior_not_sig_pos = not (in_ >= 2 and im > 0.0 and im / ise > 2.0)

    # F2 λ / volume co-travel.
    elev_kyle = [
        float(b["kyle_lambda_60s_percentile"])
        for _s, b in extreme
        if b["kyle_lambda_60s_percentile"] is not None
    ]
    base_kyle = [
        float(b["kyle_lambda_60s_percentile"])
        for _s, b in base
        if b["kyle_lambda_60s_percentile"] is not None
    ]
    elev_vol = [float(b["print_volume_900s"]) for _s, b in extreme]
    base_vol = [float(b["print_volume_900s"]) for _s, b in base]
    kyle_c, kyle_mat = contrast_material(elev_kyle, base_kyle)
    vol_c, vol_mat = contrast_material(elev_vol, base_vol)
    f2_pass = kyle_mat or vol_mat

    # Per-symbol diagnostics (non-governing magnitude/p; sign → JC-5).
    per_symbol: dict[str, Any] = {}
    for sym, cells in (("APP", app), ("RMBS", rmbs)):
        xs, ys, _ = _ic_pairs(primary_eligible(cells))
        per_symbol[sym] = _ic_block(xs, ys)

    # Bucket monotonicity.
    edge = long_short_edge_bps(ex, ey) if len(ex) >= 5 else float("nan")
    buckets = bucketed_forward_return(ex, ey, n_buckets=5) if len(ex) >= 5 else []

    # Conditional tail (F1): mean continuation-signed 900 s on primary eligible.
    tail = [y for _s, b in extreme if (y := _ycont(b)) is not None]
    tm, tse, tn = _mean_se(tail)
    tt = _tstat(tail)

    ric = e_ic["rank_ic"]
    p = e_ic["p"]
    n_evidence = len(extreme)

    criteria = [
        _crit(
            "extreme-SFI pooled RankIC sign",
            ric,
            "> 0 (continuation-correct)",
            ric is not None and ric > 0,
            n_class="n-invariant",
        ),
        _crit(
            "extreme-SFI pooled |RankIC|",
            ric,
            ">= 0.03",
            ric is not None and abs(ric) >= 0.03,
            n_class="n-invariant",
        ),
        _crit(
            "extreme-SFI pooled Fisher-z p",
            p,
            "<= 0.01",
            p is not None and p <= 0.01,
            n_class="n-variant",
        ),
        _crit(
            "pooled sample minimum (viable-region extreme)",
            n_evidence,
            ">= 100",
            n_evidence >= 100,
            n_class="n-variant",
        ),
        _crit(
            "interior contrast (extreme RankIC - interior RankIC > 0 "
            "AND interior continuation-signed mean <= 0 within 2 SE)",
            {
                "contrast": contrast,
                "interior_mean_bps": im * 1e4 if in_ else None,
                "interior_se_bps": ise * 1e4 if in_ >= 2 else None,
                "interior_n": in_,
            },
            "contrast > 0 AND interior not significantly positive",
            contrast is not None and contrast > 0 and interior_not_sig_pos,
            n_class="n-invariant",
        ),
        _crit(
            "F2 lambda/volume co-travel",
            {
                "kyle_contrast": kyle_c,
                "kyle_material": kyle_mat,
                "volume_contrast": vol_c,
                "volume_material": vol_mat,
            },
            "at least one contrast > 0 with material separation (> 1 SE)",
            f2_pass,
            n_class="mechanism",
        ),
        _crit(
            "per-symbol diagnostics (reported, non-governing)",
            per_symbol,
            "reported (sign feeds JC-5 on 2b PASS only)",
            True,
            n_class="diagnostic",
        ),
        _crit(
            "bucket monotonicity (top-minus-bottom forward-return spread)",
            edge,
            "> 0 (continuation direction)",
            not math.isnan(edge) and edge > 0,
            n_class="n-invariant",
        ),
        _crit(
            "conditional tail (mean continuation-signed 900s fwd, t >= 2)",
            {"mean_bps": tm * 1e4 if tn else None, "t": tt, "n": tn},
            "mean > 0 with t >= 2",
            tn >= 2 and tm > 0.0 and tt >= 2.0,
            n_class="n-invariant (sign); t n-variant",
        ),
    ]

    return {
        "n_extreme": n_evidence,
        "dropped_none_pairs": {"extreme": edrop, "interior": idrop},
        "extreme_ic": e_ic,
        "interior_ic": i_ic,
        "interior_contrast": contrast,
        "interior_continuation": {
            "n": in_,
            "mean_bps": im * 1e4 if in_ else None,
            "se_bps": ise * 1e4 if in_ >= 2 else None,
            "t": _tstat(iy_cont),
            "not_significantly_positive": interior_not_sig_pos,
        },
        "f2": {
            "kyle_contrast": kyle_c,
            "kyle_material": kyle_mat,
            "volume_contrast": vol_c,
            "volume_material": vol_mat,
            "pass": f2_pass,
        },
        "per_symbol": per_symbol,
        "bucket_monotonicity": {
            "edge_bps": edge,
            "bucket_means_bps": [round(b.mean_forward_return * 1e4, 4) for b in buckets],
            "bucket_ns": [b.n for b in buckets],
        },
        "conditional_tail": {
            "n": tn,
            "mean_bps": tm * 1e4 if tn else None,
            "se_bps": tse * 1e4 if tn >= 2 else None,
            "t": tt,
        },
        "criteria": criteria,
    }


# ── Stage 2.3 — measured-edge floors ──────────────────────────────────────


def stage_23(app: list[dict], rmbs: list[dict], deployable: list[str]) -> dict[str, Any]:
    remaining: list[str] = []
    per: dict[str, Any] = {}
    for sym, cells in (("APP", app), ("RMBS", rmbs)):
        if sym not in deployable:
            continue
        eps = primary_eligible(cells)
        both = [y for _s, b in eps if (y := _ycont(b)) is not None]
        longs = [
            y
            for _s, b in eps
            if b["side"] == "LONG" and (y := _ycont(b)) is not None
        ]
        shorts = [
            y
            for _s, b in eps
            if b["side"] == "SHORT" and (y := _ycont(b)) is not None
        ]
        m_all, se_all, n_all = _mean_se(both)
        m_l, _se_l, n_l = _mean_se(longs)
        m_s, _se_s, n_s = _mean_se(shorts)
        pass_long = n_all >= 1 and m_all * 1e4 >= FLOOR_LONG_BPS[sym]
        pass_sell = n_s >= 1 and m_s * 1e4 >= FLOOR_SHORT_BPS[sym]
        # Symbol remains in D iff long floor clears; SELL fail restates long-only.
        stays = pass_long
        if stays:
            remaining.append(sym)
        per[sym] = {
            "pooled": {
                "n": n_all,
                "mean_bps": m_all * 1e4 if n_all else None,
                "se_bps": se_all * 1e4 if n_all >= 2 else None,
            },
            "long": {"n": n_l, "mean_bps": m_l * 1e4 if n_l else None},
            "short_SELL": {"n": n_s, "mean_bps": m_s * 1e4 if n_s else None},
            "floor_long_bps": FLOOR_LONG_BPS[sym],
            "floor_short_rider_bps": FLOOR_SHORT_BPS[sym],
            "clears_long_floor": pass_long,
            "clears_sell_rider": pass_sell,
            "stays_in_D": stays,
            "sell_leg_restatement": not pass_sell,
        }

    criteria = [
        _crit(
            f"{sym} measured conditional edge >= single-stress floor",
            per[sym]["pooled"]["mean_bps"],
            f">= {FLOOR_LONG_BPS[sym]}",
            per[sym]["clears_long_floor"],
            n_class="n-variant",
        )
        for sym in deployable
        if sym in per
    ]
    criteria.append(
        _crit(
            "D non-empty after floor filter",
            remaining,
            "at least one symbol remains in D",
            len(remaining) > 0,
            n_class="n-variant",
        )
    )
    # SELL-leg floors reported (restatement trigger; not alone a park).
    for sym in deployable:
        if sym not in per:
            continue
        criteria.append(
            _crit(
                f"{sym} SELL-leg vs rider-inclusive floor (restatement if fail)",
                per[sym]["short_SELL"]["mean_bps"],
                f">= {FLOOR_SHORT_BPS[sym]} (restatement, not park while long clears)",
                True,  # never alone fails the stage; long floor governs D
                n_class="diagnostic",
            )
        )

    g12 = None
    if remaining:
        edges = [
            per[s]["pooled"]["mean_bps"]
            for s in remaining
            if per[s]["pooled"]["mean_bps"] is not None
        ]
        g12 = min(edges) if edges else None

    return {
        "per_symbol": per,
        "deployable_D_in": list(deployable),
        "deployable_D_out": remaining,
        "g12_edge_estimate_bps_input": g12,
        "criteria": criteria,
        "park_d_empty": len(remaining) == 0,
    }


# ── Stage JC-5 — sign-consistency D-membership ────────────────────────────


def stage_jc5(
    app: list[dict],
    rmbs: list[dict],
    deployable: list[str],
    per_symbol_ic: dict[str, Any],
) -> dict[str, Any]:
    remaining: list[str] = []
    dropped: list[str] = []
    for sym in deployable:
        ric = per_symbol_ic.get(sym, {}).get("rank_ic")
        if ric is not None and ric > 0:
            remaining.append(sym)
        else:
            dropped.append(sym)

    # Pooled power recheck on remaining D.
    cells_by = {"APP": app, "RMBS": rmbs}
    pooled = sum(len(primary_eligible(cells_by[s])) for s in remaining)
    power_ok = pooled >= POWER_FLOOR

    criteria = [
        _crit(
            f"{sym} own-boundary extreme RankIC sign continuation-positive",
            per_symbol_ic.get(sym, {}).get("rank_ic"),
            "> 0 (else leaves D)",
            sym in remaining,
            n_class="deployability (acts only on 2b PASS)",
        )
        for sym in deployable
    ]
    criteria.append(
        _crit(
            "pooled viable episodes on remaining D >= 100",
            pooled,
            f">= {POWER_FLOOR}",
            power_ok,
            n_class="n-variant (axis-split recheck)",
        )
    )
    return {
        "deployable_D_in": list(deployable),
        "dropped": dropped,
        "deployable_D_out": remaining,
        "pooled_viable_episodes_remaining": pooled,
        "criteria": criteria,
        # JC-5 cannot park/reject the card; only shrinks D / power-recheck.
        "card_park": len(remaining) == 0 or not power_ok,
    }


# ── Main ──────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract", type=Path, required=True)
    ap.add_argument(
        "--census",
        type=Path,
        default=Path("docs/research/artifacts/sweep_kyle_drift_census_2026-07-16.json"),
    )
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args(argv)

    extract_bytes = args.extract.read_bytes()
    census_bytes = args.census.read_bytes()
    extract = json.loads(extract_bytes)
    census_art = json.loads(census_bytes)
    app = [c for c in extract["cells"] if c["symbol"] == "APP"]
    rmbs = [c for c in extract["cells"] if c["symbol"] == "RMBS"]

    # Census-pinned D at PROCEED.
    deployable = list(
        census_art.get("park_conditions", {}).get("deployable_set_D", ["APP", "RMBS"])
    )

    out: dict[str, Any] = {
        "protocol": "sig_sweep_kyle_drift_h900_v1_validation_protocol.md step 2 statistics",
        "n_ledger_note": (
            f"First step-2 outcome contact: N advances 11 → {N_LEDGER_AT_STEP2} "
            "(protocol §10 / header)"
        ),
        "n_ledger_at_outcome": N_LEDGER_AT_STEP2,
        "inputs": {
            "extract": {
                "path": str(args.extract),
                "sha256": hashlib.sha256(extract_bytes).hexdigest(),
            },
            "census": {
                "path": str(args.census),
                "sha256": hashlib.sha256(census_bytes).hexdigest(),
            },
        },
        "stages": {},
    }

    print("== stage 0: census integrity pin ==", file=sys.stderr)
    s0 = stage0_integrity(extract, census_art)
    out["stages"]["0_integrity"] = s0
    if not s0["ok"]:
        for m in s0["mismatches"][:50]:
            print(f"  MISMATCH {m}", file=sys.stderr)
        out["verdict"] = "HALT — integrity pin failed"
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1
    print(
        f"  ok: {s0['cells_checked']} cells; evidence {s0['evidence_counts']}",
        file=sys.stderr,
    )

    print("== stage 2b ==", file=sys.stderr)
    s2b = stage_2b(app, rmbs)
    out["stages"]["2b"] = s2b
    fails_2b = [c for c in s2b["criteria"] if not c["pass"]]
    for c in s2b["criteria"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['criterion']}", file=sys.stderr)
    if fails_2b:
        out["first_fail_stage"] = "2b"
        out["status_consequence"] = STAGE_CONSEQUENCE["2b"]
        out["verdict"] = "REJECTED"
        print(f"  -> FIRST FAIL at 2b: {STAGE_CONSEQUENCE['2b']}", file=sys.stderr)
        print("  -> STOP (2.3 / JC-5 NOT computed)", file=sys.stderr)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    print("== stage 2.3 ==", file=sys.stderr)
    s23 = stage_23(app, rmbs, deployable)
    out["stages"]["2.3"] = s23
    for c in s23["criteria"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['criterion']}", file=sys.stderr)
    d_after_23 = s23["deployable_D_out"]
    if s23["park_d_empty"]:
        out["first_fail_stage"] = "2.3"
        out["status_consequence"] = STAGE_CONSEQUENCE["2.3"]
        out["verdict"] = "PARKED"
        print(f"  -> D empty: {STAGE_CONSEQUENCE['2.3']}", file=sys.stderr)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0

    print("== stage JC-5 ==", file=sys.stderr)
    sjc = stage_jc5(app, rmbs, d_after_23, s2b["per_symbol"])
    out["stages"]["JC-5"] = sjc
    for c in sjc["criteria"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['criterion']}", file=sys.stderr)
    out["deployable_set_D"] = sjc["deployable_D_out"]
    if sjc["card_park"]:
        out["first_fail_stage"] = "JC-5"
        out["status_consequence"] = (
            "PARKED (power) — D empty or pooled < 100 after sign-consistency drop"
        )
        out["verdict"] = "PARKED"
    else:
        out["first_fail_stage"] = None
        out["status_consequence"] = (
            "STEP 2 PASS — proceed to later protocol steps under order lock"
        )
        out["verdict"] = "PROCEED_STEP2"

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
