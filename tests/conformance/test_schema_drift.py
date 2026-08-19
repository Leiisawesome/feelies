"""S8 — every event class resolves a schema version; field drift is detected.

G07: 2 of 21 event classes carry a payload version field
(``SensorReading.sensor_version``, ``HorizonFeatureSnapshot.feature_versions``).
Hot-path events are otherwise unversioned. The envelope field
``schema_version`` is the consumer-readability pin. The pinned-code-per-log
rule is ``SCHEMA_VERSION`` in ``feelies.core.events``.

The log-level pin is ``event_schema_hash`` (disk_event_cache._compute_schema_hash);
R5 is withdrawn. S8 does not re-implement it.

S8 detects DRIFT, not field presence: a throwaway field on any event class
must fail this test by name. Payload version fields stay payload; they are
not the envelope pin.
"""

from __future__ import annotations

import feelies.core.events as events_mod
from feelies.core.events import Event

# Envelope fields every Event subclass must resolve, in dataclass order.
PINNED_ENVELOPE: tuple[str, ...] = (
    "timestamp_ns",
    "correlation_id",
    "sequence",
    "source_layer",
    "schema_version",
)

# Subclass payload fields after the envelope, in dataclass order.
PINNED_PAYLOAD: dict[str, tuple[str, ...]] = {
    "Alert": ("severity", "layer", "alert_name", "message", "context"),
    "CrossSectionalContext": (
        "horizon_seconds",
        "boundary_index",
        "universe",
        "signals_by_symbol",
        "signals_by_strategy_by_symbol",
        "snapshots_by_symbol",
        "completeness",
    ),
    "HorizonFeatureSnapshot": (
        "symbol",
        "horizon_seconds",
        "boundary_index",
        "boundary_ts_ns",
        "values",
        "warm",
        "stale",
        "source_sensors",
        "feature_versions",
        "parent_correlation_id",
    ),
    "HorizonTick": (
        "horizon_seconds",
        "boundary_index",
        "session_id",
        "scope",
        "boundary_timestamp_ns",
        "symbol",
        "boundary_ts_ns",
    ),
    "KillSwitchActivation": ("reason", "activated_by"),
    "LatencyBreach": (
        "engine",
        "statistic",
        "window_events",
        "observed_ns",
        "budget_ns",
    ),
    "MetricEvent": ("layer", "name", "value", "metric_type", "tags"),
    "NBBOQuote": (
        "symbol",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
        "bid_exchange",
        "ask_exchange",
        "exchange_timestamp_ns",
        "conditions",
        "indicators",
        "sequence_number",
        "tape",
        "participant_timestamp_ns",
        "trf_timestamp_ns",
        "received_ns",
    ),
    "OrderAck": (
        "order_id",
        "symbol",
        "status",
        "filled_quantity",
        "fill_price",
        "fees",
        "cost_bps",
        "reason",
        "request_sequence",
    ),
    "OrderRequest": (
        "order_id",
        "symbol",
        "side",
        "order_type",
        "quantity",
        "limit_price",
        "strategy_id",
        "is_short",
        "is_moc",
        "g12_disclosed_cost_total_bps",
        "reason",
    ),
    "PositionUpdate": (
        "symbol",
        "quantity",
        "avg_price",
        "realized_pnl",
        "unrealized_pnl",
        "cumulative_fees",
        "cost_bps",
    ),
    "RegimeHazardSpike": (
        "symbol",
        "engine_name",
        "departing_state",
        "departing_posterior_prev",
        "departing_posterior_now",
        "incoming_state",
        "hazard_score",
    ),
    "RegimeState": (
        "symbol",
        "engine_name",
        "state_names",
        "posteriors",
        "dominant_state",
        "dominant_name",
        "horizon_seconds",
        "stability",
        "posterior_entropy_nats",
        "calibrated",
        "discriminability",
    ),
    "RiskVerdict": ("symbol", "action", "reason", "scaling_factor", "constraints"),
    "SafetyStateChange": (
        "symbol",
        "strategy_id",
        "safe",
        "reason",
        "trend_mechanism",
        "regime_gate_state",
        "consumed_features",
        "expected_half_life_seconds",
        "disclosed_cost_total_bps",
        "disclosed_margin_ratio",
    ),
    "SensorReading": (
        "symbol",
        "sensor_id",
        "sensor_version",
        "value",
        "confidence",
        "warm",
        "provenance",
        "parent_correlation_id",
    ),
    "Signal": (
        "symbol",
        "strategy_id",
        "direction",
        "strength",
        "edge_estimate_bps",
        "disclosed_cost_total_bps",
        "reversal_cost_estimate_bps",
        "disclosed_margin_ratio",
        "metadata",
        "layer",
        "horizon_seconds",
        "regime_gate_state",
        "consumed_features",
        "trend_mechanism",
        "expected_half_life_seconds",
    ),
    "SizedPositionIntent": (
        "strategy_id",
        "layer",
        "horizon_seconds",
        "target_positions",
        "factor_exposures",
        "expected_turnover_usd",
        "expected_gross_exposure_usd",
        "mechanism_breakdown",
        "disclosed_cost_total_bps_by_symbol",
        "decision_basis_hash",
        "solver_status",
    ),
    "StateTransition": ("machine_name", "from_state", "to_state", "trigger", "metadata"),
    "SymbolHalted": ("symbol", "halted", "reason", "blackout_until_ns"),
    "Trade": (
        "symbol",
        "price",
        "size",
        "exchange",
        "trade_id",
        "exchange_timestamp_ns",
        "conditions",
        "decimal_size",
        "sequence_number",
        "tape",
        "trf_id",
        "trf_timestamp_ns",
        "participant_timestamp_ns",
        "correction",
        "received_ns",
    ),
}


