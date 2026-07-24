"""Revocation-symmetry flatten path — ``ExitComposer.revoke_and_flatten`` (§2.5).

Design rev 5 §2.5 / §3.6: removing a decoupled alpha's Stage-0 authorization
(quarantine, de-promotion, config revert) flattens any open deferred book
**immediately**, not at the old ceiling.  These tests pin the composer half —
the strategy-slice-scoped, non-vetoable ``DECOUPLING_REVOKED`` flatten — while
``tests/alpha/test_lifecycle_revocation.py`` pins the lifecycle→composer wiring.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import OrderRequest, Side
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
    EXIT_COMPOSER_SOURCE_LAYER,
    ExitComposer,
    ExitComposerPolicy,
)

_SID = "sig_decoupled_v1"
_OTHER_SID = "sig_other_v1"


def _make(
    *,
    policies: dict[str, ExitComposerPolicy] | None = None,
    seq_start: int = 70_000,
) -> tuple[ExitComposer, StrategyPositionStore, EventBus, list[OrderRequest]]:
    bus = EventBus()
    store = StrategyPositionStore()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(start=seq_start),
        position_store=store,
        policies=policies if policies is not None else {_SID: ExitComposerPolicy(strategy_id=_SID)},
    )
    # No attach() needed — revoke_and_flatten publishes directly; the kernel's
    # OrderRequest bridge routes it regardless of the SafetyStateChange subscription.
    return composer, store, bus, received


def _open(
    store: StrategyPositionStore, *, sid: str, symbol: str, qty: int, at_ns: int = 0
) -> None:
    store.update(sid, symbol, qty, Decimal("100"), timestamp_ns=at_ns)


def test_revoke_flattens_all_open_slices_of_the_strategy() -> None:
    composer, store, _bus, received = _make()
    _open(store, sid=_SID, symbol="AAPL", qty=100)
    _open(store, sid=_SID, symbol="MSFT", qty=-50)

    emitted = composer.revoke_and_flatten(_SID, now_ns=1_000, correlation_id="revoke:q")

    assert [o.symbol for o in emitted] == ["AAPL", "MSFT"]  # lex-sorted (Inv-5)
    assert emitted == received
    by_symbol = {o.symbol: o for o in emitted}
    # Long 100 flattens with a SELL 100; short 50 flattens with a BUY 50.
    assert by_symbol["AAPL"].side is Side.SELL and by_symbol["AAPL"].quantity == 100
    assert by_symbol["MSFT"].side is Side.BUY and by_symbol["MSFT"].quantity == 50
    for order in emitted:
        assert order.reason == EXIT_COMPOSER_REASON_DECOUPLING_REVOKED
        assert order.source_layer == EXIT_COMPOSER_SOURCE_LAYER
        assert order.strategy_id == _SID
        assert order.timestamp_ns == 1_000


def test_revoke_is_strategy_slice_scoped_not_symbol_net() -> None:
    composer, store, _bus, received = _make()
    _open(store, sid=_SID, symbol="AAPL", qty=100)  # revoked slice
    _open(store, sid=_OTHER_SID, symbol="AAPL", qty=80)  # bystander slice

    emitted = composer.revoke_and_flatten(_SID, now_ns=5, correlation_id="revoke:q")

    assert len(emitted) == 1
    assert emitted[0].strategy_id == _SID
    assert emitted[0].quantity == 100
    # The other strategy's slice is untouched by the revoked strategy's flatten.
    assert store.get(_OTHER_SID, "AAPL").quantity == 80
    assert all(o.strategy_id == _SID for o in received)


def test_revoke_no_policy_is_noop() -> None:
    composer, store, _bus, received = _make(policies={_SID: ExitComposerPolicy(strategy_id=_SID)})
    _open(store, sid="unregistered", symbol="AAPL", qty=100)

    emitted = composer.revoke_and_flatten("unregistered", now_ns=5, correlation_id="x")

    assert emitted == []
    assert received == []


def test_revoke_flat_strategy_emits_nothing() -> None:
    composer, _store, _bus, received = _make()
    emitted = composer.revoke_and_flatten(_SID, now_ns=5, correlation_id="x")
    assert emitted == []
    assert received == []


def test_revoke_respects_policy_universe() -> None:
    composer, store, _bus, _received = _make(
        policies={_SID: ExitComposerPolicy(strategy_id=_SID, universe=("AAPL",))}
    )
    _open(store, sid=_SID, symbol="AAPL", qty=100)
    _open(store, sid=_SID, symbol="TSLA", qty=40)  # outside the policy universe

    emitted = composer.revoke_and_flatten(_SID, now_ns=5, correlation_id="x")

    assert [o.symbol for o in emitted] == ["AAPL"]


def test_revoke_dedup_suppresses_second_call_without_position_change() -> None:
    composer, store, _bus, _received = _make()
    _open(store, sid=_SID, symbol="AAPL", qty=100)

    first = composer.revoke_and_flatten(_SID, now_ns=5, correlation_id="x")
    second = composer.revoke_and_flatten(_SID, now_ns=6, correlation_id="y")

    assert len(first) == 1
    assert second == []  # duplicate-close guard holds until the position changes


def test_revoke_is_deterministic_across_identical_replays() -> None:
    def run() -> list[tuple[str, str, int, int]]:
        composer, store, _bus, _received = _make(seq_start=90_000)
        _open(store, sid=_SID, symbol="AAPL", qty=100)
        _open(store, sid=_SID, symbol="MSFT", qty=-50)
        orders = composer.revoke_and_flatten(_SID, now_ns=1_000, correlation_id="revoke:q")
        return [(o.order_id, o.symbol, o.sequence, o.quantity) for o in orders]

    assert run() == run()
