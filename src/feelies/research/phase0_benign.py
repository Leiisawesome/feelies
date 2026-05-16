"""Phase-0 offline panels for ``sig_benign_midcap_v1``.

Measures falsification-oriented statistics on a replayed session:

* Spearman(OFI, forward 120s mid return) overall and conditional on gate ON/OFF
* Aligned footprint score (OFI z when micro-price z agrees on sign)
* Signal ``edge_estimate_bps`` vs orchestrator B4 threshold (1.5× RT cost)
* Cost stress (1.5×) and latency stress (2× fill latency)

Synthetic sessions are supported for pipeline calibration; pass a JSONL
cache path for economic panels on real data.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bootstrap import build_platform
from feelies.core.events import (
    HorizonFeatureSnapshot,
    NBBOQuote,
    OrderRequest,
    RegimeState,
    SensorReading,
    Signal,
    SignalDirection,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
    estimate_round_trip_cost_bps,
)
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.events import Side

SESSION_OPEN_NS = 1_768_532_400_000_000_000

ALPHA_ID = "sig_benign_midcap_v1"
HORIZON_SECONDS = 120
QUOTE_CADENCE_NS = 100_000_000


@dataclass(frozen=True, slots=True)
class BoundaryRow:
    symbol: str
    boundary_index: int
    timestamp_ns: int
    mid: float
    ofi_ewma: float | None
    ofi_ewma_zscore: float | None
    micro_price_zscore: float | None
    gate_on: bool
    forward_return_bps: float | None


@dataclass(frozen=True, slots=True)
class SpearmanPanel:
    n: int
    rho: float | None
    threshold_falsify: float = 0.05


@dataclass(frozen=True, slots=True)
class B4Panel:
    n_signals: int
    n_with_quote: int
    n_below_b4: int
    n_at_or_above_b4: int
    pct_below_b4: float | None
    edge_bps_p50: float | None
    edge_bps_p90: float | None
    rt_cost_bps_p50: float | None
    min_edge_bps_p50: float | None


@dataclass(frozen=True, slots=True)
class StressCompare:
    label: str
    n_orders: int
    n_signals_long_short: int
    n_trace_no_order: int
    n_trace_b4_suppressed: int


@dataclass
class Phase0Report:
    alpha_id: str
    data_source: str
    symbols: tuple[str, ...]
    n_quotes: int
    n_boundaries: int
    spearman_ofi_vs_fwd_return: SpearmanPanel
    spearman_ofi_gate_on: SpearmanPanel
    spearman_ofi_gate_off: SpearmanPanel
    spearman_footprint_gate_on: SpearmanPanel
    b4: B4Panel
    stress: tuple[StressCompare, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rank(values: list[float]) -> list[float]:
    """Average ranks for Spearman (1-based ranks)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in x))
    den_y = math.sqrt(sum((b - my) ** 2 for b in y))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return num / (den_x * den_y)


