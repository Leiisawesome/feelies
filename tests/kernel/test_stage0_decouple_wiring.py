"""Stage-0 decoupling must be wired end to end, not merely implemented.

Every Stage-0 unit test hand-constructs its risk authors, so all of them stayed
green while three integration seams were open:

1. ``DeferralCapController`` was never built by bootstrap, so a decoupled
   alpha's clean gate-close HOLD had no timed counterpart and the mandatory
   ``max_hold_after_safe_off`` / ``hard_exit_age_seconds`` ceilings never bound
   — the bounded-deferral guarantee (design §2.3, the load-bearing Inv-11
   defense) did not execute.
2. The kernel's non-vetoable forced-exit bridge routed the composer's reasons
   but not the deferral cap's, so ``MAX_HOLD_AFTER_SAFE_OFF`` and
   ``SESSION_FLATTEN`` flattens were silently dropped before reaching the
   backend.
3. The lifecycle revocation hook and ``ExitComposer.revoke_and_flatten`` were
   both implemented but never connected, so quarantining a decoupled alpha did
   not flatten its open deferred book (design §2.5 revocation symmetry).

These tests assert the *wiring*: that bootstrap's factories build and attach the
authors from real config, that both authors cover exactly the same alpha set,
that every reason each author can emit is routed by the kernel bridge, and that
a held book actually reaches the execution backend at its deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.alpha.lifecycle import AlphaLifecycleState, LifecycleRevocation
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import (
    _create_deferral_cap_controller,
    _create_exit_composer,
    _wire_decouple_revocation_hook,
)
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    OrderRequest,
    RegimeState,
    SafetyStateChange,
    Signal,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.kernel import orchestrator as _orchestrator_mod
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.deferral_cap import (
    DEFERRAL_EXIT_REASONS,
    DEFERRAL_REASON_MAX_HOLD,
    DeferralCapController,
)
from feelies.risk.exit_composer import EXIT_COMPOSER_EXIT_REASONS, ExitComposer
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import RegimeGate

from tests.kernel.test_orchestrator_exit_composer_routing import (
    _build_orchestrator,
    _composer_order,
    _seed_long,
)

_SECOND = 1_000_000_000
_SYMBOL = "AAPL"
_SID = "sig_decoupled_v1"
_OTHER_SID = "sig_plain_v1"
_MAX_HOLD_S = 60
_HARD_AGE_S = 900


# ── Fixtures: a decoupled alpha as bootstrap actually sees it ────────────


class _NullSignal:
    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: Any,
    ) -> Signal | None:
        return None


def _cost() -> CostArithmetic:
    return CostArithmetic(
        edge_estimate_bps=9.0,
        half_spread_bps=1.0,
        impact_bps=1.0,
        fee_bps=0.5,
        margin_ratio=1.8,
    )


def _gate(alpha_id: str) -> RegimeGate:
    return RegimeGate(
        alpha_id=alpha_id,
        on_condition="P(normal) > 0.7",
        off_condition="P(normal) < 0.5",
        engine_name="test_engine",
    )


def _registered(*, alpha_id: str, decouple: bool) -> RegisteredSignal:
    return RegisteredSignal(
        alpha_id=alpha_id,
        horizon_seconds=120,
        signal=_NullSignal(),
        params={},
        gate=_gate(alpha_id),
        cost_arithmetic=_cost(),
        decouple_gate_close=decouple,
    )


def _manifest(*, alpha_id: str, safety_exit_policy: dict[str, Any] | None) -> AlphaManifest:
    return AlphaManifest(
        alpha_id=alpha_id,
        version="1.0.0",
        description="test",
        hypothesis="test",
        falsification_criteria=("stub",),
        required_features=frozenset(),
        risk_budget=AlphaRiskBudget(
            max_position_per_symbol=100,
            max_gross_exposure_pct=5.0,
            max_drawdown_pct=1.0,
            capital_allocation_pct=10.0,
        ),
        safety_exit_policy=safety_exit_policy,
    )


@dataclass
class _StubModule:
    manifest: AlphaManifest


def _decouple_block(
    *,
    max_hold: int | None = _MAX_HOLD_S,
    hard_age: int | None = _HARD_AGE_S,
) -> dict[str, Any]:
    block: dict[str, Any] = {"mode": "decouple_caps_only"}
    if max_hold is not None:
        block["max_hold_after_safe_off"] = max_hold
    if hard_age is not None:
        block["hard_exit_age_seconds"] = hard_age
    return block


def _registry(**policies: dict[str, Any] | None) -> AlphaRegistry:
    """Registry stub whose ``get(alpha_id).manifest`` carries the given block."""
    modules = {
        alpha_id: _StubModule(_manifest(alpha_id=alpha_id, safety_exit_policy=block))
        for alpha_id, block in policies.items()
    }
    reg = AlphaRegistry()
    reg.get = lambda alpha_id: modules[alpha_id]  # type: ignore[method-assign,assignment]
    reg.active_alphas = lambda: list(modules.values())  # type: ignore[method-assign]
    return reg


def _engine(*registered: RegisteredSignal) -> HorizonSignalEngine:
    engine = HorizonSignalEngine(
        bus=EventBus(),
        signal_sequence_generator=SequenceGenerator(),
    )
    for reg in registered:
        engine.register(reg)
    return engine


def _build_authors(
    bus: EventBus,
    store: StrategyPositionStore,
) -> tuple[DeferralCapController | None, ExitComposer | None]:
    """Both Stage-0 authors, built exactly the way ``build_platform`` builds them."""
    engine = _engine(
        _registered(alpha_id=_SID, decouple=True),
        _registered(alpha_id=_OTHER_SID, decouple=False),
    )
    registry = _registry(
        **{_SID: _decouple_block(), _OTHER_SID: None},
    )
    cap = _create_deferral_cap_controller(
        bus=bus,
        registry=registry,
        horizon_signal_engine=engine,
        strategy_positions=store,
        fallback_universe=(_SYMBOL,),
        session_flatten_enabled=False,
        session_flatten_seconds_before_close=0,
    )
    composer = _create_exit_composer(
        bus=bus,
        horizon_signal_engine=engine,
        strategy_positions=store,
        fallback_universe=(_SYMBOL,),
    )
    return cap, composer


# ── B1: the deferral cap is actually built and attached ──────────────────


def test_deferral_cap_is_built_for_a_decoupled_alpha() -> None:
    cap, _ = _build_authors(EventBus(), StrategyPositionStore())
    assert cap is not None, (
        "bootstrap must build a DeferralCapController for a decoupled alpha — "
        "without it the clean-transition HOLD has no timed counterpart and the "
        "declared ceilings never bind (design §2.3)"
    )
    policy = cap.policies[_SID]
    assert policy.max_hold_after_safe_off_seconds == _MAX_HOLD_S
    assert policy.hard_exit_age_seconds == _HARD_AGE_S


def test_no_deferral_cap_when_nothing_is_decoupled() -> None:
    # Default deployments must not subscribe at all (Inv-5 bit-identity).
    cap = _create_deferral_cap_controller(
        bus=EventBus(),
        registry=_registry(**{_OTHER_SID: None}),
        horizon_signal_engine=_engine(_registered(alpha_id=_OTHER_SID, decouple=False)),
        strategy_positions=StrategyPositionStore(),
        fallback_universe=(_SYMBOL,),
        session_flatten_enabled=True,
        session_flatten_seconds_before_close=0,
    )
    assert cap is None


def test_cap_and_composer_cover_the_same_alphas() -> None:
    # The two authors are keyed off the same source, so they can never diverge:
    # an alpha with a composer HOLD but no cap would defer forever.
    cap, composer = _build_authors(EventBus(), StrategyPositionStore())
    assert cap is not None and composer is not None
    assert set(cap.policies) == set(composer.policies) == {_SID}
    assert _OTHER_SID not in cap.policies, "non-decoupled alpha must not get a cap policy"


def test_decoupled_alpha_missing_a_ceiling_fails_loudly() -> None:
    # The loader rejects this, so it is unreachable in practice — but a
    # controller wired without a ceiling would silently never bound the hold.
    with pytest.raises(ValueError, match="max_hold_after_safe_off"):
        _create_deferral_cap_controller(
            bus=EventBus(),
            registry=_registry(**{_SID: _decouple_block(max_hold=None)}),
            horizon_signal_engine=_engine(_registered(alpha_id=_SID, decouple=True)),
            strategy_positions=StrategyPositionStore(),
            fallback_universe=(_SYMBOL,),
            session_flatten_enabled=True,
            session_flatten_seconds_before_close=0,
        )


# ── B2: every forced-exit reason routes through the kernel bridge ────────


def test_bridge_routes_every_reason_from_every_risk_layer_exit_author() -> None:
    """Each author's writer set must be a subset of what the bridge routes.

    Regression: ``MAX_HOLD_AFTER_SAFE_OFF`` and ``SESSION_FLATTEN`` were dropped
    at ``Orchestrator._on_bus_hazard_order``'s reason filter, so the bounded
    deferral could never reach the execution backend.
    """
    for writer_set, name in (
        (HAZARD_EXIT_REASONS, "hazard controller"),
        (EXIT_COMPOSER_EXIT_REASONS, "exit composer"),
        (DEFERRAL_EXIT_REASONS, "deferral cap"),
    ):
        missing = sorted(writer_set - _orchestrator_mod._RISK_FORCED_EXIT_REASONS)
        assert not missing, f"{name} reasons not routed by the kernel bridge: {missing}"


@pytest.mark.parametrize("reason", sorted(DEFERRAL_EXIT_REASONS))
def test_each_deferral_reason_reaches_the_router(reason: str) -> None:
    bus = EventBus()
    positions = MemoryPositionStore()
    _seed_long(positions)
    _, router, _ = _build_orchestrator(bus=bus, positions=positions)

    bus.publish(_composer_order(reason=reason, order_id=f"dc-{reason}"))

    assert [o.reason for o in router.submitted] == [reason], (
        f"deferral-cap reason {reason!r} was silently dropped by Orchestrator._on_bus_hazard_order"
    )


# ── B3: revocation symmetry is connected ─────────────────────────────────


def test_revocation_hook_is_wired_to_the_composer() -> None:
    bus = EventBus()
    store = StrategyPositionStore()
    store.update(_SID, _SYMBOL, 100, Decimal("150"), timestamp_ns=0)
    _, composer = _build_authors(bus, store)
    assert composer is not None

    emitted: list[OrderRequest] = []
    bus.subscribe(OrderRequest, emitted.append)  # type: ignore[arg-type]

    registry = _registry(**{_SID: _decouple_block()})
    _wire_decouple_revocation_hook(registry, composer)
    assert registry._lifecycle_revocation_hook is not None

    # Fire the hook the way AlphaLifecycle does on a quarantine transition.
    registry._lifecycle_revocation_hook(
        LifecycleRevocation(
            alpha_id=_SID,
            from_state=AlphaLifecycleState.LIVE.name,
            to_state=AlphaLifecycleState.QUARANTINED.name,
            trigger="quarantined",
            timestamp_ns=42 * _SECOND,
            correlation_id="revoke-1",
        )
    )

    assert len(emitted) == 1, "quarantine must immediately flatten the open deferred book"
    assert emitted[0].reason == "DECOUPLING_REVOKED"
    assert emitted[0].strategy_id == _SID
    assert emitted[0].quantity == 100
    # Stamped from the transition, not a fresh clock read (Inv-5 replayability).
    assert emitted[0].timestamp_ns == 42 * _SECOND


def test_revocation_hook_not_wired_without_a_composer() -> None:
    registry = _registry(**{_OTHER_SID: None})
    _wire_decouple_revocation_hook(registry, None)
    assert registry._lifecycle_revocation_hook is None


# ── End to end: held book reaches the backend at its deadline ────────────


def test_bounded_deferral_reaches_the_execution_backend() -> None:
    """Clean gate-close HOLDs, then the cap's deadline exit is actually filled.

    This is the whole Stage-0 promise in one path: safety OFF does not flatten
    immediately, but the position *is* gone by the declared ceiling — through
    real bootstrap wiring and the real kernel bridge.
    """
    bus = EventBus()
    positions = MemoryPositionStore()
    _seed_long(positions)
    strategy_positions = StrategyPositionStore()
    strategy_positions.update(_SID, _SYMBOL, 100, Decimal("150"), timestamp_ns=0)

    _, router, _ = _build_orchestrator(
        bus=bus,
        positions=positions,
        strategy_positions=strategy_positions,
    )
    cap, composer = _build_authors(bus, strategy_positions)
    assert cap is not None and composer is not None

    # 1. Clean ON→OFF: composer HOLDs (bounded deferral), nothing submitted.
    bus.publish(_safety_off(10 * _SECOND))
    assert router.submitted == [], "clean transition must not flatten immediately"

    # 2. A trade before the ceiling: still held.
    bus.publish(_trade(69 * _SECOND))
    assert router.submitted == [], "held below the max_hold ceiling"

    # 3. First trade at/after first_safe_off + max_hold: the cap forces the exit
    #    and the kernel bridge submits it.
    bus.publish(_trade(70 * _SECOND))
    assert [o.reason for o in router.submitted] == [DEFERRAL_REASON_MAX_HOLD], (
        "the bounded-deferral exit must reach the execution backend at the "
        "declared ceiling — this is the Stage-0 guarantee"
    )
    assert router.submitted[0].strategy_id == _SID
    assert router.submitted[0].quantity == 100


def _safety_off(ts_ns: int) -> SafetyStateChange:
    return SafetyStateChange(
        timestamp_ns=ts_ns,
        correlation_id=f"safe:{_SYMBOL}:{ts_ns}",
        sequence=0,
        source_layer="SIGNAL",
        symbol=_SYMBOL,
        strategy_id=_SID,
        safe=False,
        reason="clean_transition",
    )


def _trade(ts_ns: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"trade:{_SYMBOL}:{ts_ns}",
        sequence=0,
        source_layer="INGESTION",
        symbol=_SYMBOL,
        price=Decimal("150.00"),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )
