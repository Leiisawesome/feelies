"""G-4: FIFO open-lot ledger (observability beside the avg-cost store)."""

from __future__ import annotations

from decimal import Decimal

import random

from feelies.portfolio.lot_ledger import LotLedger
from feelies.portfolio.memory_position_store import MemoryPositionStore


def _d(x: str) -> Decimal:
    return Decimal(x)


class TestLotLedger:
    def test_adds_lots_in_fifo_order(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1, strategy_id="a")
        led.apply_fill("AAPL", 30, _d("110"), timestamp_ns=2, strategy_id="b")
        lots = led.lots("AAPL")
        assert [(lot.quantity, lot.price) for lot in lots] == [
            (50, _d("100")),
            (30, _d("110")),
        ]
        assert led.net_quantity("AAPL") == 80
        assert led.open_lot_count("AAPL") == 2
        assert lots[0].strategy_id == "a" and lots[1].strategy_id == "b"

    def test_partial_reduce_consumes_front_lot_fifo(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1)
        led.apply_fill("AAPL", 50, _d("110"), timestamp_ns=2)
        # sell 70: consume the +50@100 lot fully and 20 of the +50@110 lot.
        led.apply_fill("AAPL", -70, _d("120"), timestamp_ns=3)
        lots = led.lots("AAPL")
        assert [(lot.quantity, lot.price) for lot in lots] == [(30, _d("110"))]
        assert led.net_quantity("AAPL") == 30
        # FIFO realized: 50*(120-100) + 20*(120-110) = 1000 + 200 = 1200.
        assert led.realized_pnl_fifo("AAPL") == _d("1200")

    def test_cross_through_zero_opens_opposite_lot(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1)
        led.apply_fill("AAPL", -80, _d("90"), timestamp_ns=2)  # flip to short 30
        lots = led.lots("AAPL")
        assert led.net_quantity("AAPL") == -30
        assert [(lot.quantity, lot.price) for lot in lots] == [(-30, _d("90"))]
        # realized only on the 50 closed: 50*(90-100) = -500.
        assert led.realized_pnl_fifo("AAPL") == _d("-500")

    def test_full_close_empties_book(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1)
        led.apply_fill("AAPL", -50, _d("105"), timestamp_ns=2)
        assert led.lots("AAPL") == ()
        assert led.net_quantity("AAPL") == 0
        assert led.realized_pnl_fifo("AAPL") == _d("250")
        assert "AAPL" not in led.symbols()

    def test_oldest_age_is_fifo_front(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1_000)
        led.apply_fill("AAPL", 50, _d("110"), timestamp_ns=2_000)
        assert led.oldest_open_age_ns("AAPL", now_ns=5_000) == 4_000  # vs front
        led.apply_fill("AAPL", -50, _d("120"), timestamp_ns=3_000)  # drop front
        assert led.oldest_open_age_ns("AAPL", now_ns=5_000) == 3_000  # next lot
        assert led.oldest_open_age_ns("MSFT", now_ns=5_000) is None

    def test_short_lots_realize_correctly(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", -50, _d("100"), timestamp_ns=1)  # short 50 @ 100
        led.apply_fill("AAPL", 30, _d("90"), timestamp_ns=2)  # cover 30 @ 90
        assert led.net_quantity("AAPL") == -20
        # short realized: 30*(100-90) = 300.
        assert led.realized_pnl_fifo("AAPL") == _d("300")


# Avg-cost reconciliation tolerance.  ``MemoryPositionStore`` derives
# ``avg_entry_price = total_cost / qty`` — a Decimal division that leaves a
# sub-cent residual on non-terminating quotients (e.g. 6080/120).  That
# residual propagates into realized PnL, so the avg-cost store reconciles
# with the division-free FIFO ledger only to within rounding, not bit-
# exactly.  One cent is far above the observed residual (~1e-20) and is the
# economically meaningful grain.
_RECON_TOLERANCE = Decimal("0.01")


class TestStoreVsLotReconciliation:
    """Audit P1 (2026-06-18): the avg-cost store and the FIFO lot ledger
    legitimately diverge on partial reduces, but they MUST agree on total
    realized PnL (to within avg-cost division rounding) once the symbol
    returns to flat — both have then closed the identical set of shares at
    the identical prices.  This pins that invariant so a regression in
    either ledger surfaces immediately.
    """

    @staticmethod
    def _apply(
        store: MemoryPositionStore,
        led: LotLedger,
        symbol: str,
        signed_qty: int,
        price: Decimal,
        ts: int,
    ) -> None:
        store.update(symbol, signed_qty, price, timestamp_ns=ts)
        led.apply_fill(symbol, signed_qty, price, timestamp_ns=ts)

    def test_agree_at_flat_open_add_reduce_cross(self) -> None:
        store = MemoryPositionStore()
        led = LotLedger()
        # open → add → reduce-through-zero (flip to short) → cover to flat.
        self._apply(store, led, "AAPL", 100, _d("10"), 1)
        self._apply(store, led, "AAPL", 100, _d("12"), 2)
        # -250 closes the +200 long and opens a -50 short (crosses zero).
        self._apply(store, led, "AAPL", -250, _d("13"), 3)
        # mid-stream the two ledgers may differ (FIFO vs blended); only
        # the total-to-flat is contractually equal.
        self._apply(store, led, "AAPL", 50, _d("9"), 4)  # cover short → flat
        assert store.get("AAPL").quantity == 0
        assert led.net_quantity("AAPL") == 0
        assert (
            abs(store.get("AAPL").realized_pnl - led.realized_pnl_fifo("AAPL")) <= _RECON_TOLERANCE
        )

    def test_agree_at_flat_short_first(self) -> None:
        store = MemoryPositionStore()
        led = LotLedger()
        self._apply(store, led, "MSFT", -80, _d("50"), 1)
        self._apply(store, led, "MSFT", -40, _d("52"), 2)
        self._apply(store, led, "MSFT", 60, _d("48"), 3)
        self._apply(store, led, "MSFT", 60, _d("47"), 4)  # back to flat
        assert store.get("MSFT").quantity == 0
        assert led.net_quantity("MSFT") == 0
        assert (
            abs(store.get("MSFT").realized_pnl - led.realized_pnl_fifo("MSFT")) <= _RECON_TOLERANCE
        )

    def test_randomized_fill_streams_agree_when_returned_to_flat(self) -> None:
        rng = random.Random(20260618)
        for _ in range(200):
            store = MemoryPositionStore()
            led = LotLedger()
            qty = 0
            ts = 0
            fills: list[tuple[int, Decimal]] = []
            for _ in range(rng.randint(2, 12)):
                ts += 1
                delta = rng.randint(-100, 100)
                if delta == 0:
                    continue
                price = _d(str(rng.randint(80, 120)))
                fills.append((delta, price))
                self._apply(store, led, "SYM", delta, price, ts)
                qty += delta
            # Force the book back to flat with one closing fill.
            if qty != 0:
                ts += 1
                self._apply(store, led, "SYM", -qty, _d("100"), ts)
            assert store.get("SYM").quantity == 0
            assert led.net_quantity("SYM") == 0
            diff = abs(store.get("SYM").realized_pnl - led.realized_pnl_fifo("SYM"))
            assert diff <= _RECON_TOLERANCE, (diff, fills)
