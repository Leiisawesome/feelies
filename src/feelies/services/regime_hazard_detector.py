"""Regime hazard detector — pure two-tick decay-spike detector.

Phase 3.1 / v0.3 §20.3.1 and §20.7
----------------------------------

A ``RegimeHazardSpike`` event is emitted when the posterior probability
of the currently-dominant regime state drops sharply within a single
tick — i.e., the regime is *about to flip*. Downstream consumers
(risk engine via §20.7.1, composition layer) use it to trigger
hazard-rate-driven exits without waiting for the next horizon
boundary.

The detector itself is **purely functional**: ``detect(prev, curr)``
takes two consecutive :class:`RegimeState` events from the same
``(symbol, engine_name)`` pair and returns either a
:class:`RegimeHazardSpike` description or ``None``.  All state
needed for *suppression* (§20.3.1: at most one spike per
``(symbol, engine_name, departing_state)`` *departure episode*,
where an episode begins when the state loses dominance and ends
only when that same state regains dominance) is held by the
caller — typically the regime-engine extension wired in the next
sub-task.

Why pure?
~~~~~~~~~

Per Inv-5 (deterministic replay) and Inv-7 (typed events on the bus)
the detector must contribute zero hidden state of its own to the
replay tape.  By restricting it to a free function over two
``RegimeState`` snapshots, we guarantee that the spike condition is
a pure function of the existing :class:`RegimeState` stream — which
is itself deterministic (v0.2 §12.2) — so :class:`RegimeHazardSpike`
inherits bit-identical replay (verifiable via the Level-5 parity
hash, §20.11.2).

Hazard semantics
~~~~~~~~~~~~~~~~

Let ``d`` = ``prev.dominant_state`` (departing state) and let
``p_prev`` = ``prev.posteriors[d]`` and ``p_now`` =
``curr.posteriors[d]``.

* The detector fires iff:

  1. ``prev.dominant_state == d`` *and* ``curr.dominant_state != d``
     OR ``p_now < 1.0 - hysteresis_threshold``.  Either signals
     loss of dominance.
  2. ``p_now < p_prev`` (departing posterior is actually decaying;
     prevents firing on numerical noise around an already-flipped
     state).

* ``hazard_score`` is the normalized magnitude of the decay clamped
  to ``[0.0, 1.0]``::

       hazard_score = clip01((p_prev - p_now) / max(p_prev, eps))

  A drop from 0.95 → 0.45 ⇒ ``hazard_score ≈ 0.526``;
  a drop from 0.95 → 0.05 ⇒ ``hazard_score ≈ 0.947``;
  a drop from 0.55 → 0.05 ⇒ ``hazard_score ≈ 0.909``.

* ``incoming_state`` is the new dominant state's *name*, or
  ``None`` if two non-departing states are tied (avoid breaking
  ties with arbitrary order — downstream code should handle the
  ambiguous case explicitly).

Inputs
~~~~~~

* ``prev`` — last :class:`RegimeState` seen on the
  ``(symbol, engine_name)`` channel.
* ``curr`` — newly arrived :class:`RegimeState` for the same channel.
* ``hysteresis_threshold`` — float in ``(0.0, 1.0)`` controlling the
  *absolute* dominance floor; the default ``0.30`` matches v0.3
  §20.3.1 prose ("posterior of the currently-dominant regime drops
  below ``1.0 - hysteresis_threshold``").

Validation
~~~~~~~~~~

The detector raises :class:`HazardDetectorContractError` when its
preconditions are violated — same ``(symbol, engine_name)``,
identical ``state_names`` ordering, and matching ``len(posteriors)``.
This prevents silent semantic corruption when the upstream engine is
swapped or reconfigured between ticks.
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
    """Stateful wrapper around the pure :func:`detect` function.

    Owns the suppression set so callers can simply hand it
    successive :class:`RegimeState` events and let the detector
    emit at most one :class:`RegimeHazardSpike` per
    ``(symbol, engine_name, departing_state)`` transition.

    The detector is *not* thread-safe — instantiate one per channel
    on the orchestrator's main event loop, matching the pattern
    used by the rest of the kernel (see :mod:`feelies.kernel.orchestrator`).

    Reset semantics
    ---------------

    Calling :meth:`reset` clears all suppression keys.  This is used
    by determinism-replay tests and by the orchestrator on session
    boundary so the new session starts from a clean tape (v0.2
    §12.5).
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
                "hysteresis_threshold must be in (0.0, 1.0); "
                f"got {hysteresis_threshold!r}"
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
        re_dominant = (
            prev.dominant_name != curr.dominant_name
            and k[2] == curr.dominant_name
        )
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
            "RegimeState pair must share symbol; "
            f"got prev={prev.symbol!r} curr={curr.symbol!r}"
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
    # Producers populate ``dominant_state`` (int index) and
    # ``dominant_name`` (str) independently; the detector reads BOTH
    # — ``dominant_state`` to index into ``state_names`` for the
    # departing label, ``dominant_name`` to drive re-arming on
    # round-trip dominance.  Disagreement between the two would
    # silently produce wrong suppression keys and inconsistent spike
    # text.  Catching it at the layer boundary upholds Inv-7 (typed
    # events on the bus carry self-consistent invariants).
    _validate_dominant_consistency(prev, "prev")
    _validate_dominant_consistency(curr, "curr")


def _validate_dominant_consistency(state: RegimeState, label: str) -> None:
    idx = state.dominant_state
    n = len(state.state_names)
    if idx < 0 or idx >= n:
        raise HazardDetectorContractError(
            f"{label}.dominant_state={idx} out of range for "
            f"state_names of length {n}"
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
