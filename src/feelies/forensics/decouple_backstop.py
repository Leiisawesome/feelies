"""Quote-freeze / session-backstop forensic check for ``decouple_caps_only``.

The bounded-deferral deadline is enforced in **event-time** (Inv-7): the cap
fires on the first bus event on the symbol at/after the deadline.  During a
post-safety-OFF **quote freeze** there is no such event, so the position may be
held past the nominal ceiling until the next event; ``session_flatten`` is the
wall-clock backstop of last resort (design rev 5 §2.3).

This module reconstructs, from per-episode forced-exit records, whether every
quote-freeze episode still exited by the session-flatten bound, and projects the
result into
:class:`~feelies.promotion.evidence.QuoteFreezeBackstopEvidence` — the
third leg of the Stage-0 promotion gate.  A position stranded past
``session_flatten`` is a defect, not a pass.

Pure and deterministic (Inv-5): same episode records → bit-identical evidence.
The reconstruction is offline forensics and never touches the tick path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from feelies.promotion.evidence import QuoteFreezeBackstopEvidence

__all__ = [
    "QuoteFreezeEpisode",
    "build_quote_freeze_backstop_evidence",
]


@dataclass(frozen=True, kw_only=True)
class QuoteFreezeEpisode:
    """One ``open ∧ safe-OFF`` episode that hit a post-safety-OFF quote freeze.

    Attributes
    ----------
    strategy_id, symbol
        The strategy-slice the deferred book belonged to (provenance).
    hold_seconds
        Wall-clock seconds the position was held, open → forced exit.  For a
        stranded book (never exited before session end) the caller records the
        time held up to the session boundary.  Must be ``>= 0``.
    exit_reason
        The terminal forced-exit reason token — the deferral-cap vocabulary
        (``MAX_HOLD_AFTER_SAFE_OFF`` / ``HARD_EXIT_AGE`` / ``SESSION_FLATTEN``).
        An **empty** string means the position never exited (stranded), which is
        a backstop breach.
    """

    strategy_id: str
    symbol: str
    hold_seconds: float
    exit_reason: str

    def exited_within(self, session_flatten_bound_seconds: float) -> bool:
        """Whether the episode exited by the session-flatten bound at latest.

        A terminal exit (non-empty ``exit_reason``) whose hold did not exceed
        the wall-clock ``session_flatten`` bound.  Anything else — never exited,
        or held past the bound — is a backstop breach.
        """
        return bool(self.exit_reason) and self.hold_seconds <= session_flatten_bound_seconds


def build_quote_freeze_backstop_evidence(
    episodes: Sequence[QuoteFreezeEpisode],
    *,
    session_flatten_bound_seconds: float,
) -> QuoteFreezeBackstopEvidence:
    """Project quote-freeze episodes into the Stage-0 backstop evidence.

    ``session_flatten_bound_seconds`` is the wall-clock session-flatten bound
    the episodes are checked against (a session-level constant).  Every episode
    in ``episodes`` is a quote-freeze episode by construction (the caller filters
    the subpopulation); the gate then requires that **all** of them exited by the
    bound with none stranded past it.

    Raises ``ValueError`` for a non-positive bound or a negative hold time.
    """
    if session_flatten_bound_seconds <= 0.0:
        raise ValueError(
            f"session_flatten_bound_seconds must be > 0, got {session_flatten_bound_seconds}"
        )
    for ep in episodes:
        if ep.hold_seconds < 0.0:
            raise ValueError(
                f"QuoteFreezeEpisode.hold_seconds must be >= 0, got {ep.hold_seconds} "
                f"({ep.strategy_id}/{ep.symbol})"
            )

    exited = sum(1 for ep in episodes if ep.exited_within(session_flatten_bound_seconds))
    breached = len(episodes) - exited
    max_hold = max((ep.hold_seconds for ep in episodes), default=0.0)

    return QuoteFreezeBackstopEvidence(
        quote_freeze_episodes=len(episodes),
        exited_by_session_flatten=exited,
        breached_session_backstop=breached,
        session_flatten_bound_seconds=session_flatten_bound_seconds,
        max_hold_seconds_observed=max_hold,
    )
