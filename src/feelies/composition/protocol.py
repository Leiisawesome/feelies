"""Pure Layer-3 portfolio-alpha contract.

Implementations map barrier-synchronized cross-sectional context to a sized
position intent. They must be deterministic, idempotent, and independent of
mapping iteration order. Invalid or infeasible context raises
``CompositionContextError``; the engine converts it to no position change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from feelies.core.events import CrossSectionalContext, Signal, SizedPositionIntent


class CompositionContextError(Exception):
    """Raised when a portfolio alpha cannot construct a valid intent."""


@dataclass(frozen=True, slots=True)
class ForecastExclusion:
    """One in-scope forecast that did not contribute, with a reason."""

    signal: Signal
    reason: str


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """One reduction of in-scope forecasts to contributors and exclusions.

    The accounting identity is ``contributors ∪ exclusions == in_scope``
    (object identity), with a non-empty reason on every exclusion.
    """

    in_scope: tuple[Signal, ...]
    contributors: tuple[Signal, ...]
    exclusions: tuple[ForecastExclusion, ...]

    @property
    def winner(self) -> Signal | None:
        if not self.contributors:
            return None
        return self.contributors[0]


class SelectionPolicy(Protocol):
    """N forecasts → a selection. Top-1 is one implementation, not the only."""

    def select(self, signals: Sequence[Signal]) -> SelectionResult:
        """Reduce *signals* to a :class:`SelectionResult`.

        ``signals`` may be empty. Every input is a contributor or an exclusion.
        """
        ...


class PortfolioAlpha(Protocol):
    """Layer-3 alpha — converts cross-sectional context into target weights.

    Implementations are constructed by the
    :class:`feelies.alpha.loader.AlphaLoader` when it encounters a
    schema-1.1 ``layer: PORTFOLIO`` spec, and registered with the
    :class:`feelies.alpha.registry.AlphaRegistry` exactly like a
    SIGNAL alpha.

    Attributes
    ----------
    alpha_id :
        Stable identifier (also the YAML ``alpha_id``).
    horizon_seconds :
        Decision horizon — the
        :class:`feelies.composition.synchronizer.UniverseSynchronizer`
        only emits :class:`CrossSectionalContext` events at boundaries
        of this horizon.
    """

    # Read-only properties accept manifest-derived implementations under strict mypy.
    @property
    def alpha_id(self) -> str: ...

    @property
    def horizon_seconds(self) -> int: ...

    def construct(
        self,
        ctx: CrossSectionalContext,
        params: Mapping[str, Any],
    ) -> SizedPositionIntent:
        """Convert *ctx* into a :class:`SizedPositionIntent`.

        Parameters
        ----------
        ctx :
            Universe-wide barrier-synced snapshot per §5.6.
        params :
            Resolved parameter mapping for this alpha (immutable).

        Returns
        -------
        :class:`SizedPositionIntent`
            Target positions per symbol.  Absent symbols are
            interpreted as "hold the existing position" by the risk
            engine.

        Raises
        ------
        CompositionContextError
            When the alpha cannot construct a meaningful intent for
            this context (e.g. completeness below threshold, solver
            infeasible).  The engine wraps the failure in a degenerate
            "no position change" intent.
        """
        ...


__all__ = [
    "CompositionContextError",
    "ForecastExclusion",
    "PortfolioAlpha",
    "SelectionPolicy",
    "SelectionResult",
]
