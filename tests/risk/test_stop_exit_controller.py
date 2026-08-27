"""Risk-layer stop-loss and session-flatten emitter."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, DeRiskRequirement, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.moc_session import et_clock_to_ns
from feelies.execution.trading_session import resolve_trading_session_bounds
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.stop_exit import (
    STOP_EXIT_REASON_SESSION_FLAT,
    STOP_EXIT_REASON_STOP,
    STOP_EXIT_SOURCE_LAYER,
    StopExitController,
    StopExitPolicy,
)

_SYMBOL = "AAPL"


def _quote(
    *,
    bid: str,
    ask: str,
    ts: int = 2_000,
    exchange_ts: int | None = None,
    symbol: str = _SYMBOL,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"corr-{ts}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts if exchange_ts is not None else ts,
    )


def _build(
    policy: StopExitPolicy,
    *,
    positions: MemoryPositionStore | None = None,
    bounds: object = None,
) -> tuple[StopExitController, list[DeRiskRequirement], MemoryPositionStore]:
    bus = EventBus()
    orders: list[DeRiskRequirement] = []
    bus.subscribe(DeRiskRequirement, orders.append)  # type: ignore[arg-type]
    positions = positions if positions is not None else MemoryPositionStore()
    controller = StopExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=positions,
        policy=policy,
        trading_session_bounds=bounds,  # type: ignore[arg-type]
    )
    controller.attach()
    return controller, orders, positions


# ── Wiring ──────────────────────────────────────────────────────────────


def test_disabled_policy_does_not_subscribe() -> None:
    """A default deployment must stay bit-identical to one without the controller."""
    controller, orders, positions = _build(StopExitPolicy())
    positions.update(_SYMBOL, 100, Decimal("150.00"))
    controller._bus.publish(_quote(bid="100.00", ask="100.10"))
    assert orders == []


def test_flat_book_emits_nothing() -> None:
    controller, orders, _ = _build(StopExitPolicy(stop_loss_pct=0.01))
    controller._bus.publish(_quote(bid="100.00", ask="100.10"))
    assert orders == []


# ── Stop-loss ───────────────────────────────────────────────────────────


def test_percentage_stop_fires_on_adverse_move() -> None:
    controller, orders, positions = _build(StopExitPolicy(stop_loss_pct=0.01))
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    # −0.5%: inside the stop.
    controller._bus.publish(_quote(bid="149.20", ask="149.30", ts=2_000))
    assert orders == []

    # −1.1%: through it.
    controller._bus.publish(_quote(bid="148.30", ask="148.40", ts=3_000))
    assert len(orders) == 1
    order = orders[0]
    assert order.reason == STOP_EXIT_REASON_STOP
    assert order.source_layer == STOP_EXIT_SOURCE_LAYER
    assert order.side is Side.SELL
    assert order.quantity == 100
    # Symbol-net: the control belongs to no alpha.
    assert order.strategy_id == ""


def test_stop_on_a_short_fires_on_an_upward_move() -> None:
    controller, orders, positions = _build(StopExitPolicy(stop_loss_pct=0.01))
    positions.update(_SYMBOL, -100, Decimal("150.00"))

    controller._bus.publish(_quote(bid="151.80", ask="151.90", ts=3_000))
    assert len(orders) == 1
    assert orders[0].side is Side.BUY
    assert orders[0].quantity == 100


def test_per_share_stop_used_when_no_percentage_configured() -> None:
    controller, orders, positions = _build(StopExitPolicy(stop_loss_per_share=1.0))
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    controller._bus.publish(_quote(bid="149.45", ask="149.55", ts=2_000))
    assert orders == []
    controller._bus.publish(_quote(bid="148.45", ask="148.55", ts=3_000))
    assert len(orders) == 1


def test_percentage_stop_overrides_per_share() -> None:
    """A 1% stop on a 150 name is 1.50/share, so a 1.00/share move must not fire."""
    controller, orders, positions = _build(
        StopExitPolicy(stop_loss_per_share=0.50, stop_loss_pct=0.01)
    )
    positions.update(_SYMBOL, 100, Decimal("150.00"))
    controller._bus.publish(_quote(bid="148.95", ask="149.05", ts=2_000))
    assert orders == []


# ── Trailing stop ───────────────────────────────────────────────────────


def test_trailing_stop_needs_activation_before_it_can_fire() -> None:
    policy = StopExitPolicy(trail_activate_pct=0.01, trail_pct=0.5)
    controller, orders, positions = _build(policy)
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    # Favourable but below the activation threshold, then giving it all back.
    controller._bus.publish(_quote(bid="150.70", ask="150.80", ts=2_000))
    controller._bus.publish(_quote(bid="149.95", ask="150.05", ts=3_000))
    assert orders == []


def test_trailing_stop_fires_after_giving_back_half_the_peak() -> None:
    policy = StopExitPolicy(trail_activate_pct=0.01, trail_pct=0.5)
    controller, orders, positions = _build(policy)
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    # +2% peak — activates (threshold is 1%).
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=2_000))
    assert orders == []
    # Still holding +1.6% of the +3.00 peak; 0.5 x 3.00 = 1.50 retained is the floor.
    controller._bus.publish(_quote(bid="152.35", ask="152.45", ts=3_000))
    assert orders == []
    # Back to +0.9% — below the retained floor.
    controller._bus.publish(_quote(bid="151.30", ask="151.40", ts=4_000))
    assert len(orders) == 1
    assert orders[0].reason == STOP_EXIT_REASON_STOP


def test_trailing_peak_resets_when_the_symbol_goes_flat() -> None:
    """A new episode must not inherit the previous episode's peak."""
    policy = StopExitPolicy(trail_activate_pct=0.01, trail_pct=0.5)
    controller, orders, positions = _build(policy)
    positions.update(_SYMBOL, 100, Decimal("150.00"))
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=2_000))  # peak +3.00

    # Close out; the flat quote clears the peak.
    positions.update(_SYMBOL, -100, Decimal("153.00"))
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=3_000))
    assert orders == []

    # Re-open. Without a reset the stale +3.00 peak would fire immediately.
    positions.update(_SYMBOL, 100, Decimal("153.00"))
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=4_000))
    assert orders == []


