# Alpha Health Check

## Purpose

The alpha health layer (`feelies.health`) provides a deterministic, auditable gate that consumes lightweight research artefacts (CSV, Parquet, JSON) produced after a backtest or experiment. It answers whether an idea is **causal**, **economically plausible after costs**, **reasonably robust**, and **safe enough** for the next deployment stage.

**Determinism:** The same artefact directory + health YAML → the same report (no randomness in scoring). Report timestamps come from `metadata.json` (`run_timestamp_ns` / `created_at_ns`) when present; otherwise they anchor to a fixed epoch for reproducibility.

**Scope:** This is **research / backtest scaffolding**. Platform-native promotion (CPCV, DSR, paper-window evidence, F-2 gate matrix, promotion ledger) remains **`feelies promote`** — see [Limitations / Promotion ledger](#limitations).

---

## Installation & dependencies

| Need | Install |
|------|---------|
| Core health (stdlib metrics, YAML config) | `pip install feelies` (PyYAML only) |
| **Parquet** artefact loading | `pip install 'feelies[health]'` **or** `'feelies[portfolio]'` (PyArrow ≥ 15) |
| Contributors / CI (includes PyArrow for Parquet tests) | `pip install -e '.[dev]'` |

Without PyArrow, `.parquet` files are **skipped** and `artifact_load_warnings` triggers a definition-category **WARN** (`artifact_load_warnings` check).

---

## Usage

### Recommended workflow: export after backtest, then health-check

From the repository root, point `PYTHONPATH` at `src` (or use an editable install of `feelies` so `feelies` / `python -m feelies` resolve without `PYTHONPATH`).

**Step 1 — run the backtest and write health artefacts** (`scripts/run_backtest.py`):

```bash
export PYTHONPATH=src   # omit if `feelies` is installed in the active env

python3 scripts/run_backtest.py \
  --symbol AAPL \
  --date 2024-01-15 \
  --config platform.yaml \
  --export-health-dir ./runs/my_alpha/latest
```

This creates (under `./runs/my_alpha/latest/`) at least `metadata.json`, `signals.csv`, `execution_variants.json`, and usually `config_snapshot.yaml`; `trades.csv` / `pnl.csv` appear when the trade journal has fills.

**Notes:**

- **`MASSIVE_API_KEY`** is required for live API ingestion on this script path.
- **`metadata.json`** includes `run_id` (hash of symbols, dates, config digest, stress multiplier, ingest counts), optional **`git_commit_hash`** (`git rev-parse HEAD` when available), and **`data_source`** (`massive_l1_nbbo` vs `disk_event_cache_jsonl` when all day sources are cache).
- **Signals** from export have **no `forward_return`** — merge labels offline if you need predictive IC checks; `metadata.forward_return_note` documents this.
- **`execution_variants.json`** is **`mid` lens only** for this replay; full execution PASS on health checks still expects **executable / conservative** (or equivalent) lenses you supply separately.

**Step 2 — run the health gate** (writes reports under `--out-dir`, defaulting to `<backtest-output>/health/`):

```bash
python3 -m feelies health-check \
  --backtest-output ./runs/my_alpha/latest \
  --config ./configs/health/default.yaml \
  --out-dir ./runs/my_alpha/latest/health \
  --format both
```

Equivalent console-script form:

```bash
feelies health-check \
  --backtest-output ./runs/my_alpha/latest \
  --config ./configs/health/default.yaml \
  --out-dir ./runs/my_alpha/latest/health \
  --format both
```

**CLI flags**

| Flag | Meaning |
|------|---------|
| `--backtest-output DIR` | Run directory containing `metadata.json` and optional tabular/JSON artefacts (CSV **or** Parquet). **Required.** |
| `--alpha` | Optional override for `alpha_name` when `metadata.json` should not dictate it. |
| `--config PATH` | Health thresholds YAML (e.g. `configs/health/default.yaml`). Omitted → built-in defaults; summary notes missing YAML. |
| `--out-dir DIR` | Report output directory. **Default:** `<backtest-output>/health/`. |
| `--format` | `json`, `markdown`, `both` (default), or `all` (also writes `alpha_health_checks.csv`). |
| `--strict` | Exit **3** if decision is `KILL` **or** any check has status `FAIL`. |

**CLI exit codes** (aligned with `feelies promote` conventions):

| Code | Meaning |
|------|---------|
| `0` | Success. |
| `1` | User error (e.g. missing `--backtest-output`, path not a directory). |
| `2` | Data / I/O error (e.g. cannot write reports, unexpected failure during run). |
| `3` | Validation failed (`--strict` and `KILL` or any `FAIL` check). |

Disk-cache-only replay uses the same **`--export-health-dir`** flag on the parser behind **`main_cache_replay`** in `scripts/run_backtest.py`; forward that argument from your offline JSONL driver.

**What `--export-health-dir` writes**

| File | Contents |
|------|-----------|
| `metadata.json` | Universe, timeframe, `run_id`, `run_timestamp_ns`, optional `git_commit_hash`, execution/cost notes, feature names from signals, forward-return / execution-variant notes |
| `signals.csv` | Deduped horizon `Signal` rows (no `forward_return` unless you add it) |
| `trades.csv` / `pnl.csv` | Present when the trade journal reports fills; daily `pnl.csv` derived from fill dates (UTC) |
| `execution_variants.json` | **`mid` lens only** — expect execution-category pressure until you add more lenses |
| `config_snapshot.yaml` | Copy of the resolved `--config` platform YAML when it exists |

### Health-check only (you already have a run directory)

```bash
python3 -m feelies health-check \
  --alpha my_alpha \
  --backtest-output ./runs/my_alpha/latest \
  --config ./configs/health/default.yaml \
  --out-dir ./reports/my_alpha_health \
  --format both \
  --strict
```

### Python API

```python
from pathlib import Path

from feelies.health import (
    load_health_config,
    load_run_directory,
    run_alpha_health_check,
    run_alpha_health_check_from_directory,
    run_and_write_reports,
)

cfg = load_health_config(Path("configs/health/default.yaml"))

# One-shot load + score (same as CLI directory mode):
report = run_alpha_health_check_from_directory(Path("./runs/demo"), config=cfg)

# Or load artefacts first (CSV / Parquet / JSON) then score:
ctx = load_run_directory(Path("./runs/demo"))
report = run_alpha_health_check(context=ctx, config=cfg)

_, paths = run_and_write_reports(
    out_dir=Path("./reports/demo"),
    run_dir=Path("./runs/demo"),
    config_path=Path("configs/health/default.yaml"),
)
```

**Programmatic export after a replay** (same writer `scripts/run_backtest.py` calls):

```python
from pathlib import Path

from feelies.health import export_backtest_health_dir

export_backtest_health_dir(
    Path("./runs/my_alpha/latest"),
    recorder=recorder,
    orchestrator=orchestrator,
    config=config_out,
    symbols=["AAPL"],
    date_range="2024-01-15",
    platform_config_path="/absolute/or/cwd/platform.yaml",
    stress_cost_multiplier=1.0,
    ingest_events=12345,
)
```

---

## Configuration

- **Default file:** `configs/health/default.yaml` — thresholds (IC, Sharpe, concentration, participation, portfolio correlation, etc.), **`metadata_required_fields`**, and **`category_weights`** for scoring.
- **Loader:** `feelies.health.load_health_config(Path | None)` — missing path → built-in defaults with `config_missing_warned` surfaced in the report summary.
- **Types:** `feelies.health.HealthConfig` (dataclass).

---

## Expected artefacts

Minimum practical set:

| File | Role |
|------|------|
| `metadata.json` | Alpha definition + provenance (`alpha_name`, `universe`, `timeframe`, `prediction_horizon`, execution/cost assumptions, optional git hash, `run_id`, notes). Required keys depend on **`metadata_required_fields`** in health YAML (defaults include `data_source` when using repo `default.yaml`). |
| `signals.csv` **or** `signals.parquet` | Rows with `timestamp`, `symbol`, `signal`, optional `forward_return` (+ optional causal timestamps). |
| `execution_variants.json` | Dictionary of lenses (`mid`, `executable`, `conservative`, …) each exposing economic summaries (`net_pnl`, `net_sharpe`, average edges/costs). |
| `trades.csv` **or** `trades.parquet` | Optional spread/volume proxies plus `net_pnl` for regime + capacity checks. |
| `pnl.csv` / `equity.csv` **or** `pnl.parquet` / `equity.parquet` | Optional cumulative-style series (`pnl`, `date`). |
| `orders.csv` **or** `orders.parquet`, `fills.csv` **or** `fills.parquet`, `regimes.csv` **or** `regimes.parquet` | Optional operational / regime tables. |
| `robustness_summary.json` | Optional sweep / OOS metrics. |
| `portfolio_benchmarks.json` | Optional aligned benchmark return series for diversification checks. |

**CSV vs Parquet:** For each logical table, the loader picks the **first existing file** in the order shown (e.g. `signals.csv` wins over `signals.parquet` when both exist). Parquet requires **PyArrow** — see [Installation](#installation--dependencies).

**Load warnings:** Failed or skipped tabular loads append to **`HealthCheckContext.extra["artifact_load_warnings"]`** and surface as check **`artifact_load_warnings`** (definition category, `WARN`).

Missing inputs downgrade confidence (`WARN` / `NOT_APPLICABLE`) rather than crashing.

---

## Outputs & report schema

**Files written** by `run_and_write_reports` / CLI:

| File | Description |
|------|-------------|
| `alpha_health_report.json` | Full machine-readable report (`health_report_to_json_dict`). |
| `alpha_health_report.md` | Human-readable summary (decision, score, tables, actions). |
| `alpha_health_checks.csv` | Per-check row summary (`--format all`). |

**Core concepts** (`feelies.health.models`):

- **`HealthStatus`:** `PASS`, `WARN`, `FAIL`, `NOT_APPLICABLE`.
- **`AlphaDecision`:** `KILL`, `RESEARCH_MORE`, `PAPER_TRADE`, `DEPLOY_SMALL`, `SCALE_CANDIDATE`.
- **`HealthCheckResult`:** `category`, `check_name`, `status`, `metrics`, `thresholds`, `message`, `suggested_action`, `severity`.
- **`AlphaHealthReport`:** `alpha_name`, `run_id`, `created_at`, `repo_commit`, `overall_status`, `decision`, `score`, `results`, `summary`, `artifacts`.

---

## Status definitions

- **`PASS`** — evidence meets configured thresholds.
- **`WARN`** — incomplete or marginal evidence.
- **`FAIL`** — threshold breach or unsafe condition.
- **`NOT_APPLICABLE`** — prerequisite artefacts absent.

---

## Decision logic & scoring

Decisions combine:

1. **Mandatory kill triggers** — e.g. label-like feature names, causal timestamp violations, unsafe regime flags, failed economics under non–mid-only realistic lenses, placebo collisions, unrealistic participation, redundant portfolio overlap; plus **causality category `FAIL`** (see `src/feelies/health/scoring.py`). **Mid-only positive PnL** does not automatically `KILL` but blocks strong promotion paths until executable/conservative evidence exists.
2. **Weighted category score** — default weights in `configs/health/default.yaml` (`metadata_definition`, `data_integrity_causality`, `raw_predictive_power`, `cost_execution_survival`, …). Per category: worst applicable check dominates; `PASS` = 1.0, `WARN` = 0.5, `FAIL` = 0.0, `NOT_APPLICABLE` excluded from that category’s weight numerator.
3. **Stage-style bands** — explicit thresholds mapping score + category passes → `RESEARCH_MORE` / `PAPER_TRADE` / `DEPLOY_SMALL` / `SCALE_CANDIDATE` / `KILL`.

**Authoritative code:** `src/feelies/health/scoring.py` — no hidden model.

---

## Check categories (reference)

| Category | Module (under `src/feelies/health/checks/`) | Focus |
|----------|---------------------------------------------|--------|
| `metadata_definition` | `definition_checks.py` | Required metadata, optional provenance, feature manifest, artefact load warnings |
| `data_integrity_causality` | `causality_checks.py` | Leakage-like names, timestamps, duplicates, missing signals, regime-label safety flag |
| `raw_predictive_power` | `predictive_checks.py` | IC, quantiles, hit rate, coverage, autocorrelation (needs paired `forward_return` when present) |
| `cost_execution_survival` | `execution_checks.py` | Execution lenses, net economics, mid-only / inferred-PnL warnings |
| `regime_robustness` | `regime_checks.py` | Spread/vol/time buckets on trades |
| `robustness_overfit` | `robustness_checks.py` | `robustness_summary.json`, placebo hooks |
| `risk_drawdown` | `risk_checks.py` | Trade distribution, drawdown, concentration |
| `capacity_liquidity` | `capacity_checks.py` | Participation / TOB when columns exist |
| `portfolio_fit` | `portfolio_checks.py` | `portfolio_benchmarks.json` correlations / marginal Sharpe |
| `production_readiness` | `production_checks.py` | Metadata checklist, artefact logging flags |

---

## Implementation layout

```
src/feelies/health/
  __init__.py          # public exports (inc. load_run_directory, export_backtest_health_dir)
  artifacts.py         # load_run_directory — CSV / Parquet / JSON
  backtest_export.py   # export_backtest_health_dir — post-replay bundle
  config.py            # HealthConfig, load_health_config
  context.py           # HealthCheckContext
  models.py            # report / check types, JSON helper
  metrics.py           # stdlib-only statistics
  runner.py            # run_alpha_health_check*, run_and_write_reports
  reporting.py         # JSON / Markdown / CSV writers
  scoring.py           # weights, decision, overall status
  checks/              # per-category check modules
```

**CLI:** `src/feelies/cli/health_check.py` — subcommand `health-check` registered in `src/feelies/cli/main.py`.

---

## Tests

- **Location:** `tests/health/` — synthetic CSV/JSON runs, export smoke test, Parquet loader tests (skipped if PyArrow missing), strict CLI exit code.
- **Run:** `PYTHONPATH=src python3 -m pytest tests/health/ -q`
- **Dev install** includes PyArrow so Parquet tests execute in typical contributor environments.

---

## Adding a new check

1. Implement `run_<domain>_checks(ctx, cfg) -> list[HealthCheckResult]` in `src/feelies/health/checks/`.
2. Register it in `run_all_health_checks` (`src/feelies/health/checks/__init__.py`).
3. Extend `HealthConfig` / `configs/health/default.yaml` if new thresholds are needed.
4. Add focused pytest coverage under `tests/health/`.

---

## Limitations

- **Metrics** in `metrics.py` are **stdlib-only** (no pandas in core). CSV uses `csv.DictReader`; Parquet uses **PyArrow** when installed.
- **Causality** cannot be proven from column names alone; missing causal timestamps → `FAIL` / `WARN` per checks, not silent `PASS`.
- **Regime** segmentation uses **causal proxies** on trade rows (spread / vol / clock); declare unsafe future-derived regime labels in metadata at your own risk (checker flags `regime_labels_use_future_data`).
- **Portfolio** diagnostics need **`portfolio_benchmarks.json`**; otherwise the category is **`NOT_APPLICABLE`**.
- **Promotion ledger / F-2 / CPCV / DSR:** continue to use **`feelies promote`** and the testing-validation promotion workflow — the health layer does **not** replace institutional promotion gates.
