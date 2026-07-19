"""Run-twice parity-hash determinism guard for
``sig_dislocation_lambda_drift_v1`` (Task 9 commit 7; impl plan §2.7).

Modeled on ``test_backtest_parity_no_cache.py``: the real bootstrap
(``build_platform`` → ``boot`` → ``run_backtest``) runs TWICE over the
same synthetic tape with the new alpha registered (strict trend-
mechanism loader mode), and the trade-sequence parity hash from the
harness (``compute_parity_hash``, ``harness/backtest_report.py``) must
be identical — Inv-5 for this alpha's full tick-to-fill path.

The tape is the §2.3 golden tape extended so the run actually trades
(the plan's primary assertion — no Signal-fingerprint fallback needed):
phase A (0–300 s) is a flat mid with spread jitter (the HMM calibration
prefix); phase B (300–600 s) builds the informed dislocation out of
per-second (quote, trade) pairs with the impact coefficient ramping up,
so the h=300 boundary at 600 s emits the LONG golden signal, which
clears the EV floor and the B4 edge/cost gate (ratio 1.5, the evidence-
config value) and fills 80 shares; phase C (600 s →) drifts the mid
down so the hazard-exit controller closes the position — two journal
records per run, and the parity hash is non-trivially populated.

Config notes (documented so the numbers aren't magic):
``regime_calibration_max_quotes=300`` uses phase A as the causal
calibration prefix (uncalibrated posteriors fail the P(vol_breakout)
gate safe to OFF — audit P0-1);
``risk_max_gross_exposure_pct=200.0`` is the reference
``platform.yaml`` value, which the evidence run config inherits — the
class default (20 %) would veto the 80-share entry at APP price levels
($43.8k notional vs a $20k cap) and leave the journal empty.

**No locked baseline:** run-twice equality only — no ``EXPECTED_*``
literal is added anywhere (impl plan §2.7 do-not-touch), so the
``tests/determinism/`` unregistered-hash sweep and the parity manifest
are untouched.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Signal, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.harness.backtest_report import compute_parity_hash
from feelies.kernel.orchestrator import Orchestrator
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog

_NS = 1_000_000_000
_SYM = "APP"
# 2026-01-15 14:30:00 UTC — a regular US-equity open (pure constant).
_SESSION_OPEN_NS = 1_768_532_400_000_000_000

_ALPHA = Path("alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml")

# Reference sensor specs — platform.yaml params, verbatim (census parity).
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "causal", "sensor_version": "2.0.0"},
        subscribes_to=(NBBOQuote, Trade),
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
)


def _quote(ts_ns: int, mid: float, spread: float, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{seq}",
        sequence=seq,
        source_layer="INGESTION",
        symbol=_SYM,
        bid=Decimal(str(round(mid - spread / 2, 6))),
        ask=Decimal(str(round(mid + spread / 2, 6))),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(ts_ns: int, price: float, size: int, seq: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{seq}",
        sequence=seq,
        source_layer="INGESTION",
        symbol=_SYM,
        price=Decimal(str(round(price, 6))),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


def _build_tape() -> list[NBBOQuote | Trade]:
    """§2.3 golden tape (LONG, λ rising) + a post-entry down-drift leg."""
    events: list[NBBOQuote | Trade] = []
    mid = 544.0
    seq = 0
    spreads = (0.08, 0.10, 0.12)  # jitter so the HMM calibration is non-degenerate
    for t in range(0, 300):
        seq += 1
        events.append(_quote(_SESSION_OPEN_NS + t * _NS, mid, spreads[t % 3], seq))
    trade_price = mid
    prev_size = 100
    for k in range(300):
        t_s = 300 + k
        # dp_k = c_k × Δq_{k-1} with c ramping UP — the causal (Δp, Δq)
        # pairing the λ sensor regresses (informed-flow fingerprint).
        c = 0.4e-4 + 1.2e-4 * (k / 299)
        mid += c * prev_size
        seq += 1
        events.append(_quote(_SESSION_OPEN_NS + t_s * _NS, mid, spreads[t_s % 3], seq))
        trade_price += 0.0001
        seq += 1
        events.append(
            _trade(
                _SESSION_OPEN_NS + t_s * _NS + 400_000_000,
                trade_price,
                50 if k % 2 == 0 else 150,
                seq,
            )
        )
        prev_size = 50 if k % 2 == 0 else 150
    # Post-entry down-drift: the hazard/exit path closes the LONG and the
    # tape carries enough forward quotes for the fill model to price it.
    for k in range(300):
        t_s = 600 + k
        mid -= 0.02
        seq += 1
        events.append(_quote(_SESSION_OPEN_NS + t_s * _NS, mid, spreads[t_s % 3], seq))
        if k % 2 == 0:
            seq += 1
            events.append(_trade(_SESSION_OPEN_NS + t_s * _NS + 400_000_000, mid - 0.04, 100, seq))
    return events


def _config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({_SYM}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({300}),
        session_open_ns=_SESSION_OPEN_NS,
        account_equity=100_000.0,
        enforce_trend_mechanism=True,
        signal_min_edge_cost_ratio=1.5,
        regime_calibration_max_quotes=300,
        risk_max_gross_exposure_pct=200.0,
    )


def _run_once() -> tuple[Orchestrator, list[Signal]]:
    config = _config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_build_tape())
    orchestrator, _ = build_platform(config, event_log=event_log)
    signals: list[Signal] = []
    orchestrator._bus.subscribe(Signal, signals.append)
    orchestrator.boot(config)
    orchestrator.run_backtest()
    return orchestrator, signals


def test_run_twice_parity_hash_identical_and_run_actually_trades() -> None:
    orch1, signals1 = _run_once()
    orch2, signals2 = _run_once()

    # The run must actually trade, else the parity hash is trivially equal
    # (impl plan §2.7: a trivially-equal empty hash proves nothing).
    assert orch1.trade_journal is not None
    records = list(orch1.trade_journal.query())
    assert len(records) > 0
    assert signals1, "golden tape must emit at least the LONG entry signal"
    assert any(s.strategy_id == "sig_dislocation_lambda_drift_v1" for s in signals1)

    assert compute_parity_hash(orch1) == compute_parity_hash(orch2)
    assert len(signals1) == len(signals2)
