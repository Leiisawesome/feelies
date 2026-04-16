# PROMPT 5 — EXPORT & LIFECYCLE: PARITY VERIFICATION, REGISTRY & ARCHIVE

> **Paste this entire file as one block. Wait for `Export & Lifecycle module: ACTIVE`, then call `INITIALIZE("your_api_key")`.**

## ACTIVATION DIRECTIVE

The Export & Lifecycle module is now active. This module:

1. Exports validated alphas as copy-paste-ready packages for the local repo
2. Defines the parity verification contract (Grok hash vs `scripts/run_backtest.py` hash)
3. Manages the signal registry and alpha lifecycle
4. Maintains the research archive

**Prerequisites: Prompts 1–4 must have been executed successfully.**

---

## CELL 1 — EXPORT command

```python
import datetime, csv, json, os, yaml

def EXPORT(
    signal_id: str,
    report: dict,
    spec: dict | str,
    feature_modules: dict[str, str] | None = None,
) -> str:
    """
    Export a validated alpha as a copy-paste-ready package for the feelies repo.

    Produces:
        /home/user/experiments/{experiment_dir}/alpha_export/
            {alpha_id}.alpha.yaml          ← copy to: feelies/alphas/{alpha_id}/{alpha_id}.alpha.yaml
            *.py                            ← copy to: feelies/alphas/{alpha_id}/*.py
            parity_fingerprint.json         ← verification data
            README_deploy.txt               ← step-by-step deployment instructions

    Args:
        signal_id:       Identifier for this signal (e.g. "gen_001_imbalance_drift")
        report:          Research report dict from TEST()
        spec:            .alpha.yaml spec dict or YAML string
        feature_modules: Optional dict of {filename: code_str} for computation_module features

    Returns:
        Path to the alpha_export directory
    """
    if isinstance(spec, str):
        spec_dict = yaml.safe_load(spec)
        spec_yaml = spec
    else:
        spec_dict = spec
        spec_yaml = yaml.dump(spec_dict, default_flow_style=False, sort_keys=False)

    alpha_id = spec_dict.get("alpha_id", signal_id)

    # --- Validation gate: must pass AlphaLoader before export ---
    print(f"[EXPORT] Validating {alpha_id} via AlphaLoader...")
    if not validate_alpha(spec_dict):
        print(f"EXPORT BLOCKED: spec failed AlphaLoader validation. Fix errors before exporting.")
        return ""

    # --- Create export directory ---
    gen = SESSION.get("generation", 1)
    exp_dir    = os.path.join(WORKSPACE["experiments"], f"generation_{gen:03d}_{alpha_id}")
    export_dir = os.path.join(exp_dir, "alpha_export", alpha_id)
    os.makedirs(export_dir, exist_ok=True)

    # --- Write .alpha.yaml ---
    yaml_path = os.path.join(export_dir, f"{alpha_id}.alpha.yaml")
    with open(yaml_path, "w") as f:
        f.write(spec_yaml)
    print(f"  Written: {yaml_path}")

    # --- Write feature module .py files (if any) ---
    for fname, code in (feature_modules or {}).items():
        if not fname.endswith(".py"):
            fname = fname + ".py"
        py_path = os.path.join(export_dir, fname)
        with open(py_path, "w") as f:
            f.write(code)
        print(f"  Written: {py_path}")

    # --- Compute parity fingerprint ---
    oos_pnl_hash = report.get("oos_pnl_hash") or report.get("steps", {}).get("oos", {}).get("pnl_hash")
    oos_metrics  = report.get("steps", {}).get("oos", {})
    config_snap  = None
    if "config_snapshot" in report.get("steps", {}).get("train", {}):
        config_snap = report["steps"]["train"]["config_snapshot"]

    fingerprint = {
        "signal_id":       signal_id,
        "alpha_id":        alpha_id,
        "n_trades":        oos_metrics.get("n"),
        "total_pnl":       oos_metrics.get("mean_pnl"),
        "oos_sharpe":      oos_metrics.get("sharpe"),
        "oos_dsr":         report.get("steps", {}).get("falsification", {}).get("dsr"),
        "pnl_hash":        oos_pnl_hash,
        "hash_function":   "SHA256(JSON([{order_id,symbol,side,quantity,fill_price,realized_pnl}]))",
        "config_snapshot": str(config_snap) if config_snap else None,
        "generated_in":    "grok_repl_v2",
        "generated_at":    datetime.datetime.utcnow().isoformat(),
        "repo_source":     "github.com/Leiisawesome/feelies (ZIP bootstrap)",
        "data_source":     "Polygon REST API (RTH substitution)",
        "parity_contract": (
            "Running same .alpha.yaml on same date range through Grok REPL "
            "and through python scripts/run_backtest.py must produce: "
            "same trade count, same total PnL ±0.01%, same pnl_hash."
        ),
    }

    fp_path = os.path.join(export_dir, "parity_fingerprint.json")
    with open(fp_path, "w") as f:
        json.dump(fingerprint, f, indent=2, default=str)
    print(f"  Written: {fp_path}")

    # --- Write deployment README ---
    readme = _build_readme(alpha_id, export_dir, fingerprint)
    with open(os.path.join(export_dir, "README_deploy.txt"), "w") as f:
        f.write(readme)

    # --- Update signal registry ---
    _registry_upsert(signal_id, alpha_id, report, fingerprint)

    print(f"\nEXPORT COMPLETE: {export_dir}")
    print(f"  Parity hash: {(oos_pnl_hash or 'none')[:16]}...")
    print(f"  Recommendation: {report.get('verdict','?')}")
    print(f"\n  Next step: copy files to local repo and run parity verification.")
    print(f"  See: {export_dir}/README_deploy.txt")
    return export_dir


def _build_readme(alpha_id: str, export_dir: str, fingerprint: dict) -> str:
    return f"""DEPLOYMENT INSTRUCTIONS — {alpha_id}
{'='*60}

Generated: {fingerprint['generated_at']}
Source:    {fingerprint['repo_source']}

STEP 1 — Copy files to local repo
-----------------------------------
mkdir -p feelies/alphas/{alpha_id}/
cp {export_dir}/{alpha_id}.alpha.yaml  feelies/alphas/{alpha_id}/{alpha_id}.alpha.yaml
cp {export_dir}/*.py                    feelies/alphas/{alpha_id}/   (if any)

  NOTE: .py files MUST be in the same directory as the .alpha.yaml
  because computation_module paths resolve relative to the .alpha.yaml.

STEP 2 — Run parity verification locally
------------------------------------------
python scripts/run_backtest.py \\
    --spec alphas/{alpha_id}/{alpha_id}.alpha.yaml \\
    --symbols AAPL \\
    --start <same_start_date> \\
    --end   <same_end_date>   \\
    --api-key $POLYGON_API_KEY

Compute the local parity hash using the same function:
    import hashlib, json
    records = list(orchestrator._trade_journal.query())
    trade_seq = [{{"order_id": str(r.order_id), "symbol": r.symbol,
                   "side": str(r.side).split(".")[-1],
                   "quantity": int(r.filled_quantity),
                   "fill_price": str(r.fill_price),
                   "realized_pnl": str(r.realized_pnl)}}
                 for r in records]
    pnl_hash = hashlib.sha256(json.dumps(trade_seq, sort_keys=True,
               separators=(",",":")).encode()).hexdigest()
    print(pnl_hash)

STEP 3 — Verify parity in Grok
--------------------------------
VERIFY("{alpha_id}", "<local_pnl_hash>")

PARITY CONTRACT
---------------
Grok hash:   {(fingerprint.get('pnl_hash') or 'not_computed')[:32]}
Expected:    same trade count, same total PnL ±0.01%, same pnl_hash
Deviation:   Any divergence is a defect unless caused by Polygon data substitution.

STEP 4 — Promote to paper trading
-----------------------------------
# Add to platform.yaml:
alpha_spec_dir: alphas/{alpha_id}
# Then run: python scripts/run_backtest.py ...
# After 30 days paper: evaluate for LIVE promotion
"""
```

