"""Deterministic stdout JSONL emitters for backtest parity streams."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from decimal import Decimal

from feelies.core.events import (
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    RegimeHazardSpike,
    SensorReading,
    Signal,
    SizedPositionIntent,
)
from feelies.execution.portfolio_netter import NetDivergence
from feelies.harness.backtest_report import BusEventRecorder

__all__ = [
    "emit_cross_sectional_jsonl",
    "emit_fills_jsonl",
    "emit_hazard_exits_jsonl",
    "emit_hazard_spikes_jsonl",
    "emit_horizon_ticks_jsonl",
    "emit_net_divergence_jsonl",
    "emit_phase2_jsonl",
    "emit_sensor_readings_jsonl",
    "emit_signals_jsonl",
    "emit_snapshots_jsonl",
    "emit_sized_intents_jsonl",
]


def emit_net_divergence_jsonl(divergences: list[NetDivergence]) -> None:
    """G-5 measurement: one JSON line per recorded cross-alpha NetDivergence.

    Sourced from the orchestrator's net-shadow sink (not the bus), in
    record order.  ``magnitude`` is ``net − winner`` so the stream is
    directly aggregable (how often, and by how much, the budget-weighted
    portfolio net would differ from the winner-take-all decision).
    """
    for d in divergences:
        _emit_jsonl_line("NETDIV_JSONL", {
            "signal_sequence": d.signal_sequence,
            "symbol": d.symbol,
            "winner_strategy_id": d.winner_strategy_id,
            "winner_target_qty": d.winner_target_qty,
            "net_target_qty": d.net_target_qty,
            "magnitude": d.net_target_qty - d.winner_target_qty,
            "contributing_alphas": d.contributing_alphas,
        })


def _emit_jsonl_line(prefix: str, line: Mapping[str, object]) -> None:
    """Print one deterministic ``<PREFIX> {json}`` parity-stream line."""
    print(f"{prefix} " + json.dumps(line, sort_keys=True), flush=True)


def emit_fills_jsonl(recorder: BusEventRecorder) -> None:
    """Print one JSON line per FILLED OrderAck in arrival order."""
    acks = recorder.of_type(OrderAck)
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]
    for a in fills:
        line = {
            "sequence": a.sequence,
            "symbol": a.symbol,
            "order_id": a.order_id,
            "filled_quantity": a.filled_quantity,
            "fill_price": (
                str(a.fill_price) if isinstance(a.fill_price, Decimal)
                else None if a.fill_price is None
                else str(Decimal(str(a.fill_price)))
            ),
        }
        _emit_jsonl_line("FILL_JSONL", line)


def emit_sensor_readings_jsonl(recorder: BusEventRecorder) -> None:
    for r in recorder.of_type(SensorReading):
        value: object
        if isinstance(r.value, tuple):
            value = list(r.value)
        else:
            value = float(r.value)
        line = {
            "sequence": r.sequence,
            "sensor_id": r.sensor_id,
            "sensor_version": r.sensor_version,
            "symbol": r.symbol,
            "value": value,
            "warm": bool(r.warm),
        }
        _emit_jsonl_line("SENSOR_JSONL", line)


def emit_horizon_ticks_jsonl(recorder: BusEventRecorder) -> None:
    for t in recorder.of_type(HorizonTick):
        line = {
            "sequence": t.sequence,
            "horizon_seconds": t.horizon_seconds,
            "boundary_index": t.boundary_index,
            "scope": t.scope,
            "symbol": t.symbol,
            "session_id": t.session_id,
        }
        _emit_jsonl_line("HTICK_JSONL", line)


def emit_snapshots_jsonl(recorder: BusEventRecorder) -> None:
    for s in recorder.of_type(HorizonFeatureSnapshot):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "horizon_seconds": s.horizon_seconds,
            "boundary_index": s.boundary_index,
            "values": dict(s.values),
            "warm": {k: bool(v) for k, v in s.warm.items()},
            "stale": {k: bool(v) for k, v in s.stale.items()},
        }
        _emit_jsonl_line("SNAP_JSONL", line)


def emit_signals_jsonl(recorder: BusEventRecorder) -> None:
    for s in recorder.of_type(Signal):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "strategy_id": s.strategy_id,
            "layer": s.layer,
            "horizon_seconds": s.horizon_seconds,
            "regime_gate_state": s.regime_gate_state,
            "direction": s.direction.name,
            "strength": float(s.strength),
            "edge_estimate_bps": float(s.edge_estimate_bps),
            "disclosed_cost_total_bps": float(s.disclosed_cost_total_bps),
            "disclosed_margin_ratio": float(s.disclosed_margin_ratio),
            "consumed_features": list(s.consumed_features),
            "trend_mechanism": (
                s.trend_mechanism.name if s.trend_mechanism is not None
                else None
            ),
            "expected_half_life_seconds": int(s.expected_half_life_seconds),
        }
        _emit_jsonl_line("SIGNAL_JSONL", line)


def emit_hazard_spikes_jsonl(recorder: BusEventRecorder) -> None:
    for s in recorder.of_type(RegimeHazardSpike):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "engine_name": s.engine_name,
            "departing_state": s.departing_state,
            "departing_posterior_prev": float(s.departing_posterior_prev),
            "departing_posterior_now": float(s.departing_posterior_now),
            "incoming_state": s.incoming_state,
            "hazard_score": float(s.hazard_score),
            "timestamp_ns": s.timestamp_ns,
            "correlation_id": s.correlation_id,
        }
        _emit_jsonl_line("HAZARD_JSONL", line)


def emit_cross_sectional_jsonl(recorder: BusEventRecorder) -> None:
    for c in recorder.of_type(CrossSectionalContext):
        line = {
            "sequence": c.sequence,
            "timestamp_ns": c.timestamp_ns,
            "horizon_seconds": c.horizon_seconds,
            "boundary_index": c.boundary_index,
            "universe": list(c.universe),
            "completeness": float(c.completeness),
            "correlation_id": c.correlation_id,
        }
        _emit_jsonl_line("XSECT_JSONL", line)


def emit_sized_intents_jsonl(recorder: BusEventRecorder) -> None:
    for it in recorder.of_type(SizedPositionIntent):
        targets = [
            {"symbol": s, "target_usd": float(tp.target_usd)}
            for s, tp in sorted(it.target_positions.items())
        ]
        mech_breakdown = {
            (k.name if hasattr(k, "name") else str(k)): float(v)
            for k, v in sorted(
                it.mechanism_breakdown.items(),
                key=lambda kv: (
                    kv[0].name if hasattr(kv[0], "name") else str(kv[0])
                ),
            )
        }
        line = {
            "sequence": it.sequence,
            "timestamp_ns": it.timestamp_ns,
            "strategy_id": it.strategy_id,
            "horizon_seconds": it.horizon_seconds,
            "target_positions": targets,
            "factor_exposures": {
                k: float(v) for k, v in sorted(it.factor_exposures.items())
            },
            "expected_turnover_usd": float(it.expected_turnover_usd),
            "expected_gross_exposure_usd": float(
                it.expected_gross_exposure_usd
            ),
            "mechanism_breakdown": mech_breakdown,
            "correlation_id": it.correlation_id,
        }
        _emit_jsonl_line("INTENT_JSONL", line)


def emit_hazard_exits_jsonl(recorder: BusEventRecorder) -> None:
    for o in recorder.of_type(OrderRequest):
        reason = getattr(o, "reason", "") or ""
        if reason not in ("HAZARD_SPIKE", "HARD_EXIT_AGE"):
            continue
        line = {
            "sequence": o.sequence,
            "timestamp_ns": o.timestamp_ns,
            "symbol": o.symbol,
            "side": o.side.name,
            "quantity": int(o.quantity),
            "order_id": o.order_id,
            "strategy_id": o.strategy_id or "",
            "reason": reason,
            "correlation_id": o.correlation_id,
        }
        _emit_jsonl_line("HAZARD_EXIT_JSONL", line)


def emit_phase2_jsonl(args: argparse.Namespace, recorder: BusEventRecorder) -> None:
    """Composable wrapper — invokes each enabled Phase-2/3/3.1/4 emitter."""
    if args.emit_sensor_readings_jsonl:
        emit_sensor_readings_jsonl(recorder)
    if args.emit_horizon_ticks_jsonl:
        emit_horizon_ticks_jsonl(recorder)
    if args.emit_snapshots_jsonl:
        emit_snapshots_jsonl(recorder)
    if args.emit_signals_jsonl:
        emit_signals_jsonl(recorder)
    if args.emit_hazard_spikes_jsonl:
        emit_hazard_spikes_jsonl(recorder)
    if getattr(args, "emit_cross_sectional_jsonl", False):
        emit_cross_sectional_jsonl(recorder)
    if getattr(args, "emit_sized_intents_jsonl", False):
        emit_sized_intents_jsonl(recorder)
    if getattr(args, "emit_hazard_exits_jsonl", False):
        emit_hazard_exits_jsonl(recorder)


# Backward-compatible aliases for ``scripts/run_backtest.py`` importlib tests.
_emit_fills_jsonl = emit_fills_jsonl
_emit_net_divergence_jsonl = emit_net_divergence_jsonl
_emit_sensor_readings_jsonl = emit_sensor_readings_jsonl
_emit_horizon_ticks_jsonl = emit_horizon_ticks_jsonl
_emit_snapshots_jsonl = emit_snapshots_jsonl
_emit_signals_jsonl = emit_signals_jsonl
_emit_hazard_spikes_jsonl = emit_hazard_spikes_jsonl
_emit_cross_sectional_jsonl = emit_cross_sectional_jsonl
_emit_sized_intents_jsonl = emit_sized_intents_jsonl
_emit_hazard_exits_jsonl = emit_hazard_exits_jsonl
_emit_phase2_jsonl = emit_phase2_jsonl
