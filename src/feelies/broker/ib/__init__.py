"""Interactive Brokers Gateway adapter (paper @ 4002 / live @ 4001).

Wraps the official ``ibapi`` TWS API behind the platform's typed
:class:`OrderRouter` / :class:`ExecutionBackend` contracts.  The
adapter runs the connection on dedicated threads and exposes only
thread-safe queues to the orchestrator's main loop — IB callbacks
NEVER touch the event bus or orchestrator state.
"""

from feelies.broker.ib.connection import IBFillEvent, IBGatewayConnection
from feelies.broker.ib.contracts import stock_contract
from feelies.broker.ib.router import IBOrderRouter

__all__ = [
    "IBFillEvent",
    "IBGatewayConnection",
    "IBOrderRouter",
    "stock_contract",
]