def spearman_rho(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    return _pearson(_rank(x), _rank(y))


def _spearman_panel(
    xs: list[float],
    ys: list[float],
) -> SpearmanPanel:
    return SpearmanPanel(n=len(xs), rho=spearman_rho(xs, ys))


def synthesize_multi_symbol_events(
    symbols: tuple[str, ...],
    *,
    quotes_per_symbol: int,
    seed: int = 42,
    session_open_ns: int = SESSION_OPEN_NS,
) -> list[NBBOQuote | Trade]:
    """Interleaved NBBO + trades for mid-cap-style universe."""
    starting_prices_cents: dict[str, int] = {
        "AAPL": 18_000,
        "MSFT": 37_000,
        "NVDA": 45_000,
    }
    all_rows: list[tuple[int, str, NBBOQuote | Trade]] = []
    for sym_idx, symbol in enumerate(symbols):
        rng = random.Random(seed * 100 + sym_idx)
        last_mid = starting_prices_cents.get(symbol, 20_000)
        for i in range(quotes_per_symbol):
            ts_ns = session_open_ns + i * QUOTE_CADENCE_NS
            last_mid += rng.choice((-1, 0, 0, 0, 1))
            bid = Decimal(last_mid) / Decimal(100)
            ask = Decimal(last_mid + 1) / Decimal(100)
            quote = NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=sym_idx * quotes_per_symbol + i,
                correlation_id=f"phase0-q-{symbol}-{i}",
                source_layer="INGESTION",
                symbol=symbol,
                bid=bid,
                ask=ask,
                bid_size=rng.choice((100, 200, 300, 400, 500)),
                ask_size=rng.choice((100, 200, 300, 400, 500)),
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11,
                ask_exchange=11,
                tape=3,
            )
            all_rows.append((ts_ns, symbol, quote))
            if i % 7 == 0 and i > 0:
                side_buy = rng.random() < 0.5
                price = Decimal(last_mid + (1 if side_buy else 0)) / Decimal(100)
                trade = Trade(
                    timestamp_ns=ts_ns + 1,
                    sequence=sym_idx * quotes_per_symbol * 2 + i,
                    correlation_id=f"phase0-t-{symbol}-{i}",
                    source_layer="INGESTION",
                    symbol=symbol,
                    price=price,
                    size=rng.choice((50, 100, 150, 200)),
                    exchange=11,
                    trade_id=f"phase0-{symbol}-{i:08d}",
                    exchange_timestamp_ns=ts_ns + 1,
                    tape=3,
                )
                all_rows.append((ts_ns + 1, symbol, trade))
    all_rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in all_rows]


def load_events_from_jsonl(path: Path) -> list[NBBOQuote | Trade]:
    events: list[NBBOQuote | Trade] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            data = json.loads(line)
            kind = data.pop("kind")
            if kind == "NBBOQuote":
                data["bid"] = Decimal(data["bid"])
                data["ask"] = Decimal(data["ask"])
                events.append(NBBOQuote(**data))
            elif kind == "Trade":
                data["price"] = Decimal(data["price"])
                events.append(Trade(**data))
    return events


def _mid_from_quote(q: NBBOQuote) -> float:
    return float((q.bid + q.ask) / 2)


def _build_boundary_rows(
    snapshots: list[HorizonFeatureSnapshot],
    *,
    gate: Any,
    sensor_cache_timeline: list[tuple[int, dict[tuple[str, str], float]]],
    regime_timeline: list[tuple[int, dict[str, RegimeState]]],
) -> list[BoundaryRow]:
    """Replay gate latch in timestamp order and attach forward 120s returns."""
    by_symbol: dict[str, list[BoundaryRow]] = defaultdict(list)
    # Index sensor/regime state at each snapshot time (latest at or before).
    snap_sorted = sorted(
        (s for s in snapshots if s.horizon_seconds == HORIZON_SECONDS),
        key=lambda s: (s.timestamp_ns, s.symbol),
    )
    sensor_idx = 0
    regime_idx = 0
    sensor_now: dict[tuple[str, str], float] = {}
    regime_now: dict[str, RegimeState] = {}

    for snap in snap_sorted:
        while (
            sensor_idx < len(sensor_cache_timeline)
            and sensor_cache_timeline[sensor_idx][0] <= snap.timestamp_ns
        ):
            sensor_now = sensor_cache_timeline[sensor_idx][1]
            sensor_idx += 1
        while (
            regime_idx < len(regime_timeline)
            and regime_timeline[regime_idx][0] <= snap.timestamp_ns
        ):
            for sym, st in regime_timeline[regime_idx][1].items():
                regime_now[sym] = st
            regime_idx += 1

        regime = regime_now.get(snap.symbol)
        bindings = HorizonSignalEngine._build_bindings(
            snap, regime, sensor_now,
        )
        try:
            gate_on = gate.evaluate(symbol=snap.symbol, bindings=bindings)
        except Exception:
            gate_on = False

        mid = float(snap.values.get("micro_price", 0.0) or 0.0)
        if mid <= 0.0:
            # Fall back: micro_price passthrough is tilt; use placeholder — filled later
            mid = float("nan")

        row = BoundaryRow(
            symbol=snap.symbol,
            boundary_index=snap.boundary_index,
            timestamp_ns=snap.timestamp_ns,
            mid=mid,
            ofi_ewma=_optional_float(snap.values.get("ofi_ewma")),
            ofi_ewma_zscore=_optional_float(snap.values.get("ofi_ewma_zscore")),
            micro_price_zscore=_optional_float(snap.values.get("micro_price_zscore")),
            gate_on=gate_on,
            forward_return_bps=None,
        )
        by_symbol[snap.symbol].append(row)

    out: list[BoundaryRow] = []
    for sym, rows in by_symbol.items():
        rows.sort(key=lambda r: r.boundary_index)
        for i, row in enumerate(rows):
            fwd_bps: float | None = None
            if i + 1 < len(rows) and row.mid > 0 and rows[i + 1].mid > 0:
                fwd_bps = (rows[i + 1].mid / row.mid - 1.0) * 10_000.0
            out.append(
                replace(row, forward_return_bps=fwd_bps),
            )
    return out


