"""Risk-layer stop-loss and end-of-session flatten emitter.

Two platform-level safety controls that were previously synthesised inline by the
kernel as fake ``Signal`` events carrying sentinel ``strategy_id`` values
(``__stop_exit__`` / ``__session_flat__``):

* **stop-loss / trailing stop** — a position moving against its entry beyond a
  configured threshold is closed;
* **session flatten** — any book still open inside the end-of-session window is
  unwound before the closing auction.

Neither is alpha conviction.  Both trigger on price and clock alone, so they are
risk controls, and they belong beside the other risk-layer exit authors
(:class:`~feelies.risk.hazard_exit.HazardExitController`,
:class:`~feelies.risk.exit_composer.ExitComposer`,
:class:`~feelies.risk.deferral_cap.DeferralCapController`) rather than in the
deterministic kernel.

Routing it through the shared bridge, rather than the SIGNAL path, also removes a
class of defect the sentinels caused: every predicate keyed on the RISK-layer
reason taxonomy silently mis-handled them because their reasons sat outside it
(see ``_order_owns_one_slice`` and ``_is_forced_market_exit`` in the kernel).

Scope
-----
Both exits are **symbol-net**: they read the aggregate
:class:`~feelies.portfolio.position_store.PositionStore` and flatten the whole
symbol, so the emitted order carries no ``strategy_id`` — it belongs to no alpha.
The kernel splits the resulting fill across whichever slices held the symbol.
Contrast the composer and deferral cap, which are slice-scoped.

Determinism (Inv-5): event-time timestamps carried through from the triggering
quote, content-derived order IDs, a dedicated sequence generator, and per-symbol
state keyed only on values read from the position store.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, OrderRequest, OrderType, Side
from feelies.core.identifiers import SequenceGenerator, derive_order_id
from feelies.execution.trading_session import (
    TradingSessionBounds,
    in_session_flatten_window,
)
from feelies.portfolio.position_store import PositionStore

_logger = logging.getLogger(__name__)

# ── Stop-exit OrderRequest signature (single source of truth) ────────────
# The kernel's forced-exit bridge (``Orchestrator._on_bus_hazard_order``) routes
# any ``OrderRequest`` carrying this source layer and one of these reasons
# through the non-vetoable submission path, mirroring the hazard controller and
# exit composer so all four risk-layer authors share one routing contract.
STOP_EXIT_SOURCE_LAYER: str = "RISK"
# A stop-loss or trailing-stop trigger.  This token is also listed in
# ``execution/_fill_helpers.STOP_EXIT_REASONS`` — the *panic-slippage* set the
# fill models consult — so a stop keeps crossing with panic pricing and depleted
# depth exactly as it did on the SIGNAL path.
STOP_EXIT_REASON_STOP: str = "STOP_EXIT"
# A scheduled end-of-session unwind.  Deliberately **absent** from the panic set:
# a scheduled flatten is not a panic, and pricing it as one would overstate its
# cost.  This matches the empty ``reason`` the inline session flat carried.
STOP_EXIT_REASON_SESSION_FLAT: str = "SESSION_FLAT"
STOP_EXIT_REASONS: frozenset[str] = frozenset(
    {
        STOP_EXIT_REASON_STOP,
        STOP_EXIT_REASON_SESSION_FLAT,
    }
)


@dataclass(frozen=True, kw_only=True)
class StopExitPolicy:
    """Platform-level stop and session-flatten thresholds.

    Percentage thresholds take precedence over the per-share fields when
    non-zero: a single configured value then applies across the universe
    regardless of per-symbol price level.  The per-share threshold can only be
    derived at evaluation time because it depends on the position's
    ``avg_entry_price``.

    All-zero stop fields disable the stop entirely, and
    ``session_flatten_enabled=False`` disables the scheduled unwind, so a default
    deployment emits nothing.
    """

    stop_loss_per_share: float = 0.0
    trail_activate_per_share: float = 0.0
    stop_loss_pct: float = 0.0
    trail_activate_pct: float = 0.0
    trail_pct: float = 0.5
    session_flatten_enabled: bool = False
    session_flatten_seconds_before_close: int = 0

    @property
    def stop_enabled(self) -> bool:
        return (
            self.stop_loss_per_share > 0
            or self.trail_activate_per_share > 0
            or self.stop_loss_pct > 0
            or self.trail_activate_pct > 0
        )

    @property
    def any_enabled(self) -> bool:
        return self.stop_enabled or self.session_flatten_enabled


class StopExitController:
    """Bus-attached stop-loss and session-flatten emitter.

    Construction is opt-in: bootstrap only instantiates the controller when the
    policy enables something, so a deployment with stops and session flatten off
    stays bit-identical to one without the controller wired.
    """

    __slots__ = (
        "_bus",
        "_seq",
        "_position_store",
        "_policy",
        "_bounds",
        "_attached",
        "_peak_pnl_per_share",
        "_pending_exit_symbols",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        position_store: PositionStore,
        policy: StopExitPolicy,
        trading_session_bounds: TradingSessionBounds | None = None,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._position_store = position_store
        self._policy = policy
        self._bounds = trading_session_bounds
        self._attached = False
        # Peak favourable excursion for the trailing stop, as
        # ``symbol -> (open_episode_start_ns, peak)``.  The episode is part of the
        # value because a peak earned by one position must not arm the trail on
        # the next one.
        self._peak_pnl_per_share: dict[str, tuple[int | None, float]] = {}
        # Suppress a duplicate close against one stale position.  Episode or
        # quantity changes release the guard for a new residual close.
        self._pending_exit_symbols: dict[str, tuple[int | None, int]] = {}

    def reset(self) -> None:
        """Clear trailing-stop peaks; keep policy and bus wiring."""
        self._peak_pnl_per_share.clear()
        self._pending_exit_symbols.clear()
        self._seq.reset()

    # ── Public API ───────────────────────────────────────────────────

    @property
    def policy(self) -> StopExitPolicy:
        return self._policy

    def attach(self) -> None:
        if self._attached:
            return
        if not self._policy.any_enabled:
            _logger.debug(
                "StopExitController.attach() — stop and session flatten both "
                "disabled; skipping bus subscription"
            )
            return
        self._bus.subscribe(NBBOQuote, self._on_quote)
        self._attached = True

    # ── Bus handler ──────────────────────────────────────────────────

    def _on_quote(self, quote: NBBOQuote) -> None:
        position = self._position_store.get(quote.symbol)
        if position.quantity == 0:
            # Flat: reset both episode-scoped guards so the next open is eligible.
            self._peak_pnl_per_share.pop(quote.symbol, None)
            self._pending_exit_symbols.pop(quote.symbol, None)
            return

        # Scheduled flatten first, then the stop.  Both close the whole symbol,
        # so at most one order is needed; the stop wins because a position that
        # is both past its stop and inside the close window should be priced as
        # the panic it is.
        reason: str | None = None
        if self._stop_triggered(quote, position.quantity, position.avg_entry_price):
            reason = STOP_EXIT_REASON_STOP
        elif self._session_flatten_triggered(quote):
            reason = STOP_EXIT_REASON_SESSION_FLAT
        if reason is None:
            return

        self._emit_exit(quote, position.quantity, reason)

    # ── Triggers ─────────────────────────────────────────────────────

    def _stop_triggered(
        self,
        quote: NBBOQuote,
        quantity: int,
        avg_entry_price: Decimal,
    ) -> bool:
        """Stop-loss or trailing-stop test against the position's entry.

        Also advances the trailing peak, so this must be called on every quote
        for an open position — not only when a trigger is plausible.
        """
        if not self._policy.stop_enabled:
            return False
        entry = float(avg_entry_price)
        if entry <= 0:
            return False

        mid = float((quote.bid + quote.ask) / Decimal(2))
        sign = 1.0 if quantity > 0 else -1.0
        unrealized_per_share = (mid - entry) * sign

        # Scope the peak to the open episode rather than resetting it when a quote
        # happens to find the book flat.  A reversal crosses zero within a single
        # fill and a close-and-reopen (``_execute_reverse``) completes inside one
        # tick, so neither ever presents this handler with a flat position — and
        # the inherited peak then arms a trail against an entry price the new
        # position never moved away from.  ``opened_at_ns`` already resets on both
        # transitions, and the duplicate-exit guard below keys on it too.
        opened = self._position_store.opened_at_ns(quote.symbol)
        previous = self._peak_pnl_per_share.get(quote.symbol)
        peak = (
            unrealized_per_share
            if previous is None or previous[0] != opened
            else max(previous[1], unrealized_per_share)
        )
        self._peak_pnl_per_share[quote.symbol] = (opened, peak)

        policy = self._policy
        stop_threshold = (
            entry * policy.stop_loss_pct
            if policy.stop_loss_pct > 0
            else policy.stop_loss_per_share
        )
        trail_activate_threshold = (
            entry * policy.trail_activate_pct
            if policy.trail_activate_pct > 0
            else policy.trail_activate_per_share
        )

        if stop_threshold > 0 and unrealized_per_share < -stop_threshold:
            return True
        return (
            trail_activate_threshold > 0
            and peak >= trail_activate_threshold
            and unrealized_per_share < peak * policy.trail_pct
        )

    def _session_flatten_triggered(self, quote: NBBOQuote) -> bool:
        """Whether the quote has crossed the session-flatten deadline."""
        return in_session_flatten_window(
            self._bounds,
            enabled=self._policy.session_flatten_enabled,
            seconds_before_close=self._policy.session_flatten_seconds_before_close,
            at_ns=quote.exchange_timestamp_ns,
        )

    # ── Emission ─────────────────────────────────────────────────────

    def _emit_exit(self, quote: NBBOQuote, quantity: int, reason: str) -> None:
        symbol = quote.symbol
        opened = self._position_store.opened_at_ns(symbol)
        # Release the duplicate-close guard when the episode or quantity changes.
        if symbol in self._pending_exit_symbols:
            if self._pending_exit_symbols[symbol] == (opened, quantity):
                return
            del self._pending_exit_symbols[symbol]

        side = Side.SELL if quantity > 0 else Side.BUY
        order = OrderRequest(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._seq.next(),
            source_layer=STOP_EXIT_SOURCE_LAYER,
            order_id=derive_order_id(
                f"{quote.correlation_id}:{quote.timestamp_ns}:{symbol}:{reason}"
            ),
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=abs(quantity),
            # Symbol-net: this control belongs to no alpha.  The kernel splits
            # the fill across whichever slices held the symbol.
            strategy_id="",
            reason=reason,
        )
        self._pending_exit_symbols[symbol] = (opened, quantity)
        self._bus.publish(order)
        _logger.info(
            "StopExitController emitted %s for %s (qty=%d, side=%s)",
            reason,
            symbol,
            abs(quantity),
            side.name,
        )


__all__ = [
    "STOP_EXIT_REASONS",
    "STOP_EXIT_REASON_SESSION_FLAT",
    "STOP_EXIT_REASON_STOP",
    "STOP_EXIT_SOURCE_LAYER",
    "StopExitController",
    "StopExitPolicy",
]
