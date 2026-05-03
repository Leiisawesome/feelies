"""Composition-layer metric collector — Phase-4-finalize observability.

Subscribes to the bus events emitted by the Phase-4 composition
pipeline and the Phase-4.1 hazard-exit controller and records the 12
metrics enumerated in :doc:`/docs/three_layer_architecture`
§20.12.2:

==  ====================================  ======================================
#   Metric                                 Source event(s)
==  ====================================  ======================================
1   ``composition.completeness``           ``CrossSectionalContext.completeness``
2   ``composition.gross_usd``              ``SizedPositionIntent``
3   ``composition.net_usd``                ``SizedPositionIntent``
4   ``composition.expected_turnover_usd``  ``SizedPositionIntent``
5   ``composition.barriers_emitted``       ``CrossSectionalContext`` (counter)
6   ``composition.intents_emitted``        ``SizedPositionIntent`` (counter)
7   ``composition.degenerate_intents``     ``SizedPositionIntent`` w/ empty
                                            ``target_positions`` (counter)
8   ``composition.factor_residual_l2``     ``SizedPositionIntent.factor_exposures``
9   ``composition.mechanism_share.{name}`` ``SizedPositionIntent.mechanism_breakdown``
10  ``composition.regime_state.{name}``    ``RegimeState`` (passthrough)
11  ``composition.hazard_spikes_observed`` ``RegimeHazardSpike`` (counter)
12  ``composition.hazard_exits_emitted``   ``OrderRequest`` w/ ``reason='HAZARD_SPIKE'``
                                            or ``'HARD_EXIT_AGE'`` (counter)
==  ====================================  ======================================

Each metric is also tagged with ``strategy_id``, ``horizon_seconds``
where applicable so downstream dashboards can slice by alpha.

Alert thresholds (§20.12.2 Alerts table):

* ``composition.completeness < 0.50``           → WARNING
* ``composition.degenerate_intents`` rate > 5%  → WARNING
* ``composition.factor_residual_l2 > 0.05``     → WARNING (neutralization
                                                  degraded — model may be
                                                  rank-deficient)
* ``composition.hazard_exits_emitted`` spike    → INFO  (auditable but not
                                                  actionable on its own)

The collector is **read-only** with respect to the pipeline: it only
publishes :class:`MetricEvent` and :class:`Alert` events; it never
mutates positions, intents, or orders.

Determinism (Inv-5)
-------------------

The collector performs no time reads — every emitted metric inherits
the timestamp of the event that triggered it.  Two replays produce
identical metric streams.
"""

from __future__ import annotations

import logging
import math
from typing import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Alert,
    AlertSeverity,
    CrossSectionalContext,
    MetricEvent,
    MetricType,
    OrderRequest,
    RegimeHazardSpike,
    SizedPositionIntent,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator

_logger = logging.getLogger(__name__)

# Alert thresholds (§20.12.2)
COMPLETENESS_WARN_THRESHOLD: float = 0.50
DEGENERATE_RATE_WARN_THRESHOLD: float = 0.05
FACTOR_RESIDUAL_WARN_THRESHOLD: float = 0.05


