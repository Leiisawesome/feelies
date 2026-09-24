"""P-10 contract surface: event types, wiring, streams, and dark stubs.

Replay fixture: ``tests/fixtures/event_logs/synth_5min_aapl.jsonl`` (first 24
records; the rest of the five-minute tape is the same generator).
"""

from __future__ import annotations

import json
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.errors import ConfigurationError
from feelies.core.events import (
    Event,
    ExitTriggeredPath,
    GateDecision,
    MarkRailUpdate,
    NBBOQuote,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    PositionSnapshot,
    RailOrientation,
    SlicePositionUpdate,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.sequence_authority import STREAM_AUTHORITIES
from feelies.core.wiring_manifest import SUBSCRIPTIONS
from feelies.portfolio.mark_rail import MarkRail
from feelies.position.engine import PositionEngine, PositionRecordSink
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_null_alpha_conservation import _NULL_ALPHA
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_FIXTURE = Path("tests/fixtures/event_logs/synth_5min_aapl.jsonl")
_NEW_EVENTS = (
    "MarkRailUpdate",
    "SlicePositionUpdate",
    "PositionSnapshot",
    "GateDecision",
    "PositionClosed",
)
_RAIL_FIELDS = (
    "paying_mark_cents",
    "valuation_mark_cents",
    "worst_side_mark_cents",
    "forced_exit_mark_cents",
    "dwelled_exit_mark_cents",
    "paying_size",
    "valuation_size",
    "paying_age_ns",
    "valuation_age_ns",
    "paying_absent_for_ns",
    "valuation_absent_for_ns",
    "paying_side_absent",
    "valuation_side_absent",
    "dwell_window_clean",
)
_EXTREME_FIELDS = (
    "cents",
    "sequence",
    "valuation_age_ns",
    "valuation_side_absent",
    "crossed",
    "feed_gap_before",
)
_FILL_LEG_FIELDS = ("price_cents", "quantity", "timestamp_ns", "sequence")
_EXIT_PATH_FIELDS = ("path", "proposed_price_cents", "trigger")
_MARK_RAIL_FIELDS = (
    "symbol",
    "quote_sequence",
    "event_timestamp_ns",
    "long",
    "short",
    "symbol_quiet_ns",
    "locked",
    "crossed",
    "feed_gap_before",
    "warmed_up",
)
_SLICE_FIELDS = (
    "symbol",
    "strategy_id",
    "order_id",
    "fill_price",
    "fill_quantity",
    "fill_ack_sequence",
    "fill_timestamp_ns",
    "quantity",
    "avg_entry_price",
)
_SNAPSHOT_FIELDS = (
    "cell_id",
    "symbol",
    "strategy_id",
    "state",
    "side",
    "declared_archetype",
    "rail_sequence",
    "size",
    "entry_cost_cents",
    "entry_spread_ticks",
    "horizon_deadline_ns",
    "move_now_cents",
    "move_worst_cents",
    "move_forced_cents",
    "best",
    "worst",
    "best_clean",
    "rail",
    "symbol_quiet_ns",
    "locked",
    "crossed",
    "feed_gap_before",
    "warmed_up",
)
_GATE_FIELDS = (
    "cell_id",
    "rail_sequence",
    "gate",
    "outcome",
    "reason",
    "form",
    "proposed_price_cents",
    "reference_ticks",
    "reference_sequence",
    "drawn_level_ticks",
)
_CLOSED_FIELDS = (
    "cell_id",
    "symbol",
    "strategy_id",
    "side",
    "declared_archetype",
    "entry_fills",
    "exit_fills",
    "entry_spread_ticks",
    "horizon_deadline_ns",
    "drawn_level_ticks",
    "exit_reason",
    "triggered_paths",
    "proposed_price_cents",
    "best",
    "worst",
    "best_clean",
    "closed_on_stale_data",
    "exited_on_unusable_data",
    "lived_through_feed_gap",
    "first_event_exit",
    "stop_inside_round_trip",
    "target_inside_round_trip",
    "uncalibrated",
    "supersedes",
)
_NEW_ROWS = (
    (36, "MarkRailUpdate", "PositionEngine", "_on_mark_rail"),
    (37, "SlicePositionUpdate", "PositionEngine", "_on_slice_update"),
    (38, "PositionSnapshot", "PositionRecordSink", "_on_snapshot"),
    (39, "GateDecision", "PositionRecordSink", "_on_gate_decision"),
    (40, "PositionClosed", "PositionRecordSink", "_on_closed"),
)
_NEW_STREAMS = (
    ("mark_rail", "MarkRail", ("MarkRailUpdate",)),
    ("slice_position", "Orchestrator", ("SlicePositionUpdate",)),
    ("position", "PositionEngine", ("PositionSnapshot", "GateDecision", "PositionClosed")),
)


def _payload(cls: type) -> tuple[str, ...]:
    skip = set(Event.__dataclass_fields__) if issubclass(cls, Event) else set()
    return tuple(f.name for f in fields(cls) if f.name not in skip)


def _load_fixture(limit: int = 24) -> list[NBBOQuote | Trade]:
    events: list[NBBOQuote | Trade] = []
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.pop("kind")
        if kind == "NBBOQuote":
            row["bid"] = Decimal(row["bid"])
            row["ask"] = Decimal(row["ask"])
            events.append(NBBOQuote(**row))
        elif kind == "Trade":
            row["price"] = Decimal(row["price"])
            events.append(Trade(**row))
        if len(events) >= limit:
            break
    return events


def _config(mode: object = OperatingMode.BACKTEST) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=mode,  # type: ignore[arg-type]
        alpha_specs=[_NULL_ALPHA],
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=SESSION_OPEN_NS,
    )


