"""Deterministic research and promotion-significance utilities.

CPCV and DSR produce the evidence consumed by promotion gates. Experiment
and hypothesis modules currently define protocols only.
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
from feelies.research.dsr import (
    DSRComputation,
    build_dsr_evidence,
    build_dsr_evidence_from_returns,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    standard_normal_cdf,
    standard_normal_quantile,
    standardised_moments,
)
from feelies.research.experiment import ExperimentTracker
from feelies.research.hypothesis import HypothesisRegistry

__all__ = [
    "CPCVConfig",
    "CPCVSplit",
    "DSRComputation",
    "ExperimentTracker",
    "HypothesisRegistry",
    "assemble_path_returns",
    "assign_groups",
    "build_cpcv_evidence",
    "build_dsr_evidence",
    "build_dsr_evidence_from_returns",
    "deflated_sharpe",
    "expected_max_sharpe",
    "fold_pnl_curves_sha256",
    "generate_cpcv_splits",
    "lo_bootstrap_p_value",
    "probabilistic_sharpe_ratio",
    "reconstruct_paths",
    "sharpe_ratio",
    "standard_normal_cdf",
    "standard_normal_quantile",
    "standardised_moments",
]
