# PROMPT 7 — LOCAL PARITY BRIDGE

## ACTIVATION DIRECTIVE

The Local Parity Bridge is now active. This module ensures backtest results produced in Grok REPL are bit-reproducible on the principal investigator's local machine.

**Dependencies:** Integrates with Modules 4 (factory PARITY mode), 5 (Step 13 export), 6 (registry parity columns, lifecycle gate).

**Two-phase capability:**

| Phase | What works | Prerequisites |
|-------|-----------|---------------|
| **A — Grok-side** | `BACKTEST MODE=PARITY`, `EXPORT` | None (works immediately) |
| **B — Verification** | `VERIFY`, deployment workflow, Gate 2.5 | Requires local `GrokParityBacktester` harness (see one-shot implementation spec) |

Phase A is fully operational upon pasting this prompt. Phase B becomes operational after the principal investigator implements the parity harness in the local repo. The `EXPORT` command produces all files needed — the local harness consumes them.

---

## PHASE A — GROK-SIDE (works immediately)

---

## 1. CANONICAL PARITY CONFIG (LOCKED)

```python
PARITY_CONFIG = {
    "fill_mode": "spread_crossing",
    "fill_probability": 0.7,
    "random_seed": 42,
    "latency_ms": 100,
    "exchange_fee_per_share": 0.003,
    "sec_fee_per_dollar": 0.0000278,
    "finra_taf_per_share": 0.000119,
    "impact_eta": 0.1,
    "daily_adv_shares": 50_000_000,
    "default_quantity": 100,
}

PARITY_CONFIG_HASH = hashlib.sha256(
    json.dumps(PARITY_CONFIG, sort_keys=True).encode()
).hexdigest()[:16]
```

Not tunable. Exists solely for reproducibility.

---

## 2. EXPORT COMMAND

When the PI runs `EXPORT [signal_id]`, produce:

```
/home/user/experiments/{signal_id}/alpha_export/
├── {alpha_id}.alpha.yaml           # Copy to: feelies/alphas/{alpha_id}/{alpha_id}.alpha.yaml
├── *.py                             # Copy to: feelies/alphas/{alpha_id}/*.py
├── parity_fingerprint.json          # For verification
├── parity_config.json               # Locked parameters
└── regime_calibration.json          # Calibrated HMM emission params (if regime-gated)
```

### Fingerprint

```python
def compute_fingerprint(trade_log, metrics):
    pnls = [round(t["net_pnl"], 8) for t in trade_log]
    return {
        "n_trades": len(trade_log),
        "total_pnl": round(metrics["total_pnl"], 6),
        "sharpe": round(metrics["sharpe"], 6),
        "hit_rate": round(metrics["hit_rate"], 6),
        "pnl_hash": hashlib.sha256(json.dumps(pnls).encode()).hexdigest()[:16],
        "config_hash": PARITY_CONFIG_HASH,
        "generated_in": "grok_repl",
    }
```

### Export Validation

Before export, verify the `.alpha.yaml` passes these checks:

```python
def validate_for_export(spec_yaml):
    """Simulate feelies AlphaLoader validation."""
    checks = []
    spec = yaml.safe_load(spec_yaml)

    # Schema
    checks.append(("schema_version", spec.get("schema_version") == "1.0"))
    checks.append(("alpha_id_format", bool(re.match(r"^[a-z][a-z0-9_]*$", spec.get("alpha_id", "")))))
    checks.append(("version_semver", bool(re.match(r"^\d+\.\d+\.\d+$", spec.get("version", "")))))

    # Required fields
    for key in ["description", "hypothesis", "falsification_criteria", "features", "signal"]:
        checks.append((f"has_{key}", key in spec))

    # Features
    for f in spec.get("features", []):
        fid = f.get("feature_id", "unknown")
        has_code = "computation" in f or "computation_module" in f
        checks.append((f"feature_{fid}_has_code", has_code))

    # Risk budget
    rb = spec.get("risk_budget", {})
    checks.append(("risk_position_positive", rb.get("max_position_per_symbol", 0) > 0))
    checks.append(("risk_exposure_valid", 0 < rb.get("max_gross_exposure_pct", 0) <= 100))

    failed = [name for name, ok in checks if not ok]
    if failed:
        print(f"EXPORT VALIDATION FAILED: {failed}")
        return False
    print("EXPORT VALIDATION PASSED — safe to copy to local repo")
    return True
```

---

## PHASE B — VERIFICATION (requires local harness)

