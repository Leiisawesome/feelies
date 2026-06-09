"""Cross-alpha position netting — G-5 phase N0 (pure contracts).

A :class:`DesiredTargetBook` holds each alpha's *standing* desired target per
symbol (signals are sparse/horizon-gated, so a target persists between
emissions), with a per-alpha budget cap and a ``k × horizon`` expiry.  The
:class:`PortfolioNetter` collapses the live standing targets for a symbol into
a single **net** :class:`DesiredPosition` that the G-1 planner then diffs
against the net book.

Locked decisions (2026-06-08,
``docs/audits/position_management_g5_netting_rfc_2026-06-08.md``):

  - **Stacking, capped** — same-direction alphas *sum* into a larger net
    target (conviction stacks), bounded by the portfolio cap.
  - **Budget-weighted sum** — each per-alpha target is clamped to its own
    ``risk_budget`` (``max_abs_qty``) *before* summing; the net is then
    clamped to ``portfolio_max_abs_qty``.
  - **Expiry** — a standing target with no refresh by ``expiry_ns`` is dropped.

Pure and order-independent (Inv-5).  N0 wires nothing to drive — it is
parity-neutral plumbing for the shadow harness (N1) and the flip (N2).
"""

from __future__ import annotations

from dataclasses import dataclass

from feelies.execution.position_manager import DesiredPosition


@dataclass(frozen=True, kw_only=True)
class StandingTarget:
    """An alpha's standing desired target for a symbol.

    ``target_qty`` is signed (``+`` long / ``-`` short).  ``max_abs_qty`` is
    the alpha's per-symbol budget cap in shares (``None`` = uncapped — rely on
    the upstream sizer).  ``expiry_ns`` is the exchange-time ns *after* which
    the target is stale — the target remains fresh at the boundary instant
    ``now_ns == expiry_ns`` to stay in lock-step with the orchestrator's
    pre-tick signal-buffer policy (``age <= horizon × 1e9`` is fresh).
    ``None`` = never expires.
    """

    strategy_id: str
    symbol: str
    target_qty: int
    edge_bps: float = 0.0
    urgency: float = 0.5
    max_abs_qty: int | None = None
    expiry_ns: int | None = None


def standing_target_from_desired(
    desired: DesiredPosition,
    *,
    strategy_id: str,
    signal_timestamp_ns: int,
    horizon_seconds: int,
    staleness_k: float,
    max_abs_qty: int | None = None,
) -> StandingTarget:
    """Build a :class:`StandingTarget` with a ``k × horizon`` expiry.

    The expiry is ``signal_ts + k × horizon_seconds`` (in ns); ``None`` when
    either ``horizon_seconds`` or ``staleness_k`` is non-positive (no decay —
    the target lives until refreshed or explicitly cleared).
    """
    expiry_ns: int | None = None
    if horizon_seconds > 0 and staleness_k > 0:
        expiry_ns = signal_timestamp_ns + int(
            staleness_k * horizon_seconds * 1_000_000_000
        )
    return StandingTarget(
        strategy_id=strategy_id,
        symbol=desired.symbol,
        target_qty=desired.target_qty,
        edge_bps=desired.edge_bps,
        urgency=desired.urgency,
        max_abs_qty=max_abs_qty,
        expiry_ns=expiry_ns,
    )


def _clamp(x: int, limit: int) -> int:
    return max(-limit, min(limit, x))


@dataclass(frozen=True, kw_only=True)
class NetDivergence:
    """N1 shadow record: the net target differs from the winner-take-all one.

    Emitted when the budget-weighted portfolio net for a symbol disagrees with
    the single arbitrated winner's target — the measurement that quantifies
    how much cross-alpha netting would change the decision before any flip.
    """

    symbol: str
    signal_sequence: int
    winner_strategy_id: str
    winner_target_qty: int
    net_target_qty: int
    contributing_alphas: int
    detail: str = ""


def _is_stale(t: StandingTarget, now_ns: int) -> bool:
    return t.expiry_ns is not None and now_ns > t.expiry_ns


class DesiredTargetBook:
    """Per-``(strategy_id, symbol)`` standing desired targets."""

    def __init__(self) -> None:
        self._book: dict[tuple[str, str], StandingTarget] = {}

    def put(self, target: StandingTarget) -> None:
        self._book[(target.strategy_id, target.symbol)] = target

    def clear(self, strategy_id: str, symbol: str) -> None:
        self._book.pop((strategy_id, symbol), None)

    def get(self, strategy_id: str, symbol: str) -> StandingTarget | None:
        return self._book.get((strategy_id, symbol))

    def live_targets(self, symbol: str, now_ns: int) -> list[StandingTarget]:
        """Non-stale standing targets for ``symbol``, sorted by strategy id."""
        return sorted(
            (
                t for (_, sym), t in self._book.items()
                if sym == symbol and not _is_stale(t, now_ns)
            ),
            key=lambda t: t.strategy_id,
        )

    def symbols(self) -> set[str]:
        return {sym for (_, sym) in self._book}


class PortfolioNetter:
    """Budget-weighted, portfolio-capped sum of standing per-alpha targets."""

    def __init__(
        self,
        book: DesiredTargetBook,
        *,
        portfolio_max_abs_qty: int | None = None,
    ) -> None:
        self._book = book
        self._portfolio_max = portfolio_max_abs_qty

    def net(self, symbol: str, now_ns: int) -> DesiredPosition:
        """Collapse live standing targets into one net ``DesiredPosition``.

        Each per-alpha target is clamped to its budget, summed (conviction
        stacks; opposing desires offset), then clamped to the portfolio cap.
        The net ``edge_bps`` is the |qty|-weighted average over contributors
        aligned with the net direction; ``urgency`` is the max over those
        contributors (most-urgent wins for execution style).
        """
        live = self._book.live_targets(symbol, now_ns)
        clamped: list[tuple[int, StandingTarget]] = []
        for t in live:
            tq = t.target_qty
            if t.max_abs_qty is not None:
                tq = _clamp(tq, t.max_abs_qty)
            clamped.append((tq, t))

        total = sum(tq for tq, _ in clamped)
        if self._portfolio_max is not None:
            total = _clamp(total, self._portfolio_max)
        direction = (total > 0) - (total < 0)

        aligned = [
            (tq, t) for tq, t in clamped
            if tq != 0 and ((tq > 0) == (total > 0)) and direction != 0
        ]
        weight = sum(abs(tq) for tq, _ in aligned)
        edge = (
            sum(t.edge_bps * abs(tq) for tq, t in aligned) / weight
            if weight > 0 else 0.0
        )
        urgency = max((t.urgency for _, t in aligned), default=0.5)

        return DesiredPosition(
            symbol=symbol,
            target_qty=total,
            direction=direction,
            edge_bps=edge,
            urgency=urgency,
            source="portfolio_net",
            reason="netted",
        )
