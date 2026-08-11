"""Sequence generators for separate event families must not interact.

Tests cover independent counters and orchestrator wiring. Sharing counters
would shift downstream replay sequences.
"""

from __future__ import annotations

from feelies.core.identifiers import SequenceGenerator


def test_independent_sequence_generators_do_not_interact() -> None:
    main = SequenceGenerator()
    sensor = SequenceGenerator()
    horizon = SequenceGenerator()
    snapshot = SequenceGenerator()

    for _ in range(10):
        main.next()
    for _ in range(3):
        sensor.next()
    for _ in range(5):
        horizon.next()

    assert main.next() == 10
    assert sensor.next() == 3
    assert horizon.next() == 5
    assert snapshot.next() == 0
