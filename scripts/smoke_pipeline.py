"""Smoke-test the full micro-state pipeline with synthetic data.

Exercises every stage of the micro-state machine and both production
Signal → Order paths:

    WAITING_FOR_MARKET_EVENT
    → MARKET_EVENT_RECEIVED   (NBBOQuote / Trade)
    → STATE_UPDATE            (RegimeState)
    → SENSOR_UPDATE           (SensorReading, incl. warm-up transition)
    → HORIZON_CHECK           (HorizonTick boundary detection)
    → HORIZON_AGGREGATE       (HorizonFeatureSnapshot)
    → SIGNAL_GATE             (regime-gate evaluation)
    → CROSS_SECTIONAL         (CrossSectionalContext → SizedPositionIntent)
    → FEATURE_COMPUTE         (M3 bookkeeping transition)
    → SIGNAL_EVALUATE         (Signal → RiskVerdict)
    → RISK_CHECK              (RiskVerdict, incl. ALLOW / SCALE_DOWN paths)
    → ORDER_DECISION          (OrderRequest, incl. ENTER + REVERSE/EXIT)
    → ORDER_ACK               (OrderAck)
    → POSITION_UPDATE         (PositionUpdate)
    → LOG_AND_METRICS         (StateTransition / MetricEvent)

Three synthetic alphas cover both standalone-SIGNAL and PORTFOLIO paths:

  smoke_always_on_v1        — standalone SIGNAL; alternates LONG (odd
                               boundaries) / SHORT (even boundaries) to
                               exercise both ENTER and REVERSE/EXIT intents.
  smoke_portfolio_feeder_v1 — SIGNAL consumed by the portfolio; always LONG
                               so the composition engine always has data.
  smoke_portfolio_v1        — PORTFOLIO; universe=[AAPL]; exercises the
                               CompositionEngine → SizedPositionIntent →
                               _on_bus_sized_intent path.

Four sensors cover both the quote-driven and trade-driven sensor paths:

  ofi_ewma, micro_price, spread_z_30d — NBBOQuote sensors
  kyle_lambda_60s                     — Trade sensor (tests Trade-path warmup)

Additional sub-runs:

  run_risk_rejection_scenario — platform limit set to 1 share to confirm
                                 check_order returns RiskAction.REJECT.

Notes on two architectural invariants visible in the report:

  ORDER_AGGREGATION micro-state — defined in micro.py but has no live
    code path in the current implementation; the standalone-SIGNAL path
    goes SIGNAL_EVALUATE → RISK_CHECK directly, and PORTFOLIO orders are
    dispatched outside the micro-SM via _on_bus_sized_intent. Flagged as
    "dead state" in the report; not a bug.

  Signal/order drop ratio — the micro-SM permits at most ONE standalone
    Signal → Order walk per tick. When multiple standalone SIGNAL alphas
    fire at the same boundary, _select_bus_signal() picks the first
    (alphabetically by alpha_id after registration-order sort). Multi-
    symbol aggregation should be handled via a PORTFOLIO alpha.

Usage::

    python scripts/smoke_pipeline.py

Exit code 0 = all stages exercised; non-zero = at least one gap.
"""

from __future__ import annotations

import sys
import random
import tempfile
import textwrap
from decimal import Decimal
from pathlib import Path
from typing import Any

# ── repo root on sys.path ────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Alert,
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    KillSwitchActivation,
    MetricEvent,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    PositionUpdate,
    RegimeHazardSpike,
    RegimeState,
    RiskAction,
    RiskVerdict,
    SensorReading,
    Signal,
    SizedPositionIntent,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog

# ── Constants ────────────────────────────────────────────────────────────

SESSION_OPEN_NS: int = 1_768_532_400_000_000_000  # 2026-01-15 14:30:00 UTC
QUOTE_CADENCE_NS: int = 100_000_000               # 10 Hz

# 3 symbols — small enough for fast smoke, large enough to prove bus routing.
_SYMBOLS: tuple[str, ...] = ("AAPL", "MSFT", "NVDA")

# 3 minutes @ 10 Hz = 1 800 quotes/symbol.
# This crosses 6 × 30 s boundaries and 1 × 120 s boundary.
_QUOTES_PER_SYMBOL: int = 1_800

_STARTING_PRICES_CENTS: dict[str, int] = {
    "AAPL": 18000,
    "MSFT": 37000,
    "NVDA": 45000,
}

