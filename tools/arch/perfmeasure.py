#!/usr/bin/env python3
"""Phase 4 (Axis E) per-engine latency measurement under replay.

Standard library only, except that it imports ``feelies`` to drive a real
backtest.  Writes ``tools/arch/evidence/perf.json``.

WHY A PROBE HARNESS AND NOT cProfile
------------------------------------
cProfile inflates Python call cost by 2-5x and the inflation is proportional to
call *count*, so it reorders engines by how chatty they are rather than by how
expensive they are.  This tool instead wraps a declared, small set of engine
boundary methods with ``time.perf_counter_ns`` and maintains a span stack, so
each probe reports both inclusive and **exclusive** (self) nanoseconds.  ~30
probes over ~83k quotes is a few million extra ns of instrumentation, and the
``plain`` mode measures exactly how much by running the same replay unprobed.

Probes attach in two ways:

1.  ``DIRECT_PROBES`` -- declared ``module:Class.method`` targets, patched with
    ``setattr`` on the class.  Reaches the 36 direct orchestrator->store calls
    that never touch the bus.
2.  bus handlers -- ``EventBus.subscribe`` is patched *before* composition, so
    every handler registered by any of the subscribe sites is wrapped and
    labelled by its own module and qualname.  Nothing has to be enumerated by
    hand and a newly added subscriber cannot escape the census.

NO PRODUCTION CODE IS MODIFIED.  Every patch is a runtime ``setattr`` from this
file, reverted at process exit by process exit.

DETERMINISM
-----------
``--mode both`` runs the same replay unprobed and probed and compares
``compute_parity_hash``.  Equal hashes are the evidence that measurement does
not perturb output (CORE C.1, P4 section 5).  Unequal hashes invalidate every
number this tool prints and it says so.

Usage (Windows PowerShell, from repo root):

    uv run python tools/arch/perfmeasure.py --mode both
    uv run python tools/arch/perfmeasure.py --mode scale
    uv run python tools/arch/perfmeasure.py --mode profile
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import platform
import sys
import time
from array import array
from dataclasses import dataclass, field, replace as dc_replace
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

# The parity-oracle cell.  Same symbol/date/config as
# tests/acceptance/test_backtest_app_baseline.py so a moved number here is
# comparable with the repo's own locked baseline.
BASE_SYMBOLS = ["APP"]
BASE_DATE = "2026-03-26"
BASE_CONFIG = "configs/bt_app.yaml"

# Symbol-cardinality scaling.  Every one of these has a cached tape for the
# date below, so N=1 and N=8 replay the same session with the same code.
SCALE_DATE = "2026-04-22"
SCALE_SYMBOLS = ["APP", "CROX", "DIOD", "ENSG", "MLI", "OLN", "PCTY", "RMBS"]

# Engine ownership per CORE E, refined by Phase 0 D0.2 / Phase 2 sheets.
# Longest prefix wins.  Engine 0 is the cross-cutting kernel; 13 is the
# measurement harness itself (backtest recorders), which is NOT an engine and
# is reported separately precisely because it is on the bus during a backtest.
ENGINE_OF_MODULE: list[tuple[str, int]] = [
    ("feelies.harness", 13),
    ("feelies.ingestion", 1),
    ("feelies.storage", 1),
    ("feelies.sensors", 2),
    ("feelies.features", 2),
    ("feelies.services", 3),
    ("feelies.signals", 4),
    ("feelies.alpha", 5),
    ("feelies.promotion", 5),
    ("feelies.composition", 6),
    ("feelies.portfolio", 7),
    ("feelies.risk", 8),
    ("feelies.execution.intent", 9),
    ("feelies.execution.position_manager", 9),
    ("feelies.execution.portfolio_netter", 9),
    ("feelies.execution.min_cost_policy", 9),
    ("feelies.execution.sized_intent_legs", 9),
    ("feelies.execution.order_admission", 9),
    ("feelies.execution", 10),
    ("feelies.broker", 10),
    ("feelies.monitoring", 11),
    ("feelies.research", 12),
    ("feelies.forensics", 12),
    ("feelies.core", 0),
    ("feelies.bus", 0),
    ("feelies.kernel", 0),
    ("feelies.bootstrap", 0),
]

# Declared boundary probes.  (engine, label, "module:Class.method")
#
# Rule applied when choosing these: probe a method only where it is the entry
# to an engine's work for one event.  Bus-dispatched handlers are NOT listed --
# the subscribe patch already covers them, and listing both double-counts.
DIRECT_PROBES: list[tuple[int, str, str]] = [
    # -- kernel: the tick itself, so every engine probe has a denominator ----
    (0, "kernel.run_backtest", "feelies.kernel.orchestrator:Orchestrator.run_backtest"),
    (0, "kernel.process_tick", "feelies.kernel.orchestrator:Orchestrator._process_tick"),
    (0, "kernel.tick_inner", "feelies.kernel.orchestrator:Orchestrator._process_tick_inner"),
    (0, "kernel.process_trade", "feelies.kernel.orchestrator:Orchestrator._process_trade_inner"),
    (0, "kernel.finalize_tick", "feelies.kernel.orchestrator:Orchestrator._finalize_tick"),
    (0, "kernel.sm_transition", "feelies.core.state_machine:StateMachine.transition"),
    (0, "kernel.bus_publish", "feelies.bus.event_bus:EventBus.publish"),
    # Isolates the StateTransition emission, which the census shows has zero
    # subscribers in this configuration -- the cost of publishing to nobody.
    (
        0,
        "kernel.emit_state_transition",
        "feelies.kernel.orchestrator:Orchestrator._emit_state_transition",
    ),
    # -- engine 1: market data ---------------------------------------------
    (1, "E1.event_log_append", "feelies.storage.memory_event_log:InMemoryEventLog.append"),
    (
        1,
        "E1.data_health_gate",
        "feelies.kernel.orchestrator:Orchestrator._data_health_blocks_trading",
    ),
    (1, "E1.verify_integrity", "feelies.kernel.orchestrator:Orchestrator._verify_data_integrity"),
    (1, "E1.update_halt_state", "feelies.kernel.orchestrator:Orchestrator._update_halt_state"),
    (1, "E1.update_ssr_state", "feelies.kernel.orchestrator:Orchestrator._update_ssr_state"),
    # -- engine 2: state / feature ----------------------------------------
    (
        2,
        "E2.dispatch_sensor_layer",
        "feelies.kernel.orchestrator:Orchestrator._dispatch_sensor_layer",
    ),
    (2, "E2.horizon_scheduler", "feelies.sensors.horizon_scheduler:HorizonScheduler.on_event"),
    # -- engine 3: regime --------------------------------------------------
    (3, "E3.update_regime", "feelies.kernel.orchestrator:Orchestrator._update_regime"),
    # -- engine 6: portfolio construction ---------------------------------
    (
        6,
        "E6.xsect_bookend",
        "feelies.kernel.orchestrator:Orchestrator._maybe_transition_cross_sectional_bookend",
    ),
    (
        6,
        "E6.flush_sized_intents",
        "feelies.kernel.orchestrator:Orchestrator._flush_pending_sized_intents",
    ),
    # -- engine 7: portfolio accounting -----------------------------------
    (
        7,
        "E7.update_mark",
        "feelies.portfolio.memory_position_store:MemoryPositionStore.update_mark",
    ),
    (
        7,
        "E7.strategy_update_mark",
        "feelies.portfolio.strategy_position_store:StrategyPositionStore.update_mark",
    ),
    (7, "E7.position_get", "feelies.portfolio.memory_position_store:MemoryPositionStore.get"),
    (
        7,
        "E7.total_exposure",
        "feelies.portfolio.memory_position_store:MemoryPositionStore.total_exposure",
    ),
    (7, "E7.apply_fill", "feelies.portfolio.memory_position_store:MemoryPositionStore.update"),
    # -- engine 8: risk & capital -----------------------------------------
    (8, "E8.check_signal", "feelies.risk.basic_risk:BasicRiskEngine.check_signal"),
    (8, "E8.check_order", "feelies.risk.basic_risk:BasicRiskEngine.check_order"),
    (8, "E8.check_sized_intent", "feelies.risk.basic_risk:BasicRiskEngine.check_sized_intent"),
    (8, "E8.refresh_hwm", "feelies.risk.basic_risk:BasicRiskEngine.refresh_high_water_mark"),
    (
        8,
        "E8.budget_check_signal",
        "feelies.alpha.risk_wrapper:AlphaBudgetRiskWrapper.check_signal",
    ),
    (
        8,
        "E8.sizer_target_qty",
        "feelies.risk.position_sizer:BudgetBasedSizer.compute_target_quantity",
    ),
    (
        8,
        "E8.compute_target_qty",
        "feelies.kernel.orchestrator:Orchestrator._compute_target_quantity",
    ),
    (
        8,
        "E8.buying_power_flip",
        "feelies.kernel.orchestrator:Orchestrator._maybe_flip_buying_power_at_rth_close",
    ),
    # -- engine 9: execution decision -------------------------------------
    (9, "E9.plan", "feelies.execution.position_manager:TargetPositionManager.plan"),
    (9, "E9.netter_net", "feelies.execution.portfolio_netter:PortfolioNetter.net"),
    (9, "E9.build_order", "feelies.kernel.orchestrator:Orchestrator._try_build_order_from_intent"),
    (
        9,
        "E9.min_cost_decide",
        "feelies.execution.min_cost_policy:MinimumCostExecutionPolicy.decide",
    ),
    # -- engine 4: alpha ---------------------------------------------------
    (4, "E4.regime_gate_eval", "feelies.signals.regime_gate:RegimeGate.evaluate"),
    # -- engine 10: execution simulation / routing ------------------------
    (10, "E10.router_on_quote", "feelies.execution.backtest_router:BacktestOrderRouter.on_quote"),
    (
        10,
        "E10.submit_tracked_order",
        "feelies.kernel.orchestrator:Orchestrator._submit_tracked_order",
    ),
    (10, "E10.settle_router_acks", "feelies.kernel.orchestrator:Orchestrator._settle_router_acks"),
    (
        10,
        "E10.reconcile_resting",
        "feelies.kernel.orchestrator:Orchestrator._reconcile_resting_fills",
    ),
    (
        10,
        "E10.router_submit",
        "feelies.execution.backtest_router:BacktestOrderRouter.submit_order",
    ),
    (10, "E10.router_poll", "feelies.execution.backtest_router:BacktestOrderRouter.poll_acks"),
    # -- engine 11: observability -----------------------------------------
    (11, "E11.metric_record", "feelies.monitoring.in_memory:InMemoryMetricCollector.record"),
    (11, "E11.alert_emit", "feelies.monitoring.in_memory:InMemoryAlertManager.emit"),
    # -- measurement-only paths that run on the tick path -----------------
    (12, "X.net_shadow", "feelies.kernel.orchestrator:Orchestrator._record_net_shadow"),
    (12, "X.size_shadow", "feelies.kernel.orchestrator:Orchestrator._record_size_shadow"),
    (
        12,
        "X.arbitration_trace",
        "feelies.kernel.orchestrator:Orchestrator._trace_buffered_signals_arbitration",
    ),
    (
        12,
        "X.signal_order_trace",
        "feelies.kernel.orchestrator:Orchestrator._append_signal_order_trace",
    ),
]


# --------------------------------------------------------------------------
# Probe accounting
# --------------------------------------------------------------------------


@dataclass
class Acc:
    """Inclusive / exclusive nanosecond accumulator for one probe.

    ``child_calls`` is the count of nested probe invocations that occurred
    inside this probe's timed window.  It is the correction key: a probe's own
    wrapper cost falls *outside* its own ``t0..t1`` bracket and *inside* its
    parent's, so overhead must be charged to the parent per child call, not to
    the child per call.
    """

    engine: int
    label: str
    n: int = 0
    incl_ns: int = 0
    excl_ns: int = 0
    child_calls: int = 0
    samples: array = field(default_factory=lambda: array("q"))


STATS: dict[str, Acc] = {}
_SPANS: list[list[int]] = []
_ARMED = [False]
_RESOLVED: list[str] = []
_UNRESOLVED: list[str] = []
_MAX_SAMPLES = 400_000


def _reset() -> None:
    STATS.clear()
    _SPANS.clear()
    _ARMED[0] = False


def _wrap(engine: int, label: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    perf = time.perf_counter_ns

    def inner(*args: Any, **kwargs: Any) -> Any:
        if not _ARMED[0]:
            return fn(*args, **kwargs)
        span = [0, 0]
        _SPANS.append(span)
        t0 = perf()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = perf() - t0
            _SPANS.pop()
            if _SPANS:
                parent = _SPANS[-1]
                parent[0] += dt
                parent[1] += 1
            acc = STATS.get(label)
            if acc is None:
                acc = STATS[label] = Acc(engine=engine, label=label)
            acc.n += 1
            acc.incl_ns += dt
            acc.excl_ns += dt - span[0]
            acc.child_calls += span[1]
            if len(acc.samples) < _MAX_SAMPLES:
                acc.samples.append(dt)

    inner.__name__ = getattr(fn, "__name__", label)
    inner.__qualname__ = getattr(fn, "__qualname__", label)
    inner._arch_probe = label  # type: ignore[attr-defined]
    return inner


def _engine_for_module(module: str) -> int:
    best = (-1, 0)
    for prefix, engine in ENGINE_OF_MODULE:
        if module == prefix or module.startswith(prefix + "."):
            if len(prefix) > best[0]:
                best = (len(prefix), engine)
    return best[1]


_INSTALLED: set[str] = set()


def _install_direct_probes() -> None:
    import importlib

    if "direct" in _INSTALLED:
        return
    _INSTALLED.add("direct")
    for engine, label, target in DIRECT_PROBES:
        mod_name, _, attr = target.partition(":")
        cls_name, _, meth = attr.partition(".")
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            fn = cls.__dict__.get(meth)
            if fn is None:
                fn = getattr(cls, meth, None)
            if fn is None or not callable(fn) or isinstance(fn, property):
                _UNRESOLVED.append(f"{target}  (not a plain method)")
                continue
            setattr(cls, meth, _wrap(engine, label, fn))
            _RESOLVED.append(f"{label}={target}")
        except Exception as exc:  # noqa: BLE001 -- a miss is evidence, not a crash
            _UNRESOLVED.append(f"{target}  ({type(exc).__name__}: {exc})")


def _install_sensor_probes() -> None:
    """Probe every sensor estimator's ``update``.

    Engine 2's cost splits into registry plumbing and estimator math, and only
    the second is irreducible.  Discovered from the package rather than listed,
    so a new sensor is measured without editing this file.
    """
    import importlib
    import pkgutil

    import feelies.sensors.impl as impl_pkg

    if "sensors" in _INSTALLED:
        return
    _INSTALLED.add("sensors")
    for mod_info in pkgutil.iter_modules(impl_pkg.__path__):
        mod = importlib.import_module(f"feelies.sensors.impl.{mod_info.name}")
        for name, obj in vars(mod).items():
            if not isinstance(obj, type) or not name.endswith("Sensor"):
                continue
            fn = obj.__dict__.get("update")
            if fn is None or not callable(fn):
                continue
            setattr(obj, "update", _wrap(2, f"E2.sensor.{name}.update", fn))
            _RESOLVED.append(
                f"E2.sensor.{name}.update=feelies.sensors.impl.{mod_info.name}:{name}.update"
            )


def _install_subscribe_probe() -> None:
    """Wrap every bus handler at registration, whoever registers it."""
    from feelies.bus.event_bus import EventBus

    original = EventBus.subscribe
    if getattr(original, "_arch_probe_subscribe", False):
        return

    def subscribe(self: Any, event_type: Any, handler: Any) -> Any:
        mod = getattr(handler, "__module__", "?") or "?"
        qual = getattr(handler, "__qualname__", getattr(handler, "__name__", repr(handler)))
        # Bound methods carry the owning class in __qualname__ already.
        label = f"bus:{event_type.__name__}->{mod.rsplit('.', 1)[-1]}.{qual}"
        engine = _engine_for_module(mod)
        return original(self, event_type, _wrap(engine, label, handler))

    subscribe._arch_probe_subscribe = True  # type: ignore[attr-defined]
    EventBus.subscribe = subscribe  # type: ignore[method-assign]


CENSUS: dict[str, dict[str, int]] = {"publish": {}, "handlers": {}, "metric": {}}


def _install_census_probes() -> None:
    """Count, do not time: what gets published, and what gets recorded.

    Two questions P4 section 6 cannot answer statically:

    * how many events are published to a type with **zero** handlers -- the bus
      dispatches on the exact concrete type (``event_bus.py:65``), so a publish
      with no exact-type subscriber is pure cost;
    * which metric names are actually recorded, since most ``MetricEvent``
      constructions pass ``name=name`` from a variable and no AST scan can
      resolve them.

    Installed separately from the timing probes so a census run and a timing
    run never contaminate each other.
    """
    from feelies.bus.event_bus import EventBus
    from feelies.monitoring.in_memory import InMemoryMetricCollector

    if "census" in _INSTALLED:
        return
    _INSTALLED.add("census")

    orig_publish = EventBus.publish
    pub = CENSUS["publish"]
    hnd = CENSUS["handlers"]

    def publish(self: Any, event: Any) -> None:
        if _ARMED[0]:
            name = type(event).__name__
            pub[name] = pub.get(name, 0) + 1
            handlers = self._handlers.get(type(event))
            hnd[name] = (0 if handlers is None else len(handlers)) + len(self._global_handlers)
        orig_publish(self, event)

    EventBus.publish = publish  # type: ignore[method-assign]

    orig_record = InMemoryMetricCollector.record
    met = CENSUS["metric"]

    def record(self: Any, metric: Any) -> None:
        if _ARMED[0]:
            key = f"{metric.layer}.{metric.name}"
            met[key] = met.get(key, 0) + 1
        orig_record(self, metric)

    InMemoryMetricCollector.record = record  # type: ignore[method-assign]


def _install_arming_probe() -> None:
    """Arm accumulation for exactly the replay window."""
    from feelies.kernel.orchestrator import Orchestrator

    original = Orchestrator.run_backtest
    if getattr(original, "_arch_arming", False):
        return

    def run_backtest(self: Any, *a: Any, **kw: Any) -> Any:
        _ARMED[0] = True
        prof = PROFILER[0]
        if prof is not None:
            prof.enable()
        t0 = time.perf_counter_ns()
        try:
            return original(self, *a, **kw)
        finally:
            WALL["replay_ns"] = time.perf_counter_ns() - t0
            if prof is not None:
                prof.disable()
            _ARMED[0] = False

    run_backtest._arch_arming = True  # type: ignore[attr-defined]
    Orchestrator.run_backtest = run_backtest  # type: ignore[method-assign]


WALL: dict[str, int] = {}

# Set by --mode profile so cProfile brackets exactly the replay window.  Enabling
# it around the whole driver instead would fold cache deserialization and the EOD
# report into the "executed" set and make cold code look tick-hot.
PROFILER: list[Any] = [None]


# --------------------------------------------------------------------------
# Replay driver
# --------------------------------------------------------------------------


@dataclass
class RunResult:
    symbols: list[str]
    date: str
    config: str
    probed: bool
    n_quotes: int
    n_events: int
    replay_ns: int
    parity_hash: str
    fills: int
    report_tail: str
    stats: dict[str, dict[str, Any]]


def _run_replay(
    symbols: list[str], date: str, config_path: str, *, quiet: bool = True
) -> RunResult:
    import argparse as _argparse

    from feelies.core.platform_config import PlatformConfig
    from feelies.harness import compute_parity_hash, prepare_backtest_event_log
    from feelies.harness.backtest_cli import apply_backtest_session_dates_from_cli
    from feelies.storage.cache_replay import load_event_log_from_disk_cache
    import feelies.harness.backtest_runner as runner

    event_log, ingest_result, day_meta = load_event_log_from_disk_cache(symbols, date, date)
    config = PlatformConfig.from_yaml(Path(config_path))
    config = dc_replace(config, symbols=frozenset(s.upper() for s in symbols))
    config = apply_backtest_session_dates_from_cli(config, start_date=date, end_date=date)
    resolved = sorted(config.symbols)
    day_sources = [
        runner.DaySource(
            symbol=m.symbol,
            date=m.date,
            source=m.source,
            event_count=m.event_count,
            ingestion_health=m.ingestion_health,
        )
        for m in day_meta
    ]
    prep = prepare_backtest_event_log(config, event_log)
    config = runner._attach_day_source_provenance(config, resolved, day_sources)

    args = _argparse.Namespace(
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

    buf = io.StringIO()
    ctx = contextlib.redirect_stdout(buf) if quiet else contextlib.nullcontext()
    with ctx:
        outcome = runner._run_backtest_phases_2_7(
            args,
            event_log,
            ingest_result,
            day_sources,
            config,
            resolved,
            "+".join(resolved),
            date,
            time.monotonic(),
            prep=prep,
        )
    if outcome.exit_code != 0:
        raise RuntimeError(
            f"replay failed exit_code={outcome.exit_code}\n{buf.getvalue()[-4000:]}"
        )

    journal = outcome.orchestrator.trade_journal
    fills = len(list(journal.query())) if journal is not None else -1
    return RunResult(
        symbols=resolved,
        date=date,
        config=config_path,
        probed=bool(_RESOLVED),
        n_quotes=prep.n_quotes,
        n_events=ingest_result.events_ingested,
        replay_ns=WALL.get("replay_ns", -1),
        parity_hash=compute_parity_hash(outcome.orchestrator),
        fills=fills,
        report_tail=buf.getvalue(),
        stats=_snapshot_stats(prep.n_quotes),
    )


def _pct(values: array, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * (len(ordered) - 1)))
    return float(ordered[idx])


def _snapshot_stats(n_quotes: int) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for label, acc in STATS.items():
        s = acc.samples
        out[label] = {
            "engine": acc.engine,
            "calls": acc.n,
            "child_probe_calls": acc.child_calls,
            "calls_per_quote": round(acc.n / n_quotes, 6) if n_quotes else 0.0,
            "inclusive_ns_total": acc.incl_ns,
            "exclusive_ns_total": acc.excl_ns,
            "inclusive_ns_per_quote": round(acc.incl_ns / n_quotes, 3) if n_quotes else 0.0,
            "exclusive_ns_per_quote": round(acc.excl_ns / n_quotes, 3) if n_quotes else 0.0,
            "inclusive_ns_mean_per_call": round(acc.incl_ns / acc.n, 1) if acc.n else 0.0,
            "sampled": len(s),
            "p50_ns": _pct(s, 0.50),
            "p95_ns": _pct(s, 0.95),
            "p99_ns": _pct(s, 0.99),
            "max_ns": float(max(s)) if s else 0.0,
        }
    return out


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------


def mode_plain(symbols: list[str], date: str, config_path: str, repeats: int) -> dict[str, Any]:
    """Unprobed replays -- the total-cost truth, one timer only."""
    _install_arming_probe()
    runs: list[dict[str, Any]] = []
    for _ in range(repeats):
        _reset()
        r = _run_replay(symbols, date, config_path)
        runs.append(
            {
                "n_quotes": r.n_quotes,
                "n_events": r.n_events,
                "replay_ns": r.replay_ns,
                "ns_per_quote": round(r.replay_ns / r.n_quotes, 1),
                "parity_hash": r.parity_hash,
                "fills": r.fills,
            }
        )
        print(
            f"  plain: {r.n_quotes:,} quotes in {r.replay_ns / 1e9:.2f}s "
            f"= {r.replay_ns / r.n_quotes:,.0f} ns/quote  parity={r.parity_hash[:12]}",
            flush=True,
        )
    return {"runs": runs}


def mode_probed(symbols: list[str], date: str, config_path: str) -> RunResult:
    _install_subscribe_probe()
    _install_direct_probes()
    _install_sensor_probes()
    _install_arming_probe()
    _reset()
    r = _run_replay(symbols, date, config_path)
    print(
        f"  probed: {r.n_quotes:,} quotes in {r.replay_ns / 1e9:.2f}s "
        f"= {r.replay_ns / r.n_quotes:,.0f} ns/quote  parity={r.parity_hash[:12]}  "
        f"probes={len(STATS)}",
        flush=True,
    )
    return r


SENSOR_INFO: dict[str, Any] = {}


@contextlib.contextmanager
def _sensor_registration_recorder(*, prune: bool) -> Iterator[None]:
    """Record the sensor specs the platform ends up registering.

    Wraps the single pruning call so the count is observed rather than inferred,
    and costs nothing during the replay: ``maybe_prune_unused_sensors`` runs once
    at bootstrap.  ``prune=False`` also neutralises it, which is how the
    full-cardinality leg is produced -- see :func:`mode_sensorscale`.
    """
    import feelies.bootstrap as bootstrap

    original = bootstrap.maybe_prune_unused_sensors

    def recording(config: Any, registry: Any) -> Any:
        result = config if not prune else original(config, registry)
        SENSOR_INFO["declared"] = len(config.sensor_specs)
        SENSOR_INFO["registered"] = len(result.sensor_specs)
        SENSOR_INFO["ids"] = sorted(s.sensor_id for s in result.sensor_specs)
        # ``subscribes_to`` holds event *classes*, not names.
        SENSOR_INFO["on_quote"] = sorted(
            s.sensor_id
            for s in result.sensor_specs
            if any(getattr(t, "__name__", "") == "NBBOQuote" for t in s.subscribes_to)
        )
        return result

    bootstrap.maybe_prune_unused_sensors = recording  # type: ignore[assignment]
    try:
        yield
    finally:
        bootstrap.maybe_prune_unused_sensors = original  # type: ignore[assignment]


def mode_sensorscale(
    symbols: list[str], date: str, config_path: str, repeats: int
) -> dict[str, Any]:
    """Cost of the tick at the pruned sensor count vs every declared sensor.

    ``configs/bt_sig_benign_midcap.yaml`` sets ``prune_unused_sensors: true``, so
    the parity-oracle workload registers 4 of the 15 sensors declared in
    ``platform.yaml``.  Engine 2 is over half the measured tick cost at that S,
    which makes "what does engine 2 cost at full S" the most load-bearing
    unmeasured number in the phase-4 budget -- and pruning weakens as alphas
    accumulate, so full S is the direction the platform moves in, not a
    hypothetical.

    ``maybe_prune_unused_sensors`` is a pure config->config function called once
    (``bootstrap.py:245``), so neutralising it is the whole intervention: no
    source edit and no new config.  The alpha still declares and reads the same
    four dependencies, so a change in the parity hash between the two legs would
    be a finding -- sensor registration leaking into output -- rather than an
    artifact of the override.

    Unprobed on both legs: the question is total and marginal cost, and 57% probe
    overhead would swamp it.
    """
    _install_arming_probe()
    points: list[dict[str, Any]] = []
    for label, prune in (("pruned", True), ("all_declared", False)):
        best: dict[str, Any] | None = None
        with _sensor_registration_recorder(prune=prune):
            for _ in range(repeats):
                SENSOR_INFO.clear()
                _reset()
                r = _run_replay(symbols, date, config_path)
                row = {
                    "leg": label,
                    "n_quotes": r.n_quotes,
                    "n_events": r.n_events,
                    "replay_ns": r.replay_ns,
                    "ns_per_quote": round(r.replay_ns / r.n_quotes, 1) if r.n_quotes else 0.0,
                    "parity_hash": r.parity_hash,
                    "fills": r.fills,
                    "sensors_declared": SENSOR_INFO.get("declared", -1),
                    "sensors_registered": SENSOR_INFO.get("registered", -1),
                    "sensors_on_quote": len(SENSOR_INFO.get("on_quote", [])),
                    "sensor_ids": SENSOR_INFO.get("ids", []),
                }
                if best is None or row["ns_per_quote"] < best["ns_per_quote"]:
                    best = row
                print(
                    f"  {label:12s}: S={row['sensors_registered']:2d} "
                    f"({row['sensors_on_quote']} on quote)  "
                    f"{row['ns_per_quote']:>10,.0f} ns/quote  "
                    f"fills={r.fills}  parity={r.parity_hash[:12]}",
                    flush=True,
                )
        assert best is not None
        points.append(best)

    a, b = points
    d_all = b["sensors_registered"] - a["sensors_registered"]
    d_quote = b["sensors_on_quote"] - a["sensors_on_quote"]
    inc = b["ns_per_quote"] - a["ns_per_quote"]
    return {
        "points": points,
        "delta": {
            "extra_sensors_registered": d_all,
            "extra_sensors_on_quote": d_quote,
            "ns_per_quote_increase": round(inc, 1),
            "ratio": round(b["ns_per_quote"] / a["ns_per_quote"], 3) if a["ns_per_quote"] else 0.0,
            "marginal_ns_per_quote_per_quote_sensor": (
                round(inc / d_quote, 1) if d_quote else 0.0
            ),
            "parity_preserved": a["parity_hash"] == b["parity_hash"],
            "fills_preserved": a["fills"] == b["fills"],
        },
    }


def mode_profile(symbols: list[str], date: str, config_path: str) -> dict[str, Any]:
    """cProfile the replay to enumerate the functions that ACTUALLY execute.

    Used for the hot-path allow list (P4 section 1): a prohibited construct is a
    violation only if the function containing it runs on the tick path.  Timing
    from this mode is deliberately NOT reported -- only the executed set and
    call counts, which cProfile measures exactly.
    """
    import cProfile
    import pstats

    _install_arming_probe()
    _reset()
    prof = cProfile.Profile()
    PROFILER[0] = prof
    try:
        r = _run_replay(symbols, date, config_path)
    finally:
        PROFILER[0] = None
    stats = pstats.Stats(prof)
    executed: dict[str, dict[str, Any]] = {}
    src_root = str(SRC)
    for (fname, lineno, funcname), (cc, nc, tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        if not fname.startswith(src_root):
            continue
        rel = Path(fname).resolve().relative_to(Path(src_root).resolve()).as_posix()
        # Keyed by line as well as name: three functions named ``now_ns`` live in
        # core/clock.py, and collapsing them by name attributes the backtest
        # clock's 13 calls/quote to WallClock.now_ns, which never runs.
        executed[f"{rel}:{lineno}:{funcname}"] = {
            "file": rel,
            "line": lineno,
            "func": funcname,
            "ncalls": nc,
            "primitive_calls": cc,
        }
    return {
        "n_quotes": r.n_quotes,
        "parity_hash": r.parity_hash,
        "n_executed_functions": len(executed),
        "executed": executed,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def _derive(plain: dict[str, Any], probed: dict[str, Any]) -> dict[str, Any]:
    """Charge each probe for the wrapper cost of the child probes inside it.

    A probe's own wrapper cost (span push/pop, accumulator update) lies OUTSIDE
    its own ``t0..t1`` bracket and INSIDE its parent's, so the parent is where
    the overhead lands.  One per-call cost is calibrated from the plain/probed
    delta divided by the number of *nested* probe calls, then subtracted from
    each probe's exclusive time as ``child_probe_calls x per_call``.  Both
    columns stay in the file so the correction is auditable.
    """
    plain_best = min(run["ns_per_quote"] for run in plain["runs"])
    stats = probed["stats"]
    n_quotes = probed["n_quotes"]
    calls_per_quote = sum(v["calls_per_quote"] for v in stats.values())
    child_calls_per_quote = sum(v["child_probe_calls"] for v in stats.values()) / n_quotes
    delta = probed["ns_per_quote"] - plain_best
    per_call = delta / child_calls_per_quote if child_calls_per_quote else 0.0

    rows: dict[str, dict[str, Any]] = {}
    per_engine: dict[str, float] = {}
    for label, v in stats.items():
        children_per_quote = v["child_probe_calls"] / n_quotes
        corrected = v["exclusive_ns_per_quote"] - children_per_quote * per_call
        rows[label] = {
            "engine": v["engine"],
            "calls_per_quote": v["calls_per_quote"],
            "child_probe_calls_per_quote": round(children_per_quote, 3),
            "raw_exclusive_ns_per_quote": v["exclusive_ns_per_quote"],
            "corrected_exclusive_ns_per_quote": round(corrected, 1),
        }
        key = str(v["engine"])
        per_engine[key] = round(per_engine.get(key, 0.0) + corrected, 1)
    return {
        "plain_ns_per_quote_best": plain_best,
        "probed_ns_per_quote": probed["ns_per_quote"],
        "probe_calls_per_quote": round(calls_per_quote, 3),
        "nested_probe_calls_per_quote": round(child_calls_per_quote, 3),
        "calibrated_probe_overhead_ns_per_nested_call": round(per_call, 1),
        "corrected_total_ns_per_quote": round(sum(per_engine.values()), 1),
        "per_engine_corrected_exclusive_ns_per_quote": per_engine,
        "per_probe": rows,
    }


def mode_report(path: Path) -> int:
    """Print the per-probe and per-engine tables from an evidence file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "derived" in data:
        d = data["derived"]
        print(
            f"\nplain {d['plain_ns_per_quote_best']:,.0f} ns/quote | "
            f"probed {d['probed_ns_per_quote']:,.0f} | "
            f"overhead {d['calibrated_probe_overhead_ns_per_nested_call']:,.0f} ns x "
            f"{d['nested_probe_calls_per_quote']:.1f} nested calls/quote | "
            f"corrected total {d['corrected_total_ns_per_quote']:,.0f}"
        )
        print(f"\n{'engine':>6}  {'corrected excl ns/quote':>24}  {'share':>7}")
        tot = sum(d["per_engine_corrected_exclusive_ns_per_quote"].values())
        for engine, ns in sorted(
            d["per_engine_corrected_exclusive_ns_per_quote"].items(), key=lambda kv: -kv[1]
        ):
            print(f"{engine:>6}  {ns:24,.1f}  {100.0 * ns / tot:6.1f}%")
        print(
            f"\n{'probe':58s} {'eng':>3} {'calls/q':>9} {'kids/q':>8} "
            f"{'raw':>10} {'corrected':>10}"
        )
        for label, v in sorted(
            d["per_probe"].items(), key=lambda kv: -kv[1]["corrected_exclusive_ns_per_quote"]
        ):
            print(
                f"{label[:58]:58s} {v['engine']:3d} {v['calls_per_quote']:9.3f} "
                f"{v['child_probe_calls_per_quote']:8.2f} "
                f"{v['raw_exclusive_ns_per_quote']:10.1f} "
                f"{v['corrected_exclusive_ns_per_quote']:10.1f}"
            )

    blocks: list[tuple[str, dict[str, Any], int]] = []
    if "probed" in data:
        blocks.append(("probed", data["probed"]["stats"], data["probed"]["n_quotes"]))
    for point in data.get("scale", {}).get("points", []):
        blocks.append((f"N={point['n_symbols']}", point["stats"], point["n_quotes"]))

    for name, stats, n_quotes in blocks:
        print(f"\n=== {name}  ({n_quotes:,} quotes) ===")
        print(
            f"{'probe':60s} {'eng':>3} {'calls/q':>9} {'excl ns/q':>10} "
            f"{'incl ns/q':>10} {'ns/call':>9} {'p99 ns':>9}"
        )
        total = 0.0
        per_engine: dict[int, float] = {}
        for label, v in sorted(stats.items(), key=lambda kv: -kv[1]["exclusive_ns_per_quote"]):
            total += v["exclusive_ns_per_quote"]
            per_engine[v["engine"]] = (
                per_engine.get(v["engine"], 0.0) + v["exclusive_ns_per_quote"]
            )
            print(
                f"{label[:60]:60s} {v['engine']:3d} {v['calls_per_quote']:9.3f} "
                f"{v['exclusive_ns_per_quote']:10.1f} {v['inclusive_ns_per_quote']:10.1f} "
                f"{v['inclusive_ns_mean_per_call']:9.1f} {v['p99_ns']:9.0f}"
            )
        print(f"\n  {'engine':>6}  {'excl ns/quote':>14}  {'share of attributed':>20}")
        for engine in sorted(per_engine):
            share = 100.0 * per_engine[engine] / total if total else 0.0
            print(f"  {engine:>6}  {per_engine[engine]:14.1f}  {share:19.1f}%")
        print(f"  {'TOTAL':>6}  {total:14.1f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode",
        default="both",
        choices=[
            "plain",
            "probed",
            "both",
            "scale",
            "sensorscale",
            "profile",
            "census",
            "report",
        ],
        help="both = plain + probed + parity comparison (default)",
    )
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--date", default=None)
    ap.add_argument("--config", default=BASE_CONFIG)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=None, help="evidence file name (default perf.json)")
    args = ap.parse_args(argv)

    symbols = args.symbols or BASE_SYMBOLS
    date = args.date or BASE_DATE
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    if args.mode == "report":
        return mode_report(EVIDENCE / (args.out or "perf.json"))

    payload: dict[str, Any] = {
        "measurement": {
            "tool": "tools/arch/perfmeasure.py",
            "mode": args.mode,
            "symbols": symbols,
            "date": date,
            "config": args.config,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": (
                "Replay runs with GC disabled and (on Windows) HIGH_PRIORITY_CLASS, "
                "because feelies.harness.backtest_runner sets both around "
                "orchestrator.run_backtest(). Numbers are therefore the harness's "
                "own conditions, not a bare interpreter's."
            ),
        }
    }

    if args.mode == "profile":
        payload["profile"] = mode_profile(symbols, date, args.config)
        out = args.out or "hotpath_executed.json"
    elif args.mode == "census":
        _install_census_probes()
        _install_arming_probe()
        _reset()
        r = _run_replay(symbols, date, args.config)
        pub = CENSUS["publish"]
        hnd = CENSUS["handlers"]
        dead = {k: v for k, v in sorted(pub.items()) if hnd.get(k, 0) == 0}
        payload["census"] = {
            "n_quotes": r.n_quotes,
            "parity_hash": r.parity_hash,
            "fills": r.fills,
            "publishes_total": sum(pub.values()),
            "publish_by_type": {
                k: {"publishes": v, "handlers": hnd.get(k, 0)} for k, v in sorted(pub.items())
            },
            "publishes_with_zero_handlers": sum(dead.values()),
            "types_with_zero_handlers": dead,
            "metric_records_total": sum(CENSUS["metric"].values()),
            "metric_by_name": dict(sorted(CENSUS["metric"].items())),
        }
        c = payload["census"]
        print(
            f"  census: {c['publishes_total']:,} publishes over {len(pub)} types; "
            f"{c['publishes_with_zero_handlers']:,} to types with zero handlers; "
            f"{c['metric_records_total']:,} metric records over "
            f"{len(CENSUS['metric'])} names",
            flush=True,
        )
        out = args.out or "perf_census.json"
    elif args.mode == "sensorscale":
        payload["sensorscale"] = mode_sensorscale(symbols, date, args.config, args.repeats)
        d = payload["sensorscale"]["delta"]
        print(
            f"  +{d['extra_sensors_on_quote']} quote sensors: "
            f"{d['ns_per_quote_increase']:+,.0f} ns/quote ({d['ratio']:.2f}x), "
            f"{d['marginal_ns_per_quote_per_quote_sensor']:,.0f} ns/quote per sensor; "
            f"parity preserved={d['parity_preserved']}",
            flush=True,
        )
        out = args.out or "perf_sensorscale.json"
    elif args.mode == "scale":
        # One process per cardinality would be cleaner, but probes are installed
        # once and the arming flag brackets each replay, so a single process is
        # fine and keeps the host state identical between the two points.
        _install_subscribe_probe()
        _install_direct_probes()
        _install_sensor_probes()
        _install_arming_probe()
        points = []
        for syms in ([SCALE_SYMBOLS[0]], SCALE_SYMBOLS):
            _reset()
            r = _run_replay(syms, args.date or SCALE_DATE, args.config)
            print(
                f"  scale N={len(r.symbols)}: {r.n_quotes:,} quotes in "
                f"{r.replay_ns / 1e9:.2f}s = {r.replay_ns / r.n_quotes:,.0f} ns/quote",
                flush=True,
            )
            points.append(
                {
                    "n_symbols": len(r.symbols),
                    "symbols": r.symbols,
                    "n_quotes": r.n_quotes,
                    "n_events": r.n_events,
                    "replay_ns": r.replay_ns,
                    "ns_per_quote": round(r.replay_ns / r.n_quotes, 1),
                    "parity_hash": r.parity_hash,
                    "fills": r.fills,
                    "stats": r.stats,
                }
            )
        payload["scale"] = {"date": args.date or SCALE_DATE, "points": points}
        out = args.out or "perf_scale.json"
    else:
        if args.mode in ("plain", "both"):
            payload["plain"] = mode_plain(symbols, date, args.config, args.repeats)
        if args.mode in ("probed", "both"):
            r = mode_probed(symbols, date, args.config)
            payload["probed"] = {
                "n_quotes": r.n_quotes,
                "n_events": r.n_events,
                "replay_ns": r.replay_ns,
                "ns_per_quote": round(r.replay_ns / r.n_quotes, 1),
                "parity_hash": r.parity_hash,
                "fills": r.fills,
                "probes_resolved": sorted(_RESOLVED),
                "probes_unresolved": sorted(_UNRESOLVED),
                "stats": r.stats,
            }
            tail = ROOT / "tools" / "arch" / "evidence" / "perf_report_tail.txt"
            tail.write_text(r.report_tail, encoding="utf-8")
        if args.mode == "both":
            plain_hashes = {run["parity_hash"] for run in payload["plain"]["runs"]}
            probed_hash = payload["probed"]["parity_hash"]
            same = plain_hashes == {probed_hash}
            plain_best = min(run["replay_ns"] for run in payload["plain"]["runs"])
            payload["determinism"] = {
                "plain_parity_hashes": sorted(plain_hashes),
                "probed_parity_hash": probed_hash,
                "measurement_perturbs_output": not same,
                "probe_overhead_pct": round(
                    100.0 * (payload["probed"]["replay_ns"] - plain_best) / plain_best, 2
                ),
            }
            print(
                f"  determinism: probed==plain parity_hash -> {same}; "
                f"probe overhead {payload['determinism']['probe_overhead_pct']:.1f}%",
                flush=True,
            )
            payload["derived"] = _derive(payload["plain"], payload["probed"])
            print(
                "  calibrated probe overhead "
                f"{payload['derived']['calibrated_probe_overhead_ns_per_nested_call']:.0f} "
                f"ns per nested call over "
                f"{payload['derived']['nested_probe_calls_per_quote']:.1f} nested calls/quote",
                flush=True,
            )
        out = args.out or "perf.json"

    payload.pop("report_tail", None)
    if "plain" in payload:
        payload["plain"].pop("report_tail", None)
    dest = EVIDENCE / out
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {dest.relative_to(ROOT).as_posix()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
