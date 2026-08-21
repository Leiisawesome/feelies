"""Pin per-strategy attribution of a symbol-net forced exit.

A forced exit (stop-loss, session flatten, hazard spike, Stage-0 flatten,
bounded-deferral cap) closes the **symbol-net** book, so its fill belongs to
whichever strategy slices were holding the symbol — not to the order's own
``strategy_id``, which for these authors is either a kernel sentinel or the one
policy that happened to trigger.

Nothing in the determinism corpus covered this before.  The replay fixtures
either wire no ``StrategyPositionStore`` at all, or hash order/state streams
rather than the journal, and ``compute_parity_hash`` did not include
``strategy_id``.  A fill could therefore move between alphas — inverting a
measured per-alpha edge and with it a promotion or quarantine decision — while
every parity check in the repo stayed green.

This fixture closes that: two strategies share one symbol, a symbol-net forced
exit flattens it, and both the slice book and the journal attribution are
hashed.  The scenario is driven through the real ``_reconcile_fills`` path so
the largest-remainder split, the fee remainder, and the journal legs are all
exercised together.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backend import ExecutionBackend
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_trade_journal import InMemoryTradeJournal

_SYMBOL = "AAPL"
_ALPHA_A = "sig_alpha_a_v1"
_ALPHA_B = "sig_alpha_b_v1"
# Deliberately uneven so the largest-remainder split has a remainder to place,
# and so an off-by-one in either allocator shows up in the hash.
_QTY_A = 70
_QTY_B = 55
# Divergent entry prices are the whole point of this fixture.  When both slices
# enter at the same price, splitting the *aggregate* realized PnL by quantity and
# reading each slice's own realized delta give identical answers — so a fixture
# built on one entry price cannot tell a correct attribution from a proportional
# one.  Here the symbol-net exit is a small aggregate gain (+475) that decomposes
# into a loss for A and a larger gain for B; a proportional split would report a
# gain for both, inverting A's sign.
_ENTRY_PRICE_A = Decimal("180.00")
_ENTRY_PRICE_B = Decimal("160.00")
_EXIT_PRICE = Decimal("175.00")
_EXIT_FEES = Decimal("1.37")


class _NoOpMetricCollector:
    def record(self, _metric: object) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self):  # type: ignore[no-untyped-def]
        return iter([])


class _FillingRouter:
    """Fills every submitted order at ``_EXIT_PRICE``."""

    def __init__(self) -> None:
        self.submitted: list[OrderRequest] = []
        self._pending: list[OrderAck] = []

    def submit(
        self, request: OrderRequest, triggering_quote: NBBOQuote | None = None
    ) -> None:
        self.submitted.append(request)
        self._pending.append(
            OrderAck(
                timestamp_ns=request.timestamp_ns + 1,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.FILLED,
                filled_quantity=request.quantity,
                fill_price=_EXIT_PRICE,
                fees=_EXIT_FEES,
            )
        )

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending)
        self._pending.clear()
        return acks


class _MinimalConfig:
    version = "test-forced-exit-attribution"
    symbols = frozenset({_SYMBOL})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _replay() -> tuple[str, int]:
    """Flatten a two-strategy book with a symbol-net forced exit."""
    clock = SimulatedClock(start_ns=1_000)
    bus = EventBus()
    positions = MemoryPositionStore()
    strategy_positions = StrategyPositionStore()

    # Two alphas hold the same symbol at different prices; symbol-net is their sum
    # and its avg_entry_price is the notional-weighted blend of the two.
    positions.update(_SYMBOL, _QTY_A, _ENTRY_PRICE_A)
    positions.update(_SYMBOL, _QTY_B, _ENTRY_PRICE_B)
    strategy_positions.update(_ALPHA_A, _SYMBOL, _QTY_A, _ENTRY_PRICE_A)
    strategy_positions.update(_ALPHA_B, _SYMBOL, _QTY_B, _ENTRY_PRICE_B)

    router = _FillingRouter()
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=router,  # type: ignore[arg-type]
            mode="BACKTEST",
        ),
        risk_engine=_AllowRiskEngine(),
        position_store=positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        strategy_positions=strategy_positions,
        trade_journal=InMemoryTradeJournal(),
        account_equity=Decimal("1000000"),
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")

    exit_order = OrderRequest(
        timestamp_ns=2_000,
        correlation_id="forced-exit-corr",
        sequence=1,
        source_layer="RISK",
        order_id="forced-exit-1",
        symbol=_SYMBOL,
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=_QTY_A + _QTY_B,
        strategy_id=_ALPHA_A,  # one policy triggered; the fill spans both slices
        reason="HAZARD_SPIKE",
    )
    bus.publish(exit_order)

    journal = orch.trade_journal
    assert journal is not None
    records = list(journal.query())

    # Hash the attribution, not just the aggregate: per-strategy slice quantity
    # and realized PnL, plus each journal leg's strategy_id.
    parts: list[str] = []
    for sid in sorted(strategy_positions.strategy_ids()):
        pos = strategy_positions.get(sid, _SYMBOL)
        parts.append(
            f"SLICE|{sid}|{pos.quantity}|{pos.realized_pnl:.6f}|{pos.cumulative_fees:.6f}"
        )
    for rec in records:
        parts.append(
            f"TRADE|{rec.strategy_id}|{rec.filled_quantity}|"
            f"{rec.realized_pnl:.6f}|{rec.fees:.6f}|"
            f"{rec.metadata.get('forced_exit_strategy_id', '')}"
        )
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest, len(records)


class _AllowRiskEngine:
    """Permissive risk engine — this fixture pins attribution, not risk."""

    def check_signal(self, signal: object, positions: object) -> object:
        raise AssertionError("forced-exit fixture must not walk the signal path")

    def check_order(self, order: OrderRequest, positions: object, **_kw: object) -> object:
        from feelies.core.events import RiskAction, RiskVerdict

        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="ok",
        )

    def check_sized_intent(self, intent: object, positions: object) -> object:
        raise AssertionError("forced-exit fixture must not walk the portfolio path")


# ── Locked baseline ─────────────────────────────────────────────────────
# A move here means per-strategy fill attribution changed and needs a rationale
# in the commit.  The pinned values, inspected at baseline time:
#
#   slice sig_alpha_a_v1  qty 0  realized -350.00  fees 0.77   (70sh x 175-180)
#   slice sig_alpha_b_v1  qty 0  realized  825.00  fees 0.60   (55sh x 175-160)
#   trade sig_alpha_a_v1  qty 70 realized -350.00  fees 0.77
#   trade sig_alpha_b_v1  qty 55 realized  825.00  fees 0.60
#
# Quantities sum to the 125-share fill, realized PnL sums to the symbol-net
# +475.00 (125sh against the blended 171.20 entry), and fees sum to the ack's
# 1.37 (largest-remainder, remainder to the last leg).  The journal mirrors the
# slice book exactly.
#
# The signs are the load-bearing part.  Splitting the aggregate +475.00 by
# quantity yields +266.00 / +209.00 — a gain for both, though A actually lost
# 350.  Per-alpha forensics groups by strategy_id, so that split would have fed
# the promotion and quarantine gates a losing alpha dressed as a winner.
EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH = (
    "8a2844e102e94060e5691ae57a2f4fcea1fd57b2a4a9d05726edc7277b339164"
)
EXPECTED_FORCED_EXIT_ATTRIBUTION_COUNT = 2


def test_forced_exit_attribution_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_FORCED_EXIT_ATTRIBUTION_COUNT, (
        f"journal leg count drift: expected "
        f"{EXPECTED_FORCED_EXIT_ATTRIBUTION_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH, (
        "forced-exit attribution drift.\n"
        f"  Expected: {EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH}\n"
        f"  Actual:   {actual_hash}\n"
    )


def test_two_replays_produce_identical_attribution_hash() -> None:
    assert _replay() == _replay()


def test_forced_exit_closes_both_slices_and_mints_no_sentinel() -> None:
    """The behavioural claim behind the hash, asserted in the clear."""
    clock = SimulatedClock(start_ns=1_000)
    bus = EventBus()
    positions = MemoryPositionStore()
    strategy_positions = StrategyPositionStore()
    positions.update(_SYMBOL, _QTY_A, _ENTRY_PRICE_A)
    positions.update(_SYMBOL, _QTY_B, _ENTRY_PRICE_B)
    strategy_positions.update(_ALPHA_A, _SYMBOL, _QTY_A, _ENTRY_PRICE_A)
    strategy_positions.update(_ALPHA_B, _SYMBOL, _QTY_B, _ENTRY_PRICE_B)

    router = _FillingRouter()
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=router,  # type: ignore[arg-type]
            mode="BACKTEST",
        ),
        risk_engine=_AllowRiskEngine(),
        position_store=positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        strategy_positions=strategy_positions,
        trade_journal=InMemoryTradeJournal(),
        account_equity=Decimal("1000000"),
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")

    bus.publish(
        OrderRequest(
            timestamp_ns=2_000,
            correlation_id="forced-exit-corr",
            sequence=1,
            source_layer="RISK",
            order_id="forced-exit-1",
            symbol=_SYMBOL,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=_QTY_A + _QTY_B,
            strategy_id=_ALPHA_A,
            reason="HAZARD_SPIKE",
        )
    )

    # Symbol-net is flat and both slices closed — neither is stranded open.
    assert positions.get(_SYMBOL).quantity == 0
    assert strategy_positions.get(_ALPHA_A, _SYMBOL).quantity == 0
    assert strategy_positions.get(_ALPHA_B, _SYMBOL).quantity == 0

    journal = orch.trade_journal
    assert journal is not None
    records = list(journal.query())
    # One leg per closed slice, not one row credited wholly to the trigger.
    assert sorted(r.strategy_id for r in records) == [_ALPHA_A, _ALPHA_B]
    assert sum(r.filled_quantity for r in records) == _QTY_A + _QTY_B
    # Every slice this exit touched was closed outright, so the legs also happen
    # to sum to the symbol-net figure.  That is a property of *this* book, not a
    # general invariant — see
    # ``test_legs_need_not_sum_to_symbol_net_when_slices_survive_the_exit``.
    assert sum((r.realized_pnl for r in records), Decimal("0")) == (
        positions.get(_SYMBOL).realized_pnl
    )
    # Fees reconcile against the ack.
    assert sum((r.fees for r in records), Decimal("0")) == _EXIT_FEES

    # ...and each leg carries *its own* realized PnL, not the aggregate
    # apportioned by quantity.  Summing to the right total is not enough: a
    # proportional split satisfies that too while reporting the wrong number for
    # every individual slice, which is what forensics groups by.
    by_alpha = {r.strategy_id: r.realized_pnl for r in records}
    assert by_alpha[_ALPHA_A] == (_EXIT_PRICE - _ENTRY_PRICE_A) * _QTY_A
    assert by_alpha[_ALPHA_B] == (_EXIT_PRICE - _ENTRY_PRICE_B) * _QTY_B
    # The journal is the same story the slice book tells.
    for alpha_id in (_ALPHA_A, _ALPHA_B):
        assert by_alpha[alpha_id] == strategy_positions.get(alpha_id, _SYMBOL).realized_pnl
    # A is down and B is up, though the symbol-net exit booked an aggregate gain —
    # the sign disagreement a proportional split would have erased.
    assert by_alpha[_ALPHA_A] < 0 < positions.get(_SYMBOL).realized_pnl < by_alpha[_ALPHA_B]


def test_legs_need_not_sum_to_symbol_net_when_slices_survive_the_exit() -> None:
    """The journal and the position store are two decompositions, not one figure.

    On a **mixed-sign** book a symbol-net exit lands only on the slices that
    oppose it, so the slices it does not touch stay open while symbol-net reaches
    zero.  The store has then realised the whole episode; the journal has realised
    only the part that closed, and the rest is still unrealised in the surviving
    slices.  The two are both correct and they do not agree.

    Pinned because the alternative — forcing the legs to sum — is exactly the
    proportional split this fixture exists to reject: it reconciles by assigning
    every slice the blended basis instead of its own.  A reader who assumes the
    sum holds will "fix" it back.

    The account's economics live in the store.  Per-alpha attribution lives in the
    journal.  Anything summing journal ``realized_pnl`` to a portfolio total is
    reading the wrong record (see ``backtest_report.generate_report``, which takes
    its headline from the store).
    """
    alpha_c = "sig_alpha_c_v1"
    positions = MemoryPositionStore()
    strategy_positions = StrategyPositionStore()
    # Long 60 @ 275, short 20 @ 275 (books no aggregate PnL), long 60 @ 195.
    # Symbol-net is 100 at a blended basis of 227.00, which is no slice's own.
    book = (
        (_ALPHA_A, 60, Decimal("275.00")),
        (_ALPHA_B, -20, Decimal("275.00")),
        (alpha_c, 60, Decimal("195.00")),
    )
    for alpha_id, qty, price in book:
        positions.update(_SYMBOL, qty, price, timestamp_ns=1_000)
        strategy_positions.update(alpha_id, _SYMBOL, qty, price, timestamp_ns=1_000)
    assert positions.get(_SYMBOL).quantity == 100
    assert positions.get(_SYMBOL).avg_entry_price == Decimal("227.00")

    router = _FillingRouter()
    orch = Orchestrator(
        clock=SimulatedClock(start_ns=1_000),
        bus=(bus := EventBus()),
        backend=ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=router,  # type: ignore[arg-type]
            mode="BACKTEST",
        ),
        risk_engine=_AllowRiskEngine(),
        position_store=positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        strategy_positions=strategy_positions,
        trade_journal=InMemoryTradeJournal(),
        account_equity=Decimal("1000000"),
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")

    bus.publish(
        OrderRequest(
            timestamp_ns=2_000,
            correlation_id="forced-exit-corr",
            sequence=1,
            source_layer="RISK",
            order_id="forced-exit-mixed",
            symbol=_SYMBOL,
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            strategy_id=_ALPHA_A,
            reason="HAZARD_SPIKE",
        )
    )

    # Symbol-net is flat, but only the two long slices were reduced: the short was
    # never opposed by a SELL, so it survives and the longs keep a residual.
    assert positions.get(_SYMBOL).quantity == 0
    assert strategy_positions.get(_ALPHA_A, _SYMBOL).quantity == 10
    assert strategy_positions.get(_ALPHA_B, _SYMBOL).quantity == -20
    assert strategy_positions.get(alpha_c, _SYMBOL).quantity == 10
    # Quantities still reconcile — that invariant *is* general.
    assert (
        sum(strategy_positions.get(a, _SYMBOL).quantity for a in (_ALPHA_A, _ALPHA_B, alpha_c))
        == positions.get(_SYMBOL).quantity
    )

    records = list(orch.trade_journal.query())  # type: ignore[union-attr]
    by_alpha = {r.strategy_id: r.realized_pnl for r in records}
    # 50 shares off each long, each against its own entry.
    assert by_alpha[_ALPHA_A] == (_EXIT_PRICE - Decimal("275.00")) * 50
    assert by_alpha[alpha_c] == (_EXIT_PRICE - Decimal("195.00")) * 50
    assert _ALPHA_B not in by_alpha

    # The divergence, stated as a number so a change in it has to be deliberate.
    journal_total = sum((r.realized_pnl for r in records), Decimal("0"))
    assert journal_total == Decimal("-6000.00")
    assert positions.get(_SYMBOL).realized_pnl == Decimal("-5200.00")
    assert journal_total != positions.get(_SYMBOL).realized_pnl

    # Fees still reconcile against the ack — that invariant is general too.
    assert sum((r.fees for r in records), Decimal("0")) == _EXIT_FEES
