"""Per-alpha cost-survival report (close-the-loop: the *measure* layer).

The audit's central finding is that the G12 / B4 gates trade on the
author-disclosed ``edge_estimate_bps`` (an estimate) while the **realized**
edge can be far lower — so an alpha clears the gate and still bleeds fees
(e.g. a backtest where ``sig_kyle_drift_v1`` took 6 fills, realized $0, and
paid $34.79 in fees).  This module turns a backtest's per-fill
:class:`TradeRecord` stream into a per-alpha realized **edge-vs-cost
verdict**, so the estimate→realized gap is measured per strategy rather than
hidden in a fleet aggregate.

It reuses :class:`feelies.forensics.decay_detector.DecayDetector` for the
canonical realized edge / cost computation (``analyze_fills``), so the
numbers match the rest of the forensics stack.

This is the input the *automate* layer (evidence-driven auto-quarantine)
consumes: an alpha whose realized edge does not clear cost over a window is
exactly what the manual ``sig_inventory_revert_v1`` quarantine did by hand.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from feelies.forensics.decay_detector import DecayDetector
from feelies.storage.trade_journal import TradeRecord

# Inv-12 survival bar: realized edge must clear this multiple of modeled
# per-trade cost.  Configurable; default mirrors MIN_MARGIN_RATIO.
DEFAULT_MIN_MARGIN_RATIO: float = 1.5
# Below this fill count a per-alpha realized PnL is noise, not evidence —
# flagged LOW_N so a 3-fill lucky day cannot read as "survives".
DEFAULT_MIN_FILLS: int = 20

# Verdict vocabulary (ordered worst → best for summary counting).
VERDICT_LOW_N = "LOW_N"
VERDICT_BLEED = "BLEED"
VERDICT_MARGINAL = "MARGINAL"
VERDICT_SURVIVES = "SURVIVES"


@dataclass(frozen=True, kw_only=True)
class AlphaCostSurvival:
    """One alpha's realized edge-vs-cost summary over a set of fills.

    Two distinct cost views travel together — keep them straight (audit P1-9):

    * ``net = gross_pnl - fees`` is the **economic** bottom line: mid-to-mid
      PnL less the booked ``fees`` (which include the spread component).  The
      BLEED verdict and the circuit-breaker's primary trip key off it.
    * ``realized_margin_ratio = mean_edge_bps / mean_cost_bps`` is a **gross**
      edge-vs-modeled-cost ratio: ``mean_edge_bps`` is gross of fees and
      ``mean_cost_bps`` is the modeled per-trade cost
      (``TradeRecord.cost_bps``) — a *different* quantity from ``fees``.  An
      alpha can be ``net``-positive yet have a thin gross margin (MARGINAL).
      The two views are not interchangeable.
    """

    strategy_id: str
    n_fills: int
    gross_pnl: float
    """Sum of mid-to-mid ``realized_pnl`` (gross of fees)."""
    fees: float
    net: float
    """``gross_pnl - fees`` — net-of-fees economic PnL."""
    mean_edge_bps: float
    """Mean **gross** edge in bps (matches ``DecayDetector.analyze_fills``)."""
    mean_cost_bps: float
    """Mean modeled per-trade cost in bps (``TradeRecord.cost_bps``)."""
    realized_margin_ratio: float
    """``mean_edge_bps / mean_cost_bps`` — gross-edge-vs-modeled-cost ratio."""
    pct_edge_covers_cost: float
    verdict: str


def _verdict(
    *,
    n_fills: int,
    net: float,
    mean_edge_bps: float,
    mean_cost_bps: float,
    min_margin_ratio: float,
    min_fills: int,
) -> str:
    if net <= 0.0:
        # Losing money is a fact worth flagging regardless of sample size;
        # low n only weakens confidence, it doesn't make a loss "unknown".
        return VERDICT_BLEED
    if n_fills < min_fills:
        # Net positive but too few fills to trust — a lucky-day guard so a
        # 3-fill winner cannot read as "survives".
        return VERDICT_LOW_N
    if mean_cost_bps > 0.0 and mean_edge_bps >= min_margin_ratio * mean_cost_bps:
        return VERDICT_SURVIVES
    # net positive but the realized edge does not clear the Inv-12 bar —
    # profitable today, structurally fragile.
    return VERDICT_MARGINAL


def per_alpha_cost_survival(
    records: Iterable[TradeRecord],
    *,
    min_margin_ratio: float = DEFAULT_MIN_MARGIN_RATIO,
    min_fills: int = DEFAULT_MIN_FILLS,
) -> list[AlphaCostSurvival]:
    """Group *records* by ``strategy_id`` and score each alpha's realized
    edge against its cost.  Rows are returned sorted by net contribution
    (descending)."""
    by_alpha: "OrderedDict[str, list[TradeRecord]]" = OrderedDict()
    for rec in records:
        by_alpha.setdefault(rec.strategy_id, []).append(rec)

    detector = DecayDetector()
    rows: list[AlphaCostSurvival] = []
    for strategy_id, trades in by_alpha.items():
        tca = detector.analyze_fills(trades)
        gross = float(sum((t.realized_pnl for t in trades), Decimal("0")))
        fees = float(sum((t.fees for t in trades), Decimal("0")))
        net = gross - fees
        margin = (
            tca.mean_edge_bps / tca.mean_cost_bps
            if tca.mean_cost_bps > 0.0
            else float("inf")
        )
        rows.append(
            AlphaCostSurvival(
                strategy_id=strategy_id,
                n_fills=len(trades),
                gross_pnl=gross,
                fees=fees,
                net=net,
                mean_edge_bps=tca.mean_edge_bps,
                mean_cost_bps=tca.mean_cost_bps,
                realized_margin_ratio=margin,
                pct_edge_covers_cost=tca.pct_edge_covers_cost,
                verdict=_verdict(
                    n_fills=len(trades),
                    net=net,
                    mean_edge_bps=tca.mean_edge_bps,
                    mean_cost_bps=tca.mean_cost_bps,
                    min_margin_ratio=min_margin_ratio,
                    min_fills=min_fills,
                ),
            )
        )
    rows.sort(key=lambda r: r.net, reverse=True)
    return rows


def format_cost_survival_report(
    rows: list[AlphaCostSurvival],
    *,
    min_margin_ratio: float = DEFAULT_MIN_MARGIN_RATIO,
    min_fills: int = DEFAULT_MIN_FILLS,
) -> str:
    """Render a per-alpha cost-survival table + fleet summary."""
    out: list[str] = []
    out.append(
        f"Per-Alpha Cost Survival (realized edge vs cost; "
        f"min_margin={min_margin_ratio:g}x, min_fills={min_fills}):"
    )
    header = (
        f"  {'strategy_id':<26s}{'fills':>6s}{'net':>12s}"
        f"{'edge_bps':>10s}{'cost_bps':>10s}{'margin':>8s}{'cover%':>8s}  verdict"
    )
    out.append(header)
    n_fills = gross = fees = net = 0.0
    counts: dict[str, int] = {}
    for r in rows:
        margin_str = "inf" if r.realized_margin_ratio == float("inf") else f"{r.realized_margin_ratio:.2f}"
        out.append(
            f"  {r.strategy_id:<26s}{r.n_fills:>6d}{r.net:>+12.2f}"
            f"{r.mean_edge_bps:>10.2f}{r.mean_cost_bps:>10.2f}{margin_str:>8s}"
            f"{r.pct_edge_covers_cost:>7.1f}%  {r.verdict}"
        )
        n_fills += r.n_fills
        gross += r.gross_pnl
        fees += r.fees
        net += r.net
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    out.append(
        f"  {'FLEET':<26s}{int(n_fills):>6d}{net:>+12.2f}"
        f"  (gross {gross:+.2f}, fees {fees:.2f})"
    )
    summary = ", ".join(
        f"{counts[v]} {v}"
        for v in (VERDICT_SURVIVES, VERDICT_MARGINAL, VERDICT_BLEED, VERDICT_LOW_N)
        if v in counts
    )
    if summary:
        out.append(f"  -> {summary}")
    return "\n".join(out)


__all__ = [
    "AlphaCostSurvival",
    "per_alpha_cost_survival",
    "format_cost_survival_report",
    "DEFAULT_MIN_MARGIN_RATIO",
    "DEFAULT_MIN_FILLS",
    "VERDICT_LOW_N",
    "VERDICT_BLEED",
    "VERDICT_MARGINAL",
    "VERDICT_SURVIVES",
]
