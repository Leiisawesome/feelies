# Closing the estimate→realized edge loop

**Problem (audit central thesis, confirmed in realized PnL).** The G12
load gate and the B4 runtime gate trade on the author-disclosed
`edge_estimate_bps` — an *estimate*. Nothing reconciles it against
*realized* edge, so an optimistic estimate clears the gate and still loses
(e.g. APP 2026-03-26: `sig_kyle_drift_v1` took 6 fills, realized $0, paid
$34.79 in fees; the fleet "+$83.28" was two fee-bleeders plus one lucky
3-fill sample).

The platform already *measures* realized edge (`forensics/decay_detector`,
`fill_attribution`, `multi_horizon_attribution`) but never *acted* on it —
the loop was open. This is the plan to close it.

## Four layers

| Layer | What | Status |
|---|---|---|
| **Measure** | Per-alpha realized edge vs cost, with a verdict | **shipped** — `forensics/cost_survival.py`, surfaced in every backtest report |
| **Automate** | Auto-quarantine a persistently cost-failing LIVE alpha | **shipped** — `forensics/cost_circuit_breaker.py` |
| **Calibrate** | Haircut `edge_estimate_bps` by realized/disclosed ratio | planned |
| **Gate** | Gate G12/B4 on the *lower confidence bound* of a data-fit edge | planned |

## Measure — `cost_survival.py`

`per_alpha_cost_survival(records)` groups `TradeRecord`s by `strategy_id`,
reuses `DecayDetector.analyze_fills` for the canonical realized edge/cost,
and assigns a verdict:

- **BLEED** — net ≤ 0 (paying fees for no realized edge).
- **LOW_N** — net > 0 but < `min_fills` (a lucky-sample guard).
- **SURVIVES** — net > 0 and realized edge ≥ `min_margin_ratio` × cost.
- **MARGINAL** — net > 0 but under the Inv-12 bar (fragile).

Rendered as a "Per-Alpha Cost Survival" section in `backtest_report`.

## Automate — `cost_circuit_breaker.py`

Two stages, deliberately separated:

- `evaluate_cost_circuit_breaker(records, policy)` — **pure**, deterministic
  decisions (`QUARANTINE` / `WATCH` / `OK` / `INSUFFICIENT_EVIDENCE`). A
  thin window (< `policy.min_fills`, default 30) is `INSUFFICIENT` — the
  breaker will **not** demote on one noisy day; "persistence" comes from the
  caller supplying a rolling multi-session fill window.
- `apply_cost_circuit_breaker(decisions, lifecycles)` — drives the **real**
  `AlphaLifecycle.quarantine` (`LIVE → QUARANTINED` + durable ledger entry)
  for flagged LIVE alphas. Non-LIVE alphas are skipped (the promotion gate
  is the relevant control there).

### Determinism (Inv-5)

`apply` is a **session/epoch-boundary action**, never per-tick. The
quarantine writes a durable, versioned promotion-ledger entry; the *next*
run reads that lifecycle state at load. Within a replay run the lifecycle
state is a fixed input, so replay stays bit-identical. This is the same
pattern the codebase already uses to keep `promotion_evidence` out of
per-tick decisions.

### Wiring point (operational, not yet auto-invoked)

The breaker is a mechanism; it is intentionally **not** auto-invoked from
the per-tick path or from single-day backtests (which would be
all-`INSUFFICIENT`). Wire it into a **session-end / EOD job** in PAPER/LIVE
operation:

```python
records = list(trade_journal.query(start_ns=window_start))  # rolling window
decisions = evaluate_cost_circuit_breaker(records)
applied = apply_cost_circuit_breaker(decisions, live_lifecycles, correlation_id=run_id)
# 'applied' alphas are now QUARANTINED in the ledger; the next session's
# loader/registry refuses them PAPER/LIVE capital.
```

This generalizes the manual `sig_inventory_revert_v1` quarantine into
evidence-driven policy.

## Next: Calibrate + Gate

- **Calibrate**: maintain a per-`(alpha, regime)` rolling
  `realized_edge / disclosed_edge` ratio (from `cost_survival`) and apply it
  as a versioned haircut to the `edge_estimate_bps` the gates see — Inv-4
  (edge decays when exploited), boundary-updated for determinism.
- **Gate**: replace hand-set `edge_per_*_bps` slopes with regression-fit
  slopes (forward return on the driving feature, OOS; the `forward_ic`
  harness is the seed) disclosed with a confidence interval, and gate on the
  **lower bound**, not the point estimate — removing the optimism at the
  source.
