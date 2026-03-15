"""Hypothesis registry — stub for tracking research hypotheses.

Defines the interface for registering, tracking, and querying
hypotheses that drive alpha research.  Concrete implementations
are future work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, kw_only=True)
class Hypothesis:
    """A testable hypothesis about market microstructure."""

    hypothesis_id: str
    description: str
    mechanism: str
    falsification_criteria: str
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)


class HypothesisRegistry(Protocol):
    """Register and track research hypotheses."""

    def register(self, hypothesis: Hypothesis) -> None:
        """Record a new hypothesis."""
        ...

    def get(self, hypothesis_id: str) -> Hypothesis:
        """Retrieve a hypothesis by ID."""
        ...

    def list_active(self) -> list[Hypothesis]:
        """Return all hypotheses with status 'active'."""
        ...

    def update_status(self, hypothesis_id: str, status: str) -> None:
        """Change hypothesis status (active, falsified, confirmed, etc.)."""
        ...
