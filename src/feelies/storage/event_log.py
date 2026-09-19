"""Event log — persistent, append-only record of all events.

Enables deterministic replay (invariant 5) and full provenance (invariant 13).
Every decision is traceable to an event in this log.
"""

from __future__ import annotations

from feelies.core.event_log import EventLog as EventLog
