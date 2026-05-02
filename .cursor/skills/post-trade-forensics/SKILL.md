---
name: post-trade-forensics
description: >
  Post-trade forensics + structural edge-decay detection for the
  feelies platform. Owns multi-horizon attribution (per-mechanism,
  per-regime), the `DecayDetector`, the quarantine-trigger evidence
  schema, and the `AlphaLifecycle.quarantine` auto-trigger. Compares
  expected vs realized slippage, hit rate, and net alpha across
  mechanism families and regimes; detects microstructure regime
  change, edge crowding, and latency-disadvantage emergence. Use
  when analyzing post-trade performance, diagnosing alpha decay,
  auditing strategy health, or reasoning about edge longevity,
  per-mechanism PnL drift, or structural regime shifts.
---

# Post-Trade Forensics & Edge-Decay Analyst

No strategy runs on autopilot. This layer continuously validates that
the structural edge a strategy exploits still exists, still converts
to PnL after costs, and has not been arbitraged away or rendered
obsolete by microstructure regime change. **Every deployed strategy
is guilty of decay until proven otherwise** (Inv-4).

This skill consumes typed events from the platform's audit trail
(`TradeRecord`, `OrderAck`, `RiskVerdict`, `StateTransition`,
`SizedPositionIntent.mechanism_breakdown`, `Signal.trend_mechanism`)
and emits forensic decisions that feed the `AlphaLifecycle`
quarantine path.

## Core Invariants

Inherits Inv-3 (evidence over intuition), Inv-4 (decay is the
default). Additionally:

1. **No autopilot** — every strategy under continuous forensic audit;
   silence is not health.
2. **Expected vs realized** — all metrics compared against backtest /
   model predictions, not absolute thresholds alone.
3. **Feedback-loop closure** — forensic findings feed back into
   backtest calibration, fill models, and research hypotheses.
4. **Mechanism-aware** — every per-trade attribution carries
   `Signal.trend_mechanism` so decay can be diagnosed per family
   rather than smeared across the strategy.
5. **Forensic-only consumer** — never reads the promotion ledger to
   make per-tick decisions; never imports orchestrator / risk-engine
   production code (audit `A-DET-02`).

---

## Multi-Horizon Attribution (`MultiHorizonAttributor`)

`forensics/multi_horizon_attribution.py` decomposes realized PnL
along three orthogonal axes:

| Axis | Bucket type | Source |
|------|-------------|--------|
| Horizon | `HorizonBucket` | `Signal.boundary_index` × alpha's `horizon_seconds` |
| Mechanism | `MechanismBucket` | `Signal.trend_mechanism` (closed `TrendMechanism` enum) |
| Regime | `RegimeBucket` | `RegimeState.dominant_name` at signal time |

Output is a `MultiHorizonReport` carrying per-bucket realized PnL,
hit rate, slippage residual, and a `mechanism_concentration`
diagnostic from the realized vs intended `mechanism_breakdown` on
each `SizedPositionIntent`.

The attributor is the primary tool for diagnosing "what's decaying":

- KYLE_INFO PnL falls while INVENTORY holds → permanent-impact decay,
  not microstructure-wide
- LIQUIDITY_STRESS exits not firing → hazard-detector regression
- HAWKES_SELF_EXCITE alpha latency-stratified → speed-game emergence

---

## 1. Compare: Expected vs Realized

Continuous comparison of live execution outcomes against backtest
model predictions. **Divergence is the primary decay signal**.

### Slippage Comparison

**Ownership boundary**: live-execution monitors slippage in real-time
(rolling 20-trade) and triggers immediate safety responses (throttle,
circuit breaker). This skill performs deeper forensic analysis over
longer windows (50–200 trades) and decides whether drift indicates
structural decay vs transient degradation. Same distinction for fill
rate.

```
expected = backtest_slippage_model(size, spread, volatility)
realized = fill_price - reference_price_at_signal_time
residual = realized - expected
```

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Mean slippage residual | rolling 50 | > 1.5 bps | Investigate fill-model calibration |
| Mean slippage residual | rolling 200 | > 2.5 bps | Recalibrate; reduce sizing |
| Slippage residual trend | 5-day OLS slope | positive, p < 0.05 | Structural cost increase; re-evaluate edge |
| Slippage asymmetry | entry vs exit split | systematic one-side bias | Adverse-selection investigation |
| Slippage by spread regime | stratified | regime-dependent degradation | Update regime-conditional cost model |
| Slippage by mechanism family | stratified by `Signal.trend_mechanism` | family-specific divergence | Mechanism-level decay; not strategy-wide |

### Hit-Rate Comparison

