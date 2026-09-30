"""Age and deadline use the trade's visible time, not its exchange stamp."""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    DeRiskRequirement,
    SafetyStateChange,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.deferral_cap import DeferralCapController, DeferralPolicy
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy

_LAT_NS = 20_000_000
_SECOND = 1_000_000_000
_SYMBOL = "AAPL"
_STRATEGY = "alpha_a"


def _trade(timestamp_ns: int) -> Trade:
    return Trade(
        timestamp_ns=timestamp_ns,
        correlation_id=f"t-{timestamp_ns}",
        sequence=1,
        symbol=_SYMBOL,
        price=Decimal("100"),
        size=10,
        exchange_timestamp_ns=timestamp_ns,
    )


def test_hazard_age_uses_visible_time() -> None:
    """A trade 20 ms before the cap, measured at exchange time, is at the cap when visible."""
    bus = EventBus()
    store = MemoryPositionStore()
    store.update(_SYMBOL, 10, Decimal("100"), timestamp_ns=0)
    received: list[DeRiskRequirement] = []
    bus.subscribe(DeRiskRequirement, received.append)  # type: ignore[arg-type]
    controller = HazardExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(start=1, stream="hazard_exit"),
        position_store=store,
        market_data_latency_ns=_LAT_NS,
        policies={
            _STRATEGY: HazardPolicy(
                strategy_id=_STRATEGY,
                hazard_score_threshold=0.5,
                min_age_seconds=0,
                hard_exit_age_seconds=1,
                universe=(_SYMBOL,),
            )
        },
    )
    controller.attach()
    bus.publish(_trade(_SECOND - _LAT_NS - 1))
    assert received == []
    bus.publish(_trade(_SECOND - _LAT_NS))
    assert len(received) == 1
    assert received[0].reason == "HARD_EXIT_AGE"


def test_deferral_deadline_uses_visible_time() -> None:
    """The deferral deadline compares the same visible time."""
    bus = EventBus()
    store = StrategyPositionStore()
    store.update(_STRATEGY, _SYMBOL, 10, Decimal("100"), timestamp_ns=0)
    received: list[DeRiskRequirement] = []
    bus.subscribe(DeRiskRequirement, received.append)  # type: ignore[arg-type]
    controller = DeferralCapController(
        bus=bus,
        sequence_generator=SequenceGenerator(start=1, stream="deferral_cap"),
        position_store=store,
        market_data_latency_ns=_LAT_NS,
        session_flatten_enabled=False,
        policies={
            _STRATEGY: DeferralPolicy(
                strategy_id=_STRATEGY,
                max_hold_after_safe_off_seconds=10,
                hard_exit_age_seconds=1,
                universe=(_SYMBOL,),
            )
        },
    )
    controller.attach()
    bus.publish(
        SafetyStateChange(
            timestamp_ns=0,
            correlation_id="off",
            sequence=1,
            symbol=_SYMBOL,
            strategy_id=_STRATEGY,
            safe=False,
            reason="clean_transition",
        )
    )
    bus.publish(_trade(_SECOND - _LAT_NS - 1))
    assert received == []
    bus.publish(_trade(_SECOND - _LAT_NS))
    assert len(received) == 1
    assert received[0].reason == "HARD_EXIT_AGE"
