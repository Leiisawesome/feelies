"""System-wide error hierarchy.

Every error belongs to a category that maps to a failure mode
(crash, degrade, retry) as required by the system-architect skill.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar


class FailureMode(Enum):
    """Structured response category for each error class.

    Lets handlers branch on the intended reaction without parsing
    docstrings (audit P2-6).  Each :class:`FeeliesError` subclass declares
    its ``failure_mode`` so the prose in the docstring and the
    machine-readable category cannot drift apart.
    """

    CRASH = "crash"  # fatal — stop / shutdown the run
    DEGRADE = "degrade"  # reduce exposure, continue in DEGRADED
    RETRY = "retry"  # transient — the operation may be retried
    LOCKDOWN = "lockdown"  # risk lockdown / force-flatten


class FeeliesError(Exception):
    """Base error for all platform exceptions."""

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH


class ConfigurationError(FeeliesError):
    """Fatal: configuration is invalid or missing. Macro → SHUTDOWN."""

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH


class DataIntegrityError(FeeliesError):
    """Degraded: data gap, corruption, or schema violation."""

    failure_mode: ClassVar[FailureMode] = FailureMode.DEGRADE


class CausalityViolation(FeeliesError):
    """Fatal: lookahead or forward leakage detected (invariant 6)."""

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH


class DeterminismViolation(FeeliesError):
    """Fatal: replay produced different output (invariant 5)."""

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH


class RiskBreachError(FeeliesError):
    """Lockdown: risk limit exceeded. Macro → RISK_LOCKDOWN."""

    failure_mode: ClassVar[FailureMode] = FailureMode.LOCKDOWN


class ExecutionError(FeeliesError):
    """Degraded/Retry: order routing or fill error."""

    failure_mode: ClassVar[FailureMode] = FailureMode.RETRY


class StaleDataError(FeeliesError):
    """Degraded: data is stale beyond tolerance (never silently consumed)."""

    failure_mode: ClassVar[FailureMode] = FailureMode.DEGRADE


class OrchestratorPipelineAbortError(FeeliesError):
    """Pipeline stopped after tick-failure recovery could not reach DEGRADED.

    Raised when ``_pipeline_abort_requested`` is set (macro transition to
    ``DEGRADED`` failed inside :meth:`Orchestrator._handle_tick_failure`) so
    callers do not mis-classify an aborted loop as normal feed exhaustion.
    """

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH


class SessionEntryBlockedError(FeeliesError):
    """Cannot enter RESEARCH/BACKTEST/PAPER/LIVE — kill switch or risk interlock."""

    failure_mode: ClassVar[FailureMode] = FailureMode.CRASH
