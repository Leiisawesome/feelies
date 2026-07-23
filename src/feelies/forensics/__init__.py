"""Post-trade edge-decay and execution-quality analysis.

:class:`~feelies.forensics.decay_detector.DecayDetector` implements TCA
and edge-decay analysis. See post-trade-forensics skill for specification.
"""

from feelies.forensics.analyzer import ForensicAnalyzer
from feelies.forensics.decay_detector import DecayDetector

__all__ = ["DecayDetector", "ForensicAnalyzer"]
