"""P-40 mark rail and config nodes T1-T9 (D-204)."""

from __future__ import annotations

import ast
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.errors import ConfigurationError
from feelies.core.events import MarkRailUpdate, NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.quote_quality import classify
from feelies.portfolio.mark_rail import MarkRail
from tests.conformance.test_null_alpha_conservation import _NULL_ALPHA
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_APP_YAML = Path("configs/bt_app.yaml")
_SRC = Path("src/feelies")


def _overlay(tmp_path: Path, body: str) -> Path:
    app = _APP_YAML.resolve()
    path = tmp_path / "rail.yaml"
    rel = Path(os.path.relpath(app, path.parent)).as_posix()
    path.write_text(f"extends: {rel}\n{body}", encoding="utf-8")
    return path


def _quote(
    *,
    bid: str,
    ask: str,
    sequence: int,
    exchange_timestamp_ns: int,
    bid_size: int = 100,
    ask_size: int = 200,
    symbol: str = "ABC",
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_timestamp_ns,
        correlation_id=f"p40-{sequence}",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=exchange_timestamp_ns,
    )


def _rail(*, slippage_ticks: int = 0, dwell_ns: int = 0) -> MarkRail:
    return MarkRail(
        SequenceGenerator(stream="mark_rail", thread_safe=False),
        slippage_ticks=slippage_ticks,
        dwell_ns=dwell_ns,
    )


def _on(rail: MarkRail, quote: NBBOQuote) -> MarkRailUpdate:
    return rail.on_quote(
        quote,
        quality=classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size),
    )


def test_t1_app_yaml_omits_default_rail_keys() -> None:
    config = PlatformConfig.from_yaml(_APP_YAML)
    assert config.position_rail_slippage_ticks == 0
    assert config.position_rail_dwell_ns == 0
    data = config.snapshot(ts_ns=0).data
    assert "position_rail_slippage_ticks" not in data
    assert "position_rail_dwell_ns" not in data


def test_t1_replaced_rail_keys_enter_the_snapshot() -> None:
    config = replace(
        PlatformConfig.from_yaml(_APP_YAML),
        position_rail_slippage_ticks=3,
        position_rail_dwell_ns=5,
    )
    data = config.snapshot(ts_ns=0).data
    assert data["position_rail_slippage_ticks"] == 3
    assert data["position_rail_dwell_ns"] == 5


def test_t2_negative_slippage_ticks(tmp_path: Path) -> None:
    path = _overlay(tmp_path, "position_rail_slippage_ticks: -1\n")
    with pytest.raises(ConfigurationError):
        PlatformConfig.from_yaml(path)
    config = replace(
        PlatformConfig.from_yaml(_APP_YAML),
        position_rail_slippage_ticks=-1,
    )
    with pytest.raises(ConfigurationError):
        config.validate()


def test_t2_negative_dwell_ns(tmp_path: Path) -> None:
    path = _overlay(tmp_path, "position_rail_dwell_ns: -1\n")
    with pytest.raises(ConfigurationError):
        PlatformConfig.from_yaml(path)
    config = replace(
        PlatformConfig.from_yaml(_APP_YAML),
        position_rail_dwell_ns=-1,
    )
    with pytest.raises(ConfigurationError):
        config.validate()


def test_t3_orchestrator_rail_receives_s_and_d() -> None:
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=SESSION_OPEN_NS,
        position_rail_slippage_ticks=4,
        position_rail_dwell_ns=2_000_000_000,
    )
    orchestrator, _resolved = build_platform(config, enable_position_engine=True)
    rail = orchestrator._mark_rail
    assert rail is not None
    assert rail.slippage_ticks == 4
    assert rail.dwell_ns == 2_000_000_000


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _innermost_function(tree: ast.AST, lineno: int) -> str | None:
    found: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        if node.lineno <= lineno <= end and (found is None or node.lineno >= found.lineno):
            found = node
    return None if found is None else found.name


