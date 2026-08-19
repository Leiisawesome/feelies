"""X11 — restart recovery of journaled attempts (G03 reject asymmetry).

The journal records submission ATTEMPTS, not in-memory occupancy. A
reject releases the in-memory id and appends a reject outcome; it does
not delete the attempt. Recovery must therefore distinguish:

* journaled and rejected -- safe to re-derive (re-submittable);
* journaled, outcome unknown -- refuse.

Recording only post-wire confirmations would contradict write-before-wire.
The replay re-opens the same file and asserts the same refusal decisions,
because the durable path is otherwise exercised only by H2 and never by
the parity oracle.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.storage.submitted_order_journal import DurableSubmittedOrderJournal


def _quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_000,
        correlation_id="q",
        sequence=1,
        symbol="APP",
        bid=Decimal("100"),
        ask=Decimal("101"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=1_000,
    )


def _order(order_id: str) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2_000,
        correlation_id="o",
        sequence=2,
        order_id=order_id,
        symbol="APP",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        limit_price=Decimal("99"),
    )


def _journal(path: Path, clock: SimulatedClock) -> DurableSubmittedOrderJournal:
    return DurableSubmittedOrderJournal(path, clock=clock)


def _router(
    clock: SimulatedClock, journal: DurableSubmittedOrderJournal
) -> PassiveLimitOrderRouter:
    return PassiveLimitOrderRouter(clock, submitted_order_journal=journal)


def test_x11_journaled_rejected_is_resubmittable(tmp_path: Path) -> None:
    """(iii) An id journaled and then REJECTED is re-submittable after restart.

    Submit with no quote so the router rejects after the attempt is
    journaled. Recovery must report REJECTED, not UNKNOWN, and a new
    router must reach the wire (ACKNOWLEDGED), not a duplicate refuse.
    Without the journal this would pass vacuously: a fresh in-memory set
    re-submits everything, rejected or not.
    """
    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    journal = _journal(path, clock)
    first = _router(clock, journal)
    order = _order("oid-rejected")
    first.submit(order)
    acks = first.poll_acks()
    assert any(a.status is OrderAckStatus.REJECTED for a in acks), (
        f"pre-restart reject did not fire; acks={[(a.status, a.reason) for a in acks]!r}"
    )
    assert journal.decision(order.order_id).name == "REJECTED", (
        f"journal did not record the reject outcome; decision={journal.decision(order.order_id)!r}"
    )

    recovered = _journal(path, clock)
    assert recovered.decision(order.order_id).name == "REJECTED", (
        "restart recovered UNKNOWN for a journaled-then-rejected id -- "
        "that bricks the router after its first rejected order"
    )
    second = _router(clock, recovered)
    second.on_quote(_quote())
    second.submit(order)
    acks2 = second.poll_acks()
    assert any(a.status is OrderAckStatus.ACKNOWLEDGED for a in acks2), (
        f"journaled-then-rejected id was not re-submittable; "
        f"acks={[(a.status, a.reason) for a in acks2]!r}"
    )
    assert not any(
        a.status is OrderAckStatus.REJECTED and "duplicate" in a.reason for a in acks2
    ), f"rejected id was permanently refused; acks={[(a.status, a.reason) for a in acks2]!r}"


def test_x11_journaled_unknown_is_refused(tmp_path: Path) -> None:
    """(iv) An id journaled with outcome unknown is refused on restart.

    ``record_attempt`` without ``record_reject`` is the crash-between-journal-
    and-ack case. Recovery must refuse; a re-submit must not reach the
    wire. This is the complement of (iii): if both passed with the same
    predicate, the asymmetry would be untested.
    """
    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    journal = _journal(path, clock)
    journal.record_attempt("oid-unknown")
    assert journal.decision("oid-unknown").name == "UNKNOWN"

    recovered = _journal(path, clock)
    assert recovered.decision("oid-unknown").name == "UNKNOWN"
    assert recovered.must_refuse("oid-unknown")

    second = _router(clock, recovered)
    second.on_quote(_quote())
    second.submit(_order("oid-unknown"))
    acks = second.poll_acks()
    assert any(a.status is OrderAckStatus.REJECTED and "duplicate" in a.reason for a in acks), (
        f"journaled-unknown id was not refused; acks={[(a.status, a.reason) for a in acks]!r}"
    )
    assert not any(a.status is OrderAckStatus.ACKNOWLEDGED for a in acks), (
        f"journaled-unknown id reached the wire; acks={[(a.status, a.reason) for a in acks]!r}"
    )


def test_x11_journal_backed_replay_same_refusals(tmp_path: Path) -> None:
    """Replay a journal-backed session: refusal decisions are identical.

    The durable path is otherwise exercised only by H2 and never by the
    oracle. This replay is the countermeasure: a second journal instance
    on the same file must reproduce the first session's UNKNOWN/REJECTED
    map, and a third router walking the same ids must refuse exactly the
    UNKNOWN set.
    """
    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    journal = _journal(path, clock)
    live = _router(clock, journal)
    live.submit(_order("oid-rej"))
    live.poll_acks()
    journal.record_attempt("oid-unk-a")
    journal.record_attempt("oid-unk-b")
    expected = {oid: journal.decision(oid).name for oid in ("oid-rej", "oid-unk-a", "oid-unk-b")}
    assert expected == {
        "oid-rej": "REJECTED",
        "oid-unk-a": "UNKNOWN",
        "oid-unk-b": "UNKNOWN",
    }

    replayed = _journal(path, clock)
    recovered = {oid: replayed.decision(oid).name for oid in ("oid-rej", "oid-unk-a", "oid-unk-b")}
    assert recovered == expected, f"journal-backed replay diverged: {recovered!r} != {expected!r}"

    third = _router(clock, replayed)
    third.on_quote(_quote())
    refusals: dict[str, bool] = {}
    for oid in ("oid-rej", "oid-unk-a", "oid-unk-b"):
        third.submit(_order(oid))
        acks = third.poll_acks()
        refusals[oid] = any(
            a.status is OrderAckStatus.REJECTED and "duplicate" in a.reason for a in acks
        )
    assert refusals == {
        "oid-rej": False,
        "oid-unk-a": True,
        "oid-unk-b": True,
    }, f"replayed refusals {refusals!r} do not match journal decisions {expected!r}"