def _optional_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _attach_mids_from_quotes(
    rows: list[BoundaryRow],
    quotes: list[NBBOQuote],
) -> list[BoundaryRow]:
    """Overwrite boundary mids with last quote mid at or before boundary ts."""
    quotes_by_sym: dict[str, list[NBBOQuote]] = defaultdict(list)
    for q in quotes:
        quotes_by_sym[q.symbol].append(q)
    for sym in quotes_by_sym:
        quotes_by_sym[sym].sort(key=lambda q: q.timestamp_ns)

    updated: list[BoundaryRow] = []
    for row in rows:
        qs = quotes_by_sym.get(row.symbol, [])
        mid = row.mid
        for q in reversed(qs):
            if q.timestamp_ns <= row.timestamp_ns:
                mid = _mid_from_quote(q)
                break
        updated.append(replace(row, mid=mid))
    return updated


def _footprint_score(row: BoundaryRow) -> float | None:
    z = row.ofi_ewma_zscore
    zm = row.micro_price_zscore
    if z is None or zm is None:
        return None
    if (z > 0.0 and zm <= 0.0) or (z < 0.0 and zm >= 0.0):
        return None
    return z


def run_phase0(
    config: PlatformConfig,
    events: list[NBBOQuote | Trade],
    *,
    data_source: str,
    loaded: LoadedSignalLayerModule | None = None,
) -> Phase0Report:
    """Replay *events* and compute Phase-0 panels."""
    if loaded is None:
        mod = AlphaLoader(
            enforce_trend_mechanism=config.enforce_trend_mechanism,
        ).load(str(config.alpha_specs[0]))
        assert isinstance(mod, LoadedSignalLayerModule)
        loaded = mod

    event_log = InMemoryEventLog()
    event_log.append_batch(events)

    snapshots: list[HorizonFeatureSnapshot] = []
    sensor_timeline: list[tuple[int, dict[tuple[str, str], float]]] = []
    regime_timeline: list[tuple[int, dict[str, RegimeState]]] = []
    sensor_now: dict[tuple[str, str], float] = {}
    regime_now: dict[str, RegimeState] = {}

    trace_sink: list[SignalOrderTraceRow] = []
    signals: list[Signal] = []
    orders: list[OrderRequest] = []
    quotes: list[NBBOQuote] = [e for e in events if isinstance(e, NBBOQuote)]

    orchestrator, cfg = build_platform(
        config,
        event_log=event_log,
        signal_order_trace_sink=trace_sink,
    )
    bus = orchestrator._bus
    bus.subscribe(HorizonFeatureSnapshot, snapshots.append)
    bus.subscribe(Signal, signals.append)
    bus.subscribe(OrderRequest, orders.append)

    def _on_sensor(r: SensorReading) -> None:
        nonlocal sensor_now
        sensor_now = dict(sensor_now)
        sensor_now[(r.symbol, r.sensor_id)] = float(r.value)
        sensor_timeline.append((r.timestamp_ns, sensor_now))

    def _on_regime(r: RegimeState) -> None:
        nonlocal regime_now
        regime_now = dict(regime_now)
        regime_now[r.symbol] = r
        regime_timeline.append((r.timestamp_ns, dict(regime_now)))

    bus.subscribe(SensorReading, _on_sensor)
    bus.subscribe(RegimeState, _on_regime)

    orchestrator.boot(cfg)
    assert orchestrator._macro.state == MacroState.READY
    orchestrator.run_backtest()

    panel_gate = loaded.gate
    panel_gate.reset(None)
    boundary_rows = _attach_mids_from_quotes(
        _build_boundary_rows(
            snapshots,
            gate=panel_gate,
            sensor_cache_timeline=sensor_timeline,
            regime_timeline=regime_timeline,
        ),
        quotes,
    )

    def _pairs(
        rows: list[BoundaryRow],
        *,
        x_fn: Any,
        gate_on: bool | None = None,
    ) -> tuple[list[float], list[float]]:
        xs: list[float] = []
        ys: list[float] = []
        for row in rows:
            if row.forward_return_bps is None:
                continue
            if gate_on is not None and row.gate_on != gate_on:
                continue
            x = x_fn(row)
            if x is None:
                continue
            xs.append(x)
            ys.append(row.forward_return_bps)
        return xs, ys

    all_x, all_y = _pairs(
        boundary_rows,
        x_fn=lambda r: r.ofi_ewma,
    )
    on_x, on_y = _pairs(
        boundary_rows,
        x_fn=lambda r: r.ofi_ewma,
        gate_on=True,
    )
    off_x, off_y = _pairs(
        boundary_rows,
        x_fn=lambda r: r.ofi_ewma,
        gate_on=False,
    )
    fp_x, fp_y = _pairs(
        boundary_rows,
        x_fn=_footprint_score,
        gate_on=True,
    )

    benign_signals = [
        s for s in signals
        if s.strategy_id == ALPHA_ID
        and s.direction in (SignalDirection.LONG, SignalDirection.SHORT)
    ]

    b4 = _b4_panel(
        benign_signals,
        trace_sink,
        config,
        quotes,
    )

    stress = (
        _stress_pass(config, events, loaded, label="baseline"),
        _stress_pass(
            replace(config, cost_stress_multiplier=1.5),
            events,
            loaded,
            label="cost_1.5x",
        ),
        _stress_pass(
            replace(config, backtest_fill_latency_ns=config.backtest_fill_latency_ns * 2),
            events,
            loaded,
            label="latency_2x",
        ),
    )

    notes = (
        "Synthetic panels measure pipeline + falsification hooks; "
        "economic significance requires multi-day real JSONL.",
        f"Falsification Spearman < 0.05 flagged when rho is not None and rho < 0.05.",
    )
    if "synthetic" in data_source:
        notes = notes + (
            "Do not promote on synthetic Spearman alone.",
        )

    return Phase0Report(
        alpha_id=ALPHA_ID,
        data_source=data_source,
        symbols=tuple(sorted(config.symbols)),
        n_quotes=len(quotes),
        n_boundaries=len(boundary_rows),
        spearman_ofi_vs_fwd_return=_spearman_panel(all_x, all_y),
        spearman_ofi_gate_on=_spearman_panel(on_x, on_y),
        spearman_ofi_gate_off=_spearman_panel(off_x, off_y),
        spearman_footprint_gate_on=_spearman_panel(fp_x, fp_y),
        b4=b4,
        stress=stress,
        notes=notes,
    )


