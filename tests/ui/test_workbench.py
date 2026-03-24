from __future__ import annotations

from feelies.ui.workbench import BacktestRunRequest, load_workbench_bootstrap, run_workbench


def test_load_workbench_bootstrap_surfaces_mode_capabilities() -> None:
    bootstrap = load_workbench_bootstrap("platform.yaml")

    assert bootstrap["capabilities"]["BACKTEST"]["available"] is True
    assert bootstrap["capabilities"]["PAPER"]["available"] is False
    assert bootstrap["capabilities"]["LIVE"]["available"] is False
    assert bootstrap["config"]["exists"] is True
    assert bootstrap["alphaSpecs"]


def test_run_workbench_demo_returns_observable_snapshot() -> None:
    snapshot = run_workbench(BacktestRunRequest(demo=True))

    assert snapshot["system"]["macroState"] == "READY"
    assert snapshot["system"]["riskLevel"] == "NORMAL"
    assert snapshot["system"]["killSwitchActive"] is False

    assert snapshot["summary"]["totalEvents"] == 8
    assert snapshot["summary"]["signalsEmitted"] >= 1
    assert snapshot["summary"]["ordersFilled"] >= 1

    assert snapshot["charts"]["equityCurve"]
    assert snapshot["tables"]["orders"]
    assert snapshot["tables"]["trades"]
    assert all(item["passed"] for item in snapshot["verification"])


def test_backtest_request_payload_normalizes_symbols() -> None:
    request = BacktestRunRequest.from_payload({
        "demo": False,
        "symbols": ["aapl", " msft ", ""],
        "startDate": "2024-01-02",
        "configPath": "platform.yaml",
    })

    assert request.demo is False
    assert request.symbols == ("AAPL", "MSFT")
    assert request.start_date == "2024-01-02"
    assert request.config_path == "platform.yaml"