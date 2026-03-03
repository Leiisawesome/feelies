"""System-wide error hierarchy.

Every error belongs to a category that maps to a failure mode
(crash, degrade, retry) as required by the system-architect skill.
"""

from __future__ import annotations


class FeeliesError(Exception):
    """Base error for all platform exceptions."""


class ConfigurationError(FeeliesError):
    """Fatal: configuration is invalid or missing. Macro → SHUTDOWN."""


class DataIntegrityError(FeeliesError):
    """Degraded: data gap, corruption, or schema violation."""


class CausalityViolation(FeeliesError):
    """Fatal: lookahead or forward leakage detected (invariant 6)."""


class DeterminismViolation(FeeliesError):
    """Fatal: replay produced different output (invariant 5)."""


class RiskBreachError(FeeliesError):
    """Lockdown: risk limit exceeded. Macro → RISK_LOCKDOWN."""


class ExecutionError(FeeliesError):
    """Degraded/Retry: order routing or fill error."""


class StaleDataError(FeeliesError):
    """Degraded: data is stale beyond tolerance (never silently consumed)."""
