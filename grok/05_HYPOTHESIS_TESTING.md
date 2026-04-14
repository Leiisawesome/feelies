# PROMPT 5 — DIRECTED HYPOTHESIS TESTING PIPELINE

## ACTIVATION DIRECTIVE

The Directed Hypothesis Testing Pipeline is now active. This module converts intuition into formal experiments and produces truth, not candidates.

Unlike the Alpha Factory (Prompt 4) which explores search space, this pipeline tests specific hypotheses with full institutional rigor. Every output is a structured research report AND a deployable `.alpha.yaml` file.

---

## PIPELINE (13 STEPS)

```
 1. HYPOTHESIS FORMALIZATION
 2. ENGINEERING SPECIFICATION (in .alpha.yaml format)
 3. DATA ACQUISITION & VALIDATION
 4. FEATURE ENGINEERING (platform-compatible modules)
 5. SIGNAL CONSTRUCTION (evaluate protocol)
 6. EVENT-DRIVEN BACKTEST (parity config)
 7. STATISTICAL VALIDATION (CPCV, DSR, bootstrap, permutation)
 8. REGIME SENSITIVITY (3-state HMM: compression, normal, vol_breakout)
 9. EXECUTION REALISM AUDIT (latency sweep)
10. PORTFOLIO INTEGRATION ASSESSMENT
11. RESEARCH REPORT
12. ARTIFACT STORAGE & REGISTRY UPDATE
13. PARITY EXPORT (feelies-loadable package)
```

---

## STEP 1 — HYPOTHESIS FORMALIZATION

```json
{
  "hypothesis_id": "H_XXX",
  "statement": "Falsifiable claim about a microstructure mechanism",
  "mechanism": "Causal chain: observable → price impact",
  "mathematical_form": "dP(t) = α × feature(t) × dt + σ dW(t)",
  "expected_sign": "+1 or -1",
  "expected_magnitude": "0.5-2.0 bps per trade",
  "holding_period": "10-60 seconds",
  "falsification_criteria": [
    "If OOS Sharpe < 0.8, reject",
    "If latency decay > 40%, reject"
  ],
  "regime_dependency": "Expected: works in compression/normal. Fails in vol_breakout."
}
```

---

## STEP 2 — ENGINEERING SPECIFICATION

The specification IS the `.alpha.yaml` file. Define it completely before touching data.

```yaml
schema_version: "1.0"
alpha_id: h_xxx_mechanism_name
version: "1.0.0"
description: "..."
hypothesis: |
  Full hypothesis statement.
falsification_criteria:
  - "OOS Sharpe < 0.80 net of all fees and latency"
  - "Bootstrap p-value > 0.05"
  - "Latency decay > 40%"
  - "Edge vanishes outside target regime"

symbols:
  - AAPL

parameters:
  entry_threshold:
    type: float
    default: 0.003
    range: [0.001, 0.02]
    description: "Signal level for entry."
  # ... all parameters with type, default, range

risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 10.0

features:
  - feature_id: my_feature
    version: "1.0.0"
    description: "..."
    depends_on: []
    warm_up:
      min_events: 50
    computation_module: my_feature.py    # or inline computation: |

signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      # ... signal logic ...
      return Signal(...) or None
```

---

## STEP 3-5 — DATA, FEATURES, SIGNAL

Use the Data Engine (Prompt 2) to fetch data. Implement feature modules following the protocol (Prompt 1 Section 3). Compile and validate the signal function.

**Pre-flight checklist before backtest:**
- [ ] `initial_state()` returns dict with only JSON-safe types
- [ ] `update(quote, state, params)` takes exactly 3 args, returns float
- [ ] `evaluate(features, params)` takes exactly 2 args
- [ ] No `import` statements in computation or signal code
- [ ] `alpha_id` matches `^[a-z][a-z0-9_]*$`
- [ ] All `feature_id` values are unique
- [ ] `depends_on` references existing feature_ids only

---

## STEP 6 — EVENT-DRIVEN BACKTEST

Run using PARITY backtest parameters (Prompt 1 Section 6):
- Fill: buy at ask, sell at bid
- Fill probability: 0.7 (seeded RNG, seed=42)
- Latency: 100ms
- TC: exchange + SEC + FINRA + impact (beyond spread)

---

## STEP 7 — STATISTICAL VALIDATION

### Full Protocol

1. **CPCV** — 20 folds, purge+embargo, report Sharpe distribution
2. **Walk-forward** — expanding AND rolling windows, compare for parameter instability
3. **DSR** — adjust for skew, kurtosis, and number of trials
4. **Bootstrap** — 5000 samples, 95% CI on mean return
5. **Permutation** — 5000 shuffles, p-value < 0.05
6. **IC analysis** — mean IC, IC t-stat, IC decay curve

### Acceptance

```
DSR > 1.0  AND  bootstrap p < 0.05  AND  permutation p < 0.05
AND  IC t-stat > 2.5  AND  mean IC > 0.03
```

---

## STEP 8 — REGIME SENSITIVITY

Using the 3-state HMM from Prompt 3:

```
State 0: compression_clustering
State 1: normal
State 2: vol_breakout
```

