"""Signal arbitration — conflict resolution when multiple alphas fire.

When multiple alpha modules produce signals for the same symbol on
the same tick, the arbitrator selects a single winner.  The protocol
is injectable so that research can experiment with different policies
(edge-weighted, ensemble voting, capital-weighted, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from feelies.core.events import Signal, SignalDirection


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


class SignalArbitrator(Protocol):
    """Selects a single signal from multiple alpha outputs.

    Receives all non-None signals produced by active alphas for a
    single tick and returns the winning signal, or None if the
    arbitrator determines no action is warranted (e.g., directional
    conflict within a dead-zone).
    """

    def arbitrate(self, signals: Sequence[Signal]) -> Signal | None:
        """Select the best signal from competing candidates.

        ``signals`` is guaranteed non-empty by the caller.
        """
        ...


class EdgeWeightedArbitrator:
    """Default arbitrator: highest edge_estimate_bps * strength wins.

    Directional conflicts (LONG vs SHORT) are resolved by comparing
    composite scores.  If the winning score falls below the dead-zone
    threshold, no signal is emitted (returns None).

    FLAT is privileged: any alpha emitting FLAT triggers an immediate
    exit regardless of competing directional signals.  FLAT is a
    constraint (exit), not a preference — it must not be outvoted
    by directional hypotheses (invariant 11: fail-safe default).
    """

    __slots__ = ("_dead_zone_bps",)

    def __init__(self, dead_zone_bps: float = 0.5) -> None:
        """Configure the minimum composite score for a signal to win.

        Args:
            dead_zone_bps: If the best composite score
                (edge_estimate_bps * strength) is below this threshold,
                the arbitrator returns None.  Prevents acting on weak,
                contested signals.
        """
        self._dead_zone_bps = dead_zone_bps

    def arbitrate(self, signals: Sequence[Signal]) -> Signal | None:
        if not signals:
            return None

        if len(signals) == 1:
            return signals[0]

        flats = [s for s in signals if s.direction == SignalDirection.FLAT]
        if flats:
            # Strategy ID makes equal-strength ties independent of input order.
            return min(flats, key=lambda s: (-s.strength, s.strategy_id))

        # Strategy ID makes equal-score ties independent of input order.
        best = min(
            signals,
            key=lambda s: (-(s.edge_estimate_bps * s.strength), s.strategy_id),
        )

        if best.edge_estimate_bps * best.strength < self._dead_zone_bps:
            return None

        return best