```
expected = backtest_hit_rate(regime, signal_type, spread_bucket)
realized = winning_trades / total_trades
residual = realized - expected
```

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Hit-rate residual | rolling 100 | < −5 pp | Warning |
| Hit-rate residual | rolling 100 | < −10 pp | Reduce allocation 50% |
| Hit-rate trend | 5-day OLS slope | negative, p < 0.05 | Edge-decay investigation |
| Hit rate by regime | stratified | regime-specific collapse | Regime-dependency audit |
| Win/loss asymmetry | avg-win / avg-loss drift | > 20% relative | Payoff-structure degradation |
| Hit rate by mechanism family | stratified | family-specific collapse | Mechanism quarantine evaluation |

### Alpha Before / After Costs

```
gross_alpha   = raw_return - benchmark
net_alpha     = gross_alpha - tx_costs - slippage - market_impact
alpha_erosion = gross_alpha_backtest - net_alpha_live
```

| Metric | Condition | Action |
|--------|-----------|--------|
| Net alpha (rolling 5d) | < 0 after costs | Decay investigation |
| Net alpha (rolling 10d) | < 0 after costs | Quarantine evaluation (matches `QuarantineTriggerEvidence.net_alpha_negative_days` default) |
| Gross-to-net conversion | < 0.5 (live) vs backtest | Cost-model recalibration |
| Alpha half-life | Decreasing across deployment periods | Structural decay confirmed |
| Alpha by mechanism family | concentration narrowing | Mechanism-level fragility |
| Alpha by time-of-day | concentration narrowing | Edge-fragility |

---

## 2. Monitor: Ongoing Health Surveillance

### Parameter Drift

| Class | Detection | Threshold |
|-------|-----------|-----------|
| Signal coefficients | Rolling re-estimate vs deployed | > 2 σ shift from calibration mean |
| Optimal holding period | Rolling exit-timing | > 30% change |
| Entry threshold | Rolling ROC, optimal cutoff drift | AUC degradation > 5% |
| Position-sizing scalar | Realized vs assumed vol | > 25% persistent divergence |
| Cost-model parameters | Realized vs modeled cost dist | KS p < 0.05 |
| `expected_half_life_seconds` (G16) | Realized half-life from `MultiHorizonAttributor` | > 1.5× envelope |

Drift detection protocol: re-estimate on rolling forward window (no
look-ahead), compare to deployed (frozen) values, if drift exceeds
threshold flag for revalidation. **Do not auto-update parameters** —
drift may indicate edge loss, not recalibration need.

### Regime Dependency Stability

**Ownership boundary**: risk-engine owns real-time regime detection
and immediate risk responses. This skill audits whether
classifications remain accurate over time and whether alpha
concentrates in or collapses across regimes.

| Check | Method | Failure |
|-------|--------|---------|
| Cross-regime alpha | Stratify PnL by spread/vol/liquidity regime | Concentrated in < 1 regime (was distributed) |
| Regime-transition PnL | PnL during transitions | Systematic losses on transitions (model lag) |
| Regime-dwell sensitivity | PnL in short vs long regime episodes | Strategy requires unrealistic persistence |
| Regime-frequency shift | Transition rate vs historical | > 50% change (market structure shift) |
| Misclassification rate | Predicted vs realized regime labels | > 20% error |

### Fill-Rate Deterioration

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Passive fill-rate drift | rolling 200 orders | > −10% relative | Warning |
| Passive fill-rate drift | rolling 200 orders | > −20% relative | Shift to more aggressive order types |
| Aggressive fill-rate drift | rolling 200 orders | > −5% relative | Broker / venue investigation |
| Fill rate by time-of-day | hourly buckets | systematic degradation | Edge-timing shift |
| Partial-fill rate increase | rolling 200 | > 30% relative | Liquidity-withdrawal detection |

---

## 3. Detect: Structural Change

### Microstructure Regime Change

The most dangerous decay vector — invalidates the **causal mechanism**,
not just the parameters.

| Signal | Observable | Detection |
|--------|-----------|-----------|
| Spread regime shift | Median quoted spread (5d) | > 30% change from calibration |
| Quote-update frequency | Quotes / sec distribution | KS p < 0.01 |
| Trade-size distribution | Mean / median | > 25% persistent change |
| Tick-to-trade ratio | Quotes / trade | > 30% change |
| Venue composition | Trades by exchange | Herfindahl change > 0.1 |
| Intraday volume profile | Volume-by-minute | Correlation with historical < 0.8 |

### Edge Crowding

Detect when the same structural edge is being competed away.

| Symptom | Observable | Interpretation |
|---------|-----------|----------------|
| Alpha decay with stable signal quality | Hit-rate stable, profit-per-trade ↓ | Others trading same pattern |
| Adverse-selection increase | More fills on losers, fewer on winners | Informed flow front-running |
| Quote anticipation | NBBO moves against you between signal and fill | Faster participants reacting |
| Factor correlation | Strategy returns correlate with published microstructure factors | Academic / industry crowding |
| Entry-timing compression | Profitable window shrinks | Competing execution at same entry |
| Execution-shortfall growth | Implementation shortfall ↑ while signal alpha stable | Speed disadvantage |

