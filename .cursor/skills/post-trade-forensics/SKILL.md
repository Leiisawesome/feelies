---
name: post-trade-forensics
description: >
  Post-trade forensics and structural edge decay detection for intraday
  strategies. Compares expected vs realized slippage, hit rate, and net alpha.
  Monitors parameter drift, regime dependency stability, and fill rate
  deterioration. Detects microstructure regime change, edge crowding, and
  latency disadvantage emergence. Triggers strategy quarantine, risk scaling
  reduction, and hypothesis revalidation. Use when analyzing post-trade
  performance, diagnosing alpha decay, investigating execution degradation,
  auditing strategy health, or reasoning about edge longevity, crowding
  dynamics, or structural regime shifts.
---

# Post-Trade Forensics & Edge Decay Analyst

No strategy runs on autopilot. This layer continuously validates that the
structural edge a strategy exploits still exists, still converts to PnL
after costs, and has not been arbitraged away or rendered obsolete by
microstructure regime change. Every deployed strategy is guilty of decay
until proven otherwise.

## Core Invariants

1. **No autopilot** — every strategy under continuous forensic audit; silence is not health
2. **Expected vs realized** — all metrics compared against backtest/model predictions, not absolute thresholds alone
3. **Decay is the default** — edges erode; the burden of proof is on continued viability
4. **Evidence before intervention** — quarantine and scaling decisions backed by statistical tests, not intuition
5. **Feedback loop closure** — forensic findings feed back into backtest calibration, fill models, and research hypotheses

---

## 1. Compare: Expected vs Realized

Continuous comparison of live execution outcomes against backtest model
predictions. Divergence is the primary decay signal.

### Slippage Comparison

**Ownership boundary**: The live-execution skill monitors slippage in
real-time (rolling 20-trade windows) and triggers immediate safety responses
(throttle, circuit breaker). This skill performs deeper forensic analysis
over longer windows (50–200 trades), detects structural trends, and
determines whether slippage drift indicates edge decay vs. transient
execution degradation. The same distinction applies to fill rate monitoring.

```
expected_slippage = backtest_slippage_model(size, spread, volatility)
realized_slippage = fill_price - reference_price_at_signal_time
slippage_residual = realized_slippage - expected_slippage
```

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Mean slippage residual | Rolling 50 trades | > 1.5 bps | Investigate fill model calibration |
| Mean slippage residual | Rolling 200 trades | > 2.5 bps | Recalibrate fill model; reduce sizing |
| Slippage residual trend | 5-day OLS slope | Positive slope, p < 0.05 | Structural cost increase; re-evaluate edge |
| Slippage asymmetry | Entry vs exit split | Systematic one-side bias | Adverse selection investigation |
| Slippage by spread regime | Stratified by tight/normal/wide | Regime-dependent degradation | Update regime-conditional cost model |

### Hit Rate Comparison

```
expected_hit_rate = backtest_hit_rate(regime, signal_type, spread_bucket)
realized_hit_rate = winning_trades / total_trades  (rolling window)
hit_rate_residual = realized_hit_rate - expected_hit_rate
```

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Hit rate residual | Rolling 100 trades | < -5pp | Warning; log |
| Hit rate residual | Rolling 100 trades | < -10pp | Reduce allocation 50% |
| Hit rate trend | 5-day OLS slope | Negative slope, p < 0.05 | Edge decay investigation |
| Hit rate by regime | Stratified by vol/spread regime | Regime-specific collapse | Regime dependency audit |
| Win/loss asymmetry shift | Avg win / avg loss ratio drift | > 20% relative change | Payoff structure degradation |

### Alpha Before/After Costs

```
gross_alpha   = raw_return - benchmark_return
net_alpha     = gross_alpha - transaction_costs - slippage - market_impact
alpha_erosion = gross_alpha_backtest - net_alpha_live
```

| Metric | Condition | Action |
|--------|-----------|--------|
| Net alpha (rolling 5 days) | < 0 after costs | Warning; begin decay investigation |
| Net alpha (rolling 10 days) | < 0 after costs | Quarantine evaluation |
| Gross-to-net conversion ratio | < 0.5 (live) vs backtest ratio | Cost model recalibration |
| Alpha half-life | Decreasing across successive deployment periods | Structural decay confirmed |
| Alpha by time-of-day | Concentration in narrowing windows | Edge fragility increasing |

