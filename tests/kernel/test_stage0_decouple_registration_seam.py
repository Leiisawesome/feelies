"""The Stage-0 opt-in must survive the loader → bootstrap registration seam.

Every other Stage-0 test covers one *side* of this seam and never the join:

* ``tests/alpha/test_safety_exit_policy.py`` asserts the **loader** sets
  ``LoadedSignalLayerModule.decouple_gate_close`` from the manifest block;
* ``tests/signals/test_safety_state_change.py``,
  ``tests/determinism/test_decoupled_safety_replay.py`` and
  ``tests/kernel/test_stage0_decouple_wiring.py`` all **hand-construct**
  ``RegisteredSignal(decouple_gate_close=...)`` and hand it straight to the
  engine or to the risk-author factories.

Nothing asserted that :func:`feelies.bootstrap._create_signal_layer` *carries*
the loader's flag onto the ``RegisteredSignal`` it registers.  It did not, and
because ``RegisteredSignal.decouple_gate_close`` defaults to ``False`` the whole
of Stage 0 was inert in any composed platform:

1. the engine's gate-close FLAT suppression (``horizon_engine`` reads
   ``registered.decouple_gate_close``) never fired, so a promoted alpha kept
   today's unconditional flatten;
2. ``_create_deferral_cap_controller`` filters its alpha set on the same flag,
   so it returned ``None`` — **the mandatory ``max_hold_after_safe_off`` /
   ``hard_exit_age_seconds`` ceilings never existed at runtime** (design §2.3,
   the load-bearing Inv-11 defense);
3. ``_create_exit_composer`` filters identically, so the fail-closed error-path
   EXIT routing never existed either.

These tests drive the **real** chain — ``AlphaLoader`` → ``AlphaRegistry`` →
``_create_signal_layer`` → the two author factories — so the flag cannot be
dropped at the registration call again without a failure here.  They are the
upstream counterpart to ``test_stage0_decouple_wiring``, which covers the three
seams *downstream* of the flag.
"""

from __future__ import annotations

import copy
from typing import Any

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import (
    _create_deferral_cap_controller,
    _create_exit_composer,
    _create_signal_layer,
)
from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

_SYMBOL = "AAPL"
_MAX_HOLD_S = 300
_HARD_AGE_S = 600

# A G16-compliant SIGNAL spec; the safety block is the only thing under test.
# KYLE_INFO half-life 120s ⇒ G17 max_hold ceiling = 3 × 120 = 360s.
_BASE_SPEC: dict[str, Any] = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "sig_seam_probe_v1",
    "version": "1.0.0",
    "description": "registration-seam fixture for the Stage-0 opt-in",
    "hypothesis": "Fixture only; asserts wiring, claims no edge.",
    "falsification_criteria": ["fails by construction"],
    "horizon_seconds": 120,
    "depends_on_sensors": ["kyle_lambda_60s", "micro_price"],
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
    "trend_mechanism": {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": 120,
        "l1_signature_sensors": ["kyle_lambda_60s", "micro_price"],
        "failure_signature": ["kyle_lambda_60s deviation falls below 1σ for 30s"],
    },
    "signal": "def evaluate(snapshot, regime, params):\n    return None\n",
}

_DECOUPLE_BLOCK: dict[str, Any] = {
    "mode": "decouple_caps_only",
    "max_hold_after_safe_off": _MAX_HOLD_S,
    "hard_exit_age_seconds": _HARD_AGE_S,
}


def _spec(alpha_id: str, *, decouple: bool) -> dict[str, Any]:
    out = copy.deepcopy(_BASE_SPEC)
    out["alpha_id"] = alpha_id
    if decouple:
        out["safety_exit_policy"] = copy.deepcopy(_DECOUPLE_BLOCK)
    return out


def _registry(*specs: dict[str, Any]) -> AlphaRegistry:
    """Load each spec through the real loader and register it."""
    loader = AlphaLoader()
    registry = AlphaRegistry()
    for spec in specs:
        registry.register(loader.load_from_dict(spec, source=f"<{spec['alpha_id']}>"))
    return registry


def _sensor_registry(bus: EventBus) -> SensorRegistry:
    """Real registry carrying the two sensor ids the fixture declares.

    ``_create_signal_layer`` resolves ``depends_on_sensors`` against this, so a
    stub would not exercise the same path.
    """
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(thread_safe=False),
        symbols=frozenset({_SYMBOL}),
    )
    # Versions are read off the classes so a sensor bump does not break this
    # test — the registry asserts spec/instance agreement.
    registry.register(
        SensorSpec(
            sensor_id="micro_price",
            sensor_version=MicroPriceSensor.sensor_version,
            cls=MicroPriceSensor,
        )
    )
    registry.register(
        SensorSpec(
            sensor_id="kyle_lambda_60s",
            sensor_version=KyleLambda60sSensor.sensor_version,
            cls=KyleLambda60sSensor,
            subscribes_to=(Trade,),
            stateful=True,
        )
    )
    return registry


