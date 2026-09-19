"""Risk escalation state machine (Section VI of the system diagram).

Independent but dominant — no strategy layer can bypass this.
Only the risk engine can trigger LOCKED.
Only human override + system audit can unlock.

Safety controls only tighten autonomously; loosening requires
human re-authorization (invariant 11).
"""

from __future__ import annotations

from enum import Enum, auto

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class RiskLevel(Enum):
    """Risk escalation levels.  Monotonically tightening until human intervention."""

    NORMAL = auto()
    WARNING = auto()
    BREACH_DETECTED = auto()
    FORCED_FLATTEN = auto()
    LOCKED = auto()


_RISK_TRANSITIONS: dict[RiskLevel, frozenset[RiskLevel]] = {
    RiskLevel.NORMAL: frozenset(
        {
            RiskLevel.WARNING,
        }
    ),
    # R1 → R2 only.  Once WARNING, escalation is forward-only.
    # Only human-authorized R4-to-R0 unlock can de-escalate.
    RiskLevel.WARNING: frozenset(
        {
            RiskLevel.BREACH_DETECTED,
        }
    ),
    RiskLevel.BREACH_DETECTED: frozenset(
        {
            RiskLevel.FORCED_FLATTEN,
        }
    ),
    RiskLevel.FORCED_FLATTEN: frozenset(
        {
            RiskLevel.LOCKED,
        }
    ),
    # LOCKED-to-NORMAL requires human authorization.
    RiskLevel.LOCKED: frozenset(
        {
            RiskLevel.NORMAL,
        }
    ),
}


def create_risk_escalation_machine(clock: Clock) -> StateMachine[RiskLevel]:
    """Create the risk escalation state machine, starting at NORMAL."""
    return StateMachine(
        name="risk_escalation",
        initial_state=RiskLevel.NORMAL,
        transitions=_RISK_TRANSITIONS,
        clock=clock,
    )
