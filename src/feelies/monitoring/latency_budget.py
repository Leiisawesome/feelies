"""p99 per-engine latency budget predicate and kill-switch response (G43).

Comparison is live/paper only. Replay consumes recorded ``LatencyBreach``
events and never re-measures. An incomplete window is never-seen, never
within budget.
"""

from __future__ import annotations

from feelies.core.latency_budget import (
    _BudgetStatus as _BudgetStatus,
    _LatencyBudgetMonitor as _LatencyBudgetMonitor,
    _apply_breach_response as _apply_breach_response,
    _p99 as _p99,
)
