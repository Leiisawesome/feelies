# RFC — Cross-Alpha Position Netting (G-5)

**Date:** 2026-06-08
**Status:** Proposal / RFC. **No code changed by this document.**
**Addresses:** G-5 (P1, L) from
`docs/audits/position_management_baseline_2026-06-08.md`.
**Builds on:** the G-1 planner (`DesiredPosition` → `PositionPlan`) and
G-4's per-alpha/per-lot attribution (for validation).
**Mode:** contracts + sequencing only; everything below is *proposed*.

---

## 1. The gap, precisely

There are per-alpha books (`StrategyPositionStore`, one `MemoryPositionStore`
per alpha) and a netted aggregate view (`get_aggregate` →
`strategy_position_store.py:95`). Fills attribute back to alphas via the fill
ledger. But the **decision** is not portfolio-aware:

- **SIGNAL path** — buffered signals are arbitrated to a **single winner per
  tick** (`EdgeWeightedArbitrator.arbitrate`, `arbitration.py:60`: `max(edge ×
  strength)`, FLAT prioritised). That one alpha's target is applied against
  the **net** book; the other alphas' desired targets are **dropped** for the
  tick. The portfolio target (the *sum* of per-alpha desires) is never formed.
- **PORTFOLIO path** — `CompositionEngine` already aggregates into a full
  `SizedPositionIntent.target_positions`; that path *does* form a net target,
  but lives separately and only for PORTFOLIO alphas.

Consequences (RC-B, the netting facet):

1. **Conviction doesn't stack.** Two same-direction SIGNAL alphas don't sum
   into a larger net target — only the per-tick winner is expressed.
2. **A non-winning alpha can't act.** An alpha wanting to reduce while another
   holds is silent unless it wins arbitration that tick.
3. **Trades aren't netted at the desired level.** Internal crossing (A wants
   to buy what B wants to sell) is invisible to the decision layer, so the
   net target is one alpha's view of the net book rather than the portfolio's.

## 2. Core idea

Insert a **`PortfolioNetter`** between per-alpha desired targets and the G-1
planner. It produces, per symbol, a single **net `DesiredPosition`** =
(risk-budgeted) sum of every alpha's *standing* desired target. The planner
then diffs net-desired vs the net book exactly as today — so internal crossing
nets to zero automatically and only the **residual** reaches the market.

```
per-alpha standing desired targets ──► PortfolioNetter.net(symbol)
                                          │  Σ (budget-weighted) per-alpha target
                                          ▼
                              net DesiredPosition(symbol)
                                          ▼
                               PositionManager.plan()  (G-1, unchanged)
                                          ▼
                          gates ▸ execution ▸ fills ▸ fill-ledger attribution
```

This subsumes winner-take-all arbitration for the netting purpose (arbitration
stays as the *tie-break / dead-zone* within a single alpha's signals, not as
the cross-alpha selector) and unifies the SIGNAL and PORTFOLIO paths onto one
net-target model.

## 3. The crux: a per-alpha *standing target* book

Signals are sparse and horizon-gated — an alpha emits occasionally and its
desired position **persists** between emissions. To net per-alpha desires
every tick, the netter needs each alpha's *current* standing target, not just
this tick's signal. So G-5's real new state is a **per-alpha desired-target
book**: `{(strategy_id, symbol) → DesiredPosition}`, updated when that alpha
signals (or exits / decays), read by the netter every decision.

