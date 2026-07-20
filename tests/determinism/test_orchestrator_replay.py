"""Full-platform replay parity for orchestrator event ordering.

The hashes cover orchestrator-produced signals, intents, orders, and position
updates, including sequence allocation. These host-pinned baselines remain
outside the central manifest because regime math may vary across libm versions.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

from feelies.bootstrap import build_platform
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    PositionUpdate,
    Signal,
    SizedPositionIntent,
)
from feelies.core.platform_config import PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
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

# Passive mode produces one flat intent and no signals, orders, or fills.
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
    # An empty order stream must not hide a detached composition pipeline.
    assert _run()["intent"][1] == 1


# ── Threshold-crossing variant ───────────────────────────────────────────
#
# A seeded position and adverse quote walk exercise the non-empty stop-exit
# signal, order, and fill path without depending on alpha thresholds.

_STOP_EXIT_SYMBOL = "AAPL"
_STOP_EXIT_ENTRY_PRICE = Decimal("100.00")
_STOP_EXIT_ENTRY_QTY = 100


def _synth_stop_exit_events() -> list[NBBOQuote]:
    """A minimal, single-symbol quote walk that breaches a seeded stop-loss."""
    quote_cadence_ns = 100_000_000
    # Steps down through the armed $0.50/share stop over a few ticks so the
    # router has more than one chance to reconcile the MARKET order's fill.
    mids_cents = (9990, 9970, 9940, 9900, 9850)
    quotes: list[NBBOQuote] = []
    for i, mid_cents in enumerate(mids_cents):
        ts_ns = SESSION_OPEN_NS + i * quote_cadence_ns
        quotes.append(
            NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=i,
                correlation_id=f"stop-exit-q-{i}",
                source_layer="INGESTION",
                symbol=_STOP_EXIT_SYMBOL,
                bid=Decimal(mid_cents) / Decimal(100),
                ask=Decimal(mid_cents + 1) / Decimal(100),
                bid_size=200,
                ask_size=200,
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11,
                ask_exchange=11,
                tape=3,
            )
        )
    return quotes


def _make_stop_exit_config() -> PlatformConfig:
    """Return the one-symbol base configuration with a stop armed."""
    return replace(
        _make_phase4_config(),
        symbols=frozenset({_STOP_EXIT_SYMBOL}),
        stop_loss_per_share=0.50,
    )


def _run_stop_exit() -> dict[str, tuple[str, int]]:
    config = _make_stop_exit_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_stop_exit_events())
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
    # Seed exposure so the quote walk crosses the stop deterministically.
    orchestrator._positions.update(
        _STOP_EXIT_SYMBOL,
        _STOP_EXIT_ENTRY_QTY,
        _STOP_EXIT_ENTRY_PRICE,
    )
    orchestrator.run_backtest()

    return {
        "signal": (_hash_signals(signals), len(signals)),
        "intent": (_hash_intents(intents), len(intents)),
        "order": (_hash_orders(orders), len(orders)),
        "position_update": (_hash_updates(updates), len(updates)),
    }


def test_two_full_orchestrator_stop_exit_replays_are_identical() -> None:
    assert _run_stop_exit() == _run_stop_exit()


def test_stop_exit_replay_produces_a_non_empty_order_and_fill_stream() -> None:
    # Guard against accidentally reducing this fixture to an empty replay.
    result = _run_stop_exit()
    assert result["signal"][1] >= 1
    assert result["order"][1] >= 1
    assert result["position_update"][1] >= 1


def test_stop_exit_order_carries_stop_exit_reason() -> None:
    # Pin the field directly so failures explain more than a changed hash.
    result = _run_stop_exit_orders()
    assert result, "expected at least one stop-exit OrderRequest"
    assert result[0].reason == "STOP_EXIT"


def _run_stop_exit_orders() -> list[OrderRequest]:
    config = _make_stop_exit_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_stop_exit_events())
    orchestrator, _ = build_platform(config, event_log=event_log)
    orders: list[OrderRequest] = []
    orchestrator._bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
    orchestrator.boot(config)
    orchestrator._positions.update(
        _STOP_EXIT_SYMBOL,
        _STOP_EXIT_ENTRY_QTY,
        _STOP_EXIT_ENTRY_PRICE,
    )
    orchestrator.run_backtest()
    return orders


# Host-pinned baseline (re-baseline like any parity hash — see the module
# docstring's re-baseline workflow note). Unlike EXPECTED_ORCHESTRATOR_STREAMS,
# every stream here is non-empty: "signal" and "order" pin the synthetic
# __stop_exit__ Signal and its MARKET OrderRequest (reason="STOP_EXIT"),
# "position_update" pins the resulting fill, and "intent" pins the same
# single flat SizedPositionIntent as the baseline above (the UNIVERSE-scope
# HorizonTick fires trivially on the first quote of any session, at
# boundary_index 0, for every registered horizon simultaneously).
EXPECTED_STOP_EXIT_STREAMS: dict[str, tuple[str, int]] = {
    "signal": ("02e33e3049b03c503e8ea9256374635406f71a117b6b0800e9f7787bd5967012", 1),
    "intent": ("fa9a02d84aea823f4cf4bce6d572e87102c0021985ddb03b9c3ec67dd06cc080", 1),
    "order": ("7f39fea08b3026fcfae96f93b30ad54aa8dc3a7a843aeea119a3328538a5a724", 1),
    "position_update": ("2c5b505a3c50083f72b3d6d67c30b68f9a710a7fd20680e87034f5b9b0db6e16", 1),
}


def test_stop_exit_streams_match_locked_baseline() -> None:
    actual = _run_stop_exit()
    assert actual == EXPECTED_STOP_EXIT_STREAMS, (
        "Stop-exit orchestrator replay stream drift!\n"
        f"  Expected: {EXPECTED_STOP_EXIT_STREAMS}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_STOP_EXIT_STREAMS in the same commit "
        "and justify in the commit message (re-baseline workflow)."
    )
