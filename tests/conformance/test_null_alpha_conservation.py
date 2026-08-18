"""C1 — null-alpha conservation.

FIX-1 emits no ``Signal`` by construction, so a replay under it must leave
the book untouched: zero position, zero realized P&L, zero unrealized P&L,
at every event rather than only at the end.

This is the conservation identity every later attribution test rests on.
If exposure or P&L appears when no alpha asked for anything, it was created
by the engine, and no per-alpha attribution built on top of it can be
trusted.  Checking only the closing book would miss a position that opens
and closes inside the run.
"""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path
from typing import Any

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.harness.engine_probe import EngineProbe
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_NULL_ALPHA = Path(__file__).resolve().parent / "fixtures" / "null_alpha" / "null_alpha.alpha.yaml"

_UNIVERSE: tuple[str, ...] = ("AAPL", "MSFT")
# 400 seconds at 1 Hz crosses thirteen 30-second boundaries, so FIX-1 is
# evaluated repeatedly rather than never — a tape shorter than one horizon
# would satisfy every identity below without the alpha ever running.
_QUOTES_PER_SYMBOL = 400
_QUOTE_CADENCE_NS = 1_000_000_000
_HORIZON_SECONDS = 30

_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
)


def _synth_events(seed: int = 7) -> list[Any]:
    """A deterministic two-symbol quote/trade tape, merged on timestamp."""
    starting_cents = {"AAPL": 18000, "MSFT": 37000}
    rows: list[tuple[int, str, Any]] = []
    for sym_idx, symbol in enumerate(_UNIVERSE):
        rng = random.Random(seed * 100 + sym_idx)
        mid = starting_cents[symbol]
        for i in range(_QUOTES_PER_SYMBOL):
            ts_ns = SESSION_OPEN_NS + i * _QUOTE_CADENCE_NS
            mid += rng.choice((-1, 0, 0, 0, 1))
            rows.append(
                (
                    ts_ns,
                    symbol,
                    NBBOQuote(
                        timestamp_ns=ts_ns,
                        sequence=sym_idx * _QUOTES_PER_SYMBOL + i,
                        correlation_id=f"null-q-{symbol}-{i}",
                        source_layer="INGESTION",
                        symbol=symbol,
                        bid=Decimal(mid) / Decimal(100),
                        ask=Decimal(mid + 1) / Decimal(100),
                        bid_size=rng.choice((100, 200, 300)),
                        ask_size=rng.choice((100, 200, 300)),
                        exchange_timestamp_ns=ts_ns,
                        bid_exchange=11,
                        ask_exchange=11,
                        tape=3,
                    ),
                )
            )
            if i % 7 == 0 and i > 0:
                rows.append(
                    (
                        ts_ns + 1,
                        symbol,
                        Trade(
                            timestamp_ns=ts_ns + 1,
                            sequence=sym_idx * _QUOTES_PER_SYMBOL * 2 + i,
                            correlation_id=f"null-t-{symbol}-{i}",
                            source_layer="INGESTION",
                            symbol=symbol,
                            price=Decimal(mid) / Decimal(100),
                            size=rng.choice((50, 100, 150)),
                            exchange=11,
                            trade_id=f"null-{symbol}-{i:08d}",
                            exchange_timestamp_ns=ts_ns + 1,
                            tape=3,
                        ),
                    )
                )
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows]


def _replay_under_null_alpha() -> EngineProbe:
    config = PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({_HORIZON_SECONDS}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        # FIX-1 declares no trend_mechanism: it exploits no mechanism.
        enforce_trend_mechanism=False,
    )
    event_log = InMemoryEventLog()
    events = _synth_events()
    event_log.append_batch(events)

    orchestrator, _ = build_platform(config, event_log=event_log)
    probe = EngineProbe(positions=orchestrator._positions, symbols=_UNIVERSE)
    probe.attach(orchestrator._bus)

    orchestrator.boot(config)
    orchestrator.run_backtest()

    # Two ways this replay can satisfy every identity below without testing
    # anything, both of which have already happened once while writing it:
    # the tape can be shorter than one horizon so no boundary is crossed, and
    # the regime gate can fail safe to OFF so evaluate is never reached.
    assert probe.event_count >= len(events), (
        f"probe saw {probe.event_count} events but {len(events)} were fed in — "
        "the replay did not run, so the conservation identities are vacuous"
    )
    engine = orchestrator._horizon_signal_engine
    assert engine is not None, "no horizon signal engine — FIX-1 was never evaluated"
    registered = [r for r in engine._signals if r.alpha_id == "null_alpha"]
    assert len(registered) == 1, f"expected FIX-1 registered once, got {len(registered)}"
    gate = registered[0].gate
    gated_off = [s for s in _UNIVERSE if not gate.is_on(s)]
    assert not gated_off, (
        f"FIX-1's regime gate never latched ON for {gated_off} — evaluate was not "
        "reached, so this replay proves the gate suppressed the alpha, not that "
        "the alpha emits nothing"
    )
    return probe


def test_null_alpha_creates_no_position_or_pnl_at_any_event() -> None:
    probe = _replay_under_null_alpha()

    violations = [s for s in probe.samples if s.quantity or s.realized_pnl or s.unrealized_pnl]
    assert not violations, (
        f"FIX-1 emits no Signal, yet the book moved at {len(violations)} of "
        f"{len(probe.samples)} observations. First: {violations[0]}. "
        "Exposure or P&L with no strategy asking for it is engine-created, "
        "and per-alpha attribution cannot be trusted while it happens."
    )


def test_null_alpha_probe_observes_every_watched_symbol() -> None:
    """Guards the identity above against an empty or partial sample set."""
    probe = _replay_under_null_alpha()

    assert probe.samples, "probe recorded no observations"
    observed = {s.symbol for s in probe.samples}
    assert observed == set(_UNIVERSE), (
        f"probe covered {sorted(observed)}, expected {sorted(_UNIVERSE)} — "
        "an unwatched symbol could move without the conservation test noticing"
    )
