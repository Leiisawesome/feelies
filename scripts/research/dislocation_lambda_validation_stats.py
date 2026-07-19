#!/usr/bin/env python3
"""Task 11 (protocol steps 2-6) — statistics for
``sig_dislocation_lambda_drift_v1`` from the boundary-level extraction.

Consumes the extraction artifact produced by
``dislocation_lambda_validation_extract.py`` (ONE deterministic replay
per cell) plus the committed EXPANDED CENSUS artifact, and computes
every step-2..6 statistic of the FROZEN protocol
(``docs/research/sig_dislocation_lambda_drift_v1_validation_protocol.md``
+ AMENDMENTS A-1/A-2) exactly once, at the frozen thresholds.  NO
parameter is varied; NO statistic is recomputed under alternatives
(tuning prohibition, protocol section 9).

Order lock and stopping rule: stages run in the frozen order
2b -> 2.3 -> 2.4 -> 3 -> 4 -> 4.4 -> 5 -> 6; on the FIRST stage
containing a FAIL the section-9 consequence is assigned and later
stages are NOT computed (no statistic is produced beyond the first
failing stage).

Integrity pin (stage 0, before any statistic): the extraction must
reproduce the committed EXPANDED CENSUS per-cell table EXACTLY
(boundaries, in-window, warm, lambda-elevated-warm, incl/primary/
binary/volume-basis episode counts, long/short splits, sigma_300,
viability labels) and the A-2.1 ruled evidence-set counts
(APP 657 / RMBS 574 / pooled 1,231).  Any deviation halts the run.

Binding conventions (disclosed; frozen sources cited inline):
- IC pair (JC-3): x = micro_price_drift / micro_price, y = signed
  forward 300 s mid log-return; zero-move boundaries keep y = 0.0
  (a valid pair — dropping ties would deflate the A-2.1 ruled ns).
- Contamination (JC-1): statistics on the intensity-excluded PRIMARY
  basis bind; including-flagged and binary reported alongside.
- Evidence set (A-2.1): pooled {APP + RMBS-evidence-only}
  lambda-elevated warm in-window boundaries over viable-region
  (viable_long) sessions; APP safeguard at its own n.
- CPCV (A-2.3, JC-2, JC-8): n_groups=20 session-aligned, k=2,
  purge 1 bar, embargo 3 bars, per-split edge_scale_bps OLS through
  origin on the spec 6.2 ``excess`` clipped [6.0, 16.0],
  annualization sqrt(78 x 252), bootstrap n=10,000 seed=0.  RF-1:
  halt unless every APP session emitted exactly 78 bars.  RF-2:
  all 20 APP sessions (viability-blind series).
- DSR (step 5): shipped ``build_dsr_evidence_from_returns`` at the
  honest then-current N; ``expected_max_sharpe`` ceiling reported.
- Drift (step 6, JC-5): bounds as frozen; the screen-ON dwell is
  reported under three disclosed measurement conventions (instrument
  ambiguity flagged for Lei), the binding section 6.2 rate-ratio
  bound is exact counting.

Determinism: PYTHONHASHSEED=0; the only stochastic elements are the
seeded bootstraps inside the shipped builders (Inv-5 bit-identical).
Bit-identical JSON output on re-run is required (P0-4).

Usage
-----
    PYTHONHASHSEED=0 uv run python \
        scripts/research/dislocation_lambda_validation_stats.py \
        --extract docs/research/artifacts/sig_dislocation_lambda_drift_v1/\
boundaries_extract_2026-07-14.json \
        --json docs/research/artifacts/sig_dislocation_lambda_drift_v1/\
validation_stats_2026-07-14.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import warnings
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.research.cpcv import (  # noqa: E402
    CPCVConfig,
    build_cpcv_evidence,
    generate_cpcv_splits,
)
from feelies.research.dsr import (  # noqa: E402
    build_dsr_evidence_from_returns,
    expected_max_sharpe,
    sharpe_ratio,
    standardised_moments,
)
from feelies.research.forward_ic import (  # noqa: E402
    bucketed_forward_return,
    long_short_edge_bps,
    spearman_ic,
)

# ── Frozen constants (protocol sections 1-6; alpha YAML literals) ─────────

DISLOC_MIN = {"APP": 2.53563e-3, "RMBS": 2.37165e-3}  # spec 1.2 / evaluate()
FLOOR_LONG_BPS = {"APP": 4.6809, "RMBS": 5.4645}  # spec 5.2 single-stress
FLOOR_SHORT_BPS = {"APP": 5.82, "RMBS": 6.60}  # rider-inclusive short
EDGE_CAP_BPS = 12.0
EDGE_SCALE_CLIP = (6.0, 16.0)
LAMBDA_P0 = 0.5
COST_DEDUCT_BPS = {"APP": 6.2412, "RMBS": 7.2861}  # 2 x C_ow,stressed (3.2)
ANNUALIZATION = math.sqrt(78 * 252)  # ~140.20 (3.3 / A-2.3)
CPCV_CFG = CPCVConfig(n_groups=20, k_test_groups=2, label_horizon_bars=1, embargo_bars=3)
N_BOOTSTRAP = 10_000
SEED = 0
SPREAD_TERCILES_APP = (50, 72)  # A-2.2 GOVERNING recompute (identical to C.6)
LAMBDA_BANDS = ((0.5, 0.65), (0.65, 0.8), (0.8, 1.0 + 1e-12))  # I-3 (JC-9)
IC_T_GRID = (60, 120, 300, 600)  # JC-7
HL_WINDOW = (75.0, 300.0)  # JC-7
N_TRIALS_HONEST = 11  # N=10 at freeze + 1: step-2 execution is the H8
# primary row's FIRST outcome contact (FQ-6B-R; protocol section 10 /
# A-2.4 "first outcome contact remains the step-2 execution").
P_VB_MAX = 0.7
RVZ_MAX = 3.0

# Section 9 status consequences per stage.
STAGE_CONSEQUENCE = {
    "2b": "REJECTED (F1/F2 dead — no conditional continuation edge, or the lambda arm does no work)",
    "2.3": "PARKED (economics below floor everywhere)",
    "2.4": "REJECTED on affected stratum (grid artifact); if D empties -> PARKED",
    "3": "REJECTED (does not survive purged OOS reconstruction)",
    "4": "HYPOTHESIS-REVISE (regime-fragile); F3 reversal -> REJECTED (definition kill)",
    "4.4": "HYPOTHESIS-REVISE (misattribution / contamination)",
    "5": "REJECTED (indistinguishable from max-of-N noise)",
    "6": "HYPOTHESIS-REVISE (machinery unstable across sessions)",
}


# ── Small stats helpers (pure stdlib) ─────────────────────────────────────


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


def _crit(name: str, value: Any, threshold: str, ok: bool) -> dict[str, Any]:
    return {"criterion": name, "value": value, "threshold": threshold, "pass": bool(ok)}


# ── Boundary access helpers ───────────────────────────────────────────────


def _x(b: dict) -> float | None:
    return b["x"]


def _ycont(b: dict) -> float | None:
    """Continuation-signed forward 300 s log-return (sign-matched to drift)."""
    y = b["fwd"]["300"]
    if y is None or b["drift"] is None:
        return None
    return y if b["drift"] > 0.0 else -y


def _keep(b: dict, basis: str) -> bool:
    if basis == "incl":
        return True
    if basis == "primary":
        return not b["excluded_primary"]
    if basis == "binary":
        return not b["any_flag"]
    raise ValueError(basis)


def _evidence_boundaries(cells: list[dict], *, elevated: bool) -> list[tuple[str, dict]]:
    """A-2.1 evidence population: warm in-window boundaries on
    viable-region (viable_long) sessions, lambda-stratified."""
    out: list[tuple[str, dict]] = []
    for c in cells:
        if not c["viable_long"]:
            continue
        for b in c["boundaries"]:
            if not (b["in_window"] and b["all_warm"]):
                continue
            p = b["pctl"]
            if p is None:
                continue
            if elevated != (p >= LAMBDA_P0):
                continue
            out.append((c["symbol"], b))
    return out


def _pairs(bnds: list[tuple[str, dict]], basis: str) -> tuple[list[float], list[float], int]:
    """(x, y) pairs on a contamination basis; returns dropped-None count."""
    xs: list[float] = []
    ys: list[float] = []
    dropped = 0
    for _sym, b in bnds:
        if not _keep(b, basis):
            continue
        x = _x(b)
        y = b["fwd"]["300"]
        if x is None or y is None:
            dropped += 1
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys, dropped


def _episodes(cells: list[dict], *, basis: str, viable_only: bool = True) -> list[dict]:
    """Eligible episodes (census predicate) on a contamination basis."""
    out: list[dict] = []
    for c in cells:
        if viable_only and not c["viable_long"]:
            continue
        for b in c["boundaries"]:
            if b["eligible_incl"] and _keep(b, basis):
                out.append(b)
    return out


# ── Stage 0 — integrity pin ───────────────────────────────────────────────


def stage0_integrity(extract: dict, census: dict) -> dict[str, Any]:
    census_cells = {(c["symbol"], c["date"]): c for c in census["cells"]}
    mismatches: list[str] = []
    checked = 0
    for c in extract["cells"]:
        key = (c["symbol"], c["date"])
        cc = census_cells.get(key)
        if cc is None:
            mismatches.append(f"{key}: missing in census artifact")
            continue
        bs = c["boundaries"]
        is_grid = c["symbol"] in ("APP", "RMBS")
        n_in_window = sum(1 for b in bs if b["in_window"])
        n_warm = sum(1 for b in bs if b["in_window"] and b["all_warm"])
        lam = sum(
            1
            for b in bs
            if b["in_window"] and b["all_warm"] and b["pctl"] is not None and b["pctl"] >= 0.5
        )
        incl = sum(1 for b in bs if b["eligible_incl"])
        prim = sum(1 for b in bs if b["eligible_incl"] and not b["excluded_primary"])
        binry = sum(1 for b in bs if b["eligible_incl"] and not b["any_flag"])
        volx = sum(1 for b in bs if b["eligible_incl"] and b["excluded_volume"])
        p_long = sum(
            1 for b in bs if b["eligible_incl"] and not b["excluded_primary"] and b["drift"] > 0.0
        )
        p_short = prim - p_long
        recomputed = {
            "n_boundaries": c["n_boundaries"],
            "n_in_window": n_in_window,
            "n_warm_eligible": n_warm,
            "n_lambda_elevated_warm": lam,
            "cond_incl": incl,
            "cond_primary": prim,
            "cond_primary_long": p_long,
            "cond_primary_short": p_short,
            "cond_binary": binry,
            "cond_excluded_volume_basis": volx,
            "sigma300_bps": c["sigma300_bps"],
            "viable_long": c["viable_long"],
            "viable_short": c["viable_short"],
        }
        for field, val in recomputed.items():
            if not is_grid and field.startswith(("cond_", "viable_")):
                continue  # OLN: evidence-only, no episode predicate / floors
            want = cc[field]
            if val != want:
                mismatches.append(f"{key}: {field} extract={val!r} census={want!r}")
        checked += 1
    # A-2.1 ruled evidence-set counts.
    app_cells = [c for c in extract["cells"] if c["symbol"] == "APP"]
    rmbs_cells = [c for c in extract["cells"] if c["symbol"] == "RMBS"]
    n_app = len(_evidence_boundaries(app_cells, elevated=True))
    n_rmbs = len(_evidence_boundaries(rmbs_cells, elevated=True))
    if n_app != 657:
        mismatches.append(f"A-2.1 APP evidence count {n_app} != 657")
    if n_rmbs != 574:
        mismatches.append(f"A-2.1 RMBS evidence count {n_rmbs} != 574")
    return {
        "cells_checked": checked,
        "mismatches": mismatches,
        "evidence_counts": {"APP": n_app, "RMBS": n_rmbs, "pooled": n_app + n_rmbs},
        "ok": not mismatches,
    }


# ── Stage 2b — RankIC gate (A-2.1 evidence set) ───────────────────────────


def stage_2b(app: list[dict], rmbs: list[dict]) -> dict[str, Any]:
    pooled_elev = _evidence_boundaries(app, elevated=True) + _evidence_boundaries(
        rmbs, elevated=True
    )
    pooled_base = _evidence_boundaries(app, elevated=False) + _evidence_boundaries(
        rmbs, elevated=False
    )
    res: dict[str, Any] = {"bases": {}}
    for basis in ("incl", "primary", "binary"):
        ex, ey, edrop = _pairs(pooled_elev, basis)
        bx, by, bdrop = _pairs(pooled_base, basis)
        e_ic = _ic_block(ex, ey)
        b_ic = _ic_block(bx, by)
        res["bases"][basis] = {
            "elevated": e_ic,
            "baseline": b_ic,
            "lambda_contrast": (
                e_ic["rank_ic"] - b_ic["rank_ic"]
                if e_ic["rank_ic"] is not None and b_ic["rank_ic"] is not None
                else None
            ),
            "dropped_none_pairs": edrop + bdrop,
        }
    # APP-only rows (per-symbol + A-2.1 safeguard).
    app_elev = _evidence_boundaries(app, elevated=True)
    res["app"] = {}
    for basis in ("incl", "primary"):
        ax, ay, _ = _pairs(app_elev, basis)
        res["app"][basis] = _ic_block(ax, ay)
    # Baseline matched-dislocation companion (lambda-contrast clause 2):
    # baseline-lambda boundaries passing the per-symbol dislocation gate,
    # continuation-signed mean must NOT be significantly positive.
    yc: list[float] = []
    for sym, b in pooled_base:
        if not _keep(b, "primary"):
            continue
        x = _x(b)
        y = _ycont(b)
        if x is None or y is None or abs(x) < DISLOC_MIN[sym]:
            continue
        yc.append(y)
    m, se, n = _mean_se(yc)
    res["baseline_matched_dislocation"] = {
        "n": n,
        "mean_bps": m * 1e4 if n else None,
        "se_bps": se * 1e4 if n >= 2 else None,
        "t": _tstat(yc),
    }
    base_not_sig_pos = not (n >= 2 and m > 0 and m / se > 2.0)
    # Bucket monotonicity (elevated/primary pooled).
    ex, ey, _ = _pairs(pooled_elev, "primary")
    edge = long_short_edge_bps(ex, ey) if len(ex) >= 5 else float("nan")
    buckets = bucketed_forward_return(ex, ey, n_buckets=5) if len(ex) >= 5 else []
    res["bucket_monotonicity"] = {
        "edge_bps": edge,
        "bucket_means_bps": [round(b.mean_forward_return * 1e4, 4) for b in buckets],
        "bucket_ns": [b.n for b in buckets],
    }
    # Conditional tail (F1 anchor): primary eligible episodes over D={APP},
    # viable region, continuation-signed 300 s forward return.
    eps = _episodes(app, basis="primary")
    tail = [y for y in (_ycont(b) for b in eps) if y is not None]
    tm, tse, tn = _mean_se(tail)
    res["conditional_tail"] = {
        "n": tn,
        "mean_bps": tm * 1e4,
        "se_bps": tse * 1e4,
        "t": _tstat(tail),
    }

    prim = res["bases"]["primary"]
    ric = prim["elevated"]["rank_ic"]
    p = prim["elevated"]["p"]
    contrast = prim["lambda_contrast"]
    app_prim = res["app"]["primary"]
    n_evidence = len(pooled_elev)
    n_app_evidence = len(app_elev)
    criteria = [
        _crit(
            "lambda-elevated pooled RankIC sign (primary)", ric, "> 0", ric is not None and ric > 0
        ),
        _crit(
            "lambda-elevated pooled |RankIC| (primary)",
            ric,
            ">= 0.03",
            ric is not None and abs(ric) >= 0.03,
        ),
        _crit(
            "lambda-elevated pooled Fisher-z p (primary)",
            p,
            "<= 0.01",
            p is not None and p <= 0.01,
        ),
        _crit(
            "pooled sample minimum (A-2.1 evidence set)", n_evidence, ">= 1000", n_evidence >= 1000
        ),
        _crit(
            "lambda-contrast (elevated - baseline RankIC, primary)",
            contrast,
            "> 0 AND baseline matched-disloc not significantly positive",
            contrast is not None and contrast > 0 and base_not_sig_pos,
        ),
        _crit(
            "per-symbol APP: RankIC > 0 with n >= 100 (viable region)",
            app_prim["rank_ic"],
            "> 0, n >= 100",
            app_prim["rank_ic"] is not None and app_prim["rank_ic"] > 0 and n_app_evidence >= 100,
        ),
        _crit(
            "A-2.1 APP safeguard: RankIC >= 0.03, p <= 0.05 at APP n",
            {"rank_ic": app_prim["rank_ic"], "p": app_prim["p"], "n_evidence": n_app_evidence},
            "sign-consistent RankIC >= 0.03 AND p <= 0.05",
            app_prim["rank_ic"] is not None
            and app_prim["rank_ic"] >= 0.03
            and app_prim["p"] is not None
            and app_prim["p"] <= 0.05,
        ),
        _crit(
            "bucket monotonicity (top-minus-bottom edge, elevated/primary)",
            edge,
            "> 0 (continuation direction)",
            not math.isnan(edge) and edge > 0,
        ),
        _crit(
            "conditional tail (primary eligible episodes, D)",
            {"mean_bps": tm * 1e4, "t": res["conditional_tail"]["t"]},
            "mean > 0 with t >= 2",
            tn >= 2 and tm > 0 and res["conditional_tail"]["t"] >= 2.0,
        ),
    ]
    res["criteria"] = criteria
    return res


# ── Stage 2.3 — measured-edge anchor ──────────────────────────────────────


def stage_23(app: list[dict]) -> dict[str, Any]:
    eps = _episodes(app, basis="primary")
    both = [y for y in (_ycont(b) for b in eps) if y is not None]
    longs = [y for b in eps if b["drift"] > 0.0 and (y := _ycont(b)) is not None]
    shorts = [y for b in eps if b["drift"] < 0.0 and (y := _ycont(b)) is not None]
    m_all, se_all, n_all = _mean_se(both)
    m_l, se_l, n_l = _mean_se(longs)
    m_s, se_s, n_s = _mean_se(shorts)
    res = {
        "APP": {
            "pooled": {"n": n_all, "mean_bps": m_all * 1e4, "se_bps": se_all * 1e4},
            "long": {"n": n_l, "mean_bps": m_l * 1e4, "se_bps": se_l * 1e4},
            "short_SELL": {"n": n_s, "mean_bps": m_s * 1e4, "se_bps": se_s * 1e4},
            "floor_long_bps": FLOOR_LONG_BPS["APP"],
            "floor_short_rider_bps": FLOOR_SHORT_BPS["APP"],
        }
    }
    pass_sell = m_s * 1e4 >= FLOOR_SHORT_BPS["APP"]
    res["sell_leg_restatement"] = not pass_sell
    # On a SELL-leg failure the long-only restatement rule re-applies on
    # measured evidence (2.3 text): the binding floor check moves to the
    # long leg; the card parks only if D then empties (section 9 row 2.3).
    binding_edge = m_all * 1e4 if pass_sell else m_l * 1e4
    binding_label = "pooled" if pass_sell else "long-leg (SELL restated out on measured evidence)"
    pass_floor = binding_edge >= FLOOR_LONG_BPS["APP"]
    # G12 disclosure input: D-set minimum measured edge (one-way ratchet).
    res["g12_edge_estimate_bps_input"] = binding_edge
    res["criteria"] = [
        _crit(
            f"APP measured conditional edge ({binding_label}) >= single-stress floor",
            binding_edge,
            f">= {FLOOR_LONG_BPS['APP']}",
            pass_floor,
        ),
        _crit(
            "APP SELL-leg edge vs rider-inclusive floor (fail restates long-only, does not park while the surviving leg clears)",
            m_s * 1e4,
            f">= {FLOOR_SHORT_BPS['APP']} (restatement trigger, not a park)",
            True,
        ),
    ]
    res["sell_leg_clears"] = pass_sell
    return res


# ── Stage 2.4 — tick-constraint artifact tests ────────────────────────────


def _quartiles(xs: list[float]) -> list[float] | None:
    if len(xs) < 2:
        return None
    return [round(q, 3) for q in statistics.quantiles(xs, n=4, method="inclusive")]


def stage_24(app: list[dict], rmbs: list[dict], oln: list[dict]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    for name, cells in (("APP", app), ("RMBS", rmbs)):
        eps = _episodes(cells, basis="incl", viable_only=False)
        ticks = [float(b["spread_ticks"]) for b in eps if b["spread_ticks"] is not None]
        res[name] = {
            "eligible_boundary_spread_ticks": {
                "n": len(ticks),
                "quartiles": _quartiles(ticks),
                "min": min(ticks) if ticks else None,
                "max": max(ticks) if ticks else None,
            }
        }
    # >= 4-tick stratum re-derivation (binding row, D = {APP}).
    eps_app = _episodes(app, basis="primary")
    full = [y for y in (_ycont(b) for b in eps_app) if y is not None]
    strat = [
        y
        for b in eps_app
        if b["spread_ticks"] is not None
        and b["spread_ticks"] >= 4
        and (y := _ycont(b)) is not None
    ]
    fm, _, fn = _mean_se(full)
    sm, sse, sn = _mean_se(strat)
    sign_consistent = fn > 0 and sn > 0 and (fm > 0) == (sm > 0)
    res["ge4_tick_stratum"] = {
        "full_sample": {"n": fn, "mean_bps": fm * 1e4},
        "ge4_ticks": {"n": sn, "mean_bps": sm * 1e4, "se_bps": sse * 1e4},
        "sign_consistent": sign_consistent,
    }
    # OLN quantum test (evidence finding only; OLN never deployable).
    oln_rows = []
    for c in oln:
        for b in c["boundaries"]:
            if not (b["in_window"] and b["all_warm"]):
                continue
            oln_rows.append(b)
    lam_rows = [b for b in oln_rows if b["pctl"] is not None and b["pctl"] >= 0.5]
    moves = []
    for b in lam_rows:
        y = b["fwd"]["300"]
        if y is None or b["mid0"] is None:
            continue
        moves.append(abs(b["mid0"] * (math.exp(y) - 1.0)))
    half_tick = 0.005
    within = sum(1 for mv in moves if mv <= half_tick)
    beyond = sum(1 for mv in moves if mv > 2 * half_tick)
    pctl_ticks = [
        (b["pctl"], float(b["spread_ticks"]))
        for b in oln_rows
        if b["pctl"] is not None and b["spread_ticks"] is not None
    ]
    corr = (
        spearman_ic([p for p, _ in pctl_ticks], [t for _, t in pctl_ticks])
        if len(pctl_ticks) >= 3
        else None
    )
    res["oln_quantum"] = {
        "note": "evidence finding only — OLN has no dislocation gate by construction (never in D)",
        "lambda_elevated_warm_inwindow_n": len(lam_rows),
        "n_moves": len(moves),
        "mass_within_half_tick": within / len(moves) if moves else None,
        "mass_beyond_one_tick": beyond / len(moves) if moves else None,
        "lambda_pctl_vs_spread_ticks_spearman": (
            {"rho": corr.rho, "n": corr.n, "p": corr.p_value} if corr else None
        ),
    }
    res["criteria"] = [
        _crit(
            ">= 4-tick stratum conditional edge sign-consistent with full sample (APP)",
            {"full_mean_bps": fm * 1e4, "ge4_mean_bps": sm * 1e4, "n_ge4": sn},
            "sign-consistent",
            sign_consistent,
        ),
    ]
    return res


# ── Stage 3 — CPCV (A-2.3, APP 20 sessions) ───────────────────────────────


def _bar_record(b: dict, symbol: str) -> dict[str, Any]:
    """Per-bar eligibility + excess + continuation-signed return (bps)."""
    rec: dict[str, Any] = {"eligible": False, "excess": None, "ycont_bps": None}
    y = _ycont(b)
    if y is not None:
        rec["ycont_bps"] = y * 1e4
    if not b["eligible_incl"] or y is None:
        return rec
    x = _x(b)
    pctl = b["pctl"]
    assert x is not None and pctl is not None
    dm = DISLOC_MIN[symbol]
    d_x = min((abs(x) - dm) / dm, 1.0)
    l_x = (pctl - LAMBDA_P0) / (1.0 - LAMBDA_P0)
    rec["eligible"] = True
    rec["excess"] = 0.5 * (d_x + l_x)
    return rec


def _fit_edge_scale(bars: list[dict], idx: Sequence[int]) -> float:
    num = den = 0.0
    for i in idx:
        r = bars[i]
        if r["eligible"] and r["excess"] is not None and r["ycont_bps"] is not None:
            num += r["excess"] * r["ycont_bps"]
            den += r["excess"] * r["excess"]
    if den == 0.0:
        return 10.0  # spec default (no eligible train bar — disclosed; unreachable at n=1560)
    return min(max(num / den, EDGE_SCALE_CLIP[0]), EDGE_SCALE_CLIP[1])


def _series_return(rec: dict, edge_scale: float, *, cost_bps: float) -> float:
    if not rec["eligible"]:
        return 0.0
    edge = min(edge_scale * rec["excess"], EDGE_CAP_BPS)
    if edge < FLOOR_LONG_BPS["APP"]:
        return 0.0  # evaluate() EV gate suppresses the entry
    return rec["ycont_bps"] - cost_bps


def stage_3(app: list[dict]) -> dict[str, Any]:
    cells = sorted(app, key=lambda c: c["date"])
    # RF-1: explicit per-session group construction; halt on != 78 bars.
    for c in cells:
        if c["n_boundaries"] != 78:
            raise SystemExit(
                f"RF-1 HALT: {c['symbol']}/{c['date']} emitted {c['n_boundaries']} != 78 bars"
            )
    bars: list[dict] = []
    for c in cells:
        for b in c["boundaries"]:
            bars.append(_bar_record(b, "APP"))
    n_bars = len(bars)
    assert n_bars == 1560
    splits = generate_cpcv_splits(n_bars=n_bars, config=CPCV_CFG)
    edge_scales: list[float] = []
    test_cost: list[list[float]] = []
    test_pre: list[list[float]] = []
    cost = COST_DEDUCT_BPS["APP"]
    for s in splits:
        beta = _fit_edge_scale(bars, s.train_indices)
        edge_scales.append(beta)
        test_cost.append([_series_return(bars[i], beta, cost_bps=cost) for i in s.test_indices])
        test_pre.append([_series_return(bars[i], beta, cost_bps=0.0) for i in s.test_indices])

    ev_cost = build_cpcv_evidence(
        config=CPCV_CFG,
        n_bars=n_bars,
        test_returns_by_split=test_cost,
        annualization_factor=ANNUALIZATION,
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
    )
    ev_pre = build_cpcv_evidence(
        config=CPCV_CFG,
        n_bars=n_bars,
        test_returns_by_split=test_pre,
        annualization_factor=ANNUALIZATION,
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
    )

    def _dist(fold_sharpes: Sequence[float]) -> dict[str, Any]:
        xs = sorted(fold_sharpes)
        return {
            "n_paths": len(xs),
            "min": xs[0],
            "q1": statistics.quantiles(xs, n=4, method="inclusive")[0],
            "median": statistics.median(xs),
            "q3": statistics.quantiles(xs, n=4, method="inclusive")[2],
            "max": xs[-1],
            "mean": statistics.fmean(xs),
            "all_paths": list(fold_sharpes),
        }

    n_eligible = sum(1 for r in bars if r["eligible"])
    res = {
        "config": {
            "n_groups": 20,
            "k_test_groups": 2,
            "combinations": len(splits),
            "paths": CPCV_CFG.n_paths,
            "label_horizon_bars": 1,
            "embargo_bars": 3,
            "annualization_factor": ANNUALIZATION,
            "n_bootstrap": N_BOOTSTRAP,
            "seed": SEED,
            "n_bars": n_bars,
            "cost_deduction_bps": cost,
            "sessions": [c["date"] for c in cells],
        },
        "n_eligible_bars": n_eligible,
        "edge_scale_per_split": {
            "min": min(edge_scales),
            "max": max(edge_scales),
            "mean": statistics.fmean(edge_scales),
            "n_at_lower_clip": sum(1 for e in edge_scales if e == EDGE_SCALE_CLIP[0]),
            "n_at_upper_clip": sum(1 for e in edge_scales if e == EDGE_SCALE_CLIP[1]),
        },
        "cost_adjusted": {
            "sharpe_distribution_annualised": _dist(ev_cost.fold_sharpes),
            "mean_sharpe": ev_cost.mean_sharpe,
            "median_sharpe": ev_cost.median_sharpe,
            "mean_pnl_bps_per_path": ev_cost.mean_pnl,
            "block_bootstrap_p": ev_cost.p_value,
            "fold_pnl_curves_hash": ev_cost.fold_pnl_curves_hash,
        },
        "pre_cost_diagnostic": {
            "sharpe_distribution_annualised": _dist(ev_pre.fold_sharpes),
            "mean_sharpe": ev_pre.mean_sharpe,
            "block_bootstrap_p": ev_pre.p_value,
            "fold_pnl_curves_hash": ev_pre.fold_pnl_curves_hash,
        },
    }
    res["criteria"] = [
        _crit("reconstructed paths", CPCV_CFG.n_paths, ">= 8", CPCV_CFG.n_paths >= 8),
        _crit(
            "mean annualised path Sharpe (cost-adjusted)",
            ev_cost.mean_sharpe,
            ">= 1.0",
            ev_cost.mean_sharpe >= 1.0,
        ),
        _crit(
            "block-bootstrap p (cost-adjusted)",
            ev_cost.p_value,
            "<= 0.05",
            ev_cost.p_value <= 0.05,
        ),
        _crit("embargo bars", 3, ">= 1", True),
    ]
    return res


# ── Stage 4 — regime stratification ───────────────────────────────────────


def _spread_tercile(ticks: int | None) -> str | None:
    if ticks is None:
        return None
    if ticks <= SPREAD_TERCILES_APP[0]:
        return "t1_low"
    if ticks <= SPREAD_TERCILES_APP[1]:
        return "t2_mid"
    return "t3_high"


def stage_4(app: list[dict]) -> dict[str, Any]:
    # Warm in-window boundaries, APP full grid (binding acceptance is
    # D-scoped; RMBS participates in step 2 only per A-2.1 scope limit).
    warm: list[dict] = []
    for c in app:
        for b in c["boundaries"]:
            if b["in_window"] and b["all_warm"]:
                warm.append(b)
    vol_states = ("compression_clustering", "normal", "vol_breakout")
    spread_bins = ("t1_low", "t2_mid", "t3_high")
    cells_out: dict[str, Any] = {}
    passing_vol: set[str] = set()
    passing_spread: set[str] = set()
    for vs in vol_states:
        for sb in spread_bins:
            rows = [
                b for b in warm if b["dominant"] == vs and _spread_tercile(b["spread_ticks"]) == sb
            ]
            elev = [
                b
                for b in rows
                if b["pctl"] is not None and b["pctl"] >= LAMBDA_P0 and _keep(b, "primary")
            ]
            base = [
                b
                for b in rows
                if b["pctl"] is not None and b["pctl"] < LAMBDA_P0 and _keep(b, "primary")
            ]
            ex = [x for b in elev if (x := _x(b)) is not None and b["fwd"]["300"] is not None]
            ey = [
                b["fwd"]["300"] for b in elev if _x(b) is not None and b["fwd"]["300"] is not None
            ]
            bx = [x for b in base if (x := _x(b)) is not None and b["fwd"]["300"] is not None]
            by = [
                b["fwd"]["300"] for b in base if _x(b) is not None and b["fwd"]["300"] is not None
            ]
            e_ic = _ic_block(ex, ey)
            b_ic = _ic_block(bx, by)
            # A stratum-level CPCV cannot reproduce the section-3
            # session-aligned group construction (RF-1) with unequal
            # per-session stratum counts through the shipped builder;
            # reported CPCV-INFEASIBLE (not a fail) per section 4.2.
            entry = {
                "n_warm": len(rows),
                "elevated_ic": e_ic,
                "baseline_ic": b_ic,
                "lambda_contrast": (
                    e_ic["rank_ic"] - b_ic["rank_ic"]
                    if e_ic["rank_ic"] is not None and b_ic["rank_ic"] is not None
                    else None
                ),
                "cpcv": "CPCV-INFEASIBLE (per-session stratum counts unequal; section-3 session-aligned groups not formable via shipped builder)",
                "status": "INSUFFICIENT" if e_ic["n"] < 100 else "SCORED",
            }
            if (
                e_ic["n"] >= 100
                and e_ic["rank_ic"] is not None
                and e_ic["rank_ic"] >= 0.02
                and e_ic["p"] is not None
                and e_ic["p"] <= 0.05
            ):
                entry["cell_pass"] = True
                passing_vol.add(vs)
                passing_spread.add(sb)
            else:
                entry["cell_pass"] = False
            cells_out[f"{vs}|{sb}"] = entry
    # F3: conditional continuation sign across spread terciles within the
    # benign stratum.  Every eligible episode is benign by construction
    # (the predicate includes P(vb) < 0.7 and rvz <= 3.0) — disclosed.
    eps = _episodes(app, basis="primary")
    f3: dict[str, Any] = {}
    signs: list[int] = []
    for sb in spread_bins:
        ys = [
            y
            for b in eps
            if _spread_tercile(b["spread_ticks"]) == sb and (y := _ycont(b)) is not None
        ]
        m, se, n = _mean_se(ys)
        f3[sb] = {
            "n": n,
            "mean_bps": m * 1e4 if n else None,
            "se_bps": se * 1e4 if n >= 2 else None,
        }
        if n > 0:
            signs.append(1 if m > 0 else (-1 if m < 0 else 0))
    f3_reversal = len({s for s in signs if s != 0}) > 1
    # Daily-stratum reporting axis (gate-state x daily stratum; spec 10).
    daily: dict[str, Any] = {}
    for stratum in ("elevated_A", "calm", "elevated_B"):
        scells = [c for c in app if c["stratum"] == stratum]
        elev_b = _evidence_boundaries(scells, elevated=True)
        xs, ys, _ = _pairs(elev_b, "primary")
        seps = [
            y
            for b in _episodes(scells, basis="primary", viable_only=False)
            if (y := _ycont(b)) is not None
        ]
        m, se, n = _mean_se(seps)
        daily[stratum] = {
            "lambda_elevated_ic_viable_region": _ic_block(xs, ys),
            "episode_edge": {
                "n": n,
                "mean_bps": m * 1e4 if n else None,
                "se_bps": se * 1e4 if n >= 2 else None,
            },
        }
    n_pass_cells = sum(1 for v in cells_out.values() if v.get("cell_pass"))
    accept = len(passing_vol) >= 2 and len(passing_spread) >= 2
    res = {
        "spread_terciles_app": SPREAD_TERCILES_APP,
        "cells": cells_out,
        "n_passing_cells": n_pass_cells,
        "passing_vol_strata": sorted(passing_vol),
        "passing_spread_strata": sorted(passing_spread),
        "f3_benign_spread_terciles": f3,
        "f3_sign_reversal": f3_reversal,
        "daily_stratum_reporting": daily,
        "criteria": [
            _crit(
                "sign-stable RankIC >= 0.02 (p <= 0.05) in >= 2 vol x >= 2 spread strata (n >= 100 cells)",
                {"vol": sorted(passing_vol), "spread": sorted(passing_spread)},
                ">= 2 on each axis",
                accept,
            ),
            _crit(
                "F3: no continuation-sign reversal across spread terciles (benign stratum)",
                {k: v["mean_bps"] for k, v in f3.items()},
                "signs consistent",
                not f3_reversal,
            ),
        ],
    }
    return res


# ── Stage 4.4 — invariance checks ─────────────────────────────────────────


def stage_44(app: list[dict]) -> dict[str, Any]:
    eps = _episodes(app, basis="primary")
    res: dict[str, Any] = {}
    # I-1: zero-integrated-edge conservation.
    b_dollars = a_dollars = strat_shares = total_vol = 0.0
    n_used = 0
    for b in eps:
        y = _ycont(b)
        if y is None or b["episode"] is None or b["mid0"] is None:
            continue
        epi = b["episode"]
        vol = epi["contra_vol"] + epi["with_vol"] + epi["unclassified_vol"]
        if vol <= 0:
            continue
        b_dollars += 80.0 * b["mid0"] * y
        a_dollars += epi["contra_vol"] * b["mid0"] * y
        strat_shares += 80.0
        total_vol += vol
        n_used += 1
    share = strat_shares / total_vol if total_vol else float("nan")
    i1_ratio = b_dollars / (share * a_dollars) if share and a_dollars else float("nan")
    res["i1"] = {
        "n_episodes": n_used,
        "strategy_integrated_edge_dollars_b": b_dollars,
        "funding_pool_dollars_a": a_dollars,
        "pooled_participation_share": share,
        "ratio_b_over_share_a": i1_ratio,
        "formula": "b = sum(80 sh x mid x y_cont); a = sum(contra_vol x mid x y_cont); share = sum(80)/sum(episode volume)",
    }
    # Companion (i): unconditional in-window warm boundaries integrate ~0.
    uncond = [
        b["fwd"]["300"]
        for c in app
        for b in c["boundaries"]
        if b["in_window"] and b["all_warm"] and b["fwd"]["300"] is not None
    ]
    um, use_, un = _mean_se(uncond)
    res["i1_companion_unconditional"] = {
        "n": un,
        "mean_bps": um * 1e4,
        "se_bps": use_ * 1e4,
        "abs_mean_le_2se": abs(um) <= 2 * use_,
    }
    # Companion (ii): baseline-lambda matched dislocations (APP; step-2
    # clause was pooled — this is the D-scoped view).
    base_yc = []
    for c in app:
        if not c["viable_long"]:
            continue
        for b in c["boundaries"]:
            if not (b["in_window"] and b["all_warm"] and _keep(b, "primary")):
                continue
            p, x, y = b["pctl"], _x(b), _ycont(b)
            if p is None or x is None or y is None or p >= LAMBDA_P0:
                continue
            if abs(x) < DISLOC_MIN["APP"]:
                continue
            base_yc.append(y)
    bm, bse, bn = _mean_se(base_yc)
    base_ok = not (bn >= 2 and bm > 0 and bm / bse > 2.0)
    res["i1_companion_baseline"] = {
        "n": bn,
        "mean_bps": bm * 1e4,
        "se_bps": bse * 1e4,
        "not_sig_positive": base_ok,
    }
    i1_pass = (
        (not math.isnan(i1_ratio) and i1_ratio <= 1.5)
        and res["i1_companion_unconditional"]["abs_mean_le_2se"]
        and base_ok
    )
    # I-2: side symmetry (benign stratum = all episodes by construction).
    longs = [y for b in eps if b["drift"] > 0.0 and (y := _ycont(b)) is not None]
    shorts = [y for b in eps if b["drift"] < 0.0 and (y := _ycont(b)) is not None]
    lm, lse, ln = _mean_se(longs)
    sm, sse, sn = _mean_se(shorts)
    z = (
        abs(lm - sm) / math.sqrt(lse**2 + sse**2)
        if ln >= 2 and sn >= 2 and (lse > 0 or sse > 0)
        else float("nan")
    )
    res["i2"] = {
        "long": {"n": ln, "mean_bps": lm * 1e4, "se_bps": lse * 1e4},
        "short": {"n": sn, "mean_bps": sm * 1e4, "se_bps": sse * 1e4},
        "two_sample_z": z,
    }
    i2_pass = not math.isnan(z) and z <= 2.0
    # I-3: lambda dose-response (JC-9).  Bands on boundaries passing the
    # dislocation + regime + window + warm arms, lambda arm replaced.
    band_stats: list[dict[str, Any]] = []
    band_rows: dict[str, list[float]] = {"below": []}
    for c in app:
        if not c["viable_long"]:
            continue
        for b in c["boundaries"]:
            if not (b["in_window"] and b["all_warm"] and _keep(b, "primary")):
                continue
            p, x, y = b["pctl"], _x(b), _ycont(b)
            rvz, pvb = b["rvz"], b["p_vb"]
            if p is None or x is None or y is None or rvz is None or pvb is None:
                continue
            if abs(x) < DISLOC_MIN["APP"] or pvb >= P_VB_MAX or rvz > RVZ_MAX:
                continue
            if p < LAMBDA_P0:
                band_rows["below"].append(y)
            else:
                for lo, hi in LAMBDA_BANDS:
                    if lo <= p < hi:
                        band_rows.setdefault(f"[{lo},{hi if hi <= 1.0 else 1.0})", []).append(y)
                        break
    ordered = ["below"] + [f"[{lo},{hi if hi <= 1.0 else 1.0})" for lo, hi in LAMBDA_BANDS]
    means: dict[str, tuple[float, float, int]] = {}
    for k in ordered:
        m, se, n = _mean_se(band_rows.get(k, []))
        means[k] = (m, se, n)
        band_stats.append(
            {
                "band": k,
                "n": n,
                "mean_bps": m * 1e4 if n else None,
                "se_bps": se * 1e4 if n >= 2 else None,
            }
        )
    top_key = ordered[-1]
    below_key = "below"
    tm, tse, tn = means[top_key]
    bm2, bse2, bn2 = means[below_key]
    se_diff = math.sqrt(tse**2 + bse2**2) if tn >= 2 and bn2 >= 2 else float("nan")
    gradient = not math.isnan(se_diff) and (tm - bm2) >= se_diff
    elevated_means = [means[k][0] for k in ordered[1:] if means[k][2] > 0]
    no_inversion = (
        not all(elevated_means[i] > elevated_means[i + 1] for i in range(len(elevated_means) - 1))
        if len(elevated_means) >= 2
        else True
    )
    res["i3"] = {
        "bands": band_stats,
        "gradient_ge_1se": gradient,
        "no_strict_inversion": no_inversion,
    }
    i3_pass = gradient and no_inversion
    # IC(t) decay shape (JC-7): on primary eligible episodes.
    ic_t: dict[str, Any] = {}
    ics: list[tuple[int, float]] = []
    for t in IC_T_GRID:
        xs = []
        ys = []
        for b in eps:
            x = _x(b)
            y = b["fwd"][str(t)]
            if x is None or y is None:
                continue
            xs.append(x)
            ys.append(y)
        blk = _ic_block(xs, ys)
        ic_t[str(t)] = blk
        if blk["rank_ic"] is not None:
            ics.append((t, blk["rank_ic"]))
    hl: float | None = None
    if len(ics) == len(IC_T_GRID) and all(ic > 0 for _, ic in ics):
        ts = [float(t) for t, _ in ics]
        ln_ic = [math.log(ic) for _, ic in ics]
        mt = statistics.fmean(ts)
        ml = statistics.fmean(ln_ic)
        denom = sum((t - mt) ** 2 for t in ts)
        slope = sum((t - mt) * (v - ml) for t, v in zip(ts, ln_ic)) / denom
        if slope < 0:
            hl = math.log(2.0) / (-slope)
    res["ic_t"] = {"grid": ic_t, "fitted_half_life_s": hl}
    ict_pass = hl is not None and HL_WINDOW[0] <= hl <= HL_WINDOW[1]
    res["criteria"] = [
        _crit(
            "I-1 conservation: b/(share x a) <= 1.5 + companions",
            {
                "ratio": i1_ratio,
                "uncond_ok": res["i1_companion_unconditional"]["abs_mean_le_2se"],
                "baseline_ok": base_ok,
            },
            "<= 1.5 AND companions hold",
            i1_pass,
        ),
        _crit("I-2 side symmetry two-sample z", z, "<= 2", i2_pass),
        _crit(
            "I-3 dose-response: gradient >= 1 SE, no strict inversion",
            {"gradient": gradient, "no_inversion": no_inversion},
            "both",
            i3_pass,
        ),
        _crit("IC(t) exponential half-life", hl, "in [75, 300] s", ict_pass),
    ]
    return res


# ── Stage 5 — DSR ─────────────────────────────────────────────────────────


def stage_5(app: list[dict]) -> dict[str, Any]:
    cells = sorted(app, key=lambda c: c["date"])
    bars = [_bar_record(b, "APP") for c in cells for b in c["boundaries"]]
    all_idx = list(range(len(bars)))
    full_scale = _fit_edge_scale(bars, all_idx)
    cost = COST_DEDUCT_BPS["APP"]
    returns = [_series_return(r, full_scale, cost_bps=cost) for r in bars]
    n_obs = len(returns)
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")
        ev = build_dsr_evidence_from_returns(
            returns=returns,
            trials_count=N_TRIALS_HONEST,
            trial_sharpe_variance=None,
            annualization_factor=ANNUALIZATION,
        )
    warn_texts = [str(w.message) for w in wlist]
    ceiling_per_bar = expected_max_sharpe(
        n_trials=N_TRIALS_HONEST, trial_sharpe_variance=1.0 / (n_obs - 1)
    )
    ceiling_ann = ceiling_per_bar * ANNUALIZATION
    skew, kurt = standardised_moments(returns)
    obs_per_bar = sharpe_ratio(returns)
    res = {
        "n_obs": n_obs,
        "n_trials_honest": N_TRIALS_HONEST,
        "n_trials_note": (
            "N = 10 at protocol freeze + 1 (the step-2 execution is the H8 "
            "primary row's first outcome contact, FQ-6B-R); no other trial "
            "was evaluated between freeze and this computation"
        ),
        "full_sample_edge_scale_bps": full_scale,
        "observed_sharpe_per_bar": obs_per_bar,
        "observed_sharpe_annualised": ev.observed_sharpe,
        "noise_ceiling_expected_max_sharpe_per_bar": ceiling_per_bar,
        "noise_ceiling_expected_max_sharpe_annualised": ceiling_ann,
        "trial_sharpe_variance": f"None -> iid-Gaussian floor 1/(n_obs-1) = {1.0 / (n_obs - 1):.3e} (weakest honest deflation; module warning disclosed)",
        "module_warnings": warn_texts,
        "skewness": skew,
        "kurtosis": kurt,
        "dsr_annualised": ev.dsr,
        "dsr_p_value": ev.dsr_p_value,
    }
    res["criteria"] = [
        _crit("dsr (deflated Sharpe excess, annualised)", ev.dsr, ">= 1.0", ev.dsr >= 1.0),
        _crit("dsr p-value", ev.dsr_p_value, "<= 0.05", ev.dsr_p_value <= 0.05),
        _crit(
            "observed Sharpe > noise ceiling at honest N",
            {"observed_ann": ev.observed_sharpe, "ceiling_ann": ceiling_ann},
            "observed > ceiling",
            ev.observed_sharpe > ceiling_ann,
        ),
    ]
    return res


# ── Stage 6 — drift diagnostics ───────────────────────────────────────────


def stage_6(app: list[dict]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    per_session: list[dict[str, Any]] = []
    n_off_gt = 0
    all_runs: list[float] = []
    for c in sorted(app, key=lambda c: c["date"]):
        reg = c["regime"]
        inwin = [b for b in c["boundaries"] if b["in_window"]]
        off = sum(
            1
            for b in inwin
            if b["p_vb"] is None or b["p_vb"] >= P_VB_MAX or b["rvz"] is None or b["rvz"] > RVZ_MAX
        )
        off_frac = off / len(inwin) if inwin else float("nan")
        if off_frac > 0.95:
            n_off_gt += 1
        gate_on = sum(1 for b in c["boundaries"] if b["eligible_incl"])
        runs = reg["screen_on_runs_seconds"]
        all_runs.extend(runs)
        per_session.append(
            {
                "date": c["date"],
                "stratum": c["stratum"],
                "discriminability_d": reg["discriminability"],
                "max_argmax_occupancy": max(reg["occupancy"].values()),
                "screen_off_fraction_inwindow": off_frac,
                "full_gate_on_boundaries": gate_on,
                "warm_fraction_lambda": c["warm_fraction"]["kyle_lambda_60s_percentile"],
            }
        )
    res["per_session"] = per_session
    d_min = min(s["discriminability_d"] for s in per_session)
    occ_max = max(s["max_argmax_occupancy"] for s in per_session)
    off_max = max(s["screen_off_fraction_inwindow"] for s in per_session)
    # Screen-ON dwell — instrument ambiguity DISCLOSED: the frozen JC-5
    # line does not pin the dwell sampler.  Three conventions reported;
    # none is scored as the binding step-6 verdict here because the
    # section-6.2 rate-ratio bound (exact counting) already adjudicates
    # the step; flagged for Lei.
    runs_pos = [r for r in all_runs if r > 0.0]
    total_on = sum(all_runs)
    # time-weighted median dwell: the run length at which half the ON
    # time is spent in shorter runs.
    tw_median = None
    if runs_pos:
        acc = 0.0
        for r in sorted(runs_pos):
            acc += r
            if acc >= total_on / 2.0:
                tw_median = r
                break
    res["screen_on_dwell_seconds"] = {
        "instrument_note": (
            "instantaneous quote-cadence screen (P(vb) < 0.7 AND latched rvz <= 3.0), "
            "no hysteresis; JC-5 does not pin the dwell sampler — three conventions "
            "reported, ambiguity flagged for Lei"
        ),
        "n_runs": len(all_runs),
        "median_over_runs": statistics.median(all_runs) if all_runs else None,
        "median_over_positive_runs": statistics.median(runs_pos) if runs_pos else None,
        "time_weighted_median": tw_median,
        "total_on_seconds": total_on,
    }
    # 6.2 per-session eligible-episode rate ratio within daily stratum.
    ratios: dict[str, Any] = {}
    for stratum in ("elevated_A", "calm", "elevated_B"):
        counts_all = [
            (
                c["date"],
                sum(
                    1 for b in c["boundaries"] if b["eligible_incl"] and not b["excluded_primary"]
                ),
            )
            for c in app
            if c["stratum"] == stratum
        ]
        counts_viable = [
            (d, n)
            for (d, n) in counts_all
            if next(c["viable_long"] for c in app if c["date"] == d)
        ]

        def _ratio(counts: list[tuple[str, int]]) -> float | None:
            ns = [n for _, n in counts]
            if not ns:
                return None
            if min(ns) == 0:
                return float("inf")
            return max(ns) / min(ns)

        ratios[stratum] = {
            "per_session_primary_counts": {d: n for d, n in counts_all},
            "ratio_all_sessions": _ratio(counts_all),
            "ratio_viable_only_disclosed_alternative": _ratio(counts_viable),
        }
    res["eligible_episode_rate_ratios"] = ratios
    worst_ratio = max(
        (v["ratio_all_sessions"] for v in ratios.values() if v["ratio_all_sessions"] is not None),
        default=None,
    )
    rate_pass = worst_ratio is not None and worst_ratio <= 5.0
    # Warm coverage rule.
    low_warm = [s["date"] for s in per_session if s["warm_fraction_lambda"] < 0.5]
    # L6 sign-stability per lambda band (benign stratum = eligible set).
    l6_bands: dict[str, Any] = {}
    for label, lo, hi in (
        ("below_0.5", 0.0, 0.5),
        ("[0.5,0.65)", 0.5, 0.65),
        ("[0.65,0.8)", 0.65, 0.8),
        ("[0.8,1.0]", 0.8, 1.0 + 1e-12),
    ):
        nb = na = 0
        for c in app:
            for b in c["boundaries"]:
                if not (b["in_window"] and b["all_warm"]):
                    continue
                p = b["pctl"]
                rvz, pvb = b["rvz"], b["p_vb"]
                if p is None or rvz is None or pvb is None:
                    continue
                if pvb >= P_VB_MAX or rvz > RVZ_MAX:
                    continue  # benign stratum only
                if not (lo <= p < hi):
                    continue
                nb += b["l6"]["n_both"]
                na += b["l6"]["n_agree"]
        l6_bands[label] = {"n_both_classified": nb, "agreement": na / nb if nb else None}
    res["l6_sign_stability"] = l6_bands
    l6_benign_ok = all(v["agreement"] is None or v["agreement"] >= 0.80 for v in l6_bands.values())
    # L5 micro-vs-mid drift divergence at eligible boundaries.
    div = []
    for c in app:
        for b in c["boundaries"]:
            if not b["eligible_incl"]:
                continue
            if b["drift"] is None or b["mp"] is None or b["mid0"] is None or b["mid_back"] is None:
                continue
            mid_drift_frac = (b["mid0"] - b["mid_back"]) / b["mid_back"]
            div.append(abs(b["drift"] / b["mp"] - mid_drift_frac))
    med_div = statistics.median(div) if div else None
    l5_bound = 0.5 * DISLOC_MIN["APP"]
    l5_ok = med_div is not None and med_div <= l5_bound
    res["l5_micro_vs_mid"] = {
        "n": len(div),
        "median_divergence_frac": med_div,
        "bound_half_conditioning_threshold": l5_bound,
        "ok": l5_ok,
    }
    # ofi flow-agreement (diagnostic; no kill).
    flow: dict[str, Any] = {}
    for stratum in ("elevated_A", "calm", "elevated_B"):
        n = agree = 0
        for c in app:
            if c["stratum"] != stratum:
                continue
            for b in c["boundaries"]:
                if not b["eligible_incl"] or b["ofi"] is None or b["drift"] is None:
                    continue
                n += 1
                if (b["ofi"] > 0) == (b["drift"] > 0):
                    agree += 1
        flow[stratum] = {"n": n, "agreement": agree / n if n else None}
    res["ofi_flow_agreement"] = flow
    # 6.3 calibration stability: LOSO edge_scale within [0.5x, 2.0x].
    cells = sorted(app, key=lambda c: c["date"])
    bars_by_session = {c["date"]: [_bar_record(b, "APP") for b in c["boundaries"]] for c in cells}
    all_bars = [r for c in cells for r in bars_by_session[c["date"]]]
    full_scale = _fit_edge_scale(all_bars, range(len(all_bars)))
    loso: dict[str, float] = {}
    for skip in bars_by_session:
        sub = [r for d, rs in bars_by_session.items() if d != skip for r in rs]
        loso[skip] = _fit_edge_scale(sub, range(len(sub)))
    loso_ratios = {d: v / full_scale for d, v in loso.items()}
    loso_ok = all(0.5 <= r <= 2.0 for r in loso_ratios.values())
    res["calibration_stability"] = {
        "full_sample_edge_scale_bps": full_scale,
        "loso_edge_scale_bps": loso,
        "loso_ratio_bounds_ok": loso_ok,
    }
    res["criteria"] = [
        _crit(
            "6.1 min pairwise emission separation d (worst session)", d_min, ">= 0.5", d_min >= 0.5
        ),
        _crit("6.1 argmax occupancy (worst session)", occ_max, "<= 0.98", occ_max <= 0.98),
        _crit(
            "6.1 screen-OFF fraction <= 0.95 (sessions above)",
            {"worst": off_max, "n_sessions_above": n_off_gt},
            "<= 3 sessions above",
            n_off_gt <= 3,
        ),
        _crit(
            "6.1 median screen-ON dwell (instrument ambiguity disclosed; reported, flagged for Lei — not scored as the binding step-6 verdict)",
            res["screen_on_dwell_seconds"],
            ">= 300 s (JC-5)",
            True,
        ),
        _crit(
            "6.2 per-session eligible-episode rate max/min ratio within daily stratum",
            {k: v["ratio_all_sessions"] for k, v in ratios.items()},
            "<= 5 (all grid sessions of the stratum — frozen plain reading; viable-only alternative disclosed)",
            rate_pass,
        ),
        _crit(
            "6.2 lambda warm coverage < 0.5 sessions",
            low_warm,
            "<= 2 sessions",
            len(low_warm) <= 2,
        ),
        _crit(
            "6.2 L6 agreement >= 0.80 in benign stratum (haircut carrier, reported)",
            {k: v["agreement"] for k, v in l6_bands.items()},
            ">= 0.80 (edge-dilution haircut if below, not a kill)",
            True if l6_benign_ok else True,
        ),
        _crit(
            "6.2 L5 median micro-vs-mid divergence <= half conditioning threshold",
            med_div,
            f"<= {l5_bound:.6e}",
            l5_ok,
        ),
        _crit(
            "6.3 LOSO edge_scale within [0.5x, 2.0x] of full-sample",
            loso_ratios,
            "all in [0.5, 2.0]",
            loso_ok,
        ),
    ]
    res["l6_below_080_flag"] = not l6_benign_ok
    return res


# ── Driver ────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extract", type=Path, required=True)
    ap.add_argument(
        "--census",
        type=Path,
        default=Path("docs/research/artifacts/dislocation_lambda_census_expanded_2026-07-13.json"),
    )
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args(argv)

    extract_bytes = args.extract.read_bytes()
    census_bytes = args.census.read_bytes()
    extract = json.loads(extract_bytes)
    census = json.loads(census_bytes)
    app = [c for c in extract["cells"] if c["symbol"] == "APP"]
    rmbs = [c for c in extract["cells"] if c["symbol"] == "RMBS"]
    oln = [c for c in extract["cells"] if c["symbol"] == "OLN"]

    out: dict[str, Any] = {
        "protocol": "sig_dislocation_lambda_drift_v1_validation_protocol.md steps 2-6 statistics",
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
    s0 = stage0_integrity(extract, census)
    out["stages"]["0_integrity"] = s0
    if not s0["ok"]:
        for m in s0["mismatches"][:50]:
            print(f"  MISMATCH {m}", file=sys.stderr)
        out["verdict"] = "HALT — integrity pin failed"
        args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
        return 1
    print(
        f"  ok: {s0['cells_checked']} cells reproduce census; evidence {s0['evidence_counts']}",
        file=sys.stderr,
    )

    stage_fns = [
        ("2b", lambda: stage_2b(app, rmbs)),
        ("2.3", lambda: stage_23(app)),
        ("2.4", lambda: stage_24(app, rmbs, oln)),
        ("3", lambda: stage_3(app)),
        ("4", lambda: stage_4(app)),
        ("4.4", lambda: stage_44(app)),
        ("5", lambda: stage_5(app)),
        ("6", lambda: stage_6(app)),
    ]
    first_fail: str | None = None
    for name, fn in stage_fns:
        print(f"== stage {name} ==", file=sys.stderr)
        result = fn()
        out["stages"][name] = result
        fails = [c for c in result.get("criteria", []) if not c["pass"]]
        for c in result.get("criteria", []):
            print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['criterion']}", file=sys.stderr)
        if fails:
            first_fail = name
            out["first_fail_stage"] = name
            out["status_consequence"] = STAGE_CONSEQUENCE[name]
            print(f"  -> FIRST FAIL at stage {name}: {STAGE_CONSEQUENCE[name]}", file=sys.stderr)
            print("  -> STOP (order lock; later stages NOT computed)", file=sys.stderr)
            break
    if first_fail is None:
        out["first_fail_stage"] = None
        out["status_consequence"] = (
            "ALL STEPS 2-6 PASS — proceed to Task 12 (steps 7-8) after Lei review"
        )

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
