"""Gateway-free coverage of nextValidId high-water vs the durable journal.

``tests/broker/ib/test_ib_functional.py`` skips without a reachable IB
Gateway, so the S-08 nextValidId persist path had no automated coverage.
These tests call ``nextValidId(orderId)`` directly with a fake journal.

Each test names the guard it owns. A test that still passes after that
guard is removed is not testing the guard.
"""

from __future__ import annotations

from feelies.broker.ib.connection import IBGatewayConnection
from feelies.core.clock import SimulatedClock


class _FakeJournal:
    """Duck-typed submitted-order journal: recovered id + write-back log."""

    def __init__(self, recovered: int | None) -> None:
        self._recovered = recovered
        self.written: list[int] = []

    def recovered_ib_next_valid_id(self) -> int | None:
        return self._recovered

    def record_ib_next_valid_id(self, value: int) -> None:
        self.written.append(value)


def _conn() -> IBGatewayConnection:
    return IBGatewayConnection(
        host="127.0.0.1",
        port=4002,
        client_id=1,
        clock=SimulatedClock(start_ns=0),
    )


def test_next_valid_id_journal_absent() -> None:
    """Guard: ``if journal is not None`` before reading persisted.

    Removing it calls ``None.recovered_ib_next_valid_id`` and this fails.
    """
    conn = _conn()
    conn.nextValidId(100)
    assert conn.next_order_id() == 100


def test_next_valid_id_recovered_none() -> None:
    """Guard: ``if persisted is not None`` before ``max(incoming, persisted)``.

    Unguarded ``max(orderId, None)`` raises TypeError on a fresh journal.
    Journal is attached without bind() so this path is nextValidId, not bind.
    """
    conn = _conn()
    conn._submitted_order_journal = _FakeJournal(None)
    conn.nextValidId(100)
    assert conn.next_order_id() == 100


def test_next_valid_id_persisted_below_incoming() -> None:
    """Guard: ``incoming = max(incoming, persisted)`` — incoming must win.

    Replacing max with ``persisted`` yields 50 here.
    Journal is attached without bind() so bind cannot pre-seed the counter.
    """
    conn = _conn()
    conn._submitted_order_journal = _FakeJournal(50)
    conn.nextValidId(100)
    assert conn.next_order_id() == 100


def test_next_valid_id_persisted_above_incoming() -> None:
    """Guard: ``incoming = max(incoming, persisted)`` — persisted must win.

    Replacing max with ``incoming`` yields 50 here.
    Journal is attached without bind() so bind cannot pre-seed the counter.
    """
    conn = _conn()
    conn._submitted_order_journal = _FakeJournal(200)
    conn.nextValidId(50)
    assert conn.next_order_id() == 200


def test_next_valid_id_reconnect_does_not_regress() -> None:
    """Docstring at connection.py:371-373: never regress the local counter.

    Replacing ``max(self._next_valid_id, incoming)`` with ``incoming``
    makes the second handshake reuse 50.
    """
    conn = _conn()
    conn._submitted_order_journal = _FakeJournal(None)
    conn.nextValidId(100)
    assert conn.next_order_id() == 100
    assert conn.next_order_id() == 101
    conn.nextValidId(50)
    assert conn.next_order_id() == 102


def test_bind_before_handshake_takes_persisted() -> None:
    """Bind while ``_next_valid_id is None``: take persisted, write back.

    Skipping the ``_next_valid_id is None`` assignment leaves the counter
    unset and ``next_order_id`` raises.
    """
    conn = _conn()
    journal = _FakeJournal(200)
    conn.bind_submitted_order_journal(journal)
    assert conn.next_order_id() == 200
    assert journal.written == [200]


def test_bind_after_handshake_takes_max_and_writes_back() -> None:
    """Bind after handshake: max(current, persisted), then write back.

    Dropping max in favour of current fails the above-persisted half.
    Dropping max in favour of persisted fails the below-persisted half.
    Skipping write-back leaves ``written`` empty.
    """
    below = _conn()
    below.nextValidId(100)
    journal_below = _FakeJournal(50)
    below.bind_submitted_order_journal(journal_below)
    assert below.next_order_id() == 100
    assert journal_below.written[-1] == 100

    above = _conn()
    above.nextValidId(100)
    journal_above = _FakeJournal(200)
    above.bind_submitted_order_journal(journal_above)
    assert above.next_order_id() == 200
    assert journal_above.written[-1] == 200
