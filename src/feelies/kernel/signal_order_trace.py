"""Per-signal diagnostics for the standalone SIGNAL → order pipeline.

Used when operators need an explicit audit trail of why each bus-emitted
:class:`~feelies.core.events.Signal` did or did not produce an
:class:`~feelies.core.events.OrderRequest` on its quote tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence
from zoneinfo import ZoneInfo

__all__ = [
    "SignalOrderTraceRow",
    "format_trace_table",
    "print_signal_order_trace",
]

_TZ_ET = ZoneInfo("America/New_York")
_TRACE_SECTION = "\n  [SIGNAL → ORDER TRACE]"


@dataclass(frozen=True, slots=True)
class SignalOrderTraceRow:
    """One row per :class:`~feelies.core.events.Signal` evaluated on a quote."""

    quote_timestamp_ns: int
    quote_correlation_id: str
    quote_sequence: int
    signal_sequence: int
    signal_timestamp_ns: int
    strategy_id: str
    symbol: str
    signal_direction: str
    trading_intent: str
    outcome: Literal["ORDER_SUBMITTED", "NO_ORDER"]
    reasons: tuple[str, ...]


def _signal_ts_iso_et(ns: int) -> str:
    return datetime.fromtimestamp(
        ns / 1e9,
        tz=_TZ_ET,
    ).strftime("%Y-%m-%d %H:%M:%S.%f ET")


def format_trace_table(rows: Sequence[SignalOrderTraceRow]) -> str:
    """Return a human-readable audit table for SIGNAL → OrderRequest outcomes."""
    lines: list[str] = [_TRACE_SECTION]
    if not rows:
        lines.extend(
            [
                "    (empty — enable with --trace-signal-orders; bus Signals "
                "that never reached the orchestrator filter are not listed)",
                "",
            ]
        )
        return "\n".join(lines)

    w = 118
    lines.extend(
        [
            (
                f"    {'#':>4}  {'alpha (strategy_id)':^28}  "
                f"{'signal_timestamp_et':^27}  {'intent':^22}  {'outcome':^16}"
            ),
            f"    {'-' * w}",
        ]
    )
    for i, row in enumerate(rows, 1):
        reasons = " | ".join(row.reasons)
        ts_s = _signal_ts_iso_et(row.signal_timestamp_ns)
        lines.extend(
            [
                (
                    f"    {i:4d}  {row.strategy_id:28s}  {ts_s:27s}  "
                    f"{row.trading_intent:22s}  {row.outcome:16s}"
                ),
                (
                    f"          symbol={row.symbol}  signal_dir={row.signal_direction}  "
                    f"sig_seq={row.signal_sequence}  "
                    f"quote_ts={_signal_ts_iso_et(row.quote_timestamp_ns)}"
                ),
                f"          reasons: {reasons}",
            ]
        )
    lines.extend([f"    {'-' * w}", f"    Total rows: {len(rows)}", ""])
    return "\n".join(lines)


def print_signal_order_trace(rows: Sequence[SignalOrderTraceRow]) -> None:
    """Print ``format_trace_table`` to stdout."""
    print(format_trace_table(rows), flush=True)
