"""p99 per-engine latency budget predicate and kill-switch response (G43).

Comparison is live/paper only. Replay consumes recorded ``LatencyBreach``
events and never re-measures. An incomplete window is never-seen, never
within budget.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from enum import Enum, auto
from math import ceil

from feelies.core.events import LatencyBreach
from feelies.core.gate_registry import record_verdict
from feelies.core.platform_config import ENGINE_LATENCY_BUDGETS, EngineLatencyBudget
from feelies.monitoring.kill_switch import KillSwitch


class _BudgetStatus(Enum):
    NEVER_SEEN = auto()
    WITHIN = auto()
    BREACH = auto()


def _p99(samples: Sequence[int]) -> int:
    """Nearest-rank p99 over a full window. Undefined for an empty sequence."""
    if not samples:
        raise ValueError("p99 of an empty window is undefined")
    ordered = sorted(samples)
    rank = max(1, ceil(0.99 * len(ordered)))
    return ordered[rank - 1]


def _apply_breach_response(
    kill_switch: KillSwitch | None,
    event: LatencyBreach,
) -> None:
    """Kill-switch escalation on a recorded breach. Does not re-measure."""
    if kill_switch is None:
        return
    kill_switch.activate(
        reason=f"latency_budget_breach:{event.engine}",
        activated_by="latency_budget",
    )


class _LatencyBudgetMonitor:
    """Rolling p99 windows keyed by engine. Fail-closed on a short window."""

    def __init__(
        self,
        budgets: Sequence[EngineLatencyBudget] = ENGINE_LATENCY_BUDGETS,
    ) -> None:
        self._budgets: dict[str, EngineLatencyBudget] = {b.engine: b for b in budgets}
        self._windows: dict[str, deque[int]] = {
            b.engine: deque(maxlen=b.window_events) for b in budgets
        }

    def observe(
        self,
        timings_ns: Mapping[str, int],
        *,
        timestamp_ns: int,
        correlation_id: str,
    ) -> tuple[LatencyBreach, ...]:
        """Record this tick's samples. Emit a breach per engine whose p99 is over.

        Fewer than ``window_events`` samples is never-seen: not within budget
        and not a computed p99-over breach.
        """
        emitted: list[LatencyBreach] = []
        for engine, raw in timings_ns.items():
            budget = self._budgets.get(engine)
            if budget is None:
                continue
            window = self._windows[engine]
            window.append(int(raw))
            if len(window) < budget.window_events:
                record_verdict("RT.LATENCY_BUDGET", "UNKNOWN", engine)
                continue
            observed = _p99(window)
            if observed > budget.budget_ns:
                record_verdict("RT.LATENCY_BUDGET", "FAIL", engine)
                emitted.append(
                    LatencyBreach(
                        timestamp_ns=timestamp_ns,
                        correlation_id=correlation_id,
                        sequence=0,
                        source_layer="kernel",
                        engine=engine,
                        statistic=budget.statistic,
                        window_events=budget.window_events,
                        budget_ns=budget.budget_ns,
                    )
                )
            else:
                record_verdict("RT.LATENCY_BUDGET", "PASS", engine)
        return tuple(emitted)

    def _status(self, engine: str) -> _BudgetStatus:
        budget = self._budgets[engine]
        window = self._windows[engine]
        if len(window) < budget.window_events:
            return _BudgetStatus.NEVER_SEEN
        if _p99(window) > budget.budget_ns:
            return _BudgetStatus.BREACH
        return _BudgetStatus.WITHIN
