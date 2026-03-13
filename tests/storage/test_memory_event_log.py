"""Unit tests for InMemoryEventLog."""

from __future__ import annotations

import pytest

from feelies.storage.memory_event_log import InMemoryEventLog

from tests.storage.conftest import make_quote, make_trade


class TestInMemoryEventLog:
    """Tests for InMemoryEventLog implementation of EventLog protocol."""

    def test_empty_log_last_sequence_is_minus_one(self) -> None:
        log = InMemoryEventLog()
        assert log.last_sequence() == -1

    def test_append_single_event(self) -> None:
        log = InMemoryEventLog()
        q = make_quote(seq=0)
        log.append(q)
        assert len(log) == 1
        assert log.last_sequence() == 0

    def test_append_batch(self) -> None:
        log = InMemoryEventLog()
        events = [make_quote(seq=i) for i in range(3)]
        log.append_batch(events)
        assert len(log) == 3
        assert log.last_sequence() == 2

    def test_replay_yields_all_in_order(self) -> None:
        log = InMemoryEventLog()
        log.append(make_quote(seq=0))
        log.append(make_trade(seq=1))
        log.append(make_quote(seq=2))

        replayed = list(log.replay())
        assert len(replayed) == 3
        assert replayed[0].sequence == 0
        assert replayed[1].sequence == 1
        assert replayed[2].sequence == 2

    def test_replay_respects_start_sequence(self) -> None:
        log = InMemoryEventLog()
        for i in range(5):
            log.append(make_quote(seq=i))

        replayed = list(log.replay(start_sequence=2))
        assert len(replayed) == 3
        assert replayed[0].sequence == 2
        assert replayed[-1].sequence == 4

    def test_replay_respects_end_sequence(self) -> None:
        log = InMemoryEventLog()
        for i in range(5):
            log.append(make_quote(seq=i))

        replayed = list(log.replay(end_sequence=2))
        assert len(replayed) == 3
        assert replayed[0].sequence == 0
        assert replayed[-1].sequence == 2

    def test_replay_respects_range(self) -> None:
        log = InMemoryEventLog()
        for i in range(10):
            log.append(make_quote(seq=i))

        replayed = list(log.replay(start_sequence=2, end_sequence=5))
        assert len(replayed) == 4
        assert [e.sequence for e in replayed] == [2, 3, 4, 5]

    def test_append_and_append_batch_combined(self) -> None:
        log = InMemoryEventLog()
        log.append(make_quote(seq=0))
        log.append_batch([make_quote(seq=1), make_quote(seq=2)])
        log.append(make_trade(seq=3))

        replayed = list(log.replay())
        assert len(replayed) == 4
        assert log.last_sequence() == 3
