"""Quote-freeze / session-backstop forensics (dual-permission Phase 6).

Covers :mod:`feelies.forensics.decouple_backstop`:

  * every quote-freeze episode exiting by ``session_flatten`` → passing evidence;
  * a stranded book (never exited) or a hold past the wall-clock bound → a
    backstop breach that FAILs the gate;
  * an empty check (no freeze episodes exercised) → FAIL (not evidence);
  * builder input validation + determinism (Inv-5).

The reconstructed evidence is validated with the real
:func:`feelies.alpha.promotion_evidence.validate_quote_freeze_backstop` so the
forensic builder and the gate stay in lock-step.
"""

from __future__ import annotations

import pytest

from feelies.alpha.promotion_evidence import validate_quote_freeze_backstop
from feelies.forensics.decouple_backstop import (
    QuoteFreezeEpisode,
    build_quote_freeze_backstop_evidence,
)

_BOUND_S = 3600.0


def _episode(
    *,
    hold_seconds: float,
    exit_reason: str,
    strategy_id: str = "kyle",
    symbol: str = "APP",
) -> QuoteFreezeEpisode:
    return QuoteFreezeEpisode(
        strategy_id=strategy_id,
        symbol=symbol,
        hold_seconds=hold_seconds,
        exit_reason=exit_reason,
    )


class TestQuoteFreezeBackstop:
    def test_all_episodes_exit_by_session_flatten_pass(self) -> None:
        episodes = [
            _episode(hold_seconds=1800.0, exit_reason="SESSION_FLATTEN"),
            _episode(hold_seconds=600.0, exit_reason="MAX_HOLD_AFTER_SAFE_OFF"),
            _episode(hold_seconds=900.0, exit_reason="HARD_EXIT_AGE"),
        ]
        ev = build_quote_freeze_backstop_evidence(episodes, session_flatten_bound_seconds=_BOUND_S)
        assert ev.quote_freeze_episodes == 3
        assert ev.exited_by_session_flatten == 3
        assert ev.breached_session_backstop == 0
        assert ev.max_hold_seconds_observed == 1800.0
        assert validate_quote_freeze_backstop(ev) == []

    def test_stranded_book_is_a_backstop_breach(self) -> None:
        # An episode that never exited (empty reason) is stranded past the
        # session backstop — a §2.3 defect, so the gate FAILs.
        episodes = [
            _episode(hold_seconds=1800.0, exit_reason="SESSION_FLATTEN"),
            _episode(hold_seconds=_BOUND_S, exit_reason=""),  # never exited
        ]
        ev = build_quote_freeze_backstop_evidence(episodes, session_flatten_bound_seconds=_BOUND_S)
        assert ev.breached_session_backstop == 1
        assert ev.exited_by_session_flatten == 1
        errors = validate_quote_freeze_backstop(ev)
        assert any("stranded past the wall-clock backstop" in e for e in errors)

    def test_hold_past_the_bound_is_a_breach(self) -> None:
        episodes = [
            _episode(hold_seconds=_BOUND_S + 120.0, exit_reason="SESSION_FLATTEN"),
        ]
        ev = build_quote_freeze_backstop_evidence(episodes, session_flatten_bound_seconds=_BOUND_S)
        assert ev.breached_session_backstop == 1
        errors = validate_quote_freeze_backstop(ev)
        assert errors  # both the breach and the max-hold overrun surface

    def test_no_freeze_episodes_exercised_fails(self) -> None:
        ev = build_quote_freeze_backstop_evidence([], session_flatten_bound_seconds=_BOUND_S)
        assert ev.quote_freeze_episodes == 0
        errors = validate_quote_freeze_backstop(ev)
        assert any("session backstop was not exercised" in e for e in errors)

    def test_builder_rejects_nonpositive_bound(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            build_quote_freeze_backstop_evidence([], session_flatten_bound_seconds=0.0)

    def test_builder_rejects_negative_hold(self) -> None:
        with pytest.raises(ValueError, match="hold_seconds must be >= 0"):
            build_quote_freeze_backstop_evidence(
                [_episode(hold_seconds=-1.0, exit_reason="SESSION_FLATTEN")],
                session_flatten_bound_seconds=_BOUND_S,
            )

    def test_is_deterministic(self) -> None:
        episodes = [
            _episode(hold_seconds=1800.0, exit_reason="SESSION_FLATTEN"),
            _episode(hold_seconds=600.0, exit_reason="MAX_HOLD_AFTER_SAFE_OFF"),
        ]
        a = build_quote_freeze_backstop_evidence(episodes, session_flatten_bound_seconds=_BOUND_S)
        b = build_quote_freeze_backstop_evidence(episodes, session_flatten_bound_seconds=_BOUND_S)
        assert a == b
