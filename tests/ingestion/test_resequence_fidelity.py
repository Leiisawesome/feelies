"""Multi-symbol resequence fidelity tests (G2 — runs in CI without massive SDK).

Exercises the same invariants as ``test_parallel_ingest_integration.py``'s
``TestMultiDayCacheResequence`` and ``TestResequencing``, but with
hand-synthesized events instead of a live Massive API client.  The
network-backed integration tests are valuable but skip in CI when the
``massive`` SDK is absent; these tests keep the multi-symbol global
ordering invariant under test on every run.

Invariants under test (multi-symbol global ordering contract):

  1. Canonical sort key ``(exchange_timestamp_ns, symbol, type_rank,
     sequence)`` produces a strictly-monotonic key after merge.
  2. Quotes precede trades at equal ``(timestamp, symbol)``.
  3. ``InMemoryEventLog.append_batch`` enforces the same order
     invariant on the write side that ``ReplayFeed`` enforces on the
     read side.

Each test fabricates events that would *fail* a naive concatenation
sort and asserts that ``resequence_event_list`` produces the canonical
order.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.errors import CausalityViolation
from feelies.core.events import NBBOQuote, Trade
from feelies.storage.event_resequence import (
    event_merge_sort_key,
    resequence_event_list,
)
from feelies.storage.memory_event_log import InMemoryEventLog


def _q(ts_ns: int, symbol: str, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"{symbol}:{ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("100.00"),
        ask=Decimal("100.01"),
        bid_size=10,
        ask_size=10,
        exchange_timestamp_ns=ts_ns,
    )


def _t(ts_ns: int, symbol: str, seq: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"{symbol}:{ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        price=Decimal("100.005"),
        size=50,
        exchange_timestamp_ns=ts_ns,
    )


class TestResequenceMonotonic:
    """Resequenced output is strictly monotonic under the canonical key."""

    def test_two_symbols_interleaved_become_chronological(self) -> None:
        aapl = [_q(1000, "AAPL", 0), _q(3000, "AAPL", 1), _q(5000, "AAPL", 2)]
        msft = [_q(2000, "MSFT", 0), _q(4000, "MSFT", 1)]

        # Naively concatenating AAPL then MSFT puts MSFT timestamps after AAPL
        # — a deliberate worst case for the sort.
        merged = resequence_event_list(aapl + msft)

        keys = [event_merge_sort_key(e) for e in merged]
        assert keys == sorted(keys)
        # And the keys are strictly monotonic (no duplicates).
        assert len(set(keys)) == len(keys)

    def test_two_days_overlapping_sequences_become_unique(self) -> None:
        # Two days of independent normalizer runs produce overlapping
        # internal sequences (each starts from 0).  Global resequence
        # must yield contiguous unique sequences across both days.
        day1 = [_q(1000, "AAPL", 0), _q(2000, "AAPL", 1)]
        day2 = [_q(3000, "AAPL", 0), _q(4000, "AAPL", 1)]
        assert {e.sequence for e in day1} & {e.sequence for e in day2}

        merged = resequence_event_list(day1 + day2)
        seqs = [e.sequence for e in merged]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    def test_quote_precedes_trade_at_equal_timestamp(self) -> None:
        # B5 / event_merge_sort_key: type_rank breaks ties so quotes
        # appear before trades at the same (timestamp, symbol).
        same_ts_quote = _q(1000, "AAPL", 0)
        same_ts_trade = _t(1000, "AAPL", 99)
        merged = resequence_event_list([same_ts_trade, same_ts_quote])
        assert isinstance(merged[0], NBBOQuote)
        assert isinstance(merged[1], Trade)

    def test_resequence_rebuilds_correlation_ids(self) -> None:
        # Documented in event_resequence.py: correlation_id is reassigned
        # so that the deterministic replay path produces stable ids
        # regardless of upstream live ordering.
        events = [_q(1000, "AAPL", 99), _q(2000, "MSFT", 17)]
        out = resequence_event_list(events)
        for e in out:
            assert e.correlation_id.endswith(f":{e.sequence}")


class TestInMemoryEventLogOrderInvariant:
    """``append_batch`` / ``append`` both enforce the merge-sort invariant."""

    def test_append_batch_rejects_backwards_market_event(self) -> None:
        log = InMemoryEventLog()
        log.append_batch([_q(2000, "AAPL", 0)])
        with pytest.raises(CausalityViolation):
            log.append_batch([_q(1000, "AAPL", 1)])  # backwards timestamp

    def test_append_batch_stabilizes_intra_batch_order(self) -> None:
        # The market subset of a batch is re-sorted in place by
        # event_merge_sort_key (memory_event_log._stabilize_market_slice),
        # so locally-out-of-order quotes inside one batch are accepted
        # and end up canonicalized.
        log = InMemoryEventLog()
        log.append_batch(
            [
                _q(2000, "AAPL", 1),
                _q(1000, "AAPL", 0),  # earlier than the prior row in the same batch
            ]
        )
        replayed = list(log.replay())
        assert [e.timestamp_ns for e in replayed] == [1000, 2000]

    def test_replace_events_resets_watermark(self) -> None:
        # After ``replace_events``, the prior watermark is cleared so a
        # legitimate-but-earlier batch can be installed (ingest path).
        log = InMemoryEventLog()
        log.append_batch([_q(5000, "AAPL", 0)])
        log.replace_events([_q(1000, "AAPL", 0), _q(2000, "MSFT", 1)])
        replayed = list(log.replay())
        assert [e.timestamp_ns for e in replayed] == [1000, 2000]
