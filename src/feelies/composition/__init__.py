"""Layer-3 composition (PORTFOLIO) layer.

Subscribers convert per-symbol :class:`Signal` events into universe-wide
:class:`SizedPositionIntent` events via the four-stage pipeline:

    UniverseSynchronizer  →  CrossSectionalRanker  →  FactorNeutralizer
                                                          ↓
                          SectorMatcher (optional)        ↓
                                                          ↓
                                              TurnoverOptimizer
                                                          ↓
                                              CompositionEngine

The engine is constructed only when at least one ``layer: PORTFOLIO``
alpha is loaded; otherwise the entire path is bypassed so SIGNAL-only
deployments do not pay the cost of the cross-sectional construction
pipeline (Inv-A).

See ``docs/three_layer_architecture.md`` §6.5 for the design.
"""

from feelies.composition.protocol import (
    CompositionContextError,
    ForecastExclusion,
    PortfolioAlpha,
    SelectionPolicy,
    SelectionResult,
)
from feelies.composition.selection_policy import Top1SelectionPolicy

__all__ = [
    "CompositionContextError",
    "ForecastExclusion",
    "PortfolioAlpha",
    "SelectionPolicy",
    "SelectionResult",
    "Top1SelectionPolicy",
]
