# MODULE 4 — BACKTEST EXECUTION: PIPELINE, STATISTICS & REGIME ANALYSIS

## ACTIVATION DIRECTIVE

The Backtest Execution module activates with this block. This module runs
every backtest through the repo's actual pipeline — `build_platform()` from
`feelies.bootstrap` — with no invented fill model, no invented cost
constants, no invented risk limits.

All execution behavior comes from repo source. Depending on the loaded alpha,
that means the live sensor, horizon, signal, composition, execution, and risk
path from current main. The only input the kernel provides is a populated
`InMemoryEventLog` (from Module 2) and a valid `.alpha.yaml` spec (from
Module 3).

`RUN_ACTIVE()` and `SELFCHECK_ADOPTION()` defined here both call `ADOPT`,
which is defined in Module 6. They will raise `NameError` until Module 6 is
loaded; every other command in this module is fully standalone.

---

## CELL 1 — Core backtest runner (uses build_platform from repo source)

```python
import yaml, hashlib, json, os, pathlib, math, statistics, datetime
from pathlib import Path
from dataclasses import replace as _dc_replace
from feelies.bootstrap import build_platform
from feelies.core.platform_config import PlatformConfig, OperatingMode
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.events import Signal

# -------------------------------------------------------------------
# State clearing is automatic: every call to run_backtest() creates
# entirely fresh instances — PlatformConfig, InMemoryEventLog, all
# engines required by the loaded alpha (AlphaRegistry, SimulatedClock,
# SensorRegistry / HorizonAggregator / HorizonSignalEngine /
# CompositionEngine when applicable, BacktestOrderRouter,
# BasicRiskEngine, HMM3StateFractional).
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


# -------------------------------------------------------------------
# Canonical config loader.
#
# CRITICAL FOR PARITY:
#   scripts/run_backtest.py loads platform.yaml from the repo root.
#   Grok MUST do the same — otherwise PlatformConfig dataclass defaults
#   (latency=0, cooldown=0, no stop-loss, account_equity=1_000_000) will
#   silently override platform.yaml values (latency=30ms, cooldown=5000,
#   stop-loss=0.005, account_equity=100_000) and break parity hashes.
#
# The PLATFORM_YAML_PATH global is set in Prompt 1 from the same commit
# SHA the source ZIP was extracted from. Single source of truth.
# -------------------------------------------------------------------
def _load_platform_config(
    spec_path: Path | None,
    event_log: InMemoryEventLog,
    overrides: dict | None = None,
    use_active_dir: bool = False,
) -> PlatformConfig:
    """
    Build a backtest PlatformConfig identical to what scripts/run_backtest.py uses.

    Steps:
      1. Load PLATFORM_YAML_PATH via PlatformConfig.from_yaml — captures every
         execution-control field defined in platform.yaml.
      2. Replace mode=BACKTEST, symbols=<from event_log>, and the alpha
         ingress fields per `use_active_dir`:
           - False (default): explicit-spec ingress —
               alpha_spec_dir = None
               alpha_specs    = [spec_path]
             Used by TEST/EXPLORE/EVOLVE because they iterate over many
             specs that don't belong in a "live" directory.
           - True: production-discovery ingress —
               alpha_spec_dir = ALPHA_ACTIVE_DIR/<active_alpha_id>
               alpha_specs    = []
             Mirrors `python scripts/run_backtest.py` exactly: the platform
             scans the same directory layout the local repo uses for live
             trading. Requires SESSION["active_alpha_id"] to be set (via
             ADOPT — Prompt 6 — or EXPORT — Prompt 5).
      3. Apply caller overrides last (e.g. cost_stress_multiplier for sweeps).

    Any other field — backtest_fill_latency_ns, signal_entry_cooldown_ticks,
    stop_loss_per_share, trail_*, cost_*, passive_*, platform_min_order_shares,
    signal_min_edge_cost_ratio — comes verbatim from platform.yaml.

    SELFCHECK_ADOPTION (below) asserts the two ingress paths produce
    bit-identical pnl_hash + config_hash for the same spec, so this branch
    is observably equivalence-preserving.
    """
    assert "PLATFORM_YAML_PATH" in globals(), (
        "PLATFORM_YAML_PATH not set — re-paste Prompt 1. "
        "Bootstrap must extract platform.yaml from the same SHA as the source."
    )
    base = PlatformConfig.from_yaml(PLATFORM_YAML_PATH)

    symbols = _symbols_from_event_log(event_log)
    assert symbols, "event_log contains no events with symbols — run LOAD() first"

    if use_active_dir:
        active_id = SESSION.get("active_alpha_id")
        assert active_id, (
            "use_active_dir=True but SESSION['active_alpha_id'] is None. "
            "Call ADOPT(spec) first (Prompt 6) or run any MUTATE/RECOMBINE/EVOLVE."
        )
        active_dir = Path(ALPHA_ACTIVE_DIR) / active_id
        assert active_dir.is_dir(), (
            f"Active alpha directory missing: {active_dir}. "
            f"SESSION says active_alpha_id={active_id!r} but the dir was wiped. "
            f"Re-call ADOPT(spec) to repopulate."
        )
        config = _dc_replace(
            base,
            mode           = OperatingMode.BACKTEST,
            symbols        = symbols,
            alpha_spec_dir = active_dir,
            alpha_specs    = [],
        )
    else:
        assert spec_path is not None, (
            "use_active_dir=False requires an explicit spec_path."
        )
        config = _dc_replace(
            base,
            mode           = OperatingMode.BACKTEST,
            symbols        = symbols,
            alpha_spec_dir = None,
            alpha_specs    = [Path(spec_path)],
        )

    if overrides:
        invalid = set(overrides) - set(PlatformConfig.__dataclass_fields__)
        assert not invalid, f"Unknown PlatformConfig overrides: {sorted(invalid)}"
        config = _dc_replace(config, **overrides)

    config.validate()
    return config


def run_backtest(
    spec_path: str | Path | None,
    event_log: InMemoryEventLog,
    regime_engine: str | None = None,   # None → use platform.yaml value
    config_overrides: dict | None = None,
    verbose: bool = True,
    use_active_dir: bool = False,
) -> dict:
    """
    Run a backtest through the repo's actual pipeline.

    This is the ONLY backtest path. No custom fill logic. No invented constants.
    All execution behavior is loaded from platform.yaml (the same file the local
    `python scripts/run_backtest.py` consumes by default), so a Grok backtest is
    a faithful mirror of the local one.

    Args:
        spec_path:        Path to .alpha.yaml file (from save_alpha()). Required
                          unless use_active_dir=True, in which case it is ignored
                          and the spec is discovered through alpha_spec_dir.
        event_log:        Pre-populated InMemoryEventLog from LOAD()
        regime_engine:    Override the regime_engine field of platform.yaml
                          (None = use whatever platform.yaml specifies, which is
                           "hmm_3state_fractional" by default)
        config_overrides: Dict of PlatformConfig field → value, applied AFTER
                          loading platform.yaml. Use sparingly and ONLY for
                          deliberate stress sweeps (e.g. {"cost_stress_multiplier": 2.0}
                          or {"backtest_fill_latency_ns": 100_000_000}).
        verbose:          Print summary after run
        use_active_dir:   If True, ignore spec_path and load via the production
                          discovery path (alpha_spec_dir = ALPHA_ACTIVE_DIR/<active_alpha_id>).
                          Requires SESSION["active_alpha_id"] (set by ADOPT/EXPORT).
                          This is the path scripts/run_backtest.py uses; verifies
                          end-to-end that the adopted spec is what the platform
                          would scan in production.

    Returns:
        dict with keys:
            trade_count, total_pnl, net_pnl, total_fees, gross_pnl,
            pnl_hash       — SHA-256 over trade sequence (matches local script)
            config_hash    — SHA-256 of resolved PlatformConfig snapshot
            parity_hash    — SHA-256(pnl_hash || config_hash) — single comparator
            trades, positions, config_snapshot, orchestrator
    """
    if not use_active_dir:
        spec_path = Path(spec_path)
        assert spec_path.exists(), f"Alpha spec not found: {spec_path}"
    assert event_log is not None, "event_log is None — run LOAD() first"

    overrides = dict(config_overrides or {})
    if regime_engine is not None:
        overrides.setdefault("regime_engine", regime_engine)

    config = _load_platform_config(spec_path, event_log, overrides,
                                   use_active_dir=use_active_dir)

    # Fresh platform instance — all engines created new for this run
    orchestrator, resolved_config = build_platform(config, event_log=event_log)
    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    # --- Extract results ---
    journal   = orchestrator._trade_journal
    positions = orchestrator._positions.all_positions()
    records   = list(journal.query())

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

    # Three hashes — see CANONICAL HASH CONTRACT below.
    pnl_hash    = _compute_parity_hash(records)
    config_hash = _compute_config_hash(resolved_config)
    parity_hash = _compute_combined_parity_hash(pnl_hash, config_hash)

    result = {
        "trade_count":     len(records),
        "total_pnl":       total_realized,
        "gross_pnl":       gross_pnl,
        "total_fees":      total_fees,
        "net_pnl":         net_pnl,
        "unrealized_pnl":  total_unrealized,
        "pnl_hash":        pnl_hash,
        "config_hash":     config_hash,
        "parity_hash":     parity_hash,
        "trades":          records,
        "positions":       positions,
        "config_snapshot": resolved_config.snapshot() if hasattr(resolved_config, "snapshot") else None,
        "orchestrator":    orchestrator,
    }

    if verbose:
        # When use_active_dir=True we have no spec_path; surface the active id instead.
        display = (Path(ALPHA_ACTIVE_DIR) / SESSION["active_alpha_id"]
                   if use_active_dir else spec_path)
        _print_backtest_summary(result, display)

    return result


# -------------------------------------------------------------------
# CANONICAL HASH CONTRACT
#
# Both Grok and scripts/run_backtest.py MUST emit identical strings for
# the same alpha + same date range + same platform.yaml.
#
# pnl_hash    = SHA256(JSON([{order_id, symbol, side, quantity,
#                             fill_price, realized_pnl}]))
# config_hash = PlatformConfig.snapshot().checksum  (already SHA-256)
# parity_hash = SHA256(pnl_hash + ":" + config_hash)
#
# pnl_hash answers "did we produce the same trades?"
# config_hash answers "were we configured the same way?"
# parity_hash is the single comparator that answers both at once.
# -------------------------------------------------------------------

def _compute_parity_hash(records: list) -> str:
    """SHA-256 over ordered trade sequence — matches scripts/run_backtest.py."""
    trade_seq = [
        {
            "order_id":     str(getattr(r, "order_id",         "")),
            "symbol":       str(getattr(r, "symbol",            "")),
            "side":         str(getattr(r, "side",              "")).split(".")[-1],
            "quantity":     int(getattr(r, "filled_quantity",   0)),
            "fill_price":   str(getattr(r, "fill_price",       "0")),
            "realized_pnl": str(getattr(r, "realized_pnl",     "0")),
        }
        for r in records
    ]
    payload = json.dumps(trade_seq, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_config_hash(config) -> str:
    """SHA-256 of the resolved PlatformConfig snapshot (excluding non-deterministic fields)."""
    snap = config.snapshot()
    return snap.checksum


def _compute_combined_parity_hash(pnl_hash: str, config_hash: str) -> str:
    """SHA-256(pnl_hash + ':' + config_hash). Single comparator binding trades to config."""
    return hashlib.sha256(f"{pnl_hash}:{config_hash}".encode("utf-8")).hexdigest()


def _print_backtest_summary(result: dict, spec_path) -> None:
    print(f"\n{'='*60}")
    print(f"BACKTEST SUMMARY: {pathlib.Path(spec_path).stem}")
    print(f"{'='*60}")
    print(f"  Trades:       {result['trade_count']}")
    print(f"  Gross PnL:    ${result['gross_pnl']:,.4f}")
    print(f"  Fees:         ${result['total_fees']:,.4f}")
    print(f"  Net PnL:      ${result['net_pnl']:,.4f}")
    print(f"  Unrealized:   ${result['unrealized_pnl']:,.4f}")
    print(f"  pnl_hash:     {result['pnl_hash'][:16]}...")
    print(f"  config_hash:  {result['config_hash'][:16]}...")
    print(f"  parity_hash:  {result['parity_hash'][:16]}...")
    print(f"{'='*60}\n")


# Convenience command
def BACKTEST(alpha_id: str, event_log: InMemoryEventLog | None = None, **kwargs) -> dict:
    """
    Run a full backtest for a saved alpha (explicit-spec ingress).

    Usage:
        result = BACKTEST("my_alpha")
        result = BACKTEST("my_alpha", event_log=LOAD("AAPL","2026-01-15"))
        result = BACKTEST("my_alpha", config_overrides={"cost_stress_multiplier": 1.5})

    See RUN_ACTIVE() to backtest the currently adopted alpha via the
    production discovery path (alpha_spec_dir).
    """
    event_log = event_log or SESSION.get("event_log")
    assert event_log is not None, "No event_log in session. Call LOAD() first."
    spec_path = os.path.join(ALPHA_DEV_DIR, alpha_id, f"{alpha_id}.alpha.yaml")
    assert os.path.exists(spec_path), f"Alpha not found: {spec_path}"
    return run_backtest(spec_path, event_log, **kwargs)


def RUN_ACTIVE(event_log: InMemoryEventLog | None = None, **kwargs) -> dict:
    """
    Backtest the currently adopted alpha via the PRODUCTION discovery path.

    Configures alpha_spec_dir = ALPHA_ACTIVE_DIR/<active_alpha_id> and lets
    bootstrap._load_alphas scan it — exactly what scripts/run_backtest.py
    does with `platform.yaml`'s alpha_spec_dir field on the local side.

    This is the closing edge of the autonomy loop:
        MUTATE → ADOPT (auto) → RUN_ACTIVE → backtest the live spec

    Usage:
        spec   = MUTATE(parent, "perturb_param", seed=1)   # auto-ADOPTs
        result = RUN_ACTIVE()                              # via alpha_spec_dir

    Returns the same dict run_backtest() does, including all three hashes.
    """
    event_log = event_log or SESSION.get("event_log")
    assert event_log is not None, "No event_log in session. Call LOAD() first."
    aid = SESSION.get("active_alpha_id")
    assert aid, (
        "No active alpha. Call ADOPT(spec) first (Prompt 6) — or any "
        "MUTATE/RECOMBINE/EVOLVE auto-ADOPTs."
    )
    return run_backtest(spec_path=None, event_log=event_log,
                        use_active_dir=True, **kwargs)


# -------------------------------------------------------------------
# SELFCHECK — Inv-5 (deterministic replay) enforcement.
#
# Same alpha + same event_log + same config MUST produce identical trades.
# Run this immediately after defining a new alpha, BEFORE trusting any of
# its statistics.
# -------------------------------------------------------------------
def SELFCHECK(alpha_id: str, event_log: InMemoryEventLog | None = None,
              n_replays: int = 2, **kwargs) -> dict:
    """
    Run the same backtest n_replays times and assert identical pnl_hash + config_hash.

    Returns the diagnostic dict. Raises AssertionError on any divergence.
    A failure here means the system has hidden state, RNG, or wall-clock
    dependence — Inv-5 is broken and no statistical claims are valid.
    """
    event_log = event_log or SESSION.get("event_log")
    assert event_log is not None, "No event_log in session. Call LOAD() first."
    assert n_replays >= 2, "n_replays must be >= 2"

    print(f"\n{'='*60}")
    print(f"SELFCHECK: {alpha_id}  (n_replays={n_replays})")
    print(f"{'='*60}")

    hashes = []
    for i in range(n_replays):
        r = BACKTEST(alpha_id, event_log=event_log, verbose=False, **kwargs)
        hashes.append((r["pnl_hash"], r["config_hash"], r["parity_hash"], r["trade_count"]))
        print(f"  Replay {i+1}: trades={r['trade_count']:5d}  "
              f"pnl={r['pnl_hash'][:12]}  cfg={r['config_hash'][:12]}  "
              f"parity={r['parity_hash'][:12]}")

    pnl_set    = {h[0] for h in hashes}
    config_set = {h[1] for h in hashes}
    parity_set = {h[2] for h in hashes}
    trades_set = {h[3] for h in hashes}

    ok = (len(pnl_set) == 1 and len(config_set) == 1 and len(parity_set) == 1)

    print(f"  unique pnl_hash:    {len(pnl_set)}  {'OK' if len(pnl_set)==1 else 'FAIL'}")
    print(f"  unique config_hash: {len(config_set)}  {'OK' if len(config_set)==1 else 'FAIL'}")
    print(f"  unique trade_count: {len(trades_set)}  {'OK' if len(trades_set)==1 else 'FAIL'}")
    print(f"  Inv-5 (deterministic replay): {'PASS' if ok else 'FAIL'}")
    print(f"{'='*60}")

    assert ok, (
        f"SELFCHECK FAILED for {alpha_id} — Inv-5 (deterministic replay) is broken.\n"
        f"  pnl_hashes:    {pnl_set}\n"
        f"  config_hashes: {config_set}\n"
        f"Statistical results from this alpha cannot be trusted until this is fixed."
    )
    # Record pass in SESSION so EXPORT can stamp the registry's
    # `selfcheck_passed` column without re-running the backtests.
    SESSION.setdefault("selfcheck", {})[alpha_id] = {
        "passed":     True,
        "n_replays":  n_replays,
        "pnl_hash":   hashes[0][0],
        "config_hash":hashes[0][1],
        "parity_hash":hashes[0][2],
        "verified_at": datetime.datetime.utcnow().isoformat(),
    }
    return {
        "alpha_id":    alpha_id,
        "n_replays":   n_replays,
        "deterministic": True,
        "pnl_hash":    hashes[0][0],
        "config_hash": hashes[0][1],
        "parity_hash": hashes[0][2],
    }

# -------------------------------------------------------------------
# SELFCHECK_ADOPTION — ingress-path equivalence enforcement.
#
# Without this, Grok's backtest path (alpha_specs=[spec_path]) and the
# local platform's path (alpha_spec_dir scan) are observably distinct
# code branches inside bootstrap._load_alphas. They SHOULD produce
# identical results because they both end at AlphaLoader.load(), but
# "should" is not "verified". This check converts the assertion into
# evidence on every adoption.
#
# Procedure:
#   1. Run backtest via explicit-spec ingress on the supplied spec.
#   2. Run backtest via alpha_spec_dir ingress on the SAME spec
#      (after a transient ADOPT).
#   3. Assert pnl_hash and config_hash are bit-identical.
#
# A failure here is a defect — most likely cause is a config field that
# differs between the two _dc_replace branches in _load_platform_config.
# -------------------------------------------------------------------
def SELFCHECK_ADOPTION(spec_path: str | Path,
                       event_log: InMemoryEventLog | None = None,
                       **kwargs) -> dict:
    """
    Prove that explicit-spec ingress and alpha_spec_dir ingress yield
    bit-identical pnl_hash + config_hash for the same spec.

    Closes the parity asymmetry between Grok's TEST/EXPLORE path and the
    local platform's `alpha_spec_dir` discovery path. Run once after any
    change to _load_platform_config or to bootstrap._load_alphas.
    """
    event_log = event_log or SESSION.get("event_log")
    assert event_log is not None, "No event_log in session. Call LOAD() first."
    spec_path = Path(spec_path)
    assert spec_path.exists(), f"Spec not found: {spec_path}"

    # Need ADOPT (Prompt 6) to populate ALPHA_ACTIVE_DIR.
    assert "ADOPT" in globals(), (
        "ADOPT not loaded — paste Prompt 6 first. SELFCHECK_ADOPTION needs "
        "ADOPT to populate ALPHA_ACTIVE_DIR for the discovery-path leg."
    )

    print(f"\n{'='*60}")
    print(f"SELFCHECK_ADOPTION: {spec_path.name}")
    print(f"{'='*60}")

    # Snapshot pre-existing active state so we can restore it afterwards.
    prior_active = SESSION.get("active_alpha_id")

    # Leg A — explicit-spec ingress (TEST/BACKTEST default).
    a = run_backtest(spec_path, event_log, verbose=False, **kwargs)
    print(f"  explicit-spec   trades={a['trade_count']:5d}  "
          f"pnl={a['pnl_hash'][:12]}  cfg={a['config_hash'][:12]}")

    # Leg B — alpha_spec_dir ingress (RUN_ACTIVE / scripts/run_backtest.py).
    spec_dict = _yaml_safe_load_path(spec_path)
    ADOPT(spec_dict, source="SELFCHECK_ADOPTION")
    b = run_backtest(spec_path=None, event_log=event_log, verbose=False,
                     use_active_dir=True, **kwargs)
    print(f"  alpha_spec_dir  trades={b['trade_count']:5d}  "
          f"pnl={b['pnl_hash'][:12]}  cfg={b['config_hash'][:12]}")

    # Restore prior active state — SELFCHECK_ADOPTION must not leak.
    if prior_active is None:
        SESSION["active_alpha_id"] = None
    # (We deliberately do NOT remove the new active dir; ADOPT's atomic-swap
    #  semantics already replaced whatever was there, and the user can ADOPT
    #  again to re-pin their intended live spec.)

    pnl_ok    = (a["pnl_hash"]    == b["pnl_hash"])
    config_ok = (a["config_hash"] == b["config_hash"])
    trades_ok = (a["trade_count"] == b["trade_count"])

    print(f"  pnl_hash    match: {'OK' if pnl_ok    else 'FAIL'}")
    print(f"  config_hash match: {'OK' if config_ok else 'FAIL'}")
    print(f"  trade_count match: {'OK' if trades_ok else 'FAIL'}")
    print(f"  Ingress-path equivalence: {'PASS' if (pnl_ok and config_ok) else 'FAIL'}")
    print(f"{'='*60}")

    assert pnl_ok and config_ok, (
        f"SELFCHECK_ADOPTION FAILED — Grok's ingress paths diverge for the same spec.\n"
        f"  explicit-spec:   pnl={a['pnl_hash']}  cfg={a['config_hash']}\n"
        f"  alpha_spec_dir:  pnl={b['pnl_hash']}  cfg={b['config_hash']}\n"
        f"Most likely cause: _load_platform_config branches differ in a config "
        f"field. Diff `a['config_snapshot']` vs `b['config_snapshot']`."
    )
    return {
        "explicit_pnl_hash":    a["pnl_hash"],
        "active_pnl_hash":      b["pnl_hash"],
        "explicit_config_hash": a["config_hash"],
        "active_config_hash":   b["config_hash"],
        "match":                True,
    }


def _yaml_safe_load_path(path: Path) -> dict:
    """Load a YAML file as a dict (helper for SELFCHECK_ADOPTION)."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


print("Backtest Execution module: ACTIVE")
print("BACKTEST('alpha_id') runs the full repo pipeline via build_platform() (explicit-spec ingress)")
print("RUN_ACTIVE() runs the currently ADOPTed alpha via alpha_spec_dir (production-discovery ingress)")
print("SELFCHECK('alpha_id') asserts deterministic replay (Inv-5)")
print("SELFCHECK_ADOPTION(spec_path) asserts explicit-spec ≡ alpha_spec_dir ingress paths")
print("Config loaded from: PLATFORM_YAML_PATH (set in Prompt 1)")
```