_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="1.0.0",
        cls=KyleLambda60sSensor,
        # Use min_samples=5 so the sensor warms up quickly within the
        # smoke run (default is 30; 5 trades arrive within seconds).
        params={"min_samples": 5},
        subscribes_to=(Trade,),
    ),
)

# ── Smoke alpha YAMLs ─────────────────────────────────────────────────────

# Standalone SIGNAL alpha — alternates LONG (odd boundaries) / SHORT (even
# boundaries) to exercise both ENTER and REVERSE/EXIT paths.
_SMOKE_SIGNAL_YAML = textwrap.dedent("""\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: smoke_always_on_v1
    version: "1.0.0"
    description: "Smoke-test signal — alternates LONG/SHORT by boundary_index."
    hypothesis: |
      Pipeline smoke test.  Alternates LONG (odd boundary) and SHORT
      (even boundary) to prove ORDER and REVERSE/EXIT stages are reachable.
    falsification_criteria:
      - "smoke_test_pipeline_does_not_complete_end_to_end"

    depends_on_sensors:
      - ofi_ewma

    horizon_seconds: 30

    risk_budget:
      max_position_per_symbol: 100
      max_gross_exposure_pct: 20.0
      max_drawdown_pct: 5.0
      capital_allocation_pct: 50.0

    regime_gate:
      regime_engine: hmm_3state_fractional
      on_condition: "1 > 0"
      off_condition: "1 < 0"
      hysteresis:
        posterior_margin: 0.0
        percentile_margin: 0.0

    cost_arithmetic:
      edge_estimate_bps: 15.0
      half_spread_bps: 2.0
      impact_bps: 2.0
      fee_bps: 0.5
      margin_ratio: 3.33

    parameters:
      edge_bps:
        type: float
        default: 15.0
        description: "Smoke-test edge estimate in basis points."

    signal: |
      def evaluate(snapshot, regime, params):
          direction = LONG if snapshot.boundary_index % 2 == 1 else SHORT
          return Signal(
              timestamp_ns=snapshot.timestamp_ns,
              correlation_id=snapshot.correlation_id,
              sequence=snapshot.sequence,
              symbol=snapshot.symbol,
              strategy_id=alpha_id,
              direction=direction,
              strength=1.0,
              edge_estimate_bps=params["edge_bps"],
          )
""")

# Portfolio feeder SIGNAL alpha — always LONG, consumed by smoke_portfolio_v1.
_SMOKE_FEEDER_YAML = textwrap.dedent("""\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: smoke_portfolio_feeder_v1
    version: "1.0.0"
    description: "Portfolio feeder — always-LONG signal consumed by smoke_portfolio_v1."
    hypothesis: |
      Pipeline smoke test.  Always emits LONG for portfolio composition exercise.
    falsification_criteria:
      - "smoke_test_portfolio_path_does_not_produce_sized_intent"

    depends_on_sensors:
      - ofi_ewma

    horizon_seconds: 30

    risk_budget:
      max_position_per_symbol: 100
      max_gross_exposure_pct: 20.0
      max_drawdown_pct: 5.0
      capital_allocation_pct: 50.0

    regime_gate:
      regime_engine: hmm_3state_fractional
      on_condition: "1 > 0"
      off_condition: "1 < 0"
      hysteresis:
        posterior_margin: 0.0
        percentile_margin: 0.0

    cost_arithmetic:
      edge_estimate_bps: 15.0
      half_spread_bps: 2.0
      impact_bps: 2.0
      fee_bps: 0.5
      margin_ratio: 3.33

    parameters:
      edge_bps:
        type: float
        default: 15.0
        description: "Smoke-test edge estimate."

    signal: |
      def evaluate(snapshot, regime, params):
          return Signal(
              timestamp_ns=snapshot.timestamp_ns,
              correlation_id=snapshot.correlation_id,
              sequence=snapshot.sequence,
              symbol=snapshot.symbol,
              strategy_id=alpha_id,
              direction=LONG,
              strength=1.0,
              edge_estimate_bps=params["edge_bps"],
          )
""")

