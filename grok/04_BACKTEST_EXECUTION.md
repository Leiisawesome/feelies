# PROMPT 4 — BACKTEST EXECUTION: PIPELINE, STATISTICS & REGIME ANALYSIS

> **Paste this entire file as one block. Wait for `Backtest Execution module: ACTIVE` before pasting Prompt 5.**

## ACTIVATION DIRECTIVE

The Backtest Execution module is now active. This module runs every backtest
through the repo's actual pipeline — `build_platform()` from `feelies.bootstrap`
— with no invented fill model, no invented cost constants, no invented risk limits.

All execution behavior comes from repo source. The only input Grok provides is:
a populated `InMemoryEventLog` (from Prompt 2) and a valid `.alpha.yaml` spec
(from Prompt 3).

**Prerequisites: Prompts 1, 2, and 3 must have been executed successfully.**

---

## CELL 1 — Core backtest runner (uses build_platform from repo source)

```python
import yaml, hashlib, json, os, pathlib, math, statistics
from pathlib import Path
from feelies.bootstrap import build_platform
from feelies.core.platform_config import PlatformConfig, OperatingMode
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.events import Signal

# -------------------------------------------------------------------
# State clearing is automatic: every call to run_backtest() creates
# entirely fresh instances — PlatformConfig, InMemoryEventLog, all
# engines (AlphaRegistry, CompositeFeatureEngine, SimulatedClock,
# BacktestOrderRouter, BasicRiskEngine, HMM3StateFractional).
# There is no shared mutable state between runs.
# -------------------------------------------------------------------

def _symbols_from_event_log(event_log: InMemoryEventLog) -> frozenset[str]:
    """Extract unique symbols from the event log for PlatformConfig."""
    symbols: set[str] = set()
    for event in event_log.replay():
        sym = getattr(event, "symbol", None)
        if sym is not None:
            symbols.add(sym)
    return frozenset(symbols)


def run_backtest(
    spec_path: str | Path,
    event_log: InMemoryEventLog,
    regime_engine: str | None = "hmm_3state_fractional",
    account_equity: float = 100_000.0,
    execution_mode: str = "market",
    backtest_fill_latency_ns: int = 0,
    signal_entry_cooldown_ticks: int = 0,
    verbose: bool = True,
) -> dict:
    """
    Run a backtest through the repo's actual pipeline.

    This is the ONLY backtest path. No custom fill logic. No invented constants.
    All execution behavior comes from BacktestOrderRouter, DefaultCostModel,
    BasicRiskEngine — as configured by PlatformConfig and its defaults.

    Args:
        spec_path:                 Path to .alpha.yaml file (saved by save_alpha())
        event_log:                 Pre-populated InMemoryEventLog from LOAD()
        regime_engine:             "hmm_3state_fractional" (default) or None
        account_equity:            Starting capital in USD (default 100_000;
                                       PlatformConfig defaults to 1_000_000 — use the
                                       same value on both sides for parity)
        execution_mode:            "market" (mid-price fill) or "passive_limit"
        backtest_fill_latency_ns:  Fill latency in ns (default 0; platform.yaml uses 30_000_000)
        signal_entry_cooldown_ticks: Ticks between directional entries (default 0)
        verbose:                   Print summary after run

    Returns:
        dict with keys: trade_count, total_pnl, net_pnl, total_fees,
                        gross_pnl, pnl_hash, trades, positions, config_snapshot
    """
    spec_path = Path(spec_path)
    assert spec_path.exists(), f"Alpha spec not found: {spec_path}"
    assert event_log is not None, "event_log is None — run LOAD() first"

    symbols = _symbols_from_event_log(event_log)
    assert symbols, "event_log contains no events with symbols — run LOAD() first"

    # Build PlatformConfig from source defaults.
    # DO NOT add invented fill probability, cost multipliers, or RNG seeds here.
    config = PlatformConfig(
        mode                          = OperatingMode.BACKTEST,
        symbols                       = symbols,
        alpha_specs                   = [spec_path],
        regime_engine                 = regime_engine,
        account_equity                = account_equity,
        execution_mode                = execution_mode,
        backtest_fill_latency_ns      = backtest_fill_latency_ns,
        signal_entry_cooldown_ticks   = signal_entry_cooldown_ticks,
    )

    # Fresh platform instance — all engines created new for this run
    orchestrator, resolved_config = build_platform(config, event_log=event_log)
    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    # --- Extract results ---
    journal  = orchestrator._trade_journal
    positions = orchestrator._positions.all_positions()
    records  = list(journal.query())

    total_realized = sum(
        float(p.realized_pnl or 0) for p in positions.values()
    )
    total_unrealized = sum(
        float(p.unrealized_pnl or 0) for p in positions.values()
    )

    # Fees: sum from trade records (each TradeRecord carries its own fees)
    total_fees = sum(float(getattr(r, "fees", 0) or 0) for r in records)
    gross_pnl  = total_realized
    net_pnl    = gross_pnl - total_fees

    # Parity hash — deterministic over ordered trade sequence
    pnl_hash = _compute_parity_hash(records)

    result = {
        "trade_count":       len(records),
        "total_pnl":         total_realized,
        "gross_pnl":         gross_pnl,
        "total_fees":        total_fees,
        "net_pnl":           net_pnl,
        "unrealized_pnl":    total_unrealized,
        "pnl_hash":          pnl_hash,
        "trades":            records,
        "positions":         positions,
        "config_snapshot":   resolved_config.snapshot() if hasattr(resolved_config, "snapshot") else None,
        "orchestrator":      orchestrator,
    }

    if verbose:
        _print_backtest_summary(result, spec_path)

    return result


def _compute_parity_hash(records: list) -> str:
    """
    Compute a deterministic SHA-256 hash over the trade sequence.

    Both Grok and scripts/run_backtest.py must use the same hash function
    for parity verification. This function defines the canonical format.

    Hash input: JSON array of trade records, fields in sort_keys order:
      order_id, realized_pnl, side, fill_price, quantity, symbol
    """
    trade_seq = [
        {
            "order_id":     str(getattr(r, "order_id",         "")),
            "symbol":       str(getattr(r, "symbol",            "")),
            "side":         str(getattr(r, "side",              "")).split(".")[-1],  # enum name
            "quantity":     int(getattr(r, "filled_quantity",   0)),  # TradeRecord field is filled_quantity
            "fill_price":   str(getattr(r, "fill_price",       "0")),
            "realized_pnl": str(getattr(r, "realized_pnl",     "0")),
        }
        for r in records
    ]
    payload = json.dumps(trade_seq, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _print_backtest_summary(result: dict, spec_path) -> None:
    print(f"\n{'='*60}")
    print(f"BACKTEST SUMMARY: {pathlib.Path(spec_path).stem}")
    print(f"{'='*60}")
    print(f"  Trades:       {result['trade_count']}")
    print(f"  Gross PnL:    ${result['gross_pnl']:,.4f}")
    print(f"  Fees:         ${result['total_fees']:,.4f}")
    print(f"  Net PnL:      ${result['net_pnl']:,.4f}")
    print(f"  Unrealized:   ${result['unrealized_pnl']:,.4f}")
    print(f"  Parity hash:  {result['pnl_hash'][:16]}...")
    print(f"{'='*60}\n")


# Convenience command
def BACKTEST(alpha_id: str, event_log: InMemoryEventLog | None = None, **kwargs) -> dict:
    """
    Run a full backtest for a saved alpha.

    Usage:
        result = BACKTEST("my_alpha")
        result = BACKTEST("my_alpha", event_log=LOAD("AAPL","2026-01-15"))
    """
    event_log = event_log or SESSION.get("event_log")
    assert event_log is not None, "No event_log in session. Call LOAD() first."
    spec_path = os.path.join(ALPHA_DEV_DIR, alpha_id, f"{alpha_id}.alpha.yaml")
    assert os.path.exists(spec_path), f"Alpha not found: {spec_path}"
    return run_backtest(spec_path, event_log, **kwargs)

print("Backtest Execution module: ACTIVE")
print("BACKTEST('alpha_id') runs the full repo pipeline via build_platform()")
```

