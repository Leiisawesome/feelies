"""Structured logging protocol — one log stream per layer, JSON lines only.

No unstructured prints.  Every log entry carries layer identity,
optional correlation ID for end-to-end tracing, and structured
fields for machine parsing.

All timestamps injected by the implementation via the injectable
clock (invariant 10) — never raw ``datetime.now()``.

Tradeoff: structured JSON logs sacrifice human readability of raw
output for machine parseability and correlation.  Human-readable
views are rendered by the monitoring dashboard, not emitted inline.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Protocol


class LogLevel(Enum):
    """Structured log severity levels."""

    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


class StructuredLogger(Protocol):
    """Layer-scoped structured logger.

    Each layer receives its own logger instance scoped to that layer.
    Output format is JSON lines — one JSON object per log entry.

    Failure mode: degrade.  Logging failures never crash the pipeline.
    If the log sink is unavailable, entries are buffered or dropped
    with a metric counter incremented.
    """

    @property
    def layer(self) -> str:
        """The layer this logger is scoped to."""
        ...

    def log(
        self,
        level: LogLevel,
        message: str,
        *,
        correlation_id: str = "",
        fields: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured log entry.

        Timestamp is injected by the implementation from the
        injectable clock.
        """
        ...