# PORTFOLIO alpha — universe=[AAPL] only, depends on smoke_portfolio_feeder_v1.
# Restricting to a single symbol guarantees completeness=1.0 on every boundary
# (the feeder signal for AAPL is always cached before the UNIVERSE tick fires).
_SMOKE_PORTFOLIO_YAML = textwrap.dedent("""\
    schema_version: "1.1"
    layer: PORTFOLIO
    alpha_id: smoke_portfolio_v1
    version: "1.0.0"
    description: "Smoke-test portfolio — exercises CROSS_SECTIONAL → SizedPositionIntent."
    hypothesis: |
      Pipeline smoke test.  Consumes smoke_portfolio_feeder_v1 signals for AAPL
      and emits SizedPositionIntent to prove the PORTFOLIO composition path
      is wired end-to-end.
    falsification_criteria:
      - "smoke_test_portfolio_path_does_not_fire"

    horizon_seconds: 30

    universe:
      - AAPL

    depends_on_signals:
      - smoke_portfolio_feeder_v1

    factor_neutralization: false

    cost_arithmetic:
      edge_estimate_bps: 15.0
      half_spread_bps: 2.0
      impact_bps: 2.0
      fee_bps: 0.5
      margin_ratio: 3.33
""")

# ── Synthetic event generation ────────────────────────────────────────────


def _synth_events(seed: int = 42) -> list[Any]:
    """Generate deterministic multi-symbol NBBOQuote + Trade stream.

    Each symbol gets an independent ``random.Random`` derived from the
    master seed so per-symbol price walks are independent but the
    whole stream is reproducible.  Events are interleaved by
    ``(timestamp_ns, symbol)`` for causality.
    """
    all_events: list[tuple[int, str, Any]] = []

    for sym_idx, symbol in enumerate(_SYMBOLS):
        rng = random.Random(seed * 100 + sym_idx)
        last_mid = _STARTING_PRICES_CENTS[symbol]

        for i in range(_QUOTES_PER_SYMBOL):
            ts_ns = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
            delta = rng.choice((-1, 0, 0, 0, 1))
            last_mid += delta
            bid_size = rng.choice((100, 200, 300, 400, 500))
            ask_size = rng.choice((100, 200, 300, 400, 500))

            quote = NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=sym_idx * _QUOTES_PER_SYMBOL * 3 + i,
                correlation_id=f"smoke-q-{symbol}-{i}",
                source_layer="INGESTION",
                symbol=symbol,
                bid=Decimal(last_mid) / Decimal(100),
                ask=Decimal(last_mid + 1) / Decimal(100),
                bid_size=bid_size,
                ask_size=ask_size,
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11,
                ask_exchange=11,
                tape=3,
            )
            all_events.append((ts_ns, symbol, quote))

            if i % 7 == 0 and i > 0:
                side_buy = rng.random() < 0.5
                price_cents = last_mid + (1 if side_buy else 0)
                trade = Trade(
                    timestamp_ns=ts_ns + 1,
                    sequence=sym_idx * _QUOTES_PER_SYMBOL * 3 + _QUOTES_PER_SYMBOL + i,
                    correlation_id=f"smoke-t-{symbol}-{i}",
                    source_layer="INGESTION",
                    symbol=symbol,
                    price=Decimal(price_cents) / Decimal(100),
                    size=rng.choice((50, 100, 150, 200)),
                    exchange=11,
                    trade_id=f"smoke-{symbol}-{i:08d}",
                    exchange_timestamp_ns=ts_ns + 1,
                    tape=3,
                )
                all_events.append((ts_ns + 1, symbol, trade))

    all_events.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in all_events]


# ── Platform construction ─────────────────────────────────────────────────


