"""Member harness.

Synthetic runs follow ``tests/position_engine/test_p10_contract_surface.py``
``_config`` / ``_replay``: ``InMemoryEventLog.append_batch``, ``PlatformConfig``,
``build_platform``, ``bus.subscribe_all``, ``boot``, ``run_backtest``.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from feelies.bootstrap import build_platform
from feelies.core.events import (
    DeRiskRequirement,
    Event,
    GateDecision,
    MarkRailUpdate,
    NBBOQuote,
    OrderRequest,
    PositionClosed,
    PositionSnapshot,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.position_engine.tapes import make_tape

T0 = 1_774_533_600_000_000_000
_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_APP_CONFIG = Path("configs/bt_position_arbitrary_not_calibrated.yaml")
_NEEDED = frozenset({"ofi_ewma", "book_imbalance", "spread_z_30d", "realized_vol_30s"})
_CLOCK_FIXED = 946684800

RECORD_TYPES = (
    MarkRailUpdate,
    PositionSnapshot,
    GateDecision,
    PositionClosed,
    DeRiskRequirement,
)


class Record(NamedTuple):
    attributed_quote_sequence: int | None
    type_name: str
    canonical: str


class Records(list[Record]):
    """Ordered bus records, plus the quotes and orders of that run."""

    quotes: dict[int, NBBOQuote]
    order_requests: tuple[OrderRequest, ...]

    def __init__(
        self,
        rows: Sequence[Record],
        quotes: dict[int, NBBOQuote],
        order_requests: Sequence[OrderRequest],
    ) -> None:
        super().__init__(rows)
        self.quotes = quotes
        self.order_requests = tuple(order_requests)


def canonical(event: Event) -> str:
    body = json.dumps(
        dataclasses.asdict(event),
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{type(event).__name__}{body}"


def _drop_keys(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _drop_keys(item)
            for key, item in value.items()
            if key != "sequence" and not str(key).endswith("_sequence") and key != "cell_id"
        }
    if isinstance(value, list):
        return [_drop_keys(item) for item in value]
    return value


def project_for_multiname(canonical_text: str) -> str:
    name, _, payload = canonical_text.partition("{")
    data = json.loads("{" + payload)
    return name + json.dumps(_drop_keys(data), sort_keys=True, separators=(",", ":"))


def nonvacuous(records: Sequence[Record], *type_names: type[Event] | str, scenario: str) -> None:
    present = {row.type_name for row in records}
    for type_name in type_names:
        label = type_name if isinstance(type_name, str) else type_name.__name__
        if label not in present:
            raise AssertionError(f"NONVACUOUS: no {label} records in {scenario}")


def _clock_tag() -> str:
    return "fixed" if time.time() == _CLOCK_FIXED else "wall"


def _sensors() -> tuple[object, ...]:
    contra = PlatformConfig.from_yaml(Path("configs/bt_netting_contest.yaml"))
    return tuple(spec for spec in contra.sensor_specs if spec.sensor_id in _NEEDED)


def _keep(event: Event) -> bool:
    if type(event) is DeRiskRequirement:
        return event.source_layer == "POSITION"
    return type(event) in RECORD_TYPES


def _capture(bus: object) -> tuple[list[Record], dict[int, NBBOQuote], list[OrderRequest]]:
    rows: list[Record] = []
    quotes: dict[int, NBBOQuote] = {}
    orders: list[OrderRequest] = []
    last: int | None = None

    def on_quote(event: NBBOQuote) -> None:
        nonlocal last
        last = event.sequence
        quotes[event.sequence] = event

    def on_event(event: Event) -> None:
        nonlocal last
        if type(event) is MarkRailUpdate:
            # Published before its quote, so the update names the quote it belongs to.
            last = event.quote_sequence
        if type(event) is OrderRequest:
            orders.append(event)
        if _keep(event):
            rows.append(Record(last, type(event).__name__, canonical(event)))

    bus.subscribe(NBBOQuote, on_quote)  # type: ignore[attr-defined]
    bus.subscribe_all(on_event)  # type: ignore[attr-defined]
    return rows, quotes, orders


@contextmanager
def _seams(
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    attach_sink: bool,
):
    import feelies.portfolio.mark_rail as rail_mod
    import feelies.position.engine as engine_mod

    saved_engine = engine_mod.PositionEngine
    saved_on_quote = rail_mod.MarkRail.on_quote
    saved_attach = engine_mod.PositionRecordSink.attach
    try:
        if engine_factory is not None:
            engine_mod.PositionEngine = engine_factory  # type: ignore[misc, assignment]
        if rail_wrapper is not None:
            original = saved_on_quote

            def on_quote(self: object, quote: NBBOQuote) -> object:
                return rail_wrapper(original.__get__(self, type(self)), quote)

            rail_mod.MarkRail.on_quote = on_quote  # type: ignore[method-assign]
        if not attach_sink:
            engine_mod.PositionRecordSink.attach = lambda self: None  # type: ignore[method-assign]
        yield
    finally:
        engine_mod.PositionEngine = saved_engine
        rail_mod.MarkRail.on_quote = saved_on_quote
        engine_mod.PositionRecordSink.attach = saved_attach


def _execute_synthetic(
    tape: Sequence[NBBOQuote],
    symbols: tuple[str, ...],
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    attach_sink: bool,
) -> Records:
    log = InMemoryEventLog()
    log.append_batch(list(tape))
    config = PlatformConfig(
        symbols=frozenset(symbols),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=80.0,
    )
    with _seams(engine_factory, rail_wrapper, attach_sink):
        orchestrator, resolved = build_platform(config, event_log=log)
        rows, quotes, orders = _capture(orchestrator._bus)
        orchestrator.boot(resolved)
        orchestrator.run_backtest()
    return Records(rows, quotes, orders)


_TAPES: dict[tuple[tuple[int, int, str], ...], list[NBBOQuote]] = {}
_FACTORIES: dict[str, Callable[..., object]] = {}
_RAILS: dict[str, Callable[..., object]] = {}


def _factory_key(factory: Callable[..., object] | None) -> str:
    if factory is None:
        return ""
    key = repr(factory)
    _FACTORIES[key] = factory
    return key


def _rail_key(wrapper: Callable[..., object] | None) -> str:
    if wrapper is None:
        return ""
    key = repr(wrapper)
    _RAILS[key] = wrapper
    return key


@functools.lru_cache(maxsize=None)
def _cached_synthetic(
    tape_key: tuple[tuple[int, int, str], ...],
    symbols: tuple[str, ...],
    factory_key: str,
    rail_key: str,
    attach_sink: bool,
    clock_tag: str,
) -> Records:
    del clock_tag
    return _execute_synthetic(
        _TAPES[tape_key],
        symbols,
        _FACTORIES.get(factory_key),
        _RAILS.get(rail_key),
        attach_sink,
    )


def run_synthetic(
    tape: Sequence[NBBOQuote],
    *,
    symbols: Sequence[str],
    engine_factory: Callable[..., object] | None = None,
    rail_wrapper: Callable[..., object] | None = None,
    attach_sink: bool = True,
) -> Records:
    tape_key = tuple((quote.sequence, quote.timestamp_ns, quote.symbol) for quote in tape)
    _TAPES.setdefault(tape_key, list(tape))
    return _cached_synthetic(
        tape_key,
        tuple(symbols),
        _factory_key(engine_factory),
        _rail_key(rail_wrapper),
        attach_sink,
        _clock_tag(),
    )


def _missing_cache(exc: Exception) -> None:
    import pytest

    hint = f"Disk cache miss for APP/2026-03-26 ({exc})"
    if os.environ.get("FEELIES_REQUIRE_BASELINE_CACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        pytest.fail(
            f"FEELIES_REQUIRE_BASELINE_CACHE is set, so the real session must run.\n{hint}"
        )
    pytest.skip(hint)


def _load_runner():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_position_scenarios_runner",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_position_scenarios_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def real_cutoff_sequence(fraction: float) -> int:
    events, _meta = _real_bundle()
    k = int(len(events) * fraction) - 1
    return int(events[k].sequence)


@functools.lru_cache(maxsize=1)
def _real_bundle() -> tuple[tuple[Event, ...], tuple[object, ...]]:
    from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

    try:
        event_log, ingest, day_meta = load_event_log_from_disk_cache(
            ["APP"], "2026-03-26", "2026-03-26"
        )
    except CacheReplayError as exc:
        _missing_cache(exc)
        raise
    return tuple(event_log.replay()), (ingest, tuple(day_meta))


def _execute_real(
    fraction: float | None,
    engine_factory: Callable[..., object] | None,
    attach_sink: bool,
) -> Records:
    import argparse

    events, (ingest, day_meta) = _real_bundle()
    if fraction is not None:
        events = events[: int(len(events) * fraction)]
    log = InMemoryEventLog()
    log.append_batch(list(events))
    runner = _load_runner()
    from feelies.harness.backtest_prep import prepare_backtest_event_log

    config = PlatformConfig.from_yaml(_APP_CONFIG)
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
    prep = prepare_backtest_event_log(config, log)
    rc = runner._enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="position battery",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        raise RuntimeError(f"ingest event mix rejected the real session ({rc})")
    config = runner._attach_day_source_provenance(config, symbols, day_sources)
    held: dict[str, object] = {}

    def factory(config: PlatformConfig, event_log: InMemoryEventLog, **kwargs: object):
        orchestrator, resolved = build_platform(config, event_log=event_log, **kwargs)  # type: ignore[arg-type]
        rows, quotes, orders = _capture(orchestrator._bus)
        held["rows"] = rows
        held["quotes"] = quotes
        held["orders"] = orders
        return orchestrator, resolved

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
    with _seams(engine_factory, None, attach_sink):
        outcome = runner._run_backtest_phases_2_7(
            args,
            log,
            ingest,
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
        raise RuntimeError(f"real session exit {outcome.exit_code}")
    return Records(held["rows"], held["quotes"], held["orders"])  # type: ignore[arg-type]


@functools.lru_cache(maxsize=None)
def _cached_real(
    fraction: float | None,
    factory_key: str,
    attach_sink: bool,
    clock_tag: str,
) -> Records:
    del clock_tag
    return _execute_real(fraction, _FACTORIES.get(factory_key), attach_sink)


def run_real(
    *,
    fraction: float | None = None,
    engine_factory: Callable[..., object] | None = None,
    attach_sink: bool = True,
) -> Records:
    return _cached_real(fraction, _factory_key(engine_factory), attach_sink, _clock_tag())


def format_line(row: Record) -> str:
    return f"{row.attributed_quote_sequence}\t{row.type_name}\t{row.canonical}"


def _scenario(name: str) -> Records:
    if name == "syn_m1":
        tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
        return run_synthetic(tape, symbols=("SYN",))
    if name == "real_m1":
        return run_real()
    raise SystemExit(f"unknown scenario {name}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: python -m tests.position_engine.scenarios <syn_m1|real_m1>")
    for row in _scenario(args[1]):
        print(format_line(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
