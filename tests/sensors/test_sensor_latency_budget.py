"""Sensor per-event latency micro-benchmark — informational only.

Drives each Phase-2 sensor through ``EVENTS_PER_SENSOR`` synthetic
events, measures per-event ``update()`` latency with
``time.perf_counter_ns``, and prints a small p50/p99 table.

Per Phase-2 plan §13.6, this test is *informational only* — there is
no CI gate.  It exists so engineers running ``pytest -s`` locally have
a quick eyeball signal for catastrophic regressions in any sensor's
hot path.

Skipped by default unless ``CI_BENCHMARK=1`` (mirrors the throughput
no-regression test in ``tests/perf``) so day-to-day pytest runs stay
fast.

Run::

    CI_BENCHMARK=1 PYTHONHASHSEED=0 pytest tests/sensors/test_sensor_latency_budget.py -s
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.quote_hazard_rate import QuoteHazardRateSensor
from feelies.sensors.impl.quote_replenish_asymmetry import (
    QuoteReplenishAsymmetrySensor,
)
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.impl.trade_through_rate import TradeThroughRateSensor
from feelies.sensors.impl.vpin_50bucket import VPIN50BucketSensor

EVENTS_PER_SENSOR: int = 100_000
SESSION_OPEN_NS: int = 1_768_532_400_000_000_000
QUOTE_CADENCE_NS: int = 100_000_000  # 10 quotes / second event-time
SYMBOL: str = "AAPL"


pytestmark = pytest.mark.skipif(
    os.environ.get("CI_BENCHMARK") != "1",
    reason="latency micro-benchmark; opt-in via CI_BENCHMARK=1",
)


def _gen_events(
    n: int, *, seed: int, mix: str = "mixed",
) -> list[NBBOQuote | Trade]:
    """Synthesise ``n`` quote/trade events deterministically.

    ``mix`` selects the event balance:

    - ``"quote"``  — only ``NBBOQuote``;
    - ``"trade"``  — only ``Trade`` (preceded by one priming quote);
    - ``"mixed"``  — 70/30 quote/trade interleaving.
    """
    rng = random.Random(seed)
    out: list[NBBOQuote | Trade] = []
    mid_cents = 10_000
    for i in range(n):
        ts = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
        roll = rng.random()
        emit_quote: bool
        if mix == "quote":
            emit_quote = True
        elif mix == "trade":
            emit_quote = i == 0  # one priming quote up front
        else:
            emit_quote = roll < 0.7
        if emit_quote:
            mid_cents += rng.choice((-1, 0, 0, 0, +1))
            out.append(NBBOQuote(
                timestamp_ns=ts,
                correlation_id=f"q-{i}",
                sequence=i,
                symbol=SYMBOL,
                bid=Decimal(mid_cents - 1) / Decimal(100),
                ask=Decimal(mid_cents + 1) / Decimal(100),
                bid_size=rng.randint(1, 10) * 100,
                ask_size=rng.randint(1, 10) * 100,
                exchange_timestamp_ns=ts,
            ))
        else:
            side = rng.choice(("mid", "buy", "sell"))
            if side == "mid":
                price_cents = mid_cents
            elif side == "buy":
                price_cents = mid_cents + 1
            else:
                price_cents = mid_cents - 1
            out.append(Trade(
                timestamp_ns=ts,
                correlation_id=f"t-{i}",
                sequence=i,
                symbol=SYMBOL,
                price=Decimal(price_cents) / Decimal(100),
                size=rng.randint(1, 8) * 100,
                exchange_timestamp_ns=ts,
            ))
    return out


@dataclass
class BenchSpec:
    name: str
    factory: Callable[[], Any]
    mix: str = "mixed"


_SPECS: tuple[BenchSpec, ...] = (
    BenchSpec("ofi_ewma", lambda: OFIEwmaSensor(), mix="quote"),
    BenchSpec("micro_price", lambda: MicroPriceSensor(), mix="quote"),
    BenchSpec("spread_z_30d", lambda: SpreadZScoreSensor(), mix="quote"),
    BenchSpec("realized_vol_30s", lambda: RealizedVol30sSensor(), mix="quote"),
    BenchSpec(
        "vpin_50bucket",
        lambda: VPIN50BucketSensor(bucket_volume=1_000, window_buckets=20, min_buckets=5),
        mix="trade",
    ),
    BenchSpec(
        "kyle_lambda_60s",
        lambda: KyleLambda60sSensor(window_seconds=60, min_samples=10),
        mix="trade",
    ),
    BenchSpec(
        "quote_hazard_rate",
        lambda: QuoteHazardRateSensor(window_seconds=5, min_samples=20),
        mix="quote",
    ),
    BenchSpec(
        "quote_replenish_asymmetry",
        lambda: QuoteReplenishAsymmetrySensor(window_seconds=5, min_observations=20),
        mix="quote",
    ),
    BenchSpec(
        "trade_through_rate",
        lambda: TradeThroughRateSensor(window_seconds=30, min_trades=10),
        mix="mixed",
    ),
)


def _percentile(samples_ns: list[int], pct: float) -> int:
    """O(n log n) percentile — fine for a one-off bench print."""
    if not samples_ns:
        return 0
    s = sorted(samples_ns)
    k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return s[k]


def test_latency_budget_per_sensor(capsys: pytest.CaptureFixture[str]) -> None:
    """Time each sensor through 100k events and print p50/p99 latency.

    No assertion is made on the absolute numbers (informational
    only).  We *do* assert each sensor produced at least one
    non-``None`` reading so the bench cannot silently pass against an
    inert sensor.
    """
    print()  # blank line so the table renders cleanly under -s
    print(
        f"{'sensor':<28} {'p50_ns':>10} {'p99_ns':>10} {'mean_ns':>10}"
        f" {'emitted':>10}"
    )
    for spec in _SPECS:
        events = _gen_events(EVENTS_PER_SENSOR, seed=hash(spec.name) & 0xFFFF, mix=spec.mix)
        sensor = spec.factory()
        state = sensor.initial_state()
        samples: list[int] = []
        emitted = 0
        for event in events:
            t0 = time.perf_counter_ns()
            reading = sensor.update(event, state, params={})
            t1 = time.perf_counter_ns()
            samples.append(t1 - t0)
            if reading is not None:
                emitted += 1
        p50 = _percentile(samples, 50.0)
        p99 = _percentile(samples, 99.0)
        mean = sum(samples) // max(1, len(samples))
        print(
            f"{spec.name:<28} {p50:>10d} {p99:>10d} {mean:>10d} {emitted:>10d}"
        )
        assert emitted > 0, f"{spec.name} emitted zero readings — bench is degenerate"

    captured = capsys.readouterr()
    assert "sensor" in captured.out