---

## 2. Monitor: Ongoing Health Surveillance

Continuous tracking of strategy internals for drift from calibrated baselines.

### Parameter Drift

Track stability of optimized parameters relative to their calibration window.

| Parameter Class | Detection Method | Threshold |
|-----------------|-----------------|-----------|
| Signal coefficients | Rolling re-estimation vs deployed values | > 2 sigma shift from calibration mean |
| Optimal holding period | Rolling exit-timing analysis | > 30% change from calibrated value |
| Entry threshold | Rolling ROC curve, optimal cutoff drift | AUC degradation > 5% |
| Position sizing scalar | Realized vol vs assumed vol divergence | > 25% persistent divergence |
| Cost model parameters | Realized vs modeled cost distribution | KS test p < 0.05 |

Parameter drift detection protocol:
1. Re-estimate parameters on rolling forward window (no look-ahead)
2. Compare to deployed (frozen) parameter values
3. If drift exceeds threshold, flag for revalidation
4. Do **not** auto-update parameters — drift may indicate edge loss, not recalibration need

### Regime Dependency Stability

**Ownership boundary**: The risk-engine skill owns real-time regime detection
and immediate risk responses to transitions. This skill audits whether
regime classifications remain accurate over time and whether alpha is
concentrated in, or collapsing across, regimes.

Verify that the strategy's performance is not collapsing into a single
regime or losing effectiveness as regimes transition.

| Check | Method | Failure Condition |
|-------|--------|-------------------|
| Cross-regime alpha | Stratify PnL by spread/vol/liquidity regime | Alpha concentrated in < 1 regime (was distributed) |
| Regime transition PnL | Measure PnL during regime transitions | Systematic losses on transitions (model lag) |
| Regime dwell time sensitivity | Compare PnL in short vs long regime episodes | Strategy requires unrealistic regime persistence |
| Regime frequency shift | Track regime transition rate vs historical | Transition rate change > 50% (market structure shift) |
| Regime misclassification rate | Compare predicted vs realized regime labels | Classification error > 20% |

### Fill Rate Deterioration

```
expected_fill_rate = fill_model.predicted_rate(order_type, spread_regime, queue_model)
realized_fill_rate = fills / submissions  (rolling window, by order type)
fill_rate_drift    = realized_fill_rate - expected_fill_rate
```

| Metric | Window | Alert | Escalation |
|--------|--------|-------|------------|
| Passive fill rate drift | Rolling 200 orders | > -10% relative | Warning; log |
| Passive fill rate drift | Rolling 200 orders | > -20% relative | Shift to more aggressive order types |
| Aggressive fill rate drift | Rolling 200 orders | > -5% relative | Broker/venue investigation |
| Fill rate by time-of-day | Hourly buckets | Systematic degradation in key windows | Edge timing shift |
| Partial fill rate increase | Rolling 200 orders | > 30% relative increase | Liquidity withdrawal detection |

---

## 3. Detect: Structural Change Identification

Identify environmental shifts that threaten edge viability at a
structural level — beyond parameter drift.

### Microstructure Regime Change

Detect shifts in market microstructure that invalidate strategy assumptions.

| Signal | Observable | Detection |
|--------|-----------|-----------|
| Spread regime shift | Median quoted spread (rolling 5 days) | > 30% change from calibration period |
| Quote update frequency change | Quotes per second distribution | KS test p < 0.01 vs calibration |
| Trade size distribution shift | Mean/median trade size | > 25% persistent change |
| Tick-to-trade ratio change | Quotes per trade | > 30% change from calibration |
| Venue composition shift | Proportion of trades by exchange | Herfindahl index change > 0.1 |
| Intraday volume profile shift | Volume-by-minute curve | Correlation with historical profile < 0.8 |

Microstructure change is the most dangerous decay vector because it
invalidates the causal mechanism, not just the parameters.

### Edge Crowding Symptoms

Detect when the same structural edge is being exploited by competing
participants, compressing returns.

