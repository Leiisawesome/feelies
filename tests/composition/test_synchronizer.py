"""Tests for :class:`feelies.composition.synchronizer.UniverseSynchronizer`."""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.core.events import (
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    Signal,
    SignalDirection,
)
from feelies.core.identifiers import SequenceGenerator


def _make_signal(
    *,
    symbol: str,
    ts_ns: int,
    horizon: int = 300,
    strategy_id: str = "alpha_a",
    strength: float = 1.0,
    edge_bps: float = 5.0,
) -> Signal:
    return Signal(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"sig:{symbol}",
        source_layer="SIGNAL",
        symbol=symbol,
        strategy_id=strategy_id,
        direction=SignalDirection.LONG,
        strength=strength,
        edge_estimate_bps=edge_bps,
        layer="SIGNAL",
        horizon_seconds=horizon,
    )


def _make_snapshot(*, symbol: str, ts_ns: int, bi: int, horizon: int = 300):
    return HorizonFeatureSnapshot(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"snap:{symbol}:{bi}",
        source_layer="L2",
        symbol=symbol,
        horizon_seconds=horizon,
        boundary_index=bi,
    )


def _make_tick(*, ts_ns: int, bi: int, horizon: int = 300) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id=f"tick:{horizon}:{bi}",
        source_layer="SCHEDULER",
        horizon_seconds=horizon,
        boundary_index=bi,
        session_id="TEST_SESSION",
        scope="UNIVERSE",
        symbol=None,
    )


def test_emits_one_context_per_universe_tick():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL", "MSFT"),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_snapshot(symbol="MSFT", ts_ns=1_100, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    bus.publish(_make_signal(symbol="MSFT", ts_ns=1_100))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.horizon_seconds == 300
    assert ctx.boundary_index == 1
    assert ctx.universe == ("AAPL", "MSFT")
    assert ctx.completeness == 1.0
    assert all(s is not None for s in ctx.signals_by_symbol.values())


def test_emits_degenerate_context_when_signals_missing():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL", "MSFT", "TSLA"),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.completeness == 1 / 3
    assert ctx.signals_by_symbol["AAPL"] is not None
    assert ctx.signals_by_symbol["MSFT"] is None
    assert ctx.signals_by_symbol["TSLA"] is None


def test_idempotent_per_boundary():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=1_000, bi=1))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    tick = _make_tick(ts_ns=2_000, bi=1)
    bus.publish(tick)
    bus.publish(tick)
    bus.publish(tick)

    assert len(captured) == 1


def test_attach_is_noop_for_empty_universe():
    bus = EventBus()
    sync = UniverseSynchronizer(
        bus=bus,
        universe=(),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()
    bus.publish(_make_tick(ts_ns=2_000, bi=1))
    # No subscription installed → no event raised.


def test_fan_in_cross_horizon_feeders_into_portfolio_context():
    """30s feeder ``Signal`` events must surface under the 300s barrier."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
        signal_horizons=(30, 300),
        upstream_strategy_ids=("fast_feeder", "slow_feeder"),
    )
    sync.attach()

    boundary_ts = 10_000_000_000
    bi = 3
    bus.publish(
        _make_snapshot(
            symbol="AAPL",
            ts_ns=boundary_ts - 500,
            bi=bi,
            horizon=300,
        )
    )
    bus.publish(
        _make_signal(
            symbol="AAPL",
            ts_ns=boundary_ts - 400,
            horizon=30,
            strategy_id="fast_feeder",
            strength=0.5,
            edge_bps=4.0,
        )
    )
    bus.publish(
        _make_signal(
            symbol="AAPL",
            ts_ns=boundary_ts - 100,
            horizon=300,
            strategy_id="slow_feeder",
            strength=1.0,
            edge_bps=6.0,
        )
    )
    bus.publish(_make_tick(ts_ns=boundary_ts, bi=bi, horizon=300))

    assert len(captured) == 1
    ctx = captured[0]
    row = ctx.signals_by_strategy_by_symbol["AAPL"]
    assert row["fast_feeder"] is not None
    assert row["fast_feeder"].horizon_seconds == 30
    assert row["slow_feeder"] is not None
    assert row["slow_feeder"].horizon_seconds == 300
    assert ctx.signals_by_symbol["AAPL"] == row["fast_feeder"]


def test_stale_signal_dropped_from_completeness_legacy():
    """A signal older than the horizon window must not count (audit P0-5)."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL", "MSFT"),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    tick_ts = 1_000_000_000 + 301 * 1_000_000_000  # AAPL signal is 301s old
    # AAPL: stale (age 301s > 300s window) → dropped.
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000_000_000))
    # MSFT: fresh (≈1ms old) → counts.
    bus.publish(_make_signal(symbol="MSFT", ts_ns=tick_ts - 1_000_000))
    bus.publish(_make_tick(ts_ns=tick_ts, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.signals_by_symbol["AAPL"] is None
    assert ctx.signals_by_symbol["MSFT"] is not None
    assert ctx.completeness == 0.5


def test_explicit_max_age_override_drops_signal():
    """A configured window narrower than the horizon still applies (P0-5)."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
        signal_max_age_seconds=60,
    )
    sync.attach()

    # 120s old: within the 300s horizon but beyond the explicit 60s window.
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000_000_000))
    bus.publish(_make_tick(ts_ns=1_000_000_000 + 120 * 1_000_000_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.signals_by_symbol["AAPL"] is None
    assert ctx.completeness == 0.0


def test_stale_feeder_dropped_multi_feeder():
    """The stale gate also applies on the multi-feeder fan-in path (P0-5)."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
        signal_horizons=(300,),
        upstream_strategy_ids=("alpha_a",),
    )
    sync.attach()

    tick_ts = 1_000_000_000 + 301 * 1_000_000_000
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000_000_000, strategy_id="alpha_a"))
    bus.publish(_make_tick(ts_ns=tick_ts, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    assert ctx.signals_by_strategy_by_symbol["AAPL"]["alpha_a"] is None
    assert ctx.signals_by_symbol["AAPL"] is None
    assert ctx.completeness == 0.0


def test_future_signal_not_captured_legacy():
    """A future-dated signal must never be selected (Inv-6 fail-safe, P1-5)."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    # A causal signal (t=1000), then a FUTURE signal (t=10000) for the same
    # (horizon, symbol, strategy) arrives before the barrier.  The cache keeps
    # the latest timestamp, so the future signal overwrites the causal one;
    # the causality filter then drops the future signal at selection.
    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=10_000))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    sig = ctx.signals_by_symbol["AAPL"]
    # No look-ahead: a future-dated signal is never surfaced.
    assert sig is None or sig.timestamp_ns <= 2_000
    # Fail-safe: the future signal does not inflate completeness.
    assert ctx.completeness == 0.0


def test_future_signal_not_captured_multi_feeder():
    """Same causality guard on the multi-feeder fan-in path (Inv-6, P1-5)."""
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300,),
        ctx_sequence_generator=SequenceGenerator(),
        signal_horizons=(300,),
        upstream_strategy_ids=("alpha_a",),
    )
    sync.attach()

    bus.publish(_make_signal(symbol="AAPL", ts_ns=1_000, strategy_id="alpha_a"))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=10_000, strategy_id="alpha_a"))
    bus.publish(_make_tick(ts_ns=2_000, bi=1))

    assert len(captured) == 1
    ctx = captured[0]
    chosen = ctx.signals_by_strategy_by_symbol["AAPL"]["alpha_a"]
    assert chosen is None or chosen.timestamp_ns <= 2_000
    assert ctx.completeness == 0.0


def test_separate_horizons_independent():
    bus = EventBus()
    captured: list[CrossSectionalContext] = []
    bus.subscribe(CrossSectionalContext, lambda e: captured.append(e))

    sync = UniverseSynchronizer(
        bus=bus,
        universe=("AAPL",),
        horizons=(300, 900),
        ctx_sequence_generator=SequenceGenerator(),
    )
    sync.attach()

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=100, bi=1, horizon=300))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=100, horizon=300))
    bus.publish(_make_tick(ts_ns=200, bi=1, horizon=300))

    bus.publish(_make_snapshot(symbol="AAPL", ts_ns=300, bi=1, horizon=900))
    bus.publish(_make_signal(symbol="AAPL", ts_ns=300, horizon=900))
    bus.publish(_make_tick(ts_ns=400, bi=1, horizon=900))

    assert len(captured) == 2
    assert {c.horizon_seconds for c in captured} == {300, 900}
