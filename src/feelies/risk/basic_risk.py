"""Basic risk engine — first concrete RiskEngine implementation.

Enforces per-symbol position limits, gross portfolio exposure caps,
drawdown guard, and regime-aware gating.  When the platform-level
RegimeEngine is available, position *limits* are tightened in
high-volatility regimes.  Regime scaling of *quantity* is the
exclusive responsibility of the position sizer — the risk engine
never injects regime factors into ``scaling_factor`` to avoid
double-scaling through the orchestrator pipeline.

Invariants preserved:
  - Inv 11 (fail-safe): unknown states resolve to REJECT, never ALLOW.
  - Inv 12 (transaction cost realism): not enforced here — delegated
    to the position sizer / backtest fill model.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

_logger = logging.getLogger(__name__)

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Alert,
    AlertSeverity,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
    SizedPositionIntent,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.position_store import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult
from feelies.services.regime_engine import RegimeEngine


@dataclass(frozen=True, kw_only=True)
class RiskConfig:
    """Configuration for the basic risk engine."""

    max_position_per_symbol: int = 1000
    max_gross_exposure_pct: float = 20.0
    max_drawdown_pct: float = 5.0
    account_equity: Decimal = Decimal("1000000")

    regime_vol_breakout_scale: float = 0.5
    regime_compression_scale: float = 0.75
    regime_normal_scale: float = 1.0

    scale_down_threshold_pct: float = 0.8


class BasicRiskEngine:
    """Concrete risk engine with position limits and regime-aware gating.

    Satisfies the ``RiskEngine`` protocol.
    """

    # Single source of truth for the regime state names that
    # :meth:`__init__` knows how to map onto a ``RiskConfig`` scale field.
    # ``bootstrap._validate_regime_engine_risk_scale_alignment`` reads this
    # frozenset so adding/renaming a regime here propagates without a
    # parallel constant drifting out of sync.
    REGIME_SCALE_STATE_NAMES: frozenset[str] = frozenset({
        "vol_breakout",
        "compression_clustering",
        "normal",
    })

    def __init__(
        self,
        config: RiskConfig,
        regime_engine: RegimeEngine | None = None,
        *,
        bus: EventBus | None = None,
        alert_sequence_generator: SequenceGenerator | None = None,
    ) -> None:
        self._config = config
        self._regime_engine = regime_engine
        self._high_water_mark = config.account_equity
        self._realized_pnl = Decimal("0")
        self._regime_scale_map: dict[str, float] = {
            "vol_breakout": config.regime_vol_breakout_scale,
            "compression_clustering": config.regime_compression_scale,
            "normal": config.regime_normal_scale,
        }
        assert (
            self._regime_scale_map.keys()
            == BasicRiskEngine.REGIME_SCALE_STATE_NAMES
        ), (
            "REGIME_SCALE_STATE_NAMES drifted from _regime_scale_map keys"
        )
        self._regime_scale_default = min(self._regime_scale_map.values())
        # Optional diagnostic emission for the per-leg PORTFOLIO veto.
        # When ``bus`` is supplied an Alert is published listing the
        # dropped legs so dollar-neutrality / sector-neutrality breaches
        # are visible to operators (audit R4).  When omitted the
        # WARNING log line is the only signal — preserves construction
        # backwards-compatibility for existing test fixtures.
        self._bus = bus
        self._alert_seq = alert_sequence_generator

    def check_signal(
        self,
        signal: Signal,
        positions: PositionStore,
    ) -> RiskVerdict:
        """Gate 1 (signal-level): directional position-limit check.

        Complementary to ``check_order`` (gate 2).  This gate runs
        BEFORE the concrete order is sized, so it cannot compute
        post-fill quantity.  Instead it checks whether the current
        position is already at the limit and the signal would INCREASE
        exposure (``signal_reduces`` exception allows exits/reversals).

        The exposure and drawdown sub-checks via
        ``_check_exposure_and_drawdown`` are shared with gate 2.
        In the standalone SIGNAL walk these see the same position
        snapshot. Same-tick PORTFOLIO orders, when present, reconcile
        before gate 1 runs; no bus-driven position mutation occurs
        between gate 1 and gate 2. This partial redundancy is
        acceptable: gate 1 provides an early-exit before order
        construction, and removing either gate would lose the unique
        check that only that gate performs.
        """
        regime_scale = self._regime_scaling(signal.symbol)
        adjusted_max = int(self._config.max_position_per_symbol * regime_scale)

        current = positions.get(signal.symbol)
        signal_reduces = (
            (current.quantity > 0 and signal.direction in (SignalDirection.SHORT, SignalDirection.FLAT))
            or (current.quantity < 0 and signal.direction in (SignalDirection.LONG, SignalDirection.FLAT))
        )
        if abs(current.quantity) >= adjusted_max and not signal_reduces:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=f"position limit reached: |{current.quantity}| >= {adjusted_max}",
            )

        shared = self._check_exposure_and_drawdown(
            signal.timestamp_ns, signal.correlation_id, signal.sequence, signal.symbol,
            positions, scale_down_reason="approaching exposure limit",
        )
        if shared is not None:
            return shared

        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="within limits",
        )

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
        """Gate 2 (order-level): post-fill position quantity check.

        Complementary to ``check_signal`` (gate 1).  This gate runs
        AFTER the order has been sized (intent translation + scaling),
        so it can compute the exact ``post_fill_qty`` that would result
        from this order.  Gate 1 cannot do this because the concrete
        order does not exist yet at signal time.

        Removing this gate would lose the post-fill position limit
        validation — gate 1's directional check does not catch cases
        where the sized order would overshoot the limit (e.g. SCALE_UP
        by more than the remaining headroom).
        """
        regime_scale = self._regime_scaling(order.symbol)
        adjusted_max = int(self._config.max_position_per_symbol * regime_scale)

        current = positions.get(order.symbol)
        signed_qty = order.quantity if order.side == Side.BUY else -order.quantity
        post_fill_qty = abs(current.quantity + signed_qty)
        if post_fill_qty > adjusted_max:
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.REJECT,
                reason=(
                    f"post-fill position {post_fill_qty} would exceed "
                    f"regime-adjusted limit {adjusted_max}"
                ),
            )

        prospective_exposure = self._prospective_total_exposure(
            order, positions, current,
        )
        shared = self._check_exposure_and_drawdown(
            order.timestamp_ns, order.correlation_id, order.sequence, order.symbol,
            positions,
            scale_down_reason="approaching exposure limit at order gate",
            exposure_override=prospective_exposure,
        )
        if shared is not None:
            return shared

        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="order within limits",
        )

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        positions: PositionStore,
    ) -> SizedIntentRiskResult:
        """Translate a Phase-4 ``SizedPositionIntent`` to per-leg orders.

        Each non-zero ``TargetPosition`` delta vs the current position
        (in *shares*, derived from ``target_usd`` divided by the
        position store's last mark or, if no mark yet, the current
        ``avg_entry_price``) is converted into one
        :class:`OrderRequest`.

        Determinism (Inv-5)
        -------------------

        Iteration over ``intent.target_positions`` is **lexicographically
        sorted on symbol** so the emitted tuple is bit-identical across
        replays.  ``order_id`` is derived from a SHA-256 of
        ``(intent.correlation_id, intent.sequence, symbol)`` so two
        runs of the same intent always produce identical IDs.

        Per-leg veto (Inv-11)
        ---------------------

        When the per-symbol order would breach post-fill quantity or gross
        exposure limits, the offending leg is dropped and the rest of the
        intent proceeds.

        Drawdown breach (``RiskAction.FORCE_FLATTEN`` at ``check_order``)
        aborts **the entire intent**: ``orders`` is empty and
        ``requires_global_risk_escalation`` is true so the orchestrator
        runs the same emergency flatten + LOCKED path as standalone SIGNAL.

        Macro interaction (kernel audit)
        ----------------------------------
        A ``RiskAction.FORCE_FLATTEN`` verdict on a per-leg
        :meth:`check_order` call is **not** promoted to orchestrator
        global lockdown — the leg is veto-dropped like REJECT. Only the
        standalone-SIGNAL per-tick path can drive macro
        **RISK_LOCKDOWN** (see :mod:`feelies.kernel.macro`).

        Diagnostic (audit R4)
        ---------------------

        Ordinary veto drops are surfaced via ``_emit_dropped_legs_alert``.
        Global flatten intent does **not** emit the partial-execution
        alert — the orchestrator owns flatten + CRITICAL residual alerts.

        Symbols whose ``target_usd`` matches the current notional
        (within one cent) produce no order — the leg is a no-op and is
        NOT counted as a veto-dropped leg.
        """
        if not intent.target_positions:
            return SizedIntentRiskResult(orders=())

        orders: list[OrderRequest] = []
        dropped: list[tuple[str, str]] = []
        for symbol in sorted(intent.target_positions):
            tgt = intent.target_positions[symbol]
            current = positions.get(symbol)
            mark = self._mark_for(symbol, current, positions)
            if mark <= 0:
                continue

            target_shares = int(
                (Decimal(str(tgt.target_usd)) / mark).to_integral_value(
                    rounding=ROUND_HALF_UP,
                )
            )
            delta_shares = target_shares - current.quantity
            if delta_shares == 0:
                continue

            side = Side.BUY if delta_shares > 0 else Side.SELL
            quantity = abs(delta_shares)

            order_id = hashlib.sha256(
                f"{intent.correlation_id}:{intent.sequence}:{symbol}".encode()
            ).hexdigest()[:16]

            disclosed_cost = intent.disclosed_cost_total_bps_by_symbol.get(
                symbol, 0.0,
            )
            order = OrderRequest(
                timestamp_ns=intent.timestamp_ns,
                correlation_id=intent.correlation_id,
                sequence=intent.sequence,
                source_layer="PORTFOLIO",
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                strategy_id=intent.strategy_id,
                reason="PORTFOLIO",
                g12_disclosed_cost_total_bps=disclosed_cost,
            )

            verdict = self.check_order(order, positions)
            if verdict.action == RiskAction.FORCE_FLATTEN:
                return SizedIntentRiskResult(
                    orders=(),
                    requires_global_risk_escalation=True,
                )
            if verdict.action == RiskAction.REJECT:
                dropped.append((symbol, verdict.reason))
                continue
            if verdict.action == RiskAction.SCALE_DOWN:
                scaled_qty = max(1, int(quantity * verdict.scaling_factor))
                if scaled_qty == quantity:
                    pass
                else:
                    order = OrderRequest(
                        timestamp_ns=intent.timestamp_ns,
                        correlation_id=intent.correlation_id,
                        sequence=intent.sequence,
                        source_layer="PORTFOLIO",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=scaled_qty,
                        strategy_id=intent.strategy_id,
                        reason="PORTFOLIO",
                        g12_disclosed_cost_total_bps=disclosed_cost,
                    )

            orders.append(order)

        if dropped:
            self._emit_dropped_legs_alert(intent, dropped)

        return SizedIntentRiskResult(orders=tuple(orders))

    def _emit_dropped_legs_alert(
        self,
        intent: SizedPositionIntent,
        dropped: list[tuple[str, str]],
    ) -> None:
        """Surface per-leg PORTFOLIO veto drops to operators.

        Always logs at WARNING; additionally publishes a single
        ``Alert`` event when the engine was constructed with both a
        bus and a sequence generator.  The Alert lists every dropped
        symbol so a portfolio alpha that intended a dollar-neutral
        construction can be reconciled against what actually executed.
        """
        symbols_summary = ", ".join(sym for sym, _ in dropped)
        _logger.warning(
            "PORTFOLIO per-leg veto dropped %d/%d legs from intent "
            "(strategy_id=%s, correlation_id=%s): %s",
            len(dropped),
            len(intent.target_positions),
            intent.strategy_id,
            intent.correlation_id,
            symbols_summary,
        )
        if self._bus is None or self._alert_seq is None:
            return
        self._bus.publish(Alert(
            timestamp_ns=intent.timestamp_ns,
            correlation_id=intent.correlation_id,
            sequence=self._alert_seq.next(),
            source_layer="RISK",
            severity=AlertSeverity.WARNING,
            layer="risk",
            alert_name="portfolio_intent_partial_execution",
            message=(
                f"Per-leg PORTFOLIO veto dropped {len(dropped)} of "
                f"{len(intent.target_positions)} legs from intent "
                f"(strategy_id={intent.strategy_id!r}, "
                f"correlation_id={intent.correlation_id!r}). "
                f"Surviving legs execute as a partial portfolio; "
                f"any dollar-neutral / sector-neutral / "
                f"mechanism-cap invariant the alpha intended is "
                f"NOT re-validated after the drop."
            ),
            context={
                "strategy_id": intent.strategy_id,
                "intent_correlation_id": intent.correlation_id,
                "intent_sequence": intent.sequence,
                "total_legs": len(intent.target_positions),
                "dropped_legs": [
                    {"symbol": sym, "reason": reason}
                    for sym, reason in dropped
                ],
            },
        ))

    def _prospective_total_exposure(
        self,
        order: OrderRequest,
        positions: PositionStore,
        current: object,
    ) -> Decimal:
        """Gross exposure after hypothetically applying ``order``.

        Gate 2 must account for the candidate order's own notional, not
        just the snapshot passed in.  This matters especially for reverse
        entries, where the orchestrator supplies a post-exit view and the
        new entry leg must still count against the gross cap.
        """
        exposure = positions.total_exposure()
        mark = self._mark_for(order.symbol, current, positions)
        if mark <= 0 and order.limit_price is not None and order.limit_price > 0:
            mark = order.limit_price
        if mark <= 0:
            return exposure

        current_qty_obj = getattr(current, "quantity", 0)
        current_qty = current_qty_obj if isinstance(current_qty_obj, int) else 0
        signed_qty = order.quantity if order.side == Side.BUY else -order.quantity
        current_contrib = abs(current_qty) * mark
        post_fill_contrib = abs(current_qty + signed_qty) * mark
        return exposure - current_contrib + post_fill_contrib

    @staticmethod
    def _mark_for(
        symbol: str,
        current: object,
        positions: PositionStore,
    ) -> Decimal:
        """Return the best-available mark price for translating USD → shares.

        Prefers the latest live mark when recorded; otherwise falls back
        to ``avg_entry_price`` for the boot-time case before any quote has
        flowed through.  Returns ``0`` when the position has never been
        marked AND has zero average entry — the caller must treat zero as
        "skip this leg" (Inv-11 fail-safe).
        """
        # Try to read a live mark via the optional accessor introduced
        # in Phase 4-finalize; for already-open positions this must take
        # priority over cost basis so USD targets track current notional.
        latest = getattr(positions, "latest_mark", None)
        if callable(latest):
            try:
                m = latest(symbol)
                if isinstance(m, Decimal) and m > 0:
                    return m
            except Exception as exc:  # pragma: no cover - defensive
                # Inv-11 fail-safe: fall back to cost basis rather than
                # raising into the risk path.  But the swallow itself is
                # a degraded mode (live-mark feed bug) — surface it via
                # WARNING so the operator can see the slippage drift in
                # promotion-window forensics.
                _logger.warning(
                    "_mark_for(%s): latest_mark accessor raised %s; "
                    "falling back to avg_entry_price",
                    symbol, exc,
                )
        avg = getattr(current, "avg_entry_price", Decimal("0"))
        if isinstance(avg, Decimal) and avg > 0:
            return avg
        return Decimal("0")

    def _check_exposure_and_drawdown(
        self,
        timestamp_ns: int,
        correlation_id: str,
        sequence: int,
        symbol: str,
        positions: PositionStore,
        *,
        scale_down_reason: str,
        exposure_override: Decimal | None = None,
    ) -> RiskVerdict | None:
        """Check exposure cap, drawdown guard, and scale-down threshold.

        Returns a verdict (REJECT, FORCE_FLATTEN, or SCALE_DOWN) if any
        shared limit is breached, or None if all checks pass.

        ``max_exposure`` compounds against the live NAV (initial equity
        + realized − fees + unrealized).  Static initial capital would
        let the book silently over- or under-lever as PnL moves.  The
        HWM tracked inside ``_is_drawdown_breached`` uses the same
        definition so the two checks stay internally consistent.
        """
        current_equity = self._compute_current_equity(positions)
        exposure = (
            positions.total_exposure()
            if exposure_override is None else exposure_override
        )
        equity_for_cap = current_equity if current_equity > 0 else self._config.account_equity
        max_exposure = equity_for_cap * Decimal(
            str(self._config.max_gross_exposure_pct)
        ) / Decimal("100")
        if exposure >= max_exposure:
            return RiskVerdict(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=sequence,
                symbol=symbol,
                action=RiskAction.REJECT,
                reason=f"gross exposure limit: {exposure} >= {max_exposure}",
            )

        # Bump the HWM as a separate, explicit step so the predicate
        # below is a pure function of (current_equity, hwm) — see
        # _is_drawdown_breached docstring for the rationale.
        self._update_high_water_mark(current_equity)
        if self._is_drawdown_breached(current_equity):
            return RiskVerdict(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=sequence,
                symbol=symbol,
                action=RiskAction.FORCE_FLATTEN,
                reason="drawdown limit breached",
            )

        threshold = Decimal(str(self._config.scale_down_threshold_pct))
        if threshold >= Decimal("1"):
            return RiskVerdict(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=sequence,
                symbol=symbol,
                action=RiskAction.REJECT,
                reason="scale_down_threshold_pct >= 1.0 is invalid (would divide by zero)",
            )
        if exposure >= max_exposure * threshold:
            scaling = float(
                (max_exposure - exposure) / (max_exposure * (1 - threshold))
            )
            scaling = max(0.1, min(1.0, scaling))
            return RiskVerdict(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=sequence,
                symbol=symbol,
                action=RiskAction.SCALE_DOWN,
                reason=scale_down_reason,
                scaling_factor=scaling,
            )

        return None

    def _regime_scaling(self, symbol: str) -> float:
        """Expected value over posterior distribution: sum(p_i * scale_i).

        Uses EV rather than dominant-state (argmax) point estimates
        to avoid discontinuous limit jumps at regime transitions.
        With noisy HMM posteriors, argmax can oscillate rapidly
        between states, causing position limits to thrash.  EV
        smooths this at the cost of weaker response to regime
        extremes: full vol_breakout scaling (0.5×) requires 100%
        posterior certainty, which real HMMs rarely produce.

        This is acceptable because the risk engine's regime scaling
        is a secondary limit tightening, not the primary sizing
        mechanism.  The position sizer independently scales quantity
        by regime, providing the primary response.  The risk engine
        only applies regime factors to hard position *limits*, never
        to ``scaling_factor``, preventing double-scaling (see module
        docstring).  The two operate in series (sizer proposes, risk
        caps), not in parallel.

        Unknown state names default to min(all scales) (fail-safe).
        """
        if self._regime_engine is None:
            return 1.0

        posteriors = self._regime_engine.current_state(symbol)
        if posteriors is None:
            return 1.0

        state_names = list(self._regime_engine.state_names)
        default = self._regime_scale_default
        return sum(
            posteriors[i] * self._regime_scale_map.get(state_names[i], default)
            for i in range(len(posteriors))
        )

    def _compute_current_equity(self, positions: PositionStore) -> Decimal:
        """Live NAV: initial equity + realized − fees + unrealized.

        Including ``unrealized_pnl`` lets the drawdown guard fire while
        losses are still on-book — waiting for them to realize defeats
        the purpose of a stop.  Per-symbol ``unrealized_pnl`` is kept
        current by the position store's mark feed.
        """
        total_realized = Decimal("0")
        total_fees = Decimal("0")
        total_unrealized = Decimal("0")
        for pos in positions.all_positions().values():
            total_realized += pos.realized_pnl
            total_fees += pos.cumulative_fees
            total_unrealized += pos.unrealized_pnl
        return (
            self._config.account_equity
            + total_realized
            - total_fees
            + total_unrealized
        )

    def _update_high_water_mark(self, current_equity: Decimal) -> None:
        """Bump the HWM monotonically.

        Split out from ``_is_drawdown_breached`` so that a "what-if"
        caller (e.g. a speculative intent translator that probes
        ``check_order`` without intending to submit) cannot silently
        ratchet the HWM as a side effect of asking a boolean question.
        Callers that must update the HWM call this *before* querying
        ``_is_drawdown_breached`` (see ``_check_exposure_and_drawdown``).
        """
        if current_equity > self._high_water_mark:
            self._high_water_mark = current_equity

    def _is_drawdown_breached(self, current_equity: Decimal) -> bool:
        """Pure predicate over (current_equity, self._high_water_mark).

        Does NOT mutate the HWM.  Call ``_update_high_water_mark`` first
        if the caller represents a real (non-speculative) check.
        """
        if self._high_water_mark <= 0:
            return True

        drawdown_pct = float(
            (self._high_water_mark - current_equity) / self._high_water_mark * 100
        )
        return drawdown_pct >= self._config.max_drawdown_pct
