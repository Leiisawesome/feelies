#!/usr/bin/env python3
"""Sensor / feature IC harness — does horizon-windowing lift SNR? (audit P1-1).

Read-only offline validation.  For one or more ``(symbol, date)`` pairs of
**cached NBBO + trades** (the platform's ``DiskEventCache``), this script:

1. Replays the events through the real Layer-1 → Layer-1.5 pipeline
   (``SensorRegistry`` → ``HorizonScheduler`` → ``HorizonAggregator``),
   once per *feature variant*.
2. At each ``HorizonFeatureSnapshot`` boundary it pairs the warm feature
   value with the **forward mid log-return** over that snapshot's horizon.
3. Reports the Spearman **RankIC** and Pearson **IC** (with a naive
   t-stat and sample count) per ``(feature, horizon, variant)``.

The headline comparison is, for each z-scored sensor, the **old
count-window** feature (``RollingZscoreFeature``) versus the **new
horizon-windowed** feature (``HorizonWindowedFeature``).  If P1-1 helped,
the windowed variant's |RankIC| should rise toward the longer horizons
while the count-window variant stays roughly flat in ``h`` (because its
baseline never depended on ``h``).

This script computes **no point estimate of edge** and makes no trading
claim — it is a falsification tool: it tells you whether the new feature
is *more* monotonically related to forward returns than the old one.

Usage
-----
    uv run python scripts/sensor_feature_ic.py \
        --cache-dir data/cache \
        --symbol AAPL --date 2026-03-26 \
        [--horizons 30,120,300,900,1800] [--csv out.csv]

``--symbol`` / ``--date`` may be repeated (or comma-separated) and are
zipped pairwise when counts match, else taken as a full cross-product.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Callable, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    os.chdir(_REPO_ROOT)

from feelies.bootstrap import _horizon_features_for  # noqa: E402
from feelies.bus.event_bus import EventBus  # noqa: E402
from feelies.core.events import (  # noqa: E402
    HorizonFeatureSnapshot,
    NBBOQuote,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402
from feelies.features.aggregator import HorizonAggregator  # noqa: E402
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature  # noqa: E402
from feelies.features.impl.rolling_stats import RollingZscoreFeature  # noqa: E402
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature  # noqa: E402
from feelies.features.protocol import HorizonFeature  # noqa: E402
from feelies.research.forward_ic import (  # noqa: E402
    bucketed_forward_return,
    long_short_edge_bps,
    spearman_ic,
)
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor  # noqa: E402
from feelies.sensors.impl.micro_price import MicroPriceSensor  # noqa: E402
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor  # noqa: E402
from feelies.sensors.impl.ofi_raw import OFIRawSensor  # noqa: E402
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor  # noqa: E402
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor  # noqa: E402
from feelies.sensors.impl.sweep_flow_imbalance import SweepFlowImbalanceSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402
from feelies.storage.reference.event_calendar import (  # noqa: E402
    EventCalendar,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR  # noqa: E402

_NS_PER_SECOND = 1_000_000_000

# Sensor specs mirror the reference platform.yaml params so the IC reflects
# what production actually computes.
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 50, "warm_window_seconds": 300},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={"warm_after": 1, "warm_window_seconds": 60},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={
            "min_samples": 30,
            "alignment": "causal",
            "sensor_version": "2.0.0",
        },
        subscribes_to=(NBBOQuote, Trade),
    ),
)

# feature_id under test → (sensor_id, count-window builder, windowed builder).
# Both builders also include a passthrough so the snapshot is "active mode".
_FeatureBuilder = Callable[[str, int], list[HorizonFeature]]


def _count_builder(sensor_id: str, max_samples: int) -> _FeatureBuilder:
    def build(sid: str, h: int) -> list[HorizonFeature]:
        return [
            SensorPassthroughFeature(sid, h),
            RollingZscoreFeature(
                sid,
                h,
                feature_id=f"{sid}_zscore",
                max_samples=max_samples,
            ),
        ]

    return build


def _window_builder(sensor_id: str) -> _FeatureBuilder:
    def build(sid: str, h: int) -> list[HorizonFeature]:
        return [
            SensorPassthroughFeature(sid, h),
            HorizonWindowedFeature(
                sid,
                h,
                reducer="zscore",
                feature_id=f"{sid}_zscore",
            ),
        ]

    return build


# Production used max_samples=200 for ofi_ewma, default 2000 elsewhere.
_TARGETS: dict[str, int] = {
    "ofi_ewma": 200,
    "micro_price": 2000,
    "realized_vol_30s": 2000,
    "kyle_lambda_60s": 2000,
}


# ── Replay ───────────────────────────────────────────────────────────────


def _replay_snapshots(
    events: Sequence[NBBOQuote | Trade],
    *,
    symbol: str,
    horizon_features: list[HorizonFeature],
    horizons: frozenset[int],
    session_open_ns: int,
    sensor_specs: Sequence[SensorSpec] = _SENSOR_SPECS,
) -> list[HorizonFeatureSnapshot]:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({symbol}),
    )
    for spec in sensor_specs:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=horizons,
        session_id="IC_HARNESS",
        symbols=frozenset({symbol}),
        session_open_ns=session_open_ns,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({symbol}),
        sensor_buffer_seconds=2 * max(horizons),
        sequence_generator=SequenceGenerator(),
        horizon_features=horizon_features,
    )
    aggregator.attach()

    for ev in events:
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
    return captured


# ── Forward returns ──────────────────────────────────────────────────────


@dataclass
class _MidSeries:
    ts: list[int]
    mid: list[float]

    @classmethod
    def from_events(cls, events: Iterable[NBBOQuote | Trade]) -> "_MidSeries":
        ts: list[int] = []
        mid: list[float] = []
        for ev in events:
            if isinstance(ev, NBBOQuote):
                b, a = float(ev.bid), float(ev.ask)
                if b > 0.0 and a > 0.0:
                    ts.append(ev.timestamp_ns)
                    mid.append((b + a) / 2.0)
        return cls(ts=ts, mid=mid)

    def at(self, t_ns: int) -> float | None:
        """Last mid at or before ``t_ns`` (causal), or None if before start."""
        i = bisect.bisect_right(self.ts, t_ns) - 1
        if i < 0:
            return None
        return self.mid[i]

    @property
    def last_ts(self) -> int:
        return self.ts[-1] if self.ts else 0


def _forward_return(mids: _MidSeries, t0: int, horizon_s: int) -> float | None:
    t1 = t0 + horizon_s * _NS_PER_SECOND
    if t1 > mids.last_ts:
        return None  # no realised forward window — drop (no lookahead)
    m0 = mids.at(t0)
    m1 = mids.at(t1)
    if m0 is None or m1 is None or m0 <= 0.0 or m1 <= 0.0 or m1 == m0:
        return None
    return math.log(m1 / m0)


# ── Statistics (pure-python; no scipy) ───────────────────────────────────


def _rankdata(xs: Sequence[float]) -> list[float]:
    """Average-rank of each element (ties share the mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    n = len(xs)
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    return _pearson(_rankdata(xs), _rankdata(ys))


def _tstat(ic: float, n: int) -> float:
    denom = 1.0 - ic * ic
    if n < 3 or denom <= 0.0:
        return float("inf") if ic != 0 else 0.0
    return ic * math.sqrt((n - 2) / denom)


# ── Pairing snapshots ↔ forward returns ──────────────────────────────────


@dataclass
class _Pairs:
    values: list[float]
    fwd: list[float]


def _collect_pairs(
    snapshots: list[HorizonFeatureSnapshot],
    mids: _MidSeries,
    feature_id: str,
    horizon: int,
) -> _Pairs:
    values: list[float] = []
    fwd: list[float] = []
    for s in snapshots:
        if s.horizon_seconds != horizon:
            continue
        v = s.values.get(feature_id)  # present only when warm
        if v is None:
            continue
        # sensor_audit_2026-07-02 P1: pair from boundary_ts_ns (the nominal
        # grid anchor `core/events.py` documents "for IC labels / forensics"),
        # not timestamp_ns (the trigger time of the event that crossed the
        # boundary). On a sparse tape these diverge, silently shifting every
        # RankIC this script reports.
        r = _forward_return(mids, s.boundary_ts_ns, horizon)
        if r is None:
            continue
        values.append(float(v))
        fwd.append(r)
    return _Pairs(values=values, fwd=fwd)


# ── Driver ───────────────────────────────────────────────────────────────


@dataclass
class _Row:
    symbol: str
    date: str
    feature: str
    horizon: int
    variant: str
    n: int
    rank_ic: float | None
    ic: float | None
    # Gross long-short edge (top−bottom quintile forward return) in bps — the
    # tradability/cost-gate number for fast-horizon features (gas decision #2).
    edge_bps: float | None = None
    # Raw (feature, forward_return) pairs retained when ``edge_bps`` is set,
    # so multi-day pooling can re-run the cost-gate primitive on globally
    # concatenated pairs rather than averaging per-day spreads.
    pairs: _Pairs | None = None
    # Fisher-z two-sided p of ``rank_ic`` (``research/forward_ic.spearman_ic``)
    # — populated for the H8 rows, whose protocol gate binds on p, not the
    # naive t-stat.
    p_value: float | None = None

    @property
    def tstat(self) -> float | None:
        if self.rank_ic is None:
            return None
        return _tstat(self.rank_ic, self.n)


def _run_one(
    cache: DiskEventCache,
    symbol: str,
    date: str,
    horizons: frozenset[int],
) -> list[_Row]:
    events = cache.load(symbol, date)
    if not events:
        print(f"  ! no cached events for {symbol}/{date} (skipping)", file=sys.stderr)
        return []
    events = sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
    # Audit P1-8 parity: production bootstrap anchors the horizon grid to the
    # 09:30 ET RTH open when ``session_open_ns`` is unset for RTH US equity,
    # not the raw first cached event.  Mirror that here so IC boundaries and
    # snapshot pairing match a live replay of the same tape.
    session_open_ns = rth_open_ns(events[0].timestamp_ns)
    mids = _MidSeries.from_events(events)
    if len(mids.ts) < 10:
        print(f"  ! too few quotes for {symbol}/{date}", file=sys.stderr)
        return []

    rows: list[_Row] = []
    for sensor_id, max_samples in _TARGETS.items():
        feature_id = f"{sensor_id}_zscore"
        variants: dict[str, list[HorizonFeature]] = {
            "count_window": [
                f
                for h in sorted(horizons)
                for f in _count_builder(sensor_id, max_samples)(sensor_id, h)
            ],
            "horizon_window": [
                f for h in sorted(horizons) for f in _window_builder(sensor_id)(sensor_id, h)
            ],
        }
        for variant, feats in variants.items():
            snaps = _replay_snapshots(
                events,
                symbol=symbol,
                horizon_features=feats,
                horizons=horizons,
                session_open_ns=session_open_ns,
            )
            for h in sorted(horizons):
                p = _collect_pairs(snaps, mids, feature_id, h)
                rows.append(
                    _Row(
                        symbol=symbol,
                        date=date,
                        feature=feature_id,
                        horizon=h,
                        variant=variant,
                        n=len(p.values),
                        rank_ic=_spearman(p.values, p.fwd),
                        ic=_pearson(p.values, p.fwd),
                    )
                )

    # Audit P1-5: A/B the Kyle *alignment* (legacy 1.2.0 vs causal 2.0.0),
    # both under the horizon-window feature, isolating the alignment change
    # from the windowing change.  The main loop above already tests windowing
    # on whatever kyle version sits in _SENSOR_SPECS (currently causal);
    # this answers the distinct question "did the causal re-alignment help?".
    rows.extend(
        _kyle_alignment_ab(
            events,
            mids,
            symbol,
            date,
            horizons,
            session_open_ns,
        )
    )
    # Gas decision #1 (KYLE_INFO input): integrated raw OFI (Σ ofi_t, the
    # permanent-impact quantity) vs the event-paced ``ofi_ewma_zscore`` the
    # alphas currently read.  Both measured in one replay so the head-to-head
    # RankIC per horizon is directly comparable.
    rows.extend(
        _ofi_integrated_ab(
            events,
            mids,
            symbol,
            date,
            horizons,
            session_open_ns,
        )
    )
    # Protocol §2.2 H10 row (sig_sweep_kyle_drift_h900_v1) — pinned to
    # h=900; SFI-stratified contrast; additive only; no outcome contact in
    # Phase A (instrument land only).
    if _H10_HORIZON in horizons:
        rows.extend(_h10_sweep_kyle(events, mids, symbol, date, session_open_ns))
    # Protocol §2.2 H12 row (sig_halfhour_clock_drift_h900_v1) — pinned to
    # h=900; clock-stratified in-window / out-window extreme-OFI contrast;
    # additive only; no outcome contact in Phase A (instrument land only).
    if _H12_HORIZON in horizons:
        rows.extend(_h12_halfhour_clock(events, mids, symbol, date, session_open_ns))
    # Protocol §2.2 H13 row (sig_hour_checkpoint_drift_h1800_v1) — pinned to
    # h=1800; hour-stratified in-hour / :30 extreme-OFI contrast under
    # hour-only calendar injection; additive only; no outcome contact in
    # Phase A (instrument land only). N = 12 unchanged.
    if _H13_HORIZON in horizons:
        rows.extend(_h13_hour_checkpoint(events, mids, symbol, date, session_open_ns))
    return rows


def _ofi_integrated_ab(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    horizons: frozenset[int],
    session_open_ns: int,
) -> list[_Row]:
    """RankIC of ``ofi_integrated`` (Σ raw OFI over the horizon) vs
    ``ofi_ewma_zscore`` (the event-paced EWMA z the KYLE alphas read).

    The KYLE_INFO mechanism is permanent impact ∝ integrated signed flow
    (Cont–Kukanov–Stoikov 2014); the EWMA decays per quote (~0.1–0.7 s
    half-life) so its boundary value is a near-instantaneous flow snapshot.
    This A/B settles, on real cached L1, whether the integrated input has the
    higher |RankIC| (correct positive sign) at the KYLE horizons (300/900/1800 s)
    before any alpha is re-pointed.

    NOTE: CKS OFI is dominated by price-change events, so integrated OFI partly
    tracks realised in-window price direction — its forward predictiveness is
    therefore an empirical question (price autocorrelation), which is exactly
    why this must be measured on data, not assumed.
    """
    specs = _SENSOR_SPECS + (
        SensorSpec(
            sensor_id="ofi_raw",
            sensor_version="1.0.0",
            cls=OFIRawSensor,
            params={"warm_after": 50, "warm_window_seconds": 300},
            subscribes_to=(NBBOQuote,),
        ),
    )
    feats: list[HorizonFeature] = []
    for h in sorted(horizons):
        feats.append(SensorPassthroughFeature("ofi_ewma", h))
        feats.append(
            HorizonWindowedFeature(
                "ofi_ewma", h, reducer="zscore", feature_id="ofi_ewma_zscore"
            )
        )
        feats.append(
            HorizonWindowedFeature(
                "ofi_raw", h, reducer="sum", feature_id="ofi_integrated", min_samples=1
            )
        )
    snaps = _replay_snapshots(
        events,
        symbol=symbol,
        horizon_features=feats,
        horizons=horizons,
        session_open_ns=session_open_ns,
        sensor_specs=specs,
    )
    rows: list[_Row] = []
    for variant in ("ofi_ewma_zscore", "ofi_integrated"):
        for h in sorted(horizons):
            p = _collect_pairs(snaps, mids, variant, h)
            edge = (
                long_short_edge_bps(p.values, p.fwd) if len(p.values) >= 5 else None
            )
            rows.append(
                _Row(
                    symbol=symbol,
                    date=date,
                    feature="ofi_kyle_input",
                    horizon=h,
                    variant=variant,
                    n=len(p.values),
                    rank_ic=_spearman(p.values, p.fwd),
                    ic=_pearson(p.values, p.fwd),
                    edge_bps=edge,
                    pairs=p if edge is not None else None,
                )
            )
    return rows


def _kyle_alignment_ab(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    horizons: frozenset[int],
    session_open_ns: int,
) -> list[_Row]:
    """Replay legacy- and causal-aligned Kyle (each horizon-windowed) and
    report RankIC per horizon, so the P1-5 alignment can be settled directly.

    Different sensor versions share a sensor_id and cannot co-register in one
    registry (features are version-blind), so each runs under its own spec set.
    """
    feature_id = "kyle_lambda_60s_zscore"
    base = tuple(s for s in _SENSOR_SPECS if s.sensor_id != "kyle_lambda_60s")
    legacy_kyle = SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="1.2.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "legacy", "sensor_version": "1.2.0"},
        subscribes_to=(NBBOQuote, Trade),
    )
    causal_kyle = SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "causal", "sensor_version": "2.0.0"},
        subscribes_to=(NBBOQuote, Trade),
    )
    specsets = {
        "kyle_legacy_win": base + (legacy_kyle,),
        "kyle_causal_win": base + (causal_kyle,),
    }
    rows: list[_Row] = []
    for variant, specs in specsets.items():
        feats = [
            f
            for h in sorted(horizons)
            for f in _window_builder("kyle_lambda_60s")("kyle_lambda_60s", h)
        ]
        snaps = _replay_snapshots(
            events,
            symbol=symbol,
            horizon_features=feats,
            horizons=horizons,
            session_open_ns=session_open_ns,
            sensor_specs=specs,
        )
        for h in sorted(horizons):
            p = _collect_pairs(snaps, mids, feature_id, h)
            rows.append(
                _Row(
                    symbol=symbol,
                    date=date,
                    feature="kyle_alignment",
                    horizon=h,
                    variant=variant,
                    n=len(p.values),
                    rank_ic=_spearman(p.values, p.fwd),
                    ic=_pearson(p.values, p.fwd),
                )
            )
    return rows