| Symptom | Observable | Interpretation |
|---------|-----------|----------------|
| Alpha decay with stable signal quality | Hit rate stable but profit-per-trade declining | Others trading same pattern; capturing spread faster |
| Adverse selection increase | More fills on losing trades; fewer on winning | Informed flow front-running your entry |
| Quote anticipation | NBBO moves against you between signal and fill more frequently | Faster participants reacting to same signal |
| Correlation with known factors | Strategy returns correlating with published microstructure factors | Academic/industry crowding |
| Entry timing compression | Profitable window after signal shrinking | Competing execution at same entry point |
| Execution shortfall growth | Implementation shortfall increasing while signal alpha stable | Speed disadvantage relative to crowd |

Crowding is confirmed when signal quality (pre-cost) remains stable but
post-execution alpha erodes. If signal quality itself degrades, the
mechanism may be structurally exhausted rather than crowded.

### Latency Disadvantage Emergence

Detect when execution latency moves from irrelevant to alpha-destructive.

| Metric | Baseline | Alert |
|--------|----------|-------|
| Signal-to-fill alpha decay curve | Alpha(t) function calibrated at deployment | Slope steepening > 2x baseline |
| Latency-stratified PnL | PnL binned by fill latency | Profitable only in fastest quintile |
| Market move during order flight | NBBO displacement between submit and fill | Systematic adverse displacement |
| Queue position deterioration | Inferred queue position at fill time | Consistently back-of-queue |
| Cancel-replace race losses | Modify attempts filled at stale price | Increasing rate of modification failures |

If alpha becomes latency-dependent when it was previously
latency-insensitive, the edge has migrated to a speed game.
This is a structural disqualification for L1-latency infrastructure.

---

## 4. Trigger: Intervention Protocol

Forensic findings feed into concrete interventions. No finding is
informational-only — each maps to an action with defined thresholds.

### Strategy Quarantine

Temporary removal from live capital. The strategy continues to receive
signals and generate paper trades for comparison but executes no real orders.

| Trigger | Evidence Required | Duration |
|---------|-------------------|----------|
| Net alpha < 0 for 10 consecutive trading days | PnL attribution showing cost > gross alpha | Until root cause identified and remediated |
| Hit rate collapse (< -15pp from expected) | Statistical significance, p < 0.01 | Until hit rate recovers on paper or hypothesis updated |
| Structural microstructure change detected | 2+ microstructure metrics past alert threshold | Until strategy re-validated on new regime data |
| Edge crowding confirmed | Crowding scorecard (3+ symptoms present) | Until differentiation re-established or strategy retired |
| Unexplained PnL divergence (live vs paper) | PnL compression ratio < 0.3 for 5 days | Until execution path audited and divergence explained |

Quarantine protocol:
1. Cancel all open orders for the strategy
2. Flatten positions (orderly, not market-panic)
3. Continue signal generation and paper execution
4. Log all would-be trades for post-quarantine comparison
5. No automatic un-quarantine — requires explicit revalidation

### Risk Scaling Reduction

Gradual reduction of capital allocation without full quarantine.

| Condition | Scaling Action |
|-----------|---------------|
| 1 decay metric at alert level | Reduce to 75% allocation |
| 2 decay metrics at alert level | Reduce to 50% allocation |
| 3+ decay metrics at alert level | Reduce to 25% allocation |
| Any metric at escalation level | Reduce to 25% or quarantine |
| Slippage + hit rate + fill rate all degraded | Quarantine (triple failure) |

Scaling changes are:
- Applied at next rebalance window (not mid-trade)
- Logged with full forensic context
- Reversible only when metrics return to baseline for sustained period (minimum 5 trading days)
- Communicated to risk engine via capital allocation adjustment

### Hypothesis Revalidation

When forensic evidence challenges the original strategy hypothesis,
trigger a structured re-evaluation.

| Revalidation Trigger | Required Analysis |
|----------------------|-------------------|
| Alpha source shift (time-of-day, regime) | Re-run research protocol on recent data; compare to original |
| Microstructure mechanism change | Re-derive signal from first principles on current market structure |
| Parameter drift beyond 2-sigma | Re-optimize on walk-forward window; compare to deployed params |
| Crowding confirmed | Assess whether differentiation possible; if not, retire |
| Cost structure change | Re-evaluate minimum alpha threshold; sensitivity analysis |

