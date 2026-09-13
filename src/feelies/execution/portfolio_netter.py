"""Pure cross-alpha position netting.

A :class:`DesiredTargetBook` holds each alpha's *standing* desired target per
symbol (signals are sparse/horizon-gated, so a target persists between
emissions), with a per-alpha budget cap and a ``k × horizon`` expiry.  The
:class:`PortfolioNetter` collapses the live standing targets for a symbol into
a single net :class:`DesiredPosition` that the planner diffs
against the net book.

Netting contract:

  - **Stacking, capped** — same-direction alphas *sum* into a larger net
    target (conviction stacks), bounded by the portfolio cap.
  - **Budget-weighted sum** — each per-alpha target is clamped to its own
    ``risk_budget`` (``max_abs_qty``) *before* summing; the net is then
    clamped to ``portfolio_max_abs_qty``.
  - **Expiry** — a standing target with no refresh by ``expiry_ns`` is dropped.

The calculation is pure and independent of input order.
"""

from __future__ import annotations

from feelies.core.portfolio_netter import DesiredTargetBook as DesiredTargetBook
from feelies.core.portfolio_netter import NetDivergence as NetDivergence
from feelies.core.portfolio_netter import PortfolioNetter as PortfolioNetter
from feelies.core.portfolio_netter import StandingTarget as StandingTarget
from feelies.core.portfolio_netter import (
    standing_target_from_desired as standing_target_from_desired,
)
