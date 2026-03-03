"""Kill switch protocol — emergency trading halt.

The kill switch is the last-resort safety mechanism.  When activated:
  1. All open orders are cancelled
  2. All positions are flattened (or frozen, depending on mode)
  3. No new orders can be submitted
  4. Re-enabling requires manual human authorization

Kill switch activation is irreversible without human intervention.
The system cannot self-recover from a kill switch (invariant 11:
safety controls only tighten autonomously; loosening requires
human re-authorization).

Ownership boundary: the monitoring layer (via alert manager) or
a manual operator activates the kill switch.  The execution layer
enforces it (cancels orders, blocks submissions).  The risk engine's
escalation state machine is a separate, complementary mechanism —
both can halt trading independently.
"""

from __future__ import annotations

from typing import Protocol


class KillSwitch(Protocol):
    """Emergency trading halt — irreversible without manual re-enable.

    Any layer can check kill switch state via ``is_active``.
    Only the alert manager (EMERGENCY severity), the risk engine
    (via escalation), or a manual operator can activate it.

    Failure mode: fail-safe.  If the kill switch mechanism itself
    fails, the system defaults to halted (is_active returns True).
    """

    @property
    def is_active(self) -> bool:
        """Whether the kill switch is currently engaged."""
        ...

    def activate(self, reason: str, *, activated_by: str = "automated") -> None:
        """Activate the kill switch.

        Emits a ``KillSwitchActivation`` event on the bus.
        Irreversible without manual re-enable via ``reset()``.
        """
        ...

    def reset(self, *, operator: str, audit_token: str) -> None:
        """Re-enable trading after kill switch activation.

        Requires human authorization.  Audit token is logged for
        provenance (invariant 13).
        """
        ...
