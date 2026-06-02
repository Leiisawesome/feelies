"""Tests for signal → order trace formatting."""

from __future__ import annotations

from feelies.kernel.signal_order_trace import (
    SignalOrderTraceRow,
    format_trace_table,
)


def _sample_row(
    *,
    outcome: SignalOrderTraceRow["outcome"] = "NO_ORDER",
) -> SignalOrderTraceRow:
    return SignalOrderTraceRow(
        quote_timestamp_ns=1_704_000_000_000_000_000,
        quote_correlation_id="q:1",
        quote_sequence=10,
        signal_sequence=5,
        signal_timestamp_ns=1_704_000_000_100_000_000,
        strategy_id="sig_benign_midcap_v1",
        symbol="APP",
        signal_direction="LONG",
        trading_intent="ENTRY_LONG",
        outcome=outcome,
        reasons=("signal_edge_below_min_edge_cost_ratio_gate",),
    )


def test_format_trace_table_empty() -> None:
    text = format_trace_table([])
    assert "[SIGNAL → ORDER TRACE]" in text
    assert "--trace-signal-orders" in text


def test_format_trace_table_row_details() -> None:
    text = format_trace_table([_sample_row()])
    assert "sig_benign_midcap_v1" in text
    assert "signal_edge_below_min_edge_cost_ratio_gate" in text
    assert "Total rows: 1" in text
    assert "ENTRY_LONG" in text


def test_format_trace_table_order_submitted_outcome() -> None:
    text = format_trace_table([_sample_row(outcome="ORDER_SUBMITTED")])
    assert "ORDER_SUBMITTED" in text
