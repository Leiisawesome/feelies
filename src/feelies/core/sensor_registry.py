"""SensorRegistry — Layer-1 sensor collection protocol.

The Protocol lives in core so kernel can name it without importing the
sensors package.
"""

from __future__ import annotations

from typing import Protocol


class SensorRegistry(Protocol):
    """Incremental Layer-1 observers; kernel only asks whether any are registered."""

    def is_empty(self) -> bool:
        """True iff no sensors have been registered."""
        ...
