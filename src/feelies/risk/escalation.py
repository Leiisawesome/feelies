"""Risk escalation state machine (Section VI of the system diagram).

Independent but dominant — no strategy layer can bypass this.
Only the risk engine can trigger LOCKED.
Only human override + system audit can unlock.

Safety controls only tighten autonomously; loosening requires
human re-authorization (invariant 11).
"""

from __future__ import annotations

from feelies.core.escalation import (
    RiskLevel as RiskLevel,
    create_risk_escalation_machine as create_risk_escalation_machine,
)
