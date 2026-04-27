"""Research infrastructure — experiment tracking, hypothesis
management, and statistical-significance computation.

Workstream **C** equips the platform with the pure-Python
significance procedures the F-2 promotion-gate matrix already
expects:

- :mod:`feelies.research.cpcv` (Workstream C-1) — Combinatorial
  Purged Cross-Validation, emitting
  :class:`feelies.alpha.promotion_evidence.CPCVEvidence`.
- :mod:`feelies.research.dsr` (Workstream C-2) — Bailey & López de
  Prado Deflated Sharpe Ratio, emitting
  :class:`feelies.alpha.promotion_evidence.DSREvidence`.

The experiment / hypothesis modules remain protocol stubs; their
concrete implementations are future work.  See the
research-workflow and testing-validation skills for the broader
specification.
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
