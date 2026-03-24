"""Research infrastructure — experiment tracking and hypothesis management.

Protocol definitions; concrete implementations are future work.
See research-workflow skill for specification.
"""

from feelies.research.experiment import ExperimentTracker
from feelies.research.hypothesis import HypothesisRegistry

__all__ = ["ExperimentTracker", "HypothesisRegistry"]
