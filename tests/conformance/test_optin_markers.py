"""Opt-in broker/network markers and the paper-port guard.

The hook skips broker and network items unless FEELIES_BROKER_TESTS=1 or
FEELIES_NETWORK_TESTS=1. The paper guard fails closed on a live port or a
non-paper account list. Neither test opens a socket.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

_BROKER = (
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_connect_handshake_and_next_order_id",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_duplicate_submit_rejected",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_submit_buy_limit_and_cancel",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_submit_sell_limit_and_cancel",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_cancel_unknown_order_returns_false",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_two_orders_cancelled_without_cross_drain_race",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_pending_cancel_does_not_emit_spurious_ack",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_after_hours_reject_surfaces_as_rejected",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayReconnect::test_reconnect_after_clean_disconnect",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayReconnect::test_double_connect_raises",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_market_order_submit_and_cancel",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_ten_orders_rapid_submit_cancel",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_partial_fill_then_cancel",
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_fill_ack_lag_exceeds_idle_tick_interval",
    "tests/integration/test_paper_rth_e2e.py::test_cold_start_smoke",
    "tests/integration/test_paper_rth_e2e.py::test_quote_sensor_warmup",
    "tests/integration/test_paper_rth_e2e.py::test_signal_path",
    "tests/integration/test_paper_rth_e2e.py::test_shutdown_in_flight",
    "tests/integration/test_paper_rth_safety.py::test_data_gap_degrades_macro",
    "tests/integration/test_paper_rth_safety.py::test_risk_lockdown_on_force_flatten",
    "tests/integration/test_paper_rth_safety.py::test_g12_cost_exceeds_disclosure_alert",
)

_NETWORK = (
    "tests/ingestion/test_massive_functional.py::test_rest_ingest_uses_live_massive_data",
    "tests/ingestion/test_massive_functional.py::test_websocket_feed_emits_live_massive_event",
    "tests/ingestion/test_massive_functional.py::test_multi_symbol_subscribe",
    "tests/ingestion/test_massive_functional.py::test_sustained_quotes_with_idle_ticks",
    "tests/ingestion/test_parallel_ingest_integration.py::TestRawDownload::test_downloads_quotes",
    "tests/ingestion/test_parallel_ingest_integration.py::TestRawDownload::test_downloads_trades",
    "tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_events_in_chronological_order",
    "tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_contains_both_quotes_and_trades",
    "tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_sequences_are_monotonic",
    "tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_correlation_ids_are_unique",
    "tests/ingestion/test_parallel_ingest_integration.py::TestDiskCacheIntegration::test_cache_round_trip",
    "tests/ingestion/test_parallel_ingest_integration.py::TestDiskCacheIntegration::test_cache_reuse_skips_api",
    "tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_produces_contiguous_sequences",
    "tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_rebuilds_correlation_ids",
    "tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_preserves_chronological_order",
    "tests/ingestion/test_parallel_ingest_integration.py::TestMultiDayCacheResequence::test_two_days_resequenced_are_globally_monotonic",
    "tests/ingestion/test_parallel_ingest_integration.py::TestFieldFidelity::test_quote_fields_survive_pipeline",
    "tests/ingestion/test_parallel_ingest_integration.py::TestFieldFidelity::test_trade_fields_survive_pipeline",
)

_UNMARKED_NODES = (
    "tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_etradeonly_defaults_regression_unit_side",
    "tests/ingestion/test_massive_functional.py::test_normalizer_data_health_on_gap",
)

_UNMARKED_MODULES = (
    "tests.broker.ib.test_ib_connection",
    "tests.broker.ib.test_ib_router",
    "tests.broker.ib.test_next_valid_id_high_water",
    "tests.broker.ib.test_router_market_order",
)

_DUMMY = textwrap.dedent(
    """\
    import pytest

    @pytest.mark.broker
    def test_broker_optin():
        assert True

    @pytest.mark.network
    def test_network_optin():
        assert True

    @pytest.mark.functional
    def test_functional_only():
        assert True
    """
)


def _run_pytest(
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("FEELIES_BROKER_TESTS", None)
    env.pop("FEELIES_NETWORK_TESTS", None)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _dummy(tmp_path: Path) -> Path:
    path = tmp_path / "test_dummy_optin.py"
    path.write_text(_DUMMY, encoding="utf-8")
    return path


def _pytest_args(path: Path) -> list[str]:
    return [
        str(path),
        "-q",
        "-rs",
        "--rootdir",
        str(_ROOT),
        "-c",
        str(_ROOT / "pyproject.toml"),
        "-p",
        "conftest",
        "-p",
        "no:cacheprovider",
    ]


def test_optin_skips_without_flags(tmp_path: Path) -> None:
    proc = _run_pytest(_pytest_args(_dummy(tmp_path)))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "2 skipped" in out
    assert out.count("opt-in") >= 2
    assert "FEELIES_BROKER_TESTS=1" in out
    assert "FEELIES_NETWORK_TESTS=1" in out
    assert "1 passed" in out


def test_optin_flag_runs_only_the_matching_marker(tmp_path: Path) -> None:
    broker = _run_pytest(
        _pytest_args(_dummy(tmp_path)),
        extra_env={"FEELIES_BROKER_TESTS": "1"},
    )
    broker_out = broker.stdout + broker.stderr
    assert broker.returncode == 0, broker_out
    assert "2 passed" in broker_out
    assert "1 skipped" in broker_out
    assert "FEELIES_NETWORK_TESTS=1" in broker_out
    assert "FEELIES_BROKER_TESTS=1" not in broker_out

    network = _run_pytest(
        _pytest_args(_dummy(tmp_path)),
        extra_env={"FEELIES_NETWORK_TESTS": "1"},
    )
    network_out = network.stdout + network.stderr
    assert network.returncode == 0, network_out
    assert "2 passed" in network_out
    assert "1 skipped" in network_out
    assert "FEELIES_BROKER_TESTS=1" in network_out
    assert "FEELIES_NETWORK_TESTS=1" not in network_out


def test_functional_and_oracle_are_not_optin_skipped(tmp_path: Path) -> None:
    dummy = _run_pytest(_pytest_args(_dummy(tmp_path)))
    dummy_out = dummy.stdout + dummy.stderr
    assert (
        "test_functional_only" not in dummy_out or "PASSED" in dummy_out or "1 passed" in dummy_out
    )
    proc = _run_pytest(
        [
            "tests/acceptance/test_backtest_app_baseline.py",
            "--collect-only",
            "-q",
            "-m",
            "",
            "--rootdir",
            str(_ROOT),
            "-c",
            str(_ROOT / "pyproject.toml"),
            "-p",
            "conftest",
            "-p",
            "no:cacheprovider",
        ]
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "test_backtest_app_baseline.py" in out
    assert "opt-in" not in out
    assert "2 tests collected" in out or "2/2 tests collected" in out


def _mark_names(obj: object) -> set[str]:
    raw = getattr(obj, "pytestmark", ())
    if not isinstance(raw, (list, tuple)):
        raw = (raw,)
    return {str(getattr(mark, "name", "")) for mark in raw}


def _effective_marks(nodeid: str) -> set[str]:
    path, _, qual = nodeid.partition("::")
    module_name = path[:-3].replace("/", ".")
    module = importlib.import_module(module_name)
    names = set(_mark_names(module))
    obj: object = module
    if qual:
        for part in qual.split("::"):
            obj = getattr(obj, part)
            names |= _mark_names(obj)
    return names


def test_census_markers_match_the_optin_inventory() -> None:
    for nodeid in _BROKER:
        assert "broker" in _effective_marks(nodeid), nodeid
        assert "network" not in _effective_marks(nodeid), nodeid
    for nodeid in _NETWORK:
        assert "network" in _effective_marks(nodeid), nodeid
        assert "broker" not in _effective_marks(nodeid), nodeid
    for nodeid in _UNMARKED_NODES:
        marks = _effective_marks(nodeid)
        assert "broker" not in marks, nodeid
        assert "network" not in marks, nodeid
    for module_name in _UNMARKED_MODULES:
        module = importlib.import_module(module_name)
        marks = set(_mark_names(module))
        for obj in vars(module).values():
            marks |= _mark_names(obj)
        assert "broker" not in marks, module_name
        assert "network" not in marks, module_name


def test_paper_guard_ports_and_accounts() -> None:
    from _pytest.outcomes import Failed

    from tests.broker.ib._paper_guard import assert_paper_target

    for port in (4001, 7496):
        with pytest.raises(Failed):
            assert_paper_target(port, ["DU123"])
    for port in (4002, 7497):
        assert_paper_target(port, ["DU123"])
    for accounts in (["U123"], ["DU1", "U2"], []):
        with pytest.raises(Failed):
            assert_paper_target(4002, accounts)
    assert_paper_target(7497, ["DU123"])
