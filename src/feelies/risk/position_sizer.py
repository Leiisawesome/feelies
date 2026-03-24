"""Position sizer — compute target quantity from risk budget and regime.

Replaces the hardcoded ``base_quantity = 100`` in the old orchestrator.
The sizer is called by the IntentTranslator to determine how many
shares to target for a given signal, considering the alpha's declared
risk budget, account equity, current price, and regime state.

Invariants preserved:
  - Inv 5 (deterministic): same inputs → same target quantity
  - Inv 11 (fail-safe): regime scaling only reduces, never increases
    beyond the 1.0 baseline
  - Inv 12 (transaction cost realism): the sizer caps quantity so
    that the alpha never exceeds its declared budget
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import Signal
from feelies.services.regime_engine import RegimeEngine


class PositionSizer(Protocol):
    """Compute target position size for a signal."""

    def compute_target_quantity(
        self,
        signal: Signal,
        risk_budget: AlphaRiskBudget,
        symbol_price: Decimal,
        account_equity: Decimal,
    ) -> int:
        """Return unsigned target share count.

        The caller is responsible for determining direction (BUY/SELL)
        from the signal direction and current position via the
        IntentTranslator.
        """
        ...


class BudgetBasedSizer:
    """Default position sizer using alpha risk budget and regime scaling.

    Sizing formula:
      1. allocated_capital = account_equity * capital_allocation_pct / 100
      2. conviction_capital = allocated_capital * signal.strength
      3. regime_factor = EV over posterior: sum(p_i * scale_i)
      4. target_value = conviction_capital * regime_factor
      5. target_shares = floor(target_value / symbol_price)
      6. capped = min(target_shares, max_position_per_symbol)

    Regime scaling factors (configurable):
      - vol_breakout           -> 0.5x  (halve in high-vol)
      - compression_clustering -> 0.75x (reduced edge)
      - normal                 -> 1.0x

    Unknown state names default to min(all factors) (fail-safe).
    """

    _DEFAULT_REGIME_FACTORS: dict[str, float] = {
        "vol_breakout": 0.5,
        "compression_clustering": 0.75,
        "normal": 1.0,
    }

    def __init__(
        self,
        regime_engine: RegimeEngine | None = None,
        regime_factors: dict[str, float] | None = None,
    ) -> None:
        self._regime_engine = regime_engine
        self._regime_factors = regime_factors or dict(self._DEFAULT_REGIME_FACTORS)
        self._regime_factor_default = min(self._regime_factors.values()) if self._regime_factors else 1.0

    def compute_target_quantity(
        self,
        signal: Signal,
        risk_budget: AlphaRiskBudget,
        symbol_price: Decimal,
        account_equity: Decimal,
    ) -> int:
        if symbol_price <= 0 or account_equity <= 0:
            return 0

        allocated = account_equity * Decimal(str(risk_budget.capital_allocation_pct)) / Decimal("100")

        strength = max(0.0, min(1.0, signal.strength))
        conviction_capital = allocated * Decimal(str(strength))

        regime_factor = self._get_regime_factor(signal.symbol)
        sized_capital = conviction_capital * Decimal(str(regime_factor))

        target_shares = int(sized_capital / symbol_price)
        capped = min(target_shares, risk_budget.max_position_per_symbol)

        return max(0, capped)

    def _get_regime_factor(self, symbol: str) -> float:
        if self._regime_engine is None:
            return 1.0

        posteriors = self._regime_engine.current_state(symbol)
        if not posteriors:
            return 1.0

        state_names = list(self._regime_engine.state_names)
        default = self._regime_factor_default
        return sum(
            posteriors[i] * self._regime_factors.get(state_names[i], default)
            for i in range(len(posteriors))
        )