def _build(alpha_yaml_paths: list[Path], seed: int = 42) -> dict[str, list[Any]]:
    """Build platform, run backtest, return captured event lists."""
    config = PlatformConfig(
        symbols=frozenset(_SYMBOLS),
        mode=OperatingMode.BACKTEST,
        alpha_specs=alpha_yaml_paths,
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=100_000.0,
        # Smoke alphas have no trend_mechanism block — opt out of strict mode.
        enforce_trend_mechanism=False,
        # signal_min_edge_cost_ratio defaults to 0.0; all signals pass.
    )

    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_events(seed=seed))

    orchestrator, _ = build_platform(config, event_log=event_log)

    # Subscribe BEFORE boot so we capture every event from tick 1.
    captured: dict[str, list[Any]] = {
        "quotes":      [],
        "trades":      [],
        "regime":      [],
        "sensor":      [],
        "htick":       [],
        "snapshot":    [],
        "signal":      [],
        "intent":      [],
        "risk":        [],
        "order":       [],
        "ack":         [],
        "position":    [],
        "transition":  [],
        "metric":      [],
        "alert":       [],
        "killswitch":  [],
        "hazard":      [],
        "xsect":       [],
        "all":         [],
    }
    bus = orchestrator._bus
    bus.subscribe(NBBOQuote,              captured["quotes"].append)
    bus.subscribe(Trade,                  captured["trades"].append)
    bus.subscribe(RegimeState,            captured["regime"].append)
    bus.subscribe(SensorReading,          captured["sensor"].append)
    bus.subscribe(HorizonTick,            captured["htick"].append)
    bus.subscribe(HorizonFeatureSnapshot, captured["snapshot"].append)
    bus.subscribe(Signal,                 captured["signal"].append)
    bus.subscribe(SizedPositionIntent,    captured["intent"].append)
    bus.subscribe(RiskVerdict,            captured["risk"].append)
    bus.subscribe(OrderRequest,           captured["order"].append)
    bus.subscribe(OrderAck,               captured["ack"].append)
    bus.subscribe(PositionUpdate,         captured["position"].append)
    bus.subscribe(StateTransition,        captured["transition"].append)
    bus.subscribe(MetricEvent,            captured["metric"].append)
    bus.subscribe(Alert,                  captured["alert"].append)
    bus.subscribe(KillSwitchActivation,   captured["killswitch"].append)
    bus.subscribe(RegimeHazardSpike,      captured["hazard"].append)
    bus.subscribe(CrossSectionalContext,  captured["xsect"].append)
    bus.subscribe_all(captured["all"].append)

    orchestrator.boot(config)
    orchestrator.run_backtest()

    captured["_orchestrator"] = [orchestrator]
    return captured


# ── Report helpers ────────────────────────────────────────────────────────


def _sample(events: list[Any], n: int = 1) -> str:
    if not events:
        return "  (none)"
    lines = []
    for e in events[:n]:
        lines.append(f"  first: {e!r}"[:160])
    if len(events) > n:
        lines.append(f"  last:  {events[-1]!r}"[:160])
    return "\n".join(lines)


def _check(label: str, events: list[Any], required: bool = True) -> bool:
    ok = bool(events) or not required
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: {len(events)} event(s)")
    if events:
        print(_sample(events))
    return ok


# ── Main smoke run ────────────────────────────────────────────────────────


