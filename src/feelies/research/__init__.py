"""Research infrastructure — experiment tracking, hypothesis
management, and statistical-significance computation.

Workstream **C-1** added :mod:`feelies.research.cpcv`, the pure
deterministic Combinatorial Purged Cross-Validation procedure that
emits :class:`feelies.alpha.promotion_evidence.CPCVEvidence` for
the promotion gates.  The experiment / hypothesis modules remain
protocol stubs; their concrete implementations are future work.
See the research-workflow and testing-validation skills for the
broader specification.
"""

from feelies.research.cpcv import (
    CPCVConfig,
    CPCVSplit,
    assemble_path_returns,
    assign_groups,
    build_cpcv_evidence,
    fold_pnl_curves_sha256,
    generate_cpcv_splits,
    lo_bootstrap_p_value,
    reconstruct_paths,
    sharpe_ratio,
)
from feelies.research.experiment import ExperimentTracker
from feelies.research.hypothesis import HypothesisRegistry

__all__ = [
    "CPCVConfig",
    "CPCVSplit",
    "ExperimentTracker",
    "HypothesisRegistry",
    "assemble_path_returns",
    "assign_groups",
    "build_cpcv_evidence",
    "fold_pnl_curves_sha256",
    "generate_cpcv_splits",
    "lo_bootstrap_p_value",
    "reconstruct_paths",
    "sharpe_ratio",
]
