"""What ``compute_parity_hash`` must notice, and what it deliberately ignores.

Both halves are asserted. A parity hash is only as good as the set of fields it
covers, and that set is invisible: nothing about a green parity check tells you
which changes it was capable of seeing. ``strategy_id`` was missing until
``5c37879``; ``fees`` and ``cost_bps`` were missing until this file existed.

The exclusions are pinned too, so narrowing the hash is as loud as widening it.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from feelies.core.events import Side
from feelies.harness.backtest_report import compute_parity_hash
from feelies.storage.trade_journal import TradeRecord

_BASE = TradeRecord(
    order_id="o1",
    symbol="AAPL",
    strategy_id="sig_a_v1",
    side=Side.SELL,
    requested_quantity=100,
    filled_quantity=100,
    fill_price=Decimal("150.00"),
    signal_timestamp_ns=1,
    submit_timestamp_ns=2,
    fill_timestamp_ns=3,
    cost_bps=Decimal("2.0"),
    fees=Decimal("1.00"),
    realized_pnl=Decimal("500.00"),
    correlation_id="c1",
)


def _hash(record: TradeRecord) -> str:
    return compute_parity_hash(
        SimpleNamespace(trade_journal=SimpleNamespace(query=lambda: [record]))
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Economics.
        ("filled_quantity", 99),
        ("fill_price", Decimal("151.00")),
        ("realized_pnl", Decimal("400.00")),
        # Money the gross realized figure does not carry. The position store keeps
        # cumulative_fees separately, so without this a fee schedule could change
        # from 1.00 to 99.00 a fill and two runs with different net profitability
        # would still be declared at parity (Inv-9, Inv-12).
        ("fees", Decimal("99.00")),
        # The realized cost the B4 gate and the cost circuit breaker read to
        # quarantine an alpha — a capital decision, so a parity check that cannot
        # see it is not checking parity of anything that matters.
        ("cost_bps", Decimal("250.0")),
        # Which alpha a fill is booked to: the sole input to every per-alpha
        # estimator behind the promotion gates.
        ("strategy_id", "sig_b_v1"),
        ("symbol", "MSFT"),
        ("side", Side.BUY),
        ("order_id", "o2"),
    ],
)
def test_hash_moves_when_an_economic_field_changes(field: str, value: object) -> None:
    assert _hash(replace(_BASE, **{field: value})) != _hash(_BASE), (
        f"changing {field} left the parity hash unmoved — two runs differing in "
        f"{field} would be declared identical"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Plumbing: hashing these would make parity sensitive to clock and id
        # wiring rather than to economics.
        ("signal_timestamp_ns", 10_000),
        ("submit_timestamp_ns", 10_001),
        ("fill_timestamp_ns", 10_002),
        ("correlation_id", "c2"),
        # Derived provenance: the economics each annotates is already hashed
        # through the fill itself.
        ("requested_quantity", 5000),
        ("trading_intent", "EXIT"),
        ("regime_state", "toxic"),
        ("metadata", {"forced_exit_strategy_id": "sig_b_v1"}),
    ],
)
def test_hash_ignores_the_fields_it_is_meant_to_ignore(field: str, value: object) -> None:
    """Pinned so narrowing the hash is as visible as widening it.

    A failure here is not automatically a bug — it means someone added a field to
    the sequence. Decide whether it belongs by the standard in
    ``compute_parity_hash``: does it move a capital decision on its own? If yes,
    move the case to the test above and say why in the docstring.
    """
    assert _hash(replace(_BASE, **{field: value})) == _hash(_BASE)


def test_hash_is_order_sensitive() -> None:
    """The sequence is ordered: the same fills in a different order are not parity."""
    a = replace(_BASE, order_id="a")
    b = replace(_BASE, order_id="b", fill_price=Decimal("151.00"))

    def two(first: TradeRecord, second: TradeRecord) -> str:
        return compute_parity_hash(
            SimpleNamespace(trade_journal=SimpleNamespace(query=lambda: [first, second]))
        )

    assert two(a, b) != two(b, a)
