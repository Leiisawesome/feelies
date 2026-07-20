"""Detect sharp decay in a dominant regime posterior.

``detect(prev, curr)`` is pure and requires matching symbol, engine, state
ordering, and posterior shape. It fires when the departing posterior falls,
and either dominance changes or the posterior crosses the configured floor.
The normalized score is::

    clip01((p_prev - p_now) / max(p_prev, epsilon))

Tied incoming states are reported as ``None``. The stateful wrapper suppresses
duplicates until the departing state regains dominance.
"""

from __future__ import annotations

from feelies.core.events import RegimeHazardSpike, RegimeState

DEFAULT_HYSTERESIS_THRESHOLD: float = 0.30
"""Default absolute-dominance floor (§20.3.1 prose).

A departing state with ``p_now < 1.0 - 0.30 = 0.70`` qualifies as a
hazard candidate even when it remains the argmax — this catches the
"sliding peak" case where the regime hasn't formally flipped yet
but is decaying fast enough to be statistically indistinguishable
from a flip on the next tick."""

_EPS_DENOMINATOR: float = 1e-12
"""Floor on the divisor when computing ``hazard_score``.

When the departing posterior is below this floor (i.e. the state is
already effectively gone), the divisor is clamped to
``_EPS_DENOMINATOR`` so ``(p_prev - p_now) / denom`` cannot blow up.
The score is then clipped to ``[0.0, 1.0]``, so degenerate "decay
from already-near-zero" cases produce a small, bounded hazard score
rather than a divide-by-zero or an overshoot of 1.0."""


class HazardDetectorContractError(ValueError):
    """Raised when ``detect()`` is called with mismatched RegimeState pairs.

    Either the symbols/engine names disagree, the state-name tuples
    differ, or the posterior arrays have inconsistent lengths.
    Callers must hold one ``RegimeHazardDetector`` per
    ``(symbol, engine_name)`` channel — passing a stale snapshot from
    a different channel would silently produce false positives.
    """


class RegimeHazardDetector:
    """Suppress duplicate hazards within one departure episode.

    The wrapper is not thread-safe. ``reset`` clears all suppression keys.
    """

    __slots__ = (
        "_hysteresis_threshold",
        "_suppressed",
    )

    def __init__(
        self,
        *,
        hysteresis_threshold: float = DEFAULT_HYSTERESIS_THRESHOLD,
    ) -> None:
        if not 0.0 < hysteresis_threshold < 1.0:
            raise ValueError(
                f"hysteresis_threshold must be in (0.0, 1.0); got {hysteresis_threshold!r}"
            )
        self._hysteresis_threshold: float = float(hysteresis_threshold)
        self._suppressed: set[tuple[str, str, str]] = set()

    @property
    def hysteresis_threshold(self) -> float:
        return self._hysteresis_threshold

    def detect(
        self,
        prev: RegimeState | None,
        curr: RegimeState,
    ) -> RegimeHazardSpike | None:
        """Return a hazard spike description, or ``None``.

        Delegates to the module-level :func:`detect`, passing
        ``self._suppressed`` as the in-place suppression set.  The
        decision pipeline lives in exactly one place; this method is
        a thin owner of mutable session state.
        """
        return detect(
            prev,
            curr,
            hysteresis_threshold=self._hysteresis_threshold,
            suppressed=self._suppressed,
        )

    def reset(self) -> None:
        """Clear all suppression state."""
        self._suppressed.clear()


def detect(
    prev: RegimeState | None,
    curr: RegimeState,
    *,
    hysteresis_threshold: float = DEFAULT_HYSTERESIS_THRESHOLD,
    suppressed: set[tuple[str, str, str]] | None = None,
) -> RegimeHazardSpike | None:
    """Pure decision pipeline: ``(prev, curr) → RegimeHazardSpike?``.

    Single source of truth for hazard detection; the stateful
    :class:`RegimeHazardDetector` is a thin wrapper that owns the
    suppression set and delegates here.

    The ``suppressed`` set, when supplied, is mutated in-place to
    record the ``(symbol, engine_name, departing_state)`` triple of
    the spike that was returned (and to clear existing entries that
    have been re-armed on this tick).  Pass ``None`` to skip
    suppression accounting entirely — useful for property tests that
    enumerate spike conditions in isolation.

    ``prev=None`` is the cold-start case — no spike can be detected
    from a single observation.  The function still accepts ``curr``
    so callers can prime suppression state without branching at the
    call site.
    """
    if prev is None:
        return None

    _validate_pair(prev, curr)

    if suppressed is not None and suppressed:
        _rearm_suppression(prev, curr, hysteresis_threshold, suppressed)

    departing_idx = prev.dominant_state
    departing_state = prev.state_names[departing_idx]
    p_prev = float(prev.posteriors[departing_idx])
    p_now = float(curr.posteriors[departing_idx])

    if p_now >= p_prev:
        return None

    flipped = curr.dominant_state != departing_idx
    below_floor = p_now < (1.0 - hysteresis_threshold)
    if not (flipped or below_floor):
        return None

    key = (curr.symbol, curr.engine_name, departing_state)
    if suppressed is not None and key in suppressed:
        return None

    if suppressed is not None:
        suppressed.add(key)

    denom = max(p_prev, _EPS_DENOMINATOR)
    raw = (p_prev - p_now) / denom
    hazard_score = max(0.0, min(1.0, raw))

    return RegimeHazardSpike(
        timestamp_ns=curr.timestamp_ns,
        correlation_id=curr.correlation_id,
        sequence=curr.sequence,
        symbol=curr.symbol,
        engine_name=curr.engine_name,
        departing_state=departing_state,
        departing_posterior_prev=p_prev,
        departing_posterior_now=p_now,
        incoming_state=_resolve_incoming(curr, departing_idx),
        hazard_score=hazard_score,
    )


