"""Declared, hashed subscription graph for the composition root.

The ordinals are the measured ``EventBus.subscribe`` call order from a
phase-4 ``build_platform`` (PYTHONHASHSEED=0): wrap ``EventBus.subscribe``,
compose, record ``(event_type, subscriber)``. Conditional authors that
did not attach on that run (hazard, deferral, exit-composer) sit in the
slot they occupy when they do attach — between StopExit and Orchestrator.
New observers for previously zero-subscriber types are appended; they
subscribe distinct types, so existing per-type order is unchanged.

Zero-subscriber resolution:

* ``StateTransition`` — notification record. Publish stays, and nothing
  subscribes, because it is not a domain-bus consumer (G10).
  ``OrderAck``, ``PositionUpdate``, ``RiskVerdict``, ``SymbolHalted``,
  and ``KillSwitchActivation`` are subscribers (ordinals 31-35), not
  resolutions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, NamedTuple

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
    ("StateTransition", "notification_record"),
)


class CompositionRootAssignment(NamedTuple):
    """One external attribute assignment the composition-root pin counts."""

    path: str
    target: str
    reason: str


class CompositionRootPrivate(NamedTuple):
    """One cross-object private reach the composition-root pin counts."""

    path: str
    expr: str
    reason: str


# One row per live scanner site. A repeated (path, target) is a repeated
# site: the pin is a Counter, not a set. Bootstrap's constructor-injected
# patches are not rows.
COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST: tuple[CompositionRootAssignment, ...] = (
    CompositionRootAssignment(
        "src/feelies/broker/ib/contracts.py",
        "c.symbol",
        "ibapi.Contract() takes no symbol argument; the library reads the attribute",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/contracts.py",
        "c.secType",
        "ibapi.Contract() takes no secType argument; STK is this factory's asset class",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/contracts.py",
        "c.exchange",
        "ibapi.Contract() takes no exchange argument; the caller passes SMART or an override",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/contracts.py",
        "c.currency",
        "ibapi.Contract() takes no currency argument; the caller passes USD or an override",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/contracts.py",
        "c.primaryExchange",
        "ibapi.Contract() takes no primaryExchange argument; set only to disambiguate a cross-listed symbol",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.action",
        "ibapi.Order() takes no action argument; request.side maps to BUY or SELL",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.totalQuantity",
        "ibapi.Order() takes no totalQuantity argument; ibapi 10.x requires a Decimal quantity",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.tif",
        "ibapi.Order() takes no tif argument; the router submits DAY",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.eTradeOnly",
        "ibapi.Order() leaves eTradeOnly set so the gateway rejects with Error 10268; the router sets False",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.firmQuoteOnly",
        "ibapi.Order() leaves firmQuoteOnly set so the gateway rejects with Error 10268; the router sets False",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.orderType",
        "limit branch: ibapi.Order() takes no orderType argument; LMT comes from OrderType.LIMIT",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.lmtPrice",
        "limit branch: ibapi.Order() takes no lmtPrice argument; the request limit is not a constructor field",
    ),
    CompositionRootAssignment(
        "src/feelies/broker/ib/router.py",
        "order.orderType",
        "market branch: ibapi.Order() takes no orderType argument; MKT is the non-limit path",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.at_bbo",
        "buy through-fill: this quote's ask crossed the resting limit after _PendingOrder was built",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.ticks_at_level",
        "buy left the level: reset the at-level tick clock; the quote arrives after construction",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.shares_traded_at_level",
        "buy left the level: reset shares traded at the level; the quote arrives after construction",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.at_bbo",
        "sell through-fill: this quote's bid crossed the resting limit after _PendingOrder was built",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.ticks_at_level",
        "sell left the level: reset the at-level tick clock; the quote arrives after construction",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.shares_traded_at_level",
        "sell left the level: reset shares traded at the level; the quote arrives after construction",
    ),
    CompositionRootAssignment(
        "src/feelies/execution/passive_limit_router.py",
        "pending.at_bbo",
        "record whether this quote is at the resting level so a later timeout cancel can be classified; the quote is after construction",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_fills_jsonl",
        "cache-replay entry forces emit_fills_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_sensor_readings_jsonl",
        "cache-replay entry forces emit_sensor_readings_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_horizon_ticks_jsonl",
        "cache-replay entry forces emit_horizon_ticks_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_snapshots_jsonl",
        "cache-replay entry forces emit_snapshots_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_signals_jsonl",
        "cache-replay entry forces emit_signals_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_hazard_spikes_jsonl",
        "cache-replay entry forces emit_hazard_spikes_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_cross_sectional_jsonl",
        "cache-replay entry forces emit_cross_sectional_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_sized_intents_jsonl",
        "cache-replay entry forces emit_sized_intents_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/harness/backtest_cli.py",
        "args.emit_hazard_exits_jsonl",
        "cache-replay entry forces emit_hazard_exits_jsonl off on a Namespace it did not build; a new Namespace would drop the other parsed fields",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.avg_entry_price",
        "open from flat: the fill price is the episode entry; Position(symbol=) exists before the fill, and get() has already handed out that instance",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.avg_entry_price",
        "same-direction add: blend the new fill into the open episode; the fill is after construction, and a new Position would fork get()",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.avg_entry_price",
        "reversal: the fill crosses through zero and the residual opens at the fill price; that size is not known at construction",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.avg_entry_price",
        "flat: the closing fill zeros the stored entry; the fill is after construction, and get() holds this instance",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.quantity",
        "apply the fill's quantity delta to the Position instance get() already returned",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.unrealized_pnl",
        "quantity is zero, so unrealized PnL is zero; that quantity is the result of a later fill",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.unrealized_pnl",
        "no bid, ask, or mid is stored yet, so unrealized PnL stays zero instead of a missing mark",
    ),
    CompositionRootAssignment(
        "src/feelies/portfolio/memory_position_store.py",
        "pos.unrealized_pnl",
        "mark to the side-specific BBO, else the mid, times quantity; the mark arrives on a later quote",
    ),
    CompositionRootAssignment(
        "src/feelies/storage/submitted_order_journal.py",
        "router.submit",
        "router has no bind_submitted_order_journal, so the journal wraps the already-built submit to refuse a duplicate order_id",
    ),
    CompositionRootAssignment(
        "src/feelies/storage/submitted_order_journal.py",
        "router.poll_acks",
        "same fallback: wrap the already-built poll_acks so a reject updates the journal the router was not constructed with",
    ),
)

COMPOSITION_ROOT_PRIVATE_ALLOWLIST: tuple[CompositionRootPrivate, ...] = (
    CompositionRootPrivate(
        "src/feelies/bootstrap.py",
        "module._construct",
        "read the loader's private callable to see if it is the default constructor; construct() invokes it and does not return it, and the engine does not exist when the module is first built",
    ),
    CompositionRootPrivate(
        "src/feelies/bootstrap.py",
        "horizon_scheduler._session_id",
        "log the session id HorizonScheduler stored from its constructor argument; there is no public reader, and this reach is a read, not a second injection",
    ),
    CompositionRootPrivate(
        "src/feelies/cli/backtest.py",
        "argparse._SubParsersAction",
        "register() annotates the object add_subparsers returns; argparse publishes that type only as _SubParsersAction, and the name is not a value to inject",
    ),
    CompositionRootPrivate(
        "src/feelies/harness/backtest_runner.py",
        "orchestrator._bus",
        "subscribe the harness BusRecorder to the event types this invocation retains; the recorder is built from CLI flags after the orchestrator exists, and Orchestrator does not take harness subscribers",
    ),
    CompositionRootPrivate(
        "src/feelies/harness/backtest_runner.py",
        "orchestrator._bus",
        "subscribe a harness closure that keeps only tick_to_decision_latency_ns MetricEvents; the closure is created after the orchestrator exists",
    ),
    CompositionRootPrivate(
        "src/feelies/harness/backtest_runner.py",
        "orchestrator._bus",
        "subscribe QuoteReplayObserver after boot, once n_quotes is known; the observer does not exist at Orchestrator construction",
    ),
    CompositionRootPrivate(
        "src/feelies/harness/backtest_runner.py",
        "_metrics_collector._events",
        "drop warmup MetricEvents stored after the collector was constructed and before replay; those events do not exist at construction, and the buffer is private",
    ),
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