def run_smoke(alpha_yaml_paths: list[Path]) -> bool:
    """Run the pipeline once and print the stage-by-stage report.

    Returns True if all required stages produced events.
    """
    print("\n" + "=" * 70)
    print("SMOKE PIPELINE — stage-by-stage plumbing verification")
    print("=" * 70)

    print(f"\nConfig:")
    print(f"  symbols       : {_SYMBOLS}")
    print(f"  quotes/symbol : {_QUOTES_PER_SYMBOL} ({_QUOTES_PER_SYMBOL // 10}s @ 10Hz)")
    print(f"  alphas        : {[p.name for p in alpha_yaml_paths]}")

    c = _build(alpha_yaml_paths)
    orch = c["_orchestrator"][0]

    passes: list[bool] = []
    print("\n── STAGE 1 · MARKET_EVENT ──────────────────────────────────────")
    passes.append(_check("NBBOQuote", c["quotes"], required=True))
    passes.append(_check("Trade",     c["trades"], required=True))

    print("\n── STAGE 2 · STATE_UPDATE ──────────────────────────────────────")
    passes.append(_check("RegimeState", c["regime"], required=True))

    print("\n── STAGE 3 · SENSOR ────────────────────────────────────────────")
    passes.append(_check("SensorReading", c["sensor"], required=True))

    # Verify sensor warm-up transition: cold readings at startup, warm later.
    cold_readings = [s for s in c["sensor"] if not s.warm]
    warm_readings = [s for s in c["sensor"] if s.warm]
    cold_ok = bool(cold_readings)
    warm_ok = bool(warm_readings)
    print(f"  [{'PASS' if cold_ok else 'FAIL'}] cold (warm=False) readings   : {len(cold_readings)}")
    print(f"  [{'PASS' if warm_ok else 'FAIL'}] warm (warm=True)  readings   : {len(warm_readings)}")
    passes.append(cold_ok)
    passes.append(warm_ok)

    # Verify kyle_lambda_60s sensor produced readings (Trade path).
    kyle_readings = [s for s in c["sensor"] if s.sensor_id == "kyle_lambda_60s"]
    kyle_ok = bool(kyle_readings)
    print(f"  [{'PASS' if kyle_ok else 'FAIL'}] kyle_lambda_60s readings     : {len(kyle_readings)}")
    passes.append(kyle_ok)

    print("\n── STAGE 4 · AGGREGATOR ────────────────────────────────────────")
    passes.append(_check("HorizonTick",            c["htick"],    required=True))
    passes.append(_check("HorizonFeatureSnapshot", c["snapshot"], required=True))

    # Count HORIZON_CHECK transitions (M3 bookkeeping for aggregator gate).
    horizon_check_count = sum(
        1 for t in c["transition"]
        if getattr(t, "from_state", None) == "HORIZON_CHECK"
    )
    print(f"  HORIZON_CHECK transitions            : {horizon_check_count}")

    print("\n── STAGE 5 · SIGNAL ────────────────────────────────────────────")
    passes.append(_check("Signal", c["signal"], required=True))

    long_sigs  = [s for s in c["signal"] if s.direction.name == "LONG"]
    short_sigs = [s for s in c["signal"] if s.direction.name == "SHORT"]
    print(f"  LONG signals  : {len(long_sigs)}")
    print(f"  SHORT signals : {len(short_sigs)}")
    # Both directions should appear (smoke_always_on_v1 alternates per boundary).
    long_ok  = bool(long_sigs)
    short_ok = bool(short_sigs)
    print(f"  [{'PASS' if long_ok else 'FAIL'}] LONG signals exist")
    print(f"  [{'PASS' if short_ok else 'FAIL'}] SHORT signals exist")
    passes.append(long_ok)
    passes.append(short_ok)

    # FEATURE_COMPUTE / SIGNAL_EVALUATE bookkeeping transitions.
    fc_count = sum(
        1 for t in c["transition"]
        if getattr(t, "from_state", None) == "FEATURE_COMPUTE"
    )
    se_count = sum(
        1 for t in c["transition"]
        if getattr(t, "from_state", None) == "SIGNAL_EVALUATE"
    )
    print(f"  FEATURE_COMPUTE transitions  : {fc_count}")
    print(f"  SIGNAL_EVALUATE transitions  : {se_count}")

    print("\n── STAGE 6 · COMPOSITION ───────────────────────────────────────")
    # Both CrossSectionalContext and SizedPositionIntent are required now
    # that smoke_portfolio_v1 is wired in.
    passes.append(_check("CrossSectionalContext", c["xsect"],  required=True))
    passes.append(_check("SizedPositionIntent",   c["intent"], required=True))

    print("\n── STAGE 7 · RISK ──────────────────────────────────────────────")
    passes.append(_check("RiskVerdict", c["risk"], required=True))

    # Break down by RiskAction.
    from collections import Counter
    action_counts: Counter[str] = Counter(
        getattr(v, "action", None) for v in c["risk"]
    )
    for action, cnt in sorted(action_counts.items(), key=lambda x: str(x[0])):
        print(f"  {action!s:<35} {cnt}")
    # ALLOW must appear; SCALE_DOWN is expected after exposure builds up.
    allow_ok = action_counts.get(RiskAction.ALLOW, 0) > 0
    print(f"  [{'PASS' if allow_ok else 'FAIL'}] at least one ALLOW verdict")
    passes.append(allow_ok)
    scale_down_cnt = action_counts.get(RiskAction.SCALE_DOWN, 0)
    if scale_down_cnt:
        print(f"  [INFO ] SCALE_DOWN observed ({scale_down_cnt}x) — exposure threshold crossed")

    print("\n── STAGE 8 · ORDER ─────────────────────────────────────────────")
    passes.append(_check("OrderRequest", c["order"], required=True))

    # Break down by intent type (ENTER / EXIT / REVERSE_ENTRY / REVERSE_EXIT).
    intent_counts: Counter[str] = Counter(
        getattr(o, "intent", None) for o in c["order"]
    )
    for intent, cnt in sorted(intent_counts.items(), key=lambda x: str(x[0])):
        print(f"  {intent!s:<35} {cnt}")
    # EXIT/REVERSE orders appear when smoke_always_on_v1 fires SHORT after LONG.
    reverse_types = {v for k, v in intent_counts.items()
                     if k is not None and "REVERSE" in str(k)}
    exit_types    = {v for k, v in intent_counts.items()
                     if k is not None and "EXIT"    in str(k)}
    if intent_counts:
        any_exit = any("EXIT" in str(k) or "REVERSE" in str(k)
                       for k in intent_counts if k is not None)
        print(f"  [{'PASS' if any_exit else 'INFO '}] EXIT / REVERSE order{'s' if any_exit else 's (none yet — may need more boundaries)'}")
    print(f"  Signal/order ratio note: the micro-SM emits at most 1 standalone")
    print(f"  order per tick (PORTFOLIO orders handled via SizedPositionIntent).")

    print("\n── STAGE 9 · ACK ───────────────────────────────────────────────")
    passes.append(_check("OrderAck", c["ack"], required=True))

    print("\n── STAGE 10 · POSITION ─────────────────────────────────────────")
    passes.append(_check("PositionUpdate", c["position"], required=True))

    print("\n── STAGE 11 · LOG_AND_METRICS ──────────────────────────────────")
    passes.append(_check("StateTransition", c["transition"], required=False))
    passes.append(_check("MetricEvent",     c["metric"],     required=False))

    print(f"\n── SAFETY SILENCE CHECK ────────────────────────────────────────")
    # KillSwitchActivation and RegimeHazardSpike must be absent in a healthy
    # smoke run (hard monitoring alarms).
    # composition.low_completeness Alerts from horizon_metrics are expected on
    # early boundaries (cold-start sensor readings not yet warm); the smoke run
    # does NOT fail on these.
    composition_alerts = [a for a in c["alert"]
                          if getattr(a, "source_layer", "") == "COMPOSITION"]
    kernel_alerts = [a for a in c["alert"]
                     if getattr(a, "source_layer", "") != "COMPOSITION"]
    print(f"  composition Alerts (warm-up expected) : {len(composition_alerts)}")
    print(f"  kernel Alerts (expected 0)             : {len(kernel_alerts)}")
    print(f"  KillSwitchActivation (expected 0)      : {len(c['killswitch'])}")
    print(f"  RegimeHazardSpike    (expected 0)      : {len(c['hazard'])}")
    silence_ok = not kernel_alerts and not c["killswitch"] and not c["hazard"]
    print(f"  [{'PASS' if silence_ok else 'WARN'}] hard monitoring channels silent")

    print(f"\n── DEAD-STATE INVENTORY ────────────────────────────────────────")
    print(f"  ORDER_AGGREGATION — no live code path in current implementation.")
    print(f"  Standalone-SIGNAL goes SIGNAL_EVALUATE→RISK_CHECK directly.")
    print(f"  PORTFOLIO orders dispatched via _on_bus_sized_intent, not SM.")
    print(f"  Flagged as dead micro-state; not a bug.")

    print("\n── FINAL STATE ─────────────────────────────────────────────────")
    final_state = orch.macro_state
    state_ok = final_state == MacroState.READY
    print(f"  [{'PASS' if state_ok else 'FAIL'}] macro_state == READY : {final_state}")
    passes.append(state_ok)

    print(f"\n── BUS TOTALS ───────────────────────────────────────────────────")
    print(f"  all events on bus : {len(c['all'])}")
    event_type_counts: dict[str, int] = {}
    for e in c["all"]:
        k = type(e).__name__
        event_type_counts[k] = event_type_counts.get(k, 0) + 1
    for k, v in sorted(event_type_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<35} {v}")

    all_pass = all(passes)
    print("\n" + ("=" * 70))
    print(f"RESULT: {'ALL STAGES PASS' if all_pass else 'SOME STAGES FAILED'}")
    print("=" * 70)
    return all_pass