---

## CELL 2 — VERIFY command

```python
def VERIFY(signal_id: str, local_pnl_hash: str) -> bool:
    """
    Compare Grok's parity hash against the hash produced by scripts/run_backtest.py locally.

    Usage:
        VERIFY("my_alpha", "a3f8b2c1d9e04567f2c3d4e5a6b7c8d9...")
    """
    # Look up stored hash from most recent EXPORT
    stored_hash = _registry_get_pnl_hash(signal_id)

    print(f"\nPARITY VERIFICATION: {signal_id}")
    print(f"  Grok hash:  {(stored_hash or 'not found')[:32]}...")
    print(f"  Local hash: {local_pnl_hash[:32]}...")

    if stored_hash is None:
        print(f"  STATUS: NO FINGERPRINT — run EXPORT({signal_id!r}, ...) first")
        return False

    if local_pnl_hash == stored_hash:
        print(f"  STATUS: PARITY VERIFIED ✓")
        print(f"  The Grok REPL and scripts/run_backtest.py produced identical trade sequences.")
        _registry_set_status(signal_id, "parity_verified")
        return True
    else:
        print(f"  STATUS: PARITY FAILED ✗")
        print(f"  Divergence detected. Check:")
        print(f"    1. Same .alpha.yaml file used on both sides?")
        print(f"    2. Same date range?")
        print(f"    3. Same execution_mode (market vs passive_limit)?")
        print(f"    4. Polygon API returning same data on both sides?")
        print(f"    5. Hash function identical? (see README_deploy.txt)")
        print(f"  If divergence is NOT caused by the Polygon substitution, this is a defect.")
        return False


def _registry_get_pnl_hash(signal_id: str) -> str | None:
    """Look up parity hash from registry CSV."""
    if not os.path.exists(REGISTRY_PATH):
        return None
    with open(REGISTRY_PATH, "r") as f:
        for row in csv.DictReader(f):
            if row.get("signal_id") == signal_id:
                return row.get("parity_pnl_hash") or None
    return None


def _registry_set_status(signal_id: str, status: str) -> None:
    """Update status column in registry CSV."""
    if not os.path.exists(REGISTRY_PATH):
        return
    rows = []
    with open(REGISTRY_PATH, "r") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row.get("signal_id") == signal_id:
            row["status"]     = status
            row["updated_at"] = datetime.datetime.utcnow().isoformat()
    with open(REGISTRY_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_COLS)
        w.writeheader()
        w.writerows(rows)

print("EXPORT() and VERIFY() commands: ACTIVE")
```

