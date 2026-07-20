"""Pin causal fill timing for the passive-limit router.

Events before ``max(clock.now, submit exchange time) + latency`` cannot fill,
consume hazard draws, advance queue state, satisfy trade gates, or expire a
resting order. Cancellation timestamps cannot precede acknowledgement.
Post-eligibility through-fills enforce displayed-size caps. Halt handling is
tested at the orchestrator boundary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
    Trade,
)
from feelies.core.platform_config import PlatformConfig
from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
    ZeroCostModel,
)
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.execution.trading_session import (
    TradingSessionBounds,
    resolve_trading_session_bounds,
)

pytestmark = pytest.mark.backtest_validation


def _quote(
    symbol: str,
    bid: str,
    ask: str,
    ts: int,
    bid_size: int = 100,
    ask_size: int = 100,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _trade(symbol: str, price: str, size: int, ts: int) -> Trade:
    return Trade(
        timestamp_ns=ts,
        exchange_timestamp_ns=ts,
        correlation_id=f"t-{ts}",
        sequence=ts,
        symbol=symbol,
        price=Decimal(price),
        size=size,
    )


def _limit(
    symbol: str,
    side: Side,
    qty: int,
    limit_price: str,
    order_id: str = "ord1",
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="o1",
        sequence=1,
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=Decimal(limit_price),
    )


def _fills(acks: list[OrderAck]) -> list[OrderAck]:
    return [
        a for a in acks if a.status in (OrderAckStatus.FILLED, OrderAckStatus.PARTIALLY_FILLED)
    ]


class TestZeroLatencyProhibitionPrecondition:
    """00c decision A: zero fill latency is forbidden in evidence-producing
    runs.  The shipped reference profile must pin both latencies non-zero;
    a Task-12 run against a zero-latency config is a precondition failure."""

    def test_reference_profile_pins_nonzero_latencies(self) -> None:
        cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
        assert cfg.backtest_fill_latency_ns > 0
        assert cfg.market_data_latency_ns > 0


class TestThroughFillInsideLatencyWindow:
    """A crossing quote inside the order-entry latency window must neither
    fill immediately nor be remembered as a deferred fill source."""

    def _router(self, clock: SimulatedClock) -> PassiveLimitOrderRouter:
        # fill_hazard_max=0 disables drain fills entirely, so any FILLED ack
        # in these tests could only come from a (stale) through-fill.
        return PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
            fill_hazard_max=Decimal("0"),
        )

    def test_buy_cross_then_revert_inside_window_never_fills(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = self._router(clock)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        router.poll_acks()  # ACKNOWLEDGED; eligible_at = 5000 + 1000 = 6000

        # Ask gaps through the resting limit INSIDE the window, then reverts
        # before eligibility.  The stale cross must never produce a fill.
        clock.set_time(5500)
        router.on_quote(_quote("AAPL", "99.80", "99.90", ts=5500))
        assert _fills(router.poll_acks()) == []
        clock.set_time(5900)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5900))
        assert _fills(router.poll_acks()) == []

        # Post-eligibility quotes never cross again → no fill, still resting.
        for ts in (6100, 6200, 6300):
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            assert _fills(router.poll_acks()) == []
        assert router.resting_order_count == 1

    def test_sell_cross_then_revert_inside_window_never_fills(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = self._router(clock)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.SELL, 100, "100.10"))
        router.poll_acks()

        clock.set_time(5500)
        router.on_quote(_quote("AAPL", "100.20", "100.30", ts=5500))
        assert _fills(router.poll_acks()) == []
        clock.set_time(5900)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5900))
        assert _fills(router.poll_acks()) == []

        for ts in (6100, 6200, 6300):
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            assert _fills(router.poll_acks()) == []
        assert router.resting_order_count == 1

    def test_fill_prices_off_post_eligibility_quote_not_stale_cross(self) -> None:
        """The stale in-window cross offers a BETTER price (99.90) than the
        post-eligibility cross (99.98).  The fill must price off the
        post-eligibility quote — pricing at 99.90 would be lookahead."""
        clock = SimulatedClock(start_ns=5000)
        router = self._router(clock)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        router.poll_acks()

        clock.set_time(5500)
        router.on_quote(_quote("AAPL", "99.80", "99.90", ts=5500))
        assert _fills(router.poll_acks()) == []

        clock.set_time(6500)
        router.on_quote(_quote("AAPL", "99.90", "99.98", ts=6500))
        fills = _fills(router.poll_acks())
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("99.98")
        assert fills[0].timestamp_ns == 6500


class TestStaleQuoteStateNonContamination:
    """Pre-eligibility quotes must not touch resting-order state: no seeded
    hazard draws, no ``ticks_at_level`` advance, no ``total_ticks`` advance."""

    @staticmethod
    def _run_drain_scenario(pre_window_quotes: int) -> list[OrderAck]:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=5000,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=2,
            max_resting_ticks=1000,
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        router.poll_acks()  # eligible_at = 5000 + 5000 = 10000

        # Stale at-level quotes inside the window.  If these (incorrectly)
        # consumed hazard trials or advanced ``ticks_at_level``, the seeded
        # uniforms of the post-window quotes would shift and the fill tick
        # below would differ from the control run.
        for i in range(pre_window_quotes):
            ts = 6000 + i * 100
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            assert router.poll_acks() == []

        # Identical post-window sequence in every run.
        acks: list[OrderAck] = []
        for i in range(100):
            ts = 10000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            acks = router.poll_acks()
            if acks:
                break
        return acks

    def test_pre_eligibility_quotes_do_not_consume_hazard_trials(self) -> None:
        control = self._run_drain_scenario(pre_window_quotes=0)
        treatment = self._run_drain_scenario(pre_window_quotes=7)
        assert control, "control run must drain-fill within 100 ticks"
        assert len(control) == len(treatment) == 1
        assert control[0].status == treatment[0].status == OrderAckStatus.FILLED
        assert control[0].timestamp_ns == treatment[0].timestamp_ns
        assert control[0].fill_price == treatment[0].fill_price
        assert control[0].filled_quantity == treatment[0].filled_quantity

    def test_pre_eligibility_quotes_do_not_count_toward_passive_expiry(self) -> None:
        """``max_resting_ticks`` is measured in live (post-eligibility) ticks.
        Five stale quotes > ``max_resting_ticks=3`` must not expire the order;
        expiry fires on the third eligible tick, timestamped ≥ ACKNOWLEDGED."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=5000,
            cost_model=ZeroCostModel(),
            max_resting_ticks=3,
            fill_hazard_max=Decimal("0"),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        ack = router.poll_acks()[0]
        assert ack.status == OrderAckStatus.ACKNOWLEDGED  # eligible_at = 10000

        for i in range(5):  # 5 stale ticks > max_resting_ticks
            ts = 6000 + i * 100
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            assert router.poll_acks() == []
        assert router.resting_order_count == 1

        expired: list[OrderAck] = []
        for i in range(3):  # off-level eligible ticks (bid above the limit)
            ts = 10000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.02", "100.12", ts=ts))
            expired = router.poll_acks()
        assert len(expired) == 1
        assert expired[0].status == OrderAckStatus.EXPIRED
        assert expired[0].timestamp_ns >= ack.timestamp_ns
        assert router.resting_order_count == 0


