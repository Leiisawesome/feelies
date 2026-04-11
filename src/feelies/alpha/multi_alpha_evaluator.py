"""MultiAlphaEvaluator — replaces CompositeSignalEngine for multi-alpha mode.

Collects ALL intents from ALL active alphas per tick (no arbitration).
Aggregation to net orders happens downstream in the orchestrator via
``aggregate_intents()``.

Gates carried over from CompositeSignalEngine:
  - Warm gate, stale gate, symbol scope, entry cooldown, error handling
New gates:
  - Suppressed features gate (v2.1)
  - FORCE_FLATTEN short-circuit (v2.3)
  - Cooldown consumed on success only (v2.3)

Invariants preserved:
  - Inv 5 (deterministic): same inputs -> same IntentSet
  - Inv 8 (layer separation): no kernel or execution layer knowledge
  - Inv 11 (fail-safe): FORCE_FLATTEN propagation, per-alpha error isolation
"""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING

from feelies.alpha.intent_set import IntentSet
from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import (
    FeatureVector,
    NBBOQuote,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
)
from feelies.execution.intent import IntentTranslator, OrderIntent, TradingIntent
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.position_sizer import PositionSizer

if TYPE_CHECKING:
    from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper

logger = logging.getLogger(__name__)


class MultiAlphaEvaluator:
    """Replaces CompositeSignalEngine for orchestrator consumption
    in multi-alpha mode.

    Owns:
      - Per-alpha feature scoping (quote + trade paths)
      - Per-alpha signal evaluation (calls alpha.evaluate() directly)
      - Per-alpha intent translation (via IntentTranslator)
      - Per-alpha risk checking (via AlphaBudgetRiskWrapper)
      - Warm/stale/cooldown/error gates (carried over from CSE)
      - FORCE_FLATTEN propagation (v2.3)
    Does NOT own:
      - Feature computation (CompositeFeatureEngine)
      - Order aggregation, submission, or fill handling (Orchestrator)
      - Safety cascade (_escalate_risk — Orchestrator's responsibility)
    """

    def __init__(
        self,
        registry: AlphaRegistry,
        intent_translator: IntentTranslator,
        risk_wrapper: "AlphaBudgetRiskWrapper",
        strategy_positions: StrategyPositionStore,
        position_sizer: PositionSizer,
        account_equity: Decimal,
        entry_cooldown_ticks: int = 0,
    ) -> None:
        self._registry = registry
        self._intent_translator = intent_translator
        self._risk_wrapper = risk_wrapper
        self._strategy_positions = strategy_positions
        self._position_sizer = position_sizer
        self._account_equity = account_equity
        self._entry_cooldown_ticks = entry_cooldown_ticks
        self._last_entry_tick: dict[tuple[str, str], int] = {}
        self._tick_counter: dict[str, int] = {}

    def evaluate_tick(
        self,
        features: FeatureVector,
        quote: NBBOQuote,
    ) -> IntentSet:
        symbol = features.symbol
        symbol_tick = self._tick_counter.get(symbol, 0) + 1
        self._tick_counter[symbol] = symbol_tick

        empty = IntentSet(
            timestamp_ns=features.timestamp_ns,
            correlation_id=features.correlation_id,
            symbol=symbol,
            intents=(),
            signals=(),
            verdicts={},
        )

        # ── Warm gate (from CSE) ──────────────────────────
        if not features.warm:
            return empty

        collected_intents: list[OrderIntent] = []
        collected_signals: list[Signal] = []
        collected_verdicts: dict[str, RiskVerdict] = {}

        for alpha in self._registry.active_alphas():
            manifest = alpha.manifest

            # ── Symbol scope gate (from CSE) ──────────────
            if manifest.symbols is not None and symbol not in manifest.symbols:
                continue

            # ── Per-alpha feature scoping (includes suppressed intersection) ──
            scoped = self._scoped_features(features, alpha)

            # ── Per-alpha suppressed features gate (v2.3) ──
            # Only block this alpha if *its own* required features
            # are suppressed — not unrelated features from other alphas.
            if scoped.suppressed_features:
                continue

            # ── Per-alpha signal evaluation with error handling ──
            try:
                signal = alpha.evaluate(scoped)
            except Exception:
                logger.exception(
                    "Alpha '%s' raised during evaluate() for %s — skipping",
                    manifest.alpha_id,
                    symbol,
                )
                continue

            if signal is None:
                continue

            # ── Stale gate (from CSE): suppress entries, allow exits ──
            if features.stale and signal.direction != SignalDirection.FLAT:
                continue

            # ── Entry cooldown CHECK (from CSE) ───────────
            # Only check — do NOT consume the timer yet.
            # Timer consumed after all gates pass (v2.3).
            cooldown_applies = (
                signal.direction != SignalDirection.FLAT
                and self._entry_cooldown_ticks > 0
            )
            if cooldown_applies:
                key = (signal.symbol, signal.strategy_id)
                last = self._last_entry_tick.get(
                    key, -self._entry_cooldown_ticks,
                )
                if (symbol_tick - last) < self._entry_cooldown_ticks:
                    continue

            collected_signals.append(signal)

            # ── Position sizing ───────────────────────────
            target_qty = self._compute_target_quantity(
                signal, quote, manifest,
            )

            # ── Intent translation against alpha's own position ──
            alpha_position = self._strategy_positions.get(
                manifest.alpha_id, signal.symbol,
            )
            intent = self._intent_translator.translate(
                signal, alpha_position, target_qty,
            )

            if intent.intent == TradingIntent.NO_ACTION:
                continue

            # ── Per-alpha risk check ──────────────────────
            verdict = self._risk_wrapper.check_signal(
                signal,
                self._strategy_positions.as_aggregate(),
            )
            collected_verdicts[manifest.alpha_id] = verdict

            # ── FORCE_FLATTEN: short-circuit entire loop (v2.3) ──
            if verdict.action == RiskAction.FORCE_FLATTEN:
                return IntentSet(
                    timestamp_ns=features.timestamp_ns,
                    correlation_id=features.correlation_id,
                    symbol=symbol,
                    intents=(),
                    signals=tuple(collected_signals),
                    verdicts=collected_verdicts,
                    force_flatten=True,
                    force_flatten_verdict=verdict,
                )

            # ── Per-alpha REJECT: quarantine on drawdown breach, then skip ──
            if verdict.action == RiskAction.REJECT:
                if "drawdown" in verdict.reason.lower():
                    try:
                        self._registry.quarantine(
                            manifest.alpha_id, verdict.reason,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to quarantine alpha '%s' after "
                            "drawdown breach — lifecycle tracking may "
                            "be disabled",
                            manifest.alpha_id,
                        )
                continue

            if verdict.action == RiskAction.SCALE_DOWN:
                scaled_qty = round(
                    intent.target_quantity * verdict.scaling_factor,
                )
                if scaled_qty <= 0:
                    logger.warning(
                        "multi_alpha: alpha '%s' intent for %s scaled to zero "
                        "(target_qty=%d, scaling_factor=%.4f) — intent dropped",
                        manifest.alpha_id,
                        signal.symbol,
                        intent.target_quantity,
                        verdict.scaling_factor,
                    )
                    continue
                intent = replace(intent, target_quantity=scaled_qty)

            # ── All gates passed — consume cooldown timer (v2.3) ──
            if cooldown_applies:
                self._last_entry_tick[
                    (signal.symbol, signal.strategy_id)
                ] = symbol_tick

            collected_intents.append(intent)

        return IntentSet(
            timestamp_ns=features.timestamp_ns,
            correlation_id=features.correlation_id,
            symbol=symbol,
            intents=tuple(collected_intents),
            signals=tuple(collected_signals),
            verdicts=collected_verdicts,
        )

    def _scoped_features(
        self,
        features: FeatureVector,
        alpha: object,
    ) -> FeatureVector:
        """Filter feature values and suppressed set to this alpha's scope."""
        manifest = alpha.manifest  # type: ignore[union-attr]
        allowed = manifest.required_features
        scoped_values = {
            k: v for k, v in features.values.items() if k in allowed
        }
        scoped_suppressed = features.suppressed_features & allowed
        return replace(
            features,
            values=scoped_values,
            suppressed_features=scoped_suppressed,
        )

    def _compute_target_quantity(
        self,
        signal: Signal,
        quote: NBBOQuote,
        manifest: object,
    ) -> int:
        mid_price = (quote.bid + quote.ask) / Decimal(2)
        if mid_price <= 0:
            return 0
        return self._position_sizer.compute_target_quantity(
            signal=signal,
            risk_budget=manifest.risk_budget,  # type: ignore[union-attr]
            symbol_price=mid_price,
            account_equity=self._account_equity,
        )