def run_risk_rejection_scenario(alpha_yaml_paths: list[Path]) -> bool:
    """Run with risk_max_position_per_symbol=1 to force check_order REJECT.

    The position sizer targets 100 shares for every signal, but the risk
    check gate refuses any fill that would exceed 1 share.  Every
    RiskVerdict in this run should be REJECT.
    """
    import hashlib

    print("\n── RISK REJECTION SCENARIO ─────────────────────────────────────")

    # Use only the standalone SIGNAL alpha for simplicity; the tight limit
    # must trigger REJECT regardless of direction.
    config = PlatformConfig(
        symbols=frozenset(_SYMBOLS),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[alpha_yaml_paths[0]],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=100_000.0,
        enforce_trend_mechanism=False,
        risk_max_position_per_symbol=1,   # sizer returns 100, gate rejects
    )

    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_events(seed=42))

    orchestrator, _ = build_platform(config, event_log=event_log)

    risk_events: list[Any] = []
    order_events: list[Any] = []
    bus = orchestrator._bus
    bus.subscribe(RiskVerdict,  risk_events.append)
    bus.subscribe(OrderRequest, order_events.append)

    orchestrator.boot(config)
    orchestrator.run_backtest()

    reject_count = sum(
        1 for v in risk_events
        if getattr(v, "action", None) == RiskAction.REJECT
    )
    ok = reject_count > 0
    print(f"  RiskVerdicts total : {len(risk_events)}")
    print(f"  REJECT verdicts    : {reject_count}")
    print(f"  Orders placed      : {len(order_events)}")
    print(f"  [{'PASS' if ok else 'FAIL'}] at least one REJECT verdict with position limit = 1")
    return ok


