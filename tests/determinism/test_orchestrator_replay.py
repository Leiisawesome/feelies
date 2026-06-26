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

This module closes that gap: it runs the **full platform** (``build_platform`` +
``run_backtest`` with a ``SimulatedClock``) over the canonical Phase-4 synthetic
event log and hashes the orchestrator-produced ``Signal`` / ``SizedPositionIntent``
/ ``OrderRequest`` / ``PositionUpdate`` streams (``sequence`` included, so the
kernel sequence allocation is part of the lock).

``test_two_full_orchestrator_replays_are_identical`` is the portable core (it
catches any in-process nondeterminism — wall-clock / RNG / dict-reordering — that
leaks into a parity event).  The locked-baseline test additionally pins drift; as
with every other parity hash it is bound to a fixed (platform, libm) pair (see
``parity_manifest`` cross-libm caveat) and is re-baselined the same way.  It is
intentionally **not** registered in ``LOCKED_PARITY_BASELINES`` so the manifest
cross-check stays decoupled from the regime engine's transcendental sensitivity
until a canonical host fingerprint is recorded for it.
"""

from __future__ import annotations

import hashlib

from feelies.bootstrap import build_platform
from feelies.core.events import (
    OrderRequest,
    PositionUpdate,
    Signal,
    SizedPositionIntent,
)
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
            + ",".join(
                f"{sym}:{tgt}"
                for sym, tgt in sorted(i.target_positions.items())
            )
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
# fixed (platform, libm) pair.  FOLLOW-UP: a threshold-crossing fixture would lock
# a non-empty order/fill stream and exercise the M5–M10 ``_seq`` interleaving more
# richly — the two-replays test above already guards that path for determinism.
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EXPECTED_ORCHESTRATOR_STREAMS: dict[str, tuple[str, int]] = {
    "signal": (_EMPTY_SHA, 0),
    "intent": ("fa9a02d84aea823f4cf4bce6d572e87102c0021985ddb03b9c3ec67dd06cc080", 1),
    "order": (_EMPTY_SHA, 0),
    "position_update": (_EMPTY_SHA, 0),
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
