"""IdleTick sentinel — data-path control signal for live feeds.

Yielded by :class:`MarketDataSource` implementations when no market
event arrives within their internal poll timeout.  The orchestrator's
``_run_pipeline`` consumes the sentinel to drive the async fill drain
(see :meth:`Orchestrator._drain_async_fills`) so broker-pushed fills
from :class:`IBOrderRouter` are not stranded on illiquid symbols or
between WS frames.

``IdleTick`` is intentionally **not** an :class:`Event`:

* never published on the :class:`EventBus`,
* never appended to the :class:`EventLog`,
* never carries a correlation id or sequence number.

It is a data-path control signal only. The micro state machine does not advance
for idle ticks.
"""

from __future__ import annotations

from feelies.core.idle_tick import IdleTick as IdleTick
