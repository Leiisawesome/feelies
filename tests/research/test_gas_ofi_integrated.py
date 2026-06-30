"""Gas decision #1 — integrated OFI as the KYLE_INFO input.

Two artifacts of the promotion gate (sign golden + harness wiring) for switching
the KYLE alphas' OFI input from the event-paced ``ofi_ewma_zscore`` to
``ofi_integrated`` (Σ raw OFI over the horizon, the permanent-impact quantity).

The *edge* evidence — does ``ofi_integrated`` have the higher |RankIC| at the
KYLE horizons on real L1 — is an empirical question measured by
``scripts/sensor_feature_ic.py`` on cached data; that real-data pass is the gate
before any alpha is re-pointed (see ``docs/research/gas_01_integrated_ofi.md``).
What is certified *here* is correctness: the feature is signed right, and the
head-to-head harness runs end-to-end through the real pipeline.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.ofi_raw import OFIRawSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

_NS = 1_000_000_000
_H = 30


def _quote(ts: int, *, bid_size: int, ask_size: int = 10_000) -> NBBOQuote:
    # Constant best prices ⇒ raw OFI is driven purely by the displayed-size
    # deltas (CKS unchanged-price branch): OFI_t = Δbid_size − Δask_size.
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.02"),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _integrated_at_boundaries(bid_sizes: list[int]) -> list[float]:
    """Replay a constant-price tape (bid_size series) through the REAL
    registry→scheduler→aggregator; return ofi_integrated at each warm boundary."""
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({"AAPL"})
    )
    registry.register(
        SensorSpec(
            sensor_id="ofi_raw",
            sensor_version="1.0.0",
            cls=OFIRawSensor,
            params={"warm_after": 2, "warm_window_seconds": 300},
            subscribes_to=(NBBOQuote,),
        )
    )
    scheduler = HorizonScheduler(
        horizons=frozenset({_H}),
        session_id="GAS",
        symbols=frozenset({"AAPL"}),
        session_open_ns=0,
        sequence_generator=SequenceGenerator(),
    )
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=2 * _H,
        sequence_generator=SequenceGenerator(),
        horizon_features=[
            HorizonWindowedFeature("ofi_raw", _H, reducer="sum", feature_id="ofi_integrated", min_samples=1)
        ],
    )
    agg.attach()
    for i, bs in enumerate(bid_sizes):
        q = _quote(i * _NS, bid_size=bs)
        bus.publish(q)
        for tick in scheduler.on_event(q):
            bus.publish(tick)
    return [s.values["ofi_integrated"] for s in snaps if "ofi_integrated" in s.values]


def test_ofi_integrated_sign_positive_on_persistent_buy_flow() -> None:
    # Bid size grows every quote at constant price ⇒ raw OFI > 0 each event ⇒
    # the windowed sum (integrated flow) is positive.
    bid_sizes = [10_000 + 50 * i for i in range(90)]
    vals = _integrated_at_boundaries(bid_sizes)
    assert vals, "expected warm boundary snapshots"
    assert all(v > 0.0 for v in vals), vals


def test_ofi_integrated_sign_negative_on_persistent_sell_flow() -> None:
    # Bid size shrinks every quote ⇒ raw OFI < 0 each event ⇒ integrated < 0.
    bid_sizes = [10_000 - 50 * i for i in range(90)]
    vals = _integrated_at_boundaries(bid_sizes)
    assert vals
    assert all(v < 0.0 for v in vals), vals


def _load_ic_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_sensor_feature_ic", Path("scripts/sensor_feature_ic.py").resolve()
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the script's @dataclass annotation resolution can
    # find the module in sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_harness_ofi_integrated_ab_runs_and_reports_both_variants() -> None:
    """The offline head-to-head (`_ofi_integrated_ab`) runs end-to-end through
    the real pipeline and reports a row per (variant, horizon) — so the
    real-data RankIC comparison is one command away."""
    ic = _load_ic_script()
    # A small price-drifting tape so forward returns and OFI both exist.
    quotes = [
        ic.NBBOQuote(
            timestamp_ns=i * _NS,
            correlation_id=f"q-{i}",
            sequence=i,
            symbol="AAPL",
            bid=Decimal(str(round(100.0 + 1e-3 * i - 0.005, 5))),
            ask=Decimal(str(round(100.0 + 1e-3 * i + 0.005, 5))),
            bid_size=10_000 + 30 * i,
            ask_size=10_000,
            exchange_timestamp_ns=i * _NS,
        )
        for i in range(120)
    ]
    mids = ic._MidSeries.from_events(quotes)
    rows = ic._ofi_integrated_ab(quotes, mids, "AAPL", "2026-03-26", frozenset({_H}), 0)
    variants = {r.variant for r in rows}
    assert variants == {"ofi_ewma_zscore", "ofi_integrated"}
    assert all(r.feature == "ofi_kyle_input" for r in rows)
