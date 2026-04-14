"""Per-alpha risk budget wrapper with drawdown enforcement.

Wraps the platform ``RiskEngine`` with per-alpha budget enforcement.
Enforces ``min(alpha_budget, platform_budget)`` for position limits
and exposure.  Enforces per-alpha drawdown via a high-water mark
tracker — breach triggers per-alpha quarantine (REJECT), not
platform lockdown (FORCE_FLATTEN).

The inner engine handles aggregate-level checks and may return
FORCE_FLATTEN for aggregate drawdown — the MultiAlphaEvaluator
distinguishes this from per-alpha REJECT and short-circuits the
evaluation loop.

Invariants preserved:
  - Inv 11 (fail-safe): per-alpha drawdown -> REJECT -> quarantine;
    aggregate drawdown -> FORCE_FLATTEN -> lockdown
  - Inv 12 (budget enforcement): min(alpha, platform) limits
"""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import (
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
)
from feelies.portfolio.position_store import PositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import RiskConfig
from feelies.risk.engine import RiskEngine


class AlphaBudgetRiskWrapper:
    """Wraps a RiskEngine with per-alpha budget enforcement."""

    def __init__(
        self,
        inner: RiskEngine,
        registry: AlphaRegistry,
        strategy_positions: StrategyPositionStore,
        platform_config: RiskConfig,
        account_equity: Decimal,
    ) -> None:
        self._inner = inner
        self._registry = registry
        self._strategy_positions = strategy_positions
        self._platform_config = platform_config
        self._account_equity = account_equity
        self._alpha_hwm: dict[str, Decimal] = {}

    def check_signal(
        self,
        signal: Signal,
        positions: PositionStore,
    ) -> RiskVerdict:
        try:
            alpha = self._registry.get(signal.strategy_id)
        except KeyError:
            return self._inner.check_signal(signal, positions)

        budget = alpha.manifest.risk_budget

        # 1. Per-alpha position limit
        effective_max = min(
            budget.max_position_per_symbol,
            self._platform_config.max_position_per_symbol,
        )
        strategy_pos = self._strategy_positions.get(
            signal.strategy_id, signal.symbol,
        )
        if abs(strategy_pos.quantity) >= effective_max:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(
                    f"per-alpha position limit: "
                    f"|{strategy_pos.quantity}| >= {effective_max}"
                ),
            )

        # 2. Per-alpha exposure limit
        alpha_equity, alpha_max_exposure, alpha_exposure = (
            self._alpha_equity_and_exposure(signal.strategy_id, budget)
        )
        if alpha_exposure >= alpha_max_exposure:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(
                    f"per-alpha exposure limit: "
                    f"{alpha_exposure} >= {alpha_max_exposure}"
                ),
            )

        # 3. Per-alpha drawdown check (realized-only, see §10.12)
        drawdown_verdict = self._check_alpha_drawdown(
            signal, budget, alpha_equity,
        )
        if drawdown_verdict is not None:
            return drawdown_verdict

        # 4. Delegate to inner engine for aggregate checks.
        # The inner engine may return FORCE_FLATTEN for aggregate
        # drawdown breach.  The MAE distinguishes this from per-alpha
        # REJECT and short-circuits the entire evaluation loop (§4.3).
        return self._inner.check_signal(signal, positions)

    def _check_alpha_drawdown(
        self,
        signal: Signal,
        budget: object,
        alpha_equity: Decimal,
    ) -> RiskVerdict | None:
        """Per-alpha drawdown via high-water mark (net of fees)."""
        strategy_id = signal.strategy_id

        realized_pnl = self._strategy_positions.get_strategy_realized_pnl(
            strategy_id,
        )
        fees = self._strategy_positions.get_strategy_cumulative_fees(
            strategy_id,
        )
        current_equity = alpha_equity + realized_pnl - fees

        hwm = self._alpha_hwm.get(strategy_id, alpha_equity)
        if current_equity > hwm:
            hwm = current_equity
            self._alpha_hwm[strategy_id] = hwm

        if hwm <= 0:
            return None
        drawdown_pct = float((hwm - current_equity) / hwm * 100)
        if drawdown_pct >= budget.max_drawdown_pct:  # type: ignore[union-attr]
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(
                    f"per-alpha drawdown {drawdown_pct:.2f}% >= "
                    f"limit {budget.max_drawdown_pct}% — "  # type: ignore[union-attr]
                    f"alpha should be quarantined"
                ),
            )
        return None

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
        strategy_id = order.strategy_id
        if strategy_id:
            try:
                alpha = self._registry.get(strategy_id)
            except KeyError:
                # Unregistered strategy_id (e.g. "multi_alpha_net",
                # "emergency_flatten", "__stop_exit__").  Per-alpha
                # budget checks are skipped — only aggregate-level
                # checks via the inner engine apply.  For multi-alpha
                # net orders this is by design: per-alpha budgets were
                # already enforced at signal time in the evaluator.
                pass
            else:
                budget = alpha.manifest.risk_budget

                # 1. Per-alpha position limit (post-fill)
                effective_max = min(
                    budget.max_position_per_symbol,
                    self._platform_config.max_position_per_symbol,
                )
                strategy_pos = self._strategy_positions.get(
                    strategy_id, order.symbol,
                )
                signed_qty = (
                    order.quantity if order.side == Side.BUY
                    else -order.quantity
                )
                post_fill = abs(strategy_pos.quantity + signed_qty)
                if post_fill > effective_max:
                    return RiskVerdict(
                        timestamp_ns=order.timestamp_ns,
                        correlation_id=order.correlation_id,
                        sequence=order.sequence,
                        symbol=order.symbol,
                        action=RiskAction.REJECT,
                        reason=(
                            f"per-alpha position limit at order gate: "
                            f"post-fill |{post_fill}| > {effective_max}"
                        ),
                    )

                # 2. Per-alpha exposure limit
                _, alpha_max_exposure, alpha_exposure = (
                    self._alpha_equity_and_exposure(strategy_id, budget)
                )
                if alpha_exposure >= alpha_max_exposure:
                    return RiskVerdict(
                        timestamp_ns=order.timestamp_ns,
                        correlation_id=order.correlation_id,
                        sequence=order.sequence,
                        symbol=order.symbol,
                        action=RiskAction.REJECT,
                        reason=(
                            f"per-alpha exposure limit at order gate: "
                            f"{alpha_exposure} >= {alpha_max_exposure}"
                        ),
                    )

        return self._inner.check_order(order, positions)

    def _alpha_equity_and_exposure(
        self,
        strategy_id: str,
        budget: object,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Compute (alpha_equity, alpha_max_exposure, alpha_exposure).

        Centralises the repeated budget arithmetic shared by check_signal,
        check_order, and _check_alpha_drawdown.
        """
        alpha_equity = self._account_equity * Decimal(
            str(budget.capital_allocation_pct),  # type: ignore[union-attr]
        ) / Decimal("100")
        alpha_max_exposure = alpha_equity * Decimal(
            str(budget.max_gross_exposure_pct),  # type: ignore[union-attr]
        ) / Decimal("100")
        alpha_exposure = self._strategy_positions.get_strategy_exposure(strategy_id)
        return alpha_equity, alpha_max_exposure, alpha_exposure

    # ── Persistence ──────────────────────────────────────────

    def checkpoint_risk_state(self) -> dict[str, str]:
        """Serialize per-alpha HWM state for persistence.

        Returns a dict of ``{strategy_id: hwm_as_string}`` suitable
        for JSON serialization.  Stored alongside lifecycle and feature
        snapshots so drawdown enforcement survives restarts.
        """
        return {
            sid: str(hwm) for sid, hwm in self._alpha_hwm.items()
        }

    def restore_risk_state(self, state: dict[str, str]) -> None:
        """Restore per-alpha HWM state from a checkpoint.

        Accepts the dict produced by ``checkpoint_risk_state()``.
        """
        self._alpha_hwm = {
            sid: Decimal(val) for sid, val in state.items()
        }