def _replay(*, enable: bool | None = None) -> tuple[object, list[Event]]:
    log = InMemoryEventLog()
    log.append_batch(_load_fixture())
    kwargs: dict[str, object] = {}
    if enable is not None:
        kwargs["enable_position_engine"] = enable
    orchestrator, resolved = build_platform(_config(), event_log=log, **kwargs)  # type: ignore[arg-type]
    seen: list[Event] = []
    orchestrator._bus.subscribe_all(seen.append)
    orchestrator.boot(resolved)
    orchestrator.run_backtest()
    return orchestrator, seen


def test_t1_event_field_tuples() -> None:
    assert _payload(RailOrientation) == _RAIL_FIELDS
    assert _payload(PositionExtreme) == _EXTREME_FIELDS
    assert _payload(PositionFillLeg) == _FILL_LEG_FIELDS
    assert _payload(ExitTriggeredPath) == _EXIT_PATH_FIELDS
    assert _payload(MarkRailUpdate) == _MARK_RAIL_FIELDS
    assert _payload(SlicePositionUpdate) == _SLICE_FIELDS
    assert _payload(PositionSnapshot) == _SNAPSHOT_FIELDS
    assert _payload(GateDecision) == _GATE_FIELDS
    assert _payload(PositionClosed) == _CLOSED_FIELDS


def test_t2_wiring_streams_and_independence() -> None:
    rows = tuple(
        (row.ordinal, row.event_type, row.subscriber, row.method) for row in SUBSCRIPTIONS
    )
    for expected in _NEW_ROWS:
        assert expected in rows, expected
    streams = tuple((row.stream, row.authority, row.contracts) for row in STREAM_AUTHORITIES)
    for expected in _NEW_STREAMS:
        assert expected in streams, expected
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "Engine module sets"' in text
    assert '"feelies.position"' in text


def test_t3_enabled_backtest_emits_rail_and_slice_and_attaches_sink() -> None:
    writes: list[tuple[str, str]] = []
    from feelies.portfolio.strategy_position_store import StrategyPositionStore

    original = StrategyPositionStore.update

    def _counted(
        self: StrategyPositionStore,
        strategy_id: str,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
        timestamp_ns: int | None = None,
    ) -> object:
        result = original(
            self,
            strategy_id,
            symbol,
            quantity_delta,
            fill_price,
            fees=fees,
            timestamp_ns=timestamp_ns,
        )
        writes.append((strategy_id, symbol))
        return result

    StrategyPositionStore.update = _counted  # type: ignore[method-assign]
    try:
        orchestrator, seen = _replay(enable=True)
    finally:
        StrategyPositionStore.update = original  # type: ignore[method-assign]

    quotes = [e for e in seen if isinstance(e, NBBOQuote)]
    rails = [e for e in seen if isinstance(e, MarkRailUpdate)]
    slices = [e for e in seen if isinstance(e, SlicePositionUpdate)]
    assert quotes, "fixture replay published no quotes"
    assert len(rails) == len(quotes)
    assert [r.quote_sequence for r in rails] == [q.sequence for q in quotes]
    assert len(slices) == len(writes)
    sink_handlers = [
        handler
        for handler in orchestrator._bus._handlers.get(PositionSnapshot, ())
        if type(getattr(handler, "__self__", None)) is PositionRecordSink
    ]
    assert sink_handlers, "PositionRecordSink is not attached"
    sink = sink_handlers[0].__self__
    assert sink.snapshots == []
    assert sink.gate_decisions == []
    assert sink.closed == []


