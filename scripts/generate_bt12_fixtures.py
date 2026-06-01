#!/usr/bin/env python3
"""Regenerate ``tests/fixtures/bt12/*_daily_returns.json`` for BT-12."""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from feelies.alpha.promotion_evidence import validate_cpcv, validate_dsr
from tests.research.test_promotion_pipeline_e2e import (
    _build_cpcv_from_returns,
    _build_dsr_from_returns,
)

_ALPHAS: tuple[str, ...] = (
    "sig_benign_midcap_v1",
    "sig_moc_imbalance_v1",
    "sig_kyle_drift_v1",
    "sig_inventory_revert_v1",
    "sig_hawkes_burst_v1",
)
_MU = 0.006
_SIGMA = 0.005
_N_BARS = 240
_COST_DRAG = 4.0 / 10_000.0


def main() -> None:
    out = _REPO_ROOT / "tests" / "fixtures" / "bt12"
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": "bt12_post_fix_backtest_surrogate_v1",
        "source": "surrogate_v1",
        "description": (
            "Per-alpha OOS daily return surrogate for BT-12 acceptance. "
            "Replace with artefact-store curves from post-fix replay when ready."
        ),
        "mu": _MU,
        "sigma": _SIGMA,
        "n_bars": _N_BARS,
        "inv12_cost_drag_per_bar": _COST_DRAG,
    }
    for alpha_id in _ALPHAS:
        seed = int(hashlib.sha256(alpha_id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        returns = [rng.gauss(_MU, _SIGMA) for _ in range(_N_BARS)]
        cpcv = _build_cpcv_from_returns(returns)
        dsr = _build_dsr_from_returns(returns)
        stressed = [r - _COST_DRAG for r in returns]
        cpcv_s = _build_cpcv_from_returns(stressed)
        for label, errs in [
            ("cpcv", validate_cpcv(cpcv)),
            ("dsr", validate_dsr(dsr)),
            ("cpcv_stress", validate_cpcv(cpcv_s)),
        ]:
            if errs:
                raise SystemExit(f"{alpha_id}: {label} failed: {errs}")
        path = out / f"{alpha_id}_daily_returns.json"
        path.write_text(
            json.dumps({**meta, "alpha_id": alpha_id, "returns": returns}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path} mean_sharpe={cpcv.mean_sharpe:.2f} dsr={dsr.dsr:.2f}")


if __name__ == "__main__":
    main()
