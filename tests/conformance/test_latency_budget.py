"""X10 — per-engine p99 latency budget; timings are compared, not ignored.

G43 (P0): ``_tick_timings`` is written at three sites, read once in
``Orchestrator._finalize_tick``, published as ``MetricEvent``s, and never
compared to a budget.  Inv-11 has no latency-axis implementation until
that comparison exists and is a p99-over-window predicate, not a mean.
"""

from __future__ import annotations

import ast
from pathlib import Path

from feelies.core.clock import SimulatedClock
from feelies.core.platform_config import ENGINE_LATENCY_BUDGETS, EngineLatencyBudget
from feelies.kernel import orchestrator as orchestrator_mod
from feelies.monitoring.in_memory import InMemoryKillSwitch
from feelies.monitoring.latency_budget import (
    _apply_breach_response,
    _BudgetStatus,
    _LatencyBudgetMonitor,
    _p99,
)

from tests.conformance.harness.fault_injector import FaultInjector

_ORCH_PATH = Path(orchestrator_mod.__file__).resolve()

HOT_PATH_TIMING_KEYS = frozenset(
    {
        "sensor_fanout_ns",
        "sm_transition_ns",
        "signal_evaluate_ns",
        "risk_check_ns",
        "tick_to_decision_latency_ns",
    }
)


def _finalize_tick() -> ast.FunctionDef:
    tree = ast.parse(_ORCH_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Orchestrator":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_finalize_tick":
                    return item
    raise AssertionError("Orchestrator._finalize_tick not found")


def test_x10_tick_timings_are_compared_to_a_budget() -> None:
    """G43: the named read site must compare timings, not only publish them.

    The two asserts before the comparison check prove this executed against
    ``_finalize_tick`` as PROBLEM named it (``_tick_timings`` read,
    ``MetricEvent`` published).  A failure of the third assert is therefore
    "no comparison exists", not "wrong function" or "table missing".
    """
    fn = _finalize_tick()
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    constants = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)}

    assert "_tick_timings" in constants, (
        "_finalize_tick does not read _tick_timings — not the site PROBLEM named"
    )
    assert "MetricEvent" in names, (
        "_finalize_tick does not publish MetricEvent — not the site PROBLEM named"
    )

    compared = "_latency_monitor" in attrs or bool(
        names
        & {
            "_latency_monitor",
            "ENGINE_LATENCY_BUDGETS",
            "LatencyBreach",
            "_apply_breach_response",
        }
    )
    assert compared, (
        "no comparison exists: _tick_timings is published as MetricEvents "
        "and never compared to a budget"
    )


def test_x10_every_hot_path_engine_has_a_budget_entry() -> None:
    """(i) Closure: every measured hot-path engine is in the table."""
    orch_src = _ORCH_PATH.read_text(encoding="utf-8")
    for key in HOT_PATH_TIMING_KEYS:
        assert key in orch_src, f"hot-path key {key!r} is not in orchestrator.py"
    table_engines = {entry.engine for entry in ENGINE_LATENCY_BUDGETS}
    missing = sorted(HOT_PATH_TIMING_KEYS - table_engines)
    assert not missing, f"hot-path engines missing a budget entry: {missing}"
    assert ENGINE_LATENCY_BUDGETS, "budget table is empty"


def test_x10_each_entry_names_statistic_and_window() -> None:
    """(ii) Each entry declares statistic=p99 and a rolling event window."""
    assert ENGINE_LATENCY_BUDGETS, "budget table is empty"
    for entry in ENGINE_LATENCY_BUDGETS:
        assert entry.statistic == "p99", (
            f"{entry.engine}: statistic must be p99, got {entry.statistic!r}"
        )
        assert entry.window_events >= 1, (
            f"{entry.engine}: window_events must be a declared rolling count, "
            f"got {entry.window_events}"
        )
        assert entry.budget_ns > 0, f"{entry.engine}: budget_ns must be positive"


