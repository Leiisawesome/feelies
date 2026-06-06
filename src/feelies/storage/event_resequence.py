"""Deterministic ordering for merged NBBO + trade streams (Inv-5 / Inv-6).

Multi-symbol ingestion concatenates per-symbol batches; callers merge-sort by
exchange time before inserting into :class:`~feelies.storage.memory_event_log.InMemoryEventLog`.

Python's ``list.sort`` is stable, but a sort key that ties only on
``exchange_timestamp_ns`` leaves symbol order dependent on concatenation order.
The canonical tie-breaker is:

``(exchange_timestamp_ns, symbol, event_type_rank, prior_sequence)``

where quotes sort before trades at equal timestamps and ``prior_sequence`` is the
sequence carried on the event before reassignment (preserves intra-batch order).

**Live vs replay note:** This pass assigns fresh contiguous ``sequence`` and
``correlation_id`` values for deterministic replay. Those identifiers are not
expected to match an incremental live ingest of the same vendor events unless
live applies an identical merge/resequence policy.
"""

from __future__ import annotations

from dataclasses import replace

from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id

_TYPE_RANK = (NBBOQuote, Trade)


def event_merge_sort_key(
    event: NBBOQuote | Trade,
) -> tuple[int, str, int, int]:
    """Deterministic sort key for merged quote/trade lists."""
    type_rank = _TYPE_RANK.index(type(event))
    return (
        event.exchange_timestamp_ns,
        event.symbol,
        type_rank,
        event.sequence,
    )


def resequence_event_list(
    events: list[NBBOQuote | Trade],
) -> list[NBBOQuote | Trade]:
    """Sort by :func:`event_merge_sort_key` and assign contiguous sequences.

    Does not mutate ``events``; callers may retain their original list order.
    """
    sorted_events = sorted(events, key=event_merge_sort_key)
    seq = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in sorted_events:
        new_seq = seq.next()
        new_cid = make_correlation_id(
            event.symbol, event.exchange_timestamp_ns, new_seq,
        )
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result
