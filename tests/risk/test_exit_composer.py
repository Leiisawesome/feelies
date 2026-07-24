"""Tests for the risk-layer exit composer (Stage-0 dual-permission, design §2.4).

Covers the Phase-3 acceptance ledger:
  - the full §2.4 open-book actuation table as a truth-table test (Stage-0
    columns explicit; Stage-1 rows covered for completeness / readiness);
  - decoupled error paths (missing binding / gate error / arithmetic) with an
    open book ⇒ EXIT via the composer — never silent (no fail-open);
  - the clean ON→OFF transition ⇒ HOLD (bounded deferral; the cap owns the
    timed exit);
  - strategy-slice-scoped flatten (not symbol-net) under a shared symbol;
  - per-episode dedup and deterministic replay (Inv-5).

Non-vetoable routing and synchronous same-dispatch liveness are exercised at the
orchestrator boundary in ``tests/kernel/test_orchestrator_exit_composer_routing``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.events import OrderRequest, SafetyReason, SafetyStateChange
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    EXIT_COMPOSER_SOURCE_LAYER,
    BookState,
    ExitComposer,
    ExitComposerPolicy,
    ExitDecision,
    SafetyPermission,
    StoryPermission,
    compose_exit,
)

_SECOND = 1_000_000_000
_SYMBOL = "AAPL"
_SID = "sig_decoupled_v1"
_OTHER_SID = "sig_other_v1"

_ERROR_REASONS: tuple[SafetyReason, ...] = (
    "missing_binding",
    "gate_error",
    "arithmetic_error",
)


# ── compose_exit: §2.4 truth table (pure) ────────────────────────────────


@pytest.mark.parametrize("book", [BookState.LONG, BookState.SHORT])
@pytest.mark.parametrize("p_safe", [SafetyPermission.ON, SafetyPermission.OFF])
@pytest.mark.parametrize(
    "p_story", [StoryPermission.ON, StoryPermission.OFF, StoryPermission.UNKNOWN]
)
def test_caps_hit_always_exits(
    book: BookState, p_safe: SafetyPermission, p_story: StoryPermission
) -> None:
    # caps_hit dominates the whole table (§2.4 / §2.6 precedence law).
    assert (
        compose_exit(
            book=book,
            p_safe=p_safe,
            p_story=p_story,
            caps_hit=True,
            story_configured=False,
            safe_off_fail_closed=False,
        )
        is ExitDecision.EXIT
    )


@pytest.mark.parametrize("p_safe", [SafetyPermission.ON, SafetyPermission.OFF])
@pytest.mark.parametrize(
    "p_story", [StoryPermission.ON, StoryPermission.OFF, StoryPermission.UNKNOWN]
)
@pytest.mark.parametrize("caps_hit", [True, False])
@pytest.mark.parametrize("story_configured", [True, False])
@pytest.mark.parametrize("safe_off_fail_closed", [True, False])
def test_flat_book_never_actuates(
    p_safe: SafetyPermission,
    p_story: StoryPermission,
    caps_hit: bool,
    story_configured: bool,
    safe_off_fail_closed: bool,
) -> None:
    # A flat slice is never flattened by the composer (NO_ENTRY / ENTER_ELIGIBLE
    # are the signal path's concern) — always HOLD, regardless of inputs.
    assert (
        compose_exit(
            book=BookState.FLAT,
            p_safe=p_safe,
            p_story=p_story,
            caps_hit=caps_hit,
            story_configured=story_configured,
            safe_off_fail_closed=safe_off_fail_closed,
        )
        is ExitDecision.HOLD
    )


@pytest.mark.parametrize("book", [BookState.LONG, BookState.SHORT])
@pytest.mark.parametrize(
    ("p_safe", "p_story", "expected"),
    [
        # Weather fine (safe ON): only a live story-OFF forces an early exit.
        (SafetyPermission.ON, StoryPermission.ON, ExitDecision.HOLD),
        (SafetyPermission.ON, StoryPermission.OFF, ExitDecision.EXIT),  # Stage-1 net-new
        (SafetyPermission.ON, StoryPermission.UNKNOWN, ExitDecision.HOLD),  # today's behavior
        # Weather OFF (clean): entries blocked; decide the open book.
        (SafetyPermission.OFF, StoryPermission.ON, ExitDecision.HOLD),  # Stage-1 mercy
        (SafetyPermission.OFF, StoryPermission.OFF, ExitDecision.EXIT),
    ],
)
def test_open_book_table_non_ambiguous_rows(
    book: BookState,
    p_safe: SafetyPermission,
    p_story: StoryPermission,
    expected: ExitDecision,
) -> None:
    # The rows that do not depend on the Stage-0/Stage-1 mode (¬caps, clean OFF).
    assert (
        compose_exit(
            book=book,
            p_safe=p_safe,
            p_story=p_story,
            caps_hit=False,
            story_configured=False,
            safe_off_fail_closed=False,
        )
        is expected
    )


def test_off_unknown_is_stage0_hold() -> None:
    # Stage 0 (no story map): OFF ∧ Unknown ∧ ¬caps ⇒ HOLD (bounded deferral).
    assert (
        compose_exit(
            book=BookState.LONG,
            p_safe=SafetyPermission.OFF,
            p_story=StoryPermission.UNKNOWN,
            caps_hit=False,
            story_configured=False,
            safe_off_fail_closed=False,
        )
        is ExitDecision.HOLD
    )


def test_off_unknown_is_stage1_exit_when_story_configured() -> None:
    # Stage 1 (story map configured): OFF ∧ Unknown reads as a cold/errored map
    # ⇒ EXIT (fail-closed; no mercy under uncertainty).
    assert (
        compose_exit(
            book=BookState.LONG,
            p_safe=SafetyPermission.OFF,
            p_story=StoryPermission.UNKNOWN,
            caps_hit=False,
            story_configured=True,
            safe_off_fail_closed=False,
        )
        is ExitDecision.EXIT
    )


@pytest.mark.parametrize("story_configured", [True, False])
def test_fail_closed_safe_off_exits_regardless_of_stage(story_configured: bool) -> None:
    # A gate-error safe-OFF is fail-closed: it EXITs even under the Stage-0
    # OFF ∧ Unknown HOLD reading (an errored gate is not an intentional absence).
    assert (
        compose_exit(
            book=BookState.LONG,
            p_safe=SafetyPermission.OFF,
            p_story=StoryPermission.UNKNOWN,
            caps_hit=False,
            story_configured=story_configured,
            safe_off_fail_closed=True,
        )
        is ExitDecision.EXIT
    )


# ── ExitComposer controller (bus-driven) ─────────────────────────────────


def _policy(
    *,
    strategy_id: str = _SID,
    universe: tuple[str, ...] = (_SYMBOL,),
    story_configured: bool = False,
) -> ExitComposerPolicy:
    return ExitComposerPolicy(
        strategy_id=strategy_id,
        universe=universe,
        story_configured=story_configured,
    )


def _make(
    *,
    store: StrategyPositionStore | None = None,
    policies: dict[str, ExitComposerPolicy] | None = None,
    seq_start: int = 20_000,
) -> tuple[ExitComposer, StrategyPositionStore, EventBus, list[OrderRequest]]:
    bus = EventBus()
    store = store if store is not None else StrategyPositionStore()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(start=seq_start),
        position_store=store,
        policies=policies if policies is not None else {_SID: _policy()},
    )
    composer.attach()
    return composer, store, bus, received


def _open(
    store: StrategyPositionStore, *, sid: str = _SID, qty: int = 100, at_ns: int = 0
) -> None:
    store.update(sid, _SYMBOL, qty, Decimal("100"), timestamp_ns=at_ns)


def _safety(
    ts_ns: int,
    *,
    safe: bool,
    reason: SafetyReason,
    sid: str = _SID,
    symbol: str = _SYMBOL,
) -> SafetyStateChange:
    return SafetyStateChange(
        timestamp_ns=ts_ns,
        correlation_id=f"cid:safe:{ts_ns}",
        sequence=0,
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=sid,
        safe=safe,
        reason=reason,
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


@pytest.mark.parametrize("reason", _ERROR_REASONS)
def test_error_path_open_book_exits_via_composer(reason: SafetyReason) -> None:
    # Fail-closed error path with an open decoupled book ⇒ EXIT (never silent).
    _, store, bus, out = _make()
    _open(store, qty=100)
    bus.publish(_safety(3 * _SECOND, safe=False, reason=reason))

    assert len(out) == 1, f"error path {reason!r} must flatten, not strand"
    order = out[0]
    assert order.reason == EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED
    assert order.source_layer == EXIT_COMPOSER_SOURCE_LAYER
    assert order.side.name == "SELL"
    assert order.quantity == 100
    assert order.strategy_id == _SID
    assert order.timestamp_ns == 3 * _SECOND


def test_clean_transition_holds_no_order() -> None:
    # Stage-0 decoupling: a clean ON→OFF is a bounded HOLD; the deferral cap owns
    # the timed exit, so the composer emits nothing here.
    _, store, bus, out = _make()
    _open(store, qty=100)
    bus.publish(_safety(0, safe=False, reason="clean_transition"))
    assert out == []


def test_short_position_exits_with_buy() -> None:
    _, store, bus, out = _make()
    _open(store, qty=-40)
    bus.publish(_safety(0, safe=False, reason="gate_error"))
    assert len(out) == 1
    assert out[0].side.name == "BUY"
    assert out[0].quantity == 40


def test_flat_book_emits_nothing() -> None:
    _, _store, bus, out = _make()  # no position opened
    bus.publish(_safety(0, safe=False, reason="gate_error"))
    assert out == []


def test_safe_on_rearm_never_flattens() -> None:
    # A safe->ON re-arm must not flatten (loosening needs re-authorization, §2.5).
    _, store, bus, out = _make()
    _open(store, qty=100)
    bus.publish(_safety(0, safe=True, reason="clean_transition"))
    assert out == []


def test_unregistered_strategy_ignored() -> None:
    # SafetyStateChange for a non-decoupled (no-policy) strategy is ignored, so
    # the composer never double-flattens alongside that alpha's SIGNAL FLAT.
    _, store, bus, out = _make(policies={_SID: _policy()})
    store.update(_OTHER_SID, _SYMBOL, 100, Decimal("100"), timestamp_ns=0)
    bus.publish(_safety(0, safe=False, reason="gate_error", sid=_OTHER_SID))
    assert out == []


def test_universe_filter_excludes_other_symbols() -> None:
    store = StrategyPositionStore()
    store.update(_SID, "MSFT", 100, Decimal("100"), timestamp_ns=0)
    _, _, bus, out = _make(store=store, policies={_SID: _policy(universe=(_SYMBOL,))})
    bus.publish(_safety(0, safe=False, reason="gate_error", symbol="MSFT"))
    assert out == []


def test_dedup_single_exit_per_episode() -> None:
    # Two error-path safety events against one still-open slice ⇒ one flatten
    # (async fills: the position hasn't gone flat between the two events).
    _, store, bus, out = _make()
    _open(store, qty=100)
    bus.publish(_safety(0, safe=False, reason="gate_error"))
    bus.publish(_safety(1 * _SECOND, safe=False, reason="missing_binding"))
    assert len(out) == 1


def test_flatten_scoped_to_strategy_slice() -> None:
    # Two strategies hold the same symbol; only the decoupled one is composed.
    store = StrategyPositionStore()
    store.update(_SID, _SYMBOL, 100, Decimal("100"), timestamp_ns=0)  # composed slice
    store.update(_OTHER_SID, _SYMBOL, 50, Decimal("100"), timestamp_ns=0)  # bystander
    _, _, bus, out = _make(store=store, policies={_SID: _policy()})
    bus.publish(_safety(0, safe=False, reason="gate_error"))

    assert len(out) == 1
    order = out[0]
    assert order.strategy_id == _SID
    # Slice quantity (100), NOT symbol-net 150 — a symbol-net flatten would
    # cross-close the bystander strategy's slice (design §3.3 defect).
    assert order.quantity == 100
    assert store.get(_OTHER_SID, _SYMBOL).quantity == 50


def test_deterministic_replay() -> None:
    def run() -> str:
        store = StrategyPositionStore()
        _open(store, qty=100)
        _, _, bus, out = _make(store=store)
        bus.publish(_safety(5 * _SECOND, safe=False, reason="gate_error"))
        bus.publish(_safety(6 * _SECOND, safe=False, reason="arithmetic_error"))
        return _serialize(out)

    assert run() == run()


def test_attach_without_policies_is_noop() -> None:
    bus = EventBus()
    store = StrategyPositionStore()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=store,
        policies={},
    )
    composer.attach()  # no policies -> no subscription
    _open(store, qty=100)
    bus.publish(_safety(0, safe=False, reason="gate_error"))
    assert received == []
