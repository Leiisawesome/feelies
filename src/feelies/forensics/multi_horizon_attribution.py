"""Read-only PnL attribution by horizon, fill-time regime, and mechanism.

Trade provenance is authoritative. Missing mechanism provenance falls back to
the latest intent's gross-share breakdown; any remainder is explicit in
``unattributed`` so totals conserve. The attributor performs no live lookups or
time reads and returns stable, immutable reports.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Mapping

from feelies.core.events import TrendMechanism
from feelies.portfolio.cross_sectional_tracker import CrossSectionalSnapshot
from feelies.storage.trade_journal import TradeRecord

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HorizonBucket:
    """Realized PnL aggregated for one ``(strategy_id, horizon_seconds)``."""

    strategy_id: str
    horizon_seconds: int
    trade_count: int
    realized_pnl: float
    fees: float
    gross_notional: float


@dataclass(frozen=True)
class MechanismBucket:
    """Realized PnL attributed to one ``(strategy_id, mechanism)`` slice."""

    strategy_id: str
    mechanism: TrendMechanism
    realized_pnl_share: float
    gross_share: float


@dataclass(frozen=True)
class RegimeBucket:
    """Realized PnL aggregated for one ``(strategy_id, regime_state)`` slice."""

    strategy_id: str
    regime_state: str
    trade_count: int
    realized_pnl: float


@dataclass(frozen=True)
class MultiHorizonReport:
    """Snapshot returned by :meth:`MultiHorizonAttributor.attribute`.

    Iteration order over every dict is lex-sorted on the key tuple so
    JSON-serialised output is bit-stable across replays.

    ``unattributed`` carries, per strategy, any realized PnL the mechanism
    axis could not place against a named family (a trade with no mechanism
    provenance for a strategy that has *some*, or a strategy with neither
    per-trade provenance nor an intent snapshot).  It exists so the
    mechanism axis conserves: for every strategy,
    ``Σ_m mechanism[(sid, m)].realized_pnl_share + unattributed[sid]``
    equals that strategy's total realized PnL.
    """

    horizon: dict[tuple[str, int], HorizonBucket] = field(default_factory=dict)
    mechanism: dict[tuple[str, TrendMechanism], MechanismBucket] = field(default_factory=dict)
    regime: dict[tuple[str, str], RegimeBucket] = field(default_factory=dict)
    unattributed: dict[str, float] = field(default_factory=dict)


class MultiHorizonAttributor:
    """Stateful attribution helper.

    Parameters
    ----------
    intent_snapshots :
        Map ``strategy_id → CrossSectionalSnapshot``.  Supplies the
        per-mechanism gross-share weights used as a **fallback** to slice
        realized PnL for strategies whose trades carry no
        ``trend_mechanism`` provenance (typically cross-sectional
        PORTFOLIO fills).  Intents whose ``mechanism_breakdown`` is empty
        contribute zero to the mechanism axis; the PnL is reported under
        :attr:`MultiHorizonReport.unattributed` instead of vanishing.
    horizon_by_strategy :
        Map ``strategy_id → horizon_seconds``.  Required for every
        strategy that appears in the trade journal (otherwise the
        horizon axis bucket key uses ``-1`` as a sentinel — caller can
        detect this).
    """

    __slots__ = (
        "_intent_snapshots",
        "_horizon_by_strategy",
    )

    def __init__(
        self,
        *,
        intent_snapshots: Mapping[str, CrossSectionalSnapshot] | None = None,
        horizon_by_strategy: Mapping[str, int] | None = None,
    ) -> None:
        self._intent_snapshots = dict(intent_snapshots or {})
        self._horizon_by_strategy = dict(horizon_by_strategy or {})

    # ── Public API ───────────────────────────────────────────────────

    def attribute(
        self,
        trades: Iterable[TradeRecord],
    ) -> MultiHorizonReport:
        horizon_acc: dict[tuple[str, int], _HorizonAcc] = defaultdict(_HorizonAcc)
        regime_acc: dict[tuple[str, str], _RegimeAcc] = defaultdict(_RegimeAcc)
        # Total realized PnL per strategy (every axis must reconcile to it).
        strategy_pnl: dict[str, float] = defaultdict(float)
        # Per-trade mechanism provenance (Inv-1): realized PnL and gross
        # notional grouped by the actual mechanism each fill carried.
        mech_pnl: dict[tuple[str, TrendMechanism], float] = defaultdict(float)
        mech_notional: dict[tuple[str, TrendMechanism], float] = defaultdict(float)
        # Strategies with at least one mechanism-bearing trade prefer the
        # per-trade path; the residual PnL from their mechanism-less trades
        # is tracked so the axis still conserves.
        strat_has_mech: set[str] = set()
        strat_residual_pnl: dict[str, float] = defaultdict(float)

        for trade in trades:
            sid = trade.strategy_id
            horizon = self._horizon_by_strategy.get(sid, -1)
            pnl = float(trade.realized_pnl)
            fees = float(trade.fees)
            notional = self._notional(trade)

            acc = horizon_acc[(sid, horizon)]
            acc.trade_count += 1
            acc.realized_pnl += pnl
            acc.fees += fees
            acc.gross_notional += notional

            strategy_pnl[sid] += pnl

            # Regime axis — causal, taken from the record (no live lookup).
            regime_state = trade.regime_state.strip() if trade.regime_state else ""
            if regime_state:
                r_acc = regime_acc[(sid, regime_state)]
                r_acc.trade_count += 1
                r_acc.realized_pnl += pnl

            # Mechanism axis — per-trade provenance.
            mech = trade.trend_mechanism
            if mech is not None:
                mech_pnl[(sid, mech)] += pnl
                mech_notional[(sid, mech)] += notional
                strat_has_mech.add(sid)
            else:
                strat_residual_pnl[sid] += pnl

        mechanism_buckets, unattributed = self._build_mechanism_axis(
            strategy_pnl=strategy_pnl,
            mech_pnl=mech_pnl,
            mech_notional=mech_notional,
            strat_has_mech=strat_has_mech,
            strat_residual_pnl=strat_residual_pnl,
        )

        # Materialise frozen records, sorted for replay-stable iteration.
        horizon_buckets: dict[tuple[str, int], HorizonBucket] = {}
        for h_key in sorted(horizon_acc):
            sid, h = h_key
            acc = horizon_acc[h_key]
            horizon_buckets[h_key] = HorizonBucket(
                strategy_id=sid,
                horizon_seconds=h,
                trade_count=acc.trade_count,
                realized_pnl=acc.realized_pnl,
                fees=acc.fees,
                gross_notional=acc.gross_notional,
            )

        regime_buckets: dict[tuple[str, str], RegimeBucket] = {}
        for r_key in sorted(regime_acc):
            r_sid, r_state = r_key
            r_acc = regime_acc[r_key]
            regime_buckets[r_key] = RegimeBucket(
                strategy_id=r_sid,
                regime_state=r_state,
                trade_count=r_acc.trade_count,
                realized_pnl=r_acc.realized_pnl,
            )

        return MultiHorizonReport(
            horizon=horizon_buckets,
            mechanism=mechanism_buckets,
            regime=regime_buckets,
            unattributed=unattributed,
        )

    # ── Internals ────────────────────────────────────────────────────

    def _build_mechanism_axis(
        self,
        *,
        strategy_pnl: Mapping[str, float],
        mech_pnl: Mapping[tuple[str, TrendMechanism], float],
        mech_notional: Mapping[tuple[str, TrendMechanism], float],
        strat_has_mech: set[str],
        strat_residual_pnl: Mapping[str, float],
    ) -> tuple[dict[tuple[str, TrendMechanism], MechanismBucket], dict[str, float]]:
        """Build the mechanism axis with exact per-strategy conservation.

        Returns ``(mechanism_buckets, unattributed)`` where, for every
        strategy, the sum of its mechanism shares plus its ``unattributed``
        entry equals its total realized PnL.
        """
        mechanism_buckets: dict[tuple[str, TrendMechanism], MechanismBucket] = {}
        unattributed: dict[str, float] = {}

        for sid in sorted(strategy_pnl):
            total_pnl = strategy_pnl[sid]
            if sid in strat_has_mech:
                # Per-trade provenance path (Inv-1) — exact conservation.
                keys = sorted(
                    (k for k in mech_pnl if k[0] == sid),
                    key=lambda k: k[1].name,
                )
                total_notional = sum(mech_notional[k] for k in keys)
                for key in keys:
                    _sid, mech = key
                    gross_share = (
                        mech_notional[key] / total_notional if total_notional > 0 else 0.0
                    )
                    mechanism_buckets[key] = MechanismBucket(
                        strategy_id=sid,
                        mechanism=mech,
                        realized_pnl_share=mech_pnl[key],
                        gross_share=gross_share,
                    )
                residual = strat_residual_pnl.get(sid, 0.0)
                if residual:
                    unattributed[sid] = residual
                continue

            # Fallback path — gross-share weights from the latest intent
            # snapshot (cross-sectional PORTFOLIO strategies with no
            # per-trade mechanism).
            snap = self._intent_snapshots.get(sid)
            if snap is None or not snap.mechanism_breakdown:
                # No provenance and no snapshot — surface the PnL rather
                # than dropping it silently (conservation).
                if total_pnl:
                    unattributed[sid] = total_pnl
                continue
            total_share = sum(snap.mechanism_breakdown.values())
            if total_share <= 0:
                if total_pnl:
                    unattributed[sid] = total_pnl
                continue
            for mech in sorted(snap.mechanism_breakdown, key=lambda m: m.name):
                share = float(snap.mechanism_breakdown[mech]) / total_share
                mechanism_buckets[(sid, mech)] = MechanismBucket(
                    strategy_id=sid,
                    mechanism=mech,
                    realized_pnl_share=total_pnl * share,
                    gross_share=share,
                )

        return mechanism_buckets, unattributed

    @staticmethod
    def _notional(trade: TradeRecord) -> float:
        if trade.fill_price is None:
            return 0.0
        price = (
            float(trade.fill_price)
            if isinstance(trade.fill_price, Decimal)
            else float(trade.fill_price)
        )
        return float(abs(trade.filled_quantity)) * price


@dataclass
class _HorizonAcc:
    trade_count: int = 0
    realized_pnl: float = 0.0
    fees: float = 0.0
    gross_notional: float = 0.0


@dataclass
class _RegimeAcc:
    trade_count: int = 0
    realized_pnl: float = 0.0


__all__ = [
    "HorizonBucket",
    "MechanismBucket",
    "RegimeBucket",
    "MultiHorizonReport",
    "MultiHorizonAttributor",
]