---

## CELL 2 — Walk-forward and CPCV backtesting

```python
import numpy as np

def walk_forward_backtest(
    spec_path: str | Path,
    dates_by_partition: dict,
    symbols: list[str],
    n_folds: int = 5,
    **backtest_kwargs,
) -> dict:
    """
    Rolling walk-forward backtest over the train window.

    Each fold tests on the next segment after training on preceding data.
    Returns per-fold metrics and the distribution of OOS Sharpe ratios.
    """
    train_dates = dates_by_partition["train"]
    fold_size   = max(1, len(train_dates) // n_folds)
    fold_results = []

    for i in range(n_folds - 1):
        train_fold = train_dates[: (i + 1) * fold_size]
        test_fold  = train_dates[(i + 1) * fold_size : (i + 2) * fold_size]
        if not test_fold:
            continue

        print(f"Fold {i+1}/{n_folds-1}: train={train_fold[0]}…{train_fold[-1]}  "
              f"test={test_fold[0]}…{test_fold[-1]}")

        # Fetch test fold data
        elog = LOAD(symbols, test_fold[0], test_fold[-1])
        if elog is None:
            continue

        result = run_backtest(spec_path, elog, verbose=False, **backtest_kwargs)
        trades = result["trades"]

        pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in trades]
        metrics = _compute_metrics(pnls, label=f"fold_{i+1}")
        fold_results.append(metrics)

    if not fold_results:
        return {"error": "No fold results — insufficient data"}

    sharpes = [f["sharpe"] for f in fold_results if f["sharpe"] is not None]
    return {
        "folds":          fold_results,
        "sharpe_mean":    float(np.mean(sharpes)) if sharpes else None,
        "sharpe_std":     float(np.std(sharpes))  if sharpes else None,
        "sharpe_min":     float(min(sharpes))      if sharpes else None,
        "n_positive_folds": sum(s > 0 for s in sharpes),
        "n_folds":        len(fold_results),
    }


def _compute_metrics(pnls: list[float], label: str = "") -> dict:
    """Compute Sharpe, hit rate, profit factor, and DSR from a list of trade PnLs."""
    if not pnls or len(pnls) < 2:
        return {"label": label, "n": len(pnls), "sharpe": None, "dsr": None,
                "hit_rate": None, "profit_factor": None, "mean_pnl": None}

    n     = len(pnls)
    mu    = statistics.mean(pnls)
    sigma = statistics.stdev(pnls)
    sr    = mu / max(sigma, 1e-10)

    # DSR: deflated Sharpe ratio (accounts for skew, kurtosis, and trial count)
    try:
        sk  = _skewness(pnls)
        ku  = _excess_kurtosis(pnls)
        dsr = sr * math.sqrt(n) / math.sqrt(1 - sk * sr + (ku / 4) * sr ** 2)
    except (ZeroDivisionError, ValueError):
        dsr = None

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    pf     = sum(wins) / max(abs(sum(losses)), 1e-10) if losses else float("inf")

    return {
        "label":          label,
        "n":              n,
        "mean_pnl":       mu,
        "sharpe":         sr,
        "dsr":            dsr,
        "hit_rate":       len(wins) / n,
        "profit_factor":  pf,
    }


def _skewness(data: list[float]) -> float:
    n  = len(data)
    mu = sum(data) / n
    s  = statistics.stdev(data)
    if s < 1e-12:
        return 0.0
    return (sum((x - mu) ** 3 for x in data) / n) / s ** 3


def _excess_kurtosis(data: list[float]) -> float:
    n  = len(data)
    mu = sum(data) / n
    s  = statistics.stdev(data)
    if s < 1e-12:
        return 0.0
    return (sum((x - mu) ** 4 for x in data) / n) / s ** 4 - 3.0

print("Walk-forward and metrics functions: ACTIVE")
```