def _rearm_suppression(
    prev: RegimeState,
    curr: RegimeState,
    hysteresis_threshold: float,
    suppressed: set[tuple[str, str, str]],
) -> None:
    """Discard suppression keys whose departure episode has resolved.

    A key ``(symbol, engine_name, X)`` is cleared when either:

    1. **Re-dominance** — ``X`` was non-dominant in ``prev`` and is
       dominant in ``curr`` (a clean round-trip).
    2. **Posterior recovery** — ``X``'s posterior in ``curr`` has
       climbed back above ``1.0 - hysteresis_threshold`` (the
       wobble has resolved even without a dominance flip).

    Either condition signals that the prior departure episode for
    ``X`` is over, so a fresh decay can fire a new spike.  Until
    then, every subsequent tick in the same episode is suppressed,
    preventing downstream churn (§20.3.1).
    """
    floor = 1.0 - hysteresis_threshold
    index_by_name = {name: i for i, name in enumerate(curr.state_names)}
    stale: list[tuple[str, str, str]] = []
    for k in suppressed:
        if k[0] != curr.symbol or k[1] != curr.engine_name:
            continue
        re_dominant = prev.dominant_name != curr.dominant_name and k[2] == curr.dominant_name
        recovered = False
        idx = index_by_name.get(k[2])
        if idx is not None and idx < len(curr.posteriors):
            recovered = float(curr.posteriors[idx]) >= floor
        if re_dominant or recovered:
            stale.append(k)
    for k in stale:
        suppressed.discard(k)


def _validate_pair(prev: RegimeState, curr: RegimeState) -> None:
    if prev.symbol != curr.symbol:
        raise HazardDetectorContractError(
            f"RegimeState pair must share symbol; got prev={prev.symbol!r} curr={curr.symbol!r}"
        )
    if prev.engine_name != curr.engine_name:
        raise HazardDetectorContractError(
            "RegimeState pair must share engine_name; "
            f"got prev={prev.engine_name!r} curr={curr.engine_name!r}"
        )
    if prev.state_names != curr.state_names:
        raise HazardDetectorContractError(
            "RegimeState pair must share state_names ordering; "
            f"got prev={prev.state_names!r} curr={curr.state_names!r}"
        )
    if len(prev.posteriors) != len(curr.posteriors):
        raise HazardDetectorContractError(
            "RegimeState pair must share posteriors length; "
            f"got prev={len(prev.posteriors)} curr={len(curr.posteriors)}"
        )
    if len(prev.posteriors) != len(prev.state_names):
        raise HazardDetectorContractError(
            "RegimeState.posteriors and state_names must have equal "
            f"length; got posteriors={len(prev.posteriors)} "
            f"state_names={len(prev.state_names)}"
        )
    # Both dominant representations drive behavior, so they must agree.
    _validate_dominant_consistency(prev, "prev")
    _validate_dominant_consistency(curr, "curr")


def _validate_dominant_consistency(state: RegimeState, label: str) -> None:
    idx = state.dominant_state
    n = len(state.state_names)
    if idx < 0 or idx >= n:
        raise HazardDetectorContractError(
            f"{label}.dominant_state={idx} out of range for state_names of length {n}"
        )
    expected_name = state.state_names[idx]
    if state.dominant_name != expected_name:
        raise HazardDetectorContractError(
            f"{label}.dominant_state={idx} indexes "
            f"state_names[{idx}]={expected_name!r}, but "
            f"dominant_name={state.dominant_name!r} — "
            "RegimeState must publish self-consistent dominance "
            "fields"
        )


def _resolve_incoming(curr: RegimeState, departing_idx: int) -> str | None:
    """Return the dominant state's name excluding ``departing_idx``.

    Returns ``None`` when two or more non-departing states are tied
    so downstream consumers can flag the ambiguity rather than
    receiving an arbitrarily-ordered "winner".
    """
    best_idx: int | None = None
    best_value: float = -1.0
    tie = False
    for idx, value in enumerate(curr.posteriors):
        if idx == departing_idx:
            continue
        f_value = float(value)
        if f_value > best_value:
            best_idx = idx
            best_value = f_value
            tie = False
        elif f_value == best_value:
            tie = True

    if best_idx is None or tie:
        return None
    return curr.state_names[best_idx]


__all__ = [
    "DEFAULT_HYSTERESIS_THRESHOLD",
    "HazardDetectorContractError",
    "RegimeHazardDetector",
    "detect",
]
