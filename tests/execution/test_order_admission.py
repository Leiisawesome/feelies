"""Admission gates: the shared policy, and the two bases that feed it.

:mod:`feelies.execution.order_admission` holds one copy of the five Inv-11
admission gates. Both order paths run it; they differ only in how they answer
"does this order add exposure" -- standalone from its ``TradingIntent`` matrix,
composition from an ``ExposureDelta``.

The cross-product test below maps those two bases against each other over every
reachable intent rather than sampling cases someone thought of. They agree
everywhere but one, and that exception is asserted explicitly so it stays a
recorded decision instead of a latent surprise.
"""

from __future__ import annotations

import pytest

from feelies.core.events import Side, Signal, SignalDirection
from feelies.execution.intent import (
    SignalPositionTranslator,
    TradingIntent,
)
from feelies.execution.order_admission import (
    BLOCK_BELOW_MIN_ORDER_SHARES,
    BLOCK_HALT_BLACKOUT,
    BLOCK_LOCATE_UNAVAILABLE,
    BLOCK_SESSION_FLATTEN_WINDOW,
    BLOCK_SSR,
    ExposureDelta,
    admission_block_reason,
    exposure_delta_from_intent,
    side_for_intent,
)
from feelies.execution.regulatory import is_short_sale_intent
from feelies.portfolio.position_store import Position

# Mirrors the kernel's own set; duplicated here on purpose so the test fails if
# either definition drifts rather than following the kernel silently.
_ENTRY_OPENING_INTENTS = frozenset(
    {
        TradingIntent.ENTRY_LONG,
        TradingIntent.ENTRY_SHORT,
        TradingIntent.SCALE_UP,
        TradingIntent.REVERSE_LONG_TO_SHORT,
        TradingIntent.REVERSE_SHORT_TO_LONG,
    }
)


def _signal(direction: SignalDirection) -> Signal:
    return Signal(
        timestamp_ns=1_000,
        sequence=0,
        correlation_id="sig",
        source_layer="SIGNAL",
        symbol="AAPL",
        strategy_id="alpha_a",
        direction=direction,
        strength=1.0,
        edge_estimate_bps=10.0,
        layer="SIGNAL",
        horizon_seconds=300,
    )


def _side_for(intent_kind: TradingIntent, direction: SignalDirection, qty: int) -> Side:
    """Side the kernel's ``_side_from_intent`` resolves for this intent."""
    if intent_kind in (TradingIntent.ENTRY_LONG, TradingIntent.REVERSE_SHORT_TO_LONG):
        return Side.BUY
    if intent_kind in (TradingIntent.ENTRY_SHORT, TradingIntent.REVERSE_LONG_TO_SHORT):
        return Side.SELL
    if intent_kind is TradingIntent.SCALE_UP:
        return Side.BUY if direction is SignalDirection.LONG else Side.SELL
    if intent_kind is TradingIntent.EXIT:
        return Side.SELL if qty > 0 else Side.BUY
    raise AssertionError(f"no side for {intent_kind}")


@pytest.mark.parametrize("direction", list(SignalDirection))
@pytest.mark.parametrize("qty", [-250, -100, -50, -1, 0, 1, 50, 100, 250])
@pytest.mark.parametrize("target", [0, 1, 50, 100, 250])
def test_exposure_basis_matches_legacy_enum_except_zero_target_reversal(
    direction: SignalDirection,
    qty: int,
    target: int,
) -> None:
    """Map the whole intent matrix against the legacy enum classification.

    The enum arms (``_ENTRY_OPENING_INTENTS``) were the admission basis before
    the exposure delta replaced them. They agree everywhere except the
    zero-target reversal, and this enumerates the cross-product rather than
    sampling cases someone thought of.

    The surviving difference is the *point* of the change, not a defect: the
    exposure basis ships, the enum classification does not.
    """
    intent = SignalPositionTranslator().translate(
        _signal(direction), Position(symbol="AAPL", quantity=qty), target
    )
    if intent.intent is TradingIntent.NO_ACTION:
        return  # no order is built, so no gate runs

    assert side_for_intent(intent) == _side_for(intent.intent, direction, qty)
    delta = exposure_delta_from_intent(intent)
    assert delta.current_quantity == qty

    is_zero_target_reversal = (
        intent.intent in (TradingIntent.REVERSE_LONG_TO_SHORT, TradingIntent.REVERSE_SHORT_TO_LONG)
        and target == 0
    )
    if is_zero_target_reversal:
        return  # covered explicitly below

    assert delta.opens_or_increases_exposure == (intent.intent in _ENTRY_OPENING_INTENTS), (
        f"exposure basis disagrees for {intent.intent.name} "
        f"(qty={qty}, target={target}, post={delta.post_quantity})"
    )
    # ``is_short_sale_intent`` now delegates to this basis, so it must agree.
    assert delta.opens_or_increases_short == is_short_sale_intent(intent)


