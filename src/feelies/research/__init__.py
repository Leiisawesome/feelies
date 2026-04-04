"""Research infrastructure — experiment tracking and hypothesis management.

Protocol definitions; concrete implementations are future work.
See research-workflow skill for specification.
"""

from feelies.research.experiment import ExperimentTracker
from feelies.research.hypothesis import HypothesisRegistry
from feelies.research.grok_parity_backtester import (
    GrokParityBacktester,
    GrokTCConfig,
    GrokTradeRecord,
    GrokBacktestMetrics,
    latency_sensitivity,
    compare_with_feelies,
)

__all__ = [
    "ExperimentTracker",
    "HypothesisRegistry",
    "GrokParityBacktester",
    "GrokTCConfig",
    "GrokTradeRecord",
    "GrokBacktestMetrics",
    "latency_sensitivity",
    "compare_with_feelies",
]
