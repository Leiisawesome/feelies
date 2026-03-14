"""Platform-provided shared services.

Services are protocol-defined capabilities that the platform provides
to alpha modules.  The AlphaLoader injects service instances into
feature and signal code namespaces so that alpha specs can call them
without importing or constructing anything.
"""

from feelies.services.regime_engine import (
    HMM3StateFractional,
    RegimeEngine,
    get_regime_engine,
)

__all__ = [
    "HMM3StateFractional",
    "RegimeEngine",
    "get_regime_engine",
]
