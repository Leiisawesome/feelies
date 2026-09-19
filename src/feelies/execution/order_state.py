"""Order lifecycle state machine (Section V of the system diagram).

Each order has its own state machine instance.  Every transition
is triggered by an explicit event.  No inferred states.

The backtest engine must simulate this same state machine.
If live order transitions deviate from simulated expectations,
flag structural drift.
"""

from __future__ import annotations

from feelies.core.order_state import OrderState as OrderState
from feelies.core.order_state import create_order_state_machine as create_order_state_machine