---

## CELL 3 — Signal registry management

```python
def _registry_upsert(signal_id: str, alpha_id: str, report: dict, fingerprint: dict) -> None:
    """Insert or update a signal in the registry CSV."""
    oos     = report.get("steps", {}).get("oos", {})
    falsif  = report.get("steps", {}).get("falsification", {})
    latency = report.get("steps", {}).get("latency", {})
    regime  = report.get("steps", {}).get("regime", {})

    row = {
        "generation":           SESSION.get("generation", 1),
        "signal_id":            signal_id,
        "alpha_id":             alpha_id,
        "hypothesis":           report.get("hypothesis", {}).get("statement", "")[:120],
        "oos_sharpe":           round(oos.get("sharpe") or 0, 4),
        "dsr":                  round(falsif.get("dsr") or 0, 4),
        "ic_mean":              "",   # populated by IC analysis if available
        "ic_tstat":             "",
        "tc_drag_pct":          "",
        "latency_decay_pct":    round((latency.get("latency_decay") or 0) * 100, 2),
        "regime_stability_cv":  round(regime.get("regime_cv") or 0, 4),
        "regime_all_positive":  regime.get("all_positive", False),
        "status":               "candidate",
        "recommendation":       report.get("verdict", "UNKNOWN"),
        "parent_id":            "",
        "mutation_type":        "",
        "parity_n_trades":      fingerprint.get("n_trades", ""),
        "parity_total_pnl":     round(fingerprint.get("total_pnl") or 0, 6),
        "parity_pnl_hash":      fingerprint.get("pnl_hash", ""),
        "created_at":           datetime.datetime.utcnow().isoformat(),
        "updated_at":           datetime.datetime.utcnow().isoformat(),
        "exported_at":          datetime.datetime.utcnow().isoformat(),
        "retired_at":           "",
        "notes":                "",
    }

    # Read existing rows
    existing = []
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r") as f:
            existing = list(csv.DictReader(f))

    # Update if exists, else append
    updated = False
    for i, r in enumerate(existing):
        if r.get("signal_id") == signal_id:
            existing[i] = {**r, **row}
            updated = True
            break
    if not updated:
        existing.append(row)

    with open(REGISTRY_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_COLS)
        w.writeheader()
        w.writerows(existing)
    print(f"  Registry updated: {signal_id} → {row['recommendation']}")


def REGISTRY() -> None:
    """Display the signal registry."""
    if not os.path.exists(REGISTRY_PATH):
        print("Registry is empty.")
        return
    with open(REGISTRY_PATH, "r") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("Registry is empty.")
        return

    print(f"\n{'Signal Registry':}")
    print(f"{'─'*100}")
    header = f"{'signal_id':25s} {'alpha_id':25s} {'oos_sharpe':>10} {'dsr':>6} {'status':15s} {'verdict':12s}"
    print(header)
    print(f"{'─'*100}")
    for r in rows:
        print(f"{r.get('signal_id',''):25s} {r.get('alpha_id',''):25s} "
              f"{r.get('oos_sharpe',''):>10} {r.get('dsr',''):>6} "
              f"{r.get('status',''):15s} {r.get('recommendation',''):12s}")
    print(f"{'─'*100}")
    print(f"Total: {len(rows)} signals")


def RETIRE(signal_id: str, reason: str = "") -> None:
    """Mark a signal as retired in the registry."""
    _registry_set_status(signal_id, "retired")
    if reason:
        # Append reason to notes
        rows = []
        with open(REGISTRY_PATH, "r") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row.get("signal_id") == signal_id:
                row["retired_at"] = datetime.datetime.utcnow().isoformat()
                row["notes"]      = reason
        with open(REGISTRY_PATH, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=REGISTRY_COLS)
            w.writeheader()
            w.writerows(rows)
    print(f"Retired: {signal_id}  ({reason})")

print("REGISTRY(), RETIRE() commands: ACTIVE")
```