def test_t4_one_classify_call_site_in_the_mark_path() -> None:
    """D-62: src keeps one classify call, in the orchestrator mark path."""
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "classify":
                found.append((path, node))
    assert len(found) == 1
    path, node = found[0]
    assert path.as_posix().endswith("src/feelies/kernel/orchestrator.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert _innermost_function(tree, node.lineno) == "_process_tick_inner"


def test_t5_dwelled_is_none_before_any_usable_value() -> None:
    rail = _rail(dwell_ns=1_000)
    update = _on(
        rail,
        _quote(bid="10.50", ask="10.00", sequence=1, exchange_timestamp_ns=5_000),
    )
    assert update.long.dwelled_exit_mark_cents is None
    assert update.short.dwelled_exit_mark_cents is None


def test_t5_non_valid_quote_contributes_its_held_price() -> None:
    """D-204: a non-VALID quote still in the window contributes its held price."""
    rail = _rail(dwell_ns=500)
    _on(rail, _quote(bid="1.00", ask="1.01", sequence=1, exchange_timestamp_ns=0))
    _on(rail, _quote(bid="1.10", ask="1.20", sequence=2, exchange_timestamp_ns=100))
    update = _on(
        rail,
        _quote(bid="5.00", ask="0.50", sequence=3, exchange_timestamp_ns=700),
    )
    assert update.long.dwelled_exit_mark_cents == 110
    assert update.short.dwelled_exit_mark_cents == 120


def test_t6_warmed_up_false_at_first_plus_999() -> None:
    rail = _rail(dwell_ns=1_000)
    _on(rail, _quote(bid="10.00", ask="10.01", sequence=1, exchange_timestamp_ns=10_000))
    update = _on(
        rail,
        _quote(bid="10.00", ask="10.01", sequence=2, exchange_timestamp_ns=10_999),
    )
    assert update.warmed_up is False


def test_t6_warmed_up_true_at_first_plus_1000() -> None:
    rail = _rail(dwell_ns=1_000)
    _on(rail, _quote(bid="10.00", ask="10.01", sequence=1, exchange_timestamp_ns=10_000))
    update = _on(
        rail,
        _quote(bid="10.00", ask="10.01", sequence=2, exchange_timestamp_ns=11_000),
    )
    assert update.warmed_up is True


def test_t6_warmed_up_true_at_first_quote_when_d_is_zero() -> None:
    rail = _rail(dwell_ns=0)
    update = _on(
        rail,
        _quote(bid="10.00", ask="10.01", sequence=1, exchange_timestamp_ns=10_000),
    )
    assert update.warmed_up is True


def test_t7_forced_exit_mark_offsets_worst_side_by_s() -> None:
    rail = _rail(slippage_ticks=4)
    update = _on(rail, _quote(bid="10.00", ask="10.02", sequence=1, exchange_timestamp_ns=1))
    assert update.long.worst_side_mark_cents == 1000
    assert update.short.worst_side_mark_cents == 1002
    assert update.long.forced_exit_mark_cents == 996
    assert update.short.forced_exit_mark_cents == 1006


def test_t8_non_valid_publishes_absent_held_prices_and_zero_size() -> None:
    rail = _rail()
    _on(
        rail,
        _quote(
            bid="10.00",
            ask="10.02",
            sequence=1,
            exchange_timestamp_ns=1_000,
            bid_size=100,
            ask_size=200,
        ),
    )
    update = _on(
        rail,
        _quote(
            bid="10.50",
            ask="10.00",
            sequence=2,
            exchange_timestamp_ns=1_500,
            bid_size=50,
            ask_size=60,
        ),
    )
    for side in (update.long, update.short):
        assert side.paying_side_absent is True
        assert side.valuation_side_absent is True
        assert side.paying_size == 0
        assert side.valuation_size == 0
    assert update.long.valuation_mark_cents == 1000
    assert update.long.paying_mark_cents == 1002
    assert update.short.paying_mark_cents == 1000
    assert update.short.valuation_mark_cents == 1002


def test_t9_ages_run_from_the_first_quote_until_the_first_usable_price() -> None:
    rail = _rail(dwell_ns=10_000)
    t0 = 5_000
    _on(rail, _quote(bid="10.50", ask="10.00", sequence=1, exchange_timestamp_ns=t0))
    second = _on(
        rail,
        _quote(bid="10.50", ask="10.00", sequence=2, exchange_timestamp_ns=t0 + 300),
    )
    for side in (second.long, second.short):
        assert side.paying_age_ns == 300
        assert side.valuation_age_ns == 300
        assert side.paying_absent_for_ns == 300
        assert side.valuation_absent_for_ns == 300
    third = _on(
        rail,
        _quote(bid="10.00", ask="10.02", sequence=3, exchange_timestamp_ns=t0 + 500),
    )
    for side in (third.long, third.short):
        assert side.paying_age_ns == 0
        assert side.valuation_age_ns == 0
        assert side.paying_absent_for_ns == 0
        assert side.valuation_absent_for_ns == 0


def test_t10_window_excludes_quotes_stamped_after_t() -> None:
    rail = _rail(dwell_ns=1_000)
    _on(rail, _quote(bid="10.00", ask="10.05", sequence=1, exchange_timestamp_ns=500))
    _on(rail, _quote(bid="9.90", ask="10.15", sequence=2, exchange_timestamp_ns=900))
    third = _on(rail, _quote(bid="10.00", ask="10.05", sequence=3, exchange_timestamp_ns=700))
    assert third.long.dwelled_exit_mark_cents == 1_000
    assert third.short.dwelled_exit_mark_cents == 1_005
    fourth = _on(rail, _quote(bid="10.00", ask="10.05", sequence=4, exchange_timestamp_ns=950))
    assert fourth.long.dwelled_exit_mark_cents == 990
    assert fourth.short.dwelled_exit_mark_cents == 1_015


def test_t10_clean_ignores_quotes_stamped_after_t() -> None:
    rail = _rail(dwell_ns=1_000)
    _on(rail, _quote(bid="10.00", ask="10.05", sequence=1, exchange_timestamp_ns=500))
    _on(rail, _quote(bid="10.10", ask="10.05", sequence=2, exchange_timestamp_ns=900))
    third = _on(rail, _quote(bid="10.00", ask="10.05", sequence=3, exchange_timestamp_ns=700))
    assert third.long.dwell_window_clean is True
    assert third.short.dwell_window_clean is True
    fourth = _on(rail, _quote(bid="10.00", ask="10.05", sequence=4, exchange_timestamp_ns=950))
    assert fourth.long.dwell_window_clean is False
    assert fourth.short.dwell_window_clean is False


def test_t10_trimmed_quote_stays_out_when_time_steps_back() -> None:
    rail = _rail(dwell_ns=1_000)
    _on(rail, _quote(bid="9.70", ask="10.35", sequence=1, exchange_timestamp_ns=600))
    _on(rail, _quote(bid="9.80", ask="10.25", sequence=2, exchange_timestamp_ns=2_000))
    third = _on(rail, _quote(bid="10.00", ask="10.05", sequence=3, exchange_timestamp_ns=1_500))
    assert third.long.dwelled_exit_mark_cents == 1_000
    assert third.short.dwelled_exit_mark_cents == 1_005