The PORTFOLIO path already has this (composition emits a full target each
cycle); the SIGNAL path is event-driven and does not. **Giving the SIGNAL
path a standing-target book is the bulk of G-5.** Open question: how long a
standing target lives without refresh (a staleness/expiry policy, likely tied
to the alpha's `horizon_seconds`).

## 4. Design decisions (need sign-off)

1. **Aggregation rule.** Net target = Σ per-alpha targets, or
   budget-weighted Σ (each alpha's target capped by its `risk_budget`, then
   summed, then capped by portfolio `max_position_per_symbol`)? *Recommend
   budget-weighted sum* — it preserves per-alpha risk discipline while letting
   conviction stack.
2. **Standing-target staleness.** Expire an alpha's standing target after
   `k × horizon_seconds` with no refresh (else a dead alpha pins exposure)?
   *Recommend yes*, configurable.
3. **Arbitration's new role.** Keep `EdgeWeightedArbitrator` to collapse
   *one alpha's* multiple same-tick signals, but remove it as the
   *cross-alpha* selector (the netter sums instead). Confirm.
4. **Unify or bridge the PORTFOLIO path.** Route `SizedPositionIntent`
   target_positions through the same `PortfolioNetter` (one netting layer for
   both), or leave composition as a parallel producer feeding the netter?
   *Recommend one netter*, fed by both producers.
5. **Risk + attribution.** Per-alpha budgets still enforced upstream
   (sizing) and via `AlphaBudgetRiskWrapper`; the net order's fills attribute
   back through the existing fill ledger. Confirm no double-counting.

## 5. Determinism & parity

- **Pure + ordered.** `PortfolioNetter.net` is a pure function of the
  standing-target book; iterate alphas in sorted order (Inv-5).
- **Shadow first.** Ship the netter + standing-target book in **shadow**:
  compute the net target alongside the live winner-take-all decision and log
  any divergence (reusing the G-1 shadow-sink pattern). Parity-neutral.
- **Default-off flip.** Drive the decision from the net target behind a
  config flag (default off → today's arbitration, byte-identical). New
  baseline captured when on — this is a genuine behavioral change (conviction
  stacking, trade netting), so it is *expected* to move the trade path.
- **G-4 validates it.** Per-alpha/per-lot attribution (just landed) is the
  instrument to confirm the netter eliminates cross-alpha churn (fewer
  offsetting fills; lower per-alpha round-trip count for the same net book).

## 6. Phased rollout

| Phase | Deliverable | Default | Parity |
|-------|-------------|---------|--------|
| **N0** | `DesiredTargetBook` (per-alpha standing targets) + `PortfolioNetter.net` (pure) + unit tests | off | none |
| **N1** | Maintain the standing-target book from the SIGNAL path; run the netter in **shadow**, log divergence vs winner-take-all | shadow | none |
| **N2** | Drive the decision from the net target (SIGNAL path) behind `enable_portfolio_netting`; arbitration demoted to intra-alpha | off→on | new baseline |
| **N3** | Route the PORTFOLIO `SizedPositionIntent` path through the same netter; retire the parallel `check_sized_intent` diff | off→on | shadow-verified |
| **N4** | Standing-target staleness/expiry + per-alpha budget-weighting tuning | on | new baseline |

N0–N1 are parity-neutral plumbing; N2+ are the behavioral wins, each gated.

## 7. Scope boundaries

Out of scope here: lot-level cross-alpha attribution beyond what G-4 exposes;
a cross-sectional optimiser (this is *netting*, not portfolio optimisation);
sizing changes (G-7, deliberately last — its inventory term then lives at the
**net** level this RFC establishes).

## 8. Decisions locked (2026-06-08)

1. **Reinforcement: stacking, capped.** Same-direction alphas **sum** into a
   larger net target. Each alpha's target is capped by its `risk_budget`; the
   summed net is capped by portfolio `max_position_per_symbol`. Conviction is
   expressed, bounded by the existing per-symbol cap.
2. **Aggregation: budget-weighted sum.** Each per-alpha target is sized/capped
   by its own `risk_budget` *before* summing (per-alpha risk discipline
   preserved), then the portfolio cap applies to the net.
3. **Staleness: expire after `k × horizon_seconds`.** A standing target with no
   refresh within `k ×` the alpha's horizon decays to flat, so a dead/stale
   alpha cannot pin exposure. `k` is configurable.
4. **Scope: SIGNAL-path first, bridge PORTFOLIO later.** Net the SIGNAL path
   now (N0–N2); leave the PORTFOLIO `SizedPositionIntent` path as-is and unify
   it through the netter in N3. Smaller, lower-risk first step.

These resolve §4 and the prior open questions; (1)+(2) make the net target a
**budget-weighted, portfolio-capped sum** of standing per-alpha targets.
