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
from feelies.services.regime_hazard_detector import (
    DEFAULT_HYSTERESIS_THRESHOLD,
    HazardDetectorContractError,
    RegimeHazardDetector,
    detect as detect_hazard_spike,
)

__all__ = [
    "DEFAULT_HYSTERESIS_THRESHOLD",
    "HMM3StateFractional",
    "HazardDetectorContractError",
    "RegimeEngine",
    "RegimeHazardDetector",
    "detect_hazard_spike",
    "get_regime_engine",
]