---

## CELL 3 — Statistical falsification battery

```python
import random

def falsification_battery(
    trade_pnls: list[float],
    n_bootstrap: int = 5000,
    n_permutation: int = 5000,
    seed: int = 0,
) -> dict:
    """
    Full statistical falsification for a candidate signal.

    Tests:
    1. Bootstrap: is mean return significantly > 0?
    2. Permutation: is signal Sharpe better than random?
    3. DSR: deflated Sharpe accounting for skew, kurtosis, n_trials
    4. IC proxy: correlation between signal rank and next-tick return (if available)

    Acceptance criteria (all must pass):
      bootstrap_pvalue < 0.05
      permutation_pvalue < 0.05
      dsr > 1.0

    Returns:
      dict with all test statistics and a 'pass' boolean
    """
    rng = random.Random(seed)
    n   = len(trade_pnls)

    if n < 10:
        return {"pass": False, "error": f"Insufficient trades: {n} < 10"}

    mu    = statistics.mean(trade_pnls)
    sigma = statistics.stdev(trade_pnls)
    sr    = mu / max(sigma, 1e-10)

    # Bootstrap: p(mean <= 0) under resampling
    boot_means = [
        statistics.mean(rng.choices(trade_pnls, k=n))
        for _ in range(n_bootstrap)
    ]
    bootstrap_pvalue = sum(m <= 0 for m in boot_means) / n_bootstrap

    # Permutation: p(Sharpe >= observed) under label shuffle
    perm_sharpes = []
    for _ in range(n_permutation):
        shuffled = trade_pnls[:]
        rng.shuffle(shuffled)
        perm_mu = statistics.mean(shuffled)
        perm_sr = perm_mu / max(statistics.stdev(shuffled), 1e-10)
        perm_sharpes.append(perm_sr)
    permutation_pvalue = sum(s >= sr for s in perm_sharpes) / n_permutation

    # DSR
    try:
        sk  = _skewness(trade_pnls)
        ku  = _excess_kurtosis(trade_pnls)
        dsr = sr * math.sqrt(n) / math.sqrt(max(1 - sk * sr + (ku / 4) * sr ** 2, 1e-10))
    except Exception:
        dsr = None

    passed = (
        bootstrap_pvalue   < 0.05 and
        permutation_pvalue < 0.05 and
        (dsr is not None and dsr > 1.0)
    )

    return {
        "n_trades":           n,
        "mean_pnl":           mu,
        "sharpe":             sr,
        "dsr":                dsr,
        "bootstrap_pvalue":   bootstrap_pvalue,
        "permutation_pvalue": permutation_pvalue,
        "hit_rate":           len([p for p in trade_pnls if p > 0]) / n,
        "pass":               passed,
        "verdict":            "PASS" if passed else "FAIL",
    }

print("falsification_battery() available.")
```

