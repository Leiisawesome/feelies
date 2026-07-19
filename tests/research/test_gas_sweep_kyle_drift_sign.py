"""Harness sign-goldens for ``sig_sweep_kyle_drift_h900_v1`` — protocol §2.1
under Ordering B (slate-C SEQUENCING RULING).

Phase B YAML / ``evaluate`` is gated on step-2 PASS, so these goldens
certify the *extraction path* (real ``SensorRegistry → HorizonScheduler
→ HorizonAggregator`` + the census-pinned §1.1 predicate) — the
harness-sign-golden mitigation for the 2a/2b inversion.  Full
loader-compiled ``evaluate`` goldens remain a Phase-B proof obligation
after a PASS (protocol §2.1 / spec §15).

No cached data, no forward returns, no outcome statistic — correctness
certification only (protocol §2.1: assertion failure ⇒ REJECTED
sign/wiring defect; fix is implementation-correction, N unchanged).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.core.session_clock import rth_open_ns
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from scripts.research.sweep_kyle_drift_census import (
    ENTRY_WARM_IDS,
    SENSOR_SPECS,
    _HORIZON,
    _sfi_features,
    is_entry_eligible,
    run_cell_from_events,
)

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_SYM = "APP"
_DATE = "2026-01-15"


def _et_ns(hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(2026, 1, 15, hour, minute, second, tzinfo=_TZ_ET).timestamp() * 1e9)


def _synth_tape(
    *,
    n_iso: int = 45,
    conditions: tuple[int, ...] = (14,),
    correction: int | None = None,
    sell: bool = False,
    mix_interior: bool = False,
) -> list[NBBOQuote | Trade]:
    """Minimal RTH tape (same construction as census synthetic pin)."""
    events: list[NBBOQuote | Trade] = []
    open_ns = _et_ns(9, 30, 0)
    end_ns = _et_ns(9, 50, 0)
    seq = 0
    t = open_ns
    while t <= end_ns:
        seq += 1
        events.append(
            NBBOQuote(
                timestamp_ns=t,
                correlation_id=f"q-{seq}",
                sequence=seq,
                symbol=_SYM,
                bid=Decimal("100.00"),
                ask=Decimal("100.02"),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=t,
            )
        )
        t += _NS

    trade_start = _et_ns(9, 31, 0)
    for i in range(n_iso):
        seq += 1
        ts = trade_start + i * 12 * _NS
        if mix_interior:
            # Alternate buy/sell ISO so the windowed percentile stays interior.
            up = i % 2 == 0
            px = Decimal(f"{100.00 + (i + 1) * (0.01 if up else -0.01):.2f}")
        elif sell:
            px = Decimal(f"{100.00 - (i + 1) * 0.01:.2f}")
        else:
            px = Decimal(f"{100.00 + (i + 1) * 0.01:.2f}")
        events.append(
            Trade(
                timestamp_ns=ts,
                correlation_id=f"t-{seq}",
                sequence=seq,
                symbol=_SYM,
                price=px,
                size=100,
                exchange_timestamp_ns=ts,
                conditions=conditions,
                correction=correction,
            )
        )
    return events


def _replay_snapshots(
    events: list[NBBOQuote | Trade],
) -> list[HorizonFeatureSnapshot]:
    events = sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
    session_open = rth_open_ns(events[0].timestamp_ns)
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({_SYM}),
    )
    for spec in SENSOR_SPECS:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id="H10_SIGN",
        symbols=frozenset({_SYM}),
        session_open_ns=session_open,
        sequence_generator=SequenceGenerator(),
    )
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({_SYM}),
        sensor_buffer_seconds=2 * _HORIZON,
        sequence_generator=SequenceGenerator(),
        horizon_features=_sfi_features(),
    )
    agg.attach()
    for ev in events:
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
    return [s for s in snaps if s.horizon_seconds == _HORIZON]


def _in_window_boundary(
    snaps: list[HorizonFeatureSnapshot],
) -> HorizonFeatureSnapshot | None:
    """Sole in-window boundary under the census synthetic tape (09:45)."""
    target = _et_ns(9, 45, 0)
    for s in snaps:
        if s.boundary_ts_ns == target:
            return s
    return None


# ── §2.1 assertions (Ordering-B harness equivalents) ─────────────────────


def test_2a_1_informed_continuation_long_golden() -> None:
    """Buy-side Class-A ∩ id-14 ISO dominance ⇒ SFI>0, pctl≥0.90 ⇒ LONG arm."""
    cell = run_cell_from_events(_synth_tape(), _SYM, _DATE)
    assert cell is not None
    assert cell.episodes == 1
    assert cell.episodes_long == 1
    snap = _in_window_boundary(_replay_snapshots(_synth_tape()))
    assert snap is not None
    sfi = snap.values["sweep_flow_imbalance"]
    pctl = snap.values["sweep_flow_imbalance_percentile"]
    assert sfi > 0.0
    assert pctl >= 0.90
    ok, side = is_entry_eligible(sfi=sfi, pctl=pctl, rvz=0.0, p_breakout=0.2)
    assert ok and side == "LONG"


def test_2a_2_mirror_short_golden() -> None:
    """Mirrored sell-side ISO tape ⇒ SFI<0, pctl≤0.10 ⇒ SHORT arm."""
    cell = run_cell_from_events(_synth_tape(sell=True), _SYM, _DATE)
    assert cell is not None
    assert cell.episodes == 1
    assert cell.episodes_short == 1
    snap = _in_window_boundary(_replay_snapshots(_synth_tape(sell=True)))
    assert snap is not None
    sfi = snap.values["sweep_flow_imbalance"]
    pctl = snap.values["sweep_flow_imbalance_percentile"]
    assert sfi < 0.0
    assert pctl <= 0.10
    ok, side = is_entry_eligible(sfi=sfi, pctl=pctl, rvz=0.0, p_breakout=0.2)
    assert ok and side == "SHORT"


def test_2a_3_interior_null_golden() -> None:
    """Alternating ISO signs ⇒ percentile interior ⇒ entry suppressed."""
    cell = run_cell_from_events(_synth_tape(mix_interior=True), _SYM, _DATE)
    assert cell is not None
    assert cell.episodes == 0
    snap = _in_window_boundary(_replay_snapshots(_synth_tape(mix_interior=True)))
    assert snap is not None
    if snap.warm.get("sweep_flow_imbalance") and snap.warm.get("sweep_flow_imbalance_percentile"):
        pctl = snap.values["sweep_flow_imbalance_percentile"]
        sfi = snap.values["sweep_flow_imbalance"]
        assert 0.10 < pctl < 0.90
        ok, _ = is_entry_eligible(sfi=sfi, pctl=pctl, rvz=0.0, p_breakout=0.2)
        assert ok is False


def test_2a_4_filter_exclusion_golden() -> None:
    """Non-id-14 / Class-B prints do not accumulate in SFI ⇒ no extreme entry."""
    cell = run_cell_from_events(_synth_tape(conditions=(8,)), _SYM, _DATE)
    assert cell is not None
    assert cell.episodes == 0
    assert cell.sfi_warm_fraction_in_window == 0.0


def test_2a_5_warm_gate_golden() -> None:
    """< 20 eligible ISO prints ⇒ SFI not warm ⇒ entry suppressed."""
    cell = run_cell_from_events(_synth_tape(n_iso=5), _SYM, _DATE)
    assert cell is not None
    assert cell.episodes == 0
    assert cell.sfi_warm_fraction_in_window == 0.0


def test_2a_6_sign_disagreement_golden() -> None:
    """Predicate rejects extreme percentile with wrong SFI sign (spec §5.2)."""
    assert is_entry_eligible(sfi=-0.1, pctl=0.95, rvz=1.0, p_breakout=0.2) == (
        False,
        None,
    )
    assert is_entry_eligible(sfi=0.1, pctl=0.05, rvz=1.0, p_breakout=0.2) == (
        False,
        None,
    )


def test_2a_7_h900_key_presence_golden() -> None:
    """h=900 snapshot carries consumed entry ids (factory wiring lock)."""
    feats = _sfi_features()
    fids = {f.feature_id for f in feats}
    assert set(ENTRY_WARM_IDS) <= fids
    snaps = _replay_snapshots(_synth_tape())
    snap = _in_window_boundary(snaps)
    assert snap is not None
    for fid in ENTRY_WARM_IDS:
        assert fid in snap.values or snap.warm.get(fid) is not None
        # Warm path: values present once warm.
        if snap.warm.get(fid, False):
            assert fid in snap.values
