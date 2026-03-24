"""Signal arbitration — conflict resolution when multiple alphas fire.

When multiple alpha modules produce signals for the same symbol on
the same tick, the arbitrator selects a single winner.  The protocol
is injectable so that research can experiment with different policies
(edge-weighted, ensemble voting, capital-weighted, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from feelies.core.events import Signal, SignalDirection


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
            return max(flats, key=lambda s: s.strength)

        best = max(
            signals,
            key=lambda s: s.edge_estimate_bps * s.strength,
        )

        if best.edge_estimate_bps * best.strength < self._dead_zone_bps:
            return None

        return best