def test_trailing_peak_resets_when_a_single_fill_flips_the_position() -> None:
    """A reversal never shows the controller a flat quote, so flat cannot be the reset.

    The peak belongs to one directional episode.  A fill that crosses zero starts
    a new one against a new entry price, and carrying the old peak into it arms a
    trail the new position never earned — here the short is exactly at its entry
    and would be flattened on the spot.
    """
    policy = StopExitPolicy(trail_activate_pct=0.01, trail_pct=0.5)
    controller, orders, positions = _build(policy)
    positions.update(_SYMBOL, 100, Decimal("150.00"), timestamp_ns=1_000)
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=2_000))  # peak +3.00
    assert orders == []

    # One fill takes long 100 straight to short 100 at the new entry.
    positions.update(_SYMBOL, -200, Decimal("153.00"), timestamp_ns=3_000)
    assert positions.get(_SYMBOL).quantity == -100

    # Flat on the new episode: nothing has been given back, so nothing may fire.
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=4_000))
    assert orders == []


def test_trailing_peak_resets_when_the_symbol_reopens_between_quotes() -> None:
    """Close and re-open inside one tick — the flat book is never quoted.

    ``_execute_reverse`` closes and re-enters within a single tick, so the
    flat-quote reset above cannot see the boundary.  Only the open-episode
    timestamp distinguishes the two episodes.
    """
    policy = StopExitPolicy(trail_activate_pct=0.01, trail_pct=0.5)
    controller, orders, positions = _build(policy)
    positions.update(_SYMBOL, 100, Decimal("150.00"), timestamp_ns=1_000)
    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=2_000))  # peak +3.00
    assert orders == []

    # Exit and re-enter the same side, both before the next quote arrives.
    positions.update(_SYMBOL, -100, Decimal("153.00"), timestamp_ns=3_000)
    positions.update(_SYMBOL, 100, Decimal("153.00"), timestamp_ns=3_001)

    controller._bus.publish(_quote(bid="152.95", ask="153.05", ts=4_000))
    assert orders == []