def test_x10_p99_over_window_breaches_when_mean_is_under() -> None:
    """(iii) Mean under budget and p99 over must breach.

    A mean-based predicate would pass this distribution. Without this
    case, X10 would accept a table of entries that never detects the
    condition G43 exists to catch.
    """
    window = 100
    budget_ns = 50_000
    n_low, low_ns = 98, 1_000
    n_high, high_ns = 2, 1_000_000
    samples = [low_ns] * n_low + [high_ns] * n_high
    assert len(samples) == window

    mean = sum(samples) / len(samples)
    observed = _p99(samples)
    assert mean < budget_ns, f"setup: mean {mean} must be under budget {budget_ns}"
    assert observed > budget_ns, f"setup: p99 {observed} must be over budget {budget_ns}"

    entry = EngineLatencyBudget(
        engine="risk_check_ns",
        budget_ns=budget_ns,
        statistic="p99",
        window_events=window,
    )
    monitor = _LatencyBudgetMonitor((entry,))
    emitted: list[object] = []
    for i, sample in enumerate(samples):
        emitted.extend(
            monitor.observe(
                {"risk_check_ns": sample},
                timestamp_ns=i,
                correlation_id="x10-iii",
            )
        )
    assert monitor._status("risk_check_ns") is _BudgetStatus.BREACH
    assert emitted, (
        "p99 was over budget while the mean was under, and no LatencyBreach "
        "fired — the predicate is not p99-over-window"
    )
    breach = emitted[-1]
    assert breach.sequence == 0
    assert breach.statistic == "p99"
    assert breach.window_events == window
    assert breach.observed_ns == observed
    assert breach.budget_ns == budget_ns


def test_x10_incomplete_window_is_never_seen_not_within_budget() -> None:
    """Fewer than a window of samples is never-seen, never within budget."""
    entry = EngineLatencyBudget(
        engine="risk_check_ns",
        budget_ns=1,
        statistic="p99",
        window_events=100,
    )
    monitor = _LatencyBudgetMonitor((entry,))
    emitted = []
    for i in range(99):
        emitted.extend(
            monitor.observe(
                {"risk_check_ns": 10_000_000},
                timestamp_ns=i,
                correlation_id="never-seen",
            )
        )
    assert emitted == []
    assert monitor._status("risk_check_ns") is _BudgetStatus.NEVER_SEEN
    assert monitor._status("risk_check_ns") is not _BudgetStatus.WITHIN


def test_x10_harn2_slow_engine_breach_replays_without_remeasuring() -> None:
    """HARN-2 injects a slow engine; replay of the record does not re-measure."""
    delay_ns = 10_000_000
    window = 100
    budget_ns = 3_000_000
    clock = SimulatedClock(0)
    injector = FaultInjector(clock=clock)
    injector.slow_engine("risk_check_ns", delay_ns)
    slow = injector.wrap("risk_check_ns", lambda: None)

    entry = EngineLatencyBudget(
        engine="risk_check_ns",
        budget_ns=budget_ns,
        statistic="p99",
        window_events=window,
    )
    live = _LatencyBudgetMonitor((entry,))
    log = []
    for i in range(window):
        t0 = clock.now_ns()
        slow()
        sample = clock.now_ns() - t0
        log.extend(
            live.observe(
                {"risk_check_ns": sample},
                timestamp_ns=clock.now_ns(),
                correlation_id=f"harn2-{i}",
            )
        )

    assert injector.injections, "HARN-2 applied no delay — a breach here would be unprovoked"
    assert all(inj.delay_ns == delay_ns for inj in injector.injections)
    assert log, "HARN-2 slow engine did not write a LatencyBreach"
    assert all(event.sequence == 0 for event in log)
    assert live._status("risk_check_ns") is _BudgetStatus.BREACH

    replay_ks = InMemoryKillSwitch()
    replay = _LatencyBudgetMonitor((entry,))
    assert replay._status("risk_check_ns") is _BudgetStatus.NEVER_SEEN
    for event in log:
        _apply_breach_response(replay_ks, event)
    assert replay_ks.is_active, "replay of the recorded breach did not escalate"
    assert replay._status("risk_check_ns") is _BudgetStatus.NEVER_SEEN, (
        "replay re-measured: the fresh monitor is no longer never-seen"
    )
    assert replay.observe({}, timestamp_ns=0, correlation_id="replay") == ()