@pytest.mark.parametrize("direction", [SignalDirection.LONG, SignalDirection.SHORT])
@pytest.mark.parametrize("qty", [-250, -50, 50, 250])
def test_zero_target_reversal_is_a_flatten_not_an_opening(
    direction: SignalDirection,
    qty: int,
) -> None:
    """A ``REVERSE_*`` sized to zero trades to flat and must never be refused.

    Reachable: the sizer returns 0 (low strength, low regime factor, or a price
    that makes the budget round to nothing) while a position is open on the
    other side. ``translate`` then produces ``REVERSE_*`` with
    ``target_quantity = |qty| + 0``, which trades the whole position away.

    The legacy enum basis classified that as an opening, so a halt blackout,
    the session-flatten window, SSR or a missing locate could refuse it --
    a safety control trapping an open position, exactly the failure Inv-11
    exists to prevent. Every environment flag is hostile here; it still admits.
    """
    opposing = SignalDirection.LONG if qty < 0 else SignalDirection.SHORT
    if direction is not opposing:
        return  # only the opposite-side case produces a reversal

    intent = SignalPositionTranslator().translate(
        _signal(direction), Position(symbol="AAPL", quantity=qty), 0
    )
    assert intent.intent in (
        TradingIntent.REVERSE_LONG_TO_SHORT,
        TradingIntent.REVERSE_SHORT_TO_LONG,
    )
    assert intent.target_quantity == abs(qty)

    delta = exposure_delta_from_intent(intent)
    assert delta.post_quantity == 0, "a zero-target reversal lands the book flat"
    assert not delta.opens_or_increases_exposure
    assert not delta.opens_or_increases_short
    # The legacy basis disagreed, which is why this case is pinned.
    assert intent.intent in _ENTRY_OPENING_INTENTS

    assert (
        admission_block_reason(
            opens_exposure=delta.opens_or_increases_exposure,
            opens_short=delta.opens_or_increases_short,
            in_halt_blackout=True,
            in_session_flatten_window=True,
            ssr_active=True,
            locate_unavailable=True,
        )
        is None
    ), "a flatten must survive every admission gate (Inv-11)"


def test_flatten_to_zero_is_not_an_opening() -> None:
    """A clean exit to flat must not read as opening exposure.

    Same distinction Inv-11's forced-exit clamp turns on: magnitude shrinkage is
    not the test, crossing zero is.
    """
    assert not ExposureDelta(
        current_quantity=100, signed_quantity=-100
    ).opens_or_increases_exposure
    assert not ExposureDelta(
        current_quantity=-100, signed_quantity=100
    ).opens_or_increases_exposure
    # ... but crossing through zero is, even when the magnitude shrinks.
    crossed = ExposureDelta(current_quantity=100, signed_quantity=-170)
    assert abs(crossed.post_quantity) < abs(crossed.current_quantity)
    assert crossed.opens_or_increases_exposure


def test_partial_cover_is_not_a_short_sale() -> None:
    """Reducing a short is a buy; deepening one is the short sale."""
    assert not ExposureDelta(current_quantity=-100, signed_quantity=60).opens_or_increases_short
    assert not ExposureDelta(current_quantity=-100, signed_quantity=100).opens_or_increases_short
    assert ExposureDelta(current_quantity=-100, signed_quantity=-40).opens_or_increases_short
    # Crossing long -> short is a short sale even though it starts from a long.
    assert ExposureDelta(current_quantity=100, signed_quantity=-170).opens_or_increases_short


def test_reducing_orders_pass_every_environment_gate() -> None:
    """Inv-11: a reduction is never refused by halt, session, SSR or locate.

    Every environment flag is hostile here; the exit still admits.
    """
    reduce_long = ExposureDelta(current_quantity=100, signed_quantity=-100)
    assert (
        admission_block_reason(
            opens_exposure=reduce_long.opens_or_increases_exposure,
            opens_short=reduce_long.opens_or_increases_short,
            in_halt_blackout=True,
            in_session_flatten_window=True,
            ssr_active=True,
            locate_unavailable=True,
        )
        is None
    )


def test_block_precedence_is_stable() -> None:
    """Token order is part of the operator contract when several gates fire."""
    hostile = dict(
        opens_exposure=True,
        opens_short=True,
        in_halt_blackout=True,
        in_session_flatten_window=True,
        ssr_active=True,
        locate_unavailable=True,
    )
    assert admission_block_reason(**hostile) == BLOCK_HALT_BLACKOUT
    assert (
        admission_block_reason(**{**hostile, "in_halt_blackout": False})
        == BLOCK_SESSION_FLATTEN_WINDOW
    )
    assert (
        admission_block_reason(
            **{**hostile, "in_halt_blackout": False, "in_session_flatten_window": False},
        )
        == BLOCK_SSR
    )
    assert (
        admission_block_reason(
            **{
                **hostile,
                "in_halt_blackout": False,
                "in_session_flatten_window": False,
                "ssr_active": False,
            },
        )
        == BLOCK_LOCATE_UNAVAILABLE
    )


def test_min_size_is_skipped_when_quantity_unknown_and_exempt_for_exits() -> None:
    benign: dict[str, bool] = dict(
        opens_exposure=True,
        opens_short=False,
        in_halt_blackout=False,
        in_session_flatten_window=False,
        ssr_active=False,
        locate_unavailable=False,
    )
    # Quantity withheld: the caller re-checks at construction.
    assert admission_block_reason(**benign, min_order_shares=50) is None
    # Quantity supplied: the floor binds.
    assert (
        admission_block_reason(**benign, quantity=40, min_order_shares=50)
        == BLOCK_BELOW_MIN_ORDER_SHARES
    )
    # An exit below the floor must still be closable.
    assert (
        admission_block_reason(
            **{**benign, "opens_exposure": False},
            quantity=40,
            min_order_shares=50,
            exempt_from_min_size=True,
        )
        is None
    )
