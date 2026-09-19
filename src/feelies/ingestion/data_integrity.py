"""Per-symbol data integrity state machine (Section VII of the system diagram).

Each symbol stream maintains its own health state.
If CORRUPTED during PAPER_TRADING_MODE, the global macro state
transitions to DEGRADED — execution stops.
"""

from __future__ import annotations

from feelies.core.clock import Clock
from feelies.core.data_health import (
    DataHealth as DataHealth,
    HaltSignal as HaltSignal,
    classify_halt_status as classify_halt_status,
    _sync_halt_store_and_health as _sync_halt_store_and_health,
    _HaltTradeability as _HaltTradeability,
    _require_halt_authority as _require_halt_authority,
)
from feelies.core.state_machine import StateMachine

_DATA_TRANSITIONS: dict[DataHealth, frozenset[DataHealth]] = {
    DataHealth.HEALTHY: frozenset(
        {
            DataHealth.GAP_DETECTED,
            DataHealth.HALTED,
            DataHealth.CORRUPTED,
        }
    ),
    DataHealth.GAP_DETECTED: frozenset(
        {
            DataHealth.HEALTHY,  # gap resolved
            DataHealth.HALTED,  # halt declared mid-gap
            DataHealth.CORRUPTED,  # gap unresolvable
        }
    ),
    DataHealth.HALTED: frozenset(
        {
            DataHealth.HEALTHY,  # halt resolved (resume marker)
            DataHealth.CORRUPTED,  # stream corrupted during halt
        }
    ),
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
