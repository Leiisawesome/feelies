"""CompositionContextError — Layer-3 construct failure.

Raised when a portfolio alpha cannot construct a valid intent. The type
lives in core so the loaded PORTFOLIO module can name it without importing
the composition package.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from feelies.core.events import Signal, SignalDirection


class CompositionContextError(Exception):
    """Raised when a portfolio alpha cannot construct a valid intent."""


class CompositionEngine(Protocol):
    """Injected composition engine. Kernel never calls methods by name."""


def _signal_reduces_book(current_qty: int, direction: SignalDirection) -> bool:
    """True when *direction* would close or offset a non-flat *current_qty*."""
    if current_qty == 0:
        return False
    if direction == SignalDirection.FLAT:
        return True
    if current_qty > 0 and direction == SignalDirection.SHORT:
        return True
    if current_qty < 0 and direction == SignalDirection.LONG:
        return True
    return False


def standalone_signal_actionable_for_strategy(
    signal: Signal,
    *,
    strategy_qty: int,
    aggregate_qty: int,
    alpha_has_prior_fill: bool,
) -> bool:
    """Whether a standalone signal may participate in arbitration.

    A gate-close FLAT from an alpha that has never filled is suppressed
    while another strategy owns the aggregate position. Directional exits
    likewise require matching strategy exposure; entries always pass.
    """
    if (
        signal.direction == SignalDirection.FLAT
        and signal.regime_gate_state == "OFF"
        and strategy_qty == 0
        and aggregate_qty != 0
        and not alpha_has_prior_fill
    ):
        return False
    if signal.direction == SignalDirection.FLAT:
        return True
    if _signal_reduces_book(aggregate_qty, signal.direction):
        return _signal_reduces_book(strategy_qty, signal.direction)
    return True


def is_redundant_gate_close_flat(
    signal: Signal,
    *,
    aggregate_qty: int,
    alpha_has_prior_fill: bool,
) -> bool:
    """True when a gate-close FLAT is a no-op (never traded, flat book)."""
    return (
        signal.direction == SignalDirection.FLAT
        and signal.regime_gate_state == "OFF"
        and aggregate_qty == 0
        and not alpha_has_prior_fill
    )


def collision_is_harmless_flat_gate_close(
    candidates: Sequence[Signal],
    aggregate_qty: int,
) -> bool:
    """True when every candidate is an inert gate-close on a flat book."""
    if aggregate_qty != 0:
        return False
    return all(
        signal.direction == SignalDirection.FLAT and signal.regime_gate_state == "OFF"
        for signal in candidates
    )


@dataclass(frozen=True, slots=True)
class StandaloneArbitrationCollision:
    """One post-filter standalone-signal arbitration tick (forensics)."""

    candidate_count: int
    strategy_ids: tuple[str, ...]
    kinds: tuple[tuple[str, str, str], ...]
    harmless: bool
