"""Passive limit order router — queue-position fill model for backtest mode.

Implements the ``OrderRouter`` protocol with a passive limit order fill
model.  Instead of crossing the spread (market orders), entry orders
post limit orders at the near side of the BBO and fill via a deterministic
queue-drain model.

Fill model (L1-only, conservative):
  LIMIT orders rest at ``limit_price`` (bid for BUY, ask for SELL).
  Two fill triggers:

  1. **Through fill**: the opposite BBO crosses our level.
     - BUY:  ``ask <= limit_price`` (sellers met us)
     - SELL: ``bid >= limit_price`` (buyers met us)
     Fill is guaranteed (price-improved to the crossed BBO).

  2. **Level (drain) fill**: while our level is the BBO, each quote tick
     is a *seeded Bernoulli trial* against a per-tick fill hazard ``h``
     (``PassiveLimitOrderRouter._fill_hazard``).  The hazard rises with
     the observed fraction of the queue ahead that trades have drained
     (queue-depth regime) or with order-flow imbalance against the
     resting side (quote-imbalance regime, ``h0 = 1/fill_delay_ticks``).
     This replaces the old deterministic ``fill_delay_ticks`` /
     ``queue_position_shares`` thresholds: queue position is unobservable
     on L1, so the fill is probabilistic.

  Unfilled orders are cancelled after ``max_resting_ticks`` quotes.
  Each terminal resting order is classified by a ``PassiveFillOutcome``
  (stamped on the ack ``reason`` and tallied by ``passive_fill_stats``).

  MARKET orders use the same causal latency model and D14 cross-price +
  walk-the-book partial-fill semantics as :class:`~feelies.execution.backtest_router.BacktestOrderRouter`:
  ACKNOWLEDGED is always emitted before any fill or reject; with
  ``latency_ns > 0``, fills price off the first latency-eligible quote.

Invariants preserved:
  - Inv 5 (deterministic replay): the level-fill Bernoulli trial uses no
    RNG — the uniform is a SHA-256 hash of replay-stable quote/order keys
    (``_seeded_uniform``), so identical event logs replay bit-identically.
  - Inv 9 (backtest/live parity): implements the same OrderRouter
    protocol used by live and paper routers.
  - Inv 11 (fail-safe): MARKET orders fill once latency-eligible quotes
    arrive; passive orders that timeout are CANCELLED, not silently dropped;
    duplicate order_ids are rejected.
  - Inv 12 (transaction cost realism): passive fills charge zero
    spread cost and optionally model maker rebates.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from feelies.core.clock import Clock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.cost_model import CostModel, ZeroCostModel
from feelies.execution.market_fill import append_market_fill_acks, to_decimal
from feelies.execution.moc_fill import MocFillController
from feelies.execution.moc_session import MocSessionBounds
from feelies.execution.trading_session import (
    RthEntryFillGate,
    TradingSessionBounds,
)
from feelies.execution.tick_size import snap_limit_price


class PassiveFillOutcome(Enum):
    """Terminal classification of a resting passive limit order.

    Stamped onto the FILLED / CANCELLED ``OrderAck.reason`` and tallied
    by :meth:`PassiveLimitOrderRouter.passive_fill_stats` for backtest
    fill-quality forensics.
    """

    FILLED_BY_THROUGH = "FILLED_BY_THROUGH"
    FILLED_BY_DRAIN = "FILLED_BY_DRAIN"
    CANCELLED_MAX_RESTING_TICKS = "CANCELLED_MAX_RESTING_TICKS"
    CANCELLED_LEVEL_LEFT_BBO = "CANCELLED_LEVEL_LEFT_BBO"


@dataclass
class _PendingOrder:
    """Mutable state for a resting limit order."""

    request: OrderRequest
    side: Side
    limit_price: Decimal
    submit_time_ns: int
    # ACKNOWLEDGED ack timestamp captured at submit so subsequent acks
    # (CANCELLED on timeout / explicit cancel) can be floored at it to
    # preserve monotonic per-order ack ordering even when ``clock.now_ns()``
    # has not yet advanced past the post timestamp.
    ack_timestamp_ns: int = 0
    # Per-order queue threshold captured at post time.  Allows callers
    # to override the default via ``set_queue_ahead`` if they need a
    # per-order sampled position rather than a global assumption.
    queue_ahead_shares: int = 0
    ticks_at_level: int = 0
    total_ticks: int = 0
    shares_traded_at_level: int = 0
    # Whether the order was resting at the BBO on the most recent quote
    # evaluation — used to classify a timeout cancel as
    # CANCELLED_MAX_RESTING_TICKS (competitive at cancel) vs
    # CANCELLED_LEVEL_LEFT_BBO (behind the market at cancel).
    at_bbo: bool = False


@dataclass(frozen=True)
class _DeferredAggressiveFill:
    """MARKET order deferred until exchange time reaches ``deadline_ns``.

    ``ack_timestamp_ns`` matches the ACKNOWLEDGED ack emitted at submit.
    The FILLED timestamp uses ``max(clock.now_ns(), ack_timestamp_ns)`` so
    we do not add ``latency_ns`` again — the eligibility deadline already
    advanced exchange time by one latency slice — while staying aligned
    with the simulated decision clock under any ``ReplayFeed``
    ``market_data_latency_ns`` setting (parity with
    :class:`~feelies.execution.backtest_router.BacktestOrderRouter`).
    ``max_resting_ticks`` timeout rejects use the same floor so REJECTED
    does not precede ACKNOWLEDGED before the latency deadline.
    """

    request: OrderRequest
    fill_deadline_exchange_ns: int
    ack_timestamp_ns: int
    ticks_for_symbol: int = 0


class PassiveLimitOrderRouter:
    """Simulated order router with passive limit order fill model.

    Handles two order types:
      - ``LIMIT``: deferred fill via queue-position model (entries/exits)
      - ``MARKET``: cross-price aggressive fill with the same ``latency_ns``
        deferral and D14 depth walk as
        :class:`~feelies.execution.backtest_router.BacktestOrderRouter`
        (zero L1 depth rejects; no vacuum fills)

    The orchestrator must call ``on_quote()`` for each incoming quote
    so the router can (a) track the latest NBBO and (b) check resting
    orders for fill conditions.
    """

    def __init__(
        self,
        clock: Clock,
        latency_ns: int = 0,
        cost_model: CostModel | None = None,
        market_impact_factor: Decimal | int | str | float = Decimal("0.5"),
        max_impact_half_spreads: Decimal | int | str | float = Decimal("10"),
        *,
        fill_delay_ticks: int = 3,
        max_resting_ticks: int = 50,
        queue_position_shares: int = 0,
        cancel_fee_per_share: Decimal = Decimal("0.0"),
        fill_hazard_max: Decimal | int | str | float = Decimal("0.5"),
        moc_bounds: MocSessionBounds | None = None,
        trading_session_bounds: TradingSessionBounds | None = None,
    ) -> None:
        self._clock = clock
        self._latency_ns = latency_ns
        self._cost_model: CostModel = cost_model or ZeroCostModel()
        self._market_impact_factor = to_decimal(
            market_impact_factor, "market_impact_factor"
        )
        self._max_impact_half_spreads = to_decimal(
            max_impact_half_spreads, "max_impact_half_spreads"
        )
        self._fill_delay_ticks = fill_delay_ticks
        self._max_resting_ticks = max_resting_ticks
        self._queue_position_shares = queue_position_shares
        self._cancel_fee_per_share = cancel_fee_per_share
        self._fill_hazard_max = to_decimal(
            fill_hazard_max, "fill_hazard_max"
        )
        # Base per-tick fill hazard for the quote-imbalance regime,
        # h0 = 1 / fill_delay_ticks (so mean ticks-to-fill ≈
        # fill_delay_ticks at a balanced book).  fill_delay_ticks <= 0
        # collapses to the hazard cap (near-immediate level fills).
        self._base_hazard = (
            Decimal(1) / Decimal(fill_delay_ticks)
            if fill_delay_ticks > 0
            else self._fill_hazard_max
        )

        # ── Passive fill-quality forensics (BT-2) ────────────────────
        self._fills_by_through = 0
        self._fills_by_drain = 0
        self._cancels_max_resting = 0
        self._cancels_level_left = 0
        self._sum_ticks_to_fill = 0

        self._last_quotes: dict[str, NBBOQuote] = {}
        self._pending_acks: list[OrderAck] = []
        self._resting_orders: dict[str, _PendingOrder] = {}
        # Symbol → insertion-ordered order_ids index so on_quote() is O(k)
        # in the number of orders for that symbol rather than O(n) across
        # all orders.  Order of fills/cancels is determinism-critical.
        self._resting_by_symbol: dict[str, dict[str, None]] = {}
        # Full set of order_ids ever submitted — used for idempotent reject.
        self._submitted_order_ids: set[str] = set()
        self._ack_seq = SequenceGenerator()
        # Deferred MARKET orders: see ``_DeferredAggressiveFill``.
        self._deferred_aggressive: list[_DeferredAggressiveFill] = []
        self._moc: MocFillController | None = None
        if moc_bounds is not None:
            self._moc = MocFillController(
                moc_bounds,
                clock,
                self._cost_model,
                self._ack_seq,
                self._pending_acks,
                max_resting_ticks=max_resting_ticks,
            )
        self._rth_gate = RthEntryFillGate(trading_session_bounds)

    def bind_position_qty(self, fn) -> None:
        """Wire signed position qty for RTH entry/exit discrimination (BT-16)."""
        self._rth_gate.bind_position_qty(fn)

    # ── Public interface (OrderRouter protocol) ──────────────────

    def on_quote(self, quote: NBBOQuote) -> None:
        """Update latest quote and check resting orders for fills."""
        self._last_quotes[quote.symbol] = quote
        if self._moc is not None:
            self._moc.on_quote(quote)
        self._flush_deferred_aggressive(quote)
        self._check_resting_orders(quote)

    def on_trade(self, trade: Trade) -> None:
        """Accumulate traded volume for the queue-position fill model.

        For each resting order at the traded symbol with a non-zero
        per-order ``queue_ahead_shares`` (or any resting order when
        the global ``queue_position_shares`` is set), adds the trade
        size to ``shares_traded_at_level`` if the trade price is at or
        through our limit price (i.e. the order queue is draining).
        """
        order_ids = self._resting_by_symbol.get(trade.symbol)
        if not order_ids:
            return
        for order_id in order_ids:
            pending = self._resting_orders[order_id]
            if pending.queue_ahead_shares <= 0:
                continue
            if pending.side == Side.BUY and trade.price <= pending.limit_price:
                pending.shares_traded_at_level += trade.size
            elif pending.side == Side.SELL and trade.price >= pending.limit_price:
                pending.shares_traded_at_level += trade.size

    def _rth_reject_entry_if_needed(
        self,
        request: OrderRequest,
        exchange_ts_ns: int,
    ) -> bool:
        suppress, reason = self._rth_gate.should_suppress(
            request, exchange_ts_ns,
        )
        if not suppress:
            return False
        self._reject(request, reason)
        return True

    def submit(self, request: OrderRequest) -> None:
        if request.order_id in self._submitted_order_ids:
            self._reject(
                request,
                f"duplicate order_id: {request.order_id}",
                release_submitted_id=False,
            )
            return
        self._submitted_order_ids.add(request.order_id)

        quote = self._last_quotes.get(request.symbol)
        if quote is None:
            self._reject(request, "no quote available for symbol")
            return

        # Crossed (bid > ask) quotes are data errors; locked (bid == ask)
        # leaves no passive side and breaks the marketability guard.
        # Applied before the MOC ack path so MOC orders share the same
        # data-quality guard as MARKET/LIMIT orders at submit time.
        if quote.bid >= quote.ask:
            self._reject(
                request,
                f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
            )
            return

        if self._rth_reject_entry_if_needed(
            request, quote.exchange_timestamp_ns,
        ):
            return

        if self._moc is not None and self._moc.submit(
            request,
            exchange_timestamp_ns=quote.exchange_timestamp_ns,
            reject_fn=self._reject,
        ):
            return

        if request.order_type == OrderType.MARKET:
            self._submit_aggressive_market(request, quote)
        elif request.order_type == OrderType.LIMIT:
            self._post_passive(request, quote)
        else:
            self._reject(request, f"unsupported order type: {request.order_type}")

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks

    # ── Aggressive (market) fills ────────────────────────────────

    def _submit_aggressive_market(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
    ) -> None:
        """MARKET submit: ACKNOWLEDGED first (Inv 9, parity with
        ``BacktestOrderRouter``); then immediate FILLED when ``latency_ns <= 0``
        (after depth check), else deferred fill on the first exchange-time-
        eligible quote.
        """
        ack_ts = self._clock.now_ns() + self._latency_ns
        self._pending_acks.append(OrderAck(
            timestamp_ns=ack_ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))

        if self._latency_ns <= 0:
            depth = (
                quote.ask_size if request.side == Side.BUY else quote.bid_size
            )
            if depth <= 0:
                self._reject(
                    request,
                    f"zero depth on {request.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                )
                return
            self._execute_market_fill(request, quote, fill_ts=ack_ts)
            return

        # Deferred fills: depth is checked in ``_flush_deferred_aggressive`` on
        # the first latency-eligible quote (not the submission quote).
        self._deferred_aggressive.append(
            _DeferredAggressiveFill(
                request=request,
                fill_deadline_exchange_ns=(
                    quote.exchange_timestamp_ns + self._latency_ns
                ),
                ack_timestamp_ns=ack_ts,
            ),
        )

    def _flush_deferred_aggressive(self, quote: NBBOQuote) -> None:
        if not self._deferred_aggressive:
            return
        remaining: list[_DeferredAggressiveFill] = []
        for dm in self._deferred_aggressive:
            req = dm.request
            if req.symbol != quote.symbol:
                remaining.append(dm)
                continue
            ticks_for_symbol = dm.ticks_for_symbol + 1
            if quote.exchange_timestamp_ns < dm.fill_deadline_exchange_ns:
                if ticks_for_symbol >= self._max_resting_ticks:
                    # Preserve monotonic ordering of the order's ack stream:
                    # the timeout fires precisely because exchange time has
                    # not yet reached the latency deadline, so ``clock.now_ns()``
                    # may be < the stored ACKNOWLEDGED timestamp.
                    self._reject(
                        req,
                        f"deferred aggressive timeout after "
                        f"{ticks_for_symbol} ticks (no latency-eligible quote)",
                        timestamp_ns=max(
                            self._clock.now_ns(),
                            dm.ack_timestamp_ns,
                        ),
                    )
                    continue
                remaining.append(
                    replace(dm, ticks_for_symbol=ticks_for_symbol),
                )
                continue
            # Post-ACK reject paths must floor at ``ack_timestamp_ns`` so
            # REJECTED never timestamps before ACKNOWLEDGED (mirrors the
            # ``max_resting_ticks`` timeout path above).
            reject_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            if quote.bid >= quote.ask:
                self._reject(
                    req,
                    f"crossed or locked quote bid={quote.bid} ask={quote.ask}",
                    timestamp_ns=reject_ts,
                )
                continue
            depth = (
                quote.ask_size if req.side == Side.BUY else quote.bid_size
            )
            if depth <= 0:
                self._reject(
                    req,
                    f"zero depth on {req.side.name} side "
                    f"(bid_size={quote.bid_size}, ask_size={quote.ask_size})",
                    timestamp_ns=reject_ts,
                )
                continue
            # Marketable LIMIT orders route here via ``_post_passive``; during a
            # positive-latency window the BBO may move so mid exceeds limit_price.
            if req.limit_price is not None:
                fill_mid = (quote.bid + quote.ask) / Decimal("2")
                if (
                    req.side == Side.BUY and fill_mid > req.limit_price
                ) or (
                    req.side == Side.SELL and fill_mid < req.limit_price
                ):
                    self._reject(
                        req,
                        f"deferred fill mid {fill_mid} violates "
                        f"{req.side.name} limit {req.limit_price} "
                        f"(BBO moved adversely during latency window)",
                        timestamp_ns=reject_ts,
                    )
                    continue
            if self._rth_reject_entry_if_needed(
                req, quote.exchange_timestamp_ns,
            ):
                continue
            fill_ts = max(self._clock.now_ns(), dm.ack_timestamp_ns)
            self._execute_market_fill(req, quote, fill_ts=fill_ts)
        self._deferred_aggressive = remaining

    def _execute_market_fill(
        self,
        request: OrderRequest,
        quote: NBBOQuote,
        *,
        fill_ts: int | None = None,
    ) -> None:
        """Aggressive fill at ``quote`` — shared D14 model with ``BacktestOrderRouter``."""
        if self._rth_reject_entry_if_needed(
            request, quote.exchange_timestamp_ns,
        ):
            return
        if fill_ts is None:
            fill_ts = self._clock.now_ns() + self._latency_ns
        append_market_fill_acks(
            self._pending_acks,
            self._ack_seq,
            self._cost_model,
            request,
            quote,
            fill_ts,
            market_impact_factor=self._market_impact_factor,
            max_impact_half_spreads=self._max_impact_half_spreads,
        )

    # ── Passive (limit) order posting ────────────────────────────

    def _post_passive(self, request: OrderRequest, quote: NBBOQuote) -> None:
        """Record a resting limit order and emit ACKNOWLEDGED ack."""
        limit_price = request.limit_price
        if limit_price is None:
            limit_price = quote.bid if request.side == Side.BUY else quote.ask

        # D13: marketability guard — evaluate against the *submitted*
        # limit price (pre-snap) so a sub-penny marketable limit (e.g.
        # BUY 100.072 vs ask 100.071) isn't floored below the cross by
        # ``snap_limit_price`` and then mis-classified as passive.
        if request.side == Side.BUY and limit_price >= quote.ask:
            self._submit_aggressive_market(request, quote)
            return
        if request.side == Side.SELL and limit_price <= quote.bid:
            self._submit_aggressive_market(request, quote)
            return

        limit_price = snap_limit_price(request.side, limit_price)

        ack_ts = self._clock.now_ns()
        pending = _PendingOrder(
            request=request,
            side=request.side,
            limit_price=limit_price,
            submit_time_ns=ack_ts,
            ack_timestamp_ns=ack_ts,
            queue_ahead_shares=self._queue_position_shares,
        )
        self._resting_orders[request.order_id] = pending
        self._resting_by_symbol.setdefault(request.symbol, {})[
            request.order_id
        ] = None

        self._pending_acks.append(OrderAck(
            timestamp_ns=ack_ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.ACKNOWLEDGED,
            request_sequence=request.sequence,
        ))

    def set_queue_ahead(self, order_id: str, shares: int) -> bool:
        """Override the queue-ahead threshold for a specific resting order.

        Allows per-order queue-position sampling (e.g. drawn from an
        exchange-specific distribution) rather than the global default.
        Returns True if the order was found.
        """
        pending = self._resting_orders.get(order_id)
        if pending is None:
            return False
        pending.queue_ahead_shares = shares
        return True

    # ── Resting order fill checking ──────────────────────────────

    def _check_resting_orders(self, quote: NBBOQuote) -> None:
        """Evaluate all resting orders for the quoted symbol."""
        order_ids = self._resting_by_symbol.get(quote.symbol)
        if not order_ids:
            return

        to_remove: list[str] = []

        for order_id in order_ids:
            pending = self._resting_orders[order_id]
            pending.total_ticks += 1
            action = self._evaluate_fill(pending, quote)

            if action in ("through", "drain"):
                suppress, rth_reason = self._rth_gate.should_suppress(
                    pending.request, quote.exchange_timestamp_ns,
                )
                if suppress:
                    self._reject(
                        pending.request,
                        rth_reason,
                        timestamp_ns=max(
                            self._clock.now_ns(), pending.ack_timestamp_ns,
                        ),
                    )
                    to_remove.append(order_id)
                    continue

            if action == "through":
                # Price improvement on through-fills: IBKR (and the NMS
                # rule) fills limit orders at the limit price OR BETTER,
                # never worse.  When the opposite-side BBO has gapped
                # through our limit (BUY: ask < limit, SELL: bid > limit),
                # the realistic fill price is the new BBO, not the resting
                # limit.  The market traded *through* the resting order,
                # so this is the adversely-selected regime in the cost
                # model (is_through_fill=True).
                fill_price = pending.limit_price
                if pending.side == Side.BUY and quote.ask < pending.limit_price:
                    fill_price = quote.ask
                elif pending.side == Side.SELL and quote.bid > pending.limit_price:
                    fill_price = quote.bid
                self._emit_passive_fill(
                    pending,
                    fill_price=fill_price,
                    is_through_fill=True,
                    outcome=PassiveFillOutcome.FILLED_BY_THROUGH,
                )
                self._record_fill(pending, PassiveFillOutcome.FILLED_BY_THROUGH)
                to_remove.append(order_id)
            elif action == "drain":
                # Queue-drain fill: the queue ahead drained at a stable
                # price.  Fill at the resting limit, benign adverse
                # selection (is_through_fill=False).
                self._emit_passive_fill(
                    pending,
                    fill_price=pending.limit_price,
                    is_through_fill=False,
                    outcome=PassiveFillOutcome.FILLED_BY_DRAIN,
                )
                self._record_fill(pending, PassiveFillOutcome.FILLED_BY_DRAIN)
                to_remove.append(order_id)
            elif action == "cancel":
                outcome = (
                    PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS
                    if pending.at_bbo
                    else PassiveFillOutcome.CANCELLED_LEVEL_LEFT_BBO
                )
                self._emit_timeout_cancel(pending, outcome=outcome)
                self._record_cancel(outcome)
                to_remove.append(order_id)

        for oid in to_remove:
            self._remove_resting(oid)

    def _evaluate_fill(self, pending: _PendingOrder, quote: NBBOQuote) -> str:
        """Determine whether a resting order fills, cancels, or continues.

        Returns ``"through"``, ``"drain"``, ``"cancel"``, or ``"wait"``.

        Fill model (BT-2): a through-fill (the opposite-side BBO crosses
        the resting level) is still a guaranteed fill.  A level fill is a
        *seeded Bernoulli trial per quote tick* against a per-tick fill
        hazard ``h`` (see :meth:`_fill_hazard`): the queue ahead drains
        probabilistically rather than after a fixed tick count or share
        threshold.  Determinism (Inv-5) is preserved because the uniform
        is derived from a SHA-256 of the replay-stable quote/order keys
        (no RNG) — see :meth:`_seeded_uniform`.
        """
        at_level = False
        if pending.side == Side.BUY:
            if quote.ask <= pending.limit_price:
                pending.at_bbo = True
                return "through"
            if quote.bid <= pending.limit_price:
                at_level = True
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0
        else:
            if quote.bid >= pending.limit_price:
                pending.at_bbo = True
                return "through"
            if quote.ask >= pending.limit_price:
                at_level = True
            else:
                pending.ticks_at_level = 0
                pending.shares_traded_at_level = 0

        pending.at_bbo = at_level
        if at_level:
            pending.ticks_at_level += 1
            hazard = self._fill_hazard(pending, quote)
            if hazard > 0 and self._seeded_uniform(pending, quote) < hazard:
                return "drain"

        if pending.total_ticks >= self._max_resting_ticks:
            return "cancel"

        return "wait"

    def _fill_hazard(
        self, pending: _PendingOrder, quote: NBBOQuote,
    ) -> Decimal:
        """Per-tick level-fill hazard ``h ∈ [0, fill_hazard_max]``.

        Two regimes, selected by whether a queue depth was supplied:

        * **Queue-depth** (``queue_ahead_shares > 0``): the order sits
          behind ``queue_ahead_shares`` at its level and cannot fill until
          observed trades have drained the queue ahead
          (``shares_traded_at_level >= queue_ahead_shares``, fed by
          :meth:`on_trade`).  Once at the front, each tick fills at the
          hazard cap — the residual queue-position uncertainty (you are at
          the front but not guaranteed the next print).  Below the
          threshold the hazard is exactly 0, so a not-yet-drained queue
          never fills (deterministic).

        * **Quote-imbalance** (``queue_ahead_shares == 0``): a base hazard
          ``h0 = 1 / fill_delay_ticks`` modulated by the order-flow
          imbalance — the share of size resting on the *opposite* side,
          ``imbalance = opp_size / (our_size + opp_size)``.  A book tilted
          against the resting side (heavy opposite size) predicts the
          resting level getting hit, so ``aggression = 2 · imbalance``
          (neutral 1.0 at a balanced book): ``h = h0 · aggression``.

        ``ticks_at_level`` enters through the repeated per-tick Bernoulli
        trials: the cumulative fill probability by tick ``n`` is
        ``1 − ∏(1 − h_i)``, an increasing function of time at the level.
        """
        if pending.queue_ahead_shares > 0:
            if pending.shares_traded_at_level >= pending.queue_ahead_shares:
                return self._fill_hazard_max
            return Decimal(0)

        our_size = quote.bid_size if pending.side == Side.BUY else quote.ask_size
        opp_size = quote.ask_size if pending.side == Side.BUY else quote.bid_size
        total_size = our_size + opp_size
        if total_size > 0:
            imbalance = Decimal(opp_size) / Decimal(total_size)
        else:
            imbalance = Decimal("0.5")
        aggression = Decimal(2) * imbalance
        hazard = self._base_hazard * aggression

        if hazard < 0:
            return Decimal(0)
        if hazard > self._fill_hazard_max:
            return self._fill_hazard_max
        return hazard

    def _seeded_uniform(
        self, pending: _PendingOrder, quote: NBBOQuote,
    ) -> Decimal:
        """Deterministic per-tick uniform in ``[0, 1)`` for the fill trial.

        Derived from a SHA-256 over replay-stable keys (symbol, quote
        sequence number, exchange timestamp, the order's resting-tick
        count, side, level price, order id) so the draw varies per tick
        and per order yet replays bit-identically (Inv-5) — no live RNG,
        no sampling.
        """
        seed = (
            f"{quote.symbol}|{quote.sequence_number}|"
            f"{quote.exchange_timestamp_ns}|{pending.total_ticks}|"
            f"{pending.side.name}|{pending.limit_price}|"
            f"{pending.request.order_id}"
        )
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        return Decimal(value) / Decimal(1 << 64)

    def _record_fill(
        self, pending: _PendingOrder, outcome: PassiveFillOutcome,
    ) -> None:
        if outcome is PassiveFillOutcome.FILLED_BY_THROUGH:
            self._fills_by_through += 1
        else:
            self._fills_by_drain += 1
        self._sum_ticks_to_fill += pending.total_ticks

    def _record_cancel(self, outcome: PassiveFillOutcome) -> None:
        if outcome is PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS:
            self._cancels_max_resting += 1
        else:
            self._cancels_level_left += 1

    def passive_fill_stats(self) -> dict[str, float | int]:
        """Backtest fill-quality forensics (BT-2).

        Returns counts per :class:`PassiveFillOutcome`, the
        ``passive_fill_rate`` (fills / terminal resting orders), and
        ``mean_resting_ticks_to_fill`` (0.0 when nothing has filled).
        """
        filled = self._fills_by_through + self._fills_by_drain
        cancelled = self._cancels_max_resting + self._cancels_level_left
        terminal = filled + cancelled
        return {
            "filled": filled,
            "fills_by_through": self._fills_by_through,
            "fills_by_drain": self._fills_by_drain,
            "cancelled": cancelled,
            "cancels_max_resting_ticks": self._cancels_max_resting,
            "cancels_level_left_bbo": self._cancels_level_left,
            "passive_fill_rate": (filled / terminal) if terminal > 0 else 0.0,
            "mean_resting_ticks_to_fill": (
                self._sum_ticks_to_fill / filled if filled > 0 else 0.0
            ),
        }

    # ── Ack emission helpers ─────────────────────────────────────
    def _reject(
        self,
        request: OrderRequest,
        reason: str,
        *,
        timestamp_ns: int | None = None,
        release_submitted_id: bool = True,
    ) -> None:
        """Emit a REJECTED ack for the given order request.

        Clears ``order_id`` from :attr:`_submitted_order_ids` unless
        ``release_submitted_id=False`` (duplicate submissions — the id may
        still belong to an in-flight resting or deferred aggressive order).
        """
        ts = self._clock.now_ns() if timestamp_ns is None else timestamp_ns
        self._pending_acks.append(OrderAck(
            timestamp_ns=ts,
            correlation_id=request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.REJECTED,
            reason=reason,
            request_sequence=request.sequence,
        ))
        if release_submitted_id:
            self._submitted_order_ids.discard(request.order_id)

    def _emit_passive_fill(
        self,
        pending: _PendingOrder,
        fill_price: Decimal | None = None,
        is_through_fill: bool = False,
        outcome: PassiveFillOutcome = PassiveFillOutcome.FILLED_BY_DRAIN,
    ) -> None:
        """Emit a FILLED ack for a passive limit order.

        Calls the cost model with ``is_taker=False`` so the maker rebate
        and adverse-selection penalty are applied by the model — no
        separate rebate subtraction needed here.

        ``fill_price`` defaults to the resting ``limit_price`` (queue-
        drain / level fills).  Callers may pass a better price (BUY:
        a lower ask that gapped through, SELL: a higher bid) to model
        IBKR's price-improvement rule on through-fills.

        ``is_through_fill`` selects the cost model's adverse-selection
        regime: ``True`` for a market-through (gapped) fill, ``False``
        (default) for a queue-drain / level fill.

        ``outcome`` is stamped onto the FILLED ack ``reason`` for
        fill-quality forensics (BT-2).
        """
        if fill_price is None:
            fill_price = pending.limit_price
        # Maker rounding: a passive fill must be at the resting limit
        # OR BETTER (BUY pays no more, SELL receives no less).  Taker
        # rounding (``snap_fill_price``) would round *against* the
        # resting order on through-fills and erase the documented
        # price improvement, so snap on the limit-price grid instead.
        fill_price = snap_limit_price(pending.side, fill_price)
        fill_ts = self._clock.now_ns() + self._latency_ns

        costs = self._cost_model.compute(
            symbol=pending.request.symbol,
            side=pending.side,
            quantity=pending.request.quantity,
            fill_price=fill_price,
            half_spread=Decimal("0"),
            is_taker=False,
            is_short=pending.request.is_short,
            is_through_fill=is_through_fill,
        )

        self._pending_acks.append(OrderAck(
            timestamp_ns=fill_ts,
            correlation_id=pending.request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=pending.request.order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=pending.request.quantity,
            fill_price=fill_price,
            fees=costs.total_fees,
            cost_bps=costs.cost_bps,
            reason=outcome.value,
            request_sequence=pending.request.sequence,
        ))

    def _cancel_fees(self, quantity: int) -> Decimal:
        """Deterministically quantized cancel-fee computation."""
        return (self._cancel_fee_per_share * quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def _emit_timeout_cancel(
        self,
        pending: _PendingOrder,
        outcome: PassiveFillOutcome = (
            PassiveFillOutcome.CANCELLED_MAX_RESTING_TICKS
        ),
    ) -> None:
        """Emit a CANCELLED ack for a timed-out resting order.

        Floors at ``pending.ack_timestamp_ns`` so the CANCELLED ack never
        timestamps before ACKNOWLEDGED — matches the same guard the
        aggressive-deferred-timeout path applies in
        ``_flush_deferred_aggressive``.

        ``outcome`` (CANCELLED_MAX_RESTING_TICKS when the order was still
        at the BBO, CANCELLED_LEVEL_LEFT_BBO when it had fallen behind the
        market) is prepended to the ``reason`` for fill-quality forensics.
        """
        cancel_fees = self._cancel_fees(pending.request.quantity)
        cancel_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)
        self._pending_acks.append(OrderAck(
            timestamp_ns=cancel_ts,
            correlation_id=pending.request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=pending.request.order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.CANCELLED,
            reason=(
                f"{outcome.value}: passive limit timeout after "
                f"{pending.total_ticks} ticks"
            ),
            fees=cancel_fees if cancel_fees > 0 else Decimal("0"),
            request_sequence=pending.request.sequence,
        ))

    # ── Explicit cancellation ───────────────────────────────────

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific resting order.

        Returns True if the order was found and cancelled.  The
        cancellation ack is queued for the next ``poll_acks()`` call.
        """
        pending = self._resting_orders.get(order_id)
        if pending is None:
            # Acknowledged-but-unfilled MOC orders live in the
            # MocFillController queue, not ``_resting_orders``.  Halt
            # cleanup walks active orders and calls ``cancel_order``
            # on each, so MOC entries must be reachable here too.
            if self._moc is not None and self._moc.cancel_pending(
                order_id, "client_cancel",
            ):
                return True
            return False
        cancel_fees = self._cancel_fees(pending.request.quantity)
        cancel_ts = max(self._clock.now_ns(), pending.ack_timestamp_ns)
        self._pending_acks.append(OrderAck(
            timestamp_ns=cancel_ts,
            correlation_id=pending.request.correlation_id,
            sequence=self._ack_seq.next(),
            order_id=order_id,
            symbol=pending.request.symbol,
            status=OrderAckStatus.CANCELLED,
            reason="client_cancel",
            fees=cancel_fees if cancel_fees > 0 else Decimal("0"),
            request_sequence=pending.request.sequence,
        ))
        self._remove_resting(order_id)
        return True

    def _remove_resting(self, order_id: str) -> None:
        pending = self._resting_orders.pop(order_id, None)
        if pending is None:
            return
        symbol_orders = self._resting_by_symbol.get(pending.request.symbol)
        if symbol_orders is not None:
            symbol_orders.pop(order_id, None)
            if not symbol_orders:
                del self._resting_by_symbol[pending.request.symbol]

    # ── Diagnostics ──────────────────────────────────────────────

    def expire_pending_moc(
        self,
        reason: str = "MOC_NO_CLOSE_PRINT",
    ) -> int:
        """Reject any acknowledged MOC orders that never received a
        closing-auction print.  Called by the kernel at session /
        replay end so an MOC cannot remain non-terminal indefinitely
        when no qualifying post-close NBBO arrives in the feed.
        Returns the number of orders expired.
        """
        if self._moc is None:
            return 0
        return self._moc.expire_unfilled(reason, reject_fn=self._reject)

    @property
    def resting_order_count(self) -> int:
        """Number of currently resting limit orders."""
        return len(self._resting_orders)

    def resting_symbols(self) -> frozenset[str]:
        """Symbols with at least one resting limit order."""
        return frozenset(self._resting_by_symbol.keys())

    @property
    def requires_trade_feed(self) -> bool:
        """True when ``on_trade()`` must be wired for correct fills.

        When the queue-position mode is enabled (``queue_position_shares > 0``
        at construction, or any order has a non-zero per-order threshold),
        level fills only fire when accumulated trade volume reaches the
        threshold.  Without a trade feed subscription those orders never
        fill by queue drain and silently degrade — callers should wire
        ``on_trade`` when this is True.
        """
        return self._queue_position_shares > 0
