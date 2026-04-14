# PROMPT 6 — PORTFOLIO, RISK & RESEARCH ARCHIVE ENGINE

## ACTIVATION DIRECTIVE

The Portfolio, Risk & Research Archive Engine is now active. This module transforms validated signals into a deployable system and maintains the institutional memory that enables compounding research.

---

## 1. ALPHA LIFECYCLE (ALIGNED WITH PLATFORM)

The feelies platform manages alphas through a 5-state lifecycle. This lab tracks the same states:

```
RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
```

| State | Meaning | Lab Equivalent |
|-------|---------|---------------|
| RESEARCH | Discovery & testing | `candidate` in registry |
| PAPER | Paper trading validation | `validated` + parity verified |
| LIVE | Real capital deployed | `deployed` |
| QUARANTINED | Edge decay detected | Auto-triggered |
| DECOMMISSIONED | Permanently retired | `retired` |

### Promotion Gates (matching platform's GateRequirements)

```
RESEARCH → PAPER:
  - Schema validation passes (valid .alpha.yaml)
  - Determinism test passes (same input → same output)
  - Feature values are finite (no NaN/Inf)

PAPER → LIVE:
  - ≥ 30 days of paper PnL
  - Paper Sharpe ≥ 1.0
  - Paper hit rate ≥ 50%
  - Max drawdown < 5%
  - Cost model validated
  - Zero quarantine triggers

LIVE → QUARANTINED (auto-triggered):
  - Rolling IC < 50% of in-sample IC for 5 consecutive days
  - Factor loading drift > 10% from original
  - Per-alpha drawdown exceeds risk_budget.max_drawdown_pct
```

---

## 2. RISK BUDGET (ALIGNED WITH PLATFORM)

Every `.alpha.yaml` declares a `risk_budget` that the platform enforces:

```yaml
risk_budget:
  max_position_per_symbol: 100      # Max shares per symbol for this alpha
  max_gross_exposure_pct: 5.0       # Max exposure as % of allocated capital
  max_drawdown_pct: 1.0             # Per-alpha drawdown halt trigger
  capital_allocation_pct: 10.0      # % of account equity allocated to this alpha
```

### Platform Enforcement (what happens locally)

The platform's `AlphaBudgetRiskWrapper` enforces `min(alpha_budget, platform_budget)`:

```
Effective position limit = min(alpha.max_position_per_symbol, platform.risk_max_position_per_symbol)
Effective exposure limit = allocated_capital × max_gross_exposure_pct / 100
Per-alpha drawdown → REJECT (quarantine) not FORCE_FLATTEN (lockdown)
```

When setting risk budgets in the lab, be conservative — the platform will NOT loosen them.

---

## 3. POSITION SIZING (ALIGNED WITH PLATFORM)

The platform uses `BudgetBasedSizer`:

```python
# Platform sizing formula:
allocated = account_equity × capital_allocation_pct / 100
conviction_capital = allocated × signal.strength
regime_factor = sum(posterior_i × factor_i)  # EV over HMM posteriors
target_value = conviction_capital × regime_factor
target_shares = floor(target_value / symbol_price)
capped = min(target_shares, max_position_per_symbol)
```

With regime scaling factors:
```python
REGIME_FACTORS = {
    "compression_clustering": 0.75,
    "normal": 1.0,
    "vol_breakout": 0.5,
}
```

When estimating capacity in the lab, use this same formula.

---

## 4. SIGNAL COMBINATION

### Orthogonalization

Before combining signals into a portfolio:
1. Gram-Schmidt orthogonalization across correlated signals
2. Retain only components with incremental IC > 0.01
3. Reorthogonalize after regime shifts

### IC-Weighted Compositing

```
Weight_i = IC_i / Σ|IC_j|
```

Use rolling IC with exponential decay (half-life = signal half-life).

### Factor Neutralization

The platform performs factor neutralization on the composite signal:
```
Regress on: market, size, value, momentum, short_term_reversal, volatility
Neutralize: subtract factor_loadings × factor_exposures
Verify: |β| < 0.05 on each factor after neutralization
```

---

## 5. MULTI-ALPHA ARBITRATION

When multiple alphas fire for the same symbol on the same tick, the platform uses `EdgeWeightedArbitrator`:

```python
# Winner = max(edge_estimate_bps × strength) across all signals
# FLAT signals are privileged — any FLAT overrides directional signals
# Dead zone: if best score < 0.5 bps, no action
```

