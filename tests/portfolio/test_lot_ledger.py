"""G-4: FIFO open-lot ledger (observability beside the avg-cost store)."""

from __future__ import annotations

from decimal import Decimal

from feelies.portfolio.lot_ledger import LotLedger


def _d(x: str) -> Decimal:
    return Decimal(x)


class TestLotLedger:
    def test_adds_lots_in_fifo_order(self) -> None:
        led = LotLedger()
        led.apply_fill("AAPL", 50, _d("100"), timestamp_ns=1, strategy_id="a")
        led.apply_fill("AAPL", 30, _d("110"), timestamp_ns=2, strategy_id="b")
        lots = led.lots("AAPL")
        assert [(lot.quantity, lot.price) for lot in lots] == [
            (50, _d("100")), (30, _d("110")),
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
        led.apply_fill("AAPL", 30, _d("90"), timestamp_ns=2)    # cover 30 @ 90
        assert led.net_quantity("AAPL") == -20
        # short realized: 30*(100-90) = 300.
        assert led.realized_pnl_fifo("AAPL") == _d("300")
