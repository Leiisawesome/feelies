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
| **Calibrate** | Haircut `edge_estimate_bps` by realized/disclosed ratio | **shipped** — `forensics/edge_calibration.py` |
| **Gate** | B4 gate on the *lower confidence bound* of realized edge | **shipped** — `orchestrator` B4 reads the calibration factor |
| **Wire** | Session-end boundary job (automate + calibrate) | **shipped** — `forensics/session_reconcile.py` |

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

## Calibrate — `edge_calibration.py`

`build_edge_calibrations(records, disclosed_edges)` reconciles realized edge
(`realized_pnl / notional` bps) against each alpha's disclosed
`edge_estimate_bps` over a fill window and produces two factors in `[0, 1]`:

- `haircut_factor` = clamp(realized_mean / disclosed, 0, 1) — point shrink.
- `lcb_factor` = clamp(realized_LCB / disclosed, 0, 1), where
  `LCB = mean − z·std/√n` — the **lower confidence bound**, so the gate
  trades on a conservative estimate, not an optimistic point.

Insufficient evidence (`n < min_fills` or no disclosed edge) → factor `1.0`
(no haircut). Factors are persisted by `EdgeCalibrationStore` as versioned,
sorted JSON.

## Gate — B4 reads the calibration factor

`Orchestrator` takes `edge_calibration_factors` (`strategy_id → factor`,
loaded by `bootstrap` from `config.edge_calibration_path` via
`EdgeCalibrationStore.factors()`). The B4 gate multiplies
`signal.edge_estimate_bps × factor` before the edge-vs-cost comparison, so
an alpha whose realized edge has decayed is gated on the shrunken estimate.
**Empty factors → 1.0 → identical behaviour** (parity-preserving); a present
factor is a versioned input fixed within a replay (Inv-5).

## Wire — `session_reconcile.py`

`reconcile_session(records, disclosed_edges, lifecycles, calibration_store)`
is the **session/epoch-boundary** job that closes the loop in one call:

1. **Automate** — runs the cost circuit-breaker and quarantines LIVE
   bleeders (durable ledger write).
2. **Calibrate** — rebuilds the edge factors and writes them to the
   `EdgeCalibrationStore` at `config.edge_calibration_path`.

The *next* run's B4 gate reads those factors at construction. Determinism is
preserved because both writes are versioned durable state read at load, never
per-tick.

```python
# session-end / EOD job (PAPER/LIVE)
records = list(trade_journal.query(start_ns=window_start))   # rolling window
reconcile_session(
    records,
    disclosed_edges=disclosed_edges_from_registry(alpha_registry),
    lifecycles=live_lifecycles,
    calibration_store=EdgeCalibrationStore(config.edge_calibration_path),
    calibration_version=session_id,
    correlation_id=run_id,
)
```

## Remaining (optional refinements)

- **Per-regime calibration**: key factors by `(alpha, regime)` rather than
  alpha alone (the structure is already boundary-versioned).
- **Authoring-time CI**: regression-fit the `edge_per_*_bps` slopes (the
  `forward_ic` harness is the seed) and disclose a confidence interval at
  load, so G12 also gates on a lower bound — removing optimism at the source,
  not just at runtime.
- **Live call-site**: invoke `reconcile_session` from the operational
  session-end scheduler (the function is wired and tested; only the live
  cron/hook is environment-specific).
