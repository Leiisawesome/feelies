"""Kernel-hosted unions of risk-authored forced-exit reasons."""

from __future__ import annotations

from feelies.risk.deferral_cap import (
    DEFERRAL_EXIT_REASONS,
    DEFERRAL_SLICE_SCOPED_REASONS,
)
from feelies.risk.exit_composer import EXIT_COMPOSER_EXIT_REASONS
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS
from feelies.risk.stop_exit import STOP_EXIT_REASONS

# Risk-authored exits use one non-vetoable reason registry.
_RISK_FORCED_EXIT_REASONS: frozenset[str] = (
    HAZARD_EXIT_REASONS | EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_EXIT_REASONS | STOP_EXIT_REASONS
)

# Slice-scoped authors may reduce either symbol-net or strategy-slice exposure.
_SLICE_SCOPED_FORCED_EXIT_REASONS: frozenset[str] = (
    EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_EXIT_REASONS
)

# Only unambiguous slice-scoped reasons self-attribute fills.
_SELF_ATTRIBUTED_FORCED_EXIT_REASONS: frozenset[str] = (
    EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_SLICE_SCOPED_REASONS
)