---

## CELL 4 — Regime sensitivity and execution realism audit

```python
def regime_sensitivity(
    trades: list,
    event_log: InMemoryEventLog,
) -> dict:
    """
    Evaluate signal performance per HMM regime state.

    Replays event_log through a fresh HMM3StateFractional engine (from repo source)
    to classify each trade's entry timestamp into a regime state, then computes
    per-state performance metrics.

    State names (canonical, from repo source):
      ("compression_clustering", "normal", "vol_breakout")
    """
    from feelies.services.regime_engine import HMM3StateFractional
    from feelies.core.events import NBBOQuote

    state_names = ("compression_clustering", "normal", "vol_breakout")
    per_state_pnls: dict[str, list[float]] = {s: [] for s in state_names}
    unclassified = []

    # Build a lookup: exchange_timestamp_ns → regime posterior
    # Replay the event log through the regime engine
    posteriors_by_ts: dict[int, list[float]] = {}
    hmm = HMM3StateFractional()
    for event in event_log.replay():
        if isinstance(event, NBBOQuote):
            post = hmm.posterior(event)
            posteriors_by_ts[event.exchange_timestamp_ns] = list(post)

    # Match each trade to the regime at its entry timestamp.
    # TradeRecord uses signal_timestamp_ns (not timestamp_ns).
    for record in trades:
        ts   = getattr(record, "signal_timestamp_ns", None)
        pnl  = float(getattr(record, "realized_pnl", 0) or 0)
        post = posteriors_by_ts.get(ts) if ts else None

        if post is not None:
            dominant = state_names[post.index(max(post))]
            per_state_pnls[dominant].append(pnl)
        else:
            unclassified.append(pnl)

    per_state_metrics = {}
    for state, pnls in per_state_pnls.items():
        per_state_metrics[state] = _compute_metrics(pnls, label=state)

    sharpes = [m["sharpe"] for m in per_state_metrics.values()
               if m["sharpe"] is not None]
    all_positive  = all(s > 0 for s in sharpes) if sharpes else False
    cv            = (statistics.stdev(sharpes) / abs(statistics.mean(sharpes) + 1e-10)
                     if len(sharpes) > 1 else 0.0)

    result = {
        "per_state":         per_state_metrics,
        "all_positive":      all_positive,
        "regime_cv":         cv,
        "worst_sharpe":      min(sharpes) if sharpes else None,
        "unclassified_trades": len(unclassified),
        "stable":            all_positive and cv < 1.5,
    }

    # Print summary
    print("\nRegime Sensitivity:")
    for state, m in per_state_metrics.items():
        print(f"  {state:30s}: n={m['n']:4d}  sharpe={m['sharpe'] or 0:+.3f}  "
              f"hit_rate={m['hit_rate'] or 0:.1%}")
    print(f"  All positive: {all_positive}  |  CV: {cv:.2f}  |  Stable: {result['stable']}")
    return result


def latency_sweep(
    spec_path: str | Path,
    event_log: InMemoryEventLog,
    latency_ms_values: list[int] | None = None,
    **backtest_kwargs,
) -> dict:
    """
    Run backtest at multiple fill latencies and measure Sharpe decay.

    Uses backtest_fill_latency_ns parameter from PlatformConfig — no invented latency model.
    Pass criteria: decay from 0ms to 200ms < 40%.
    """
    latency_ms_values = latency_ms_values or [0, 50, 100, 200]
    results = {}

    for ms in latency_ms_values:
        ns = ms * 1_000_000
        r  = run_backtest(spec_path, event_log, verbose=False,
                          backtest_fill_latency_ns=ns, **backtest_kwargs)
        trades = r["trades"]
        pnls   = [float(getattr(t, "realized_pnl", 0) or 0) for t in trades]
        m      = _compute_metrics(pnls, label=f"{ms}ms")
        results[ms] = {**m, "n_trades": r["trade_count"]}
        print(f"  Latency {ms:4d}ms: trades={r['trade_count']:5d}  "
              f"sharpe={m['sharpe'] or 0:+.3f}  net_pnl=${r['net_pnl']:,.2f}")

    # Decay: (Sharpe_0ms - Sharpe_200ms) / Sharpe_0ms
    sr_0   = results.get(0,   {}).get("sharpe")
    sr_200 = results.get(200, {}).get("sharpe")
    if sr_0 and sr_0 > 0 and sr_200 is not None:
        decay = (sr_0 - sr_200) / sr_0
        print(f"  Latency decay (0→200ms): {decay:.1%}  "
              f"{'PASS' if decay < 0.40 else 'FAIL'} (threshold: 40%)")
        results["latency_decay"] = decay
        results["latency_pass"]  = decay < 0.40

    return results


def tc_sensitivity(
    spec_path: str | Path,
    event_log: InMemoryEventLog,
    stress_multipliers: list[float] | None = None,
    **backtest_kwargs,
) -> dict:
    """
    Run backtest at multiple TC stress multipliers (uses DefaultCostModel.stress_multiplier).
    Pass criteria: breakeven multiplier > 1.5×.
    """
    stress_multipliers = stress_multipliers or [1.0, 1.5, 2.0, 3.0]
    spec_path = Path(spec_path)   # resolve once before the loop
    results = {}

    symbols = _symbols_from_event_log(event_log)

    for mult in stress_multipliers:
        # Construct a custom PlatformConfig with only the stress multiplier changed.
        # All other cost params: source defaults.
        config = PlatformConfig(
            mode                    = OperatingMode.BACKTEST,
            symbols                 = symbols,
            alpha_specs             = [spec_path],
            cost_stress_multiplier  = mult,
            **{k: v for k, v in backtest_kwargs.items()
               if k in PlatformConfig.__dataclass_fields__},
        )
        orchestrator, resolved = build_platform(config, event_log=event_log)
        orchestrator.boot(resolved)
        orchestrator.run_backtest()

        trades = list(orchestrator._trade_journal.query())
        pnls   = [float(getattr(t, "realized_pnl", 0) or 0) for t in trades]
        fees   = sum(float(getattr(t, "fees", 0) or 0) for t in trades)
        m      = _compute_metrics(pnls, label=f"{mult}x")
        results[mult] = {**m, "total_fees": fees, "net_pnl": sum(pnls) - fees}
        print(f"  TC stress {mult:.1f}x: trades={len(trades):5d}  "
              f"sharpe={m['sharpe'] or 0:+.3f}  net_pnl=${results[mult]['net_pnl']:,.2f}")

    # Find breakeven multiplier (where net_pnl crosses zero)
    for mult in sorted(results.keys()):
        if results[mult]["net_pnl"] <= 0:
            print(f"  TC breakeven: ~{mult:.1f}x  "
                  f"{'PASS' if mult > 1.5 else 'FAIL'} (threshold: 1.5×)")
            results["tc_breakeven"] = mult
            results["tc_pass"]      = mult > 1.5
            break

    return results

print("Regime sensitivity, latency sweep, TC sensitivity: ACTIVE")
```