---

## CELL 4 — Alpha lifecycle and decay monitoring

```python
# -------------------------------------------------------------------
# Alpha lifecycle states (aligned with feelies platform)
# -------------------------------------------------------------------
# RESEARCH       → Discovery and testing in this lab
# PAPER          → Paper trading on the platform (≥30 days required)
# LIVE           → Real capital deployed
# QUARANTINED    → Automatic — edge decay, TC drift, or drawdown breach
# DECOMMISSIONED → Permanent retirement

LIFECYCLE_STATES = ["RESEARCH", "PAPER", "LIVE", "QUARANTINED", "DECOMMISSIONED"]

# Promotion gates (must all pass before advancing state)
PROMOTION_GATES = {
    "RESEARCH → PAPER": [
        "AlphaLoader validation passes (schema + compilation)",
        "Determinism test: same event_log → same trade sequence",
        "Feature values finite (no NaN/Inf) over 5-day sample",
        "OOS Sharpe ≥ 0.80",
        "DSR > 1.0",
        "Bootstrap p < 0.05",
    ],
    "PAPER → LIVE": [
        "≥ 30 days of paper PnL on the platform",
        "Paper Sharpe ≥ 1.0",
        "Paper hit rate ≥ 50%",
        "Max paper drawdown < risk_budget.max_drawdown_pct",
        "Zero quarantine triggers during paper period",
        "Cost model validated (TC actual ≤ 1.5× TC estimated)",
    ],
}

# Auto-quarantine triggers (monitored by platform's AlphaBudgetRiskWrapper)
QUARANTINE_TRIGGERS = [
    "Rolling IC < 50% of in-sample IC for 5 consecutive days",
    "Factor loading drift > 10% from original baseline",
    "Per-alpha drawdown exceeds risk_budget.max_drawdown_pct",
    "Latency decay exceeds 40% (post-deployment measurement)",
]


def REPORT(generation: int | None = None) -> None:
    """Generate a research report for a generation or the full registry."""
    if not os.path.exists(REGISTRY_PATH):
        print("No registry found.")
        return
    with open(REGISTRY_PATH, "r") as f:
        rows = list(csv.DictReader(f))

    if generation is not None:
        rows = [r for r in rows if str(r.get("generation", "")) == str(generation)]

    if not rows:
        print(f"No signals found for generation {generation}.")
        return

    passed    = [r for r in rows if r.get("recommendation") in ("DEPLOY", "VALIDATE")]
    rejected  = [r for r in rows if r.get("recommendation") == "REJECT"]
    mutate    = [r for r in rows if r.get("recommendation") == "MUTATE"]
    archived  = [r for r in rows if r.get("recommendation") == "ARCHIVE"]
    verified  = [r for r in rows if r.get("status") == "parity_verified"]

    print(f"\n{'Research Report':}")
    gen_label = f"Generation {generation}" if generation else "All generations"
    print(f"{gen_label} — {len(rows)} signals evaluated")
    print(f"{'─'*60}")
    print(f"  DEPLOY/VALIDATE: {len(passed)}")
    print(f"  MUTATE:          {len(mutate)}")
    print(f"  ARCHIVE:         {len(archived)}")
    print(f"  REJECT:          {len(rejected)}")
    print(f"  Parity verified: {len(verified)}")
    print(f"{'─'*60}")

    if passed:
        print("\nPromising signals:")
        for r in passed:
            print(f"  {r['signal_id']:30s}  Sharpe={r['oos_sharpe']:>7}  "
                  f"DSR={r['dsr']:>6}  {r['recommendation']}")

print("REPORT(), alpha lifecycle state machine: ACTIVE")
```

