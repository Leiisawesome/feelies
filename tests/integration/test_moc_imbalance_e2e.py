"""Wiring e2e for pofi_moc_imbalance_v1 (SIGNAL layer, calendar-injected).

Boots ``pofi_moc_imbalance_v1`` (SIGNAL) through ``build_platform`` over a
360-second deterministic 3-symbol synthetic stream anchored at
SESSION_OPEN_NS (2026-01-15 09:30 ET).

What this test guarantees
--------------------------

* ``pofi_moc_imbalance_v1`` registers without ``AlphaLoadError``,
  ``LayerValidationError``, or wiring failures.
* ``ScheduledFlowWindowSensor`` is constructed successfully — which
  proves bootstrap correctly loaded the ``EventCalendar`` from
  ``event_calendar_path`` and injected it as ``calendar=`` into the
  sensor spec before handing it to ``SensorRegistry``.
* ``HorizonSignalEngine`` is wired (SIGNAL layer present).
* A full backtest reaches ``MacroState.READY`` without exception.
* Zero ``Signal`` events are emitted during the 09:30–09:36 ET
  synthetic stream: the MOC_IMBALANCE window in
  ``2026-01-15.yaml`` opens at 15:50 ET, so the regime gate condition
  ``scheduled_flow_window_active == 1.0`` is never satisfied during the
  run.  This asserts the alpha's activation semantics — it must only
  trade inside the declared window.
* Two replays of the exact same fixture produce a byte-identical
  ``Signal`` stream (Inv-5 determinism), even when that stream is empty.

Calendar injection path
-----------------------

``PlatformConfig`` stores ``event_calendar_path`` as a ``Path``.
``bootstrap._create_sensor_layer`` loads it at boot time via
``load_event_calendar()`` and splices the resulting ``EventCalendar``
object into the ``ScheduledFlowWindowSensor`` spec's ``params`` using
``dataclasses.replace`` before passing the spec to ``SensorRegistry``.
``SensorRegistry.register`` then calls ``cls(**params)`` — so a
missing or wrong-typed calendar would raise at boot, not at first event.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Signal, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor
from feelies.sensors.spec import SensorSpec
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]

_MOC_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_moc_imbalance_v1"
    / "pofi_moc_imbalance_v1.alpha.yaml"
)
_CALENDAR_PATH = (
    _REPO_ROOT / "storage" / "reference" / "event_calendar"
    / "2026-01-15.yaml"
)

# 3-symbol universe — SIGNAL-only alphas have no portfolio universe
# constraint, so a small set keeps the test fast.
_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")

# 360 seconds at 10 Hz per symbol — long enough to cross the 120-second
# horizon boundary several times.  The MOC window (15:50 ET) is never
# reached, so the regime gate stays OFF throughout.
_QUOTES_PER_SYMBOL: int = 3_600


# ScheduledFlowWindowSensor requires a live EventCalendar object at
# construction time — that cannot be expressed as a plain YAML param.
# The ``params={}`` here is intentional: bootstrap detects the cls and
# injects ``calendar=<EventCalendar>`` from ``event_calendar_path``
# before passing the spec to SensorRegistry.
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    # calendar param intentionally omitted — bootstrap injects it.
    SensorSpec(
        sensor_id="scheduled_flow_window",
        sensor_version="1.0.0",
        cls=ScheduledFlowWindowSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


def _synth_events(seed: int = 42) -> list[Any]:
    """Deterministic 360-second 3-symbol NBBOQuote/Trade stream."""
    quote_cadence_ns: int = 100_000_000  # 10 Hz
    starting_prices_cents: dict[str, int] = {
        "AAPL": 18000, "MSFT": 37000, "NVDA": 45000,
    }

    all_events: list[tuple[int, str, Any]] = []
    for sym_idx, symbol in enumerate(_UNIVERSE):
        rng = random.Random(seed * 100 + sym_idx)
        last_mid = starting_prices_cents[symbol]
        for i in range(_QUOTES_PER_SYMBOL):
            ts_ns = SESSION_OPEN_NS + i * quote_cadence_ns
            delta = rng.choice((-1, 0, 0, 0, 1))
            last_mid = max(1, last_mid + delta)
            bid_cents = last_mid
            ask_cents = last_mid + 1
            quote = NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=sym_idx * _QUOTES_PER_SYMBOL + i,
                correlation_id=f"synth-q-{symbol}-{i}",
                source_layer="INGESTION",
                symbol=symbol,
                bid=Decimal(bid_cents) / Decimal(100),
                ask=Decimal(ask_cents) / Decimal(100),
                bid_size=rng.choice((100, 200, 300)),
                ask_size=rng.choice((100, 200, 300)),
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11,
                ask_exchange=11,
                tape=3,
            )
            all_events.append((ts_ns, symbol, quote))
            if i % 7 == 0 and i > 0:
                side_buy = rng.random() < 0.5
                price_cents = last_mid + (1 if side_buy else 0)
                trade = Trade(
                    timestamp_ns=ts_ns + 1,
                    sequence=sym_idx * _QUOTES_PER_SYMBOL * 2 + i,
                    correlation_id=f"synth-t-{symbol}-{i}",
                    source_layer="INGESTION",
                    symbol=symbol,
                    price=Decimal(price_cents) / Decimal(100),
                    size=rng.choice((50, 100, 150)),
                    exchange=11,
                    trade_id=f"synth-{symbol}-{i:08d}",
                    exchange_timestamp_ns=ts_ns + 1,
                    tape=3,
                )
                all_events.append((ts_ns + 1, symbol, trade))

    all_events.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in all_events]


def _make_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_MOC_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        event_calendar_path=_CALENDAR_PATH,
        enforce_trend_mechanism=True,
    )


def _build() -> tuple[Orchestrator, list[Signal]]:
    config = _make_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_events())

    orchestrator, _ = build_platform(config, event_log=event_log)

    captured_signals: list[Signal] = []
    orchestrator._bus.subscribe(Signal, captured_signals.append)

    orchestrator.boot(config)
    orchestrator.run_backtest()
    return orchestrator, captured_signals


def _hash_signals(signals: list[Signal]) -> str:
    lines: list[str] = []
    for sig in signals:
        lines.append(
            f"{sig.sequence}|{sig.timestamp_ns}|{sig.strategy_id}|"
            f"{sig.symbol}|{sig.direction}|{sig.horizon_seconds}|"
            f"{sig.edge_estimate_bps:.4f}|{sig.regime_gate_state}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Wiring ──────────────────────────────────────────────────────────────


def test_moc_imbalance_e2e_alpha_registers() -> None:
    """``pofi_moc_imbalance_v1`` must register without error."""
    orchestrator, _s = _build()
    registry = orchestrator._alpha_registry
    assert registry is not None
    assert "pofi_moc_imbalance_v1" in registry.alpha_ids()


def test_moc_imbalance_e2e_calendar_injection_succeeded() -> None:
    """``ScheduledFlowWindowSensor`` must appear in the sensor registry.

    A missing ``event_calendar_path`` or a failed ``load_event_calendar``
    call would have raised ``ConfigurationError`` at boot time.  Reaching
    this assertion means the injection path in ``_create_sensor_layer``
    completed successfully.
    """
    orchestrator, _s = _build()
    registry = orchestrator._sensor_registry
    assert registry is not None, "SensorRegistry must be wired when sensor_specs is non-empty"
    sensor_ids = {spec.sensor_id for spec in registry.specs}
    assert "scheduled_flow_window" in sensor_ids, (
        "ScheduledFlowWindowSensor was not registered; bootstrap may have "
        "failed to inject the EventCalendar into its SensorSpec params"
    )


def test_moc_imbalance_e2e_signal_engine_is_wired() -> None:
    """``HorizonSignalEngine`` must be constructed for a SIGNAL-layer alpha."""
    orchestrator, _s = _build()
    assert isinstance(orchestrator._horizon_signal_engine, HorizonSignalEngine)


def test_moc_imbalance_e2e_run_completes_and_reaches_ready() -> None:
    """Full backtest must reach MacroState.READY without exception."""
    orchestrator, _s = _build()
    assert orchestrator.macro_state == MacroState.READY


def test_moc_imbalance_e2e_regime_gate_inactive_outside_moc_window() -> None:
    """Zero signals during the 09:30–09:36 ET opening range.

    The MOC_IMBALANCE window in ``2026-01-15.yaml`` opens at 15:50 ET.
    The synthetic stream ends at 09:36 ET (~360 s after open), so
    ``scheduled_flow_window_active`` is 0.0 for every event.  The
    regime gate condition ``scheduled_flow_window_active == 1.0`` is
    never satisfied, and the signal engine must emit zero Signals.

    This directly tests that the alpha's activation semantics are
    correctly gated on the declared scheduled-flow window — the alpha
    must not fire during random opening-range price moves.
    """
    _orch, signals = _build()
    moc_signals = [s for s in signals if s.strategy_id == "pofi_moc_imbalance_v1"]
    assert len(moc_signals) == 0, (
        f"Expected zero pofi_moc_imbalance_v1 signals during 09:30–09:36 ET "
        f"(MOC window opens at 15:50 ET), but got {len(moc_signals)}.  "
        f"Check that regime_gate.on_condition correctly gates on "
        f"scheduled_flow_window_active == 1.0."
    )


def test_moc_imbalance_e2e_signal_stream_is_deterministic() -> None:
    """Two replays must produce byte-identical signal streams (Inv-5).

    Both replays are expected to produce zero signals (regime gate OFF
    throughout); the hash comparison is the canonical Inv-5 check and
    will remain valid when the test is extended to a full-day stream
    that crosses the 15:50 ET MOC window.
    """
    _orch_a, signals_a = _build()
    _orch_b, signals_b = _build()

    assert len(signals_a) == len(signals_b), (
        f"Signal count drifted across replays: "
        f"{len(signals_a)} vs {len(signals_b)}"
    )
    assert _hash_signals(signals_a) == _hash_signals(signals_b), (
        "pofi_moc_imbalance_v1 signal hash drift across identical replays "
        "(Inv-5 violation)"
    )