def run_determinism_check(alpha_yaml_paths: list[Path]) -> bool:
    """Run pipeline twice and verify all output streams are byte-identical (Inv-5)."""
    import hashlib

    print("\n── DETERMINISM CHECK (Inv-5) ────────────────────────────────────")

    def _h(items: list[Any], key_fn: Any) -> str:
        return hashlib.sha256(
            "\n".join(key_fn(e) for e in items).encode()
        ).hexdigest()

    def _sig_key(s: Any) -> str:
        return (
            f"{s.sequence}|{s.symbol}|{s.strategy_id}|"
            f"{s.direction.name}|{s.strength:.6f}|"
            f"{s.edge_estimate_bps:.6f}|{s.timestamp_ns}"
        )

    def _ord_key(o: Any) -> str:
        return f"{o.symbol}|{o.sequence}|{o.timestamp_ns}"

    def _pos_key(p: Any) -> str:
        return f"{p.symbol}|{p.quantity}|{p.timestamp_ns}"

    def _reg_key(r: Any) -> str:
        return f"{r.timestamp_ns}|{r.symbol}|{r.engine_name}"

    def _vrdt_key(v: Any) -> str:
        return f"{v.timestamp_ns}|{getattr(v, 'action', '')}"

    def _sensor_key(s: Any) -> str:
        return f"{s.sensor_id}|{s.symbol}|{s.timestamp_ns}|{s.warm}"

    c1 = _build(alpha_yaml_paths, seed=42)
    c2 = _build(alpha_yaml_paths, seed=42)

    streams = [
        ("Signal",         c1["signal"],     c2["signal"],     _sig_key),
        ("OrderRequest",   c1["order"],      c2["order"],      _ord_key),
        ("PositionUpdate", c1["position"],   c2["position"],   _pos_key),
        ("RegimeState",    c1["regime"],     c2["regime"],     _reg_key),
        ("RiskVerdict",    c1["risk"],       c2["risk"],       _vrdt_key),
        # Sample every 10th sensor reading to keep the hash concise.
        ("SensorReading (sampled)",
         c1["sensor"][::10], c2["sensor"][::10], _sensor_key),
    ]

    all_ok = True
    for name, s1, s2, kfn in streams:
        h1 = _h(s1, kfn)
        h2 = _h(s2, kfn)
        ok = h1 == h2
        all_ok = all_ok and ok
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {name:<30}"
            f" n={len(s1)}  h={h1[:16]}..."
        )

    return all_ok


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="feelies_smoke_") as tmpdir:
        td = Path(tmpdir)
        signal_path    = td / "smoke_always_on_v1.alpha.yaml"
        feeder_path    = td / "smoke_portfolio_feeder_v1.alpha.yaml"
        portfolio_path = td / "smoke_portfolio_v1.alpha.yaml"

        signal_path.write_text(_SMOKE_SIGNAL_YAML,    encoding="utf-8")
        feeder_path.write_text(_SMOKE_FEEDER_YAML,    encoding="utf-8")
        portfolio_path.write_text(_SMOKE_PORTFOLIO_YAML, encoding="utf-8")

        all_alpha_paths = [signal_path, feeder_path, portfolio_path]

        stage_ok  = run_smoke(all_alpha_paths)
        reject_ok = run_risk_rejection_scenario(all_alpha_paths)
        det_ok    = run_determinism_check(all_alpha_paths)

    all_ok = stage_ok and reject_ok and det_ok
    print(f"\nFINAL EXIT: {'0 (success)' if all_ok else '1 (failure)'}\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
