"""Self-attributed forced-exit reason tokens."""

from __future__ import annotations

# Only unambiguous slice-scoped reasons self-attribute fills.
_SELF_ATTRIBUTED_FORCED_EXIT_REASONS: frozenset[str] = frozenset(
    {
        "SAFETY_FAIL_CLOSED",
        "DECOUPLING_REVOKED",
        "MAX_HOLD_AFTER_SAFE_OFF",
        "SESSION_FLATTEN",
    }
)