def _concrete_event_classes() -> dict[str, type[Event]]:
    found: dict[str, type[Event]] = {}
    for name, obj in vars(events_mod).items():
        if isinstance(obj, type) and issubclass(obj, Event) and obj is not Event:
            found[name] = obj
    return found


def test_s8_every_event_class_resolves_schema_version() -> None:
    """Closure + drift. Inventory is asserted first so a throwaway field is named
    even when ``SCHEMA_VERSION`` itself is still absent.
    """
    concrete = _concrete_event_classes()
    assert set(concrete) == set(PINNED_PAYLOAD), (
        f"event class set drifted: extra={sorted(set(concrete) - set(PINNED_PAYLOAD))!r} "
        f"missing={sorted(set(PINNED_PAYLOAD) - set(concrete))!r}"
    )

    drift: list[str] = []
    for name, cls in sorted(concrete.items()):
        actual = tuple(cls.__dataclass_fields__)
        expected = PINNED_ENVELOPE + PINNED_PAYLOAD[name]
        if actual != expected:
            extra = tuple(n for n in actual if n not in expected)
            missing = tuple(n for n in expected if n not in actual)
            drift.append(f"{name}: extra={extra!r} missing={missing!r}")
    assert not drift, "event schema drift: " + "; ".join(drift)

    assert hasattr(events_mod, "SCHEMA_VERSION"), (
        "pinned-code-per-log rule is not stated: SCHEMA_VERSION missing from feelies.core.events"
    )
    schema_version = events_mod.SCHEMA_VERSION
    assert isinstance(schema_version, int)

    envelope_field = Event.__dataclass_fields__.get("schema_version")
    assert envelope_field is not None, "Event envelope has no schema_version"
    assert envelope_field.default == schema_version

    unresolved = [
        name
        for name, cls in sorted(concrete.items())
        if "schema_version" not in cls.__dataclass_fields__
        or cls.__dataclass_fields__["schema_version"].default != schema_version
    ]
    assert not unresolved, f"event classes do not resolve SCHEMA_VERSION: {unresolved}"
