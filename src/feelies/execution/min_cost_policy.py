"""Choose passive or aggressive execution from modeled per-order cost.

The policy uses the router's cost model, including rebates, adverse selection,
commission floors, and non-fill risk. Must-trade orders always use aggressive
execution. Decisions depend only on the supplied order, quote, and config.
"""

from __future__ import annotations

from feelies.core.min_cost_policy import MinCostPolicyConfig as MinCostPolicyConfig
from feelies.core.min_cost_policy import (
    MinimumCostExecutionPolicy as MinimumCostExecutionPolicy,
)

__all__ = [
    "MinCostPolicyConfig",
    "MinimumCostExecutionPolicy",
]
