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


def test_orchestrator_constructs_default_generators_when_none_provided() -> None:
    """Smoke: orchestrator creates fresh, independent generators by default.

    We do not boot the orchestrator (which would drag in alphas /
    backend / etc.) — we only inspect the four generator slots after
    construction with the minimum mandatory arguments.
    """
    from unittest.mock import MagicMock

    from feelies.kernel.orchestrator import Orchestrator

    orch = Orchestrator(
        clock=MagicMock(),
        bus=MagicMock(),
        backend=MagicMock(),
        risk_engine=MagicMock(),
        position_store=MagicMock(),
        event_log=MagicMock(),
        metric_collector=MagicMock(),
        alert_manager=MagicMock(),
        kill_switch=MagicMock(),
    )
    seqs = (
        orch._seq,
        orch._sensor_seq,
        orch._horizon_seq,
        orch._snapshot_seq,
    )
    assert all(isinstance(s, SequenceGenerator) for s in seqs)
    assert len({id(s) for s in seqs}) == 4

    orch._seq.next()
    orch._seq.next()
    orch._sensor_seq.next()
    assert orch._sensor_seq.next() == 1
    assert orch._horizon_seq.next() == 0
    assert orch._snapshot_seq.next() == 0
    assert orch._seq.next() == 2
