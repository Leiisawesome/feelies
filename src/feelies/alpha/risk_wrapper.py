"""Per-alpha risk budget wrapper with drawdown enforcement.

Wraps the platform ``RiskEngine`` with per-alpha budget enforcement.
Enforces ``min(alpha_budget, platform_budget)`` for position limits
and exposure.  Enforces per-alpha drawdown via a high-water mark
tracker — breach triggers per-alpha quarantine (REJECT), not
platform lockdown (FORCE_FLATTEN).

The inner engine handles aggregate-level checks and may return
FORCE_FLATTEN for aggregate drawdown.  On the PORTFOLIO path,
``check_sized_intent`` surfaces that verdict as
``requires_global_risk_escalation`` so the orchestrator runs the same
emergency flatten + macro lockdown as standalone SIGNAL breaches.

Invariants preserved:
  - Inv 11 (fail-safe): per-alpha drawdown -> REJECT -> quarantine;
    aggregate drawdown -> FORCE_FLATTEN -> lockdown
  - Inv 12 (budget enforcement): min(alpha, platform) limits
"""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.module import AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import (
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
    SizedPositionIntent,
)
from feelies.portfolio.position_store import PositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import RiskConfig
from feelies.risk.buying_power import BuyingPowerPhase
from feelies.risk.engine import RiskEngine
from feelies.risk.sized_intent_orders import build_sized_intent_orders
from feelies.risk.sized_intent_result import SizedIntentRiskResult


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

        # 1. Per-alpha position limit.
        # Signals that reduce the position (exits, reversals, FLATs from
        # a non-zero book) must never be rejected by a position-limit
        # check — otherwise an alpha at its cap becomes trapped and
        # cannot unwind.  Mirrors BasicRiskEngine.check_signal.
        effective_max = min(
            budget.max_position_per_symbol,
            self._platform_config.max_position_per_symbol,
        )
        strategy_pos = self._strategy_positions.get(
            signal.strategy_id,
            signal.symbol,
        )
        signal_reduces = _signal_reduces_position(
            strategy_pos.quantity,
            signal.direction,
        )
        if abs(strategy_pos.quantity) >= effective_max and not signal_reduces:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(f"per-alpha position limit: |{strategy_pos.quantity}| >= {effective_max}"),
            )

        # 2. Per-alpha exposure limit.  Exempt reducing signals for the
        # same reason as the position-limit gate.
        alpha_equity, alpha_max_exposure, alpha_exposure = self._alpha_equity_and_exposure(
            signal.strategy_id, budget
        )
        if alpha_exposure >= alpha_max_exposure and not signal_reduces:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(f"per-alpha exposure limit: {alpha_exposure} >= {alpha_max_exposure}"),
            )

        # 3. Per-alpha drawdown check (realized-only, see §10.12)
        drawdown_verdict = self._check_alpha_drawdown(
            signal,
            budget,
            alpha_equity,
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
        budget: AlphaRiskBudget,
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
        unrealized_pnl = self._strategy_positions.get_strategy_unrealized_pnl(
            strategy_id,
        )
        # Include unrealized so open losses count against the alpha's
        # HWM before they realize — otherwise an alpha can hold a loss
        # indefinitely without tripping its drawdown budget.
        current_equity = alpha_equity + realized_pnl - fees + unrealized_pnl

        hwm = self._alpha_hwm.get(strategy_id, alpha_equity)
        if current_equity > hwm:
            hwm = current_equity
            self._alpha_hwm[strategy_id] = hwm

        if hwm <= 0:
            return None
        drawdown_pct = float((hwm - current_equity) / hwm * 100)
        if drawdown_pct >= budget.max_drawdown_pct:
            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.REJECT,
                reason=(
                    f"per-alpha drawdown {drawdown_pct:.2f}% >= "
                    f"limit {budget.max_drawdown_pct}% — "
                    f"alpha should be quarantined"
                ),
            )
        return None

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
        *,
        additional_exposure: Decimal = Decimal("0"),
    ) -> RiskVerdict:
        strategy_id = order.strategy_id
        if strategy_id:
            try:
                alpha = self._registry.get(strategy_id)
            except KeyError:
                # Synthetic and net strategies use aggregate risk checks only.
                pass
            else:
                budget = alpha.manifest.risk_budget

                # 1. Per-alpha position limit (post-fill)
                effective_max = min(
                    budget.max_position_per_symbol,
                    self._platform_config.max_position_per_symbol,
                )
                strategy_pos = self._strategy_positions.get(
                    strategy_id,
                    order.symbol,
                )
                signed_qty = order.quantity if order.side == Side.BUY else -order.quantity
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

                # Exposure limits never block orders that reduce absolute position.
                order_reduces = post_fill < abs(strategy_pos.quantity)
                _, alpha_max_exposure, alpha_exposure = self._alpha_equity_and_exposure(
                    strategy_id, budget
                )
                if alpha_exposure >= alpha_max_exposure and not order_reduces:
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

        # Include prior legs when enforcing gross and buying-power caps.
        return self._inner.check_order(order, positions, additional_exposure=additional_exposure)

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        positions: PositionStore,
    ) -> SizedIntentRiskResult:
        """Translate a PORTFOLIO ``SizedPositionIntent`` to per-leg orders.

        Mirrors :meth:`BasicRiskEngine.check_sized_intent` (sort by
        symbol → mark-driven shares → SHA-256 order_id) but routes
        each per-leg ``check_order`` through ``self`` so the per-alpha
        budget gates run against the wrapper's
        :class:`StrategyPositionStore`.  Without this override, the
        inner engine's ``check_sized_intent`` would call
        ``self._inner.check_order`` directly and skip per-alpha enforcement.

        Inv-5: lexicographic symbol order keeps the emitted tuple
        bit-identical across replays.  Inv-11: per-leg veto drops only
        the offending leg for ordinary rejects; aggregate
        ``FORCE_FLATTEN`` aborts the intent and requests global
        orchestrator escalation. The inner engine emits ordinary veto-drop
        diagnostics through ``_emit_dropped_legs_alert``.
        """
        emit_alert = getattr(self._inner, "_emit_dropped_legs_alert", None)
        return build_sized_intent_orders(
            intent,
            positions,
            check_order=self.check_order,
            on_dropped_legs=emit_alert if callable(emit_alert) else None,
        )

    def _alpha_equity_and_exposure(
        self,
        strategy_id: str,
        budget: AlphaRiskBudget,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Compute (alpha_equity, alpha_max_exposure, alpha_exposure).

        Centralises the repeated budget arithmetic shared by check_signal,
        check_order, and _check_alpha_drawdown.
        """
        alpha_equity = (
            self._account_equity
            * Decimal(
                str(budget.capital_allocation_pct),
            )
            / Decimal("100")
        )
        alpha_max_exposure = (
            alpha_equity
            * Decimal(
                str(budget.max_gross_exposure_pct),
            )
            / Decimal("100")
        )
        alpha_exposure = self._strategy_positions.get_strategy_exposure(strategy_id)
        return alpha_equity, alpha_max_exposure, alpha_exposure

    # ── Persistence ──────────────────────────────────────────

    def checkpoint_risk_state(self) -> dict[str, str]:
        """Serialize per-alpha HWM state for persistence.

        Returns a dict of ``{strategy_id: hwm_as_string}`` suitable
        for JSON serialization.  Stored alongside lifecycle and feature
        snapshots so drawdown enforcement survives restarts.
        """
        return {sid: str(hwm) for sid, hwm in self._alpha_hwm.items()}

    def restore_risk_state(self, state: dict[str, str]) -> None:
        """Restore per-alpha HWM state from a checkpoint.

        Accepts the dict produced by ``checkpoint_risk_state()``.
        """
        self._alpha_hwm = {sid: Decimal(val) for sid, val in state.items()}

    def refresh_high_water_mark(self, positions: PositionStore) -> None:
        """Delegate mark-driven HWM refresh to the inner engine.

        The orchestrator calls this on every mark update so the
        platform-level HWM advances continuously, not just at order
        gates.  Per-alpha HWM tracking lives in this wrapper
        (``_alpha_hwm``) and is bumped only at order time because the
        wrapper does not see mid-tick mark updates; that remains a known
        limitation and is documented in :meth:`_check_alpha_drawdown`.

        Capability is optional on the inner ``RiskEngine`` — if it does
        not implement a callable hook (e.g. a test stub), the call is
        silently skipped.
        """
        refresh = getattr(self._inner, "refresh_high_water_mark", None)
        if callable(refresh):
            refresh(positions)

    def record_fill(
        self,
        symbol: str,
        prev_qty: int,
        new_qty: int,
        timestamp_ns: int,
    ) -> None:
        """Delegate PDT round-trip bookkeeping to the inner engine.

        The orchestrator calls this after each applied fill; the inner
        ``BasicRiskEngine`` owns the ``PDTConstraint``.
        """
        record = getattr(self._inner, "record_fill", None)
        if callable(record):
            record(symbol, prev_qty, new_qty, timestamp_ns)

    def set_buying_power_phase(self, phase: BuyingPowerPhase) -> None:
        """Delegate intraday/overnight buying-power flip to the inner engine.

        The orchestrator calls this on the engine it holds
        (which is *this* wrapper when per-alpha budgets are enforced)
        when exchange time crosses the RTH close.  Without this
        forwarder, ``getattr(self._risk_engine, "set_buying_power_phase",
        None)`` would return ``None`` on the wrapper and the inner
        ``BasicRiskEngine`` would stay on the 4× intraday cap past the
        close.
        """
        set_phase = getattr(self._inner, "set_buying_power_phase", None)
        if callable(set_phase):
            set_phase(phase)


def _signal_reduces_position(
    current_qty: int,
    direction: SignalDirection,
) -> bool:
    """Return True if a signal would close or offset an open position.

    A FLAT signal against any non-zero position is a pure exit.  A
    SHORT against a long (or LONG against a short) unwinds at least
    partially before any new exposure is added.  Both are always
    permissible regardless of position / exposure caps.
    """
    if current_qty == 0:
        return False
    if direction == SignalDirection.FLAT:
        return True
    if current_qty > 0 and direction == SignalDirection.SHORT:
        return True
    if current_qty < 0 and direction == SignalDirection.LONG:
        return True
    return False
