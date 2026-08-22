"""Sequence-authority and producer registry (G09).

Streams are the named SequenceGenerator construction sites in src/feelies.
Authorities are the classes that own those generators. Contracts are the
bus event types already enumerated in wiring_manifest.SUBSCRIPTIONS and
ZERO_SUBSCRIBER_RESOLUTIONS; each is produced by the stream that stamps it.
gate_registry.record_verdict draws no sequence and is not a producer.

Two construction sites share a stream when one is the injected generator
and the other is the recipient's fallback: ``hazard`` (bootstrap +
Orchestrator) and ``metric`` (bootstrap + HorizonMetricsCollector).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SequenceAuthority:
    """One named sequence stream and the class that may draw from it."""

    stream: str
    authority: str
    contracts: tuple[str, ...] = ()


STREAM_AUTHORITIES: tuple[SequenceAuthority, ...] = (
    SequenceAuthority("risk_alert", "BasicRiskEngine", ("Alert",)),
    SequenceAuthority("ib_alert", "bootstrap", ("Alert",)),
    SequenceAuthority("sensor", "SensorRegistry", ("SensorReading",)),
    SequenceAuthority("horizon", "HorizonScheduler", ("HorizonTick",)),
    SequenceAuthority("snapshot", "HorizonAggregator", ("HorizonFeatureSnapshot",)),
    SequenceAuthority("hazard", "Orchestrator", ("RegimeHazardSpike",)),
    SequenceAuthority("signal", "HorizonSignalEngine", ("Signal",)),
    SequenceAuthority("intent", "CompositionEngine", ("SizedPositionIntent",)),
    SequenceAuthority("ctx", "UniverseSynchronizer", ("CrossSectionalContext",)),
    SequenceAuthority(
        "metric",
        "HorizonMetricsCollector",
        ("MetricEvent", "Alert"),
    ),
    SequenceAuthority("stop_exit", "StopExitController", ("OrderRequest",)),
    SequenceAuthority("hazard_exit", "HazardExitController", ("OrderRequest",)),
    SequenceAuthority("exit_composer", "ExitComposer", ("OrderRequest",)),
    SequenceAuthority("deferral_cap", "DeferralCapController", ("OrderRequest",)),
    SequenceAuthority("sensor_metrics", "SensorRegistry", ("MetricEvent",)),
    SequenceAuthority("signal_metrics", "HorizonSignalEngine", ("MetricEvent",)),
    SequenceAuthority("safety", "HorizonSignalEngine", ("SafetyStateChange",)),
    SequenceAuthority(
        "orchestrator",
        "Orchestrator",
        (
            "Alert",
            "KillSwitchActivation",
            "LatencyBreach",
            "MetricEvent",
            "OrderRequest",
            "PositionUpdate",
            "RegimeState",
            "RiskVerdict",
            "StateTransition",
            "SymbolHalted",
        ),
    ),
    SequenceAuthority("scheduler_metrics", "HorizonScheduler", ("MetricEvent",)),
    SequenceAuthority("aggregator_metrics", "HorizonAggregator", ("MetricEvent",)),
    SequenceAuthority("backtest_ack", "BacktestOrderRouter", ("OrderAck",)),
    SequenceAuthority("passive_limit_ack", "PassiveLimitOrderRouter", ("OrderAck",)),
    SequenceAuthority("ib_ack", "IBOrderRouter", ("OrderAck",)),
    SequenceAuthority("massive", "MassiveNormalizer", ("NBBOQuote", "Trade")),
)
