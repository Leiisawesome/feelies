"""Invariance of the content-keyed drain seed.

P1 and P2 insert one inert orchestrator event that consumes the kernel
sequence counter before the tape. Fill price, quantity, type, side and
time must stay put. Order ids may move.

P3 inserts a second symbol and resequences. The drain seed is a function
of vendor sequence number, exchange time, side and level, so a shared
content key must keep its uniform. The legacy seed, which also hashes
``order_id`` and ``ticks_at_level``, is the negative control and must
move at least one economic field.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

ROOT = Path(__file__).resolve().parents[2]
# Captured at import, before any case replaces the method. A reused
# process must not treat the previous case's wrapper as the content seed.
_CONTENT_UNIFORM = PassiveLimitOrderRouter._seeded_uniform
_SHIFT_NS = 60_000_000_000

_CASES = (
    ("base", "c"),
    ("base", "old"),
    ("p1", "c"),
    ("p1", "old"),
    ("p2", "c"),
    ("p2", "old"),
    ("p3a", "c"),
    ("p3a", "old"),
    ("p3b", "c"),
    ("p3b", "old"),
    ("p3c", "c"),
    ("p3c", "old"),
)


def _legacy_seeded_uniform(self: Any, pending: Any, quote: Any) -> float:
    """f4e615bb drain draw: content plus per-order tick count and order id."""
    seed = (
        f"{quote.symbol}|{quote.sequence_number}|"
        f"{quote.exchange_timestamp_ns}|{pending.ticks_at_level}|"
        f"{pending.side.name}|{pending.limit_price}|{pending.request.order_id}"
    )
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _economic(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(row["time_ns"], row["price"], row["qty"], row["type"], row["side"]) for row in rows]


def _diff_count(left: list[Any], right: list[Any]) -> int:
    shared = min(len(left), len(right))
    changed = sum(1 for index in range(shared) if left[index] != right[index])
    return changed + abs(len(left) - len(right))


def _first_index(left: list[Any], right: list[Any]) -> int | None:
    shared = min(len(left), len(right))
    for index in range(shared):
        if left[index] != right[index]:
            return index
    if len(left) != len(right):
        return shared
    return None


def _uniform_conflict(base: list[tuple[Any, ...]], other: list[tuple[Any, ...]]) -> int:
    """Shared content keys whose uniform differs. A content seed has zero."""
    left: dict[tuple[Any, ...], float] = {}
    for key, uniform in base:
        left.setdefault(key, uniform)
    conflicts = 0
    seen: set[tuple[Any, ...]] = set()
    for key, uniform in other:
        if key in seen or key not in left:
            continue
        seen.add(key)
        if left[key] != uniform:
            conflicts += 1
    return conflicts


def replay_case(spec: tuple[str, str]) -> dict[str, Any]:
    """One oracle replay. ``spec`` is (perturbation, seed mode)."""
    perturb, seed_mode = spec
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from feelies.bootstrap import build_platform
    from feelies.core.events import (
        AlertSeverity,
        MetricEvent,
        NBBOQuote,
        OrderAck,
        OrderAckStatus,
        OrderRequest,
        Signal,
        Trade,
    )
    from feelies.core.platform_config import PlatformConfig
    from feelies.harness import compute_parity_hash, prepare_backtest_event_log
    from feelies.storage.cache_replay import load_event_log_from_disk_cache
    from feelies.storage.event_resequence import resequence_event_list
    from feelies.storage.memory_event_log import InMemoryEventLog

    draws: list[tuple[tuple[Any, ...], float]] = []
    production = _legacy_seeded_uniform if seed_mode == "old" else _CONTENT_UNIFORM

    def _recording(self: Any, pending: Any, quote: Any) -> float:
        uniform = production(self, pending, quote)
        key = (
            quote.symbol,
            quote.sequence_number,
            quote.exchange_timestamp_ns,
            pending.side.name,
            str(pending.limit_price),
        )
        draws.append((key, uniform))
        return uniform

    PassiveLimitOrderRouter._seeded_uniform = _recording  # type: ignore[method-assign]

    runner_spec = importlib.util.spec_from_file_location(
        f"_p23d_runner_{perturb}_{seed_mode}",
        ROOT / "scripts" / "run_backtest.py",
    )
    assert runner_spec is not None and runner_spec.loader is not None
    runner = importlib.util.module_from_spec(runner_spec)
    sys.modules[runner_spec.name] = runner
    runner_spec.loader.exec_module(runner)

    event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
        ["APP"],
        "2026-03-26",
        "2026-03-26",
    )
    if perturb in {"p3a", "p3b", "p3c"}:
        loaded = list(event_log.replay())
        if perturb == "p3a":
            first_ex = min(event.exchange_timestamp_ns for event in loaded)
            extra: list[Any] = [
                NBBOQuote(
                    timestamp_ns=first_ex - 1,
                    correlation_id="ZZZ:inject:0",
                    sequence=0,
                    symbol="ZZZ",
                    bid=Decimal("10"),
                    ask=Decimal("10.01"),
                    bid_size=1,
                    ask_size=1,
                    exchange_timestamp_ns=first_ex - 1,
                    sequence_number=424242,
                )
            ]
        else:
            shift = _SHIFT_NS if perturb == "p3c" else 0
            extra = []
            for event in loaded:
                if not isinstance(event, (NBBOQuote, Trade)):
                    continue
                extra.append(
                    replace(
                        event,
                        symbol="ZZZ",
                        timestamp_ns=event.timestamp_ns + shift,
                        exchange_timestamp_ns=event.exchange_timestamp_ns + shift,
                        sequence_number=event.sequence_number + 9_000_000,
                    )
                )
        merged = resequence_event_list([*loaded, *extra])
        event_log = InMemoryEventLog()
        event_log.append_batch(merged)

    orders: list[tuple[Any, ...]] = []
    signals: list[tuple[Any, ...]] = []

    def factory(*args: Any, **kwargs: Any) -> Any:
        orchestrator, config_out = build_platform(*args, **kwargs)
        if perturb == "p1":
            orchestrator._publish_alert(
                timestamp_ns=0,
                correlation_id="p23d-p1",
                severity=AlertSeverity.INFO,
                alert_name="p23d_inert",
                message="sequence consume",
            )
        elif perturb == "p2":
            orchestrator._bus.publish(
                MetricEvent(
                    timestamp_ns=0,
                    correlation_id="p23d-p2",
                    sequence=orchestrator._seq.next(),
                    layer="kernel",
                    name="p23d_inert",
                    value=0.0,
                )
            )

        def _on_order(event: Any) -> None:
            if isinstance(event, OrderRequest):
                orders.append(
                    (
                        event.symbol,
                        event.side.name,
                        event.order_type.name,
                        event.quantity,
                        str(event.limit_price),
                        event.timestamp_ns,
                        event.order_id,
                    )
                )

        def _on_signal(event: Any) -> None:
            if isinstance(event, Signal):
                signals.append(
                    (
                        event.symbol,
                        event.strategy_id,
                        event.direction.name,
                        event.sequence,
                        event.timestamp_ns,
                    )
                )

        orchestrator._bus.subscribe(OrderRequest, _on_order)
        orchestrator._bus.subscribe(Signal, _on_signal)
        return orchestrator, config_out

    config = PlatformConfig.from_yaml(ROOT / "configs" / "bt_app.yaml")
    symbols = sorted(config.symbols)
    day_sources = [
        runner.DaySource(
            symbol=meta.symbol,
            date=meta.date,
            source=meta.source,
            event_count=meta.event_count,
            ingestion_health=meta.ingestion_health,
        )
        for meta in day_meta
    ]
    prep = prepare_backtest_event_log(config, event_log)
    mix = runner._enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="loaded from disk cache (baseline test)",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if mix != 0:
        return {"error": f"ingest mix {mix}", "perturb": perturb, "seed": seed_mode}
    config = runner._attach_day_source_provenance(config, symbols, day_sources)
    args = argparse.Namespace(
        trace_signal_orders=False,
        emit_fills_jsonl=False,
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
        emit_cross_sectional_jsonl=False,
        emit_sized_intents_jsonl=False,
        emit_hazard_exits_jsonl=False,
    )
    outcome = runner._run_backtest_phases_2_7(
        args,
        event_log,
        ingest_result,
        day_sources,
        config,
        symbols,
        "APP",
        "2026-03-26",
        time.monotonic(),
        platform_factory=factory,
        prep=prep,
    )
    if outcome.exit_code != 0:
        return {"error": f"exit {outcome.exit_code}", "perturb": perturb, "seed": seed_mode}

    journal = outcome.orchestrator.trade_journal
    assert journal is not None
    acks = {
        ack.order_id: ack
        for ack in outcome.recorder.of_type(OrderAck)
        if ack.status == OrderAckStatus.FILLED
    }
    fills: list[dict[str, Any]] = []
    for record in journal.query():
        ack = acks.get(record.order_id)
        reason = "" if ack is None else ack.reason
        if "THROUGH" in reason:
            kind = "THROUGH"
        elif "DRAIN" in reason:
            kind = "DRAIN"
        else:
            kind = reason
        fills.append(
            {
                "time_ns": record.fill_timestamp_ns,
                "price": str(record.fill_price),
                "qty": record.filled_quantity,
                "type": kind,
                "side": record.side.name,
                "order_id": record.order_id,
            }
        )
    positions = outcome.orchestrator.position_store.all_positions()
    gross = sum(
        (position.realized_pnl + position.unrealized_pnl for position in positions.values()),
        Decimal("0"),
    )
    fees = sum((ack.fees for ack in outcome.recorder.of_type(OrderAck)), Decimal("0"))
    return {
        "perturb": perturb,
        "seed": seed_mode,
        "fills": fills,
        "net": str(gross - fees),
        "hash": compute_parity_hash(outcome.orchestrator),
        "orders": orders,
        "signals": signals,
        "draws": draws,
    }


def _pair(
    campaign: dict[tuple[str, str], dict[str, Any]], perturb: str, seed: str
) -> dict[str, Any]:
    row = campaign[(perturb, seed)]
    assert "error" not in row, row
    return row


def _report(campaign: dict[tuple[str, str], dict[str, Any]], perturb: str) -> dict[str, Any]:
    base_c = _pair(campaign, "base", "c")
    case_c = _pair(campaign, perturb, "c")
    base_old = _pair(campaign, "base", "old")
    case_old = _pair(campaign, perturb, "old")
    econ_c = _diff_count(_economic(base_c["fills"]), _economic(case_c["fills"]))
    econ_old = _diff_count(_economic(base_old["fills"]), _economic(case_old["fills"]))
    ids = _diff_count(
        [row["order_id"] for row in base_c["fills"]],
        [row["order_id"] for row in case_c["fills"]],
    )
    order_index = _first_index(base_c["orders"], case_c["orders"])
    signal_index = _first_index(base_c["signals"], case_c["signals"])
    return {
        "econ_c": econ_c,
        "econ_old": econ_old,
        "ids": ids,
        "uniform_conflicts": _uniform_conflict(base_c["draws"], case_c["draws"]),
        "order_index": order_index,
        "signal_index": signal_index,
        "base_order": None if order_index is None else base_c["orders"][order_index],
        "case_order": None
        if order_index is None or order_index >= len(case_c["orders"])
        else case_c["orders"][order_index],
        "base_signal": None if signal_index is None else base_c["signals"][signal_index],
        "case_signal": None
        if signal_index is None or signal_index >= len(case_c["signals"])
        else case_c["signals"][signal_index],
        "net_c": case_c["net"],
        "hash_c": case_c["hash"],
        "fills_c": case_c["fills"],
    }


@pytest.fixture(scope="module")
def campaign() -> dict[tuple[str, str], dict[str, Any]]:
    with ProcessPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(replay_case, _CASES))
    out = {(row["perturb"], row["seed"]): row for row in rows}
    missing = [spec for spec in _CASES if spec not in out]
    assert not missing, missing
    return out


def test_p1_fill_economics_are_invariant(campaign: dict[tuple[str, str], dict[str, Any]]) -> None:
    report = _report(campaign, "p1")
    assert report["econ_old"] >= 1, report
    assert report["econ_c"] == 0, report


def test_p2_fill_economics_are_invariant(campaign: dict[tuple[str, str], dict[str, Any]]) -> None:
    report = _report(campaign, "p2")
    assert report["econ_old"] >= 1, report
    assert report["econ_c"] == 0, report


@pytest.mark.parametrize("perturb", ["p3a", "p3b"])
def test_p3_drain_uniforms_follow_content(
    campaign: dict[tuple[str, str], dict[str, Any]],
    perturb: str,
) -> None:
    report = _report(campaign, perturb)
    assert report["econ_old"] >= 1, report
    assert report["uniform_conflicts"] == 0, report
    assert report["econ_c"] == 0, report


def test_p3c_shifted_symbol_does_not_move_app_fills(
    campaign: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """A time-shifted second symbol does not move APP fill economics.

    The old drain seed remains the negative control.
    """
    report = _report(campaign, "p3c")
    assert report["econ_old"] >= 1, report
    assert report["uniform_conflicts"] == 0, report
    assert report["econ_c"] == 0, report
