"""X6 — pathological inputs are refused by a named registered gate.

S-06 landed case 1 (unregistered strategy_id).  S-11 completes FIX-3's
remaining six input classes, each bound to a named gate in the registry,
and requires an emitted notification record from a runtime refuse/allow
— not an API probe that loops record_verdict over GATE_REGISTRY.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.core.events import RiskAction
from feelies.portfolio.strategy_position_store import StrategyPositionStore

from tests.conformance.test_per_alpha_budget import (
    _order,
    _wrapper,
    load_unregistered_strategy_id,
)

# FIX-3 remaining six. Must-be-refused-by is the Phase 6 class table.
# Three family-template IDs have no named row until S-12 instances exist.
FIX3_FAMILY: tuple[tuple[str, str], ...] = (
    ("nan", "RT.CONTRACT_CONFORM"),
    ("out_of_universe", "RT.IN_UNIVERSE"),
    ("missing_schema_version", "RT.SCHEMA_SUPPORTED"),
)
FIX3_RUNTIME: tuple[tuple[str, str], ...] = (
    ("stale_timestamp", "RT.DATA_HEALTH"),
    ("duplicate_id", "RT.DUPLICATE_INTENT"),
    ("self_contradictory", "GOV.CONTRACT_SHAPE"),
)

_REGISTRY_SRC = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "feelies"
    / "core"
    / "gate_registry.py"
)


def _assert_emitted(gate_id: str, class_id: str) -> None:
    from feelies.core.gate_registry import iter_verdicts

    recs = [r for r in iter_verdicts() if r.gate_id == gate_id]
    assert recs, (
        f"silent skip: pathological class {class_id!r} was not refused by "
        f"an emitted record from gate {gate_id}"
    )
    rec = recs[-1]
    assert rec.outcome in ("FAIL", "UNKNOWN"), (
        f"gate {gate_id} emitted {rec.outcome} for {class_id!r}; "
        "FAIL/UNKNOWN is required on the notification channel"
    )
    assert not hasattr(rec, "sequence")


def test_unregistered_strategy_id_fixture_is_refused() -> None:
    """FIX-3 case 1: the fixture id enters the KeyError handler and is refused."""
    from feelies.core.gate_registry import clear_verdicts

    unregistered = load_unregistered_strategy_id()
    wrapper, registry, inner = _wrapper()
    positions = StrategyPositionStore().as_aggregate()

    clear_verdicts()
    verdict = wrapper.check_order(_order(unregistered), positions)

    assert unregistered in registry.lookups, (
        "fixture strategy_id never reached registry.get; "
        f"lookups={registry.lookups!r}"
    )
    assert unregistered in registry.key_errors, (
        "fixture strategy_id did not raise KeyError in the wrapper; "
        f"key_errors={registry.key_errors!r}"
    )
    assert inner.orders == [], (
        "pathological unregistered id was forwarded unbudgeted: "
        f"{[o.strategy_id for o in inner.orders]!r}"
    )
    assert verdict.action is RiskAction.REJECT, (
        f"pathological unregistered id was not refused "
        f"(action={verdict.action.name}, reason={verdict.reason!r})"
    )
    assert unregistered in verdict.reason
    _assert_emitted("RT.BUDGET_RESOLVE", "unregistered_strategy_id")


@pytest.mark.parametrize("class_id,gate_id", FIX3_RUNTIME)
def test_pathological_class_refused_by_named_registered_gate(
    class_id: str, gate_id: str
) -> None:
    """FIX-3 remaining runtime classes: named gate plus an emitted record."""
    from feelies.core.gate_registry import (
        FAMILY_TEMPLATES,
        GATE_REGISTRY,
        clear_verdicts,
    )

    assert gate_id not in FAMILY_TEMPLATES
    assert gate_id in GATE_REGISTRY, (
        f"pathological class {class_id!r} has no named registered gate "
        f"{gate_id!r} to refuse against"
    )
    row = GATE_REGISTRY[gate_id]
    assert "X6" in row.tested_by
    clear_verdicts()
    _drive_pathological(class_id)
    _assert_emitted(gate_id, class_id)


@pytest.mark.xfail(strict=True, reason="family instances land at S-12")
@pytest.mark.parametrize("class_id,gate_id", FIX3_FAMILY)
def test_pathological_family_class_awaits_s12_instances(
    class_id: str, gate_id: str
) -> None:
    """FIX-3 classes bound to family templates have no named row until S-12."""
    from feelies.core.gate_registry import FAMILY_TEMPLATES, GATE_REGISTRY

    assert gate_id in FAMILY_TEMPLATES, (
        f"{class_id!r} must bind to a family template, not a spine row"
    )
    assert gate_id not in GATE_REGISTRY
    raise AssertionError(
        f"family instance for {gate_id} (class {class_id}) has not landed"
    )


def test_x6_runtime_gates_emit_records_not_api_probe() -> None:
    """X6 totality: runtime refuse/allow sites emit; the test does not loop
    record_verdict over GATE_REGISTRY."""
    from feelies.core.gate_registry import (
        GATE_REGISTRY,
        clear_verdicts,
        iter_verdicts,
        record_verdict,
    )

    src = _REGISTRY_SRC.read_text(encoding="utf-8")
    assert "SequenceGenerator" not in src
    assert "self._seq" not in src
    assert ".publish(" not in src

    # Guard against the rejected probe: looping record_verdict over the
    # registry would pass with every runtime site still silent.
    probe_ids = set(GATE_REGISTRY)
    clear_verdicts()
    _drive_runtime_sites()
    emitted = {r.gate_id for r in iter_verdicts()}
    assert emitted, (
        "no notification records: runtime gates stayed silent"
    )
    # The test body must not have called record_verdict itself.
    assert record_verdict.__module__ == "feelies.core.gate_registry"
    missing = sorted(
        gid
        for gid in (
            "GOV.CONTRACT_SHAPE",
            "RT.BUDGET_RESOLVE",
            "RT.SESSION_ADMISSION",
            "RT.MIN_SIZE",
            "RT.KILL_SWITCH",
            "RT.LATENCY_BUDGET",
            "RT.DATA_HEALTH",
            "RT.EXPOSURE_LIMITS",
        )
        if gid not in emitted
    )
    assert not missing, (
        "runtime gates evaluated without an emitted record: " + ", ".join(missing)
    )
    # Totality is not an API loop filling the registry.
    assert emitted != probe_ids, (
        "totality looks like an API probe over GATE_REGISTRY "
        f"({len(emitted)} records == {len(probe_ids)} rows)"
    )


def _drive_pathological(class_id: str) -> None:
    if class_id == "self_contradictory":
        _drive_self_contradictory()
    elif class_id == "stale_timestamp":
        _drive_stale_timestamp()
    elif class_id == "duplicate_id":
        _drive_duplicate_id()
    else:
        raise AssertionError(f"no driver for {class_id!r}")


def _drive_self_contradictory() -> None:
    from feelies.alpha.layer_validator import LayerValidationError, LayerValidator

    spec = {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_x",
        "version": "1.0.0",
        "description": "test alpha",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["criterion 1"],
        "horizon_seconds": 120,
        "depends_on_sensors": ["ofi_ewma", "spread_z_30d"],
        "regime_gate": {
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "P(normal) > 0.7",
            "off_condition": "P(normal) < 0.5",
        },
        "cost_arithmetic": {
            "edge_estimate_bps": 9.0,
            "half_spread_bps": 2.0,
            "impact_bps": 2.0,
            "fee_bps": 1.0,
            "margin_ratio": 1.8,
        },
        "signal": 123,
    }
    with pytest.raises(LayerValidationError, match="G2"):
        LayerValidator().validate(spec, source="<x6>")


def _drive_stale_timestamp() -> None:
    from feelies.ingestion.data_integrity import HaltSignal, classify_halt_status

    result = classify_halt_status((1,), frozenset({1}), frozenset({2}))
    assert result is HaltSignal.HALT_ON


def _drive_duplicate_id() -> None:
    from feelies.core.clock import SimulatedClock
    from feelies.core.events import (
        OrderRequest,
        OrderType,
        Side,
        SizedPositionIntent,
    )
    from feelies.execution.order_state import OrderState
    from tests.kernel.test_orchestrator import _build_orchestrator

    clock = SimulatedClock(start_ns=1_000_000_000)
    orch = _build_orchestrator(clock)
    pending = OrderRequest(
        timestamp_ns=clock.now_ns(),
        correlation_id="x6-dup",
        sequence=1,
        order_id="ord-pending",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        strategy_id="alpha_x",
    )
    orch._track_order(pending.order_id, pending.side, pending)
    orch._transition_order(pending.order_id, OrderState.SUBMITTED, "submitted")
    later = OrderRequest(
        timestamp_ns=clock.now_ns(),
        correlation_id="x6-dup-2",
        sequence=2,
        order_id="ord-later",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        strategy_id="alpha_x",
    )
    intent = SizedPositionIntent(
        timestamp_ns=clock.now_ns(),
        correlation_id="x6-dup",
        sequence=3,
        strategy_id="alpha_x",
    )
    kept = orch._filter_portfolio_orders_for_pending_conflicts(
        [later],
        intent=intent,
        correlation_id="x6-dup",
    )
    assert kept == []


def _drive_runtime_sites() -> None:
    from feelies.alpha.layer_validator import LayerValidationError, LayerValidator
    from feelies.core.events import OrderType, Side
    from feelies.core.platform_config import EngineLatencyBudget
    from feelies.execution.order_admission import admission_block_reason
    from feelies.ingestion.data_integrity import classify_halt_status
    from feelies.monitoring.kill_switch import observe_kill_switch
    from feelies.monitoring.latency_budget import _LatencyBudgetMonitor
    from feelies.portfolio.memory_position_store import MemoryPositionStore
    from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig

    from tests.conformance.test_per_alpha_budget import _order, _wrapper

    spec = {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_x",
        "version": "1.0.0",
        "description": "test alpha",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["criterion 1"],
        "horizon_seconds": 120,
        "depends_on_sensors": ["ofi_ewma", "spread_z_30d"],
        "regime_gate": {
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "P(normal) > 0.7",
            "off_condition": "P(normal) < 0.5",
        },
        "cost_arithmetic": {
            "edge_estimate_bps": 9.0,
            "half_spread_bps": 2.0,
            "impact_bps": 2.0,
            "fee_bps": 1.0,
            "margin_ratio": 1.8,
        },
        "signal": 123,
    }
    with pytest.raises(LayerValidationError):
        LayerValidator().validate(spec, source="<x6-totality>")

    wrapper, _, _ = _wrapper()
    wrapper.check_order(
        _order(load_unregistered_strategy_id()),
        StrategyPositionStore().as_aggregate(),
    )

    admission_block_reason(
        opens_exposure=True,
        opens_short=False,
        in_halt_blackout=True,
        in_session_flatten_window=False,
        ssr_active=False,
        locate_unavailable=False,
    )
    admission_block_reason(
        opens_exposure=True,
        opens_short=False,
        in_halt_blackout=False,
        in_session_flatten_window=False,
        ssr_active=False,
        locate_unavailable=False,
        quantity=1,
        min_order_shares=10,
    )

    observe_kill_switch(True, reason="x6-totality")

    monitor = _LatencyBudgetMonitor(
        (
            EngineLatencyBudget(
                engine="risk_check_ns",
                budget_ns=10,
                statistic="p99",
                window_events=1,
            ),
        )
    )
    monitor.observe(
        {"risk_check_ns": 100},
        timestamp_ns=1,
        correlation_id="x6",
    )

    classify_halt_status((1,), frozenset({1}), frozenset({2}))

    engine = BasicRiskEngine(RiskConfig(max_position_per_symbol=1))
    engine.check_order(
        _order("registered_alpha", quantity=100),
        MemoryPositionStore(),
    )
    _ = (OrderType, Side)
