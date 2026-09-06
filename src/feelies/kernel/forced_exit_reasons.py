"""Kernel-hosted unions of risk-authored forced-exit reasons."""

from __future__ import annotations

# Risk-authored exits use one non-vetoable reason registry.
_RISK_FORCED_EXIT_REASONS: frozenset[str] = frozenset(
    {
        "HAZARD_SPIKE",
        "HARD_EXIT_AGE",
        "SAFETY_FAIL_CLOSED",
        "DECOUPLING_REVOKED",
        "MAX_HOLD_AFTER_SAFE_OFF",
        "SESSION_FLATTEN",
        "STOP_EXIT",
        "SESSION_FLAT",
    }
)

# Slice-scoped authors may reduce either symbol-net or strategy-slice exposure.
_SLICE_SCOPED_FORCED_EXIT_REASONS: frozenset[str] = frozenset(
    {
        "SAFETY_FAIL_CLOSED",
        "DECOUPLING_REVOKED",
        "HARD_EXIT_AGE",
        "MAX_HOLD_AFTER_SAFE_OFF",
        "SESSION_FLATTEN",
    }
)

# Only unambiguous slice-scoped reasons self-attribute fills.
_SELF_ATTRIBUTED_FORCED_EXIT_REASONS: frozenset[str] = frozenset(
    {
        "SAFETY_FAIL_CLOSED",
        "DECOUPLING_REVOKED",
        "MAX_HOLD_AFTER_SAFE_OFF",
        "SESSION_FLATTEN",
    }
)