Crowding is confirmed when **signal quality (pre-cost) remains stable
but post-execution alpha erodes**. If signal quality itself degrades,
the mechanism may be structurally exhausted rather than crowded.

### Latency Disadvantage Emergence

If alpha becomes latency-dependent when previously latency-insensitive,
the edge has migrated to a speed game. **Structural disqualification
for L1-latency infrastructure**.

| Metric | Baseline | Alert |
|--------|----------|-------|
| Signal-to-fill alpha decay curve | calibrated at deployment | Slope steepening > 2× baseline |
| Latency-stratified PnL | binned by fill latency | Profitable only in fastest quintile |
| Market move during order flight | NBBO displacement submit→fill | Systematic adverse displacement |
| Queue-position deterioration | Inferred queue position at fill | Consistently back-of-queue |
| Cancel-replace race losses | Modify attempts filled stale | Increasing modification failures |

---

## 4. Trigger: Intervention Protocol

### Strategy Quarantine

Forensic findings emit `QuarantineTriggerEvidence` → invoke
`AlphaLifecycle.quarantine(structured_evidence=[ev])`. This path is
**fail-safe**: even if the validator flags the trigger as
spurious-looking, the demotion always commits (Inv-11).

| Trigger threshold (default) | Field |
|-----------------------------|-------|
| 10 net-alpha-negative days | `net_alpha_negative_days` |
| Hit-rate residual ≤ −15 pp | `hit_rate_residual_pp` |
| 2+ microstructure metrics breached | `microstructure_metrics_breached` |
| 3+ crowding symptoms | `crowding_symptoms` |
| PnL compression < 0.3 over 5 days | `pnl_compression_ratio_5d` |

`validate_quarantine_trigger` does **not** gate the demotion; instead
it flags spurious-looking triggers (no documented threshold crossed)
so operators can investigate false positives.

Quarantine protocol:

1. Cancel all open orders for the strategy
2. Flatten positions (orderly, not market-panic)
3. Continue signal generation for paper comparison (logged via
   `OrderRequest` → simulated routing in QUARANTINED state)
4. Log all would-be trades for post-quarantine comparison
5. **No automatic un-quarantine** — requires explicit revalidation

### Risk Scaling Reduction (Pre-Quarantine)

Gradual capital reduction without full quarantine:

| Condition | Scaling |
|-----------|---------|
| 1 decay metric at alert level | 75% allocation |
| 2 decay metrics at alert level | 50% allocation |
| 3+ decay metrics at alert level | 25% allocation |
| Slippage + hit-rate + fill-rate all degraded | Quarantine (triple failure) |

Scaling changes:
- Applied at next rebalance window (not mid-trade)
- Logged with full forensic context
- Reversible only when metrics return to baseline for ≥ 5 trading days

### Hypothesis Revalidation (Quarantine Exit)

When forensic evidence challenges the original hypothesis, trigger a
structured re-evaluation that produces `RevalidationEvidence`:

| Trigger | Required analysis |
|---------|-------------------|
| Alpha-source shift (time-of-day, regime) | Re-run research protocol; compare to original |
| Microstructure-mechanism change | Re-derive signal from first principles on current market structure |
| Parameter drift > 2σ | Re-optimize on walk-forward window |
| Crowding confirmed | Assess differentiation possibility; if not, retire |
| Cost-structure change | Re-evaluate minimum alpha threshold |

Revalidation follows the research protocol from microstructure-alpha:
re-state hypothesis → re-define features → OOS validation on
post-deployment data → updated tx-cost / fill assumptions → updated
falsification criteria. If hypothesis survives: re-deploy with
updated parameters via `revalidate_to_paper(structured_evidence=[ev])`.
If it fails: retire (`QUARANTINED_TO_DECOMMISSIONED`); preserve
forensic record.

`RevalidationEvidence` requires `human_signoff` (non-empty
identifier) — automatic re-promotion is forbidden.

---

## Forensic Reporting

### Per-Strategy Health Report

Generated daily and on-demand:

```
{
  "strategy_id": str,
  "report_date": date,
  "deployment_age_days": int,
  "current_lifecycle_state": "RESEARCH" | "PAPER" | "LIVE" | "QUARANTINED" | "DECOMMISSIONED",
  "current_capital_tier": "SMALL_CAPITAL" | "SCALED" | null,
  "health_status": "healthy" | "warning" | "degraded" | "quarantined",
  "compare": { ... per Compare section },
  "monitor": { ... per Monitor section },
  "detect": { ... per Detect section },
  "multi_horizon": {
    "by_horizon":  { horizon_seconds: realized_pnl },
    "by_mechanism": { TrendMechanism: realized_pnl },
    "by_regime":   { regime_name: realized_pnl }
  },
  "trigger": {
    "active_interventions": [],
    "scaling_level": float,
    "quarantine_status": bool,
    "revalidation_pending": bool
  }
}
```

