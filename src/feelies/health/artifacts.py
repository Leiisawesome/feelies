"""Load backtest / research artifacts from a run directory."""

from __future__ import annotations

import csv
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from feelies.health.context import HealthCheckContext


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> tuple[dict[str, Any], ...]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return ()
        fields = [str(f).strip() for f in reader.fieldnames if f is not None]
        rows: list[dict[str, Any]] = []
        for raw in reader:
            row = {fields[i]: raw.get(reader.fieldnames[i], "") for i in range(len(fields))}
            rows.append(row)
    return tuple(rows)


def _normalize_parquet_scalar(val: Any) -> Any:
    """Coerce Arrow / NumPy scalars into CSV-compatible Python scalars."""

    if val is None:
        return ""
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, float):
        return "" if math.isnan(val) else val
    if hasattr(val, "item"):
        try:
            inner: Any = val.item()
            if isinstance(inner, float) and inner != inner:
                return ""
            return inner
        except Exception:
            return val
    return val


def _read_parquet_rows(path: Path) -> tuple[dict[str, Any], ...]:
    """Load a Parquet file into the same row shape as :func:`_read_csv_rows`."""

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError(
            "Reading .parquet health artefacts requires pyarrow. "
            "Install with: pip install 'feelies[health]' (or feelies[portfolio])."
        ) from exc

    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    raw_rows = table.to_pylist()
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {str(k).strip(): _normalize_parquet_scalar(v) for k, v in row.items()},
        )
    return tuple(out)


def _read_tabular(path: Path, warnings: list[str]) -> tuple[dict[str, Any], ...]:
    suf = path.suffix.lower()
    if suf == ".csv":
        return _read_csv_rows(path)
    if suf == ".parquet":
        try:
            return _read_parquet_rows(path)
        except ImportError as exc:
            warnings.append(f"{path.name}: {exc}")
            return ()
    warnings.append(f"{path.name}: unsupported tabular suffix {path.suffix!r}")
    return ()


def _pick_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for n in names:
        p = root / n
        if p.is_file():
            return p
    return None


def load_run_directory(
    root: Path,
    *,
    alpha_name: str | None = None,
    run_id: str | None = None,
) -> HealthCheckContext:
    """Best-effort load of ``metadata.json``, CSV/Parquet tables, and optional JSON bundles."""

    meta_path = root / "metadata.json"
    metadata: dict[str, Any] = {}
    if meta_path.is_file():
        loaded = _read_json(meta_path)
        if isinstance(loaded, dict):
            metadata = dict(loaded)

    eff_alpha = alpha_name or str(metadata.get("alpha_name") or metadata.get("alpha") or root.name)
    eff_run = run_id or str(metadata.get("run_id") or metadata.get("experiment_id") or root.name)
    created_ns = int(metadata.get("run_timestamp_ns") or metadata.get("created_at_ns") or 0)
    repo_commit = metadata.get("git_commit_hash") or metadata.get("repo_commit")
    if repo_commit is not None:
        repo_commit = str(repo_commit)

    feature_names: tuple[str, ...] = ()
    fl = metadata.get("feature_names") or metadata.get("features") or metadata.get("feature_list")
    if isinstance(fl, list):
        feature_names = tuple(str(x) for x in fl)

    warnings: list[str] = []

    signals_path = _pick_existing(root, ("signals.csv", "signals.parquet"))
    trades_path = _pick_existing(root, ("trades.csv", "trades.parquet"))
    pnl_path = _pick_existing(
        root,
        ("pnl.csv", "pnl.parquet", "equity.csv", "equity.parquet"),
    )
    orders_path = _pick_existing(root, ("orders.csv", "orders.parquet"))
    fills_path = _pick_existing(root, ("fills.csv", "fills.parquet"))
    regimes_path = _pick_existing(root, ("regimes.csv", "regimes.parquet"))

    signals = _read_tabular(signals_path, warnings) if signals_path else ()
    trades = _read_tabular(trades_path, warnings) if trades_path else ()
    pnl = _read_tabular(pnl_path, warnings) if pnl_path else ()
    orders = _read_tabular(orders_path, warnings) if orders_path else ()
    fills = _read_tabular(fills_path, warnings) if fills_path else ()
    regimes = _read_tabular(regimes_path, warnings) if regimes_path else ()

    execution_variants: dict[str, dict[str, Any]] = {}
    ev_path = root / "execution_variants.json"
    if ev_path.is_file():
        ev_loaded = _read_json(ev_path)
        if isinstance(ev_loaded, dict):
            for k, v in ev_loaded.items():
                if isinstance(v, dict):
                    execution_variants[str(k)] = dict(v)

    robustness: dict[str, Any] = {}
    rb_path = root / "robustness_summary.json"
    if rb_path.is_file():
        rb_raw = _read_json(rb_path)
        if isinstance(rb_raw, dict):
            robustness = dict(rb_raw)

    portfolio_path = root / "portfolio_benchmarks.json"
    existing_equity: dict[str, tuple[float, ...]] = {}
    if portfolio_path.is_file():
        pr = _read_json(portfolio_path)
        if isinstance(pr, dict):
            for name, series in pr.items():
                if isinstance(series, list):
                    nums: list[float] = []
                    for x in series:
                        try:
                            nums.append(float(x))
                        except (TypeError, ValueError):
                            continue
                    existing_equity[str(name)] = tuple(nums)

    config_snapshot = metadata.get("config_snapshot")
    extra: dict[str, Any] = {}
    if isinstance(config_snapshot, dict):
        extra["config_snapshot"] = config_snapshot

    snap_path = root / "config_snapshot.yaml"
    if snap_path.is_file():
        try:
            raw = yaml.safe_load(snap_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            raw = None
        if isinstance(raw, dict):
            extra["config_snapshot_yaml"] = raw

    if warnings:
        extra["artifact_load_warnings"] = warnings

    return HealthCheckContext(
        alpha_name=eff_alpha,
        run_id=eff_run,
        created_at_ns=created_ns,
        config=None,  # filled by runner
        metadata=metadata,
        feature_names=feature_names,
        signals=signals,
        trades=trades,
        pnl_series=pnl,
        orders=orders,
        fills=fills,
        regime_rows=regimes,
        execution_variants=execution_variants,
        robustness_summary=robustness,
        existing_strategy_equity=existing_equity,
        artifacts_path=root.resolve(),
        repo_commit=repo_commit,
        extra=extra,
    )


__all__ = ["load_run_directory"]
