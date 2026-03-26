"""IntentSet — per-tick multi-alpha evaluation result.

Collects intents, signals, and risk verdicts from all active alphas
for a single tick.  Carries FORCE_FLATTEN escalation when the
aggregate risk engine triggers platform-wide lockdown.

When ``force_flatten`` is True the orchestrator must fire the safety
cascade (_escalate_risk) immediately — no aggregation, no order
submission.  The ``intents`` tuple is empty in this case.
"""

from __future__ import annotations

from dataclasses import dataclass

from feelies.core.events import RiskVerdict, Signal
from feelies.execution.intent import OrderIntent


@dataclass(frozen=True, kw_only=True)
class IntentSet:
    """Per-alpha intents for a single tick, preserving full provenance."""

    timestamp_ns: int
    correlation_id: str
    symbol: str
    intents: tuple[OrderIntent, ...]
    signals: tuple[Signal, ...]
    verdicts: dict[str, RiskVerdict]

    force_flatten: bool = False
    force_flatten_verdict: RiskVerdict | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.intents) == 0 and not self.force_flatten
