"""Orchestrator-level replay parity (audit kernel-P1, gap-test).

Every other locked parity baseline in ``tests/determinism/`` drives a *leaf*
component (regime engine, sensor/scheduler/aggregator/signal engine, composition
engine, risk engine, backtest router) on a bare :class:`EventBus`.  None of them
instantiates the :class:`~feelies.kernel.orchestrator.Orchestrator`, so the
kernel's own ordering guarantees — the shared ``_seq`` interleaving across
RegimeState / PositionUpdate / StateTransition / MetricEvent, the micro-state
walk, the ``_pending_sized_intents`` drain order, and the bus-subscriber
registration order — were not coupled to any hash.  A kernel-introduced ordering
regression could pass the whole determinism suite.

This module closes that gap with **two** scenarios:

* ``_run()`` — the canonical Phase-4 synthetic fixture (``build_platform`` +
  ``run_backtest`` over :func:`tests.integration.test_phase4_e2e._synth_multi_symbol_events`).
  Its random walk never crosses a reference alpha's entry gate (see that
  module's own docstring), so the ``signal`` / ``order`` / ``position_update``
  streams are the well-known empty-input SHA-256 and only ``intent`` (a single
  flat, order-less ``SizedPositionIntent``) is non-trivial.  Kept as a
  regression baseline for the flat-book case — it still pins that the kernel
  produces *exactly* that shape on quiet data, and the M2 fan-out survives
  mixed SIGNAL+PORTFOLIO boot.
* ``_run_smoke()`` — a dedicated single-symbol scenario using the platform's
  own ``paper_smoke_v1`` smoke alpha (``alphas/_paper_smoke_v1/``, already used
  by the paper-RTH harness for exactly this "guarantee occasional entries"
  purpose — its gate is unconditionally ``True``, so it needs no regime
  calibration).  A plain random-walk quote stream is enough to cross its
  permissive ``realized_vol_30s_zscore`` threshold, so this scenario produces
  **genuinely non-empty** ``Signal``, ``OrderRequest``, and ``PositionUpdate``
  streams — the first orchestrator-level baseline to actually exercise the
  M4-M10 order-submission / ack / position-reconciliation interleaving it was
  built to protect (audit-2026-07-02 P1 #1).

``test_two_full_orchestrator_replays_are_identical`` /
``test_two_full_orchestrator_smoke_replays_are_identical`` are the portable
core (they catch any in-process nondeterminism — wall-clock / RNG /
dict-reordering — that leaks into a parity event).  The locked-baseline tests
additionally pin drift; as with every other parity hash each is bound to a
fixed (platform, libm) pair (see ``parity_manifest`` cross-libm caveat) and is
re-baselined the same way.

Naming (audit-2026-07-02 P1 #2): every locked constant here ends in ``_HASH``
so :func:`tests.determinism.test_parity_manifest.test_every_locked_hash_is_registered_or_exempt`'s
scanner actually sees it.  All eight are intentionally kept **out** of
``LOCKED_PARITY_BASELINES`` (registered instead in
``_UNREGISTERED_HASH_EXEMPTIONS``) so the manifest cross-check stays decoupled
from the regime engine's transcendental sensitivity until a canonical host
fingerprint is recorded for orchestrator-level replay.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    PositionUpdate,
    Signal,
    SizedPositionIntent,
)
from feelies.core.platform_config import PlatformConfig
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.integration.test_phase4_e2e import (
    _make_phase4_config,
    _synth_multi_symbol_events,
)


def _run() -> dict[str, tuple[str, int]]:
    config = _make_phase4_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_multi_symbol_events())
    orchestrator, _ = build_platform(config, event_log=event_log)

    signals: list[Signal] = []
    intents: list[SizedPositionIntent] = []
    orders: list[OrderRequest] = []
    updates: list[PositionUpdate] = []
    orchestrator._bus.subscribe(Signal, signals.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(SizedPositionIntent, intents.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(PositionUpdate, updates.append)  # type: ignore[arg-type]

    orchestrator.boot(config)
    orchestrator.run_backtest()

    return {
        "signal": (_hash_signals(signals), len(signals)),
        "intent": (_hash_intents(intents), len(intents)),
        "order": (_hash_orders(orders), len(orders)),
        "position_update": (_hash_updates(updates), len(updates)),
    }


def _sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _hash_signals(signals: list[Signal]) -> str:
    return _sha(
        [
            f"{s.sequence}|{s.symbol}|{s.strategy_id}|{s.layer}|{s.direction.name}|"
            f"{s.strength:.6f}|{s.edge_estimate_bps:.6f}|{s.timestamp_ns}|"
            f"{s.correlation_id}"
            for s in signals
        ]
    )


def _hash_intents(intents: list[SizedPositionIntent]) -> str:
    return _sha(
        [
            f"{i.sequence}|{i.correlation_id}|{i.timestamp_ns}|"
            f"{getattr(i, 'decision_basis_hash', '')}|"
            + ",".join(f"{sym}:{tgt}" for sym, tgt in sorted(i.target_positions.items()))
            for i in intents
        ]
    )


def _hash_orders(orders: list[OrderRequest]) -> str:
    return _sha(
        [
            f"{o.sequence}|{o.order_id}|{o.symbol}|{o.side.name}|{o.order_type.name}|"
            f"{o.quantity}|{o.strategy_id}|{o.reason}|{o.source_layer}|"
            f"{o.correlation_id}"
            for o in orders
        ]
    )


def _hash_updates(updates: list[PositionUpdate]) -> str:
    return _sha(
        [
            f"{u.sequence}|{u.symbol}|{u.quantity}|{u.avg_price}|{u.realized_pnl}|"
            f"{u.timestamp_ns}|{u.correlation_id}"
            for u in updates
        ]
    )


# ── Determinism (two in-process replays → identical) — portable ──────────


def test_two_full_orchestrator_replays_are_identical() -> None:
    assert _run() == _run()


# ── Locked baselines (host-pinned; re-baseline like any parity hash) ─────

# The canonical Phase-4 synthetic fixture runs the aggregator in passive mode, so
# the reference alphas never cross an entry threshold — the SIGNAL / OrderRequest
# / PositionUpdate streams are empty (the well-known empty-input SHA-256) and the
# PORTFOLIO barrier emits exactly one flat ``SizedPositionIntent`` that produces
# no orders.  This mirrors the empty Level-2/3 leaf baselines.  The empty hashes
# and the counts are host-independent; only the single intent hash is bound to a
# fixed (platform, libm) pair.  See ``_run_smoke()`` below for the non-empty
# companion scenario that exercises order/ack/position-reconciliation ordering.
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EXPECTED_ORCHESTRATOR_SIGNAL_HASH = _EMPTY_SHA
EXPECTED_ORCHESTRATOR_SIGNAL_COUNT = 0
EXPECTED_ORCHESTRATOR_INTENT_HASH = (
    "fa9a02d84aea823f4cf4bce6d572e87102c0021985ddb03b9c3ec67dd06cc080"
)
EXPECTED_ORCHESTRATOR_INTENT_COUNT = 1
EXPECTED_ORCHESTRATOR_ORDER_HASH = _EMPTY_SHA
EXPECTED_ORCHESTRATOR_ORDER_COUNT = 0
EXPECTED_ORCHESTRATOR_POSITION_UPDATE_HASH = _EMPTY_SHA
EXPECTED_ORCHESTRATOR_POSITION_UPDATE_COUNT = 0

EXPECTED_ORCHESTRATOR_STREAMS: dict[str, tuple[str, int]] = {
    "signal": (EXPECTED_ORCHESTRATOR_SIGNAL_HASH, EXPECTED_ORCHESTRATOR_SIGNAL_COUNT),
    "intent": (EXPECTED_ORCHESTRATOR_INTENT_HASH, EXPECTED_ORCHESTRATOR_INTENT_COUNT),
    "order": (EXPECTED_ORCHESTRATOR_ORDER_HASH, EXPECTED_ORCHESTRATOR_ORDER_COUNT),
    "position_update": (
        EXPECTED_ORCHESTRATOR_POSITION_UPDATE_HASH,
        EXPECTED_ORCHESTRATOR_POSITION_UPDATE_COUNT,
    ),
}


def test_orchestrator_streams_match_locked_baseline() -> None:
    actual = _run()
    assert actual == EXPECTED_ORCHESTRATOR_STREAMS, (
        "Orchestrator replay stream drift!\n"
        f"  Expected: {EXPECTED_ORCHESTRATOR_STREAMS}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_ORCHESTRATOR_STREAMS in the same commit "
        "and justify in the commit message (re-baseline workflow)."
    )


def test_wiring_actually_dispatches_an_intent() -> None:
    # No-false-empty guard (mirrors test_signal_replay): the empty SIGNAL/order
    # baselines above only mean "no threshold crossed", not "pipeline detached".
    # The PORTFOLIO barrier must still emit its intent, proving the full
    # orchestrator composition chain ran.
    assert _run()["intent"][1] == 1


# ── Smoke scenario: a real, non-empty Signal → Order → Ack → PositionUpdate ──
# ── walk through the full orchestrator (audit-2026-07-02 P1 #1)             ──

_SMOKE_SYMBOL = "AAPL"
_SMOKE_BASE_TS = 1_700_000_000_000_000_000
_SMOKE_QUOTE_DT_NS = 200_000_000  # 200ms cadence
_SMOKE_N_QUOTES = 600  # 120s of quotes — several horizon boundaries at 30s

# The platform's own smoke-test alpha (used by the paper-RTH harness for
# exactly this purpose): unconditional ``on_condition: "True"`` gate (no
# regime dependency, so no HMM calibration is needed) and a permissive
# |realized_vol_30s_zscore| >= 0.3 entry threshold ("guarantees occasional
# entries for pipeline smoke testing" per its own YAML docstring).
_SMOKE_ALPHA = (
    Path(__file__).resolve().parents[2]
    / "alphas"
    / "_paper_smoke_v1"
    / "paper_smoke_v1.alpha.yaml"
)

_SMOKE_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


def _smoke_quotes() -> list[NBBOQuote]:
    """Deterministic single-symbol random walk (same shape as the Phase-4
    fixture's per-symbol walk) — no deliberate volatility burst is needed;
    ``paper_smoke_v1``'s 0.3 z-score floor is permissive enough that an
    ordinary random walk crosses it within the first few horizon boundaries.
    """
    rng = random.Random(11)
    mid_cents = 18000
    events: list[NBBOQuote] = []
    ts = _SMOKE_BASE_TS
    for i in range(_SMOKE_N_QUOTES):
        mid_cents += rng.choice((-1, 0, 0, 0, 1))
        events.append(
            NBBOQuote(
                timestamp_ns=ts,
                correlation_id=f"smoke-q-{i}",
                sequence=i,
                symbol=_SMOKE_SYMBOL,
                bid=Decimal(mid_cents) / Decimal(100),
                ask=Decimal(mid_cents + 1) / Decimal(100),
                bid_size=200,
                ask_size=200,
                exchange_timestamp_ns=ts,
            )
        )
        ts += _SMOKE_QUOTE_DT_NS
    return events


def _make_smoke_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({_SMOKE_SYMBOL}),
        alpha_specs=[_SMOKE_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SMOKE_SENSOR_SPECS,
        horizons_seconds=frozenset({30}),
        session_open_ns=_SMOKE_BASE_TS,
        account_equity=1_000_000.0,
        # paper_smoke_v1's gate is unconditional, so strict trend-mechanism
        # enforcement is irrelevant here — off to match the other fixtures.
        enforce_trend_mechanism=False,
    )


def _run_smoke() -> dict[str, tuple[str, int]]:
    config = _make_smoke_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_smoke_quotes())
    orchestrator, _ = build_platform(config, event_log=event_log)

    signals: list[Signal] = []
    intents: list[SizedPositionIntent] = []
    orders: list[OrderRequest] = []
    updates: list[PositionUpdate] = []
    orchestrator._bus.subscribe(Signal, signals.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(SizedPositionIntent, intents.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
    orchestrator._bus.subscribe(PositionUpdate, updates.append)  # type: ignore[arg-type]

    orchestrator.boot(config)
    orchestrator.run_backtest()

    return {
        "signal": (_hash_signals(signals), len(signals)),
        "intent": (_hash_intents(intents), len(intents)),
        "order": (_hash_orders(orders), len(orders)),
        "position_update": (_hash_updates(updates), len(updates)),
    }


def test_two_full_orchestrator_smoke_replays_are_identical() -> None:
    assert _run_smoke() == _run_smoke()


# Locked smoke baseline.  No PORTFOLIO alpha is registered in this scenario,
# so ``intent`` legitimately stays empty (there is no cross-sectional barrier
# to fire) — the point of this scenario is the SIGNAL/order/position_update
# path, which the flat scenario above cannot exercise.
EXPECTED_ORCHESTRATOR_SMOKE_SIGNAL_HASH = (
    "5e7986c7f85061d758eea6275376f225ede75c63a8649546900c4235085b966f"
)
EXPECTED_ORCHESTRATOR_SMOKE_SIGNAL_COUNT = 2
EXPECTED_ORCHESTRATOR_SMOKE_INTENT_HASH = _EMPTY_SHA
EXPECTED_ORCHESTRATOR_SMOKE_INTENT_COUNT = 0
EXPECTED_ORCHESTRATOR_SMOKE_ORDER_HASH = (
    "a48f0e19968627ae2c98701b0e9a8e26b67d3fdb93772e8ebbde597b99f3f175"
)
EXPECTED_ORCHESTRATOR_SMOKE_ORDER_COUNT = 1
EXPECTED_ORCHESTRATOR_SMOKE_POSITION_UPDATE_HASH = (
    "d686a148bed0398d6633750d87689d4810157e3884d023ccc7a9750f3eb4a034"
)
EXPECTED_ORCHESTRATOR_SMOKE_POSITION_UPDATE_COUNT = 1

EXPECTED_ORCHESTRATOR_SMOKE_STREAMS: dict[str, tuple[str, int]] = {
    "signal": (
        EXPECTED_ORCHESTRATOR_SMOKE_SIGNAL_HASH,
        EXPECTED_ORCHESTRATOR_SMOKE_SIGNAL_COUNT,
    ),
    "intent": (
        EXPECTED_ORCHESTRATOR_SMOKE_INTENT_HASH,
        EXPECTED_ORCHESTRATOR_SMOKE_INTENT_COUNT,
    ),
    "order": (
        EXPECTED_ORCHESTRATOR_SMOKE_ORDER_HASH,
        EXPECTED_ORCHESTRATOR_SMOKE_ORDER_COUNT,
    ),
    "position_update": (
        EXPECTED_ORCHESTRATOR_SMOKE_POSITION_UPDATE_HASH,
        EXPECTED_ORCHESTRATOR_SMOKE_POSITION_UPDATE_COUNT,
    ),
}


def test_orchestrator_smoke_streams_match_locked_baseline() -> None:
    actual = _run_smoke()
    assert actual == EXPECTED_ORCHESTRATOR_SMOKE_STREAMS, (
        "Orchestrator smoke-replay stream drift!\n"
        f"  Expected: {EXPECTED_ORCHESTRATOR_SMOKE_STREAMS}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_ORCHESTRATOR_SMOKE_STREAMS in the same "
        "commit and justify in the commit message (re-baseline workflow)."
    )


def test_smoke_scenario_actually_produces_a_fill() -> None:
    """No-false-empty guard: this scenario exists specifically to exercise a
    real order/ack/position-reconciliation walk.  If a future change silently
    detached the smoke alpha (or the fixture stopped crossing its gate), this
    fails loudly instead of quietly reverting to the flat-book baseline shape.
    """
    actual = _run_smoke()
    assert actual["signal"][1] > 0, "smoke scenario emitted no Signal — gate never opened"
    assert actual["order"][1] > 0, "smoke scenario emitted no OrderRequest — order path detached"
    assert actual["position_update"][1] > 0, (
        "smoke scenario produced no PositionUpdate — fill/reconciliation path detached"
    )