# ── Session flatten ─────────────────────────────────────────────────────


def _session_policy() -> StopExitPolicy:
    return StopExitPolicy(session_flatten_enabled=True, session_flatten_seconds_before_close=300)


def test_session_flatten_fires_inside_the_window() -> None:
    session_date = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(session_date)
    controller, orders, positions = _build(_session_policy(), bounds=bounds)
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    midday = et_clock_to_ns(session_date, "12:00")
    controller._bus.publish(_quote(bid="150.00", ask="150.10", ts=1, exchange_ts=midday))
    assert orders == []

    inside = bounds.rth_close_ns - 60 * 1_000_000_000
    controller._bus.publish(_quote(bid="150.00", ask="150.10", ts=2, exchange_ts=inside))
    assert len(orders) == 1
    assert orders[0].reason == STOP_EXIT_REASON_SESSION_FLAT
    assert orders[0].side is Side.SELL


def test_session_flatten_is_not_priced_as_a_panic() -> None:
    """A scheduled unwind must stay out of the fill models' panic-slippage set."""
    from feelies.execution._fill_helpers import STOP_EXIT_REASONS as PANIC_REASONS

    assert STOP_EXIT_REASON_STOP in PANIC_REASONS
    assert STOP_EXIT_REASON_SESSION_FLAT not in PANIC_REASONS


def test_stop_wins_when_both_would_fire() -> None:
    session_date = date(2026, 1, 15)
    bounds = resolve_trading_session_bounds(session_date)
    policy = StopExitPolicy(
        stop_loss_pct=0.01,
        session_flatten_enabled=True,
        session_flatten_seconds_before_close=300,
    )
    controller, orders, positions = _build(policy, bounds=bounds)
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    inside = bounds.rth_close_ns - 60 * 1_000_000_000
    controller._bus.publish(_quote(bid="148.30", ask="148.40", ts=2, exchange_ts=inside))
    assert len(orders) == 1
    # Priced as the panic it is, not as a scheduled unwind.
    assert orders[0].reason == STOP_EXIT_REASON_STOP


# ── Duplicate suppression and determinism ───────────────────────────────


def test_repeat_quotes_do_not_stack_a_second_exit() -> None:
    controller, orders, positions = _build(StopExitPolicy(stop_loss_pct=0.01))
    positions.update(_SYMBOL, 100, Decimal("150.00"))

    controller._bus.publish(_quote(bid="148.30", ask="148.40", ts=3_000))
    controller._bus.publish(_quote(bid="148.20", ask="148.30", ts=4_000))
    controller._bus.publish(_quote(bid="148.10", ask="148.20", ts=5_000))
    assert len(orders) == 1


def test_residual_position_releases_the_guard() -> None:
    """A partial close leaves a residual that must still be exitable."""
    controller, orders, positions = _build(StopExitPolicy(stop_loss_pct=0.01))
    positions.update(_SYMBOL, 100, Decimal("150.00"))
    controller._bus.publish(_quote(bid="148.30", ask="148.40", ts=3_000))
    assert len(orders) == 1

    # Only half filled; the quantity change releases the guard.
    positions.update(_SYMBOL, -50, Decimal("148.35"))
    controller._bus.publish(_quote(bid="148.20", ask="148.30", ts=4_000))
    assert len(orders) == 2
    assert orders[1].quantity == 50


def test_two_runs_emit_identical_orders() -> None:
    """Inv-5: content-derived ids and event-time stamps replay identically."""

    def _run() -> list[tuple[str, str, int, str]]:
        controller, orders, positions = _build(StopExitPolicy(stop_loss_pct=0.01))
        positions.update(_SYMBOL, 100, Decimal("150.00"))
        controller._bus.publish(_quote(bid="148.30", ask="148.40", ts=3_000))
        return [(o.order_id, o.symbol, o.quantity, o.reason) for o in orders]

    assert _run() == _run()
