"""Declared construction policy: reduce N forecasts to one (or none).

Engine 6's job is N forecasts → one desired portfolio. Top-1 selection is
one such construction — a concentration constraint of one — not a kernel
detail and not an alpha-package concern. Other :class:`SelectionPolicy`
implementations are admissible; top-1 is the default, not the only
reachable behaviour.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from feelies.composition.protocol import (
    ForecastExclusion,
    SelectionResult,
)
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


class Top1SelectionPolicy:
    """Default construction policy: highest edge_estimate_bps * strength wins.

    Directional conflicts (LONG vs SHORT) are resolved by comparing
    composite scores.  If the winning score falls below the dead-zone
    threshold, no signal is emitted (empty contributors).

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
                contributors is empty.  Prevents acting on weak,
                contested signals.
        """
        self._dead_zone_bps = dead_zone_bps

    def select(self, signals: Sequence[Signal]) -> SelectionResult:
        in_scope = tuple(signals)
        if not signals:
            return SelectionResult(in_scope=(), contributors=(), exclusions=())

        if len(signals) == 1:
            return SelectionResult(
                in_scope=in_scope,
                contributors=(signals[0],),
                exclusions=(),
            )

        flats = [s for s in signals if s.direction == SignalDirection.FLAT]
        if flats:
            # Strategy ID makes equal-strength ties independent of input order.
            winner = min(flats, key=lambda s: (-s.strength, s.strategy_id))
            return SelectionResult(
                in_scope=in_scope,
                contributors=(winner,),
                exclusions=tuple(
                    ForecastExclusion(
                        signal=s,
                        reason=f"not_selected_in_arbitration_winner_is:{winner.strategy_id}",
                    )
                    for s in signals
                    if s is not winner
                ),
            )

        # Strategy ID makes equal-score ties independent of input order.
        best = min(
            signals,
            key=lambda s: (-(s.edge_estimate_bps * s.strength), s.strategy_id),
        )

        if best.edge_estimate_bps * best.strength < self._dead_zone_bps:
            return SelectionResult(
                in_scope=in_scope,
                contributors=(),
                exclusions=tuple(
                    ForecastExclusion(
                        signal=s,
                        reason="arbitration_returned_none_dead_zone_or_conflict",
                    )
                    for s in signals
                ),
            )

        return SelectionResult(
            in_scope=in_scope,
            contributors=(best,),
            exclusions=tuple(
                ForecastExclusion(
                    signal=s,
                    reason=f"not_selected_in_arbitration_winner_is:{best.strategy_id}",
                )
                for s in signals
                if s is not best
            ),
        )