def _stress_pass(
    config: PlatformConfig,
    events: list[NBBOQuote | Trade],
    loaded: LoadedSignalLayerModule,
    *,
    label: str,
) -> StressCompare:
    trace: list[SignalOrderTraceRow] = []
    signals: list[Signal] = []
    orders: list[OrderRequest] = []
    event_log = InMemoryEventLog()
    event_log.append_batch(events)
    orchestrator, cfg = build_platform(
        config,
        event_log=event_log,
        signal_order_trace_sink=trace,
    )
    bus = orchestrator._bus
    bus.subscribe(Signal, signals.append)
    bus.subscribe(OrderRequest, orders.append)
    orchestrator.boot(cfg)
    orchestrator.run_backtest()
    n_ls = sum(
        1 for s in signals
        if s.strategy_id == ALPHA_ID
        and s.direction in (SignalDirection.LONG, SignalDirection.SHORT)
    )
    n_b4 = sum(
        1 for t in trace
        if t.strategy_id == ALPHA_ID
        and "signal_edge_below_min_edge_cost_ratio_gate" in t.reasons
    )
    n_no = sum(
        1 for t in trace
        if t.strategy_id == ALPHA_ID and t.outcome == "NO_ORDER"
    )
    return StressCompare(
        label=label,
        n_orders=sum(1 for o in orders if o.symbol in config.symbols),
        n_signals_long_short=n_ls,
        n_trace_no_order=n_no,
        n_trace_b4_suppressed=n_b4,
    )


