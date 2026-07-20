"""Read-only composition and hazard-exit metrics.

The collector publishes completeness, exposure, turnover, intent, residual,
mechanism-share, hazard, and solver-health metrics. It warns on low completeness,
frequent degenerate intents, large factor residuals, and degraded solvers.
Metrics inherit source-event timestamps, so replay output is deterministic.
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

# Optimizer terminal statuses that are *not* a degradation: the
# deterministic closed-form path, a healthy ECOS solve, and the benign
# "nothing to size" outcomes.  Any other non-empty status (e.g.
# ``ECOS_FAILED_FALLBACK``, ``infeasible``, ``unbounded``) raises a warning.
# Empty string means not recorded and is ignored.
_HEALTHY_SOLVER_STATUSES: frozenset[str] = frozenset(
    {"CLOSED_FORM", "optimal", "optimal_inaccurate", "ZERO_GROSS", "EMPTY_UNIVERSE"}
)


class HorizonMetricsCollector:
    """Bus-attached composition metrics + alert publisher.

    Bootstrap constructs one instance only when a PORTFOLIO alpha is registered,
    so other deployments emit no extra metrics or alerts.
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
        "_last_solver_status",
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
        # Last status per alpha throttles repeated solver-degradation alerts.
        self._last_solver_status: dict[str, str] = {}

    # ── Public API ───────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        self._bus.subscribe(CrossSectionalContext, self._on_context)
        self._bus.subscribe(SizedPositionIntent, self._on_intent)
        self._bus.subscribe(RegimeHazardSpike, self._on_hazard_spike)
        self._bus.subscribe(OrderRequest, self._on_order)
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
                f"completeness={ctx.completeness:.3f} < {COMPLETENESS_WARN_THRESHOLD}",
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
            intent.timestamp_ns,
            intent.correlation_id,
            "composition.intents_emitted",
            float(self._intents_total),
            MetricType.COUNTER,
            tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns,
            intent.correlation_id,
            "composition.gross_usd",
            gross,
            MetricType.GAUGE,
            tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns,
            intent.correlation_id,
            "composition.net_usd",
            net,
            MetricType.GAUGE,
            tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns,
            intent.correlation_id,
            "composition.expected_turnover_usd",
            float(intent.expected_turnover_usd),
            MetricType.GAUGE,
            tags=tags,
        )
        self._publish_metric(
            intent.timestamp_ns,
            intent.correlation_id,
            "composition.factor_residual_l2",
            residual_l2,
            MetricType.GAUGE,
            tags=tags,
        )

        for mech in sorted(intent.mechanism_breakdown, key=lambda m: m.name):
            share = float(intent.mechanism_breakdown[mech])
            self._publish_metric(
                intent.timestamp_ns,
                intent.correlation_id,
                f"composition.mechanism_share.{mech.name}",
                share,
                MetricType.GAUGE,
                tags=tags,
            )

        if is_degenerate:
            self._publish_metric(
                intent.timestamp_ns,
                intent.correlation_id,
                "composition.degenerate_intents",
                float(self._degenerate_total),
                MetricType.COUNTER,
                tags=tags,
            )
            rate = self._degenerate_total / max(1, self._intents_total)
            if rate > DEGENERATE_RATE_WARN_THRESHOLD:
                self._publish_alert(
                    intent.timestamp_ns,
                    intent.correlation_id,
                    AlertSeverity.WARNING,
                    "composition.high_degenerate_rate",
                    f"degenerate_rate={rate:.3f} > {DEGENERATE_RATE_WARN_THRESHOLD}",
                    context={
                        "strategy_id": intent.strategy_id,
                        "degenerate_total": self._degenerate_total,
                        "intents_total": self._intents_total,
                    },
                )

        # Alert only on transition into a degraded optimizer status.
        status = intent.solver_status
        prev_status = self._last_solver_status.get(intent.strategy_id, "")
        if status and status not in _HEALTHY_SOLVER_STATUSES and status != prev_status:
            self._publish_alert(
                intent.timestamp_ns,
                intent.correlation_id,
                AlertSeverity.WARNING,
                "composition.solver_degraded",
                f"optimizer solver_status={status!r} (degraded)",
                context={
                    "strategy_id": intent.strategy_id,
                    "solver_status": status,
                    "previous_status": prev_status,
                },
            )
        self._last_solver_status[intent.strategy_id] = status

        if residual_l2 > FACTOR_RESIDUAL_WARN_THRESHOLD:
            self._publish_alert(
                intent.timestamp_ns,
                intent.correlation_id,
                AlertSeverity.WARNING,
                "composition.factor_residual_high",
                f"factor_residual_l2={residual_l2:.4f} > {FACTOR_RESIDUAL_WARN_THRESHOLD}",
                context={
                    "strategy_id": intent.strategy_id,
                    "factor_exposures": dict(intent.factor_exposures),
                },
            )

    def _on_hazard_spike(self, spike: RegimeHazardSpike) -> None:
        self._hazard_spikes_total += 1
        self._publish_metric(
            spike.timestamp_ns,
            spike.correlation_id,
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
            order.timestamp_ns,
            order.correlation_id,
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
