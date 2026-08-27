"""Declared, hashed subscription graph for the composition root.

The ordinals are the measured ``EventBus.subscribe`` call order from a
phase-4 ``build_platform`` (PYTHONHASHSEED=0): wrap ``EventBus.subscribe``,
compose, record ``(event_type, subscriber)``. Conditional authors that
did not attach on that run (hazard, deferral, exit-composer) sit in the
slot they occupy when they do attach — between StopExit and Orchestrator.
New observers for previously zero-subscriber types are appended; they
subscribe distinct types, so existing per-type order is unchanged.

Zero-subscriber resolutions (step 4, one type at a time):

* ``OrderAck`` — consumer (observer). Publish kept; no ``self._seq`` change.
* ``PositionUpdate`` — consumer (observer). Publish kept.
* ``RiskVerdict`` — consumer (observer). Publish kept (removing it would
  re-pin). Notification-shaped, still a domain-bus event this step.
* ``SymbolHalted`` — consumer (observer). Forensic marker; publish kept.
* ``KillSwitchActivation`` — consumer (observer). Additive; the four
  direct orchestrator reads are the control path.
* ``StateTransition`` — reclassified as a notification record. Publish
  kept (S-31 deletes it). No subscriber this step, so S11 remains xfail
  on this type alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

Disposition = Literal["consumer", "notification_record"]


@dataclass(frozen=True, slots=True)
class Subscription:
    """One declared bus subscription, in measured registration order."""

    ordinal: int
    event_type: str
    subscriber: str
    method: str
    disposition: Disposition = "consumer"


SUBSCRIPTIONS: tuple[Subscription, ...] = (
    Subscription(0, "RegimeState", "RegimeStateCache", "record"),
    Subscription(1, "NBBOQuote", "_on_backtest_quote", "_on_backtest_quote"),
    Subscription(2, "NBBOQuote", "SensorRegistry", "_on_event"),
    Subscription(3, "Trade", "SensorRegistry", "_on_event"),
    Subscription(4, "SensorReading", "HorizonAggregator", "_on_sensor_reading"),
    Subscription(5, "HorizonTick", "HorizonAggregator", "_on_horizon_tick"),
    Subscription(6, "RegimeState", "HorizonSignalEngine", "_on_regime_state"),
    Subscription(7, "SensorReading", "HorizonSignalEngine", "_on_sensor_reading"),
    Subscription(8, "HorizonFeatureSnapshot", "HorizonSignalEngine", "_on_snapshot"),
    Subscription(9, "HorizonFeatureSnapshot", "UniverseSynchronizer", "_on_snapshot"),
    Subscription(10, "Signal", "UniverseSynchronizer", "_on_signal"),
    Subscription(11, "HorizonTick", "UniverseSynchronizer", "_on_tick"),
    Subscription(12, "CrossSectionalContext", "CompositionEngine", "_on_context"),
    Subscription(13, "CrossSectionalContext", "CrossSectionalTracker", "_on_context"),
    Subscription(14, "SizedPositionIntent", "CrossSectionalTracker", "_on_intent"),
    Subscription(15, "CrossSectionalContext", "HorizonMetricsCollector", "_on_context"),
    Subscription(16, "SizedPositionIntent", "HorizonMetricsCollector", "_on_intent"),
    Subscription(17, "RegimeHazardSpike", "HorizonMetricsCollector", "_on_hazard_spike"),
    Subscription(18, "OrderRequest", "HorizonMetricsCollector", "_on_order"),
    Subscription(19, "NBBOQuote", "StopExitController", "_on_quote"),
    Subscription(20, "RegimeHazardSpike", "HazardExitController", "_on_spike"),
    Subscription(21, "Trade", "HazardExitController", "_on_trade"),
    Subscription(22, "SafetyStateChange", "DeferralCapController", "_on_safety_state_change"),
    Subscription(23, "Trade", "DeferralCapController", "_on_trade"),
    Subscription(24, "SafetyStateChange", "ExitComposer", "_on_safety_state_change"),
    Subscription(25, "MetricEvent", "Orchestrator", "_on_metric_event"),
    Subscription(26, "LatencyBreach", "Orchestrator", "_on_latency_breach"),
    Subscription(27, "Alert", "Orchestrator", "_on_alert_event"),
    Subscription(28, "Signal", "Orchestrator", "_on_bus_signal"),
    Subscription(29, "SizedPositionIntent", "Orchestrator", "_on_bus_sized_intent"),
    Subscription(30, "DeRiskRequirement", "Orchestrator", "_on_bus_derisk_requirement"),
    Subscription(31, "OrderAck", "_NotificationObserver", "on_event"),
    Subscription(32, "PositionUpdate", "_NotificationObserver", "on_event"),
    Subscription(33, "RiskVerdict", "_NotificationObserver", "on_event"),
    Subscription(34, "SymbolHalted", "_NotificationObserver", "on_event"),
    Subscription(35, "KillSwitchActivation", "_NotificationObserver", "on_event"),
)

ZERO_SUBSCRIBER_RESOLUTIONS: tuple[tuple[str, str], ...] = (
    ("OrderAck", "consumer"),
    ("PositionUpdate", "consumer"),
    ("RiskVerdict", "consumer"),
    ("SymbolHalted", "consumer"),
    ("KillSwitchActivation", "consumer"),
    ("StateTransition", "notification_record"),
)

# Frozen remainder of G39. The five bootstrap patches are constructor-injected
# and must not appear here.
COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("src/feelies/broker/ib/contracts.py", "c.symbol"),
        ("src/feelies/broker/ib/contracts.py", "c.secType"),
        ("src/feelies/broker/ib/contracts.py", "c.exchange"),
        ("src/feelies/broker/ib/contracts.py", "c.currency"),
        ("src/feelies/broker/ib/contracts.py", "c.primaryExchange"),
        ("src/feelies/broker/ib/router.py", "order.action"),
        ("src/feelies/broker/ib/router.py", "order.totalQuantity"),
        ("src/feelies/broker/ib/router.py", "order.tif"),
        ("src/feelies/broker/ib/router.py", "order.eTradeOnly"),
        ("src/feelies/broker/ib/router.py", "order.firmQuoteOnly"),
        ("src/feelies/broker/ib/router.py", "order.orderType"),
        ("src/feelies/broker/ib/router.py", "order.lmtPrice"),
        ("src/feelies/cli/forensics.py", "sub.required"),
        ("src/feelies/cli/main.py", "subparsers.required"),
        ("src/feelies/cli/promote.py", "sub.required"),
        ("src/feelies/execution/passive_limit_router.py", "pending.at_bbo"),
        ("src/feelies/execution/passive_limit_router.py", "pending.ticks_at_level"),
        ("src/feelies/execution/passive_limit_router.py", "pending.shares_traded_at_level"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_fills_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_sensor_readings_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_horizon_ticks_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_snapshots_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_signals_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_hazard_spikes_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_cross_sectional_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_sized_intents_jsonl"),
        ("src/feelies/harness/backtest_cli.py", "args.emit_hazard_exits_jsonl"),
        ("src/feelies/portfolio/memory_position_store.py", "pos.quantity"),
        ("src/feelies/portfolio/memory_position_store.py", "pos.unrealized_pnl"),
        ("src/feelies/portfolio/memory_position_store.py", "pos.avg_entry_price"),
        ("src/feelies/storage/submitted_order_journal.py", "router.submit"),
        ("src/feelies/storage/submitted_order_journal.py", "router.poll_acks"),
    }
)

COMPOSITION_ROOT_PRIVATE_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("src/feelies/bootstrap.py", "module._construct"),
        ("src/feelies/bootstrap.py", "horizon_scheduler._session_id"),
        ("src/feelies/cli/backtest.py", "argparse._SubParsersAction"),
        ("src/feelies/harness/backtest_runner.py", "orchestrator._bus"),
        ("src/feelies/harness/backtest_runner.py", "_metrics_collector._events"),
        ("src/feelies/signals/regime_gate.py", "gate._referenced_identifiers"),
    }
)


def manifest_hash() -> str:
    """SHA-256 of the declared graph. Part of the run fingerprint."""
    payload = {
        "subscriptions": [
            {
                "disposition": row.disposition,
                "event_type": row.event_type,
                "method": row.method,
                "ordinal": row.ordinal,
                "subscriber": row.subscriber,
            }
            for row in SUBSCRIPTIONS
        ],
        "zero_subscriber_resolutions": [
            {"event_type": event_type, "resolution": resolution}
            for event_type, resolution in ZERO_SUBSCRIBER_RESOLUTIONS
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
