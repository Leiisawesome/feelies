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
_ENTRY_PRICE = Decimal("180.00")
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

    def submit(self, request: OrderRequest) -> None:
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

    # Two alphas hold the same symbol; symbol-net is their sum.
    positions.update(_SYMBOL, _QTY_A + _QTY_B, _ENTRY_PRICE)
    strategy_positions.update(_ALPHA_A, _SYMBOL, _QTY_A, _ENTRY_PRICE)
    strategy_positions.update(_ALPHA_B, _SYMBOL, _QTY_B, _ENTRY_PRICE)

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
#   slice sig_alpha_a_v1  qty 0  realized -350.00  fees 0.77   (70sh x -5.00)
#   slice sig_alpha_b_v1  qty 0  realized -275.00  fees 0.60   (55sh x -5.00)
#   trade sig_alpha_a_v1  qty 70 realized -350.00  fees 0.77
#   trade sig_alpha_b_v1  qty 55 realized -275.00  fees 0.60
#
# Quantities sum to the 125-share fill, realized PnL sums to the symbol-net
# -625.00, and fees sum to the ack's 1.37 (largest-remainder, remainder to the
# last leg).  The journal mirrors the slice book exactly.
EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH = (
    "61277728bd9155c6804fe65a0c438b089744c37d7ea4a2378accb7cafef50a9f"
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
    positions.update(_SYMBOL, _QTY_A + _QTY_B, _ENTRY_PRICE)
    strategy_positions.update(_ALPHA_A, _SYMBOL, _QTY_A, _ENTRY_PRICE)
    strategy_positions.update(_ALPHA_B, _SYMBOL, _QTY_B, _ENTRY_PRICE)

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
    # Aggregate realized PnL is preserved by the split.
    assert sum((r.realized_pnl for r in records), Decimal("0")) == (
        positions.get(_SYMBOL).realized_pnl
    )
    # Fees reconcile against the ack.
    assert sum((r.fees for r in records), Decimal("0")) == _EXIT_FEES