---

## CELL 5 — STATUS command (full system status)

```python
def STATUS() -> None:
    """Report all module states and current session variables."""
    print(f"\n{'='*60}")
    print("MICROSTRUCTURE RESEARCH LABORATORY V2 — STATUS")
    print(f"{'='*60}")
    print(f"  Module 1 (Bootstrap):         ACTIVE")
    print(f"  Module 2 (Data Ingestion):    ACTIVE")
    print(f"  Module 3 (Alpha Development): ACTIVE")
    print(f"  Module 4 (Backtest Exec):     ACTIVE")
    print(f"  Module 5 (Export/Lifecycle):  ACTIVE")
    print()
    print(f"  API key set:      {'YES' if SESSION.get('api_key') else 'NO — run INITIALIZE()'}")
    print(f"  Loaded symbols:   {SESSION.get('loaded_symbols', [])}")
    print(f"  Loaded dates:     {SESSION.get('loaded_dates', [])}")
    n_events = len(list(SESSION["event_log"].replay())) if SESSION.get("event_log") else 0
    print(f"  Event log:        {n_events} events")
    print(f"  Generation:       {SESSION.get('generation', 0)}")
    print(f"  Active alpha:     {SESSION.get('active_alpha', 'none')}")
    print()

    # Registry summary
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r") as f:
            rows = list(csv.DictReader(f))
        print(f"  Registry:         {len(rows)} signals")
        verified = sum(1 for r in rows if r.get("status") == "parity_verified")
        print(f"  Parity verified:  {verified}")
    else:
        print(f"  Registry:         empty")

    print()
    print(f"  Source:           github.com/Leiisawesome/feelies (ZIP bootstrap)")
    print(f"  Single source:    repo code (no invented fill/cost/risk)")
    print(f"  Allowed deviation: MassiveHistoricalIngestor → PolygonFetcher")
    print(f"  Parity verifier:  python scripts/run_backtest.py")
    print(f"{'='*60}")

print("STATUS() command: ACTIVE — full system status")
print()
print("=" * 60)
print("ALL 5 MODULES ACTIVE — LABORATORY READY")
print("=" * 60)
print()
print("Commands available:")
print("  INITIALIZE(api_key)        — set API key")
print("  LOAD(symbols, start, end)  — fetch RTH data")
print("  TEST(hypothesis, spec, ...) — directed hypothesis test")
print("  BACKTEST(alpha_id)          — single full backtest")
print("  EXPORT(signal_id, report, spec) — produce deployable package")
print("  VERIFY(signal_id, local_hash)   — parity verification")
print("  REGISTRY()                  — display signal registry")
print("  REPORT(generation)          — research summary")
print("  RETIRE(signal_id, reason)   — mark retired")
print("  STATUS()                    — system status")
```

