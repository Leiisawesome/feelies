"""Tests for the bounded-deferral cap (Stage-0 dual-permission, design §2.3).

Covers the Phase-2 acceptance ledger:
  - first-safe-OFF monotonic clock (flicker does not restart it);
  - ``min()`` deadline (age-cap wins when shorter, deferral wins otherwise);
  - ``session_flatten`` as the wall-clock backstop of last resort;
  - strategy-slice-scoped flatten (not symbol-net);
  - missing mandatory cap ⇒ reject (Phase-4 wiring stub);
  - deterministic replay of the emitted flatten stream.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st

from feelies.bus.event_bus import EventBus
from feelies.core.events import OrderRequest, SafetyStateChange, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.core.session_clock import rth_close_ns
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.deferral_cap import (
    DEFERRAL_REASON_HARD_AGE,
    DEFERRAL_REASON_MAX_HOLD,
    DEFERRAL_REASON_SESSION_FLATTEN,
    DeferralCapController,
    DeferralPolicy,
)

_SECOND = 1_000_000_000
_SYMBOL = "AAPL"
_SID = "sig_decoupled_v1"
_OTHER_SID = "sig_other_v1"

# A weekday mid-afternoon instant (2026-03-26 ~14:00 ET) as an epoch-ns anchor
# for the session-boundary tests.  rth_close_ns() resolves the 16:00 ET close
# for whatever ET date contains it, so the exact value only needs to sit inside
# a regular trading session.
_MID_SESSION_NS = int(Decimal("1774548000") * _SECOND)  # 2026-03-26 18:00:00 UTC


# ── Builders ─────────────────────────────────────────────────────────────


def _policy(
    *,
    strategy_id: str = _SID,
    max_hold_s: int = 60,
    hard_age_s: int = 10_000_000,
    universe: tuple[str, ...] = (_SYMBOL,),
) -> DeferralPolicy:
    return DeferralPolicy(
        strategy_id=strategy_id,
        max_hold_after_safe_off_seconds=max_hold_s,
        hard_exit_age_seconds=hard_age_s,
        universe=universe,
    )


def _make(
    *,
    store: StrategyPositionStore | None = None,
    policies: dict[str, DeferralPolicy] | None = None,
    session_flatten_enabled: bool = False,
    session_flatten_seconds_before_close: int = 0,
    seq_start: int = 10_000,
) -> tuple[DeferralCapController, StrategyPositionStore, EventBus, list[OrderRequest]]:
    bus = EventBus()
    store = store if store is not None else StrategyPositionStore()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    controller = DeferralCapController(
        bus=bus,
        sequence_generator=SequenceGenerator(start=seq_start),
        position_store=store,
        policies=policies if policies is not None else {_SID: _policy()},
        session_flatten_enabled=session_flatten_enabled,
        session_flatten_seconds_before_close=session_flatten_seconds_before_close,
    )
    controller.attach()
    return controller, store, bus, received


def _open(
    store: StrategyPositionStore, *, sid: str = _SID, qty: int = 100, at_ns: int = 0
) -> None:
    store.update(sid, _SYMBOL, qty, Decimal("100"), timestamp_ns=at_ns)


def _safety_off(ts_ns: int, *, sid: str = _SID, symbol: str = _SYMBOL) -> SafetyStateChange:
    return SafetyStateChange(
        timestamp_ns=ts_ns,
        correlation_id=f"cid:safe:{ts_ns}",
        sequence=0,
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=sid,
        safe=False,
        reason="clean_transition",
    )


def _safety_on(ts_ns: int, *, sid: str = _SID, symbol: str = _SYMBOL) -> SafetyStateChange:
    # A re-arm (safe=True) — must never re-anchor the monotonic clock.
    return SafetyStateChange(
        timestamp_ns=ts_ns,
        correlation_id=f"cid:safe:{ts_ns}",
        sequence=0,
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=sid,
        safe=True,
        reason="clean_transition",
    )


def _trade(ts_ns: int, *, symbol: str = _SYMBOL, cid: str | None = None) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=cid if cid is not None else f"cid:trade:{ts_ns}",
        sequence=0,
        source_layer="INGESTION",
        symbol=symbol,
        price=Decimal("100"),
        size=1,
        exchange_timestamp_ns=ts_ns,
    )


def _serialize(orders: list[OrderRequest]) -> str:
    return json.dumps(
        [
            {
                "timestamp_ns": o.timestamp_ns,
                "sequence": o.sequence,
                "symbol": o.symbol,
                "side": o.side.name,
                "quantity": o.quantity,
                "strategy_id": o.strategy_id,
                "reason": o.reason,
                "order_id": o.order_id,
                "source_layer": o.source_layer,
            }
            for o in orders
        ],
        sort_keys=True,
    )


# ── Reject stub (Phase-4 wiring lands the full loader guard) ─────────────


def test_missing_max_hold_rejected() -> None:
    with pytest.raises(ValueError, match="max_hold_after_safe_off_seconds"):
        DeferralPolicy(
            strategy_id=_SID,
            max_hold_after_safe_off_seconds=0,
            hard_exit_age_seconds=600,
        )


def test_missing_hard_exit_age_rejected() -> None:
    with pytest.raises(ValueError, match="hard_exit_age_seconds"):
        DeferralPolicy(
            strategy_id=_SID,
            max_hold_after_safe_off_seconds=60,
            hard_exit_age_seconds=0,
        )


# ── Bounded hold + basic actuation ───────────────────────────────────────


def test_no_exit_before_safe_off() -> None:
    # Open book, weather still fine (no SafetyStateChange) — the deferral cap is
    # silent; it only bounds a *deferred* (safe-OFF) hold.
    _, store, bus, out = _make()
    _open(store, at_ns=0)
    bus.publish(_trade(1_000 * _SECOND))
    assert out == []


def test_holds_then_exits_at_max_hold_deadline() -> None:
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=60)})
    _open(store, at_ns=0)
    bus.publish(_safety_off(10 * _SECOND))  # anchor -> deadline = 70s

    bus.publish(_trade(69 * _SECOND))
    assert out == [], "held below the deferral ceiling"

    bus.publish(_trade(70 * _SECOND))
    assert len(out) == 1
    order = out[0]
    assert order.reason == DEFERRAL_REASON_MAX_HOLD
    assert order.strategy_id == _SID
    assert order.side.name == "SELL"
    assert order.quantity == 100
    assert order.source_layer == "RISK"
    assert order.timestamp_ns == 70 * _SECOND


def test_short_position_exits_with_buy() -> None:
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=60)})
    _open(store, qty=-40, at_ns=0)
    bus.publish(_safety_off(0))
    bus.publish(_trade(60 * _SECOND))
    assert len(out) == 1
    assert out[0].side.name == "BUY"
    assert out[0].quantity == 40


def test_dedup_single_exit_per_episode() -> None:
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=60)})
    _open(store, at_ns=0)
    bus.publish(_safety_off(0))
    for i in range(4):
        bus.publish(_trade((70 + i) * _SECOND, cid=f"c{i}"))
    assert len(out) == 1, "one flatten per open episode despite repeated trades past the deadline"


# ── min() deadline ───────────────────────────────────────────────────────


def test_min_deadline_age_wins_when_shorter() -> None:
    # age = opened(0) + 100s = 100s; deferral = first_off(10s) + 200s = 210s.
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=200, hard_age_s=100)})
    _open(store, at_ns=0)
    bus.publish(_safety_off(10 * _SECOND))

    bus.publish(_trade(99 * _SECOND))
    assert out == []

    bus.publish(_trade(100 * _SECOND))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_HARD_AGE
    assert out[0].timestamp_ns == 100 * _SECOND


def test_min_deadline_deferral_wins_otherwise() -> None:
    # age = opened(0) + 500s = 500s; deferral = first_off(10s) + 60s = 70s.
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=60, hard_age_s=500)})
    _open(store, at_ns=0)
    bus.publish(_safety_off(10 * _SECOND))

    bus.publish(_trade(70 * _SECOND))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_MAX_HOLD
    assert out[0].timestamp_ns == 70 * _SECOND


# ── Monotonic first-safe-OFF clock (flicker must not restart it) ─────────


def test_flicker_does_not_restart_clock() -> None:
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=100, hard_age_s=10_000_000)})
    _open(store, at_ns=0)

    bus.publish(_safety_off(1_000 * _SECOND))  # first OFF -> anchor, deadline = 1100s
    bus.publish(_safety_on(1_020 * _SECOND))  # gate re-arm — must not re-anchor
    bus.publish(_safety_off(1_050 * _SECOND))  # flicker OFF — must not re-anchor

    # Before the first-anchored deadline: no exit (proves anchor is not earlier).
    bus.publish(_trade(1_099 * _SECOND))
    assert out == []

    # At/after 1100s but before a hypothetically re-anchored 1150s: exit fires,
    # proving the clock stayed anchored to the FIRST safe-OFF (design §2.3).
    bus.publish(_trade(1_120 * _SECOND))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_MAX_HOLD
    assert out[0].timestamp_ns == 1_120 * _SECOND


def test_reopen_reanchors_new_episode() -> None:
    # A fresh open episode after a flat gap re-anchors to its OWN first safe-OFF,
    # not the previous episode's stale anchor.
    _, store, bus, out = _make(policies={_SID: _policy(max_hold_s=60, hard_age_s=10_000_000)})
    _open(store, at_ns=0)
    bus.publish(_safety_off(0))
    bus.publish(_trade(60 * _SECOND))  # episode 1 exits
    assert len(out) == 1

    # Flatten the slice (simulate the exit fill) then reopen much later.
    store.update(_SID, _SYMBOL, -100, Decimal("100"), timestamp_ns=60 * _SECOND)
    _open(store, at_ns=1_000 * _SECOND)
    bus.publish(_safety_off(1_000 * _SECOND))  # episode 2 anchor -> deadline 1060s

    bus.publish(_trade(1_059 * _SECOND))
    assert len(out) == 1, "episode 2 not yet at its own deadline"
    bus.publish(_trade(1_060 * _SECOND))
    assert len(out) == 2
    assert out[1].timestamp_ns == 1_060 * _SECOND


@settings(max_examples=75, deadline=None)
@given(
    first_off_s=st.integers(min_value=1, max_value=10_000),
    flicker_offsets_s=st.lists(st.integers(min_value=0, max_value=1_000), max_size=6),
    max_hold_s=st.integers(min_value=1, max_value=1_000),
)
def test_flicker_monotonic_property(
    first_off_s: int,
    flicker_offsets_s: list[int],
    max_hold_s: int,
) -> None:
    store = StrategyPositionStore()
    _open(store, at_ns=0)
    _, _, bus, out = _make(
        store=store,
        policies={_SID: _policy(max_hold_s=max_hold_s, hard_age_s=10_000_000)},
    )
    first_off_ns = first_off_s * _SECOND
    bus.publish(_safety_off(first_off_ns))
    # Subsequent OFFs anywhere in the window must never push the deadline out.
    for off in sorted(flicker_offsets_s):
        bus.publish(_safety_off(first_off_ns + min(off, max_hold_s) * _SECOND))

    deadline = first_off_ns + max_hold_s * _SECOND
    bus.publish(_trade(deadline - 1))
    assert out == []
    bus.publish(_trade(deadline))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_MAX_HOLD
    assert out[0].timestamp_ns == deadline


# ── session_flatten wall-clock backstop ──────────────────────────────────


def test_session_flatten_is_wall_clock_backstop() -> None:
    # Open late; both nominal ceilings out-run the session, so the 16:00 ET
    # close is the binding cap.
    close_ns = rth_close_ns(_MID_SESSION_NS)
    open_ns = close_ns - 30 * 60 * _SECOND  # opened 30 min before close
    store = StrategyPositionStore()
    _open(store, at_ns=open_ns)
    _, _, bus, out = _make(
        store=store,
        policies={_SID: _policy(max_hold_s=86_400, hard_age_s=86_400)},
        session_flatten_enabled=True,
    )
    bus.publish(_safety_off(open_ns + 60 * _SECOND))

    bus.publish(_trade(close_ns - _SECOND))
    assert out == [], "held right up to the session boundary"

    bus.publish(_trade(close_ns))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_SESSION_FLATTEN
    assert out[0].timestamp_ns == close_ns


def test_session_flatten_honours_buffer() -> None:
    close_ns = rth_close_ns(_MID_SESSION_NS)
    open_ns = close_ns - 30 * 60 * _SECOND
    store = StrategyPositionStore()
    _open(store, at_ns=open_ns)
    _, _, bus, out = _make(
        store=store,
        policies={_SID: _policy(max_hold_s=86_400, hard_age_s=86_400)},
        session_flatten_enabled=True,
        session_flatten_seconds_before_close=120,  # unwind 2 min before close
    )
    bus.publish(_safety_off(open_ns + 60 * _SECOND))

    deadline = close_ns - 120 * _SECOND
    bus.publish(_trade(deadline - _SECOND))
    assert out == []
    bus.publish(_trade(deadline))
    assert len(out) == 1
    assert out[0].reason == DEFERRAL_REASON_SESSION_FLATTEN


def test_quote_freeze_exits_by_session_boundary() -> None:
    # No events at all between safe-OFF and the session close: the nominal
    # max_hold ceiling lapses during the freeze, but the platform polls nothing
    # (Inv-7), so the position is only unwound on the first event at/after the
    # boundary — and it IS unwound by then, never stranded (design §2.3).
    close_ns = rth_close_ns(_MID_SESSION_NS)
    open_ns = close_ns - 3 * 60 * 60 * _SECOND  # 3h before close
    store = StrategyPositionStore()
    _open(store, at_ns=open_ns)
    _, _, bus, out = _make(
        store=store,
        policies={_SID: _policy(max_hold_s=60, hard_age_s=86_400)},
        session_flatten_enabled=True,
    )
    bus.publish(_safety_off(open_ns + 60 * _SECOND))  # max_hold lapses at +120s

    # ... quote freeze: no events until the closing print ...
    bus.publish(_trade(close_ns))

    assert len(out) == 1, "the frozen book exits at the session boundary, not stranded"
    assert out[0].timestamp_ns == close_ns
    # The binding cap that lapsed during the freeze (max_hold) is the reason it
    # fires; the guarantee is that it fires by the session boundary at latest.
    assert out[0].reason == DEFERRAL_REASON_MAX_HOLD


# ── Strategy-slice scoping (not symbol-net) ──────────────────────────────


def test_flatten_scoped_to_strategy_slice() -> None:
    # Two strategies hold the same symbol; only the decoupled one deferred.
    store = StrategyPositionStore()
    store.update(_SID, _SYMBOL, 100, Decimal("100"), timestamp_ns=0)  # deferred slice
    store.update(_OTHER_SID, _SYMBOL, 50, Decimal("100"), timestamp_ns=0)  # bystander slice
    _, _, bus, out = _make(store=store, policies={_SID: _policy(max_hold_s=60)})
    bus.publish(_safety_off(0))
    bus.publish(_trade(60 * _SECOND))

    assert len(out) == 1
    order = out[0]
    assert order.strategy_id == _SID
    # Slice quantity (100), NOT the symbol-net 150 — a symbol-net backstop would
    # cross-flatten the bystander strategy (design §3.3 defect).
    assert order.quantity == 100
    # The bystander slice is untouched.
    assert store.get(_OTHER_SID, _SYMBOL).quantity == 50


def test_universe_filter_excludes_other_symbols() -> None:
    store = StrategyPositionStore()
    store.update(_SID, "MSFT", 100, Decimal("100"), timestamp_ns=0)
    _, _, bus, out = _make(
        store=store,
        policies={_SID: _policy(max_hold_s=60, universe=(_SYMBOL,))},
    )
    bus.publish(_safety_off(0, symbol="MSFT"))
    bus.publish(_trade(1_000 * _SECOND, symbol="MSFT"))
    assert out == [], "policy universe excludes MSFT"


# ── Determinism (Inv-5) ──────────────────────────────────────────────────


def test_deterministic_replay() -> None:
    def run() -> str:
        store = StrategyPositionStore()
        _open(store, at_ns=0)
        _, _, bus, out = _make(store=store, policies={_SID: _policy(max_hold_s=60)})
        bus.publish(_safety_off(10 * _SECOND))
        for i in range(5):
            bus.publish(_trade((100 + i) * _SECOND, cid=f"c{i}"))
        return _serialize(out)

    assert run() == run()


def test_attach_without_policies_is_noop() -> None:
    bus = EventBus()
    store = StrategyPositionStore()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    controller = DeferralCapController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={},
    )
    controller.attach()  # no policies -> no subscription
    _open(store, at_ns=0)
    bus.publish(_safety_off(0))
    bus.publish(_trade(10_000 * _SECOND))
    assert received == []
