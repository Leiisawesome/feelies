"""Write alpha health-check artefacts after a platform backtest replay.

These files match the layout described in ``docs/alpha_health_check.md`` so
``feelies health-check --backtest-output <dir>`` can run without manual CSV
curation.  Forward returns are **not** synthesized here — predictive IC checks
remain honest until research attaches labelled outcomes offline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from feelies.core.events import OrderAck, Signal, SignalDirection
from feelies.core.platform_config import PlatformConfig
from feelies.health.metrics import safe_mean, sharpe_ratio


def _dedupe_signals(signals: Sequence[Signal]) -> list[Signal]:
    seen: set[int] = set()
    out: list[Signal] = []
    for s in signals:
        oid = id(s)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(s)
    return out


def _signed_strength(s: Signal) -> float:
    if s.direction == SignalDirection.LONG:
        return float(s.strength)
    if s.direction == SignalDirection.SHORT:
        return -float(s.strength)
    return 0.0


def _try_git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    head = proc.stdout.strip()
    return head or None


def _compute_run_id(
    *,
    symbols: Sequence[str],
    date_range: str,
    stress_cost_multiplier: float,
    ingest_events: int,
    platform_config_path: str | None,
) -> str:
    parts = [
        "|".join(sorted(symbols)),
        date_range,
        f"stress={stress_cost_multiplier}",
        f"events={ingest_events}",
    ]
    if platform_config_path:
        p = Path(platform_config_path)
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            parts.append(f"cfg_sha256_16={digest}")
        except OSError:
            parts.append(f"cfg_path={p.name}")
    raw = "||".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _accounting(recorder: Any, orchestrator: Any) -> dict[str, float]:
    positions = orchestrator._positions
    all_pos = positions.all_positions()
    realized_pnl = sum((p.realized_pnl for p in all_pos.values()), Decimal("0"))
    unrealized_pnl = sum((p.unrealized_pnl for p in all_pos.values()), Decimal("0"))
    gross_pnl = realized_pnl + unrealized_pnl
    acks: list[OrderAck] = recorder.of_type(OrderAck)
    fees = sum((a.fees for a in acks), Decimal("0"))
    net_pnl = gross_pnl - fees
    return {
        "gross_pnl": float(gross_pnl),
        "net_pnl": float(net_pnl),
        "fees_total": float(fees),
        "realized_pnl": float(realized_pnl),
        "unrealized_pnl": float(unrealized_pnl),
    }


def _trade_csv_rows(orchestrator: Any) -> list[dict[str, Any]]:
    journal = orchestrator._trade_journal
    rows: list[dict[str, Any]] = []
    for rec in journal.query():
        ft = rec.fill_timestamp_ns
        rows.append(
            {
                "timestamp": ft if ft is not None else rec.submit_timestamp_ns,
                "symbol": rec.symbol,
                "side": rec.side.name if hasattr(rec.side, "name") else str(rec.side),
                "quantity": rec.filled_quantity,
                "net_pnl": float(rec.realized_pnl),
                "fees": float(rec.fees),
                "cost_bps": float(rec.cost_bps),
                "signal_timestamp": rec.signal_timestamp_ns,
                "strategy_id": rec.strategy_id,
            }
        )
    return rows


def _daily_pnl_from_trades(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    daily: dict[str, float] = defaultdict(float)
    for r in rows:
        ts = r.get("timestamp")
        if ts is None:
            continue
        try:
            ns = int(ts)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).date().isoformat()
        daily[day] += float(r.get("net_pnl", 0.0))
    out = [{"date": d, "pnl": daily[d]} for d in sorted(daily.keys())]
    return out


def export_backtest_health_dir(
    out_dir: Path,
    *,
    recorder: Any,
    orchestrator: Any,
    config: PlatformConfig,
    symbols: list[str],
    date_range: str,
    platform_config_path: str | None,
    stress_cost_multiplier: float,
    ingest_events: int,
    data_source: str = "massive_l1_nbbo",
) -> None:
    """Populate *out_dir* with health-check inputs derived from the replay."""

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_signals: list[Signal] = recorder.of_type(Signal)
    signals = _dedupe_signals(raw_signals)

    strategy_id = signals[0].strategy_id if signals else "feelies_backtest"
    horizons = sorted({s.horizon_seconds for s in signals if s.horizon_seconds})
    prediction_horizon = (
        f"{horizons[0]}s" if len(horizons) == 1 else ",".join(f"{h}s" for h in horizons) or "unknown"
    )

    feature_names: list[str] = sorted({f for s in signals for f in s.consumed_features})

    acct = _accounting(recorder, orchestrator)
    trade_rows = _trade_csv_rows(orchestrator)
    daily_rows = _daily_pnl_from_trades(trade_rows)

    daily_pnls = [float(r["pnl"]) for r in daily_rows]
    daily_sharpe = sharpe_ratio(daily_pnls, annualization_factor=252.0) if len(daily_pnls) >= 2 else None

    per_trade_gross = []
    per_trade_cost = []
    for r in trade_rows:
        net = float(r["net_pnl"])
        fees = float(r["fees"])
        per_trade_gross.append(net + fees)
        per_trade_cost.append(fees)
    avg_gross = safe_mean(per_trade_gross)
    avg_cost = safe_mean(per_trade_cost)
    ratio = None
    if avg_cost is not None and avg_cost != 0.0 and avg_gross is not None:
        ag = avg_gross
        ac = avg_cost
        ratio = abs(ag) / max(1e-12, abs(ac))

    run_id = _compute_run_id(
        symbols=symbols,
        date_range=date_range,
        stress_cost_multiplier=stress_cost_multiplier,
        ingest_events=ingest_events,
        platform_config_path=platform_config_path,
    )
    last_ts = max((s.timestamp_ns for s in signals), default=0)

    meta: dict[str, Any] = {
        "alpha_name": strategy_id,
        "universe": list(symbols),
        "timeframe": date_range,
        "data_source": data_source,
        "prediction_horizon": prediction_horizon,
        "execution_assumption": (
            f"feelies backtest ExecutionBackend; mode={config.mode.name}; "
            f"session_kind={config.session_kind}"
        ),
        "cost_assumption": (
            f"platform CostModel + fees from fills; cost_stress_multiplier={stress_cost_multiplier}"
        ),
        "run_timestamp_ns": int(last_ts),
        "run_id": run_id,
        "git_commit_hash": _try_git_commit(),
        "ingested_event_count": ingest_events,
        "feature_names": feature_names,
        "entry_rule": "see alpha YAML (strategy_id)",
        "exit_rule": "see alpha YAML / risk engine",
        "forward_return_note": (
            "Not exported — attach offline labels or merge forward_return into signals.csv for IC."
        ),
        "execution_variant_note": (
            "Only 'mid' lens exported from this replay; add executable/conservative summaries "
            "from alternative fill models for full health-check PASS on execution survival."
        ),
        "deterministic_config": True,
        "reproducible_run_id": run_id,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if signals:
        sig_fields = [
            "timestamp",
            "symbol",
            "signal",
            "decision_timestamp",
            "strategy_id",
            "horizon_seconds",
            "direction",
            "edge_estimate_bps",
            "regime_gate_state",
        ]
        sig_csv = []
        for s in signals:
            sig_csv.append(
                {
                    "timestamp": s.timestamp_ns,
                    "symbol": s.symbol,
                    "signal": _signed_strength(s),
                    "decision_timestamp": s.timestamp_ns,
                    "strategy_id": s.strategy_id,
                    "horizon_seconds": s.horizon_seconds,
                    "direction": s.direction.name,
                    "edge_estimate_bps": float(s.edge_estimate_bps),
                    "regime_gate_state": s.regime_gate_state,
                }
            )
        with (out_dir / "signals.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=sig_fields)
            w.writeheader()
            w.writerows(sig_csv)

    if trade_rows:
        fields = list(trade_rows[0].keys())
        with (out_dir / "trades.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(trade_rows)

    if daily_rows:
        with (out_dir / "pnl.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "pnl"])
            w.writeheader()
            w.writerows(daily_rows)

    ns_sh = daily_sharpe if daily_sharpe is not None else 0.0
    exec_mid = {
        "net_pnl": acct["net_pnl"],
        "gross_pnl": acct["gross_pnl"],
        "net_sharpe": float(ns_sh),
        "avg_gross_edge_per_trade": float(avg_gross) if avg_gross is not None else 0.0,
        "avg_cost_per_trade": float(avg_cost) if avg_cost is not None else 0.0,
        "gross_edge_to_cost_ratio": float(ratio) if ratio is not None else 0.0,
        "fee_total": acct["fees_total"],
        "trade_count": len(trade_rows),
    }
    bundle = {
        "mid": exec_mid,
        "description": "mid = backtest router path (see execution_variant_note in metadata.json)",
    }
    (out_dir / "execution_variants.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if platform_config_path:
        src = Path(platform_config_path)
        if src.is_file():
            shutil.copy2(src, out_dir / "config_snapshot.yaml")


__all__ = ["export_backtest_health_dir"]
