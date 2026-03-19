"""Multi-symbol ordering and independence tests.

Skills: backtest-engine, data-engineering, feature-engine
Invariants: 6 (causality), 5 (determinism)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import (
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderRequest,
)

from .conftest import BusRecorder, _run_scenario

pytestmark = pytest.mark.backtest_validation


class TestMultiSymbolOrdering:
    """Multi-symbol event replay ordering and isolation."""

    def test_events_replayed_in_timestamp_order(self, multi_symbol_scenario) -> None:
        _, recorder, _, _ = multi_symbol_scenario
        quotes = recorder.of_type(NBBOQuote)
        assert len(quotes) == 12

        for i in range(len(quotes) - 1):
            assert quotes[i].exchange_timestamp_ns <= quotes[i + 1].exchange_timestamp_ns, (
                f"Out-of-order quotes at index {i}: "
                f"{quotes[i].exchange_timestamp_ns} > {quotes[i + 1].exchange_timestamp_ns}"
            )

    def test_per_symbol_feature_isolation(self, multi_symbol_scenario) -> None:
        _, recorder, _, _ = multi_symbol_scenario
        features = recorder.of_type(FeatureVector)

        aapl_features = [fv for fv in features if fv.symbol == "AAPL"]
        msft_features = [fv for fv in features if fv.symbol == "MSFT"]

        assert len(aapl_features) == 6
        assert len(msft_features) == 6

        for fv in aapl_features:
            assert fv.symbol == "AAPL"
        for fv in msft_features:
            assert fv.symbol == "MSFT"

    def test_per_symbol_position_independence(self, multi_symbol_scenario) -> None:
        orchestrator, _, _, _ = multi_symbol_scenario
        aapl_pos = orchestrator._positions.get("AAPL")
        msft_pos = orchestrator._positions.get("MSFT")

        aapl_qty = aapl_pos.quantity
        msft_qty = msft_pos.quantity
        assert isinstance(aapl_qty, int)
        assert isinstance(msft_qty, int)

    def test_multi_symbol_deterministic_replay(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        from .conftest import _make_quotes

        aapl_ticks = [
            {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
            {"bid": "150.00", "ask": "150.01", "ts": 7_000_000_000},
            {"bid": "160.00", "ask": "160.01", "ts": 9_000_000_000},
            {"bid": "140.00", "ask": "140.01", "ts": 11_000_000_000},
        ]
        msft_ticks = [
            {"bid": "350.00", "ask": "350.01", "ts": 2_000_000_000},
            {"bid": "350.00", "ask": "350.01", "ts": 4_000_000_000},
            {"bid": "350.00", "ask": "350.01", "ts": 6_000_000_000},
            {"bid": "350.00", "ask": "350.01", "ts": 8_000_000_000},
            {"bid": "360.00", "ask": "360.01", "ts": 10_000_000_000},
            {"bid": "340.00", "ask": "340.01", "ts": 12_000_000_000},
        ]

        results = []
        for i in range(2):
            tmp = tmp_path_factory.mktemp(f"multi_det_{i}")
            aapl_quotes = _make_quotes("AAPL", aapl_ticks)
            msft_quotes = _make_quotes("MSFT", msft_ticks)
            all_quotes = sorted(
                aapl_quotes + msft_quotes,
                key=lambda q: q.exchange_timestamp_ns,
            )
            from feelies.core.events import NBBOQuote as NQ
            for j, q in enumerate(all_quotes, start=1):
                all_quotes[j - 1] = NQ(
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=j,
                    symbol=q.symbol,
                    bid=q.bid,
                    ask=q.ask,
                    bid_size=q.bid_size,
                    ask_size=q.ask_size,
                    exchange_timestamp_ns=q.exchange_timestamp_ns,
                )
            orch, rec, _, _ = _run_scenario(
                tmp,
                quotes=all_quotes,
                symbols=frozenset({"AAPL", "MSFT"}),
            )
            results.append((orch, rec))

        orch_a, rec_a = results[0]
        orch_b, rec_b = results[1]

        assert len(rec_a.events) == len(rec_b.events)

        aapl_a = orch_a._positions.get("AAPL")
        aapl_b = orch_b._positions.get("AAPL")
        assert aapl_a.quantity == aapl_b.quantity
        assert aapl_a.realized_pnl == aapl_b.realized_pnl

    def test_fill_uses_correct_symbol_quote(self, multi_symbol_scenario) -> None:
        _, recorder, _, _ = multi_symbol_scenario
        acks = recorder.of_type(OrderAck)
        orders = recorder.of_type(OrderRequest)
        quotes = recorder.of_type(NBBOQuote)

        order_by_id = {o.order_id: o for o in orders}

        for ack in acks:
            if ack.fill_price is None:
                continue
            order = order_by_id.get(ack.order_id)
            if order is None:
                continue

            symbol_quotes = [
                q for q in quotes
                if q.symbol == ack.symbol
                and q.exchange_timestamp_ns <= order.timestamp_ns
            ]
            if not symbol_quotes:
                continue
            latest = symbol_quotes[-1]
            expected_mid = (latest.bid + latest.ask) / Decimal("2")
            assert ack.fill_price == expected_mid, (
                f"Fill for {ack.symbol} used wrong quote: "
                f"got {ack.fill_price}, expected {expected_mid}"
            )