### Decay Timeline

Maintain a longitudinal record per strategy: alpha curve from
deployment to present, cost-structure evolution, regime distribution
over time, crowding-indicator trajectory, intervention history.
Primary artifact for strategy lifecycle decisions (scale, maintain,
reduce, retire).

---

## Data Sources

| Source | Type | Location |
|--------|------|----------|
| Trade lifecycle | `TradeRecord` | `storage/trade_journal.py` — `TradeJournal.query()` |
| Position changes | `PositionUpdate` | `core/events.py` — bus at M9 |
| Execution acks | `OrderAck` with `OrderAckStatus` | `core/events.py` |
| Risk decisions | `RiskVerdict` with `RiskAction` | `core/events.py` — bus at M5 / M6 |
| State changes | `StateTransition` | `core/events.py` — SM audit trail |
| Mechanism lineage | `Signal.trend_mechanism` + `SizedPositionIntent.mechanism_breakdown` | `core/events.py` |
| Hazard exits | `OrderRequest.reason ∈ {HAZARD_SPIKE, HARD_EXIT_AGE}` | `core/events.py` |
| Promotion history | `PromotionLedger` (read-only) | `alpha/promotion_ledger.py` |

`TradeRecord` carries the full decision chain
(`order_id`, `symbol`, `strategy_id`, `side`, `signal_timestamp_ns`,
`submit_timestamp_ns`, `fill_timestamp_ns`, `slippage_bps`, `fees`,
`realized_pnl`, `correlation_id`) — linking each trade to the signal
that caused it.

---

## Event Interface

Forensic findings are delivered via `Alert` events (`core/events.py`)
with `AlertSeverity` levels. `AlertManager` routes by severity.

The following forensic-specific events are NOT YET IMPLEMENTED. When
built they must extend `Event` to inherit `timestamp_ns`,
`correlation_id`, and `sequence`:

| Future event | Payload |
|-------|---------|
| `FORENSIC_ALERT` | strategy_id, metric, category, current, threshold, severity |
| `DECAY_DETECTED` | strategy_id, decay_type, evidence, confidence, recommended action |
| `QUARANTINE_INITIATED` | strategy_id, trigger reasons, positions flattened, paper-mode active |
| `QUARANTINE_LIFTED` | strategy_id, revalidation evidence, new parameters |
| `SCALING_ADJUSTED` | strategy_id, old level, new level, triggering metrics |
| `REVALIDATION_REQUESTED` | strategy_id, trigger, original hypothesis, required analysis |
| `HEALTH_REPORT` | strategy_id, full report payload |
| `STRATEGY_RETIRED` | strategy_id, retirement reason, forensic record id |

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Stale forensic data | Trade count below minimum per window | Use wider window; flag low-sample alert |
| Backtest baseline outdated | Calibration date > max age | Force recalibration before next assessment |
| False-positive decay | Single-metric spike without corroboration | Require 2+ corroborating metrics for escalation |
| False negative | Post-mortem reveals undetected degradation | Add detection rule; tighten thresholds |
| Engine unavailable | Heartbeat | Continue trading with last-known health; alert ops |
| Regime classifier disagreement | Forensic vs risk-engine labels diverge | Use more conservative classification; alert |
| Promotion-ledger schema mismatch | `LEDGER_SCHEMA_VERSION` | Bail out; do not silently degrade |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Live Execution | `OrderAck` for fill analysis; `MetricEvent` for latency |
| Risk Engine | `RiskVerdict` for constraint context; `RiskLevel` SM state; `OrderRequest.reason` for lineage |
| Backtest Engine | `TradeRecord` baselines via `TradeJournal.query()` |
| Microstructure Alpha | `Signal.trend_mechanism` + `expected_half_life_seconds` for per-mechanism attribution; hypothesis revalidation |
| Composition Layer | `SizedPositionIntent.mechanism_breakdown` for crowding diagnostics |
| Regime Detection | `RegimeState` + `RegimeHazardSpike` for hazard-attribution and regime-stability audit |
| Testing & Validation | Sim-vs-live divergence metrics; `QuarantineTriggerEvidence` schema |
| Data Engineering | `EventLog.replay()` for historical analysis |
| Alpha Lifecycle | `AlphaLifecycle.quarantine` auto-trigger; `revalidate_to_paper` evidence |

The forensic layer sits downstream of execution and upstream of
strategy lifecycle decisions. It is forensic-only — never on the
per-tick critical path.