def test_t4_default_is_dark() -> None:
    constructed: list[str] = []
    originals = (
        (MarkRail, MarkRail.__init__),
        (PositionEngine, PositionEngine.__init__),
        (PositionRecordSink, PositionRecordSink.__init__),
    )

    def _spy(label: str, original: object) -> object:
        def _init(self: object, *args: object, **kwargs: object) -> None:
            constructed.append(label)
            original(self, *args, **kwargs)  # type: ignore[operator]

        return _init

    for cls, original in originals:
        cls.__init__ = _spy(cls.__name__, original)  # type: ignore[method-assign]
    try:
        _orchestrator, seen = _replay(enable=None)
    finally:
        for cls, original in originals:
            cls.__init__ = original  # type: ignore[method-assign]
    assert constructed == []
    published = {type(event).__name__ for event in seen}
    assert published.isdisjoint(_NEW_EVENTS)


@pytest.mark.parametrize("mode_name", ["PAPER", "LIVE"])
def test_t5_non_backtest_refuses_before_attach(mode_name: str) -> None:
    if mode_name == "PAPER":
        mode: object = OperatingMode.PAPER
    else:
        mode = type("LiveMode", (), {"name": "LIVE"})()
    constructed: list[str] = []
    from feelies.bus.event_bus import EventBus

    original_bus = EventBus.__init__
    original_mark = MarkRail.__init__
    original_engine = PositionEngine.__init__
    original_sink = PositionRecordSink.__init__

    def _bus(self: object, *args: object, **kwargs: object) -> None:
        constructed.append("EventBus")
        original_bus(self, *args, **kwargs)  # type: ignore[arg-type]

    def _mark(self: object, *args: object, **kwargs: object) -> None:
        constructed.append("MarkRail")
        original_mark(self, *args, **kwargs)  # type: ignore[arg-type]

    def _engine(self: object, *args: object, **kwargs: object) -> None:
        constructed.append("PositionEngine")
        original_engine(self, *args, **kwargs)  # type: ignore[arg-type]

    def _sink(self: object, *args: object, **kwargs: object) -> None:
        constructed.append("PositionRecordSink")
        original_sink(self, *args, **kwargs)  # type: ignore[arg-type]

    EventBus.__init__ = _bus  # type: ignore[method-assign]
    MarkRail.__init__ = _mark  # type: ignore[method-assign]
    PositionEngine.__init__ = _engine  # type: ignore[method-assign]
    PositionRecordSink.__init__ = _sink  # type: ignore[method-assign]
    try:
        with pytest.raises(ConfigurationError):
            build_platform(_config(mode), enable_position_engine=True)
    finally:
        EventBus.__init__ = original_bus  # type: ignore[method-assign]
        MarkRail.__init__ = original_mark  # type: ignore[method-assign]
        PositionEngine.__init__ = original_engine  # type: ignore[method-assign]
        PositionRecordSink.__init__ = original_sink  # type: ignore[method-assign]
    assert constructed == []


def _quote(
    *,
    symbol: str = "AAPL",
    bid: str,
    ask: str,
    sequence: int,
    exchange_timestamp_ns: int,
    bid_size: int = 100,
    ask_size: int = 200,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_timestamp_ns,
        correlation_id=f"t6-{sequence}",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=exchange_timestamp_ns,
    )


