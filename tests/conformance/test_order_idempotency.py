"""H2 — exactly-once submission across process restart (G03).

A restart re-derives the same ``order_id``. The durable journal records
which IDs were submitted. H2 kills mid-submission, restarts, and asserts
the broker never sees the id twice.

A page-cached append survives process kill, so restart survival alone
does not prove fsync-per-record. The mode assertion is therefore a
separate check: ``os.fsync`` must run, and ``durability_mode`` must
name fsync-per-record.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.platform_config import ENGINE_LATENCY_BUDGETS
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.monitoring.in_memory import InMemoryKillSwitch
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


def _install_broker_probe(router: PassiveLimitOrderRouter, sink: list[str]) -> None:
    orig_passive = router._post_passive
    orig_mkt = router._submit_aggressive_market

    def passive(request: OrderRequest, quote: NBBOQuote) -> None:
        sink.append(request.order_id)
        orig_passive(request, quote)

    def mkt(request: OrderRequest, quote: NBBOQuote) -> None:
        sink.append(request.order_id)
        orig_mkt(request, quote)

    router._post_passive = passive  # type: ignore[method-assign]
    router._submit_aggressive_market = mkt  # type: ignore[method-assign]


def test_h2_kill_mid_submission_restart_no_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(i) Kill after the durable write, restart, broker sees the id once.

    The fsync spy raises after a successful ``os.fsync``. The broker probe
    is ``_post_passive`` / ``_submit_aggressive_market``: those are the
    simulated wire. An assertion on ``broker`` therefore executed the fill
    path, not a stub.
    """
    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    fsynced: list[int] = []
    real_fsync = os.fsync

    def fsync_then_kill(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)
        raise KeyboardInterrupt("kill mid-submission")

    monkeypatch.setattr(os, "fsync", fsync_then_kill)

    journal = _journal(path, clock)
    broker: list[str] = []
    first = _router(clock, journal)
    _install_broker_probe(first, broker)
    first.on_quote(_quote())
    order = _order("oid-kill")
    with pytest.raises(KeyboardInterrupt, match="kill mid-submission"):
        first.submit(order)
    assert fsynced, (
        "kill-after-fsync never ran: the write was not fsynced, so this "
        "would also pass under buffered append"
    )
    assert broker == [], f"wire ran before the kill: broker={broker!r}"

    recovered = _journal(path, clock)
    second = _router(clock, recovered)
    _install_broker_probe(second, broker)
    second.on_quote(_quote())
    second.submit(order)
    acks = second.poll_acks()
    assert broker == [], (
        f"duplicate reached the broker after restart: {broker!r}; "
        f"acks={[(a.order_id, a.status, a.reason) for a in acks]!r}"
    )
    rejected = [a for a in acks if a.status is OrderAckStatus.REJECTED and "duplicate" in a.reason]
    assert rejected, (
        f"restart did not refuse journaled id; "
        f"acks={[(a.order_id, a.status, a.reason) for a in acks]!r}"
    )


def test_h2_durability_mode_is_fsync_per_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(ii) Durability is fsync-per-record, proven by calling os.fsync.

    Restart survival is not this assertion. A flag without a fsync spy
    would pass under page-cached append. Both checks must fire: the
    mode name, and a non-empty spy list after ``record_attempt``.
    """
    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    journal = _journal(path, clock)
    assert journal.durability_mode == "fsync-per-record", (
        f"durability_mode={journal.durability_mode!r}; H2 must not infer "
        "power-loss safety from a surviving restart"
    )
    fsynced: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    journal.record_attempt("oid-fsync")
    assert fsynced, (
        "record_attempt returned without os.fsync -- the write is page-cached, not power-loss safe"
    )


def test_h2_journal_latency_breach_does_not_activate_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(A) Journal I/O stays on-tick with its own p99 budget; breach != kill.

    statistic=p99, window=100, budget=15 ms. A breach is recorded on the
    journal. It does not activate the kill switch: flatten-on-kill would
    enqueue more per-leg writes on the same slow device.
    """
    entry = next(e for e in ENGINE_LATENCY_BUDGETS if e.engine == "submitted_order_journal_ns")
    assert entry.statistic == "p99"
    assert entry.window_events == 100
    assert entry.budget_ns == 15_000_000

    clock = SimulatedClock(start_ns=0)
    path = tmp_path / "submitted_orders.jsonl"
    journal = _journal(path, clock)
    assert not hasattr(journal, "_kill_switch")
    kill_switch = InMemoryKillSwitch()
    real_fsync = os.fsync

    def slow_fsync(fd: int) -> None:
        real_fsync(fd)
        clock.set_time(clock.now_ns() + 20_000_000)

    monkeypatch.setattr(os, "fsync", slow_fsync)
    for i in range(entry.window_events):
        journal.record_attempt(f"oid-slow-{i}")
    assert journal.latency_breach_count >= 1
    assert not kill_switch.is_active
