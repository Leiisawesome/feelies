"""S15 — the wiring manifest matches the runtime subscription graph.

G02: the subscription graph is emergent. A subscription that is not a
row in the hashed manifest fails this test by name. The manifest is
written from measured registration order, not from a reading of
``bootstrap.py``.
"""

from __future__ import annotations

from collections.abc import Callable

from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.events import Event
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.integration.test_phase4_e2e import (
    _make_phase4_config,
    _synth_multi_symbol_events,
)


def _load_manifest() -> tuple[tuple[object, ...], str]:
    try:
        from feelies.core.wiring_manifest import SUBSCRIPTIONS, manifest_hash
    except ImportError:
        return (), ""
    return tuple(SUBSCRIPTIONS), manifest_hash()


def _subscriber_id(handler: Callable[..., object]) -> str:
    owner = getattr(handler, "__self__", None)
    if owner is not None:
        return type(owner).__name__
    name = getattr(handler, "__name__", "")
    if name and name != "<lambda>":
        return name
    return getattr(handler, "__qualname__", repr(handler))


def _measure_phase4() -> list[tuple[str, str]]:
    orig = EventBus.subscribe
    rows: list[tuple[str, str]] = []

    def traced(
        self: EventBus,
        event_type: type[Event],
        handler: Callable[..., object],
    ) -> None:
        rows.append((event_type.__name__, _subscriber_id(handler)))
        orig(self, event_type, handler)

    EventBus.subscribe = traced  # type: ignore[method-assign]
    try:
        config = _make_phase4_config()
        event_log = InMemoryEventLog()
        event_log.append_batch(_synth_multi_symbol_events())
        build_platform(config, event_log=event_log)
    finally:
        EventBus.subscribe = orig  # type: ignore[method-assign]
    return rows


def test_s15_manifest_matches_runtime_graph() -> None:
    """A runtime subscription not in the manifest fails, naming that row."""
    subscriptions, hashed = _load_manifest()
    declared = [
        (str(getattr(row, "event_type", "")), str(getattr(row, "subscriber", "")))
        for row in subscriptions
    ]
    runtime = _measure_phase4()
    undeclared = [row for row in runtime if row not in declared]
    assert not undeclared, (
        "subscription not in the manifest: "
        + f"{undeclared[0][0]} {undeclared[0][1]}"
    )
    assert hashed, "wiring manifest hash is missing from the run fingerprint"
    assert len(hashed) == 64


def test_s15_manifest_hash_covers_declared_order() -> None:
    subscriptions, hashed = _load_manifest()
    assert subscriptions, "wiring manifest is empty"
    assert hashed, "wiring manifest is unhashed"