# ── H10 row — sig_sweep_kyle_drift_h900_v1 (protocol §2.2; Task 9-A Phase A)
#
# Measurement plumbing for the pre-registered H10 primary trial, not a new
# trial: x = sweep_flow_imbalance (signed) vs y = signed forward 900 s mid
# log-return, stratified by the extreme-SFI decile
# (percentile ≥ 0.90 OR ≤ 0.10 with sign agreement) vs the interior
# (0.10, 0.90).  Primary contamination posture = filter-clean by SFI
# construction (JC-1); no intensity exclusion on the IC row.  OLN cells are
# evidence-only §2.4 tick-artifact inputs — reported to stderr, never
# contributing an IC row.  Phase A lands the instrument only — no cached-
# data IC run executes here (N = 11 unchanged).

_H10_HORIZON = 900
_H10_SFI_PCTL_HI = 0.90
_H10_SFI_PCTL_LO = 0.10
_H10_EVIDENCE_ONLY_SYMBOLS = frozenset({"OLN"})
_H10_CONSUMED_IDS = (
    "sweep_flow_imbalance",
    "sweep_flow_imbalance_percentile",
    "realized_vol_30s_zscore",
)
_H10_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="sweep_flow_imbalance",
        sensor_version="1.0.0",
        cls=SweepFlowImbalanceSensor,
        params={
            "window_seconds": 900,
            "min_eligible_prints": 20,
            "max_gap_seconds": 60,
            "drop_correction_records": (10, 11, 12),
        },
        subscribes_to=(Trade,),
    ),
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={
            "min_samples": 30,
            "alignment": "causal",
            "sensor_version": "2.0.0",
        },
        subscribes_to=(NBBOQuote, Trade),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
)