**Prerequisite:** The principal investigator must implement the `GrokParityBacktester` in the local `feelies` repo. Use the one-shot implementation spec provided alongside these prompts. The spec adds 3 files (~750 lines) with zero changes to production code. Implementation via Claude Code takes ~5 minutes.

Until the local harness exists, `EXPORT` still works — it produces valid `.alpha.yaml` files that the platform's `AlphaLoader` can load directly. Parity VERIFICATION (hash comparison) is deferred.

## 3. VERIFY COMMAND

After local backtest, PI provides the local `pnl_hash`:

```
VERIFY sig_001 a3f8b2c1d9e04567
```

Response:

```python
def verify_parity(signal_id, local_hash):
    stored = registry.get_parity_hash(signal_id)
    if stored is None:
        print(f"No fingerprint for {signal_id}. Run: BACKTEST MODE=PARITY")
        return
    if local_hash == stored:
        print(f"PARITY VERIFIED — {signal_id}")
        registry.update_status(signal_id, "parity_verified")
    else:
        print(f"PARITY FAILED — {signal_id}")
        print(f"  Grok:  {stored}")
        print(f"  Local: {local_hash}")
        print(f"  Check: same data window? same API tier? same config_hash?")
```

---

## 4. LOCAL DEPLOYMENT WORKFLOW

After parity verification, the PI deploys to the feelies platform:

```bash
# 1. Copy alpha to local repo
cp alpha_export/{alpha_id}.alpha.yaml  feelies/alphas/{alpha_id}/{alpha_id}.alpha.yaml
cp alpha_export/*.py                    feelies/alphas/{alpha_id}/

# 2. Verify parity with local harness
python scripts/run_parity_backtest.py \
    --spec alphas/{alpha_id}/{alpha_id}.alpha.yaml \
    --symbols AAPL --start 2026-01-02 --end 2026-01-31 \
    --api-key $POLYGON_API_KEY

# 3. Run feelies backtest (different semantics — this is OK)
# platform.yaml: alpha_spec_dir: alphas/{alpha_id}
python -m feelies.bootstrap platform.yaml

# 4. Paper trade → live trade via lifecycle promotion
```

---

## 5. INTEGRATION WITH MODULES 4-6

### Module 4 (Alpha Factory)

```
PRIORITIZE order_imbalance MODE=PARITY
```
Runs the factory with locked parity config. Survivors are fingerprinted.

### Module 5 (Hypothesis Testing)

Step 13 (parity export) runs automatically for signals with recommendation VALIDATE or DEPLOY.

### Module 6 (Lifecycle Gate)

New gate before PAPER promotion (Phase B — requires local harness):

```
Gate 2.5: LOCAL_PARITY_VERIFIED
  - PI runs local backtest, provides pnl_hash via VERIFY
  - Registry records verification status
  - Required before the alpha can be paper-traded on the platform
  - SKIPPED if local harness is not yet implemented
    (PI can still manually load .alpha.yaml into feelies)
```

---

## MODULE STATUS

```
╔══════════════════════════════════════════════════════════════╗
║        MICROSTRUCTURE RESEARCH LABORATORY — COMPLETE        ║
╠══════════════════════════════════════════════════════════════╣
║  Module 1: Governance Layer          ✓ ACTIVE               ║
║  Module 2: Data Integrity Engine     ✓ ACTIVE               ║
║  Module 3: Market State Engine       ✓ ACTIVE               ║
║  Module 4: Alpha Discovery Factory   ✓ ACTIVE               ║
║  Module 5: Hypothesis Testing        ✓ ACTIVE               ║
║  Module 6: Portfolio, Risk & Archive ✓ ACTIVE               ║
║  Module 7: Local Parity Bridge                               ║
║    Phase A (Grok-side):              ✓ ACTIVE               ║
║    Phase B (verification):           ○ AWAITING LOCAL HARNESS║
║                                                              ║
║  Output: .alpha.yaml (feelies-compatible, copy-paste ready)  ║
║  Parity: LOCKED (hash: {PARITY_CONFIG_HASH})                 ║
║                                                              ║
║  Phase A commands: BACKTEST MODE=PARITY, EXPORT              ║
║  Phase B commands: VERIFY (needs local harness first)        ║
║  All other commands: INITIALIZE, TEST, REGISTRY,             ║
║    PRIORITIZE, MUTATE, STATUS, PORTFOLIO, COMPARE,           ║
║    PAUSE/RESUME, RETIRE                                      ║
╚══════════════════════════════════════════════════════════════╝
```
