"""Constructed tapes F and H for the P-95 attribution diff (D-249)."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import yaml

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Event,
    NBBOQuote,
    OrderAckStatus,
    PositionClosed,
    PositionExtreme,
    Side,
    Signal,
    SignalDirection,
)
from feelies.forensics.exit_attribution import (
    ArmEpisode,
    ArmEvents,
    AttributionReport,
    ClassTotals,
    EpisodeDiff,
    Fill,
    attribute,
)
from tests.position_engine.scenarios import T0, Records, run_synthetic

_NS = 1_000_000_000
_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_STRATEGY = "sig_position_fixture_v1"
_SIGNAL_TS = 1_774_533_720_000_000_000
_SIGNAL_CID = "snap:SYN:120:1774533720000000000:1"
_ENTRY_TS = 1_774_533_721_020_000_000
_ENTRY_PRICE = Decimal("100.01")
_ENTRY_FEE = Decimal("1.18")
_EXIT_FEE = Decimal("1.82")
_QTY = 124
_FAV_TS = 1_774_533_731_020_000_000
_FAV_PRICE = Decimal("100.07")
_HORIZON_TS = 1_774_533_843_020_000_000
_HORIZON_PRICE = Decimal("100.00")
_LEGACY_HASH = "e0f6243f00c4c70bf92205bd092bd5ed7458b1adb86a36f306770d4e627a34a2"
_ENGINE_HASH = "7346811902da264535ff4f6f37bf3e4c5e38313555519f1b7e3f58583fd7035e"
_TAPE_WORST = PositionExtreme(
    cents=-124,
    sequence=123,
    valuation_age_ns=122_000_000_000,
    valuation_side_absent=False,
    crossed=False,
    feed_gap_before=False,
)


def _legacy_variant() -> dict[str, object]:
    loaded = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    spec: dict[str, object] = copy.deepcopy(loaded)
    spec.pop("exit_policy")
    return spec


def _tape(last_s: int, *, jump_at_s: int | None) -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    for i in range(last_s + 1):
        bid_cents = 10_000 + (7 if jump_at_s is not None and i >= jump_at_s else 0)
        ts = T0 + i * _NS
        quotes.append(
            NBBOQuote(
                symbol="SYN",
                bid=Decimal(bid_cents) / 100,
                ask=Decimal(bid_cents + 1) / 100,
                bid_size=1_000,
                ask_size=1_000,
                timestamp_ns=ts,
                exchange_timestamp_ns=ts,
                sequence=i + 1,
                correlation_id=f"q-{i}",
                source_layer="INGESTION",
            )
        )
    return quotes


def _run(
    tape: list[NBBOQuote],
    variant: dict[str, object] | None,
) -> tuple[Records, tuple[Signal, ...]]:
    seen: list[Signal] = []
    original = EventBus.subscribe_all

    def wrapped(self: EventBus, handler: Callable[[Event], None]) -> None:
        def both(event: Event) -> None:
            if type(event) is Signal:
                seen.append(event)
            handler(event)

        original(self, both)

    EventBus.subscribe_all = wrapped  # type: ignore[method-assign]
    try:
        records = run_synthetic(tape, symbols=("SYN",), variant=variant)
    finally:
        EventBus.subscribe_all = original
    return records, tuple(seen)


def _arm(records: Records, signals: tuple[Signal, ...]) -> ArmEvents:
    closed = tuple(item for item in records.sink_closed if isinstance(item, PositionClosed))
    quotes = tuple(records.quotes[key] for key in sorted(records.quotes))
    return ArmEvents(
        signals=signals,
        order_requests=records.order_requests,
        order_acks=records.order_acks,
        risk_verdicts=records.risk_verdicts,
        quotes=quotes,
        position_closed=closed,
    )


def _arms(tape: list[NBBOQuote]) -> tuple[ArmEvents, ArmEvents]:
    legacy_records, legacy_signals = _run(tape, _legacy_variant())
    engine_records, engine_signals = _run(tape, None)
    return _arm(legacy_records, legacy_signals), _arm(engine_records, engine_signals)


def _fills(arm: ArmEvents) -> tuple[tuple[Decimal, int, int, Decimal, int], ...]:
    return tuple(
        (ack.fill_price, ack.filled_quantity, ack.timestamp_ns, ack.fees, ack.sequence)
        for ack in arm.order_acks
        if ack.filled_quantity > 0
        and ack.status in (OrderAckStatus.FILLED, OrderAckStatus.PARTIALLY_FILLED)
        and ack.fill_price is not None
    )


def _check_inputs(
    legacy: ArmEvents,
    engine: ArmEvents,
    *,
    exit_reason: str,
    exit_price: Decimal,
    exit_ts: int,
    last_s: int,
) -> None:
    assert len(legacy.signals) == 1
    assert len(engine.signals) == 1
    left, right = legacy.signals[0], engine.signals[0]
    for item in dataclasses.fields(Signal):
        if item.name == "metadata":
            continue
        assert getattr(left, item.name) == getattr(right, item.name)
    assert dict(left.metadata) == {"manifest_hash": _LEGACY_HASH}
    assert dict(right.metadata) == {"manifest_hash": _ENGINE_HASH}
    assert right.direction is SignalDirection.LONG
    assert right.timestamp_ns == _SIGNAL_TS
    assert right.correlation_id == _SIGNAL_CID
    assert right.sequence == 0
    assert right.symbol == "SYN"
    assert right.strategy_id == _STRATEGY
    assert legacy.quotes[-1].timestamp_ns == T0 + last_s * _NS
    assert legacy.quotes[-1].timestamp_ns < T0 + 360 * _NS
    assert _fills(legacy) == ((_ENTRY_PRICE, _QTY, _ENTRY_TS, _ENTRY_FEE, 1),)
    entry_ack = next(ack for ack in legacy.order_acks if ack.filled_quantity > 0)
    entry_order = next(
        order for order in legacy.order_requests if order.order_id == entry_ack.order_id
    )
    assert entry_order.side is Side.BUY
    assert _fills(engine) == (
        (_ENTRY_PRICE, _QTY, _ENTRY_TS, _ENTRY_FEE, 1),
        (exit_price, _QTY, exit_ts, _EXIT_FEE, 3),
    )
    assert legacy.position_closed == ()
    assert len(engine.position_closed) == 1
    assert engine.position_closed[0].exit_reason == exit_reason
    assert engine.position_closed[0].worst == _TAPE_WORST


def _fill(price: Decimal, ts: int, fee: Decimal, seq: int) -> Fill:
    return Fill(
        fill_price=price,
        filled_quantity=_QTY,
        timestamp_ns=ts,
        fees=fee,
        sequence=seq,
    )


def _expected(
    legacy: ArmEvents,
    engine: ArmEvents,
    *,
    engine_reason: str,
    exit_price: Decimal,
    exit_ts: int,
    engine_holding: int,
    legacy_holding: int,
    engine_net: str,
) -> AttributionReport:
    entry = _fill(_ENTRY_PRICE, _ENTRY_TS, _ENTRY_FEE, 1)
    legacy_episode = ArmEpisode(
        symbol="SYN",
        strategy_id=_STRATEGY,
        entry_signal=legacy.signals[0],
        side="LONG",
        entry_fills=(entry,),
        exit_fills=(),
        net_after_fees=Decimal("-1.18"),
        holding_time_ns=legacy_holding,
    )
    engine_episode = ArmEpisode(
        symbol="SYN",
        strategy_id=_STRATEGY,
        entry_signal=engine.signals[0],
        side="LONG",
        entry_fills=(entry,),
        exit_fills=(_fill(exit_price, exit_ts, _EXIT_FEE, 3),),
        net_after_fees=Decimal(engine_net),
        holding_time_ns=engine_holding,
    )
    diff = EpisodeDiff(
        episode_class="EXIT_CHANGED",
        engine_reason=engine_reason,
        legacy_reason="END_OF_TAPE",
        explanation="",
        legacy=legacy_episode,
        engine=engine_episode,
        legacy_mae=Decimal("0.01"),
        engine_mae=Decimal("0.01"),
        engine_worst=_TAPE_WORST,
    )
    return AttributionReport(
        diffs=(diff,),
        totals=(
            ClassTotals(
                episode_class="EXIT_CHANGED",
                count=1,
                legacy_net=Decimal("-1.18"),
                engine_net=Decimal(engine_net),
            ),
        ),
        day_count=1,
        label="descriptive",
    )


def test_tape_f_favorable_exit_changed() -> None:
    legacy, engine = _arms(_tape(150, jump_at_s=130))
    _check_inputs(
        legacy,
        engine,
        exit_reason="FAVORABLE",
        exit_price=_FAV_PRICE,
        exit_ts=_FAV_TS,
        last_s=150,
    )
    report = attribute(legacy, engine, day_count=1)
    assert report == _expected(
        legacy,
        engine,
        engine_reason="FAVORABLE",
        exit_price=_FAV_PRICE,
        exit_ts=_FAV_TS,
        engine_holding=10_000_000_000,
        legacy_holding=28_980_000_000,
        engine_net="4.44",
    )


def test_tape_h_horizon_exit_changed() -> None:
    legacy, engine = _arms(_tape(300, jump_at_s=None))
    _check_inputs(
        legacy,
        engine,
        exit_reason="HORIZON",
        exit_price=_HORIZON_PRICE,
        exit_ts=_HORIZON_TS,
        last_s=300,
    )
    report = attribute(legacy, engine, day_count=1)
    assert report == _expected(
        legacy,
        engine,
        engine_reason="HORIZON",
        exit_price=_HORIZON_PRICE,
        exit_ts=_HORIZON_TS,
        engine_holding=122_000_000_000,
        legacy_holding=178_980_000_000,
        engine_net="-4.24",
    )