def _signal_layer(registry: AlphaRegistry, bus: EventBus | None = None) -> Any:
    """Compose the engine exactly the way ``build_platform`` does."""
    resolved_bus = bus if bus is not None else EventBus()
    engine = _create_signal_layer(
        registry=registry,
        bus=resolved_bus,
        clock=SimulatedClock(),
        sensor_registry=_sensor_registry(resolved_bus),
        horizon_features=None,
    )
    return engine


def _authors(
    engine: Any,
    registry: AlphaRegistry,
    bus: EventBus,
    store: StrategyPositionStore,
) -> tuple[Any, Any]:
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


# ── The seam itself ──────────────────────────────────────────────────────


def test_bootstrap_carries_the_loader_flag_onto_the_registered_signal() -> None:
    """``_create_signal_layer`` must not drop ``decouple_gate_close``.

    This is the regression that made all three Stage-0 legs inert: the loader
    set the flag, the engine and both authors read it, and the registration call
    in between never passed it.
    """
    alpha_id = "sig_seam_probe_v1"
    registry = _registry(_spec(alpha_id, decouple=True))

    # Precondition: the loader really did set the flag we expect to survive.
    loaded = registry.get(alpha_id)
    assert getattr(loaded, "decouple_gate_close") is True, (
        "fixture invalid — the loader did not set decouple_gate_close, so this "
        "test would pass vacuously"
    )

    engine = _signal_layer(registry)
    assert engine is not None
    registered = [s for s in engine.signals if s.alpha_id == alpha_id]
    assert len(registered) == 1
    assert registered[0].decouple_gate_close is True, (
        "bootstrap dropped the Stage-0 opt-in at the RegisteredSignal call — the "
        "gate-close FLAT will not be suppressed and neither risk-layer author "
        "will be built, so the mandatory deferral ceilings never bind"
    )


def test_default_alpha_stays_not_decoupled_through_registration() -> None:
    """Absent block ⇒ flag stays False (default compatibility, Inv-5)."""
    alpha_id = "sig_plain_v1"
    engine = _signal_layer(_registry(_spec(alpha_id, decouple=False)))
    assert engine is not None
    assert engine.signals[0].decouple_gate_close is False


def test_mixed_book_carries_the_flag_per_alpha() -> None:
    """Only the promoted alpha is decoupled; the other keeps today's flatten."""
    registry = _registry(
        _spec("sig_seam_probe_v1", decouple=True),
        _spec("sig_plain_v1", decouple=False),
    )
    engine = _signal_layer(registry)
    assert engine is not None
    by_id = {s.alpha_id: s.decouple_gate_close for s in engine.signals}
    assert by_id == {"sig_seam_probe_v1": True, "sig_plain_v1": False}


# ── Downstream consequence: both authors actually get built ──────────────


def test_both_risk_authors_are_built_from_a_loaded_decoupled_spec() -> None:
    """End-to-end: a real spec must yield a live deferral cap *and* composer.

    Both factories select their alpha set with
    ``[s for s in engine.signals if s.decouple_gate_close]``, so a dropped flag
    makes each return ``None`` and leaves the bounded-deferral guarantee with no
    runtime representation.
    """
    alpha_id = "sig_seam_probe_v1"
    bus = EventBus()
    registry = _registry(_spec(alpha_id, decouple=True))
    engine = _signal_layer(registry, bus)
    cap, composer = _authors(engine, registry, bus, StrategyPositionStore())

    assert cap is not None, (
        "no DeferralCapController built for a decouple_caps_only alpha — the "
        "mandatory max_hold_after_safe_off / hard_exit_age_seconds ceilings "
        "would never bind at runtime (design §2.3)"
    )
    assert composer is not None, (
        "no ExitComposer built for a decouple_caps_only alpha — the fail-closed "
        "error-path EXIT routing would not exist"
    )
    assert alpha_id in cap.policies
    assert alpha_id in composer.policies


def test_declared_ceilings_reach_the_deferral_policy() -> None:
    """The frozen YAML ceilings must arrive on the runtime policy unchanged."""
    alpha_id = "sig_seam_probe_v1"
    bus = EventBus()
    registry = _registry(_spec(alpha_id, decouple=True))
    engine = _signal_layer(registry, bus)
    cap, _ = _authors(engine, registry, bus, StrategyPositionStore())
    assert cap is not None
    policy = cap.policies[alpha_id]
    assert policy.max_hold_after_safe_off_seconds == _MAX_HOLD_S
    assert policy.hard_exit_age_seconds == _HARD_AGE_S


def test_no_authors_when_nothing_is_decoupled() -> None:
    """Default book builds neither author — today's behaviour, unchanged."""
    bus = EventBus()
    registry = _registry(_spec("sig_plain_v1", decouple=False))
    engine = _signal_layer(registry, bus)
    cap, composer = _authors(engine, registry, bus, StrategyPositionStore())
    assert cap is None
    assert composer is None
