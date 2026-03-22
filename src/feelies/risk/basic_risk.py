"""Basic risk engine — first concrete RiskEngine implementation.

Enforces per-symbol position limits, gross portfolio exposure caps,
drawdown guard, and regime-aware gating.  When the platform-level
RegimeEngine is available, limits are tightened in high-volatility
regimes and loosened (to baseline) in normal regimes.

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

    def check_signal(
        self,
        signal: Signal,
        positions: PositionStore,
    ) -> RiskVerdict:
        regime_scale = self._regime_scaling(signal.symbol)
        adjusted_max = int(self._config.max_position_per_symbol * regime_scale)

        current = positions.get(signal.symbol)
        if abs(current.quantity) >= adjusted_max:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=f"position limit reached: |{current.quantity}| >= {adjusted_max}",
            )

        exposure = positions.total_exposure()
        max_exposure = self._config.account_equity * Decimal(
            str(self._config.max_gross_exposure_pct)
        ) / Decimal("100")
        if exposure >= max_exposure:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=f"gross exposure limit: {exposure} >= {max_exposure}",
            )

        if self._is_drawdown_breached(positions):
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.FORCE_FLATTEN,
                reason="drawdown limit breached",
            )

        threshold = Decimal(str(self._config.scale_down_threshold_pct))
        if exposure >= max_exposure * threshold:
            scaling = float(
                (max_exposure - exposure) / (max_exposure * (1 - threshold))
            )
            scaling = max(0.1, min(1.0, scaling))
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.SCALE_DOWN,
                reason="approaching exposure limit",
                scaling_factor=scaling * regime_scale,
            )

        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="within limits",
            scaling_factor=regime_scale,
        )

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
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

        exposure = positions.total_exposure()
        max_exposure = self._config.account_equity * Decimal(
            str(self._config.max_gross_exposure_pct)
        ) / Decimal("100")
        if exposure >= max_exposure:
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.REJECT,
                reason=f"gross exposure limit: {exposure} >= {max_exposure}",
            )

        if self._is_drawdown_breached(positions):
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.FORCE_FLATTEN,
                reason="drawdown limit breached",
            )

        threshold = Decimal(str(self._config.scale_down_threshold_pct))
        if exposure >= max_exposure * threshold:
            scaling = float(
                (max_exposure - exposure) / (max_exposure * (1 - threshold))
            )
            scaling = max(0.1, min(1.0, scaling))
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.SCALE_DOWN,
                reason="approaching exposure limit at order gate",
                scaling_factor=scaling * regime_scale,
            )

        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="order within limits",
        )

    def _regime_scaling(self, symbol: str) -> float:
        """Determine position scaling based on current regime state."""
        if self._regime_engine is None:
            return 1.0

        posteriors = self._regime_engine.current_state(symbol)
        if posteriors is None:
            return 1.0

        state_names = list(self._regime_engine.state_names)
        dominant_idx = max(range(len(posteriors)), key=lambda i: posteriors[i])
        dominant_name = state_names[dominant_idx] if dominant_idx < len(state_names) else ""

        if dominant_name == "vol_breakout":
            return self._config.regime_vol_breakout_scale
        if dominant_name == "compression_clustering":
            return self._config.regime_compression_scale
        return self._config.regime_normal_scale

    def _is_drawdown_breached(self, positions: PositionStore) -> bool:
        total_realized = Decimal("0")
        for pos in positions.all_positions().values():
            total_realized += pos.realized_pnl

        current_equity = self._config.account_equity + total_realized
        if current_equity > self._high_water_mark:
            self._high_water_mark = current_equity

        if self._high_water_mark <= 0:
            return True

        drawdown_pct = float(
            (self._high_water_mark - current_equity) / self._high_water_mark * 100
        )
        return drawdown_pct >= self._config.max_drawdown_pct
