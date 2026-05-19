"""Per-symbol data integrity state machine (Section VII of the system diagram).

Each symbol stream maintains its own health state.
If CORRUPTED during LIVE_TRADING_MODE, the global macro state
transitions to DEGRADED — execution stops.
"""

from __future__ import annotations

from enum import Enum, auto

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class DataHealth(Enum):
    """Per-symbol data stream health.

    ``CORRUPTED`` is a terminal state by design: once a symbol stream is
    corrupted, the only recovery path is a manual restart.  The operator
    runbook should restart the normalizer for affected symbols.
    """

    HEALTHY = auto()
    GAP_DETECTED = auto()
    CORRUPTED = auto()


_DATA_TRANSITIONS: dict[DataHealth, frozenset[DataHealth]] = {
    DataHealth.HEALTHY: frozenset({
        DataHealth.GAP_DETECTED,
        DataHealth.CORRUPTED,
    }),
    DataHealth.GAP_DETECTED: frozenset({
        DataHealth.HEALTHY,     # gap resolved
        DataHealth.CORRUPTED,   # gap unresolvable
    }),
    DataHealth.CORRUPTED: frozenset(),  # terminal — restart required
}


def create_data_integrity_machine(
    symbol: str,
    clock: Clock,
    *,
    channel: str | None = None,
) -> StateMachine[DataHealth]:
    """Create a data integrity tracker for a single symbol (and optional channel).

    ``channel`` distinguishes quote vs trade sequence spaces on the same symbol
    so gap / recovery on one feed does not false-clear the other.
    """
    label = f"{symbol}:{channel}" if channel else symbol
    return StateMachine(
        name=f"data_integrity:{label}",
        initial_state=DataHealth.HEALTHY,
        transitions=_DATA_TRANSITIONS,
        clock=clock,
    )
