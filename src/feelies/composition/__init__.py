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
alpha is loaded; otherwise the entire path is bypassed and the legacy
LEGACY_SIGNAL execution path is preserved bit-for-bit (Inv-A).

See ``design_docs/three_layer_architecture.md`` §6.5 for the design.
"""

from feelies.composition.protocol import (
    CompositionContextError,
    PortfolioAlpha,
)

__all__ = ["PortfolioAlpha", "CompositionContextError"]
