"""Member harness.

Synthetic runs follow ``tests/position_engine/test_p10_contract_surface.py``
``_config`` / ``_replay``: ``InMemoryEventLog.append_batch``, ``PlatformConfig``,
``build_platform``, ``bus.subscribe_all``, ``boot``, ``run_backtest``.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import hashlib
import json
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.core.events import (
    DeRiskRequirement,
    Event,
    GateDecision,
    MarkRailUpdate,
    NBBOQuote,
    OrderRequest,
    PositionClosed,
    RiskAction,
    RiskVerdict,
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
    risk_verdicts: tuple[RiskVerdict, ...]

    def __init__(
        self,
        rows: Sequence[Record],
        quotes: dict[int, NBBOQuote],
        order_requests: Sequence[OrderRequest],
        risk_verdicts: Sequence[RiskVerdict] = (),
    ) -> None:
        super().__init__(rows)
        self.quotes = quotes
        self.order_requests = tuple(order_requests)
        self.risk_verdicts = tuple(risk_verdicts)


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


def assert_no_risk_rejects(records: Records) -> None:
    """Synthetic batteries must not be thinned by a risk-layer reject."""
    rejects = [
        verdict for verdict in records.risk_verdicts if verdict.action is not RiskAction.ALLOW
    ]
    if not rejects:
        return
    counts: dict[str, int] = {}
    for verdict in rejects:
        counts[verdict.reason] = counts.get(verdict.reason, 0) + 1
    detail = ", ".join(f"{reason}:{counts[reason]}" for reason in sorted(counts))
    raise AssertionError(f"CONFOUND: risk rejected {len(rejects)} signals ({detail})")


def nonvacuous(records: Sequence[Record], *type_names: type[Event] | str, scenario: str) -> None:
    present = {row.type_name for row in records}
    for type_name in type_names:
        label = type_name if isinstance(type_name, str) else type_name.__name__
        if label not in present:
            raise AssertionError(f"NONVACUOUS: no {label} records in {scenario}")


_EXIT_RANK = ("ADVERSE", "HORIZON", "INVALIDATION", "FAVORABLE")


def drawn_adverse_level(cell_id: str, centre: int, band: int) -> int:
    """contracts.md §9 band draw. ``band`` is even; the level is whole ticks."""
    offset = int.from_bytes(hashlib.sha256(cell_id.encode("utf-8")).digest()[:8], "big") % (
        band + 1
    )
    return (centre - band // 2) + offset


def _body(canonical_text: str) -> dict[str, object]:
    return json.loads(canonical_text[canonical_text.index("{") :])


def _cents(price: object) -> int:
    return int(price * 100)  # type: ignore[operator]


def _sign(side: str) -> int:
    if side == "LONG":
        return 1
    if side == "SHORT":
        return -1
    raise AssertionError(f"displacement identity: side {side} is not LONG or SHORT")


def _valuation_cents(quote: NBBOQuote, side: str) -> int:
    return _cents(quote.bid if side == "LONG" else quote.ask)


def cell_economics(row: Record, quotes: dict[int, NBBOQuote]) -> tuple[int, int, int]:
    """Return ``(result, displacement, cost)`` in cent-shares from the tape."""
    body = _body(row.canonical)
    cell = str(body["cell_id"])
    side = str(body["side"])
    sign = _sign(side)
    entries = body["entry_fills"]
    exits = body["exit_fills"]
    assert isinstance(entries, list) and isinstance(exits, list)
    entry = entries[0]
    exit_fill = exits[0]
    assert isinstance(entry, dict) and isinstance(exit_fill, dict)
    exit_seq = int(exit_fill["sequence"])
    entry_seq = int(entry["sequence"])
    if exit_seq not in quotes:
        raise AssertionError(
            f"displacement identity: cell {cell} exit fill sequence {exit_seq} is not on the tape"
        )
    if entry_seq not in quotes:
        raise AssertionError(
            f"displacement identity: cell {cell} entry fill sequence {entry_seq} is not on the tape"
        )
    qty = int(entry["quantity"])
    result = sign * (
        sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in exits)
        - sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in entries)
    )
    displacement = (
        sign
        * qty
        * (_valuation_cents(quotes[exit_seq], side) - _valuation_cents(quotes[entry_seq], side))
    )
    return result, displacement, displacement - result


def displacement_identity(records: Records) -> None:
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        result, displacement, cost = cell_economics(row, records.quotes)
        if result + cost != displacement:
            cell = str(_body(row.canonical)["cell_id"])
            raise AssertionError(
                f"displacement identity failed for {cell}: cost {cost} != "
                f"displacement {displacement} - result {result}"
            )


def mean_within_se(samples: Sequence[float], expected: float, *, label: str) -> None:
    n = len(samples)
    if n < 2:
        raise AssertionError(f"mean {label}: need at least 2 samples, got {n}")
    mean = sum(samples) / n
    var = sum((sample - mean) ** 2 for sample in samples) / (n - 1)
    bound = 4 * math.sqrt(var / n)
    if abs(mean - expected) > bound:
        raise AssertionError(f"mean {label} {mean} outside 4 SE of {expected} (bound {bound})")


def exit_reason_at_collision(records: Records) -> None:
    requirements = [row for row in records if row.type_name == "DeRiskRequirement"]
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        cell = str(body["cell_id"])
        paths = body["triggered_paths"]
        assert isinstance(paths, list)
        names = [str(path["path"]) for path in paths if isinstance(path, dict)]
        ranked = [name for name in _EXIT_RANK if name in names]
        expected = ranked[0]
        got = str(body["exit_reason"])
        if got != expected:
            raise AssertionError(
                f"exit reason {got} != {expected} cell {cell} candidates {ranked}"
            )
        prices = [int(path["proposed_price_cents"]) for path in paths if isinstance(path, dict)]
        worst = min(prices) if body["side"] == "LONG" else max(prices)
        if int(body["proposed_price_cents"]) != worst:
            raise AssertionError(
                f"proposed price {body['proposed_price_cents']} != worst {worst} cell {cell}"
            )
        entries = body["entry_fills"]
        exits = body["exit_fills"]
        assert isinstance(entries, list) and isinstance(exits, list) and entries and exits
        assert isinstance(entries[0], dict) and isinstance(exits[0], dict)
        start = int(entries[0]["timestamp_ns"])
        end = int(exits[0]["timestamp_ns"])
        count = 0
        for req in requirements:
            req_body = _body(req.canonical)
            if req_body.get("symbol") != body["symbol"]:
                continue
            if req_body.get("strategy_id") != body["strategy_id"]:
                continue
            ts = int(req_body["timestamp_ns"])
            if start <= ts <= end:
                count += 1
        if count != 1:
            raise AssertionError(f"requirement count {count} != 1 cell {cell}")


def _clock_tag() -> str:
    return "fixed" if time.time() == _CLOCK_FIXED else "wall"


def _sensors() -> tuple[object, ...]:
    contra = PlatformConfig.from_yaml(Path("configs/bt_netting_contest.yaml"))
    return tuple(spec for spec in contra.sensor_specs if spec.sensor_id in _NEEDED)


def _keep(event: Event) -> bool:
    if type(event) is DeRiskRequirement:
        return event.source_layer == "POSITION"
    return type(event) in RECORD_TYPES


def attribute(stream: Sequence[Event]) -> list[tuple[int | None, str, str]]:
    """Attribute each recorded event to the quote cursor at publication.

    The cursor starts at None. A MarkRailUpdate sets it to ``quote_sequence``
    before that update is recorded. An NBBOQuote sets it to ``sequence``.
    """
    cursor: int | None = None
    rows: list[tuple[int | None, str, str]] = []
    for event in stream:
        if type(event) is MarkRailUpdate:
            cursor = event.quote_sequence
        elif type(event) is NBBOQuote:
            cursor = event.sequence
        if _keep(event):
            rows.append((cursor, type(event).__name__, canonical(event)))
    return rows


def _capture(bus: object) -> list[Event]:
    stream: list[Event] = []
    bus.subscribe_all(stream.append)  # type: ignore[attr-defined]
    return stream


def _records_from(stream: Sequence[Event]) -> Records:
    quotes = {event.sequence: event for event in stream if type(event) is NBBOQuote}
    orders = [event for event in stream if type(event) is OrderRequest]
    verdicts = [event for event in stream if type(event) is RiskVerdict]
    return Records([Record(*row) for row in attribute(stream)], quotes, orders, verdicts)


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


def fixture_variant(**overrides: object) -> dict[str, object]:
    """Pure in-memory edit of the position fixture. No YAML file is written."""
    spec = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    edited: dict[str, object] = copy.deepcopy(spec)
    if "horizon_seconds" in overrides:
        edited["horizon_seconds"] = overrides["horizon_seconds"]
    policy = edited["exit_policy"]
    assert isinstance(policy, dict)
    if "fee_round_trip_ticks" in overrides:
        policy["fee_round_trip_ticks"] = overrides["fee_round_trip_ticks"]
    horizon = policy["horizon"]
    adverse = policy["adverse"]
    favorable = policy["favorable"]
    assert isinstance(horizon, dict) and isinstance(adverse, dict) and isinstance(favorable, dict)
    if "T_seconds" in overrides:
        horizon["T_seconds"] = overrides["T_seconds"]
    for key in ("centre_ticks", "band_ticks", "lo_ticks", "hi_ticks"):
        if key in overrides:
            adverse[key] = overrides[key]
    if "target_ticks" in overrides:
        favorable["target_ticks"] = overrides["target_ticks"]
    if "archetype" in overrides:
        policy["archetype"] = overrides["archetype"]
    if "form" in overrides:
        favorable["form"] = overrides["form"]
    if "giveback_spread_multiple" in overrides:
        favorable["giveback_spread_multiple"] = overrides["giveback_spread_multiple"]
    return edited


def synthetic_alpha_spec(variant: dict[str, object] | None) -> dict[str, object]:
    """In-memory fixture for synthetic runs. Drawdown is 100 unless set explicitly."""
    on_disk = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    disk_risk = on_disk.get("risk_budget")
    disk_pct = disk_risk.get("max_drawdown_pct") if isinstance(disk_risk, dict) else None
    if variant is None:
        spec: dict[str, object] = copy.deepcopy(on_disk)
        explicit = False
    else:
        spec = copy.deepcopy(variant)
        caller_risk = variant.get("risk_budget")
        explicit = (
            isinstance(caller_risk, dict)
            and "max_drawdown_pct" in caller_risk
            and caller_risk.get("max_drawdown_pct") != disk_pct
        )
    if not explicit:
        risk = spec.get("risk_budget")
        if not isinstance(risk, dict):
            risk = {}
            spec["risk_budget"] = risk
        risk["max_drawdown_pct"] = 100.0
    return spec


def _execute_synthetic(
    tape: Sequence[NBBOQuote],
    symbols: tuple[str, ...],
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    attach_sink: bool,
    variant: dict[str, object] | None,
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
    original_load = AlphaLoader.load
    spec = synthetic_alpha_spec(variant)

    def _load(
        self: AlphaLoader,
        path: object,
        param_overrides: dict[str, object] | None = None,
    ) -> object:
        if Path(str(path)) == _FIXTURE:
            return self.load_from_dict(spec, source=str(_FIXTURE))
        return original_load(self, path, param_overrides)  # type: ignore[arg-type]

    AlphaLoader.load = _load  # type: ignore[method-assign]
    try:
        with _seams(engine_factory, rail_wrapper, attach_sink):
            orchestrator, resolved = build_platform(config, event_log=log)
            stream = _capture(orchestrator._bus)
            orchestrator.boot(resolved)
            orchestrator.run_backtest()
    finally:
        AlphaLoader.load = original_load  # type: ignore[method-assign]
    return _records_from(stream)


_TAPES: dict[tuple[tuple[int, int, str, str, str, int, int], ...], list[NBBOQuote]] = {}
_FACTORIES: dict[str, Callable[..., object]] = {}
_RAILS: dict[str, Callable[..., object]] = {}
_VARIANTS: dict[str, dict[str, object] | None] = {}


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
    tape_key: tuple[tuple[int, int, str, str, str, int, int], ...],
    symbols: tuple[str, ...],
    factory_key: str,
    rail_key: str,
    attach_sink: bool,
    clock_tag: str,
    variant_key: str,
) -> Records:
    del clock_tag
    return _execute_synthetic(
        _TAPES[tape_key],
        symbols,
        _FACTORIES.get(factory_key),
        _RAILS.get(rail_key),
        attach_sink,
        _VARIANTS.get(variant_key),
    )


def run_synthetic(
    tape: Sequence[NBBOQuote],
    *,
    symbols: Sequence[str],
    engine_factory: Callable[..., object] | None = None,
    rail_wrapper: Callable[..., object] | None = None,
    attach_sink: bool = True,
    variant: dict[str, object] | None = None,
) -> Records:
    tape_key = tuple(
        (
            quote.sequence,
            quote.timestamp_ns,
            quote.symbol,
            str(quote.bid),
            str(quote.ask),
            quote.bid_size,
            quote.ask_size,
        )
        for quote in tape
    )
    _TAPES.setdefault(tape_key, list(tape))
    variant_key = "" if variant is None else json.dumps(variant, sort_keys=True, default=str)
    _VARIANTS[variant_key] = variant
    return _cached_synthetic(
        tape_key,
        tuple(symbols),
        _factory_key(engine_factory),
        _rail_key(rail_wrapper),
        attach_sink,
        _clock_tag(),
        variant_key,
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
        held["stream"] = _capture(orchestrator._bus)
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
    return _records_from(held["stream"])  # type: ignore[arg-type]


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
