"""Single-writer discipline guard (audit kernel-P1 2026-07-02, gap-test #4).

The 2026-06-24 kernel audit found (and fixed) a Signal echo: the
orchestrator re-published the bus-arbitrated standalone-SIGNAL winner that
``HorizonSignalEngine`` had already published, so every subscriber
(``UniverseSynchronizer``, forensics) saw the same ``Signal`` twice. Nothing
mechanical caught it — only manual audit did. The fix restricted the
re-publish to synthetic forced-exit signals only
(``orchestrator.py:_process_tick_inner``), but no test asserts the
*invariant* the fix restores, so a future regression that re-broadens the
re-publish condition (or introduces an analogous echo on any other event
type) would again pass the entire test suite silently.

This module closes that gap generically: it subscribes a ``subscribe_all``
recorder to a full ``build_platform`` + ``run_backtest`` run and asserts no
two captured events share both a type and a ``sequence`` value. Two
distinct event *types* legitimately sharing a numeric sequence is expected
and fine (several kernel-owned types share the orchestrator's single
``_seq`` generator by design — see the kernel audit's "shared `_seq`"
finding); the same *type* publishing the same sequence twice is not, and is
exactly the echo bug's signature (the re-published object was the identical
``Signal``, so both publishes carried its original sequence).
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import Alert, AlertSeverity, Event, HorizonTick
from feelies.core.platform_config import PlatformConfig
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.determinism.test_orchestrator_replay import (
    _STOP_EXIT_ENTRY_PRICE,
    _STOP_EXIT_ENTRY_QTY,
    _STOP_EXIT_SYMBOL,
    _make_stop_exit_config,
    _synth_stop_exit_events,
)
from tests.integration.test_phase4_e2e import _make_phase4_config, _synth_multi_symbol_events


def _boot_and_record(
    config: PlatformConfig, events: list[object]
) -> tuple[Orchestrator, list[Event]]:
    event_log = InMemoryEventLog()
    event_log.append_batch(events)
    orchestrator, _ = build_platform(config, event_log=event_log)
    captured: list[Event] = []
    orchestrator._bus.subscribe_all(captured.append)
    orchestrator.boot(config)
    return orchestrator, captured


def _assert_no_duplicate_type_sequence_pairs(events: list[Event]) -> None:
    seen_by_key: dict[tuple[str, int], Event] = {}
    duplicates: list[tuple[Event, Event]] = []
    for event in events:
        key = (type(event).__name__, event.sequence)
        prior = seen_by_key.get(key)
        if prior is not None:
            duplicates.append((prior, event))
        else:
            seen_by_key[key] = event
    assert not duplicates, (
        "Duplicate (event_type, sequence) pairs observed on the bus — a "
        "second writer republished an already-sequenced event (the exact "
        "signature of the 2026-06-24 Signal-echo bug):\n"
        + "\n".join(f"  {a!r}\n    == {b!r}" for a, b in duplicates)
    )


def _grouped_by_type(events: list[Event]) -> dict[str, list[Event]]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        grouped[type(event).__name__].append(event)
    return grouped


def test_phase4_fixture_has_no_duplicate_event_sequence_pairs() -> None:
    config = _make_phase4_config()
    orchestrator, captured = _boot_and_record(config, _synth_multi_symbol_events())
    orchestrator.run_backtest()
    _assert_no_duplicate_type_sequence_pairs(captured)


def test_stop_exit_fixture_has_no_duplicate_event_sequence_pairs() -> None:
    config = _make_stop_exit_config()
    orchestrator, captured = _boot_and_record(config, _synth_stop_exit_events())
    orchestrator._positions.update(
        _STOP_EXIT_SYMBOL,
        _STOP_EXIT_ENTRY_QTY,
        _STOP_EXIT_ENTRY_PRICE,
    )
    orchestrator.run_backtest()
    _assert_no_duplicate_type_sequence_pairs(captured)


def _alert(sequence: int) -> Alert:
    return Alert(
        timestamp_ns=0,
        correlation_id="",
        sequence=sequence,
        severity=AlertSeverity.INFO,
        layer="test",
        alert_name="synthetic",
        message="synthetic",
    )


def _horizon_tick(sequence: int) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=0,
        correlation_id="",
        sequence=sequence,
        horizon_seconds=30,
        boundary_index=0,
        session_id="test",
        scope="UNIVERSE",
    )


def test_duplicate_same_type_sequence_pair_is_detected() -> None:
    # Proves the assertion helper has teeth: the same event type publishing
    # the same sequence twice (the echo bug's exact signature) must fail.
    events: list[Event] = [_alert(1), _alert(2), _alert(1)]
    with pytest.raises(AssertionError, match="Duplicate"):
        _assert_no_duplicate_type_sequence_pairs(events)


def test_same_sequence_across_different_types_is_not_a_false_positive() -> None:
    # Two different event types sharing a numeric sequence is expected and
    # fine (several kernel-owned types share the orchestrator's single
    # ``_seq`` generator by design) — must not be flagged.
    events: list[Event] = [_alert(1), _horizon_tick(1)]
    _assert_no_duplicate_type_sequence_pairs(events)  # must not raise


def test_signal_sequence_never_repeats_across_standalone_and_forced_exit_paths() -> None:
    # Direct guard for the exact invariant the 06-24 fix restores: the
    # standalone-SIGNAL path (HorizonSignalEngine, the sole writer of alpha
    # Signals) and the synthetic forced-exit path (orchestrator, disjoint
    # strategy_id namespace) must never both publish the same Signal.
    config = _make_stop_exit_config()
    orchestrator, captured = _boot_and_record(config, _synth_stop_exit_events())
    orchestrator._positions.update(
        _STOP_EXIT_SYMBOL,
        _STOP_EXIT_ENTRY_QTY,
        _STOP_EXIT_ENTRY_PRICE,
    )
    orchestrator.run_backtest()
    signal_sequences = [e.sequence for e in _grouped_by_type(captured)["Signal"]]
    assert signal_sequences, "expected at least one Signal (the synthetic stop-exit)"
    assert len(signal_sequences) == len(set(signal_sequences)), (
        f"Signal.sequence repeated across captured events: {signal_sequences}"
    )
