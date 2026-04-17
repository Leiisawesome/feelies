"""PnL/provenance audit, two-phase risk enforcement, latency injection e2e.

Skills: post-trade-forensics, risk-engine, live-execution, backtest-engine
Invariants: 13 (provenance), 12 (cost realism)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    RiskAction,
    RiskVerdict,
)
from feelies.storage.trade_journal import TradeRecord

from .conftest import BusRecorder

pytestmark = pytest.mark.backtest_validation


class TestPositionReconciliation:
    """Position delta matches fill quantities."""

    def test_position_delta_matches_fill_quantity(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, recorder, _, _ = single_symbol_scenario
        acks = recorder.of_type(OrderAck)
        orders = recorder.of_type(OrderRequest)
        order_by_id = {o.order_id: o for o in orders}

        from feelies.core.events import Side

        net_delta = 0
        for ack in acks:
            if ack.fill_price is None or ack.filled_quantity <= 0:
                continue
            order = order_by_id.get(ack.order_id)
            if order is None:
                continue
            signed = ack.filled_quantity if order.side == Side.BUY else -ack.filled_quantity
            net_delta += signed

        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity == net_delta

    def test_realized_pnl_matches_trade_journal(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, _, _, _ = single_symbol_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        journal_pnl = sum(r.realized_pnl for r in records)
        position_pnl = orchestrator._positions.get("AAPL").realized_pnl
        assert journal_pnl == position_pnl


class TestTradeRecordIntegrity:
    """Every TradeRecord has required fields and causal timestamps."""

    def test_trade_record_has_all_required_fields(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, _, _, _ = single_symbol_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        assert len(records) > 0

        for rec in records:
            assert rec.order_id, "order_id is empty"
            assert rec.symbol, "symbol is empty"
            assert rec.strategy_id, "strategy_id is empty"
            assert rec.correlation_id, "correlation_id is empty"
            assert rec.fill_price is not None and rec.fill_price > 0

    def test_trade_record_timestamps_causal(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, _, _, _ = single_symbol_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))

        for rec in records:
            assert rec.signal_timestamp_ns <= rec.submit_timestamp_ns, (
                f"Signal ts {rec.signal_timestamp_ns} > submit ts {rec.submit_timestamp_ns}"
            )
            if rec.fill_timestamp_ns is not None:
                assert rec.submit_timestamp_ns <= rec.fill_timestamp_ns, (
                    f"Submit ts {rec.submit_timestamp_ns} > fill ts {rec.fill_timestamp_ns}"
                )


class TestOrderRequestAckParity:
    """Every submitted OrderRequest reaches a terminal ack, and every ack
    traces back to a submitted order.

    An order may produce multiple acks (ACKNOWLEDGED, PARTIALLY_FILLED,
    FILLED, etc.) so the invariant is a set-equality on order_ids, not a
    count parity."""

    def test_every_order_has_at_least_one_terminal_ack(
        self, single_symbol_scenario
    ) -> None:
        _, recorder, _, _ = single_symbol_scenario
        orders = recorder.of_type(OrderRequest)
        acks = recorder.of_type(OrderAck)
        terminal = {
            OrderAckStatus.FILLED,
            OrderAckStatus.CANCELLED,
            OrderAckStatus.REJECTED,
            OrderAckStatus.EXPIRED,
        }
        terminal_order_ids = {a.order_id for a in acks if a.status in terminal}
        for order in orders:
            assert order.order_id in terminal_order_ids, (
                f"Order {order.order_id} has no terminal ack"
            )

    def test_no_orphaned_fills(self, single_symbol_scenario) -> None:
        orchestrator, recorder, _, _ = single_symbol_scenario
        orders = recorder.of_type(OrderRequest)
        acks = recorder.of_type(OrderAck)
        order_ids = {o.order_id for o in orders}

        for ack in acks:
            assert ack.order_id in order_ids, (
                f"Orphaned fill: order_id={ack.order_id} not in submitted orders"
            )


class TestFeesAndSlippage:
    """Fees and slippage invariants."""

    def test_fees_and_slippage_non_negative(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, _, _, _ = single_symbol_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        for rec in records:
            assert rec.fees >= 0, f"Negative fees: {rec.fees}"
            assert rec.cost_bps >= 0, f"Negative cost_bps: {rec.cost_bps}"

    def test_pnl_decomposition_sums_correctly(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, _, _, _ = single_symbol_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        total_journal_pnl = sum(r.realized_pnl for r in records)
        portfolio_pnl = orchestrator._positions.get("AAPL").realized_pnl
        assert total_journal_pnl == portfolio_pnl


class TestTwoPhaseRiskEnforcement:
    """Hotspot 8 — both check_signal AND check_order fire for every order."""

    def test_both_risk_checks_fire_for_every_order(
        self, single_symbol_scenario
    ) -> None:
        _, recorder, _, _ = single_symbol_scenario
        orders = recorder.of_type(OrderRequest)
        verdicts = recorder.of_type(RiskVerdict)

        if not orders:
            return

        order_cids = {o.correlation_id for o in orders}

        for cid in order_cids:
            cid_verdicts = [v for v in verdicts if v.correlation_id == cid]
            assert len(cid_verdicts) >= 2, (
                f"Expected at least 2 RiskVerdicts (check_signal + check_order) "
                f"for correlation_id={cid}, got {len(cid_verdicts)}"
            )


class TestLatencyInjection:
    """Hotspot 5 — latency injection e2e propagation."""

    def test_latency_injection_propagates_to_fill_ts(
        self, latency_injection_scenario
    ) -> None:
        orchestrator, recorder, _, _ = latency_injection_scenario
        acks = recorder.of_type(OrderAck)
        orders = recorder.of_type(OrderRequest)

        if not acks:
            return

        order_by_id = {o.order_id: o for o in orders}
        for ack in acks:
            if ack.fill_price is None:
                continue
            order = order_by_id.get(ack.order_id)
            if order is None:
                continue
            assert ack.timestamp_ns == order.timestamp_ns + 5000, (
                f"Fill ts {ack.timestamp_ns} != "
                f"submit ts {order.timestamp_ns} + 5000"
            )

    def test_latency_injection_causal_fill_after_submit(
        self, latency_injection_scenario
    ) -> None:
        orchestrator, _, _, _ = latency_injection_scenario
        records = list(orchestrator._trade_journal.query(symbol="AAPL"))

        for rec in records:
            if rec.fill_timestamp_ns is not None:
                assert rec.fill_timestamp_ns > rec.submit_timestamp_ns, (
                    f"Fill ts {rec.fill_timestamp_ns} should be strictly "
                    f"after submit ts {rec.submit_timestamp_ns} with latency > 0"
                )
