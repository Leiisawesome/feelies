"""Typed configuration protocol — versioned and auditable (invariant 13).

Every configuration used in production or backtest is versioned,
snapshotable, and validated before use.  Configuration snapshots
enable deterministic replay: same snapshot + same event log →
identical output (invariant 5).

The orchestrator and all layers consume configuration through
this protocol.  No raw ``dict[str, Any]`` crosses layer boundaries
as configuration — always this typed contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, kw_only=True)
class ConfigSnapshot:
    """Immutable, serializable snapshot of configuration for provenance.

    Stored alongside event logs so that any historical run can be
    reproduced with the exact configuration that produced it.
    """

    version: str
    timestamp_ns: int
    author: str
    data: dict[str, Any]
    checksum: str


class Configuration(Protocol):
    """Versioned, auditable system configuration.

    Every config change is traceable to an author and has a rollback
    path (invariant 13).  Configuration is validated before use and
    snapshotted for replay provenance.
    """

    @property
    def version(self) -> str:
        """Unique version identifier for this configuration."""
        ...

    @property
    def symbols(self) -> frozenset[str]:
        """Trading universe — the set of symbols to process."""
        ...

    def snapshot(self) -> ConfigSnapshot:
        """Create an immutable snapshot for provenance and replay.

        The snapshot must be JSON-serializable so it can be stored
        alongside the event log.
        """
        ...

    def validate(self) -> None:
        """Validate all configuration values.

        Raises ``ConfigurationError`` if any value is invalid or
        missing.  Must be called before the configuration is used.
        """
        ...