def test_t6_mark_rail_stub() -> None:
    rail = MarkRail(SequenceGenerator(stream="mark_rail", thread_safe=False))
    first = rail.on_quote(
        _quote(bid="10.00", ask="10.02", sequence=1, exchange_timestamp_ns=1_000)
    )
    assert first.symbol_quiet_ns == 0
    assert first.warmed_up is False
    assert first.locked is False
    assert first.crossed is False
    assert first.feed_gap_before is False
    assert first.long.paying_mark_cents == 1002
    assert first.long.valuation_mark_cents == 1000
    assert first.long.worst_side_mark_cents == 1000
    assert first.long.forced_exit_mark_cents == 1000
    assert first.long.dwelled_exit_mark_cents == 1000
    assert first.long.paying_size == 200
    assert first.long.valuation_size == 100
    assert first.long.paying_age_ns == 0
    assert first.long.valuation_age_ns == 0
    assert first.long.paying_absent_for_ns == 0
    assert first.long.valuation_absent_for_ns == 0
    assert first.long.dwell_window_clean is False
    assert first.short.paying_mark_cents == 1000
    assert first.short.valuation_mark_cents == 1002
    assert first.short.worst_side_mark_cents == 1002
    assert first.short.forced_exit_mark_cents == 1002
    assert first.short.dwelled_exit_mark_cents == 1002
    assert first.short.paying_size == 100
    assert first.short.valuation_size == 200
    assert first.short.dwell_window_clean is False

    second = rail.on_quote(
        _quote(bid="10.01", ask="10.01", sequence=2, exchange_timestamp_ns=1_500)
    )
    assert second.locked is True
    assert second.crossed is False
    assert second.symbol_quiet_ns == 500
    assert second.warmed_up is False
    assert second.long.dwell_window_clean is False
    assert second.long.paying_mark_cents == 1001
    assert second.long.valuation_mark_cents == 1001
    assert second.short.worst_side_mark_cents == 1001

    crossed = rail.on_quote(
        _quote(bid="10.05", ask="10.01", sequence=3, exchange_timestamp_ns=2_000)
    )
    assert crossed.crossed is True
    assert crossed.locked is False
    assert crossed.long.paying_mark_cents == 1001
    assert crossed.long.valuation_mark_cents == 1005
    assert crossed.long.worst_side_mark_cents == min(1005, 1001)
    assert crossed.short.paying_mark_cents == 1005
    assert crossed.short.valuation_mark_cents == 1001
    assert crossed.short.worst_side_mark_cents == max(1005, 1001)
    assert crossed.long.forced_exit_mark_cents == crossed.long.worst_side_mark_cents
    assert crossed.short.dwelled_exit_mark_cents == crossed.short.valuation_mark_cents

    with pytest.raises(ValueError, match="ZZZ"):
        rail.on_quote(
            _quote(
                symbol="ZZZ",
                bid="10.001",
                ask="10.02",
                sequence=4,
                exchange_timestamp_ns=3_000,
            )
        )


def test_t7_enabled_subscriptions_are_declared_and_present() -> None:
    """Enabled BACKTEST build: runtime subscriptions are a subset of SUBSCRIPTIONS.

    Reuses S15's EventBus.subscribe trace (``_measure_phase4``). The five
    position rows must be present; an undeclared pair fails naming that event.
    """
    import tests.conformance.test_wiring_manifest as s15

    original = s15.build_platform

    def _enabled(config: object, event_log: object = None, **kwargs: object) -> object:
        kwargs["enable_position_engine"] = True
        return original(config, event_log=event_log, **kwargs)  # type: ignore[operator]

    s15.build_platform = _enabled  # type: ignore[method-assign]
    try:
        runtime = s15._measure_phase4()
    finally:
        s15.build_platform = original  # type: ignore[method-assign]

    declared = [(row.event_type, row.subscriber) for row in SUBSCRIPTIONS]
    undeclared = [row for row in runtime if row not in declared]
    assert not undeclared, (
        "subscription not in the manifest: " + f"{undeclared[0][0]} {undeclared[0][1]}"
    )
    for event_type, subscriber in (
        (event_type, subscriber) for _ordinal, event_type, subscriber, _method in _NEW_ROWS
    ):
        assert (event_type, subscriber) in runtime, event_type