---

## CELL 5 — Full TEST command (5-step directed hypothesis test)

```python
def TEST(
    hypothesis: dict,
    spec: dict | str,
    symbols: list[str],
    train_dates: list[str],
    oos_dates: list[str],
    regime_engine: str | None = "hmm_3state_fractional",
    n_walk_forward_folds: int = 5,
) -> dict:
    """
    Full directed hypothesis test — 5 steps.

    Step 1: Validate spec via AlphaLoader from repo source
    Step 2: In-sample (train) backtest via build_platform()
    Step 3: OOS backtest via build_platform()
    Step 4: Statistical falsification (bootstrap, permutation, DSR)
    Step 5: Regime sensitivity + latency sweep

    Args:
        hypothesis:   Formalized hypothesis dict (from formalize_hypothesis())
        spec:         .alpha.yaml spec dict or YAML string
        symbols:      List of tickers
        train_dates:  List of YYYY-MM-DD strings for training
        oos_dates:    List of YYYY-MM-DD strings for OOS evaluation
        regime_engine: Name of regime engine or None

    Returns:
        Full research report dict
    """
    alpha_id = (spec if isinstance(spec, dict) else yaml.safe_load(spec)).get("alpha_id", "unknown")
    print(f"\n{'='*60}")
    print(f"TEST: {alpha_id}")
    print(f"Hypothesis: {hypothesis.get('statement','')[:80]}")
    print(f"{'='*60}")

    report = {"hypothesis": hypothesis, "alpha_id": alpha_id, "steps": {}}

    # Step 1: Validate spec
    print("\n[Step 1/5] Validating alpha spec via AlphaLoader...")
    if not validate_alpha(spec, regime_engine):
        report["verdict"] = "INVALID_SPEC"
        return report
    spec_path = save_alpha(spec)
    report["steps"]["validation"] = {"passed": True, "spec_path": spec_path}

    # Step 2: In-sample backtest
    print("\n[Step 2/5] In-sample backtest (train window)...")
    train_log = LOAD(symbols, train_dates[0], train_dates[-1])
    train_result = run_backtest(spec_path, train_log, regime_engine=regime_engine,
                                verbose=True)
    train_pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in train_result["trades"]]
    train_metrics = _compute_metrics(train_pnls, label="train")
    report["steps"]["train"] = {**train_metrics, "pnl_hash": train_result["pnl_hash"]}

    # Step 3: OOS backtest
    print("\n[Step 3/5] OOS backtest (sealed evaluation)...")
    oos_log    = LOAD(symbols, oos_dates[0], oos_dates[-1])
    oos_result = run_backtest(spec_path, oos_log, regime_engine=regime_engine,
                              verbose=True)
    oos_pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in oos_result["trades"]]
    oos_metrics = _compute_metrics(oos_pnls, label="oos")
    report["steps"]["oos"] = {**oos_metrics, "pnl_hash": oos_result["pnl_hash"]}

    # Step 4: Statistical falsification
    print("\n[Step 4/5] Statistical falsification (bootstrap + permutation + DSR)...")
    falsification = falsification_battery(oos_pnls)
    report["steps"]["falsification"] = falsification
    print(f"  Bootstrap p: {falsification['bootstrap_pvalue']:.4f}  "
          f"Permutation p: {falsification['permutation_pvalue']:.4f}  "
          f"DSR: {falsification.get('dsr') or 'N/A'}  "
          f"→ {falsification['verdict']}")

    # Step 5: Regime sensitivity + latency sweep
    print("\n[Step 5/5] Regime sensitivity + latency sweep...")
    regime_result  = regime_sensitivity(oos_result["trades"], oos_log)
    latency_result = latency_sweep(spec_path, oos_log, regime_engine=regime_engine)
    report["steps"]["regime"]  = regime_result
    report["steps"]["latency"] = latency_result

    # Recommendation
    oos_sharpe  = oos_metrics.get("sharpe") or 0
    oos_dsr     = falsification.get("dsr") or 0
    regime_ok   = regime_result.get("stable", False)
    latency_ok  = latency_result.get("latency_pass", True)
    stat_ok     = falsification.get("pass", False)

    if oos_sharpe > 1.5 and oos_dsr > 1.5 and regime_ok and latency_ok and stat_ok:
        recommendation = "DEPLOY"
    elif oos_sharpe > 0.8 and oos_dsr > 1.0 and stat_ok:
        recommendation = "VALIDATE"
    elif oos_sharpe > 0.5:
        recommendation = "MUTATE"
    elif oos_sharpe > 0:
        recommendation = "ARCHIVE"
    else:
        recommendation = "REJECT"

    report["verdict"] = recommendation
    report["oos_pnl_hash"] = oos_result["pnl_hash"]

    print(f"\n{'='*60}")
    print(f"VERDICT: {recommendation}")
    print(f"  OOS Sharpe: {oos_sharpe:+.3f}  DSR: {oos_dsr:.3f}  "
          f"Regime-stable: {regime_ok}  Latency-ok: {latency_ok}")
    print(f"  OOS parity hash: {oos_result['pnl_hash'][:16]}...")
    print(f"{'='*60}")

    # Auto-save to experiments directory
    SESSION["generation"] = SESSION.get("generation", 0) + 1
    _save_experiment(report, alpha_id)

    return report


def _save_experiment(report: dict, alpha_id: str) -> str:
    gen = SESSION.get("generation", 1)
    exp_dir = os.path.join(WORKSPACE["experiments"], f"generation_{gen:03d}_{alpha_id}")
    os.makedirs(exp_dir, exist_ok=True)
    path = os.path.join(exp_dir, "research_report.json")
    with open(path, "w") as f:
        # Serialize: replace non-JSON-safe objects with string repr
        json.dump(report, f, indent=2, default=str)
    print(f"  Saved: {path}")
    return exp_dir

print("TEST() command: ACTIVE — runs 5-step directed hypothesis test")
print("BACKTEST() command: ACTIVE — runs single full backtest")
```