def _h10_features() -> list[HorizonFeature]:
    h = _H10_HORIZON
    return [
        SensorPassthroughFeature("sweep_flow_imbalance", h),
        HorizonWindowedFeature(
            "sweep_flow_imbalance",
            h,
            reducer="percentile",
            feature_id="sweep_flow_imbalance_percentile",
        ),
        *_horizon_features_for("kyle_lambda_60s", h),
        *_horizon_features_for("realized_vol_30s", h),
    ]


def _h10_rank_row(symbol: str, date: str, variant: str, p: _Pairs, *, with_edge: bool) -> _Row:
    n = len(p.values)
    rank_ic = ic = p_value = None
    if n >= 3:
        res = spearman_ic(p.values, p.fwd)
        rank_ic, p_value = res.rho, res.p_value
        ic = _pearson(p.values, p.fwd)
    edge = long_short_edge_bps(p.values, p.fwd) if with_edge and n >= 5 else None
    return _Row(
        symbol=symbol,
        date=date,
        feature="h10_sweep_kyle",
        horizon=_H10_HORIZON,
        variant=variant,
        n=n,
        rank_ic=rank_ic,
        ic=ic,
        edge_bps=edge,
        pairs=p if edge is not None else None,
        p_value=p_value,
    )


def _h10_oln_tick_artifact_report(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    boundaries: list[tuple[int, float]],
) -> None:
    """§2.4 evidence-only hooks for OLN: spread-in-ticks + half-tick quantum."""
    quote_ts = [e.timestamp_ns for e in events if isinstance(e, NBBOQuote)]
    quote_spread = [float(e.ask) - float(e.bid) for e in events if isinstance(e, NBBOQuote)]
    tick = 0.01
    spreads: list[int] = []
    within_quantum = 0
    n_moves = 0
    for asof_ns, _x in boundaries:
        qi = bisect.bisect_right(quote_ts, asof_ns) - 1
        if qi >= 0:
            spreads.append(round(quote_spread[qi] / tick))
        m0 = mids.at(asof_ns)
        m1 = mids.at(asof_ns + _H10_HORIZON * _NS_PER_SECOND)
        if (
            m0 is not None
            and m1 is not None
            and asof_ns + _H10_HORIZON * _NS_PER_SECOND <= mids.last_ts
        ):
            n_moves += 1
            if abs(m1 - m0) <= tick / 2.0:
                within_quantum += 1
    med = sorted(spreads)[len(spreads) // 2] if spreads else None
    mass = within_quantum / n_moves if n_moves else None
    print(
        f"  # H10 §2.4 OLN tick-artifact {symbol}/{date}: warm boundaries={len(boundaries)}, "
        f"median spread_ticks={med}, half-tick quantum mass="
        f"{'n/a' if mass is None else f'{mass:.3f}'} (n={n_moves})",
        file=sys.stderr,
    )


def _h10_sweep_kyle(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    session_open_ns: int,
) -> list[_Row]:
    """Protocol §2.2 H10 rows for one (symbol, date) — SFI extreme vs interior."""
    snaps = _replay_snapshots(
        events,
        symbol=symbol,
        horizon_features=_h10_features(),
        horizons=frozenset({_H10_HORIZON}),
        session_open_ns=session_open_ns,
        sensor_specs=_H10_SENSOR_SPECS,
    )
    strata = ("extreme", "interior")
    pairs = {s: _Pairs(values=[], fwd=[]) for s in strata}
    oln_boundaries: list[tuple[int, float]] = []
    for s in snaps:
        if s.horizon_seconds != _H10_HORIZON:
            continue
        if not all(
            s.warm.get(fid, False) and not s.stale.get(fid, True) for fid in _H10_CONSUMED_IDS
        ):
            continue
        sfi = s.values.get("sweep_flow_imbalance")
        pctl = s.values.get("sweep_flow_imbalance_percentile")
        if sfi is None or pctl is None:
            continue
        asof_ns = s.boundary_ts_ns
        if symbol in _H10_EVIDENCE_ONLY_SYMBOLS:
            oln_boundaries.append((asof_ns, sfi))
            continue
        y = _forward_return(mids, asof_ns, _H10_HORIZON)
        if y is None:
            continue
        # Extreme stratum requires sign agreement with the decile arm.
        if pctl >= _H10_SFI_PCTL_HI and sfi > 0.0:
            stratum = "extreme"
        elif pctl <= _H10_SFI_PCTL_LO and sfi < 0.0:
            stratum = "extreme"
        elif _H10_SFI_PCTL_LO < pctl < _H10_SFI_PCTL_HI:
            stratum = "interior"
        else:
            continue  # sign-disagreement at extreme — not in either IC stratum
        pairs[stratum].values.append(sfi)
        pairs[stratum].fwd.append(y)

    if symbol in _H10_EVIDENCE_ONLY_SYMBOLS:
        _h10_oln_tick_artifact_report(events, mids, symbol, date, oln_boundaries)
        return []

    rows: list[_Row] = [
        _h10_rank_row(symbol, date, "extreme", pairs["extreme"], with_edge=True),
        _h10_rank_row(symbol, date, "interior", pairs["interior"], with_edge=False),
    ]
    e = rows[0]
    b = rows[1]
    contrast = e.rank_ic - b.rank_ic if e.rank_ic is not None and b.rank_ic is not None else None
    rows.append(
        _Row(
            symbol=symbol,
            date=date,
            feature="h10_sweep_kyle",
            horizon=_H10_HORIZON,
            variant="sfi_contrast",
            n=min(e.n, b.n),
            rank_ic=contrast,
            ic=None,
        )
    )
    ep = pairs["extreme"]
    if len(ep.values) >= 5:
        buckets = bucketed_forward_return(ep.values, ep.fwd, n_buckets=5)
        means = ", ".join(f"{b_.mean_forward_return * 1e4:+.2f}" for b_ in buckets)
        print(
            f"  # H10 buckets(extreme) {symbol}/{date}: [{means}] bps",
            file=sys.stderr,
        )
    return rows


# ── H12 row — sig_halfhour_clock_drift_h900_v1 (protocol §2.2; Task 9-A)
#
# Measurement plumbing for the pre-registered H12 primary trial, not a new
# trial: x = ofi_integrated (signed) vs y = signed forward 900 s mid
# log-return, stratified by the census-pinned extreme-OFI quintile
# (percentile ≥ 0.80 OR ≤ 0.20 with sign agreement) into:
#   * in_window_extreme  (W_hh = 1 — ALGO_CLOCK membership)
#   * out_window_extreme (W_hh = 0 — matched OFI, F2 arm)
#   * clock_contrast     (in RankIC − out RankIC)
# OLN cells are evidence-only §2.4 tick-artifact inputs — empty IC rows.
# Phase A lands the instrument only — no cached-data IC run (N = 12).

_H12_HORIZON = 900
_H12_OFI_PCTL_HI = 0.80
_H12_OFI_PCTL_LO = 0.20
_H12_EVIDENCE_ONLY_SYMBOLS = frozenset({"OLN"})
_H12_CONSUMED_IDS = (
    "scheduled_flow_window_active",
    "ofi_integrated",
    "ofi_integrated_percentile",
    "realized_vol_30s_zscore",
)


def _h12_load_calendar(date_str: str) -> EventCalendar | None:
    path = EVENT_CALENDAR_DIR / f"{date_str}.yaml"
    if not path.is_file():
        return None
    return load_event_calendar(path, expected_session_date=_date.fromisoformat(date_str))


def _h12_sensor_specs(calendar: EventCalendar) -> tuple[SensorSpec, ...]:
    return (
        SensorSpec(
            sensor_id="scheduled_flow_window",
            sensor_version="1.2.0",
            cls=ScheduledFlowWindowSensor,
            params={"calendar": calendar},
            subscribes_to=(NBBOQuote, Trade),
        ),
        SensorSpec(
            sensor_id="ofi_raw",
            sensor_version="1.0.0",
            cls=OFIRawSensor,
            params={"warm_after": 50, "warm_window_seconds": 300},
            subscribes_to=(NBBOQuote,),
        ),
        SensorSpec(
            sensor_id="realized_vol_30s",
            sensor_version="1.3.0",
            cls=RealizedVol30sSensor,
            params={"window_seconds": 30, "warm_after": 16},
            subscribes_to=(NBBOQuote,),
        ),
    )


def _h12_features() -> list[HorizonFeature]:
    h = _H12_HORIZON
    feats: list[HorizonFeature] = []
    for sid in ("scheduled_flow_window", "ofi_raw", "realized_vol_30s"):
        feats.extend(_horizon_features_for(sid, h))
    return feats


def _h12_rank_row(symbol: str, date: str, variant: str, p: _Pairs, *, with_edge: bool) -> _Row:
    n = len(p.values)
    rank_ic = ic = p_value = None
    if n >= 3:
        res = spearman_ic(p.values, p.fwd)
        rank_ic, p_value = res.rho, res.p_value
        ic = _pearson(p.values, p.fwd)
    edge = long_short_edge_bps(p.values, p.fwd) if with_edge and n >= 5 else None
    return _Row(
        symbol=symbol,
        date=date,
        feature="h12_halfhour_clock",
        horizon=_H12_HORIZON,
        variant=variant,
        n=n,
        rank_ic=rank_ic,
        ic=ic,
        edge_bps=edge,
        pairs=p if edge is not None else None,
        p_value=p_value,
    )


def _h12_halfhour_clock(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    session_open_ns: int,
    *,
    calendar: EventCalendar | None = None,
) -> list[_Row]:
    """Protocol §2.2 H12 rows — clock-stratified extreme-OFI contrast (both arms)."""
    if symbol in _H12_EVIDENCE_ONLY_SYMBOLS:
        return []
    cal = calendar if calendar is not None else _h12_load_calendar(date)
    if cal is None:
        print(
            f"  # H12 skip {symbol}/{date}: no event calendar YAML",
            file=sys.stderr,
        )
        return []

    snaps = _replay_snapshots(
        events,
        symbol=symbol,
        horizon_features=_h12_features(),
        horizons=frozenset({_H12_HORIZON}),
        session_open_ns=session_open_ns,
        sensor_specs=_h12_sensor_specs(cal),
    )
    strata = ("in_window_extreme", "out_window_extreme")
    pairs = {s: _Pairs(values=[], fwd=[]) for s in strata}
    for s in snaps:
        if s.horizon_seconds != _H12_HORIZON:
            continue
        if not all(
            s.warm.get(fid, False) and not s.stale.get(fid, True) for fid in _H12_CONSUMED_IDS
        ):
            continue
        ofi = s.values.get("ofi_integrated")
        pctl = s.values.get("ofi_integrated_percentile")
        w_hh = s.values.get("scheduled_flow_window_active")
        if ofi is None or pctl is None or w_hh is None:
            continue
        asof_ns = s.boundary_ts_ns
        y = _forward_return(mids, asof_ns, _H12_HORIZON)
        if y is None:
            continue
        # Extreme stratum + sign agreement (census §1.1 arms 4/7).
        if pctl >= _H12_OFI_PCTL_HI and ofi > 0.0:
            pass
        elif pctl <= _H12_OFI_PCTL_LO and ofi < 0.0:
            pass
        else:
            continue
        stratum = "in_window_extreme" if w_hh >= 0.5 else "out_window_extreme"
        pairs[stratum].values.append(ofi)
        pairs[stratum].fwd.append(y)

    rows: list[_Row] = [
        _h12_rank_row(symbol, date, "in_window_extreme", pairs["in_window_extreme"], with_edge=True),
        _h12_rank_row(
            symbol, date, "out_window_extreme", pairs["out_window_extreme"], with_edge=True
        ),
    ]
    e = rows[0]
    b = rows[1]
    contrast = e.rank_ic - b.rank_ic if e.rank_ic is not None and b.rank_ic is not None else None
    rows.append(
        _Row(
            symbol=symbol,
            date=date,
            feature="h12_halfhour_clock",
            horizon=_H12_HORIZON,
            variant="clock_contrast",
            n=min(e.n, b.n),
            rank_ic=contrast,
            ic=None,
        )
    )
    return rows


# ── H13 row — sig_hour_checkpoint_drift_h1800_v1 (protocol §2.2; Task 9-A)
#
# Measurement plumbing for the pre-registered H13 primary trial, not a new
# trial: x = ofi_integrated (signed) vs y = signed forward 1800 s mid
# log-return, stratified by the census-pinned extreme-OFI quintile
# (percentile ≥ 0.80 OR ≤ 0.20 with sign agreement) into:
#   * in_hour_extreme     (W_hr = 1 — hour-only ALGO_CLOCK membership)
#   * halfhour_extreme    (W_hr = 0 — matched OFI at :30, F2 arm)
#   * hour_contrast       (in RankIC − halfhour RankIC)
# Eight-symbol evidence pool (incl. ENSG/MLI) produces IC rows — JC-12.
# Calendar injection = hour-only derived view (:30 excluded).
# Phase A lands the instrument only — no cached-data IC run (N = 12).

_H13_HORIZON = 1800
_H13_OFI_PCTL_HI = 0.80
_H13_OFI_PCTL_LO = 0.20
_H13_CONSUMED_IDS = (
    "scheduled_flow_window_active",
    "ofi_integrated",
    "ofi_integrated_percentile",
    "realized_vol_30s_zscore",
)


def _h13_load_hour_only_calendar(date_str: str) -> EventCalendar | None:
    from scripts.research.derive_hour_only_algo_clock_calendars import (
        load_hour_only_calendar,
    )

    return load_hour_only_calendar(date_str)


def _h13_sensor_specs(calendar: EventCalendar) -> tuple[SensorSpec, ...]:
    return (
        SensorSpec(
            sensor_id="scheduled_flow_window",
            sensor_version="1.2.0",
            cls=ScheduledFlowWindowSensor,
            params={"calendar": calendar},
            subscribes_to=(NBBOQuote, Trade),
        ),
        SensorSpec(
            sensor_id="ofi_raw",
            sensor_version="1.0.0",
            cls=OFIRawSensor,
            params={"warm_after": 50, "warm_window_seconds": 300},
            subscribes_to=(NBBOQuote,),
        ),
        SensorSpec(
            sensor_id="realized_vol_30s",
            sensor_version="1.3.0",
            cls=RealizedVol30sSensor,
            params={"window_seconds": 30, "warm_after": 16},
            subscribes_to=(NBBOQuote,),
        ),
    )


def _h13_features() -> list[HorizonFeature]:
    h = _H13_HORIZON
    feats: list[HorizonFeature] = []
    for sid in ("scheduled_flow_window", "ofi_raw", "realized_vol_30s"):
        feats.extend(_horizon_features_for(sid, h))
    return feats


def _h13_rank_row(symbol: str, date: str, variant: str, p: _Pairs, *, with_edge: bool) -> _Row:
    n = len(p.values)
    rank_ic = ic = p_value = None
    if n >= 3:
        res = spearman_ic(p.values, p.fwd)
        rank_ic, p_value = res.rho, res.p_value
        ic = _pearson(p.values, p.fwd)
    edge = long_short_edge_bps(p.values, p.fwd) if with_edge and n >= 5 else None
    return _Row(
        symbol=symbol,
        date=date,
        feature="h13_hour_checkpoint",
        horizon=_H13_HORIZON,
        variant=variant,
        n=n,
        rank_ic=rank_ic,
        ic=ic,
        edge_bps=edge,
        pairs=p if edge is not None else None,
        p_value=p_value,
    )


def _h13_hour_checkpoint(
    events: Sequence[NBBOQuote | Trade],
    mids: "_MidSeries",
    symbol: str,
    date: str,
    session_open_ns: int,
    *,
    calendar: EventCalendar | None = None,
) -> list[_Row]:
    """Protocol §2.2 H13 rows — hour-stratified extreme-OFI contrast (both arms)."""
    cal = calendar if calendar is not None else _h13_load_hour_only_calendar(date)
    if cal is None:
        print(
            f"  # H13 skip {symbol}/{date}: no hour-only calendar view",
            file=sys.stderr,
        )
        return []

    snaps = _replay_snapshots(
        events,
        symbol=symbol,
        horizon_features=_h13_features(),
        horizons=frozenset({_H13_HORIZON}),
        session_open_ns=session_open_ns,
        sensor_specs=_h13_sensor_specs(cal),
    )
    strata = ("in_hour_extreme", "halfhour_extreme")
    pairs = {s: _Pairs(values=[], fwd=[]) for s in strata}
    for s in snaps:
        if s.horizon_seconds != _H13_HORIZON:
            continue
        if not all(
            s.warm.get(fid, False) and not s.stale.get(fid, True) for fid in _H13_CONSUMED_IDS
        ):
            continue
        ofi = s.values.get("ofi_integrated")
        pctl = s.values.get("ofi_integrated_percentile")
        w_hr = s.values.get("scheduled_flow_window_active")
        if ofi is None or pctl is None or w_hr is None:
            continue
        asof_ns = s.boundary_ts_ns
        y = _forward_return(mids, asof_ns, _H13_HORIZON)
        if y is None:
            continue
        # Extreme stratum + sign agreement (census §1.1 arms 4/7).
        if pctl >= _H13_OFI_PCTL_HI and ofi > 0.0:
            pass
        elif pctl <= _H13_OFI_PCTL_LO and ofi < 0.0:
            pass
        else:
            continue
        stratum = "in_hour_extreme" if w_hr >= 0.5 else "halfhour_extreme"
        pairs[stratum].values.append(ofi)
        pairs[stratum].fwd.append(y)

    rows: list[_Row] = [
        _h13_rank_row(symbol, date, "in_hour_extreme", pairs["in_hour_extreme"], with_edge=True),
        _h13_rank_row(
            symbol, date, "halfhour_extreme", pairs["halfhour_extreme"], with_edge=True
        ),
    ]
    e = rows[0]
    b = rows[1]
    contrast = e.rank_ic - b.rank_ic if e.rank_ic is not None and b.rank_ic is not None else None
    rows.append(
        _Row(
            symbol=symbol,
            date=date,
            feature="h13_hour_checkpoint",
            horizon=_H13_HORIZON,
            variant="hour_contrast",
            n=min(e.n, b.n),
            rank_ic=contrast,
            ic=None,
        )
    )
    return rows


def _fmt(x: float | None) -> str:
    return "   n/a" if x is None else f"{x:+.4f}"


def _print_table(rows: list[_Row]) -> None:
    hdr = (
        f"{'feature':<24}{'horizon':>8}{'variant':>26}{'n':>7}"
        f"{'RankIC':>9}{'IC':>9}{'t':>8}{'edgeBps':>9}{'p':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    rows_sorted = sorted(rows, key=lambda r: (r.feature, r.horizon, r.variant))
    for r in rows_sorted:
        t = r.tstat
        t_s = "   n/a" if t is None else f"{t:+.2f}"
        e_s = "   n/a" if r.edge_bps is None else f"{r.edge_bps:+.2f}"
        p_s = "       n/a" if r.p_value is None else f"{r.p_value:>10.2e}"
        print(
            f"{r.feature:<24}{r.horizon:>8}{r.variant:>26}{r.n:>7}"
            f"{_fmt(r.rank_ic):>9}{_fmt(r.ic):>9}{t_s:>8}{e_s:>9}{p_s:>10}"
        )


def _aggregate_across_days(rows: list[_Row]) -> list[_Row]:
    """Pool RankIC across (symbol,date) by sample-weighted mean per
    (feature, horizon, variant) so multi-day runs get one headline row."""
    buckets: dict[tuple[str, int, str], list[_Row]] = {}
    for r in rows:
        buckets.setdefault((r.feature, r.horizon, r.variant), []).append(r)
    pooled: list[_Row] = []
    for (feature, horizon, variant), rs in buckets.items():
        ric_rows = [r for r in rs if r.rank_ic is not None]
        ic_rows = [r for r in rs if r.ic is not None]
        pair_rows = [r for r in rs if r.pairs is not None]

        n_ric = sum(r.n for r in ric_rows)
        n_ic = sum(r.n for r in ic_rows)

        ric = (
            sum(r.rank_ic * r.n for r in ric_rows) / n_ric  # type: ignore[operator]
            if n_ric
            else None
        )
        ic = (
            sum(r.ic * r.n for r in ic_rows) / n_ic  # type: ignore[operator]
            if n_ic
            else None
        )
        # Pooled edge must match the cost-gate primitive (Inv-12 / gas #2):
        # re-bucket on globally-concatenated (feature, forward_return) pairs,
        # not a sample-weighted mean of per-day spreads (which uses each day's
        # own quintile cuts and would disagree with the binding gate).
        pooled_values: list[float] = []
        pooled_fwd: list[float] = []
        for r in pair_rows:
            assert r.pairs is not None
            pooled_values.extend(r.pairs.values)
            pooled_fwd.extend(r.pairs.fwd)
        edge = (
            long_short_edge_bps(pooled_values, pooled_fwd)
            if len(pooled_values) >= 5
            else None
        )
        pooled_pairs = (
            _Pairs(values=pooled_values, fwd=pooled_fwd) if pair_rows else None
        )

        pooled.append(
            _Row(
                symbol="*",
                date="*",
                feature=feature,
                horizon=horizon,
                variant=variant,
                n=max(n_ric, n_ic),
                rank_ic=ric,
                ic=ic,
                edge_bps=edge,
                pairs=pooled_pairs,
            )
        )
    return pooled


def _parse_multi(value: list[str]) -> list[str]:
    out: list[str] = []
    for v in value:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", required=True, type=Path)
    ap.add_argument("--symbol", action="append", default=[], required=True)
    ap.add_argument("--date", action="append", default=[], required=True)
    ap.add_argument("--horizons", default="30,120,300,900,1800")
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args(argv)

    symbols = _parse_multi(args.symbol)
    dates = _parse_multi(args.date)
    horizons = frozenset(int(h) for h in args.horizons.split(","))

    # Zip pairwise when lengths match; else cross-product.
    if len(symbols) == len(dates):
        pairs = list(zip(symbols, dates))
    else:
        pairs = [(s, d) for s in symbols for d in dates]

    cache = DiskEventCache(args.cache_dir)
    all_rows: list[_Row] = []
    for symbol, date in pairs:
        print(f"# {symbol} {date}", file=sys.stderr)
        all_rows.extend(_run_one(cache, symbol, date, horizons))

    if not all_rows:
        print("No data produced — check --cache-dir / symbol / date.", file=sys.stderr)
        return 1

    print("\n== Per (symbol, date) ==")
    _print_table(all_rows)

    if len(pairs) > 1:
        print("\n== Pooled across days (sample-weighted) ==")
        _print_table(_aggregate_across_days(all_rows))

    if args.csv is not None:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "symbol",
                    "date",
                    "feature",
                    "horizon",
                    "variant",
                    "n",
                    "rank_ic",
                    "ic",
                    "tstat",
                    "edge_bps",
                    "p_value",
                ]
            )
            for r in all_rows:
                w.writerow(
                    [
                        r.symbol,
                        r.date,
                        r.feature,
                        r.horizon,
                        r.variant,
                        r.n,
                        r.rank_ic,
                        r.ic,
                        r.tstat,
                        r.edge_bps,
                        r.p_value,
                    ]
                )
        print(f"\nWrote {args.csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
