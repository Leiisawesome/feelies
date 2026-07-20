"""Pure Layer-3 portfolio-alpha contract.

Implementations map barrier-synchronized cross-sectional context to a sized
position intent. They must be deterministic, idempotent, and independent of
mapping iteration order. Invalid or infeasible context raises
``CompositionContextError``; the engine converts it to no position change.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from feelies.core.events import CrossSectionalContext, SizedPositionIntent


class CompositionContextError(Exception):
    """Raised when a portfolio alpha cannot construct a valid intent."""


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


__all__ = ["CompositionContextError", "PortfolioAlpha"]