class HorizonMetricsCollector:
    """Bus-attached composition metrics + alert publisher.

    One instance per platform.  Constructed by the bootstrap layer
    when at least one PORTFOLIO alpha is registered (Inv-A: legacy
    deployments stay bit-identical because the collector is never
    instantiated and the bus carries zero ``MetricEvent`` /
    ``Alert`` extras).
    """

    __slots__ = (
        "_bus",
        "_metric_seq",
        "_attached",
        "_intents_total",
        "_degenerate_total",
        "_barriers_total",
        "_hazard_spikes_total",
        "_hazard_exits_total",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        metric_sequence_generator: SequenceGenerator | None = None,
    ) -> None:
        self._bus = bus
        self._metric_seq = metric_sequence_generator or SequenceGenerator()
        self._attached = False
        self._intents_total = 0
        self._degenerate_total = 0
        self._barriers_total = 0
        self._hazard_spikes_total = 0
        self._hazard_exits_total = 0

    # ── Public API ───────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        self._bus.subscribe(
            CrossSectionalContext, self._on_context,  # type: ignore[arg-type]
        )
        self._bus.subscribe(
            SizedPositionIntent, self._on_intent,  # type: ignore[arg-type]
        )
        self._bus.subscribe(
            RegimeHazardSpike, self._on_hazard_spike,  # type: ignore[arg-type]
        )
        self._bus.subscribe(
            OrderRequest, self._on_order,  # type: ignore[arg-type]
        )
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_context(self, ctx: CrossSectionalContext) -> None:
        self._barriers_total += 1
        self._publish_metric(
            ctx.timestamp_ns,
            ctx.correlation_id,
            "composition.completeness",
            float(ctx.completeness),
            MetricType.GAUGE,
            tags={"horizon_seconds": str(ctx.horizon_seconds)},
        )
        self._publish_metric(
            ctx.timestamp_ns,
            ctx.correlation_id,
            "composition.barriers_emitted",
            float(self._barriers_total),
            MetricType.COUNTER,
            tags={"horizon_seconds": str(ctx.horizon_seconds)},
        )
        if ctx.completeness < COMPLETENESS_WARN_THRESHOLD:
            self._publish_alert(
                ctx.timestamp_ns,
                ctx.correlation_id,
                AlertSeverity.WARNING,
                "composition.low_completeness",
                f"completeness={ctx.completeness:.3f} < "
                f"{COMPLETENESS_WARN_THRESHOLD}",
                context={
                    "horizon_seconds": ctx.horizon_seconds,
                    "boundary_index": ctx.boundary_index,
                    "completeness": float(ctx.completeness),
                },
            )

    def _on_intent(self, intent: SizedPositionIntent) -> None:
        self._intents_total += 1
        is_degenerate = not intent.target_positions
        if is_degenerate:
            self._degenerate_total += 1

        gross, net = self._gross_net(intent.target_positions)
        residual_l2 = self._l2_norm(intent.factor_exposures)
        tags = {
            "strategy_id": intent.strategy_id,
            "horizon_seconds": str(intent.horizon_seconds),
        }

        self._publish_metric(
            intent.timestamp_ns, intent.correlation_id,
            "composition.intents_emitted", float(self._intents_total),
            MetricType.COUNTER, tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns, intent.correlation_id,
            "composition.gross_usd", gross, MetricType.GAUGE, tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns, intent.correlation_id,
            "composition.net_usd", net, MetricType.GAUGE, tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns, intent.correlation_id,
            "composition.expected_turnover_usd",
            float(intent.expected_turnover_usd),
            MetricType.GAUGE, tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns, intent.correlation_id,
            "composition.factor_residual_l2", residual_l2,
            MetricType.GAUGE, tags=tags,
        )

        for mech in sorted(intent.mechanism_breakdown, key=lambda m: m.name):
            share = float(intent.mechanism_breakdown[mech])
            self._publish_metric(
                intent.timestamp_ns, intent.correlation_id,
                f"composition.mechanism_share.{mech.name}",
                share, MetricType.GAUGE, tags=tags,
            )

        if is_degenerate:
            self._publish_metric(
                intent.timestamp_ns, intent.correlation_id,
                "composition.degenerate_intents",
                float(self._degenerate_total),
                MetricType.COUNTER, tags=tags,
            )
            rate = self._degenerate_total / max(1, self._intents_total)
            if rate > DEGENERATE_RATE_WARN_THRESHOLD:
                self._publish_alert(
                    intent.timestamp_ns, intent.correlation_id,
                    AlertSeverity.WARNING,
                    "composition.high_degenerate_rate",
                    f"degenerate_rate={rate:.3f} > "
                    f"{DEGENERATE_RATE_WARN_THRESHOLD}",
                    context={
                        "strategy_id": intent.strategy_id,
                        "degenerate_total": self._degenerate_total,
                        "intents_total": self._intents_total,
                    },
                )

        if residual_l2 > FACTOR_RESIDUAL_WARN_THRESHOLD:
            self._publish_alert(
                intent.timestamp_ns, intent.correlation_id,
                AlertSeverity.WARNING,
                "composition.factor_residual_high",
                f"factor_residual_l2={residual_l2:.4f} > "
                f"{FACTOR_RESIDUAL_WARN_THRESHOLD}",
                context={
                    "strategy_id": intent.strategy_id,
                    "factor_exposures": dict(intent.factor_exposures),
                },
            )

    def _on_hazard_spike(self, spike: RegimeHazardSpike) -> None:
        self._hazard_spikes_total += 1
        self._publish_metric(
            spike.timestamp_ns, spike.correlation_id,
            "composition.hazard_spikes_observed",
            float(self._hazard_spikes_total),
            MetricType.COUNTER,
            tags={
                "engine_name": spike.engine_name,
                "departing_state": spike.departing_state,
            },
        )

    def _on_order(self, order: OrderRequest) -> None:
        # Only count hazard-driven exits — ordinary orders are tracked
        # by the existing order-flow metrics elsewhere in the platform.
        if order.reason not in ("HAZARD_SPIKE", "HARD_EXIT_AGE"):
            return
        self._hazard_exits_total += 1
        self._publish_metric(
            order.timestamp_ns, order.correlation_id,
            "composition.hazard_exits_emitted",
            float(self._hazard_exits_total),
            MetricType.COUNTER,
            tags={"reason": order.reason, "symbol": order.symbol},
        )

    # ── Internals ────────────────────────────────────────────────────

    def _publish_metric(
        self,
        timestamp_ns: int,
        correlation_id: str,
        name: str,
        value: float,
        metric_type: MetricType,
        *,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        evt = MetricEvent(
            timestamp_ns=timestamp_ns,
            correlation_id=correlation_id,
            sequence=self._metric_seq.next(),
            source_layer="COMPOSITION",
            layer="COMPOSITION",
            name=name,
            value=float(value),
            metric_type=metric_type,
            tags=dict(tags or {}),
        )
        self._bus.publish(evt)

    def _publish_alert(
        self,
        timestamp_ns: int,
        correlation_id: str,
        severity: AlertSeverity,
        name: str,
        message: str,
        *,
        context: Mapping[str, object] | None = None,
    ) -> None:
        alert = Alert(
            timestamp_ns=timestamp_ns,
            correlation_id=correlation_id,
            sequence=self._metric_seq.next(),
            source_layer="COMPOSITION",
            severity=severity,
            layer="COMPOSITION",
            alert_name=name,
            message=message,
            context=dict(context or {}),
        )
        self._bus.publish(alert)

    @staticmethod
    def _gross_net(
        target_positions: Mapping[str, object],
    ) -> tuple[float, float]:
        gross = 0.0
        net = 0.0
        for symbol in sorted(target_positions):
            usd = float(getattr(target_positions[symbol], "target_usd", 0.0))
            gross += abs(usd)
            net += usd
        return gross, net

    @staticmethod
    def _l2_norm(exposures: Mapping[str, float]) -> float:
        if not exposures:
            return 0.0
        return math.sqrt(sum(float(v) ** 2 for v in exposures.values()))


# Re-export TrendMechanism for downstream callers that build mechanism-tagged
# metric names without taking a separate dependency.
__all__ = [
    "COMPLETENESS_WARN_THRESHOLD",
    "DEGENERATE_RATE_WARN_THRESHOLD",
    "FACTOR_RESIDUAL_WARN_THRESHOLD",
    "HorizonMetricsCollector",
    "TrendMechanism",
]