Evaluate per-regime:
- Sharpe, hit rate, profit factor per state
- Stability: all_positive, CV < 1.5
- Worst regime Sharpe > -0.5

---

## STEP 9 — EXECUTION REALISM AUDIT

### Latency Sensitivity

Run backtest at 0ms, 50ms, 100ms, 200ms, 500ms:

```
Decay = 1 - (Sharpe_200ms / Sharpe_0ms)
PASS if decay < 40%
```

### TC Sensitivity

Run at 1.0×, 1.5×, 2.0× cost multiplier:
- Find breakeven TC multiplier
- PASS if breakeven > 1.5×

### Capacity Estimate

```
Max AUM = ADV × participation_rate_ceiling × avg_price
participation_rate_ceiling = 0.05  (5% of ADV)
```

---

## STEP 10 — PORTFOLIO INTEGRATION

If existing signals are registered:
- Correlation check: max pairwise |ρ| < 0.5
- Incremental IC > 0.01
- Factor exposure: |β_market| < 0.05 after neutralization

---

## STEP 11 — RESEARCH REPORT

```json
{
  "1_hypothesis": { "statement": "...", "mechanism": "..." },
  "2_design": { "alpha_id": "...", "features": [...], "parameters": {...} },
  "3_results": {
    "train": { "sharpe": ..., "trades": ... },
    "validation": { "sharpe": ..., "trades": ... },
    "oos": { "sharpe": ..., "trades": ... }
  },
  "4_validation": { "dsr": ..., "bootstrap_p": ..., "permutation_p": ..., "ic": ... },
  "5_regimes": { "per_state": {...}, "stability": {...} },
  "6_execution": { "latency_decay": ..., "tc_breakeven": ..., "capacity": ... },
  "7_portfolio": { "correlations": {...}, "incremental_ic": ... },
  "8_failure_modes": { "regime_kill": "...", "tc_kill_at": ..., "structural_risks": [...] },
  "9_recommendation": "DEPLOY | VALIDATE | MUTATE | REJECT | ARCHIVE"
}
```

### Recommendation Framework

| Status | Criteria |
|--------|---------|
| DEPLOY | DSR > 1.5, all regimes positive, latency decay < 20% |
| VALIDATE | DSR > 1.0, most regimes positive, decay < 40% |
| MUTATE | Shows promise but fails one criterion |
| REJECT | Fails multiple criteria |
| ARCHIVE | Interesting mechanism but not tradeable |

---

## STEP 12 — ARTIFACT STORAGE

```
/home/user/experiments/{experiment_id}/
├── research_report.json
├── {alpha_id}.alpha.yaml        # Deployable spec
├── *.py                          # Feature modules
├── metrics.csv
├── trades.csv
├── regime_analysis.json
├── falsification_report.json
└── parity_fingerprint.json
```

Update signal registry with all metrics.

---

## STEP 13 — PARITY EXPORT (NEW)

For signals with status VALIDATE or DEPLOY, produce a parity export:

```python
def compute_parity_fingerprint(trade_log, metrics):
    pnl_sequence = [round(t["net_pnl"], 8) for t in trade_log]
    pnl_hash = hashlib.sha256(json.dumps(pnl_sequence).encode()).hexdigest()[:16]
    return {
        "n_trades": len(trade_log),
        "total_pnl": round(metrics["total_pnl"], 6),
        "sharpe": round(metrics["sharpe"], 6),
        "hit_rate": round(metrics["hit_rate"], 6),
        "pnl_hash": pnl_hash,
        "first_trade_entry_ns": trade_log[0]["entry_time"] if trade_log else None,
        "last_trade_exit_ns": trade_log[-1]["exit_time"] if trade_log else None,
        "config_hash": PARITY_CONFIG_HASH,
        "generated_in": "grok_repl",
    }
```

The export package:

```
alpha_export/
├── {alpha_id}.alpha.yaml          # Copy directly to feelies alphas/{alpha_id}/ directory
├── *.py                            # Feature modules (MUST be in same dir as yaml)
├── parity_fingerprint.json         # For local verification
├── parity_config.json              # Locked backtest parameters
└── regime_calibration.json         # Calibrated HMM emission params (if regime-gated)
```

**Copy-paste workflow (nested directory layout required):**
```
Grok: alpha_export/{alpha_id}.alpha.yaml  →  feelies: alphas/{alpha_id}/{alpha_id}.alpha.yaml
Grok: alpha_export/*.py                   →  feelies: alphas/{alpha_id}/*.py
# The .py files MUST be in the same directory as the .alpha.yaml
# because computation_module paths resolve relative to the yaml file.
```

---

## HYPOTHESIS TESTING STATUS

```
Hypothesis Testing Pipeline: ACTIVE
Steps: 1-13 (including parity export)
Output format: .alpha.yaml + research_report.json + parity_fingerprint.json
Backtest: PARITY mode (spread-crossing, 70% fill, 100ms latency)
Validation: CPCV + DSR + bootstrap + permutation + IC
Regime: 3-state HMM (compression_clustering, normal, vol_breakout)
```

Awaiting Portfolio, Risk & Archive activation (Prompt 6).
