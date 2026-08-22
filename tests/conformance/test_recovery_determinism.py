"""R6 — reset-then-replay equals cold-start replay.

A class that mutates outside ``__init__`` and is reused across runs in one
process must restore run-scoped state.  Otherwise the second replay is a
function of the first, and process-per-run is the only thing containing it
(G04).
"""

from __future__ import annotations

from feelies.bootstrap import build_platform
from feelies.core.events import Event
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_null_alpha_conservation import (
    _HORIZON_SECONDS,
    _NULL_ALPHA,
    _SENSOR_SPECS,
    _UNIVERSE,
    _synth_events,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


def _config() -> PlatformConfig:
    return PlatformConfig(
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


def _fingerprint(events: list[Event]) -> tuple[tuple[str, int], ...]:
    return tuple((type(e).__name__, e.sequence) for e in events)


def _replay(*, reset_then_replay: bool) -> tuple[tuple[str, int], ...]:
    config = _config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_events())
    orchestrator, _ = build_platform(config, event_log=event_log)

    recorded: list[Event] = []

    def _record(event: Event) -> None:
        recorded.append(event)

    orchestrator._bus.subscribe_all(_record)
    orchestrator.boot(config)
    orchestrator.run_backtest()
    if reset_then_replay:
        orchestrator.reset()
        recorded.clear()
        orchestrator.boot(config)
        orchestrator.run_backtest()
    return _fingerprint(recorded)


def test_reset_then_replay_matches_cold_start() -> None:
    cold = _replay(reset_then_replay=False)
    assert cold, "cold-start replay published nothing — the comparison is vacuous"
    warm = _replay(reset_then_replay=True)
    assert warm == cold, (
        f"reset-then-replay diverged from cold-start: "
        f"cold {len(cold)} events, warm {len(warm)} events"
    )