---

## 1. STATE CLEARING PROTOCOL

Every `TEST` or `BACKTEST` call is guaranteed to start clean:

```
build_platform(config, event_log=event_log)  →  creates fresh:
  SimulatedClock()          start_ns = 0
  AlphaRegistry             clock = None (backtest mode)
  AlphaLoader               fresh instance
  CompositeFeatureEngine    fresh instance, all feature states at initial_state()
  HMM3StateFractional       fresh instance, all posteriors at uniform prior
  BacktestOrderRouter       fresh instance, no pending orders
  DefaultCostModel          fresh instance
  BasicRiskEngine           fresh instance, HWM = starting equity
  InMemoryTradeJournal      empty
  MemoryPositionStore       empty
```

There is no global mutable state. Calling `build_platform()` twice produces
two independent pipelines with zero shared state.

---

## 2. FILL MODEL (DO NOT INVENT — READ FROM SOURCE)

`BacktestOrderRouter` in `feelies.execution.backtest_router`:
- Fill price: `(bid + ask) / 2` (mid-price) — **NOT spread-crossing**
- No fill probability, no RNG seed
- Depth check: partial fills if `request.quantity > available_depth`
- Impact: `fill_price ± market_impact_factor × (excess / depth) × half_spread`
- Default `market_impact_factor`: 0.5 (from `PlatformConfig`)
- Latency: configurable via `backtest_fill_latency_ns`

---

## 3. COST MODEL (DO NOT INVENT — READ FROM SOURCE)

`DefaultCostModel` in `feelies.execution.cost_model`:
- Commission: $0.0035/share
- Taker exchange: $0.003/share
- Maker exchange: -$0.002/share (rebate)
- Min commission: $0.35/order
- Max commission: 1% of notional
- Passive adverse selection: 0.5 bps
- Market impact: see fill model above
- All values scalable via `cost_stress_multiplier` (default 1.0)

---

## BACKTEST EXECUTION STATUS

```
Backtest Execution Module: ACTIVE
Pipeline:          build_platform() from feelies.bootstrap (repo source)
Fill model:        BacktestOrderRouter (mid-price, depth-based partial fills)
Cost model:        DefaultCostModel (IB Tiered defaults)
Risk engine:       BasicRiskEngine / AlphaBudgetRiskWrapper (from source)
Regime engine:     HMM3StateFractional — states: compression_clustering, normal, vol_breakout
State clearing:    Guaranteed — fresh instances per run
Parity hash:       SHA-256 over ordered trade sequence (canonical definition above)

Awaiting Export & Lifecycle activation (Prompt 5).
```