def _b4_panel(
    signals: list[Signal],
    trace: list[SignalOrderTraceRow],
    config: PlatformConfig,
    quotes: list[NBBOQuote],
) -> B4Panel:
    cost_model = DefaultCostModel(DefaultCostModelConfig(
        min_spread_cost_bps=Decimal(str(config.cost_min_spread_bps)),
        commission_per_share=Decimal(str(config.cost_commission_per_share)),
        taker_exchange_per_share=Decimal(str(config.cost_taker_exchange_per_share)),
        maker_exchange_per_share=Decimal(str(config.cost_maker_exchange_per_share)),
        passive_adverse_selection_bps=Decimal(
            str(config.cost_passive_adverse_selection_bps),
        ),
        sell_regulatory_bps=Decimal(str(config.cost_sell_regulatory_bps)),
        stress_multiplier=Decimal(str(config.cost_stress_multiplier)),
        min_commission=Decimal(str(config.cost_min_commission)),
        max_commission_pct=Decimal(str(config.cost_max_commission_pct)),
        htb_borrow_annual_bps=Decimal(str(config.cost_htb_borrow_annual_bps)),
    ))
    ratio = config.signal_min_edge_cost_ratio
    use_passive = config.execution_mode == "passive_limit"

    quotes_by_sym: dict[str, list[NBBOQuote]] = defaultdict(list)
    for q in quotes:
        quotes_by_sym[q.symbol].append(q)
    for sym in quotes_by_sym:
        quotes_by_sym[sym].sort(key=lambda q: q.timestamp_ns)

    edges: list[float] = []
    rt_costs: list[float] = []
    min_edges: list[float] = []
    below = 0
    above = 0
    with_quote = 0

    for sig in signals:
        edges.append(sig.edge_estimate_bps)
        qs = quotes_by_sym.get(sig.symbol, [])
        if not qs:
            continue
        q = qs[-1]
        for qq in reversed(qs):
            if qq.timestamp_ns <= sig.timestamp_ns:
                q = qq
                break
        with_quote += 1
        mid = (q.bid + q.ask) / Decimal(2)
        half_spread = (q.ask - q.bid) / Decimal(2)
        side = Side.BUY if sig.direction == SignalDirection.LONG else Side.SELL
        rt = estimate_round_trip_cost_bps(
            cost_model,
            symbol=sig.symbol,
            entry_side=side,
            quantity=config.platform_min_order_shares,
            mid_price=mid,
            half_spread=half_spread,
            is_taker=not use_passive,
            is_short_entry=sig.direction == SignalDirection.SHORT,
            is_taker_exit=True,
        )
        rt_costs.append(rt)
        min_edge = ratio * rt
        min_edges.append(min_edge)
        if sig.edge_estimate_bps < min_edge:
            below += 1
        else:
            above += 1

    def _pctile(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        idx = int(round((len(s) - 1) * p))
        return s[idx]

    pct_below = (below / with_quote * 100.0) if with_quote else None
    return B4Panel(
        n_signals=len(signals),
        n_with_quote=with_quote,
        n_below_b4=below,
        n_at_or_above_b4=above,
        pct_below_b4=pct_below,
        edge_bps_p50=_pctile(edges, 0.5),
        edge_bps_p90=_pctile(edges, 0.9),
        rt_cost_bps_p50=_pctile(rt_costs, 0.5),
        min_edge_bps_p50=_pctile(min_edges, 0.5),
    )


def write_report(report: Phase0Report, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "Phase0Report",
    "run_phase0",
    "synthesize_multi_symbol_events",
    "write_report",
]