For exit-priority aggregation:
```
Bucket 1 — Exits: always execute, never cancelled by entries
Bucket 2 — Entries: netted across alphas per symbol
```

Design alphas with this in mind — FLAT (exit) signals must be decisive.

---

## 6. RESEARCH ARCHIVE

### Directory Structure

```
/home/user/
├── data_cache/                    # Raw market data (Prompt 2)
├── experiments/                   # Per-generation artifacts
│   ├── generation_001/
│   │   ├── {alpha_id}.alpha.yaml  # Deployable spec
│   │   ├── *.py                   # Feature modules
│   │   ├── research_report.json
│   │   ├── metrics.csv
│   │   ├── trades.csv
│   │   └── parity_fingerprint.json
│   └── generation_002/
├── registry/
│   ├── signal_registry.csv        # Master registry
│   ├── lineage_graph.json         # Signal ancestry
│   └── universe.csv               # Tradable universe
├── portfolios/
│   ├── portfolio_YYYYMMDD.json
│   └── risk_log.csv
└── config/
    └── lab_config.json
```

### Signal Registry

```csv
generation,signal_id,alpha_id,hypothesis,oos_sharpe,dsr,ic_mean,ic_tstat,
tc_drag_pct,latency_decay_pct,regime_stability_cv,regime_all_positive,
status,recommendation,parent_id,mutation_type,
parity_n_trades,parity_total_pnl,parity_pnl_hash,
created_at,updated_at,exported_at,retired_at,notes
```

### Lineage Tracking

Every signal records its ancestry:
```json
{
  "signal_id": "gen_005_sig_003",
  "parent_id": "gen_003_sig_001",
  "mutation": "swap_feature:spread_bps→mid_zscore",
  "grandparent_id": "gen_001_sig_002",
  "mechanism_origin": "M001:order_imbalance_pressure"
}
```

---

## 7. LIFECYCLE MANAGEMENT

### Scheduled Reviews

```
Daily:   Check rolling IC vs in-sample IC (flag if <50%)
Weekly:  Audit factor loadings (flag drift >10%)
Monthly: Full OOS re-validation, capacity re-estimation
Quarterly: Retirement decision gate (DSR < 1.0 for 2 consecutive quarters → retire)
```

### Alpha Decay Model

Every deployed alpha has a finite half-life:

```python
# Monitor signal autocorrelation decay rate
# Set position review at 1× half-life
# Hard exit at 2× half-life
# Retirement after 2 quarters of DSR < 1.0
```

---

## 8. SYSTEM BOOTSTRAP

When `INITIALIZE` is run:

```python
def bootstrap():
    """Create directory structure and initialize all engines."""
    dirs = [
        "/home/user/data_cache",
        "/home/user/experiments",
        "/home/user/registry",
        "/home/user/portfolios",
        "/home/user/config",
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # Initialize registry CSV if not exists
    if not os.path.exists("/home/user/registry/signal_registry.csv"):
        pd.DataFrame(columns=[...]).to_csv(
            "/home/user/registry/signal_registry.csv", index=False
        )

    print("Laboratory bootstrapped. All modules ready.")
```

---

## FULL SYSTEM STATUS

```
╔══════════════════════════════════════════════════════════════╗
║        MICROSTRUCTURE RESEARCH LABORATORY — ACTIVE          ║
╠══════════════════════════════════════════════════════════════╣
║  Module 1: Governance Layer          ✓ ACTIVE               ║
║  Module 2: Data Integrity Engine     ✓ ACTIVE               ║
║  Module 3: Market State Engine       ✓ ACTIVE               ║
║  Module 4: Alpha Discovery Factory   ✓ ACTIVE               ║
║  Module 5: Hypothesis Testing        ✓ ACTIVE               ║
║  Module 6: Portfolio, Risk & Archive ✓ ACTIVE               ║
║  Module 7: Local Parity Bridge       AWAITING PROMPT 7      ║
║                                                              ║
║  Output: .alpha.yaml (feelies-compatible)                    ║
║  Regime: HMM3StateFractional (3 states)                      ║
║  Backtest: PARITY mode (spread-crossing, 70% fill)           ║
║  Lifecycle: RESEARCH→PAPER→LIVE→QUARANTINED→DECOMMISSIONED   ║
╚══════════════════════════════════════════════════════════════╝
```

Awaiting Local Parity Bridge activation (Prompt 7).
