"""Unit tests for H10 step-2 validation instruments (no DiskEventCache).

Pure helpers + stage-0 shape smoke on synthetic extract/census payloads.
"""

from __future__ import annotations

from scripts.research.sweep_kyle_drift_validation_extract import (
    FWD_HORIZONS_S,
    _fwd_log_return,
)
from scripts.research.sweep_kyle_drift_validation_stats import (
    POOLED_VIABLE_EXPECTED,
    STAGE0_FIELDS,
    _ycont,
    contrast_material,
    primary_eligible,
    stage0_integrity,
    stage_2b,
)


def test_fwd_horizons_match_protocol() -> None:
    assert FWD_HORIZONS_S == (120, 300, 900, 1800)


def test_fwd_log_return_zero_move_is_zero_not_none() -> None:
    ns = 1_000_000_000
    quote_ts = [0, ns, 2 * ns, 3 * ns]
    mid = [100.0, 100.0, 100.0, 100.0]
    y = _fwd_log_return(quote_ts, mid, ns, 1)
    assert y == 0.0


def test_fwd_log_return_missing_future_is_none() -> None:
    quote_ts = [0, 1_000_000_000]
    mid = [100.0, 101.0]
    assert _fwd_log_return(quote_ts, mid, 0, 900) is None


def test_ycont_matches_sfi_sign() -> None:
    assert _ycont({"fwd": {"900": 0.01}, "sfi": 0.5}) == 0.01
    assert _ycont({"fwd": {"900": 0.01}, "sfi": -0.5}) == -0.01
    assert _ycont({"fwd": {"900": None}, "sfi": 0.5}) is None
    assert _ycont({"fwd": {"900": 0.01}, "sfi": 0.0}) is None


def test_contrast_material_elevated_vs_baseline() -> None:
    c, mat = contrast_material([2.0, 2.2, 2.1, 2.3], [1.0, 1.1, 0.9, 1.0])
    assert c is not None and c > 0 and mat is True
    c2, mat2 = contrast_material([1.0, 1.0], [2.0, 2.0])
    assert c2 is not None and c2 < 0 and mat2 is False


def test_primary_eligible_viable_long_only() -> None:
    cells = [
        {
            "symbol": "APP",
            "viable_long": True,
            "boundaries": [
                {"eligible": True, "side": "LONG"},
                {"eligible": False, "side": None},
            ],
        },
        {
            "symbol": "APP",
            "viable_long": False,
            "boundaries": [{"eligible": True, "side": "SHORT"}],
        },
    ]
    eps = primary_eligible(cells)
    assert len(eps) == 1
    assert eps[0][1]["side"] == "LONG"


def _bnd(
    *,
    eligible: bool = False,
    side: str | None = None,
    sfi: float = 0.5,
    sfi_pctl: float = 0.95,
    fwd900: float = 0.001,
    in_window: bool = True,
    all_warm: bool = True,
    kyle_pctl: float | None = 0.8,
    vol: float = 1000.0,
) -> dict:
    return {
        "eligible": eligible,
        "side": side,
        "sfi": sfi,
        "sfi_pctl": sfi_pctl,
        "fwd": {"120": 0.0, "300": 0.0, "900": fwd900, "1800": 0.0},
        "in_window": in_window,
        "all_warm": all_warm,
        "kyle_lambda_60s_percentile": kyle_pctl,
        "print_volume_900s": vol,
    }


