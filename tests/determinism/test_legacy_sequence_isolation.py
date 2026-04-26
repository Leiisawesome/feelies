"""Inv-A / C1 — sequence-generator isolation between event families.

Phase-2 introduces three new sequence generators on the orchestrator
(``_sensor_seq``, ``_horizon_seq``, ``_snapshot_seq``) that must be
*completely* isolated from the legacy ``_seq`` generator (Inv-A).
Without isolation, registering even a single sensor would shift the
sequence numbers of every legacy event downstream — the exact failure
mode that would cause Level-1 hash drift.

These tests assert isolation at two levels:

1.  **Independent counters** — each generator advances independently
    and starts at zero, regardless of how often any other one is
    called.
2.  **Orchestrator wiring** — when an orchestrator is constructed
    with explicit generators (or defaults), advancing the sensor
    counter does not advance the legacy counter and vice versa.
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
        orch._seq, orch._sensor_seq, orch._horizon_seq, orch._snapshot_seq,
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