Revalidation follows the research protocol from microstructure-alpha:
1. Re-state the hypothesis with current market structure assumptions
2. Re-define features and measurable quantities
3. Run out-of-sample validation on post-deployment data
4. Apply updated transaction cost and fill assumptions
5. Define updated failure criteria
6. If hypothesis survives: re-deploy with updated parameters
7. If hypothesis fails: retire strategy; preserve forensic record

---

## Forensic Reporting

### Per-Strategy Health Report

Generated daily and on-demand. Contains:

```
{
  "strategy_id": str,
  "report_date": date,
  "deployment_age_days": int,
  "health_status": "healthy" | "warning" | "degraded" | "quarantined",
  "compare": {
    "slippage": { expected, realized, residual, trend, p_value },
    "hit_rate": { expected, realized, residual, trend, p_value },
    "alpha": { gross, net, conversion_ratio, half_life_estimate }
  },
  "monitor": {
    "parameter_drift": { param: { deployed, current, sigma_shift } },
    "regime_stability": { regime: alpha_contribution },
    "fill_rate": { expected, realized, drift, by_order_type }
  },
  "detect": {
    "microstructure_change": { metric: { baseline, current, alert_level } },
    "crowding_score": { symptom_count, symptoms_present[], confidence },
    "latency_disadvantage": { alpha_decay_slope, latency_pnl_correlation }
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

Maintain a longitudinal record of edge quality for each strategy:
- Alpha curve from deployment through present
- Cost structure evolution
- Regime distribution over time
- Crowding indicator trajectory
- Intervention history with outcomes

This timeline is the primary artifact for strategy lifecycle decisions
(scale, maintain, reduce, retire).

---

## Event Interface

| Event | Payload |
|-------|---------|
| `FORENSIC_ALERT` | strategy_id, metric, category, current_value, threshold, severity |
| `DECAY_DETECTED` | strategy_id, decay_type, evidence, confidence, recommended_action |
| `QUARANTINE_INITIATED` | strategy_id, trigger_reasons[], positions_flattened, paper_mode_active |
| `QUARANTINE_LIFTED` | strategy_id, revalidation_evidence, new_parameters |
| `SCALING_ADJUSTED` | strategy_id, old_level, new_level, triggering_metrics[] |
| `REVALIDATION_REQUESTED` | strategy_id, trigger, original_hypothesis, required_analysis[] |
| `HEALTH_REPORT` | strategy_id, full_report_payload |
| `STRATEGY_RETIRED` | strategy_id, retirement_reason, forensic_record_id |

Every event carries a timestamp from the injectable clock.

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Stale forensic data (no new trades) | Trade count below minimum per window | Use wider window; flag low-sample alert |
| Backtest baseline outdated | Calibration date > configured max age | Force recalibration before next assessment |
| False positive decay signal | Single metric spike without supporting evidence | Require 2+ corroborating metrics for escalation |
| False negative (missed decay) | Post-mortem reveals undetected degradation | Add detection rule; tighten thresholds |
| Forensic engine unavailable | Heartbeat monitor | Continue trading with last-known health status; alert ops |
| Regime classifier disagreement | Forensic vs risk engine regime labels diverge | Use more conservative classification; alert |

---

## Integration Points

| Dependency | Interface |
|------------|-----------|
| Live Execution (live-execution skill) | Slippage, latency, fill rate metrics; execution quality stream |
| Risk Engine (risk-engine skill) | Capital allocation adjustments; regime classification; drawdown context |
| Backtest Engine (backtest-engine skill) | Expected baselines for slippage, fill rate, hit rate, PnL |
| Microstructure Alpha (microstructure-alpha skill) | Research protocol for hypothesis revalidation; signal definitions |
| Testing & Validation (testing-validation skill) | Sim-vs-live divergence metrics; promotion/demotion pipeline |
| Data Engineering (data-engineering skill) | Historical NBBO for microstructure change detection |

The forensic layer sits downstream of execution and upstream of strategy
lifecycle decisions. It consumes execution telemetry, compares against
backtest baselines, and emits decay signals that feed into risk scaling
and strategy promotion/demotion decisions.
