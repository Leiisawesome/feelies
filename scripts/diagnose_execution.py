#!/usr/bin/env python3
"""Execution-path diagnostic: Signal bus traffic vs orders and fills.

Replays ``run_backtest`` wiring, records bus events, and prints aggregates:
portfolio-filtered signals, standalone-eligible signals, ``RiskVerdict`` actions,
``OrderRequest`` reasons, ``OrderAck`` statuses.

Usage:
    python3 scripts/diagnose_execution.py --symbol AAPL --date 2026-04-08

Note: The orchestrator may ``publish`` the selected ``Signal`` again at M4 after
arbitration/stop handling, so raw ``Signal`` bus counts can exceed
HorizonSignalEngine emissions; ``unique_signal_fingerprints`` dedupes on
``(timestamp_ns, sequence, strategy_id, symbol, direction)``.

``RiskVerdict`` pairing uses the spine triple ``(correlation_id, symbol, sequence)``
copied from the producer: gate-1 verdicts match horizon-anchored ``Signal`` events;
gate-2 verdicts match ``OrderRequest`` events (quote correlation_id). The two gates use
different correlation namespaces, so each verdict classifies to at most one bucket.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Signal,
    SizedPositionIntent,
)
from feelies.core.platform_config import PlatformConfig


def _portfolio_consumed_strategy_ids(orchestrator: object) -> frozenset[str]:
    reg = getattr(orchestrator, "_alpha_registry", None)
    if reg is None:
        return frozenset()
    consumed: set[str] = set()
    portfolio_fn = getattr(reg, "portfolio_alphas", None)
    if portfolio_fn is None:
        return frozenset()
    for module in portfolio_fn():
        deps = getattr(module, "depends_on_signals", ()) or ()
        consumed.update(deps)
    return frozenset(consumed)


def _signal_fingerprint(s: Signal) -> tuple[int, int, str, str, str]:
    return (
        s.timestamp_ns,
        s.sequence,
        s.strategy_id,
        s.symbol,
        s.direction.name,
    )


def _spine_triple(ev: Signal | RiskVerdict | OrderRequest) -> tuple[str, str, int]:
    return (ev.correlation_id, ev.symbol, ev.sequence)


def _analyze_verdict_correlation(
    layer_signals: list[Signal],
    orders: list[OrderRequest],
    verdicts: list[RiskVerdict],
) -> dict[str, object]:
    """Pair each published RiskVerdict to signal gate vs order gate via spine triple."""
    sig_by_triple: dict[tuple[str, str, int], Signal] = {}
    for s in layer_signals:
        t = _spine_triple(s)
        sig_by_triple.setdefault(t, s)

    ord_by_triple: dict[tuple[str, str, int], OrderRequest] = {}
    for o in orders:
        ord_by_triple[_spine_triple(o)] = o

    sg_by_action: dict[str, int] = defaultdict(int)
    og_by_action: dict[str, int] = defaultdict(int)
    sg_by_strategy: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    og_by_strategy: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unmatched: list[dict[str, object]] = []

    for v in verdicts:
        t = _spine_triple(v)
        act = v.action.name
        if t in sig_by_triple:
            sg_by_action[act] += 1
            sid = sig_by_triple[t].strategy_id
            sg_by_strategy[sid][act] += 1
        elif t in ord_by_triple:
            og_by_action[act] += 1
            oid = ord_by_triple[t].strategy_id or "(empty_strategy_id)"
            og_by_strategy[oid][act] += 1
        else:
            unmatched.append(
                {
                    "correlation_id": v.correlation_id,
                    "symbol": v.symbol,
                    "sequence": v.sequence,
                    "action": act,
                    "reason": v.reason,
                }
            )

    def nest_plain(d: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        return {k: dict(sorted(v.items())) for k, v in sorted(d.items())}

    sg_ct = sum(sg_by_action.values())
    og_ct = sum(og_by_action.values())
    return {
        "signal_gate_verdict_count": sg_ct,
        "order_gate_verdict_count": og_ct,
        "unmatched_verdict_count": len(unmatched),
        "signal_gate_by_action": dict(sorted(sg_by_action.items())),
        "order_gate_by_action": dict(sorted(og_by_action.items())),
        "signal_gate_by_strategy_then_action": nest_plain(sg_by_strategy),
        "order_gate_by_strategy_then_action": nest_plain(og_by_strategy),
        "unmatched_verdict_samples": unmatched[:15],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Signal → execution pipeline.")
    parser.add_argument("--config", type=Path, default=_PROJECT_ROOT / "platform.yaml")
    parser.add_argument("--symbol", nargs="+", help="Override universe")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit one JSON object to stdout")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set.", file=sys.stderr)
        return 1

    config_path = args.config
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)
    if args.symbol:
        config = replace(config, symbols=frozenset(s.upper() for s in args.symbol))

    symbols = sorted(config.symbols)
    if not symbols:
        print("ERROR: No symbols.", file=sys.stderr)
        return 1

    rb_path = _PROJECT_ROOT / "scripts" / "run_backtest.py"
    spec = importlib.util.spec_from_file_location("feelies_run_backtest_exec_diag", rb_path)
    if spec is None or spec.loader is None:
        print(f"ERROR: cannot load {rb_path}", file=sys.stderr)
        return 1
    rb_mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, rb_mod)
    spec.loader.exec_module(rb_mod)
    ingest_data = rb_mod.ingest_data

    event_log, _, _ = ingest_data(
        api_key,
        symbols,
        args.date,
        args.date,
        cache_dir=args.cache_dir,
        no_cache=args.no_cache,
    )

    orchestrator, _cfg = build_platform(config, event_log=event_log)
    consumed_portfolio = _portfolio_consumed_strategy_ids(orchestrator)

    signals: list[Signal] = []
    orders: list[OrderRequest] = []
    acks: list[OrderAck] = []
    verdicts: list[RiskVerdict] = []
    intents: list[SizedPositionIntent] = []

    def on_all(ev: object) -> None:
        if isinstance(ev, Signal):
            signals.append(ev)
        elif isinstance(ev, OrderRequest):
            orders.append(ev)
        elif isinstance(ev, OrderAck):
            acks.append(ev)
        elif isinstance(ev, RiskVerdict):
            verdicts.append(ev)
        elif isinstance(ev, SizedPositionIntent):
            intents.append(ev)

    orchestrator._bus.subscribe_all(on_all)
    orchestrator.boot(config)
    orchestrator.run_backtest()

    layer_signal = [s for s in signals if s.layer == "SIGNAL"]
    stop_filtered = sum(1 for s in layer_signal if s.strategy_id == "__stop_exit__")
    portfolio_path = sum(
        1 for s in layer_signal
        if s.strategy_id != "__stop_exit__" and s.strategy_id in consumed_portfolio
    )
    standalone_eligible = sum(
        1 for s in layer_signal
        if s.strategy_id != "__stop_exit__" and s.strategy_id not in consumed_portfolio
    )

    fps = {_signal_fingerprint(s) for s in layer_signal}
    strategy_counts: dict[str, int] = defaultdict(int)
    for s in layer_signal:
        strategy_counts[s.strategy_id] += 1

    verdict_action_counts: dict[str, int] = defaultdict(int)
    for v in verdicts:
        verdict_action_counts[v.action.name] += 1

    order_reason_counts: dict[str, int] = defaultdict(int)
    for o in orders:
        reason = o.reason or "(empty)"
        order_reason_counts[reason] += 1

    ack_status_counts: dict[str, int] = defaultdict(int)
    for a in acks:
        ack_status_counts[a.status.name] += 1

    filled_qty = sum(a.filled_quantity for a in acks if a.status == OrderAckStatus.FILLED)

    verdict_corr = _analyze_verdict_correlation(layer_signal, orders, verdicts)

    report = {
        "portfolio_depends_on_signals": sorted(consumed_portfolio),
        "sized_position_intents": len(intents),
        "signal_bus_events_total": len(signals),
        "signal_layer_SIGNAL_events": len(layer_signal),
        "signal_unique_fingerprints_layer_SIGNAL": len(fps),
        "signal_strategy_id___stop_exit__": stop_filtered,
        "signal_routed_to_portfolio_composition_only": portfolio_path,
        "signal_standalone_pipeline_eligible_bus_publish": standalone_eligible,
        "signals_by_strategy_id": dict(sorted(strategy_counts.items())),
        "risk_verdict_events": len(verdicts),
        "risk_verdict_by_action": dict(sorted(verdict_action_counts.items())),
        "risk_verdict_correlation_pairing": verdict_corr,
        "order_request_events": len(orders),
        "order_request_by_reason": dict(sorted(order_reason_counts.items())),
        "order_ack_events": len(acks),
        "order_ack_by_status": dict(sorted(ack_status_counts.items())),
        "filled_quantity_sum_on_filled_acks": filled_qty,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("\n── Execution path diagnostic ──\n")
    print(f"PORTFOLIO depends_on_signals (standalone path skips): {report['portfolio_depends_on_signals']}")
    print(f"SizedPositionIntent events:              {len(intents):,}")
    print()
    print("Signal (bus)")
    print(f"  all Signal events:                     {len(signals):,}")
    print(f"  layer == SIGNAL:                       {len(layer_signal):,}")
    print(f"  unique fingerprints (layer=SIGNAL):    {len(fps):,}")
    print(f"  strategy_id __stop_exit__ (filtered): {stop_filtered:,}")
    print(f"  portfolio-composition only (skipped):  {portfolio_path:,}")
    print(f"  standalone M4 path eligible (bus):     {standalone_eligible:,}")
    print("  by strategy_id:")
    for sid, n in sorted(strategy_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {sid!r}: {n:,}")
    print()
    print(f"RiskVerdict events: {len(verdicts):,}")
    for act, n in sorted(verdict_action_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {act}: {n:,}")
    print()
    vc = verdict_corr
    print("RiskVerdict correlation pairing (spine triple)")
    print(
        f"  gate-1 (matched emitted Signal):     "
        f"{vc['signal_gate_verdict_count']:,}"
    )
    print(
        f"  gate-2 (matched OrderRequest):       "
        f"{vc['order_gate_verdict_count']:,}"
    )
    print(
        f"  unmatched (no Signal/Order triple): {vc['unmatched_verdict_count']:,}"
    )
    if vc["signal_gate_by_action"]:
        print("  gate-1 by action:")
        for act, n in sorted(
            vc["signal_gate_by_action"].items(),
            key=lambda kv: (-kv[1], kv[0]),
        ):
            print(f"    {act}: {n:,}")
    if vc["order_gate_by_action"]:
        print("  gate-2 by action:")
        for act, n in sorted(
            vc["order_gate_by_action"].items(),
            key=lambda kv: (-kv[1], kv[0]),
        ):
            print(f"    {act}: {n:,}")
    sg_sa = vc["signal_gate_by_strategy_then_action"]
    if sg_sa:
        print("  gate-1 by strategy_id → action:")
        for sid, acts in sg_sa.items():
            inner = ", ".join(f"{a}={c:,}" for a, c in sorted(acts.items()))
            print(f"    {sid!r}: {inner}")
    og_sa = vc["order_gate_by_strategy_then_action"]
    if og_sa:
        print("  gate-2 by strategy_id → action:")
        for sid, acts in og_sa.items():
            inner = ", ".join(f"{a}={c:,}" for a, c in sorted(acts.items()))
            print(f"    {sid!r}: {inner}")
    samples = vc["unmatched_verdict_samples"]
    if samples:
        print("  unmatched samples (first few):")
        for row in samples:
            print(f"    {row}")
    print()
    print(f"OrderRequest events: {len(orders):,}")
    for r, n in sorted(order_reason_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  reason {r!r}: {n:,}")
    print()
    print(f"OrderAck events: {len(acks):,}")
    for st, n in sorted(ack_status_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {st}: {n:,}")
    print(f"  Σ filled_quantity (FILLED acks): {filled_qty:,}")
    print()
    print(
        "Hint: standalone_eligible is bus HorizonSignalEngine output that clears "
        "_on_bus_signal filters; at most one per quote tick is arbitrated into "
        "risk after sizing/intent translation."
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