---

## CELL 2 — CPCV backtesting (combinatorial purged cross-validation)

```python
import numpy as np
import itertools

def cpcv_backtest(
    spec_path: str | Path,
    symbols: list[str],
    all_dates: list[str],
    n_groups: int = 6,
    k_test: int = 2,
    embargo_days: int = 1,
    **backtest_kwargs,
) -> dict:
    """
    Combinatorial Purged Cross-Validation (López de Prado, 2018, Ch. 12).

    Splits `all_dates` into `n_groups` contiguous groups; every C(n_groups, k_test)
    combination of `k_test` groups becomes one test fold. Train groups adjacent
    to a test group are EMBARGOED (dropped) by `embargo_days` to prevent
    information leakage from autocorrelated features.

    Returns per-fold metrics + the distribution of OOS Sharpe ratios across
    the C(n_groups, k_test) folds. With n_groups=6, k_test=2 → 15 folds.

    Why CPCV vs walk-forward:
      - Walk-forward gives n_folds-1 ~independent OOS estimates and is biased
        toward the most recent regime.
      - CPCV uses every (n_groups choose k_test) combination, dramatically
        increasing the number of OOS observations and decoupling the
        estimate from time-direction.
      - Embargo enforces that no train sample shares feature-window overlap
        with any test sample.
    """
    assert len(all_dates) >= n_groups * 2, (
        f"Need >= {n_groups*2} trading days for CPCV with n_groups={n_groups}; "
        f"got {len(all_dates)}"
    )
    assert 1 <= k_test < n_groups, "k_test must be in [1, n_groups-1]"

    # Partition dates into n_groups contiguous groups.
    group_size = len(all_dates) // n_groups
    groups: list[list[str]] = [
        all_dates[i * group_size : (i + 1) * group_size]
        for i in range(n_groups - 1)
    ]
    groups.append(all_dates[(n_groups - 1) * group_size :])   # tail catches remainder

    fold_combinations = list(itertools.combinations(range(n_groups), k_test))
    print(f"CPCV: {n_groups} groups, k_test={k_test}, embargo={embargo_days}d "
          f"→ {len(fold_combinations)} folds")

    fold_results = []
    for fold_idx, test_group_ids in enumerate(fold_combinations):
        test_dates = []
        for gid in test_group_ids:
            test_dates.extend(groups[gid])

        # Embargo: drop the boundary days of each test group that are adjacent
        # to a train group.  Feature state computed over a trailing train window
        # leaks into the first `embargo_days` of the succeeding test group
        # (autocorrelation / warm-up); the reverse holds for the tail of a test
        # group that precedes a train group.
        #
        # Correct logic: for each test group gid, remove its leading
        # `embargo_days` when the prior group (gid-1) is a *train* group, and
        # remove its trailing `embargo_days` when the next group (gid+1) is a
        # *train* group.  We filter within test_dates — the embargo_set is
        # therefore a subset of test_dates by construction.
        test_group_set = set(test_group_ids)
        embargo_set: set[str] = set()
        for gid in test_group_ids:
            if gid > 0 and (gid - 1) not in test_group_set:
                # prior group is train: contaminated leading edge of this test group
                embargo_set.update(groups[gid][:embargo_days])
            if gid < n_groups - 1 and (gid + 1) not in test_group_set:
                # next group is train: contaminated trailing edge of this test group
                embargo_set.update(groups[gid][-embargo_days:])

        # Test fold = test groups minus embargoed boundary dates.
        test_dates = [d for d in test_dates if d not in embargo_set]
        if not test_dates:
            continue

        print(f"  Fold {fold_idx+1:2d}/{len(fold_combinations)}: "
              f"test={test_dates[0]}…{test_dates[-1]}  ({len(test_dates)} days)")

        elog = LOAD(symbols, test_dates[0], test_dates[-1])
        result = run_backtest(spec_path, elog, verbose=False, **backtest_kwargs)
        pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in result["trades"]]
        m    = _compute_metrics(pnls, label=f"fold_{fold_idx+1}")
        fold_results.append({
            **m,
            "test_groups": list(test_group_ids),
            "test_start":  test_dates[0],
            "test_end":    test_dates[-1],
            "pnl_hash":    result["pnl_hash"],
            "config_hash": result["config_hash"],
        })

    if not fold_results:
        return {"error": "No fold results — insufficient data"}

    sharpes = [f["sharpe"] for f in fold_results if f["sharpe"] is not None]
    return {
        "n_groups":         n_groups,
        "k_test":           k_test,
        "embargo_days":     embargo_days,
        "n_folds":          len(fold_results),
        "folds":            fold_results,
        "sharpe_mean":      float(np.mean(sharpes)) if sharpes else None,
        "sharpe_std":       float(np.std(sharpes))  if sharpes else None,
        "sharpe_min":       float(min(sharpes))      if sharpes else None,
        "sharpe_p10":       float(np.percentile(sharpes, 10)) if sharpes else None,
        "n_positive_folds": sum(s > 0 for s in sharpes),
        "fraction_positive": sum(s > 0 for s in sharpes) / len(sharpes) if sharpes else 0,
    }


# Deprecated rolling walk-forward — preserved for backward compat only.
# Prefer cpcv_backtest() for any decision that gates promotion.
def walk_forward_backtest(*args, **kwargs):
    """DEPRECATED: prefer cpcv_backtest(). Calls it with k_test=1 for compatibility."""
    print("DEPRECATED: walk_forward_backtest → use cpcv_backtest(k_test>=2) for proper MHT statistics.")
    spec_path = args[0] if args else kwargs.pop("spec_path")
    symbols   = args[2] if len(args) > 2 else kwargs.pop("symbols")
    dbp       = args[1] if len(args) > 1 else kwargs.pop("dates_by_partition")
    all_dates = list(dbp.get("train", [])) + list(dbp.get("validation", [])) + list(dbp.get("oos", []))
    n_folds   = kwargs.pop("n_folds", 5)
    return cpcv_backtest(spec_path, symbols, all_dates,
                         n_groups=n_folds, k_test=1,
                         embargo_days=1, **kwargs)


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

print("CPCV backtest + metrics functions: ACTIVE")
print("cpcv_backtest(spec_path, symbols, all_dates, n_groups=6, k_test=2)")
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
    n_trials: int = 1,
) -> dict:
    """
    Full statistical falsification for a candidate signal.

    Tests:
    1. Bootstrap: is mean return significantly > 0?
    2. Permutation: is signal Sharpe better than random?
    3. DSR: deflated Sharpe accounting for skew, kurtosis, n_trials.
       Pass `n_trials` = total candidates evaluated in the same family
       (e.g. EXPLORE(n=8) → n_trials=8) so DSR penalizes selection bias.

    Acceptance criteria (all must pass):
      bootstrap_pvalue < 0.05
      permutation_pvalue < 0.05
      dsr > 1.0

    For multi-hypothesis families, ALSO apply holm_correction() over the
    set of bootstrap p-values returned by this function across all candidates.

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

    # DSR (deflated Sharpe ratio, López de Prado 2014).
    # The trial-count deflation is applied inside the variance term:
    # SR_max under the null with n_trials independent estimates grows like
    # sqrt(2*log(n_trials)). We approximate by inflating the variance term.
    try:
        sk  = _skewness(trade_pnls)
        ku  = _excess_kurtosis(trade_pnls)
        # base DSR (single-trial form)
        dsr_single = sr * math.sqrt(n) / math.sqrt(
            max(1 - sk * sr + (ku / 4) * sr ** 2, 1e-10)
        )
        # multiple-trial penalty
        if n_trials > 1:
            sr_max_null = math.sqrt(2 * math.log(max(n_trials, 2)))
            dsr = (sr - sr_max_null / math.sqrt(n)) * math.sqrt(n) / math.sqrt(
                max(1 - sk * sr + (ku / 4) * sr ** 2, 1e-10)
            )
        else:
            dsr = dsr_single
    except Exception:
        dsr = None
        dsr_single = None

    passed = (
        bootstrap_pvalue   < 0.05 and
        permutation_pvalue < 0.05 and
        (dsr is not None and dsr > 1.0)
    )

    return {
        "n_trades":           n,
        "n_trials":           n_trials,
        "mean_pnl":           mu,
        "sharpe":             sr,
        "dsr":                dsr,
        "dsr_single_trial":   dsr_single,
        "bootstrap_pvalue":   bootstrap_pvalue,
        "permutation_pvalue": permutation_pvalue,
        "hit_rate":           len([p for p in trade_pnls if p > 0]) / n,
        "pass":               passed,
        "verdict":            "PASS" if passed else "FAIL",
    }


# -------------------------------------------------------------------
# Multiple-Hypothesis Testing (MHT) correction.
#
# When a family of candidates is evaluated together (EXPLORE, EVOLVE),
# the per-candidate p-values must be adjusted for selection bias before
# any "this candidate is significant" claim is made.
#
# Holm step-down is the default: uniformly more powerful than Bonferroni
# while preserving FWER ≤ alpha.  Benjamini-Hochberg (FDR) is offered as
# an alternative for large families where some false positives are
# acceptable.
# -------------------------------------------------------------------
def holm_correction(p_values: list[float], alpha: float = 0.05) -> dict:
    """
    Holm-Bonferroni step-down correction.

    Args:
        p_values: list of p-values from independent tests in the same family
        alpha:    family-wise error rate

    Returns:
        dict with:
          'q_values':    adjusted p-values (same order as input)
          'rejected':    list[bool] — True if H0 rejected at family alpha
          'n_rejected':  count of survivors
    """
    n = len(p_values)
    if n == 0:
        return {"q_values": [], "rejected": [], "n_rejected": 0}

    # Sort with original indices
    order = sorted(range(n), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]

    # Step-down: q_i = max over j<=i of (n-j) * p_(j)
    q_sorted = [0.0] * n
    running_max = 0.0
    for i, p in enumerate(sorted_p):
        adj = (n - i) * p
        running_max = max(running_max, adj)
        q_sorted[i] = min(running_max, 1.0)

    # Restore original order
    q_values = [0.0] * n
    rejected = [False] * n
    for sorted_idx, orig_idx in enumerate(order):
        q_values[orig_idx] = q_sorted[sorted_idx]
        rejected[orig_idx] = q_sorted[sorted_idx] < alpha

    return {
        "q_values":   q_values,
        "rejected":   rejected,
        "n_rejected": sum(rejected),
        "method":     "holm",
        "alpha":      alpha,
    }


def benjamini_hochberg(p_values: list[float], alpha: float = 0.10) -> dict:
    """Benjamini-Hochberg FDR control. Use when families are large (>20)."""
    n = len(p_values)
    if n == 0:
        return {"q_values": [], "rejected": [], "n_rejected": 0}

    order = sorted(range(n), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]

    # q_(i) = min over j>=i of (n / (j+1)) * p_(j) [step-up form]
    q_sorted = [0.0] * n
    running_min = 1.0
    for i in range(n - 1, -1, -1):
        adj = (n / (i + 1)) * sorted_p[i]
        running_min = min(running_min, adj)
        q_sorted[i] = min(running_min, 1.0)

    q_values = [0.0] * n
    rejected = [False] * n
    for sorted_idx, orig_idx in enumerate(order):
        q_values[orig_idx] = q_sorted[sorted_idx]
        rejected[orig_idx] = q_sorted[sorted_idx] < alpha

    return {
        "q_values":   q_values,
        "rejected":   rejected,
        "n_rejected": sum(rejected),
        "method":     "benjamini_hochberg",
        "alpha":      alpha,
    }


# -------------------------------------------------------------------
# Information Coefficient (IC) — predictive correlation between the
# alpha's signal strength at time T and realized returns over T+1..T+H.
#
# IC complements PnL-based tests by measuring whether the signal carries
# information regardless of execution. A signal with strong PnL but
# IC ≈ 0 typically owes its return to a small number of fortunate fills,
# not a real predictive edge.
# -------------------------------------------------------------------
def compute_ic(
    spec_path: str | Path,
    event_log: InMemoryEventLog,
    horizon_ticks: int = 100,
    regime_engine: str | None = None,
) -> dict:
    """
    Compute the Spearman Information Coefficient for an alpha over an event log.

    Procedure:
      1. Replay the event log via build_platform() (same pipeline as backtest).
      2. Capture every Signal emitted by the alpha (signal_strength, timestamp).
      3. Compute realized log-return over the next `horizon_ticks` quote events.
      4. IC = corr(rank(signal), rank(forward_return)) over all (signal,return) pairs.
      5. Newey-West-adjusted t-stat with lag = horizon_ticks (handles overlap).

    Returns:
        ic_mean, ic_tstat, n_pairs, horizon_ticks, hit_rate (sign agreement).
    """
    from feelies.core.events import Signal as _SignalEvt, NBBOQuote as _NBBO

    # Capture signals via a bus subscriber. We rebuild the platform with a
    # tap on the bus to record Signal events as they fire. Use the SAME
    # _load_platform_config() path as run_backtest() so the IC is computed
    # against the exact same execution config a backtest would use.
    overrides = {}
    if regime_engine is not None:
        overrides["regime_engine"] = regime_engine
    config = _load_platform_config(Path(spec_path), event_log, overrides)
    orchestrator, resolved = build_platform(config, event_log=event_log)

    captured_signals: list = []
    bus = getattr(orchestrator, "_bus", None)
    if bus is not None and hasattr(bus, "subscribe"):
        bus.subscribe(_SignalEvt, lambda e: captured_signals.append(e))

    orchestrator.boot(resolved)
    orchestrator.run_backtest()

    if not captured_signals:
        return {"ic_mean": 0.0, "ic_tstat": 0.0, "n_pairs": 0,
                "horizon_ticks": horizon_ticks,
                "error": "no signals emitted"}

    # Build per-symbol mid-price index keyed by sequence
    quotes_by_symbol: dict[str, list] = {}
    for evt in event_log.replay():
        if isinstance(evt, _NBBO):
            quotes_by_symbol.setdefault(evt.symbol, []).append(evt)

    pairs: list[tuple[float, float]] = []
    for sig in captured_signals:
        quotes = quotes_by_symbol.get(sig.symbol, [])
        if not quotes:
            continue
        # Find the quote at or after the signal time
        i0 = next((i for i, q in enumerate(quotes)
                   if q.exchange_timestamp_ns >= sig.timestamp_ns), None)
        if i0 is None or i0 + horizon_ticks >= len(quotes):
            continue
        q0  = quotes[i0]
        q1  = quotes[i0 + horizon_ticks]
        mp0 = float(q0.bid + q0.ask) / 2.0
        mp1 = float(q1.bid + q1.ask) / 2.0
        if mp0 <= 0:
            continue
        ret = math.log(mp1 / mp0)
        # Sign-aware signal magnitude: LONG positive, SHORT negative
        from feelies.core.events import SignalDirection
        sign = (1.0 if sig.direction == SignalDirection.LONG
                else -1.0 if sig.direction == SignalDirection.SHORT
                else 0.0)
        pairs.append((sign * float(getattr(sig, "strength", 1.0) or 1.0), ret))

    n = len(pairs)
    if n < 30:
        return {"ic_mean": 0.0, "ic_tstat": 0.0, "n_pairs": n,
                "horizon_ticks": horizon_ticks,
                "error": f"too few signal/return pairs: {n} < 30"}

    # Spearman = Pearson on ranks
    sigs = [p[0] for p in pairs]
    rets = [p[1] for p in pairs]
    rs = _spearman(sigs, rets)
    # Newey-West t-stat: t = IC * sqrt((n-2)/(1 - IC^2)) inflated by overlap
    overlap_factor = max(1.0, horizon_ticks ** 0.5)   # rough HAC adjustment
    if abs(rs) >= 1.0:
        t = float("inf")
    else:
        t = rs * math.sqrt((n - 2) / (1 - rs * rs)) / overlap_factor
    hit = sum(1 for s, r in pairs if (s > 0 and r > 0) or (s < 0 and r < 0))
    return {
        "ic_mean":       rs,
        "ic_tstat":      t,
        "n_pairs":       n,
        "horizon_ticks": horizon_ticks,
        "hit_rate":      hit / n,
        "method":        "spearman + Newey-West (heuristic HAC adj.)",
    }


def _spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation."""
    rx = _ranks(x)
    ry = _ranks(y)
    n  = len(x)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))
    if den_x < 1e-12 or den_y < 1e-12:
        return 0.0
    return num / (den_x * den_y)


def _ranks(values: list[float]) -> list[float]:
    """Average-rank (handles ties)."""
    indexed = sorted(enumerate(values), key=lambda p: p[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


print("falsification_battery() / holm_correction() / benjamini_hochberg() / compute_ic(): ACTIVE")
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
        # platform.yaml's latency is the baseline; we override per-step.
        # All other execution params (cooldown, costs, stops) remain canonical.
        overrides = {
            "backtest_fill_latency_ns": ns,
            **{k: v for k, v in backtest_kwargs.items()
               if k in PlatformConfig.__dataclass_fields__},
        }
        r = run_backtest(spec_path, event_log, verbose=False,
                         config_overrides=overrides)
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

    for mult in stress_multipliers:
        # platform.yaml is loaded as the base; we override ONLY the stress
        # multiplier (plus any deliberate caller overrides). Every other
        # field — cost constants, latency, cooldown, stops — stays canonical.
        overrides = {
            "cost_stress_multiplier": mult,
            **{k: v for k, v in backtest_kwargs.items()
               if k in PlatformConfig.__dataclass_fields__},
        }
        r = run_backtest(
            spec_path, event_log,
            config_overrides=overrides, verbose=False,
        )
        trades = r["trades"]
        pnls   = [float(getattr(t, "realized_pnl", 0) or 0) for t in trades]
        fees   = r["total_fees"]
        m      = _compute_metrics(pnls, label=f"{mult}x")
        results[mult] = {**m, "total_fees": fees, "net_pnl": sum(pnls) - fees}
        print(f"  TC stress {mult:.1f}x: trades={r['trade_count']:5d}  "
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

## CELL 5 — Full TEST command (7-step directed hypothesis test)

```python
def TEST(
    hypothesis: dict,
    spec: dict | str,
    symbols: list[str],
    train_dates: list[str],
    oos_dates: list[str],
    regime_engine: str | None = "hmm_3state_fractional",
    n_walk_forward_folds: int = 5,
    n_trials: int = 1,
    cpcv_groups: int = 6,
    cpcv_k_test: int = 2,
    embargo_days: int = 1,
    ic_horizon_ticks: int = 100,
) -> dict:
    """
    Full directed hypothesis test — 7 steps.

    Step 1: Validate spec via AlphaLoader from repo source
    Step 2: In-sample (train) backtest via build_platform()
    Step 3: OOS backtest via build_platform()
    Step 4: Statistical falsification (bootstrap, permutation, DSR with n_trials)
    Step 5: Regime sensitivity + latency sweep
    Step 6: Information Coefficient (IC) on OOS quotes
    Step 7: CPCV across (train + oos) — embargoed combinatorial folds

    n_trials: total candidates evaluated in this family (use sibling count from
              EXPLORE/EVOLVE) so DSR penalizes selection bias correctly.

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
    spec_dict = spec if isinstance(spec, dict) else yaml.safe_load(spec)
    alpha_id = spec_dict.get("alpha_id", "unknown")
    hypothesis_text = (
        hypothesis.get("statement")
        or hypothesis.get("mechanism")
        or spec_dict.get("hypothesis", "")
    )
    print(f"\n{'='*60}")
    print(f"TEST: {alpha_id}")
    print(f"Hypothesis: {hypothesis_text[:80]}")
    print(f"{'='*60}")

    report = {
        "hypothesis": hypothesis,
        "alpha_id": alpha_id,
        "metadata": {
            "schema_version": spec_dict.get("schema_version"),
            "layer": spec_dict.get("layer"),
            "horizon_seconds": spec_dict.get("horizon_seconds"),
            "depends_on_sensors": spec_dict.get("depends_on_sensors", []),
            "depends_on_signals": spec_dict.get("depends_on_signals", []),
            "margin_ratio": (spec_dict.get("cost_arithmetic") or {}).get("margin_ratio"),
            "trend_mechanism_family": (spec_dict.get("trend_mechanism") or {}).get("family"),
            "expected_half_life_seconds": (spec_dict.get("trend_mechanism") or {}).get("expected_half_life_seconds"),
        },
        "steps": {},
    }

    # Step 1: Validate spec
    print("\n[Step 1/7] Validating alpha spec via AlphaLoader...")
    if not validate_alpha(spec, regime_engine):
        report["verdict"] = "INVALID_SPEC"
        return report
    spec_path = save_alpha(spec)
    report["steps"]["validation"] = {"passed": True, "spec_path": spec_path}

    # Step 2: In-sample backtest
    print("\n[Step 2/7] In-sample backtest (train window)...")
    train_log = LOAD(symbols, train_dates[0], train_dates[-1])
    train_result = run_backtest(spec_path, train_log, regime_engine=regime_engine,
                                verbose=True)
    train_pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in train_result["trades"]]
    train_metrics = _compute_metrics(train_pnls, label="train")
    report["steps"]["train"] = {
        **train_metrics,
        "pnl_hash":    train_result["pnl_hash"],
        "config_hash": train_result["config_hash"],
        "parity_hash": train_result["parity_hash"],
    }

    # Step 3: OOS backtest
    print("\n[Step 3/7] OOS backtest (sealed evaluation)...")
    oos_log    = LOAD(symbols, oos_dates[0], oos_dates[-1])
    oos_result = run_backtest(spec_path, oos_log, regime_engine=regime_engine,
                              verbose=True)
    oos_pnls = [float(getattr(t, "realized_pnl", 0) or 0) for t in oos_result["trades"]]
    oos_metrics = _compute_metrics(oos_pnls, label="oos")
    report["steps"]["oos"] = {
        **oos_metrics,
        "pnl_hash":    oos_result["pnl_hash"],
        "config_hash": oos_result["config_hash"],
        "parity_hash": oos_result["parity_hash"],
    }

    # Step 4: Statistical falsification (DSR with n_trials penalty)
    print(f"\n[Step 4/7] Statistical falsification (bootstrap + permutation + DSR, n_trials={n_trials})...")
    falsification = falsification_battery(oos_pnls, n_trials=n_trials)
    report["steps"]["falsification"] = falsification
    print(f"  Bootstrap p: {falsification['bootstrap_pvalue']:.4f}  "
          f"Permutation p: {falsification['permutation_pvalue']:.4f}  "
          f"DSR: {falsification.get('dsr') or 'N/A'}  "
          f"→ {falsification['verdict']}")

    # Step 5: Regime sensitivity + latency sweep
    print("\n[Step 5/7] Regime sensitivity + latency sweep...")
    regime_result  = regime_sensitivity(oos_result["trades"], oos_log)
    latency_result = latency_sweep(spec_path, oos_log, regime_engine=regime_engine)
    report["steps"]["regime"]  = regime_result
    report["steps"]["latency"] = latency_result

    # Step 6: Information Coefficient — predictive correlation regardless of fills
    print(f"\n[Step 6/7] Information Coefficient on OOS (horizon={ic_horizon_ticks} ticks)...")
    try:
        ic_result = compute_ic(spec_path, oos_log,
                               horizon_ticks=ic_horizon_ticks,
                               regime_engine=regime_engine)
        report["steps"]["ic"] = ic_result
        ic_mean  = ic_result.get("ic_mean") or 0
        ic_t     = ic_result.get("ic_tstat") or 0
        print(f"  IC: {ic_mean:+.4f}  t-stat: {ic_t:+.2f}  "
              f"n={ic_result.get('n_pairs',0)}  "
              f"hit={ic_result.get('hit_rate',0):.1%}")
    except Exception as e:
        ic_result = {"ic_mean": 0.0, "ic_tstat": 0.0, "error": str(e)}
        report["steps"]["ic"] = ic_result
        print(f"  IC computation failed: {e}")

    # Step 7: CPCV — combinatorial purged cross-validation
    all_dates = list(train_dates) + list(oos_dates)
    if len(all_dates) >= cpcv_groups * 2:
        print(f"\n[Step 7/7] CPCV (n_groups={cpcv_groups}, k_test={cpcv_k_test}, embargo={embargo_days}d)...")
        try:
            cpcv_result = cpcv_backtest(
                spec_path, symbols, all_dates,
                n_groups=cpcv_groups, k_test=cpcv_k_test,
                embargo_days=embargo_days, regime_engine=regime_engine,
            )
            report["steps"]["cpcv"] = cpcv_result
            print(f"  CPCV folds={cpcv_result.get('n_folds')}  "
                  f"sharpe_mean={cpcv_result.get('sharpe_mean') or 0:+.3f}  "
                  f"sharpe_p10={cpcv_result.get('sharpe_p10') or 0:+.3f}  "
                  f"frac_positive={cpcv_result.get('fraction_positive',0):.1%}")
        except Exception as e:
            cpcv_result = {"error": str(e)}
            report["steps"]["cpcv"] = cpcv_result
            print(f"  CPCV failed: {e}")
    else:
        cpcv_result = {"error": f"insufficient days for CPCV (need >= {cpcv_groups*2})"}
        report["steps"]["cpcv"] = cpcv_result
        print(f"\n[Step 7/7] CPCV skipped — {cpcv_result['error']}")

    # Recommendation
    oos_sharpe  = oos_metrics.get("sharpe") or 0
    oos_dsr     = falsification.get("dsr") or 0
    regime_ok   = regime_result.get("stable", False)
    latency_ok  = latency_result.get("latency_pass", True)
    stat_ok     = falsification.get("pass", False)
    ic_ok       = abs(ic_result.get("ic_tstat") or 0) >= 2.0
    cpcv_ok     = (cpcv_result.get("fraction_positive") or 0) >= 0.60

    if oos_sharpe > 1.5 and oos_dsr > 1.5 and regime_ok and latency_ok and stat_ok and ic_ok and cpcv_ok:
        recommendation = "DEPLOY"
    elif oos_sharpe > 0.8 and oos_dsr > 1.0 and stat_ok and (ic_ok or cpcv_ok):
        recommendation = "VALIDATE"
    elif oos_sharpe > 0.5:
        recommendation = "MUTATE"
    elif oos_sharpe > 0:
        recommendation = "ARCHIVE"
    else:
        recommendation = "REJECT"

    report["verdict"]         = recommendation
    report["oos_pnl_hash"]    = oos_result["pnl_hash"]
    report["oos_config_hash"] = oos_result["config_hash"]
    report["oos_parity_hash"] = oos_result["parity_hash"]
    # Holm q-value placeholder: TEST evaluates one candidate at a time, so
    # the per-candidate q-value equals its bootstrap p (n_trials=1 in Holm).
    # EXPLORE/EVOLVE will overwrite this with the family-corrected q-value.
    report["holm_qvalue"]     = falsification.get("bootstrap_pvalue")
    # Determinism evidence — populated by SELFCHECK() if the user runs it
    # before EXPORT. Default to None so EXPORT records "unverified".
    report.setdefault("selfcheck_passed", None)

    print(f"\n{'='*60}")
    print(f"VERDICT: {recommendation}")
    print(f"  OOS Sharpe: {oos_sharpe:+.3f}  DSR(n_trials={n_trials}): {oos_dsr:.3f}  "
          f"Regime-stable: {regime_ok}  Latency-ok: {latency_ok}")
    print(f"  IC: {ic_result.get('ic_mean') or 0:+.4f} (t={ic_result.get('ic_tstat') or 0:+.2f}) "
          f"|  CPCV frac_positive: {cpcv_result.get('fraction_positive',0):.1%}")
    print(f"  OOS pnl_hash:    {oos_result['pnl_hash'][:16]}...")
    print(f"  OOS config_hash: {oos_result['config_hash'][:16]}...")
    print(f"  OOS parity_hash: {oos_result['parity_hash'][:16]}...")
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

print("TEST() command: ACTIVE — runs 7-step directed hypothesis test")
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
    Sensor / horizon path     fresh instances when the loaded alpha requires them
  HMM3StateFractional       fresh instance, all posteriors at uniform prior
    Signal / composition path fresh instances when the loaded alpha requires them
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
Config source:     platform.yaml from same commit SHA as source ZIP
                    (loaded via PlatformConfig.from_yaml(PLATFORM_YAML_PATH))
Layer path:        sensor -> horizon -> signal -> composition when required by loaded alpha
Fill model:        BacktestOrderRouter (mid-price, depth-based partial fills)
Cost model:        DefaultCostModel (IB Tiered defaults from platform.yaml)
Risk engine:       BasicRiskEngine / AlphaBudgetRiskWrapper (from source)
Regime engine:     HMM3StateFractional — states: compression_clustering, normal, vol_breakout
State clearing:    Guaranteed — fresh instances per run
Determinism:       SELFCHECK() asserts Inv-5 by re-running and comparing hashes
Hashes:
  pnl_hash         SHA-256 over ordered trade sequence
  config_hash      PlatformConfig.snapshot().checksum
  parity_hash      SHA-256(pnl_hash + ":" + config_hash) — single comparator
```