class TestArrivalMidQueueDrain:
    """Ignore queue-drain prints that predate the order's live time."""

    def test_pre_eligibility_print_does_not_satisfy_volume_gate(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=2000,
            cost_model=ZeroCostModel(),
            require_trade_for_level_fill=True,
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        router.poll_acks()  # eligible_at = 5000 + 2000 = 7000

        # In-window print at the level: alone it would satisfy the volume
        # gate, but the order was not on the book when it occurred.
        router.on_trade(_trade("AAPL", "100.00", 500, ts=6000))
        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=7000))
        assert router.poll_acks() == []

        # A post-eligibility print satisfies the gate → guaranteed drain
        # (h = 1.0) on the next at-level quote.
        router.on_trade(_trade("AAPL", "100.00", 500, ts=7500))
        clock.set_time(8000)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=8000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].reason == "FILLED_BY_DRAIN"


class TestCancelReplenishAtRestingLevel:
    """Liquidity cancel/replenish at the resting level inside the latency
    window, and explicit client cancels inside the window."""

    @staticmethod
    def _run_with_pre_window(pre_window: list[NBBOQuote]) -> list[OrderAck]:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=5000,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=2,
            max_resting_ticks=1000,
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00"))
        router.poll_acks()  # eligible_at = 10000

        for q in pre_window:
            clock.set_time(q.exchange_timestamp_ns)
            router.on_quote(q)
            assert router.poll_acks() == []

        acks: list[OrderAck] = []
        for i in range(100):
            ts = 10000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=ts))
            acks = router.poll_acks()
            if acks:
                break
        return acks

    def test_level_cancel_and_replenish_inside_window_leaves_state_untouched(
        self,
    ) -> None:
        """The level empties (bid steps above the limit) and replenishes
        inside the window — neither transition may touch the resting-order
        counters, so the post-window behavior matches the control run."""
        control = self._run_with_pre_window([])
        treatment = self._run_with_pre_window(
            [
                _quote("AAPL", "100.00", "100.10", ts=6000),  # at level
                _quote("AAPL", "100.02", "100.12", ts=6500),  # level cancelled
                _quote("AAPL", "100.00", "100.10", ts=7000),  # replenished
            ]
        )
        assert control, "control run must drain-fill within 100 ticks"
        assert len(control) == len(treatment) == 1
        assert control[0].status == treatment[0].status
        assert control[0].timestamp_ns == treatment[0].timestamp_ns
        assert control[0].fill_price == treatment[0].fill_price

    def test_explicit_cancel_inside_window_floors_ts_and_blocks_fill(self) -> None:
        """A client cancel inside the latency window emits CANCELLED
        timestamped no earlier than ACKNOWLEDGED (monotonic per-order ack
        stream), and a later crossing quote must not fill the dead order."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=2000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.00", order_id="c1"))
        ack = router.poll_acks()[0]
        assert ack.status == OrderAckStatus.ACKNOWLEDGED
        assert ack.timestamp_ns == 7000

        clock.set_time(5500)  # inside the window
        assert router.cancel_order("c1") is True
        cancelled = router.poll_acks()[0]
        assert cancelled.status == OrderAckStatus.CANCELLED
        assert cancelled.timestamp_ns >= ack.timestamp_ns

        clock.set_time(8000)  # post-eligibility crossing quote
        router.on_quote(_quote("AAPL", "99.80", "99.90", ts=8000))
        assert _fills(router.poll_acks()) == []
        assert router.resting_order_count == 0


class TestSizeCapSplit:
    """FQ-2 through-fill size-cap split cases T12-SC1..T12-SC5
    (``docs/research/prompt_pack_00c_eval_canon.md`` §2)."""

    @staticmethod
    def _cap_router(
        clock: SimulatedClock,
        *,
        cost_model: DefaultCostModel | ZeroCostModel | None = None,
        cancel_fee_per_share: Decimal = Decimal("0.0"),
        max_resting_ticks: int = 50,
        fill_hazard_max: Decimal = Decimal("0"),
        fill_delay_ticks: int = 3,
        trading_session_bounds: TradingSessionBounds | None = None,
    ) -> PassiveLimitOrderRouter:
        return PassiveLimitOrderRouter(
            clock,
            cost_model=cost_model or ZeroCostModel(),
            through_fill_size_cap_enabled=True,
            cancel_fee_per_share=cancel_fee_per_share,
            max_resting_ticks=max_resting_ticks,
            fill_hazard_max=fill_hazard_max,
            fill_delay_ticks=fill_delay_ticks,
            trading_session_bounds=trading_session_bounds,
        )

    def test_sc1_partial_then_expire_cancel_fee_on_full_original_quantity(
        self,
    ) -> None:
        """T12-SC1: partial through-fill then timeout.  Pins the shipped
        behavior: the EXPIRED ack's cancel fee is computed on the FULL
        original quantity (``pending.request.quantity``), not the unfilled
        remainder — inert on the canonical profile (fee 0.0) but a
        conservative wrong-basis divergence if a fee is ever configured
        (00c §2 characterization).  Terminal accounting: only the partial
        30 shares ever filled."""
        clock = SimulatedClock(start_ns=5000)
        router = self._cap_router(
            clock,
            cancel_fee_per_share=Decimal("0.01"),
            max_resting_ticks=3,
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.05"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=6000, ask_size=30))
        partial = router.poll_acks()
        assert [a.status for a in partial] == [OrderAckStatus.PARTIALLY_FILLED]
        assert partial[0].filled_quantity == 30

        terminal: list[OrderAck] = []
        for i in range(3):  # off-level quotes (bid above limit, no through)
            ts = 7000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "100.10", "100.20", ts=ts))
            terminal.extend(router.poll_acks())
        assert [a.status for a in terminal] == [OrderAckStatus.EXPIRED]
        # Cancel fee basis: 0.01 × 100 (full original), not 0.01 × 70.
        assert terminal[0].fees == Decimal("1.00")
        assert router.resting_order_count == 0
        # Partially-filled-then-expired tallies as a cancel (terminal-only
        # stats), despite having filled shares.
        stats = router.passive_fill_stats()
        assert stats["filled"] == 0
        assert stats["cancelled"] == 1

    def test_sc2_per_slice_commission_floor_applies_per_slice(self) -> None:
        """T12-SC2: a two-slice split of a 50-share order pays the IBKR
        $0.35 minimum-commission floor PER SLICE (2 × 0.35 total) —
        conservative vs IBKR's per-order billing (00c §2)."""
        cost = DefaultCostModel(
            DefaultCostModelConfig(
                maker_exchange_per_share=Decimal("0"),
                passive_adverse_selection_bps=Decimal("0"),
                through_fill_adverse_selection_bps=Decimal("0"),
                adverse_selection_through_bps=Decimal("0"),
                adverse_selection_drain_bps=Decimal("0"),
                sell_regulatory_bps=Decimal("0"),
                finra_taf_per_share=Decimal("0"),
            )
        )
        clock = SimulatedClock(start_ns=5000)
        router = self._cap_router(clock, cost_model=cost)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 50, "100.05"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=6000, ask_size=30))
        slice1 = router.poll_acks()
        assert [a.status for a in slice1] == [OrderAckStatus.PARTIALLY_FILLED]
        assert slice1[0].filled_quantity == 30
        assert slice1[0].fees == Decimal("0.35")  # floored (30 × 0.0035 = 0.105)

        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=7000, ask_size=1000))
        slice2 = router.poll_acks()
        assert [a.status for a in slice2] == [OrderAckStatus.FILLED]
        assert slice2[0].filled_quantity == 20
        assert slice2[0].fees == Decimal("0.35")  # floored again, per slice
        assert slice1[0].fees + slice2[0].fees == Decimal("0.70")

    def test_sc3_partial_then_rth_suppression_rejects_after_partial(self) -> None:
        """T12-SC3: partial through-fill inside RTH, then the next
        through-tick lands past the RTH close → the router REJECTS an order
        that already has ``filled_quantity > 0`` and removes it (00c §2;
        downstream position handling is the position manager's concern)."""
        session = date(2026, 3, 24)
        bounds = resolve_trading_session_bounds(session)
        t0 = bounds.rth_open_ns + 3_600_000_000_000  # 10:30 ET
        clock = SimulatedClock(start_ns=t0)
        router = self._cap_router(clock, trading_session_bounds=bounds)

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=t0))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.05"))
        router.poll_acks()

        t1 = t0 + 1_000_000_000
        clock.set_time(t1)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=t1, ask_size=30))
        partial = router.poll_acks()
        assert [a.status for a in partial] == [OrderAckStatus.PARTIALLY_FILLED]
        assert partial[0].filled_quantity == 30

        t2 = bounds.rth_close_ns + 1_000_000_000  # past the close, same date
        clock.set_time(t2)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=t2, ask_size=1000))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.REJECTED]
        assert "RTH" in acks[0].reason
        assert router.resting_order_count == 0

    def test_sc4_zero_size_crossing_falls_back_to_full_remainder(self) -> None:
        """T12-SC4: a degenerate through-tick with zero displayed size on the
        crossing side fills the FULL remainder (shipped fallback, 00c §2)."""
        clock = SimulatedClock(start_ns=5000)
        router = self._cap_router(clock)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.05"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "100.00", "100.04", ts=6000, ask_size=0))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.FILLED]
        assert acks[0].filled_quantity == 100
        assert acks[0].reason == "FILLED_BY_THROUGH"

    def test_sc5_drain_of_remainder_bills_level_adverse_rate(self) -> None:
        """T12-SC5: partial through-fill (THROUGH adverse rate) then drain of
        the remainder — the drain ack quantity equals the remainder and its
        adverse selection switches to the LEVEL rate (2.0 vs 5.0 bps)."""
        cost = DefaultCostModel(
            DefaultCostModelConfig(
                commission_per_share=Decimal("0"),
                min_commission=Decimal("0"),
                maker_exchange_per_share=Decimal("0"),
                sell_regulatory_bps=Decimal("0"),
                finra_taf_per_share=Decimal("0"),
                # Defaults kept explicit: THROUGH 5.0 bps, LEVEL 2.0 bps.
                through_fill_adverse_selection_bps=Decimal("5.0"),
                passive_adverse_selection_bps=Decimal("2.0"),
            )
        )
        clock = SimulatedClock(start_ns=5000)
        router = self._cap_router(
            clock,
            cost_model=cost,
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5000))
        router.submit(_limit("AAPL", Side.BUY, 100, "100.05"))
        router.poll_acks()

        # Through slice: ask at the limit, 30 displayed → partial 30.
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "100.00", "100.05", ts=6000, ask_size=30))
        slice1 = router.poll_acks()
        assert [a.status for a in slice1] == [OrderAckStatus.PARTIALLY_FILLED]
        assert slice1[0].filled_quantity == 30
        # THROUGH adverse: 100.05 (crossing ask) × 30 × 5.0 bps = 1.50.
        assert slice1[0].fees == Decimal("1.50")

        # Drain of the remainder: our level back at the BBO, h = 1.0.
        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "100.05", "100.15", ts=7000))
        drain = router.poll_acks()
        assert [a.status for a in drain] == [OrderAckStatus.FILLED]
        assert drain[0].filled_quantity == 70  # exactly the remainder
        assert drain[0].reason == "FILLED_BY_DRAIN"
        # LEVEL adverse: 100.15 (opposite BBO) × 70 × 2.0 bps = 1.40 —
        # strictly the gentler rate despite the larger slice.
        assert drain[0].fees == Decimal("1.40")
