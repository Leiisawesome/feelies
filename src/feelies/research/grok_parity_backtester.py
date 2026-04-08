"""Grok-parity backtest harness — replicates Grok REPL exact backtest semantics.

Research-only module.  Zero modifications to production code.

Key differences from the production backtester:
- Fill price: spread-crossing (buy @ ask, sell @ bid) instead of mid-price
- Probabilistic fills with seeded instance RNG
- Latency simulation via pending-order model
- Full transaction-cost stack (exchange + SEC + FINRA + impact)
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.registry import AlphaRegistry
from feelies.alpha.composite import CompositeFeatureEngine
from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade, Signal, SignalDirection


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class GrokTCConfig:
    """Transaction-cost parameters beyond the spread."""

    exchange_fee_per_share: float = 0.003
    sec_fee_per_dollar: float = 0.0000278
    finra_taf_per_share: float = 0.000119
    impact_eta: float = 0.1
    daily_adv_shares: int = 50_000_000


@dataclass
class GrokTradeRecord:
    """Single round-trip trade record."""

    entry_time_ns: int
    exit_time_ns: int
    direction: int  # +1 long, -1 short
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    tc: float
    net_pnl: float
    holding_seconds: float
    signal_value: float
    entry_spread_bps: float
    exit_spread_bps: float


@dataclass
class GrokBacktestMetrics:
    """Aggregate metrics from a parity backtest run."""

    n_trades: int = 0
    n_signals: int = 0
    n_fills: int = 0
    n_rejected_fills: int = 0
    sharpe: float = 0.0
    hit_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    gross_pnl: float = 0.0
    total_tc: float = 0.0
    tc_drag_pct: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_holding_seconds: float = 0.0
    annualized_sharpe: float = 0.0
    latency_ms: float = 0.0
    fill_probability: float = 0.0
    pnl_hash: str = ""


# ── Internal helpers ────────────────────────────────────────────────


@dataclass
class _PendingOrder:
    """Order waiting for latency window to elapse."""

    signal_time_ns: int
    execute_at_ns: int
    direction: int  # +1 or -1
    signal_value: float
    spread_bps: float


@dataclass
class _OpenPosition:
    """Currently held position."""

    entry_time_ns: int
    direction: int
    entry_price: float
    quantity: int
    signal_value: float
    entry_spread_bps: float


def _compute_tc(
    price: float,
    quantity: int,
    spread: float,
    config: GrokTCConfig,
) -> float:
    """Transaction costs BEYOND the spread (spread is already in the fill price)."""
    notional = price * quantity
    exchange = config.exchange_fee_per_share * quantity
    sec = config.sec_fee_per_dollar * notional
    finra = config.finra_taf_per_share * quantity
    sigma = spread / max(price, 1e-12)
    impact = (
        sigma
        * math.sqrt(quantity / max(config.daily_adv_shares, 1))
        * config.impact_eta
        * notional
    )
    return exchange + sec + finra + impact


def _spread_bps(quote: NBBOQuote) -> float:
    ask = float(quote.ask)
    bid = float(quote.bid)
    mid = (ask + bid) / 2.0
    if mid <= 0:
        return 0.0
    return (ask - bid) / mid * 10_000


def _compute_metrics(
    trades: list[GrokTradeRecord],
    n_signals: int,
    n_fills: int,
    n_rejected: int,
    latency_ms: float,
    fill_probability: float,
) -> GrokBacktestMetrics:
    metrics = GrokBacktestMetrics(
        n_trades=len(trades),
        n_signals=n_signals,
        n_fills=n_fills,
        n_rejected_fills=n_rejected,
        latency_ms=latency_ms,
        fill_probability=fill_probability,
    )
    if not trades:
        return metrics

    pnls = [t.net_pnl for t in trades]
    gross_pnls = [t.gross_pnl for t in trades]

    metrics.total_pnl = sum(pnls)
    metrics.gross_pnl = sum(gross_pnls)
    metrics.total_tc = sum(t.tc for t in trades)
    metrics.avg_pnl = metrics.total_pnl / len(pnls)
    metrics.hit_rate = sum(1 for p in pnls if p > 0) / len(pnls)
    metrics.avg_holding_seconds = (
        sum(t.holding_seconds for t in trades) / len(trades)
    )

    if metrics.gross_pnl != 0:
        metrics.tc_drag_pct = metrics.total_tc / abs(metrics.gross_pnl) * 100

    # Sharpe
    if len(pnls) > 1:
        mean = metrics.avg_pnl
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        metrics.sharpe = mean / std if std > 0 else 0.0
        metrics.annualized_sharpe = metrics.sharpe * math.sqrt(252)

    # Profit factor
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    metrics.profit_factor = gains / losses if losses > 0 else float("inf")

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    metrics.max_drawdown = max_dd

    # PnL hash for parity verification
    metrics.pnl_hash = hashlib.sha256(
        json.dumps([round(p, 8) for p in pnls]).encode()
    ).hexdigest()[:16]

    return metrics


# ── Core engine ─────────────────────────────────────────────────────


class GrokParityBacktester:
    """Event-driven backtester matching Grok REPL semantics exactly."""

    def __init__(
        self,
        latency_ms: float = 100.0,
        fill_probability: float = 0.7,
        tc_config: GrokTCConfig | None = None,
        default_quantity: int = 100,
        random_seed: int = 42,
    ) -> None:
        self._latency_ns = int(latency_ms * 1_000_000)
        self._fill_probability = fill_probability
        self._tc_config = tc_config or GrokTCConfig()
        self._default_quantity = default_quantity
        self._rng = random.Random(random_seed)

    @staticmethod
    def _fill_price(quote: NBBOQuote, direction: int) -> float:
        """Spread-crossing fill: BUY at ASK, SELL at BID."""
        if direction > 0:
            return float(quote.ask)
        return float(quote.bid)

    def run(
        self,
        alpha_module: Any,
        event_log: Any,
        start_sequence: int = 0,
        end_sequence: int | None = None,
        regime_engine: Any | None = None,
        trace_file: Any | None = None,
    ) -> tuple[list[GrokTradeRecord], GrokBacktestMetrics]:
        """Run parity backtest over an event log.

        Returns (trades, metrics).

        When called via ``run_from_spec()``, the regime engine is already
        created and shared with the ``AlphaLoader`` so the signal
        namespace's ``regime_posteriors`` reads from the same instance
        that receives ``posterior()`` updates here.

        If *trace_file* is a writable file object, a JSONL parity trace
        is emitted for every signal, fill, reject, and trade — enabling
        tick-level diff against a Grok reference trace.
        """
        clock = SimulatedClock()
        registry = AlphaRegistry()
        registry.register(alpha_module)
        feature_engine = CompositeFeatureEngine(registry, clock, parity_mode=True)

        if regime_engine is None:
            try:
                from feelies.services.regime_engine import get_regime_engine

                regime_engine = get_regime_engine("hmm_3state_fractional")
            except Exception:
                pass

        def _trace(record: dict[str, Any]) -> None:
            if trace_file is not None:
                trace_file.write(json.dumps(record, default=str) + "\n")

        trades: list[GrokTradeRecord] = []
        pending: _PendingOrder | None = None
        position: _OpenPosition | None = None
        n_signals = 0
        n_fills = 0
        n_rejected = 0
        tick_idx = 0

        for event in event_log.replay(start_sequence, end_sequence):
            if isinstance(event, Trade):
                if event.exchange_timestamp_ns > clock.now_ns():
                    clock.set_time(event.exchange_timestamp_ns)
                feature_engine.process_trade(event)
                continue

            if not isinstance(event, NBBOQuote):
                continue

            ts = event.exchange_timestamp_ns
            if ts > clock.now_ns():
                clock.set_time(ts)
            tick_idx += 1

            if regime_engine is not None:
                try:
                    regime_engine.posterior(event)
                except Exception:
                    pass

            # Check pending order (latency execution)
            if pending is not None and ts >= pending.execute_at_ns:
                rng_val = self._rng.random()
                if rng_val <= self._fill_probability:
                    fill_price = self._fill_price(event, pending.direction)
                    position = _OpenPosition(
                        entry_time_ns=ts,
                        direction=pending.direction,
                        entry_price=fill_price,
                        quantity=self._default_quantity,
                        signal_value=pending.signal_value,
                        entry_spread_bps=pending.spread_bps,
                    )
                    n_fills += 1
                    _trace({"type": "fill", "tick": tick_idx, "ts": ts,
                            "direction": pending.direction, "price": fill_price,
                            "rng": round(rng_val, 10)})
                else:
                    n_rejected += 1
                    _trace({"type": "reject", "tick": tick_idx, "ts": ts,
                            "rng": round(rng_val, 10)})
                pending = None

            features = feature_engine.update(event)
            if not features.warm:
                continue

            signal = alpha_module.evaluate(features)
            if signal is None:
                continue

            n_signals += 1

            if signal.direction == SignalDirection.LONG:
                sig_dir = 1
            elif signal.direction == SignalDirection.SHORT:
                sig_dir = -1
            else:
                sig_dir = 0

            _trace({"type": "signal", "tick": tick_idx, "ts": ts,
                    "direction": sig_dir, "strength": round(signal.strength, 8),
                    "edge_bps": round(signal.edge_estimate_bps, 8),
                    "features": {k: round(v, 10) for k, v in features.values.items()}})

            should_exit = position is not None and (
                sig_dir == 0 or sig_dir == -position.direction
            )

            if should_exit:
                exit_price = self._fill_price(event, -position.direction)
                exit_spread_bps = _spread_bps(event)
                spread = float(event.ask) - float(event.bid)

                gross = (
                    (exit_price - position.entry_price)
                    * position.direction
                    * position.quantity
                )
                entry_tc = _compute_tc(
                    position.entry_price,
                    position.quantity,
                    spread,
                    self._tc_config,
                )
                exit_tc = _compute_tc(
                    exit_price,
                    position.quantity,
                    spread,
                    self._tc_config,
                )
                total_tc = entry_tc + exit_tc
                net = gross - total_tc

                holding_ns = ts - position.entry_time_ns
                trade_rec = GrokTradeRecord(
                    entry_time_ns=position.entry_time_ns,
                    exit_time_ns=ts,
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    quantity=position.quantity,
                    gross_pnl=gross,
                    tc=total_tc,
                    net_pnl=net,
                    holding_seconds=holding_ns / 1e9,
                    signal_value=position.signal_value,
                    entry_spread_bps=position.entry_spread_bps,
                    exit_spread_bps=exit_spread_bps,
                )
                trades.append(trade_rec)
                _trace({"type": "trade", "tick": tick_idx, "ts": ts,
                        "dir": trade_rec.direction,
                        "entry": trade_rec.entry_price,
                        "exit": trade_rec.exit_price,
                        "gross": round(trade_rec.gross_pnl, 8),
                        "tc": round(trade_rec.tc, 8),
                        "net": round(trade_rec.net_pnl, 8)})
                position = None

            if sig_dir != 0 and position is None and pending is None:
                pending = _PendingOrder(
                    signal_time_ns=ts,
                    execute_at_ns=ts + self._latency_ns,
                    direction=sig_dir,
                    signal_value=signal.strength,
                    spread_bps=_spread_bps(event),
                )
                _trace({"type": "pending", "tick": tick_idx, "ts": ts,
                        "direction": sig_dir,
                        "execute_at": pending.execute_at_ns})

        metrics = _compute_metrics(
            trades, n_signals, n_fills, n_rejected,
            self._latency_ns / 1_000_000, self._fill_probability,
        )
        return trades, metrics

    def run_from_spec(
        self,
        spec_path: str,
        event_log: Any,
        param_overrides: dict[str, Any] | None = None,
        trace_file: Any | None = None,
    ) -> tuple[list[GrokTradeRecord], GrokBacktestMetrics]:
        """Load an alpha from a .alpha.yaml spec and run the parity backtest.

        Loads ``parity_config.json`` (TC/fill/latency/seed) and
        ``regime_calibration.json`` (HMM emission params) from the
        alpha directory when present, ensuring the backtester matches
        the exact Grok environment that produced the alpha.
        """
        alpha_dir = Path(spec_path).parent.resolve()

        # D3: Load parity_config.json — Grok's exact TC/fill parameters.
        parity_cfg = alpha_dir / "parity_config.json"
        if parity_cfg.exists():
            cfg = json.loads(parity_cfg.read_text(encoding="utf-8"))
            self._latency_ns = int(cfg.get("latency_ms", self._latency_ns / 1_000_000) * 1_000_000)
            self._fill_probability = cfg.get("fill_probability", self._fill_probability)
            self._default_quantity = cfg.get("default_quantity", self._default_quantity)
            seed = cfg.get("random_seed")
            if seed is not None:
                self._rng = random.Random(seed)
            self._tc_config = GrokTCConfig(
                exchange_fee_per_share=cfg.get("exchange_fee_per_share", self._tc_config.exchange_fee_per_share),
                sec_fee_per_dollar=cfg.get("sec_fee_per_dollar", self._tc_config.sec_fee_per_dollar),
                finra_taf_per_share=cfg.get("finra_taf_per_share", self._tc_config.finra_taf_per_share),
                impact_eta=cfg.get("impact_eta", self._tc_config.impact_eta),
                daily_adv_shares=cfg.get("daily_adv_shares", self._tc_config.daily_adv_shares),
            )

        # D2: Load regime_calibration.json — calibrated HMM emission params.
        regime_engine = None
        try:
            from feelies.services.regime_engine import get_regime_engine

            cal_path = alpha_dir / "regime_calibration.json"
            kwargs: dict[str, Any] = {}
            if cal_path.exists():
                cal = json.loads(cal_path.read_text(encoding="utf-8"))
                emission = cal.get("emission_params")
                if emission is not None:
                    kwargs["emission_params"] = [tuple(p) for p in emission]
                state_names = cal.get("state_names")
                if state_names is not None:
                    kwargs["state_names"] = state_names

            regime_engine = get_regime_engine("hmm_3state_fractional", **kwargs)
        except Exception:
            pass

        # D1: Share the regime engine with AlphaLoader so signal
        # namespace's regime_posteriors reads from the same instance
        # that receives posterior() updates in run().
        loader = AlphaLoader(regime_engine=regime_engine)
        alpha_module = loader.load(spec_path, param_overrides=param_overrides)
        return self.run(alpha_module, event_log, regime_engine=regime_engine,
                        trace_file=trace_file)


# ── Utility functions ───────────────────────────────────────────────


def latency_sensitivity(
    alpha_module: Any,
    event_log: Any,
    latency_levels_ms: tuple[float, ...] = (0, 50, 100, 200, 500),
    fill_probability: float = 0.7,
    random_seed: int = 42,
    tc_config: GrokTCConfig | None = None,
    default_quantity: int = 100,
) -> dict[float, GrokBacktestMetrics]:
    """Run the same alpha at multiple latency levels.

    Returns a dict mapping latency_ms -> metrics.
    """
    results: dict[float, GrokBacktestMetrics] = {}
    for lat in latency_levels_ms:
        bt = GrokParityBacktester(
            latency_ms=lat,
            fill_probability=fill_probability,
            tc_config=tc_config,
            default_quantity=default_quantity,
            random_seed=random_seed,
        )
        _, metrics = bt.run(alpha_module, event_log)
        results[lat] = metrics
    return results


def compare_with_feelies(
    grok_metrics: GrokBacktestMetrics,
    feelies_trades: list[Any],
    feelies_pnl: list[float],
) -> dict[str, Any]:
    """Compare Grok-parity results with production feelies backtest.

    Returns a dict with comparison fields for each metric.
    """
    feelies_total = sum(feelies_pnl)
    feelies_n = len(feelies_trades)

    feelies_sharpe = 0.0
    if len(feelies_pnl) > 1:
        mean = feelies_total / len(feelies_pnl)
        var = sum((p - mean) ** 2 for p in feelies_pnl) / (len(feelies_pnl) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        feelies_sharpe = mean / std if std > 0 else 0.0

    feelies_hash = hashlib.sha256(
        json.dumps([round(p, 8) for p in feelies_pnl]).encode()
    ).hexdigest()[:16]

    return {
        "grok_total_pnl": grok_metrics.total_pnl,
        "feelies_total_pnl": feelies_total,
        "pnl_diff": grok_metrics.total_pnl - feelies_total,
        "pnl_diff_pct": (
            (grok_metrics.total_pnl - feelies_total) / abs(feelies_total) * 100
            if feelies_total != 0
            else 0.0
        ),
        "grok_n_trades": grok_metrics.n_trades,
        "feelies_n_trades": feelies_n,
        "grok_sharpe": grok_metrics.sharpe,
        "feelies_sharpe": feelies_sharpe,
        "grok_pnl_hash": grok_metrics.pnl_hash,
        "feelies_pnl_hash": feelies_hash,
        "hashes_match": grok_metrics.pnl_hash == feelies_hash,
    }
