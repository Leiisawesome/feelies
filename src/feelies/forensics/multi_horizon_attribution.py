"""Multi-horizon, mechanism-aware PnL attribution — Phase-4-finalize.

Decomposes realized PnL across three orthogonal axes:

* **horizon**          — every PORTFOLIO alpha declares one
                          ``decision_horizon_seconds``; trades booked
                          against a Phase-4 intent inherit it from the
                          intent's correlation-id prefix.  Used by the
                          per-horizon edge / IC dashboards (§20.12.2).
* **regime**           — the dominant regime state at the fill
                          timestamp (taken from the per-symbol
                          :class:`RegimeEngine`).  ``None`` when the
                          regime engine is absent.
* **per_mechanism**    — gross-share-weighted decomposition by
                          :class:`TrendMechanism`.  When a strategy's
                          most recent intent breakdown attributes 60%
                          of gross to ``KYLE_INFO`` and 40% to
                          ``RISK_DRIVEN``, this attribution module
                          reports 60%/40% of that strategy's realized
                          PnL to the respective mechanism buckets.

The module is **read-only**: it consumes trade records and (optional)
intent snapshots and produces immutable :class:`MultiHorizonReport`
objects.  No bus subscriptions, no time reads — fully deterministic
from its inputs (Inv-5).

Usage
-----

.. code-block:: python

    from feelies.forensics.multi_horizon_attribution import (
        MultiHorizonAttributor,
    )

    attr = MultiHorizonAttributor(
        intent_snapshots={"pofi_xsect_v1": last_intent_snapshot},
        regime_engine=regime_engine,
    )
    report = attr.attribute(trade_journal.query(strategy_id="pofi_xsect_v1"))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Mapping

from feelies.core.events import TrendMechanism
from feelies.portfolio.cross_sectional_tracker import CrossSectionalSnapshot
from feelies.services.regime_engine import RegimeEngine
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
    """

    horizon: dict[tuple[str, int], HorizonBucket] = field(
        default_factory=dict
    )
    mechanism: dict[tuple[str, TrendMechanism], MechanismBucket] = field(
        default_factory=dict
    )
    regime: dict[tuple[str, str], RegimeBucket] = field(default_factory=dict)


class MultiHorizonAttributor:
    """Stateful attribution helper.

    Parameters
    ----------
    intent_snapshots :
        Map ``strategy_id → CrossSectionalSnapshot``.  Supplies the
        per-mechanism gross-share weights used to slice realized PnL.
        Intents whose ``mechanism_breakdown`` is empty contribute zero
        to the mechanism axis (still appear on the horizon axis).
    regime_engine :
        Optional shared :class:`RegimeEngine`.  When absent the regime
        axis is empty.
    horizon_by_strategy :
        Map ``strategy_id → horizon_seconds``.  Required for every
        strategy that appears in the trade journal (otherwise the
        horizon axis bucket key uses ``-1`` as a sentinel — caller can
        detect this).
    """

    __slots__ = (
        "_intent_snapshots",
        "_regime_engine",
        "_horizon_by_strategy",
    )

    def __init__(
        self,
        *,
        intent_snapshots: Mapping[str, CrossSectionalSnapshot] | None = None,
        regime_engine: RegimeEngine | None = None,
        horizon_by_strategy: Mapping[str, int] | None = None,
    ) -> None:
        self._intent_snapshots = dict(intent_snapshots or {})
        self._regime_engine = regime_engine
        self._horizon_by_strategy = dict(horizon_by_strategy or {})

    # ── Public API ───────────────────────────────────────────────────

    def attribute(
        self,
        trades: Iterable[TradeRecord],
    ) -> MultiHorizonReport:
        horizon_acc: dict[tuple[str, int], _HorizonAcc] = defaultdict(
            _HorizonAcc
        )
        regime_acc: dict[tuple[str, str], _RegimeAcc] = defaultdict(
            _RegimeAcc
        )
        # Track total realized PnL per strategy so we can split it
        # across mechanisms by the per-strategy gross-share weights.
        strategy_pnl: dict[str, float] = defaultdict(float)

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

            regime_state = self._regime_for(trade.symbol)
            if regime_state is not None:
                r_acc = regime_acc[(sid, regime_state)]
                r_acc.trade_count += 1
                r_acc.realized_pnl += pnl

        # Build mechanism axis from per-strategy intent snapshots.
        mechanism_buckets: dict[
            tuple[str, TrendMechanism], MechanismBucket
        ] = {}
        for sid in sorted(strategy_pnl):
            snap = self._intent_snapshots.get(sid)
            total_pnl = strategy_pnl[sid]
            if snap is None or not snap.mechanism_breakdown:
                continue
            total_share = sum(snap.mechanism_breakdown.values())
            if total_share <= 0:
                continue
            for mech in sorted(
                snap.mechanism_breakdown, key=lambda m: m.name,
            ):
                share = float(snap.mechanism_breakdown[mech]) / total_share
                mechanism_buckets[(sid, mech)] = MechanismBucket(
                    strategy_id=sid,
                    mechanism=mech,
                    realized_pnl_share=total_pnl * share,
                    gross_share=share,
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
        )

    # ── Internals ────────────────────────────────────────────────────

    def _regime_for(self, symbol: str) -> str | None:
        if self._regime_engine is None:
            return None
        post = self._regime_engine.current_state(symbol)
        if post is None:
            return None
        names = list(self._regime_engine.state_names)
        if not names:
            return None
        # Argmax — for forensics, dominant-state attribution is the
        # convention (contrast with risk engine's EV-based scaling).
        idx = max(range(len(post)), key=lambda i: post[i])
        return names[idx] if idx < len(names) else None

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
