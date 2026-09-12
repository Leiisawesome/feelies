"""PaperSessionRecorder — paper-session forensic buffer protocol.

The Protocol lives in core so kernel can name it without importing the
monitoring package.
"""

from __future__ import annotations

from typing import Any, Protocol


class PaperSessionRecorder(Protocol):
    """Paper-mode session recorder. Kernel names record_idle_tick and record_timing."""

    def record_idle_tick(self) -> None:
        """Count one idle tick."""
        ...

    def record_timing(
        self,
        *,
        kind: str,
        duration_ns: int,
        correlation_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a timing row."""
        ...