---

## 1. PARITY VERIFICATION CONTRACT

```
CANONICAL PARITY CONTRACT (V2)
────────────────────────────────────────────────────────────
Same .alpha.yaml + same date range + same execution_mode:

  Grok REPL (Prompt 4)              scripts/run_backtest.py (local)
  ──────────────────────            ──────────────────────────────
  build_platform()                  scripts/run_backtest.py
  BacktestOrderRouter               BacktestOrderRouter (same source)
  DefaultCostModel                  DefaultCostModel (same source)
  BasicRiskEngine                   BasicRiskEngine (same source)
  PolygonFetcher (substitution)     MassiveHistoricalIngestor
      ↓                                     ↓
  pnl_hash  ─────── must match ──────  pnl_hash

Parity hash function (canonical — both sides must use this exactly):
  records = list(orchestrator._trade_journal.query())
  trade_seq = [{"order_id": str(r.order_id), "symbol": r.symbol,
                "side": str(r.side).split(".")[-1],
                "quantity": int(r.filled_quantity),
                "fill_price": str(r.fill_price),
                "realized_pnl": str(r.realized_pnl)}
               for r in records]
  pnl_hash = SHA256(JSON(trade_seq, sort_keys=True, separators=(",",":"))).hexdigest()

Pass criteria:
  ✓ Same trade count
  ✓ Same total PnL ± 0.01%
  ✓ Same pnl_hash

Any divergence is a defect unless caused by the Polygon substitution.
────────────────────────────────────────────────────────────
```

---

## 2. ALPHA LIFECYCLE

```
RESEARCH   →  Grok testing + falsification + parity export
  ↓ Gate: AlphaLoader passes, OOS Sharpe ≥ 0.80, DSR > 1.0
PAPER      →  Running on feelies platform with paper signals
  ↓ Gate: ≥30 days, Sharpe ≥ 1.0, hit rate ≥ 50%, no quarantine triggers
LIVE       →  Real capital allocated by feelies
  ↓ Auto-triggered by: IC decay, factor drift, alpha drawdown breach
QUARANTINED →  Paper signals only; revalidation required to return to LIVE
  ↓ Two consecutive quarters DSR < 1.0
DECOMMISSIONED →  Permanent retirement
```

---

## EXPORT & LIFECYCLE STATUS

```
Export & Lifecycle Module: ACTIVE

EXPORT(signal_id, report, spec):
  Validates via AlphaLoader (repo source)
  Writes .alpha.yaml + .py files + parity_fingerprint.json + README_deploy.txt
  Updates registry CSV

VERIFY(signal_id, local_hash):
  Compares Grok hash vs local scripts/run_backtest.py hash
  Sets status = "parity_verified" on match

Registry: /home/user/registry/signal_registry.csv
Archive:  /home/user/experiments/generation_XXX_{alpha_id}/

Lifecycle: RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
Parity:    SHA-256 over ordered trade sequence (canonical definition in Section 1)
```
