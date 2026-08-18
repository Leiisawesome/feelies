"""A1 — alpha purity: a SIGNAL alpha cannot see the book.

``signals/`` is a forecaster.  Its inputs are exactly three —
:class:`RegimeState`, :class:`SensorReading` and
:class:`HorizonFeatureSnapshot` — and not one of them carries position,
P&L or order state.  A forecast that cannot see the book cannot quietly
become a decision, which is what keeps the layer substitutable in
isolation and what every per-alpha attribution downstream rests on.

The way that is lost is a fourth subscription: ``PositionUpdate`` or
``OrderAck`` added to :meth:`HorizonSignalEngine.attach` so an alpha can
"pre-filter" on a position it already holds.  The temptation arrives from
the opposite direction to the obvious one, and nothing else in the suite
would notice it.

Both halves observe FIX-1, the control alpha that emits nothing by
construction, so what is measured is the engine's wiring rather than a
strategy's behaviour.  The tape and sensor set are imported from C1 rather
than restated: one control alpha, one fixture.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, replace
from typing import Any

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Event,
    HorizonFeatureSnapshot,
    RegimeState,
    SensorReading,
    Signal,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_null_alpha_conservation import (
    _HORIZON_SECONDS,
    _NULL_ALPHA,
    _SENSOR_SPECS,
    _UNIVERSE,
    _synth_events,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

#: The three inputs engine 4 is allowed to have.  This set *is* the
#: contract; the assertion below is an equality, not a containment, so a
#: fourth subscription fails here whatever it subscribes to.
_PURE_INPUTS: frozenset[type[Event]] = frozenset(
    {RegimeState, SensorReading, HorizonFeatureSnapshot}
)

#: Field-name fragments that would mean book state reached the alpha.
#: A type check alone would not catch a ``position_quantity`` field grown
#: onto an otherwise pure event.
_BOOK_STATE_TOKENS: tuple[str, ...] = (
    "position",
    "quantity",
    "pnl",
    "order",
    "fill",
    "exposure",
    "realized",
    "avg_price",
    "fee",
)


class _EvaluateRecorder:
    """Pass-through wrapper recording what the alpha was handed.

    Records only; it returns the wrapped alpha's own verdict unchanged, so
    attaching it cannot alter the replay it observes.
    """

    def __init__(self, inner: Any) -> None:
        self.signal_id = inner.signal_id
        self.signal_version = inner.signal_version
        self._inner = inner
        self.calls: list[tuple[HorizonFeatureSnapshot, RegimeState | None, Mapping[str, Any]]] = []

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: Mapping[str, Any],
    ) -> Signal | None:
        self.calls.append((snapshot, regime, params))
        result: Signal | None = self._inner.evaluate(snapshot, regime, params)
        return result


def _replay_under_null_alpha() -> tuple[HorizonSignalEngine, Any, _EvaluateRecorder]:
    """Boot the platform under FIX-1, record every evaluate, run the tape."""
    config = PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({_HORIZON_SECONDS}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        enforce_trend_mechanism=False,
    )
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_events())

    orchestrator, _ = build_platform(config, event_log=event_log)
    orchestrator.boot(config)

    engine = orchestrator._horizon_signal_engine
    assert engine is not None, "no horizon signal engine — FIX-1 was never registered"
    index = [i for i, r in enumerate(engine._signals) if r.alpha_id == "null_alpha"]
    assert len(index) == 1, f"expected FIX-1 registered once, got {len(index)}"
    recorder = _EvaluateRecorder(engine._signals[index[0]].signal)
    engine._signals[index[0]] = replace(engine._signals[index[0]], signal=recorder)

    orchestrator.run_backtest()
    return engine, orchestrator._bus, recorder


def _book_state_fields(event: Event) -> list[str]:
    return [
        f.name
        for f in fields(event)
        if any(token in f.name.lower() for token in _BOOK_STATE_TOKENS)
    ]


def test_signal_engine_subscribes_only_to_pure_inputs() -> None:
    """The engine's own subscriptions, by handler identity on the live bus."""
    engine, bus, _ = _replay_under_null_alpha()

    subscribed = {
        event_type
        for event_type, handlers in bus._handlers.items()
        if any(getattr(h, "__self__", None) is engine for h in handlers)
    }

    assert subscribed == set(_PURE_INPUTS), (
        f"the signal engine subscribes to {sorted(t.__name__ for t in subscribed)}, "
        f"expected exactly {sorted(t.__name__ for t in _PURE_INPUTS)}. A subscription "
        "to position, P&L or order state turns engine 4 from a forecaster into a "
        "decider, and makes every alpha's output depend on execution history."
    )


def test_alpha_evaluate_never_receives_book_state() -> None:
    _, _, recorder = _replay_under_null_alpha()

    # Without this the loop below is vacuous: an alpha that is never
    # evaluated is trivially pure.
    assert recorder.calls, (
        "FIX-1's evaluate was never called, so no argument was observed — "
        "this replay proves nothing about what an alpha can see"
    )

    for snapshot, regime, params in recorder.calls:
        assert type(snapshot) is HorizonFeatureSnapshot, (
            f"evaluate received a {type(snapshot).__name__} as its feature argument"
        )
        assert regime is None or type(regime) is RegimeState, (
            f"evaluate received a {type(regime).__name__} as its regime argument"
        )
        leaked = _book_state_fields(snapshot) + (
            [] if regime is None else _book_state_fields(regime)
        )
        assert not leaked, (
            f"an input handed to the alpha carries book state in {leaked} — "
            "the type is pure but the payload is not"
        )
        smuggled = [
            key for key in params if any(token in key.lower() for token in _BOOK_STATE_TOKENS)
        ]
        assert not smuggled, f"alpha params carry book state in {smuggled}"
