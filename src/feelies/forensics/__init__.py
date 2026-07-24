"""Post-trade edge-decay and execution-quality analysis.

:class:`~feelies.forensics.decay_detector.DecayDetector` implements TCA
and edge-decay analysis. See post-trade-forensics skill for specification.
"""

from feelies.forensics.analyzer import ForensicAnalyzer
from feelies.forensics.decay_detector import DecayDetector
from feelies.forensics.gate_close_attribution import (
    GateCloseAttribution,
    GateCloseAttributionError,
    from_gate_close_flat,
    reconstruct_from_safety_flatten,
)

__all__ = [
    "DecayDetector",
    "ForensicAnalyzer",
    "GateCloseAttribution",
    "GateCloseAttributionError",
    "from_gate_close_flat",
    "reconstruct_from_safety_flatten",
]
