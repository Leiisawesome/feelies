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

from feelies.core.kill_switch import (
    KillSwitch as KillSwitch,
    observe_kill_switch as observe_kill_switch,
)
