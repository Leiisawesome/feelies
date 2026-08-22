"""Pin engine 11 Alert taxonomy: alert_name and severity only.

Never hashes ``message``.  Pinning alert content would convert every
diagnostic wording change into a parity break.
"""

from __future__ import annotations

import hashlib

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Alert,
    CrossSectionalContext,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector


def _hash_taxonomy(alerts: list[Alert]) -> str:
    lines = [f"{a.alert_name}|{a.severity.name}" for a in alerts]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _replay() -> tuple[str, int]:
    bus = EventBus()
    alerts: list[Alert] = []
    bus.subscribe(Alert, alerts.append)
    collector = HorizonMetricsCollector(
        bus=bus,
        metric_sequence_generator=SequenceGenerator(start=1, stream="metric"),
    )
    collector.attach()

    bus.publish(
        CrossSectionalContext(
            timestamp_ns=1_000,
            correlation_id="ctx:low",
            sequence=1,
            horizon_seconds=300,
            boundary_index=1,
            universe=("AAPL", "MSFT"),
            completeness=0.25,
        )
    )
    bus.publish(
        SizedPositionIntent(
            timestamp_ns=2_000,
            correlation_id="intent:degen",
            sequence=2,
            source_layer="PORTFOLIO",
            strategy_id="port_tax",
            horizon_seconds=300,
            target_positions={},
        )
    )
    bus.publish(
        SizedPositionIntent(
            timestamp_ns=3_000,
            correlation_id="intent:solver",
            sequence=3,
            source_layer="PORTFOLIO",
            strategy_id="port_tax",
            horizon_seconds=300,
            target_positions={"AAPL": TargetPosition(symbol="AAPL", target_usd=1000.0)},
            solver_status="ECOS_FAILED_FALLBACK",
            factor_exposures={"mkt": 0.10},
        )
    )
    assert alerts, "fixture produced no alerts — the taxonomy hash would be vacuous"
    return _hash_taxonomy(alerts), len(alerts)


EXPECTED_ALERT_TAXONOMY_HASH = "f6b784b275a549e169f7075ca583b9f198966f802216fbf7e8eb835d6f31b557"
EXPECTED_ALERT_TAXONOMY_COUNT = 4


def test_alert_taxonomy_replay_matches_locked_hash() -> None:
    actual = _replay()
    assert actual == (EXPECTED_ALERT_TAXONOMY_HASH, EXPECTED_ALERT_TAXONOMY_COUNT)
