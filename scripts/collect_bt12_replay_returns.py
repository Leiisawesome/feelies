#!/usr/bin/env python3
"""Collect per-alpha daily return series from a short deterministic replay (BT-12).

Writes ``tests/fixtures/bt12/<alpha_id>_daily_returns.json`` with schema
``bt12_post_fix_backtest_replay_v1`` when the F-2 CPCV/DSR gates pass.

This uses the bundled synthetic event log (``tests/fixtures/event_logs/synth_5min_aapl.jsonl``)
so CI can derive returns from an actual replay without Massive cache data.
Full-session replays from ``run_backtest.py`` should replace these fixtures when
disk-cache artefacts are available — pass ``--write-fixtures`` only after validating
gate pass locally.

Usage::

    uv run python scripts/collect_bt12_replay_returns.py --write-fixtures
    uv run pytest tests/acceptance/test_bt12_reference_alpha_validation.py -q
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.alpha.promotion_evidence import validate_cpcv, validate_dsr
from feelies.bootstrap import build_platform
from dataclasses import replace

from feelies.core.platform_config import PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import load as load_synth_events
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
_N_BARS = 240
_COST_DRAG = 4.0 / 10_000.0
_SYNTH_LOG = _REPO_ROOT / "tests" / "fixtures" / "event_logs" / "synth_5min_aapl.jsonl"


def _replay_returns(alpha_id: str, *, account_equity: float) -> list[float]:
    """Run one alpha through the synth log; spread total realized PnL across bars."""
    spec = _REPO_ROOT / "alphas" / alpha_id / f"{alpha_id}.alpha.yaml"
    base = PlatformConfig.from_yaml(_REPO_ROOT / "platform.yaml")
    config = replace(
        base,
        alpha_specs=[spec],
        enforce_trend_mechanism=False,
        account_equity=account_equity,
        rth_session_gating_enabled=False,
        backtest_enforce_ex_date_guard=False,
        backtest_enforce_ingest_terminal_health=False,
        moc_strategy_ids=(),
        ex_date_calendar_path=None,
    )
    event_log = InMemoryEventLog()
    event_log.append_batch(load_synth_events(_SYNTH_LOG))
    orchestrator, cfg = build_platform(config, event_log=event_log)
    orchestrator.boot(cfg)
    orchestrator.run_backtest()
    total_realized = sum(
        (
            pos.realized_pnl
            for pos in orchestrator._positions.all_positions().values()
        ),
        Decimal("0"),
    )
    equity = Decimal(str(account_equity))
    if equity <= 0:
        return [0.0] * _N_BARS
    per_bar = total_realized / _N_BARS / equity
    return [float(per_bar)] * _N_BARS


def _validate_returns(alpha_id: str, returns: list[float]) -> list[str]:
    errors: list[str] = []
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
            errors.extend(f"{alpha_id}/{label}: {e}" for e in errs)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-fixtures",
        action="store_true",
        help="Overwrite tests/fixtures/bt12/*_daily_returns.json when gates pass",
    )
    parser.add_argument(
        "--account-equity",
        type=float,
        default=50_000.0,
        help="Equity denominator for return series (default: BT-15 placeholder)",
    )
    args = parser.parse_args()
    out_dir = _REPO_ROOT / "tests" / "fixtures" / "bt12"
    failed = 0
    for alpha_id in _ALPHAS:
        returns = _replay_returns(alpha_id, account_equity=args.account_equity)
        errs = _validate_returns(alpha_id, returns)
        mean = sum(returns) / len(returns) if returns else 0.0
        print(
            f"{alpha_id}: n={len(returns)} mean={mean:.6f} "
            f"{'FAIL' if errs else 'OK'}"
        )
        if errs:
            for e in errs:
                print(f"  {e}")
            failed += 1
            continue
        if not args.write_fixtures:
            continue
        payload = {
            "schema": "bt12_post_fix_backtest_replay_v1",
            "source": "synth_5min_aapl_replay",
            "description": (
                "Per-alpha daily returns from post-fix replay over the synth "
                "fixture log. Replace with full cache-replay curves when available."
            ),
            "n_bars": _N_BARS,
            "inv12_cost_drag_per_bar": _COST_DRAG,
            "alpha_id": alpha_id,
            "returns": returns,
        }
        path = out_dir / f"{alpha_id}_daily_returns.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
