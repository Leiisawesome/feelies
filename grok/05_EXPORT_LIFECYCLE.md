# MODULE 5 — EXPORT & LIFECYCLE: PARITY VERIFICATION, REGISTRY & ARCHIVE

## ACTIVATION DIRECTIVE

The Export & Lifecycle module activates with this block. This module:

1. Exports validated alphas as copy-paste-ready packages for the local repo
2. Defines the parity verification contract (Grok hash vs `scripts/run_backtest.py` hash)
3. Manages the signal registry and alpha lifecycle
4. Maintains the research archive

`EXPORT()` auto-promotes the exported alpha to `ALPHA_ACTIVE_DIR` only when
Module 6 is loaded (`ADOPT` is defined there). Without Module 6, `EXPORT()`
still produces the deployment package and warns that the active-directory
promotion was skipped.

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
    oos_pnl_hash    = report.get("oos_pnl_hash")    or report.get("steps", {}).get("oos", {}).get("pnl_hash")
    oos_config_hash = report.get("oos_config_hash") or report.get("steps", {}).get("oos", {}).get("config_hash")
    oos_parity_hash = report.get("oos_parity_hash") or report.get("steps", {}).get("oos", {}).get("parity_hash")
    oos_metrics     = report.get("steps", {}).get("oos", {})

    fingerprint = {
        "signal_id":       signal_id,
        "alpha_id":        alpha_id,
        "schema_version":  spec_dict.get("schema_version"),
        "layer":           spec_dict.get("layer"),
        "horizon_seconds": spec_dict.get("horizon_seconds"),
        "family":          (spec_dict.get("trend_mechanism") or {}).get("family"),
        "expected_half_life_seconds": (
            (spec_dict.get("trend_mechanism") or {}).get("expected_half_life_seconds")
        ),
        "margin_ratio":    (spec_dict.get("cost_arithmetic") or {}).get("margin_ratio"),
        "n_trades":        oos_metrics.get("n"),
        "total_pnl":       oos_metrics.get("mean_pnl"),
        "oos_sharpe":      oos_metrics.get("sharpe"),
        "oos_dsr":         report.get("steps", {}).get("falsification", {}).get("dsr"),
        # Three-hash parity contract — matches scripts/run_backtest.py exactly.
        "pnl_hash":        oos_pnl_hash,
        "config_hash":     oos_config_hash,
        "parity_hash":     oos_parity_hash,
        "hash_function": {
            "pnl_hash":    "SHA256(JSON([{order_id,symbol,side,quantity,fill_price,realized_pnl}]))",
            "config_hash": "PlatformConfig.snapshot().checksum",
            "parity_hash": "SHA256(pnl_hash + ':' + config_hash)",
        },
        "platform_yaml_source": "Same commit SHA as source ZIP — loaded via PlatformConfig.from_yaml",
        "generated_in":    "grok_repl_v2",
        "generated_at":    datetime.datetime.utcnow().isoformat(),
        "repo_source":     "github.com/Leiisawesome/feelies (ZIP bootstrap)",
        "data_source":     "Polygon REST API (RTH substitution)",
        "parity_contract": (
            "Running same .alpha.yaml on same date range through Grok REPL "
            "and through python scripts/run_backtest.py (with the same platform.yaml) "
            "must produce: identical trade count, identical pnl_hash, identical "
            "config_hash, identical parity_hash."
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

    # --- Stamp determinism evidence from any prior SELFCHECK on this alpha ---
    selfcheck = SESSION.get("selfcheck", {}).get(alpha_id)
    if selfcheck and selfcheck.get("passed"):
        report["selfcheck_passed"] = True
        # Cross-check: the SELFCHECK hashes must equal the OOS hashes,
        # otherwise the determinism proof is for a different config.
        if (selfcheck.get("pnl_hash") != oos_pnl_hash or
            selfcheck.get("config_hash") != oos_config_hash):
            print("  WARN: SELFCHECK hashes do NOT match OOS hashes — "
                  "Inv-5 was verified for a different run. Re-run SELFCHECK "
                  "against the OOS event_log before claiming determinism.")
            report["selfcheck_passed"] = False
    else:
        report["selfcheck_passed"] = False
        print("  WARN: no SELFCHECK on record for this alpha. "
              "Run SELFCHECK(alpha_id, oos_event_log) before deploying.")

    # --- Update signal registry ---
    _registry_upsert(signal_id, alpha_id, report, fingerprint)

    # --- Promote to live spec via the production-discovery ingress ---
    # EXPORT semantically means "this alpha is the new champion". Mirror
    # that on the platform side by writing the spec to ALPHA_ACTIVE_DIR
    # so RUN_ACTIVE() (Prompt 4) immediately discovers it through the
    # same alpha_spec_dir code path scripts/run_backtest.py uses.
    # If ADOPT is not loaded (Prompt 6 not pasted yet) we no-op with a
    # warning rather than failing — EXPORT must remain useful even when
    # the autonomy module is absent.
    if "ADOPT" in globals():
        try:
            ADOPT(spec_dict, alpha_id=alpha_id, source="EXPORT")
        except Exception as e:
            print(f"  WARN: post-EXPORT ADOPT failed: {e}. "
                  f"RUN_ACTIVE() will use the prior live alpha until you re-ADOPT.")
    else:
        print(f"  NOTE: ADOPT not loaded (paste Prompt 6) — exported alpha is "
              f"NOT promoted to ALPHA_ACTIVE_DIR; the platform's discovery path "
              f"won't see it until you ADOPT(spec) manually.")

    print(f"\nEXPORT COMPLETE: {export_dir}")
    print(f"  pnl_hash:    {(oos_pnl_hash or 'none')[:16]}...")
    print(f"  config_hash: {(oos_config_hash or 'none')[:16]}...")
    print(f"  parity_hash: {(oos_parity_hash or 'none')[:16]}...")
    print(f"  Recommendation: {report.get('verdict','?')}")
    if SESSION.get("active_alpha_id") == alpha_id:
        print(f"  Live spec:   ALPHA_ACTIVE_DIR/{alpha_id}/ (RUN_ACTIVE() picks this up)")
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

    NOTE: current Grok emits schema-1.1 alphas by default. The local repo's
    loader must be at or beyond the pinned commit family that supports
    `schema_version: "1.1"` and the declared `layer:` contract.

  NOTE: .py files MUST be in the same directory as the .alpha.yaml
  because computation_module paths resolve relative to the .alpha.yaml.

STEP 2 — Run parity verification locally
------------------------------------------
python scripts/run_backtest.py --config platform.yaml \\
    --symbol <same_symbol> \\
    --date  <same_start_date> \\
    --end-date <same_end_date>

  IMPORTANT: scripts/run_backtest.py reads platform.yaml by default.
  It MUST be the same platform.yaml that Grok extracted from the
  pinned commit SHA — otherwise the config_hash will diverge and
  parity will fail.

The script prints three hashes at the end of the report:
    pnl_hash     <hex>      ← over the trade sequence
    config_hash  <hex>      ← PlatformConfig.snapshot().checksum
    parity_hash  <hex>      ← SHA256(pnl_hash + ":" + config_hash)

STEP 3 — Verify parity in Grok
--------------------------------
VERIFY("{alpha_id}", "<local_pnl_hash>", "<local_config_hash>")

PARITY CONTRACT
---------------
Grok pnl_hash:    {(fingerprint.get('pnl_hash')    or 'not_computed')[:32]}
Grok config_hash: {(fingerprint.get('config_hash') or 'not_computed')[:32]}
Grok parity_hash: {(fingerprint.get('parity_hash') or 'not_computed')[:32]}

Verdicts:
  PARITY_VERIFIED              — both hashes match
  PARITY_VERIFIED_TRADES_ONLY  — pnl_hash matches; config_hash differs/missing
  PARITY_FAILED                — trade sequence differs

Any non-PARITY_VERIFIED outcome is a defect unless caused by the
documented Polygon data substitution.

STEP 4 — Promote to paper trading
-----------------------------------
# In Grok this exact alpha was already auto-ADOPTed at EXPORT time:
#     ALPHA_ACTIVE_DIR/{alpha_id}/{alpha_id}.alpha.yaml
# Calling RUN_ACTIVE() in the REPL will now backtest it through the
# same alpha_spec_dir discovery path the local platform uses.
#
# To make the same alpha live in the LOCAL repo, edit platform.yaml:
#     alpha_spec_dir: alphas/{alpha_id}
# Then run:
#     python scripts/run_backtest.py --config platform.yaml ...
#
# After 30 days paper: evaluate for LIVE promotion (mode: PAPER → LIVE).
"""
```

---

## CELL 2 — VERIFY command

```python
def VERIFY(signal_id: str, local_pnl_hash: str,
           local_config_hash: str | None = None) -> bool:
    """
    Three-hash parity verification against scripts/run_backtest.py.

    Args:
        signal_id:          Identifier registered via EXPORT()
        local_pnl_hash:     pnl_hash printed by scripts/run_backtest.py
        local_config_hash:  config_hash printed by scripts/run_backtest.py
                            (optional but RECOMMENDED — proves the local side
                             ran with the same platform.yaml as Grok)

    Verdicts:
        PARITY_VERIFIED              both hashes match
        PARITY_VERIFIED_TRADES_ONLY  pnl_hash matches; config_hash differs or
                                     was not provided (config drift possible)
        PARITY_FAILED                pnl_hash differs (real divergence)

    Usage:
        VERIFY("my_alpha", "<local_pnl_hash>", "<local_config_hash>")
    """
    grok_pnl    = _registry_get_field(signal_id, "parity_pnl_hash")
    grok_config = _registry_get_field(signal_id, "parity_config_hash")

    print(f"\nPARITY VERIFICATION: {signal_id}")
    print(f"  pnl_hash    Grok: {(grok_pnl or 'not found')[:32]}...")
    print(f"  pnl_hash    Local:{local_pnl_hash[:32]}...")
    if local_config_hash is not None:
        print(f"  config_hash Grok: {(grok_config or 'not found')[:32]}...")
        print(f"  config_hash Local:{local_config_hash[:32]}...")

    if grok_pnl is None:
        print(f"  STATUS: NO FINGERPRINT — run EXPORT({signal_id!r}, ...) first")
        return False

    pnl_ok    = (local_pnl_hash == grok_pnl)
    config_ok = (local_config_hash is not None and grok_config is not None
                 and local_config_hash == grok_config)

    if pnl_ok and config_ok:
        print(f"  STATUS: PARITY_VERIFIED")
        print(f"  Trade sequence and platform.yaml configuration both match.")
        _registry_set_status(signal_id, "parity_verified")
        return True

    if pnl_ok and not config_ok:
        print(f"  STATUS: PARITY_VERIFIED_TRADES_ONLY")
        print(f"  Trades match, but config_hash differs or was not provided.")
        print(f"  This is FRAGILE — the next platform.yaml change may break parity")
        print(f"  silently. Re-run with local_config_hash to fully verify.")
        _registry_set_status(signal_id, "parity_verified_trades_only")
        return True

    print(f"  STATUS: PARITY_FAILED")
    print(f"  Trade sequence differs. Diagnostic checklist:")
    print(f"    1. Did the local script use the SAME platform.yaml that Grok extracted")
    print(f"       from the pinned commit SHA? (config_hash mismatch is the smoking gun)")
    print(f"    2. Same .alpha.yaml file on both sides?")
    print(f"    3. Same date range and same symbols?")
    print(f"    4. Polygon API returning same data on both sides?")
    print(f"    5. Hash function identical? (see README_deploy.txt)")
    print(f"  If config_hashes differ, the gap is in platform.yaml — NOT data.")
    return False


def _registry_get_field(signal_id: str, field: str) -> str | None:
    """Look up an arbitrary registry field for a given signal_id."""
    if not os.path.exists(REGISTRY_PATH):
        return None
    with open(REGISTRY_PATH, "r") as f:
        for row in csv.DictReader(f):
            if row.get("signal_id") == signal_id:
                return row.get(field) or None
    return None


# Backward-compat alias used by older code paths.
def _registry_get_pnl_hash(signal_id: str) -> str | None:
    return _registry_get_field(signal_id, "parity_pnl_hash")


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
    """Insert or update a signal in the registry CSV.

    All hash fields and IC / Holm fields are wired through here. The columns
    are declared in REGISTRY_COLS (Prompt 1, CELL 4) — keep them in sync.
    """
    oos     = report.get("steps", {}).get("oos", {})
    falsif  = report.get("steps", {}).get("falsification", {})
    latency = report.get("steps", {}).get("latency", {})
    regime  = report.get("steps", {}).get("regime", {})
    ic      = report.get("steps", {}).get("ic", {})
    cpcv    = report.get("steps", {}).get("cpcv", {})
    lineage = report.get("lineage", {})
    meta    = report.get("metadata", {})
    hypothesis = report.get("hypothesis", {})
    hypothesis_text = hypothesis.get("statement") or hypothesis.get("mechanism") or ""

    row = {
        "generation":           SESSION.get("generation", 1),
        "signal_id":            signal_id,
        "alpha_id":             alpha_id,
        "layer":                meta.get("layer", ""),
        "horizon_seconds":      meta.get("horizon_seconds", ""),
        "family":               meta.get("trend_mechanism_family", ""),
        "expected_half_life_seconds": meta.get("expected_half_life_seconds", ""),
        "margin_ratio":         meta.get("margin_ratio", ""),
        "hypothesis_status":    "proposed",
        "hypothesis":           hypothesis_text[:120],
        "oos_sharpe":           round(oos.get("sharpe") or 0, 4),
        "dsr":                  round(falsif.get("dsr") or 0, 4),
        "ic_mean":              round(ic.get("ic_mean")   or 0, 6) if ic else "",
        "ic_tstat":             round(ic.get("ic_tstat")  or 0, 4) if ic else "",
        "tc_drag_pct":          "",
        "latency_decay_pct":    round((latency.get("latency_decay") or 0) * 100, 2),
        "regime_stability_cv":  round(regime.get("regime_cv") or 0, 4),
        "regime_all_positive":  regime.get("all_positive", False),
        "status":               "candidate",
        "recommendation":       report.get("verdict", "UNKNOWN"),
        # Lineage — populated by MUTATE() / EXPLORE() / EVOLVE() / RECOMBINE() in Prompt 6.
        "parent_id":            lineage.get("parent_id", ""),
        "co_parent_id":         lineage.get("co_parent_id", ""),
        "mutation_type":        lineage.get("mutation_type", ""),
        "parity_n_trades":      fingerprint.get("n_trades", ""),
        "parity_total_pnl":     round(fingerprint.get("total_pnl") or 0, 6),
        # Three-hash parity contract.
        "parity_pnl_hash":      fingerprint.get("pnl_hash", ""),
        "parity_config_hash":   fingerprint.get("config_hash", ""),
        "parity_combined_hash": fingerprint.get("parity_hash", ""),
        # Statistical / determinism evidence.
        "selfcheck_passed":     report.get("selfcheck_passed", ""),
        "holm_qvalue":          round(report.get("holm_qvalue") or 0, 6) if report.get("holm_qvalue") is not None else "",
        "cpcv_fraction_positive": round(cpcv.get("fraction_positive") or 0, 4) if cpcv else "",
        "cpcv_sharpe_p10":      round(cpcv.get("sharpe_p10") or 0, 4) if cpcv and cpcv.get("sharpe_p10") is not None else "",
        # Post-promotion audit fields — populated only by AUDIT() (Prompt 6).
        "audit_status":         "",
        "audit_last_run":       "",
        "audit_sharpe_decay_pct": "",
        "audit_ic_decay":       "",
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
    header = f"{'signal_id':25s} {'layer':9s} {'horizon':>7s} {'oos_sharpe':>10} {'dsr':>6} {'status':15s} {'verdict':12s}"
    print(header)
    print(f"{'─'*100}")
    for r in rows:
        print(f"{r.get('signal_id',''):25s} {r.get('layer',''):9s} {str(r.get('horizon_seconds','')):>7s} "
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
        "AlphaLoader validation passes (schema-1.1 + compilation)",
        "Determinism test: same event_log → same trade sequence",
        "Sensor / snapshot bindings finite (no NaN/Inf) over a 5-day sample",
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
    # Module sentinels — loaded by checking for a function each module exports.
    _m6 = "EVOLVE" in globals()
    _m7 = "PROPOSE" in globals()
    print(f"\n{'='*60}")
    print("MICROSTRUCTURE RESEARCH LABORATORY V2 — STATUS")
    print(f"{'='*60}")
    print(f"  Module 1 (Bootstrap):         ACTIVE")
    print(f"  Module 2 (Data Ingestion):    ACTIVE")
    print(f"  Module 3 (Alpha Development): ACTIVE")
    print(f"  Module 4 (Backtest Exec):     ACTIVE")
    print(f"  Module 5 (Export/Lifecycle):  ACTIVE")
    print(f"  Module 6 (Evolution):         {'ACTIVE' if _m6 else 'NOT YET LOADED — paste Prompt 6'}")
    print(f"  Module 7 (Hypothesis):        {'ACTIVE' if _m7 else 'NOT YET LOADED — paste Prompt 7'}")
    print()
    print(f"  API key set:      {'YES' if SESSION.get('api_key') else 'NO — run INITIALIZE()'}")
    print(f"  Loaded symbols:   {SESSION.get('loaded_symbols', [])}")
    print(f"  Loaded dates:     {SESSION.get('loaded_dates', [])}")
    n_events = len(list(SESSION["event_log"].replay())) if SESSION.get("event_log") else 0
    print(f"  Event log:        {n_events} events")
    print(f"  Generation:       {SESSION.get('generation', 0)}")
    print(f"  Active alpha id:  {SESSION.get('active_alpha_id') or 'none'}")
    print(f"  Active alpha:     {SESSION.get('active_alpha', 'none')}  (legacy dev handle)")
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
print("Export & Lifecycle module: ACTIVE")
print("Modules 1–5 loaded. Paste Prompt 6 (Evolution), then Prompt 7 (Hypothesis), then INITIALIZE().")
print("=" * 60)
print()
print("Commands available so far:")
print("  INITIALIZE(api_key)              — set API key")
print("  STATUS()                         — full system status")
print("  LOAD(symbols, start, end)        — fetch RTH data via PolygonFetcher")
print("  TEST(hypothesis, spec, ...)      — 7-step directed hypothesis test")
print("  BACKTEST(alpha_id)               — single full backtest (explicit-spec)")
print("  RUN_ACTIVE()                     — backtest the currently ADOPTed alpha")
print("                                     (requires Prompt 6)")
print("  SELFCHECK(alpha_id)              — Inv-5 deterministic-replay check")
print("  SELFCHECK_ADOPTION(spec_path)    — explicit-spec ≡ alpha_spec_dir ingress")
print("                                     (requires Prompt 6)")
print("  EXPORT(signal_id, report, spec)  — produce deployable package")
print("  VERIFY(signal_id, pnl_hash, cfg) — three-hash parity verification")
print("  REGISTRY()                       — display signal registry")
print("  REPORT(generation)               — research summary")
print("  RETIRE(signal_id, reason)        — mark retired")
```

---

## 1. PARITY VERIFICATION CONTRACT

```
CANONICAL PARITY CONTRACT (V3 — three-hash)
────────────────────────────────────────────────────────────
Same .alpha.yaml + same date range + same platform.yaml:

  Grok REPL (Prompt 4)              scripts/run_backtest.py (local)
  ──────────────────────            ──────────────────────────────
  PlatformConfig.from_yaml(         PlatformConfig.from_yaml(
    PLATFORM_YAML_PATH)               "platform.yaml")
  build_platform()                  build_platform()
  BacktestOrderRouter               BacktestOrderRouter (same source)
  DefaultCostModel                  DefaultCostModel (same source)
  BasicRiskEngine                   BasicRiskEngine (same source)
  PolygonFetcher (substitution)     MassiveHistoricalIngestor
      ↓                                     ↓
  pnl_hash    ─── must match ───   pnl_hash      (same trades)
  config_hash ─── must match ───   config_hash   (same config)
  parity_hash ─── must match ───   parity_hash   (binds both)

Hash functions (canonical — both sides emit these EXACTLY):

  pnl_hash    = SHA256(JSON([{order_id, symbol, side, quantity,
                              fill_price, realized_pnl}],
                            sort_keys=True, separators=(",",":")))
  config_hash = PlatformConfig.snapshot().checksum   # already SHA-256
  parity_hash = SHA256(pnl_hash + ":" + config_hash)

Pass criteria:
  ✓ Same trade count
  ✓ Same pnl_hash    (same trades)
  ✓ Same config_hash (same execution config — proves platform.yaml parity)
  ✓ Same parity_hash (single comparator binding both)

Any divergence is a defect unless caused by the Polygon substitution.
A pnl_hash match with a config_hash mismatch is FRAGILE: trade-level
parity happens to coincide despite divergent configuration, and the
next config change will silently break parity.
────────────────────────────────────────────────────────────
```

---

## 2. ALPHA LIFECYCLE

```
RESEARCH   →  Grok testing + falsification + parity export
    ↓ Gate: schema-1.1 AlphaLoader pass, OOS Sharpe ≥ 0.80, DSR > 1.0
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

VERIFY(signal_id, local_pnl_hash, local_config_hash=None):
  Compares Grok pnl_hash + config_hash vs scripts/run_backtest.py output
  Three verdicts: PARITY_VERIFIED, PARITY_VERIFIED_TRADES_ONLY, PARITY_FAILED
  Sets registry status accordingly

Registry: /home/user/registry/signal_registry.csv
Archive:  /home/user/experiments/generation_XXX_{alpha_id}/

Lifecycle: RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED
Parity:    Three-hash contract — pnl_hash, config_hash, parity_hash
           (canonical definition in Section 1)
```
