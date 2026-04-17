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

from dataclasses import dataclass, field
from decimal import Decimal

from feelies.core.events import (
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
)
from feelies.portfolio.position_store import PositionStore
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

    def __init__(
        self,
        config: RiskConfig,
        regime_engine: RegimeEngine | None = None,
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
        self._regime_scale_default = min(self._regime_scale_map.values())

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
        In the single-alpha path these see the same position snapshot
        (no mutation between gates).  This partial redundancy is
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

        shared = self._check_exposure_and_drawdown(
            order.timestamp_ns, order.correlation_id, order.sequence, order.symbol,
            positions, scale_down_reason="approaching exposure limit at order gate",
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

    def _check_exposure_and_drawdown(
        self,
        timestamp_ns: int,
        correlation_id: str,
        sequence: int,
        symbol: str,
        positions: PositionStore,
        *,
        scale_down_reason: str,
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
        exposure = positions.total_exposure()
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

    def _is_drawdown_breached(self, current_equity: Decimal) -> bool:
        if current_equity > self._high_water_mark:
            self._high_water_mark = current_equity

        if self._high_water_mark <= 0:
            return True

        drawdown_pct = float(
            (self._high_water_mark - current_equity) / self._high_water_mark * 100
        )
        return drawdown_pct >= self._config.max_drawdown_pct
