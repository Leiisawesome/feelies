from __future__ import annotations

import csv
import json
from pathlib import Path

from feelies.health import load_health_config, run_alpha_health_check_from_directory, run_and_write_reports


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _base_metadata(alpha: str) -> dict[str, object]:
    return {
        "alpha_name": alpha,
        "universe": ["AAA", "BBB", "CCC"],
        "timeframe": "2024-01-01/2024-06-30",
        "data_source": "synthetic",
        "prediction_horizon": "5m",
        "execution_assumption": "limit_at_mid_with_latency",
        "cost_assumption": "1bp_fee_plus_half_spread",
        "run_timestamp_ns": 1_700_000_000_000_000_000,
        "git_commit_hash": "deadbeef",
        "entry_rule": "rank_cross_section",
        "exit_rule": "horizon_exit",
    }


def _synthetic_signals(n: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(n):
        base = float(i) * 1e-7
        sig = base + float(i % 3) * 1e-9
        y = base + float(i % 3) * 5e-9
        rows.append(
            {
                "timestamp": 1_700_000_000_000_000_000 + i * 1_000_000,
                "symbol": ["AAA", "BBB", "CCC"][i % 3],
                "signal": sig,
                "forward_return": y,
                "decision_timestamp": 1_700_000_000_000_000_000 + i * 1_000_000,
                "feature_timestamp": 1_700_000_000_000_000_000 + i * 1_000_000 - 500_000,
                "target_timestamp": 1_700_000_000_000_000_000 + i * 1_000_000 + 5_000_000,
                "date": f"2024-01-{(i % 28) + 1:02d}",
            }
        )
    return rows


def _synthetic_trades() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for i in range(400):
        out.append(
            {
                "timestamp": 1_700_000_000_000_000_000 + i * 25_000_000,
                "symbol": ["AAA", "BBB", "CCC"][i % 3],
                "spread_bps": 1.0 + (i % 5) * 0.1,
                "realized_vol": 0.02 + (i % 7) * 0.001,
                "net_pnl": 0.5 if i % 19 != 0 else -0.2,
            }
        )
    return out


def test_good_alpha_paper_or_deploy(tmp_path: Path) -> None:
    root = tmp_path / "good"
    root.mkdir()
    cfg_path = _repo_root() / "configs/health/default.yaml"
    cfg = load_health_config(cfg_path)
    _write_json(root / "metadata.json", _base_metadata("good_alpha"))
    signals = _synthetic_signals(1500)
    _write_csv(
        root / "signals.csv",
        fieldnames=list(signals[0].keys()),
        rows=signals,
    )
    trades = _synthetic_trades()
    _write_csv(root / "trades.csv", fieldnames=list(trades[0].keys()), rows=trades)
    exec_payload = {
        "mid": {"net_pnl": 2500.0, "gross_pnl": 4000.0, "net_sharpe": 1.3},
        "executable": {
            "net_pnl": 1200.0,
            "gross_pnl": 3200.0,
            "net_sharpe": 1.1,
            "avg_gross_edge_per_trade": 4.0,
            "avg_cost_per_trade": 1.0,
        },
        "conservative": {
            "net_pnl": 900.0,
            "gross_pnl": 3000.0,
            "net_sharpe": 0.9,
            "avg_gross_edge_per_trade": 3.5,
            "avg_cost_per_trade": 1.2,
        },
    }
    _write_json(root / "execution_variants.json", exec_payload)
    pnl_rows = [{"date": f"2024-01-{(i % 28) + 1:02d}", "pnl": 5.0 + (i % 3)} for i in range(120)]
    _write_csv(root / "pnl.csv", fieldnames=["date", "pnl"], rows=pnl_rows)

    report = run_alpha_health_check_from_directory(root, config=cfg)
    assert report.decision.value in {"PAPER_TRADE", "DEPLOY_SMALL", "SCALE_CANDIDATE"}


def test_leakage_kill(tmp_path: Path) -> None:
    root = tmp_path / "leak"
    root.mkdir()
    meta = _base_metadata("leak")
    meta["feature_names"] = ["future_return_rank"]
    _write_json(root / "metadata.json", meta)
    signals = _synthetic_signals(1200)
    _write_csv(root / "signals.csv", fieldnames=list(signals[0].keys()), rows=signals)
    report = run_alpha_health_check_from_directory(root)
    assert report.decision.value == "KILL"


def test_mid_only_not_pass_execution(tmp_path: Path) -> None:
    root = tmp_path / "mid"
    root.mkdir()
    _write_json(root / "metadata.json", _base_metadata("mid_only"))
    signals = _synthetic_signals(1200)
    _write_csv(root / "signals.csv", fieldnames=list(signals[0].keys()), rows=signals)
    _write_json(root / "execution_variants.json", {"mid": {"net_pnl": 500.0, "net_sharpe": 1.2}})
    report = run_alpha_health_check_from_directory(root)
    exec_results = [r for r in report.results if r.category == "cost_execution_survival"]
    assert any(r.status.value == "FAIL" for r in exec_results)
    assert report.decision.value != "DEPLOY_SMALL"


def test_negative_net_kill(tmp_path: Path) -> None:
    root = tmp_path / "neg"
    root.mkdir()
    _write_json(root / "metadata.json", _base_metadata("neg"))
    signals = _synthetic_signals(1200)
    _write_csv(root / "signals.csv", fieldnames=list(signals[0].keys()), rows=signals)
    _write_json(
        root / "execution_variants.json",
        {
            "conservative": {
                "net_pnl": -400.0,
                "gross_pnl": 50.0,
                "net_sharpe": -0.8,
                "avg_gross_edge_per_trade": 1.0,
                "avg_cost_per_trade": 3.0,
            }
        },
    )
    report = run_alpha_health_check_from_directory(root)
    assert report.decision.value == "KILL"


def test_concentration_warning(tmp_path: Path) -> None:
    root = tmp_path / "conc"
    root.mkdir()
    _write_json(root / "metadata.json", _base_metadata("conc"))
    signals = _synthetic_signals(1200)
    _write_csv(root / "signals.csv", fieldnames=list(signals[0].keys()), rows=signals)
    trades = []
    for i in range(300):
        trades.append(
            {
                "timestamp": 1_700_000_000_000_000_000 + i * 20_000_000,
                "symbol": "AAA" if i == 0 else "BBB",
                "spread_bps": 1.2,
                "net_pnl": 1000.0 if i == 0 else 0.01,
            }
        )
    _write_csv(root / "trades.csv", fieldnames=list(trades[0].keys()), rows=trades)
    _write_json(
        root / "execution_variants.json",
        {
            "conservative": {
                "net_pnl": 200.0,
                "gross_pnl": 400.0,
                "net_sharpe": 0.7,
                "avg_gross_edge_per_trade": 2.0,
                "avg_cost_per_trade": 0.7,
            }
        },
    )
    report = run_alpha_health_check_from_directory(root)
    risk_msgs = [r for r in report.results if r.category == "risk_drawdown"]
    assert any("symbol" in r.check_name for r in risk_msgs)


def test_missing_artifacts_soft_fail(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    _write_json(root / "metadata.json", {"alpha_name": "ghost"})
    report = run_alpha_health_check_from_directory(root)
    assert report.results
    assert report.decision.value in {"KILL", "RESEARCH_MORE"}


def test_report_files_written(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    _write_json(root / "metadata.json", _base_metadata("writer"))
    signals = _synthetic_signals(1200)
    _write_csv(root / "signals.csv", fieldnames=list(signals[0].keys()), rows=signals)
    _write_json(
        root / "execution_variants.json",
        {
            "conservative": {
                "net_pnl": 50.0,
                "gross_pnl": 120.0,
                "net_sharpe": 0.6,
                "avg_gross_edge_per_trade": 2.0,
                "avg_cost_per_trade": 0.8,
            }
        },
    )
    out_dir = tmp_path / "reports"
    _, paths = run_and_write_reports(
        out_dir=out_dir,
        run_dir=root,
        write_json=True,
        write_markdown=True,
        write_csv=True,
    )
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    assert paths["csv"].is_file()


def test_cli_strict_exit_code(tmp_path: Path) -> None:
    from argparse import Namespace

    from feelies.cli.health_check import handle

    root = tmp_path / "strict"
    root.mkdir()
    _write_json(root / "metadata.json", {"alpha_name": "bad"})
    ns = Namespace(
        backtest_output=root,
        alpha=None,
        config=None,
        out_dir=root / "health_out",
        format="json",
        strict=True,
    )
    code = handle(ns)
    assert code != 0
