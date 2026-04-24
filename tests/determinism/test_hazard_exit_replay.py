"""Level-1 + Level-4 hazard-exit subset — replay parity (Phase 4.1).

Locks the deterministic fingerprint of the ``OrderRequest`` stream
emitted by :class:`feelies.risk.hazard_exit.HazardExitController` when
fed a synthetic sequence of ``RegimeHazardSpike`` and ``Trade`` events
against an open position book.

Determinism (Inv-5)
-------------------

* The controller never reads wall-clock time — both triggers fire
  from event timestamps.
* ``order_id`` is SHA-256 of
  ``(correlation_id, trigger_ts_ns, symbol, reason)`` truncated to 16
  hex chars.
* The episode-suppression set keys on ``(strategy_id, symbol, reason)``
  and is cleared on flat — duplicate spikes never re-fire while the
  position is held, replays observe the same suppression decisions.

Suppression (Inv-11) is exercised by publishing two consecutive spikes
on the same symbol at the same boundary; the second must be suppressed
and the order stream length / hash must reflect that.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    RegimeHazardSpike,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy


_STRATEGY_ID: str = "pofi_xsect_v1"
_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT", "GOOG")
_BASE_TS: int = 1_700_000_000_000_000_000
_HAZARD_THRESHOLD: float = 0.85
_MIN_AGE_SECONDS: int = 30
_HARD_EXIT_AGE_SECONDS: int = 600


def _seed_open_positions(store: MemoryPositionStore) -> None:
    """Open one long position per universe symbol at deterministic ts."""
    for i, symbol in enumerate(_UNIVERSE):
        opened_at = _BASE_TS + i * 1_000_000_000  # +1s per symbol
        store.update(
            symbol=symbol,
            quantity_delta=100,
            fill_price=Decimal("150.00"),
            timestamp_ns=opened_at,
        )


def _make_spike(*, symbol: str, score: float, ts_offset_s: int, seq: int) -> RegimeHazardSpike:
    return RegimeHazardSpike(
        timestamp_ns=_BASE_TS + ts_offset_s * 1_000_000_000,
        sequence=seq,
        correlation_id=f"hazard:{symbol}:{seq}",
        source_layer="REGIME",
        symbol=symbol,
        engine_name="hmm_v1",
        departing_state="normal",
        departing_posterior_prev=0.95,
        departing_posterior_now=0.30,
        incoming_state="vol_breakout",
        hazard_score=score,
    )


def _make_trade(*, symbol: str, ts_offset_s: int, seq: int) -> Trade:
    return Trade(
        timestamp_ns=_BASE_TS + ts_offset_s * 1_000_000_000,
        sequence=seq,
        correlation_id=f"trade:{symbol}:{seq}",
        source_layer="MARKET",
        symbol=symbol,
        price=Decimal("150.00"),
        size=10,
        exchange_timestamp_ns=_BASE_TS + ts_offset_s * 1_000_000_000,
    )


def _replay() -> tuple[str, int]:
    bus = EventBus()
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]

    store = MemoryPositionStore()
    _seed_open_positions(store)

    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={
            _STRATEGY_ID: HazardPolicy(
                strategy_id=_STRATEGY_ID,
                hazard_score_threshold=_HAZARD_THRESHOLD,
                min_age_seconds=_MIN_AGE_SECONDS,
                hard_exit_age_seconds=_HARD_EXIT_AGE_SECONDS,
                universe=_UNIVERSE,
            ),
        },
    )
    controller.attach()

    # ── Phase A: spikes ──
    # 1. Below threshold → ignored.
    bus.publish(_make_spike(symbol="AAPL", score=0.50, ts_offset_s=120, seq=1))
    # 2. Above threshold but inside min_age window for a younger
    #    position would be suppressed; AAPL was opened at offset 0,
    #    spike at offset 120 → age 120s > 30s → fires.
    bus.publish(_make_spike(symbol="AAPL", score=0.92, ts_offset_s=120, seq=2))
    # 3. Duplicate spike at same boundary → suppressed by episode set.
    bus.publish(_make_spike(symbol="AAPL", score=0.95, ts_offset_s=121, seq=3))
    # 4. Different symbol, fires.
    bus.publish(_make_spike(symbol="MSFT", score=0.90, ts_offset_s=130, seq=4))
    # 5. Symbol outside policy universe → ignored.
    bus.publish(_make_spike(symbol="TSLA", score=0.99, ts_offset_s=131, seq=5))

    # ── Phase B: hard-exit-age via Trade clock ──
    # GOOG was opened at offset +2s; trade at offset 700s → age ~698s
    # > 600s hard-exit cap → fires HARD_EXIT_AGE.
    bus.publish(_make_trade(symbol="GOOG", ts_offset_s=700, seq=6))
    # Duplicate trade → suppressed (already emitted in this episode).
    bus.publish(_make_trade(symbol="GOOG", ts_offset_s=701, seq=7))

    return _hash_order_stream(captured), len(captured)


def _hash_order_stream(orders: list[OrderRequest]) -> str:
    lines: list[str] = []
    for o in orders:
        lines.append(
            f"{o.sequence}|{o.timestamp_ns}|{o.order_id}|{o.symbol}|"
            f"{o.side.name}|{o.order_type.name}|{o.quantity}|"
            f"{o.strategy_id}|{o.reason}|{o.correlation_id}|"
            f"src={o.source_layer}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Determinism (replay twice → same hash) ──────────────────────────────


def test_two_replays_produce_identical_hazard_exit_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b, (
        f"hazard-exit order count drift across replays: "
        f"{count_a} vs {count_b}"
    )
    assert hash_a == hash_b, (
        "Hazard-exit OrderRequest hash drift across identical "
        f"replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_expected_order_count_and_reasons() -> None:
    """Sanity guard: AAPL+MSFT (HAZARD_SPIKE) + GOOG (HARD_EXIT_AGE)."""
    bus = EventBus()
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]

    store = MemoryPositionStore()
    _seed_open_positions(store)
    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={
            _STRATEGY_ID: HazardPolicy(
                strategy_id=_STRATEGY_ID,
                hazard_score_threshold=_HAZARD_THRESHOLD,
                min_age_seconds=_MIN_AGE_SECONDS,
                hard_exit_age_seconds=_HARD_EXIT_AGE_SECONDS,
                universe=_UNIVERSE,
            ),
        },
    )
    controller.attach()

    bus.publish(_make_spike(symbol="AAPL", score=0.92, ts_offset_s=120, seq=1))
    bus.publish(_make_spike(symbol="AAPL", score=0.95, ts_offset_s=121, seq=2))
    bus.publish(_make_spike(symbol="MSFT", score=0.90, ts_offset_s=130, seq=3))
    bus.publish(_make_trade(symbol="GOOG", ts_offset_s=700, seq=4))

    assert [(o.symbol, o.reason) for o in captured] == [
        ("AAPL", "HAZARD_SPIKE"),
        ("MSFT", "HAZARD_SPIKE"),
        ("GOOG", "HARD_EXIT_AGE"),
    ]