def test_stage0_integrity_shape_and_pooled_expectation() -> None:
    """Synthetic pin: matching fields + pooled 152; mismatch halts ok=False."""
    assert POOLED_VIABLE_EXPECTED == 152
    assert "episodes" in STAGE0_FIELDS

    def _cell(sym: str, date: str, n_eps: int, *, viable: bool = True) -> dict:
        bnds = [_bnd(eligible=True, side="LONG" if i % 2 == 0 else "SHORT") for i in range(n_eps)]
        n_in = sum(1 for b in bnds if b["in_window"])
        n_warm = sum(1 for b in bnds if b["in_window"] and b["all_warm"])
        return {
            "symbol": sym,
            "date": date,
            "n_boundaries": len(bnds),
            "n_in_window": n_in,
            "n_warm_eligible": n_warm,
            "episodes": n_eps,
            "episodes_long": sum(1 for b in bnds if b["eligible"] and b["side"] == "LONG"),
            "episodes_short": sum(1 for b in bnds if b["eligible"] and b["side"] == "SHORT"),
            "sigma900_bps": 40.0,
            "viable_long": viable,
            "viable_short": viable,
            "sfi_warm_fraction_in_window": 1.0,
            "boundaries": bnds,
        }

    # Build 94 + 58 eligible on viable cells (one date each for smoke).
    app = _cell("APP", "2025-11-25", 94)
    rmbs = _cell("RMBS", "2025-11-25", 58)
    extract = {"cells": [app, rmbs]}
    census = {
        "cells": [
            {k: app[k] for k in STAGE0_FIELDS} | {"symbol": "APP", "date": "2025-11-25"},
            {k: rmbs[k] for k in STAGE0_FIELDS} | {"symbol": "RMBS", "date": "2025-11-25"},
        ]
    }
    s0 = stage0_integrity(extract, census)
    assert s0["ok"] is True
    assert s0["evidence_counts"] == {"APP": 94, "RMBS": 58, "pooled": 152}

    # Corrupt one field → fail.
    bad = {"cells": [dict(app, episodes=93), rmbs]}
    s0b = stage0_integrity(bad, census)
    assert s0b["ok"] is False
    assert any("episodes" in m for m in s0b["mismatches"])


def test_stage_2b_criteria_table_shape() -> None:
    """Synthetic continuation extreme vs null interior → criteria table length."""
    # Extreme: positive SFI → positive fwd (continuation); elevated kyle/vol.
    extreme = [
        _bnd(
            eligible=True,
            side="LONG",
            sfi=0.5 + 0.01 * i,
            sfi_pctl=0.95,
            fwd900=0.002 + 0.0001 * i,
            kyle_pctl=0.9,
            vol=5000.0,
        )
        for i in range(60)
    ] + [
        _bnd(
            eligible=True,
            side="SHORT",
            sfi=-(0.5 + 0.01 * i),
            sfi_pctl=0.05,
            fwd900=-(0.002 + 0.0001 * i),
            kyle_pctl=0.85,
            vol=4800.0,
        )
        for i in range(60)
    ]
    interior = [
        _bnd(
            eligible=False,
            sfi=0.01 * ((-1) ** i),
            sfi_pctl=0.5,
            fwd900=0.0,
            kyle_pctl=0.3,
            vol=200.0,
        )
        for i in range(40)
    ]
    cell = {
        "symbol": "APP",
        "viable_long": True,
        "boundaries": extreme + interior,
    }
    # Mirror for RMBS so pool is large enough for IC helpers.
    cell_r = {
        "symbol": "RMBS",
        "viable_long": True,
        "boundaries": [
            _bnd(
                eligible=True,
                side="LONG",
                sfi=0.6 + 0.01 * i,
                sfi_pctl=0.92,
                fwd900=0.0015 + 0.00005 * i,
                kyle_pctl=0.88,
                vol=4500.0,
            )
            for i in range(40)
        ]
        + [
            _bnd(
                eligible=False,
                sfi=0.0,
                sfi_pctl=0.4,
                fwd900=-0.0001,
                kyle_pctl=0.25,
                vol=150.0,
            )
            for _ in range(20)
        ],
    }
    res = stage_2b([cell], [cell_r])
    assert len(res["criteria"]) == 9
    assert all("n_class" in c and "pass" in c for c in res["criteria"])
    assert res["n_extreme"] == 160  # 120 APP + 40 RMBS
    # Diagnostic criterion always passes.
    diag = next(c for c in res["criteria"] if "per-symbol" in c["criterion"])
    assert diag["pass"] is True
