"""Wiring e2e for pofi_xsect_v1 driven by its actual feeder alphas.

Boots ``pofi_kyle_drift_v1`` + ``pofi_inventory_revert_v1`` (SIGNAL
feeders) and ``pofi_xsect_v1`` (PORTFOLIO) through ``build_platform``
over a 360-second deterministic multi-symbol synthetic stream.

What this test guarantees
--------------------------

* All three layers register through ``build_platform`` without
  ``AlphaLoadError``, ``LayerValidationError``, or wiring failures.
* The composition layer is fully wired (``CompositionEngine``,
  ``CrossSectionalTracker``, ``HorizonMetricsCollector``).
* At least one 300-second horizon boundary is crossed and at least one
  ``SizedPositionIntent`` is emitted (the composition cycle fires).
* A full backtest reaches ``MacroState.READY`` without exception.
* Two replays of the exact same fixture produce a byte-identical
  ``SizedPositionIntent`` stream (Inv-5 determinism).
* Per-strategy fill attribution is independent across the three
  alpha boundaries.

Active-aggregator note
----------------------

``HorizonAggregator`` runs in passive mode (empty ``values``) in
v0.2.  The SIGNAL evaluate functions (which gate on
``kyle_lambda_60s_percentile``, ``ofi_ewma``, etc.) therefore return
``None`` for every snapshot and the composition cycle fires with zero
effective cross-sectional signals.  ``SizedPositionIntent`` events are
still emitted but with empty ``target_positions`` (the degenerate
intent path defined in ``CompositionEngine``).

The determinism assertions are therefore meaningful regression guards:
they verify that the degenerate intent stream is bit-stable across
replays.  Once the Phase-3.5 active aggregator ships the intent stream
will become non-degenerate without requiring test rewrite.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from feelies.bootstrap import build_platform
from feelies.composition.engine import CompositionEngine
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    Signal,
    SizedPositionIntent,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.quote_hazard_rate import QuoteHazardRateSensor
from feelies.sensors.impl.quote_replenish_asymmetry import (
    QuoteReplenishAsymmetrySensor,
)
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.integration.portfolio_test_constants import (
    FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE,
)


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]

_KYLE_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_kyle_drift_v1"
    / "pofi_kyle_drift_v1.alpha.yaml"
)
_INVENTORY_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_inventory_revert_v1"
    / "pofi_inventory_revert_v1.alpha.yaml"
)
_XSECT_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_xsect_v1"
    / "pofi_xsect_v1.alpha.yaml"
)
_FACTOR_LOADINGS_DIR = _REPO_ROOT / "data" / "reference" / "factor_loadings"
_SECTOR_MAP_PATH = (
    _REPO_ROOT / "data" / "reference" / "sector_map" / "sector_map.json"
)

# 10-symbol reference universe — must match alphas/pofi_xsect_v1/universe.
_UNIVERSE: tuple[str, ...] = (
    "AAPL", "AMZN", "BAC", "CVX", "GOOG",
    "JPM", "META", "MSFT", "NVDA", "XOM",
)

# 360 seconds at 10 Hz per symbol — long enough to cross one 300 s
# horizon boundary (the portfolio's decision horizon).
_QUOTES_PER_SYMBOL: int = 3_600


_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    # NBBOQuote sensors — needed by both feeder alphas.
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
        sensor_id="quote_replenish_asymmetry",
        sensor_version="1.0.0",
        cls=QuoteReplenishAsymmetrySensor,
        params={"min_observations": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="quote_hazard_rate",
        sensor_version="1.0.0",
        cls=QuoteHazardRateSensor,
        params={"min_samples": 5},
        subscribes_to=(NBBOQuote,),
    ),
    # Trade sensor — needed by pofi_kyle_drift_v1.
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="1.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 5},
        subscribes_to=(Trade,),
    ),
)


def _synth_multi_symbol_events(seed: int = 42) -> list[Any]:
    """Deterministic 360-second multi-symbol NBBOQuote/Trade stream.

    Each symbol gets its own ``random.Random`` derived from the master
    seed and its index so per-symbol price walks are independent yet
    reproducible.  Events are merged on ``(timestamp_ns, symbol)`` for
    deterministic interleaving.
    """
    quote_cadence_ns: int = 100_000_000  # 10 Hz
    starting_prices_cents: dict[str, int] = {
        "AAPL": 18000, "AMZN": 13000, "BAC":  3000, "CVX": 14000,
        "GOOG": 14000, "JPM": 14500, "META": 31000, "MSFT": 37000,
        "NVDA": 45000, "XOM":  10500,
    }

    all_events: list[tuple[int, str, dict[str, Any]]] = []
    for sym_idx, symbol in enumerate(_UNIVERSE):
        rng = random.Random(seed * 100 + sym_idx)
        last_mid = starting_prices_cents[symbol]
        for i in range(_QUOTES_PER_SYMBOL):
            ts_ns = SESSION_OPEN_NS + i * quote_cadence_ns
            delta = rng.choice((-1, 0, 0, 0, 1))
            last_mid = max(1, last_mid + delta)
            bid_cents = last_mid
            ask_cents = last_mid + 1
            bid_size = rng.choice((100, 200, 300, 400, 500))
            ask_size = rng.choice((100, 200, 300, 400, 500))
            quote = NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=sym_idx * _QUOTES_PER_SYMBOL + i,
                correlation_id=f"synth-q-{symbol}-{i}",
                source_layer="INGESTION",
                symbol=symbol,
                bid=Decimal(bid_cents) / Decimal(100),
                ask=Decimal(ask_cents) / Decimal(100),
                bid_size=bid_size,
                ask_size=ask_size,
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11,
                ask_exchange=11,
                tape=3,
            )
            all_events.append(
                (ts_ns, symbol, {"event": quote, "kind": "Q"})
            )
            if i % 7 == 0 and i > 0:
                side_buy = rng.random() < 0.5
                price_cents = last_mid + (1 if side_buy else 0)
                trade = Trade(
                    timestamp_ns=ts_ns + 1,
                    sequence=sym_idx * _QUOTES_PER_SYMBOL * 2 + i,
                    correlation_id=f"synth-t-{symbol}-{i}",
                    source_layer="INGESTION",
                    symbol=symbol,
                    price=Decimal(price_cents) / Decimal(100),
                    size=rng.choice((50, 100, 150, 200)),
                    exchange=11,
                    trade_id=f"synth-{symbol}-{i:08d}",
                    exchange_timestamp_ns=ts_ns + 1,
                    tape=3,
                )
                all_events.append(
                    (ts_ns + 1, symbol, {"event": trade, "kind": "T"})
                )

    all_events.sort(key=lambda r: (r[0], r[1]))
    return [r[2]["event"] for r in all_events]


def _make_xsect_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_KYLE_ALPHA, _INVENTORY_ALPHA, _XSECT_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        factor_loadings_dir=_FACTOR_LOADINGS_DIR,
        factor_loadings_max_age_seconds=FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE,
        sector_map_path=_SECTOR_MAP_PATH,
        # Both feeder alphas declare trend_mechanism blocks; strict mode
        # must stay ON to validate the G16 rule set.
        enforce_trend_mechanism=True,
    )


def _build() -> tuple[
    Orchestrator,
    list[Signal],
    list[SizedPositionIntent],
    list[OrderRequest],
]:
    config = _make_xsect_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_multi_symbol_events())

    orchestrator, _ = build_platform(config, event_log=event_log)

    captured_signals: list[Signal] = []
    captured_intents: list[SizedPositionIntent] = []
    captured_orders: list[OrderRequest] = []
    orchestrator._bus.subscribe(Signal, captured_signals.append)
    orchestrator._bus.subscribe(SizedPositionIntent, captured_intents.append)
    orchestrator._bus.subscribe(OrderRequest, captured_orders.append)

    orchestrator.boot(config)
    orchestrator.run_backtest()
    return orchestrator, captured_signals, captured_intents, captured_orders


def _hash_intents(intents: list[SizedPositionIntent]) -> str:
    lines: list[str] = []
    for it in intents:
        targets = "|".join(
            f"{s}={it.target_positions[s].target_usd:.2f}"
            for s in sorted(it.target_positions)
        )
        lines.append(
            f"{it.sequence}|{it.timestamp_ns}|{it.strategy_id}|"
            f"{it.layer}|{it.horizon_seconds}|{it.correlation_id}|"
            f"GE={it.expected_gross_exposure_usd:.2f}|"
            f"TO={it.expected_turnover_usd:.2f}|TGT[{targets}]"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Wiring ──────────────────────────────────────────────────────────────


def test_xsect_v1_e2e_all_three_alphas_register() -> None:
    """All three layers must register without error.

    ``pofi_kyle_drift_v1`` and ``pofi_inventory_revert_v1`` as SIGNAL
    feeders, ``pofi_xsect_v1`` as the PORTFOLIO consumer.
    """
    orchestrator, _s, _i, _o = _build()
    registry = orchestrator._alpha_registry
    assert registry is not None
    ids = registry.alpha_ids()
    assert "pofi_kyle_drift_v1" in ids
    assert "pofi_inventory_revert_v1" in ids
    assert "pofi_xsect_v1" in ids


def test_xsect_v1_e2e_composition_layer_is_wired() -> None:
    orchestrator, _s, _i, _o = _build()
    assert isinstance(orchestrator._composition_engine, CompositionEngine)
    assert isinstance(
        orchestrator._cross_sectional_tracker, CrossSectionalTracker
    )
    assert isinstance(
        orchestrator._composition_metrics_collector,
        HorizonMetricsCollector,
    )
    # pofi_xsect_v1 does not opt into hazard_exit → controller is None.
    assert orchestrator._hazard_exit_controller is None


def test_xsect_v1_e2e_run_completes_and_reaches_ready() -> None:
    orchestrator, _s, _i, _o = _build()
    assert orchestrator.macro_state == MacroState.READY


def test_xsect_v1_e2e_composition_cycle_fires() -> None:
    """At least one SizedPositionIntent must be emitted.

    360 seconds of synthetic event-time data crosses the 300-second
    decision horizon, triggering at least one composition cycle.  The
    intent may be degenerate (empty target_positions) in v0.2 passive-
    aggregator mode; what matters is that the composition pipeline does
    not silently drop the barrier event.
    """
    _o, _s, intents, _orders = _build()
    assert len(intents) >= 1, (
        "Expected at least one SizedPositionIntent across a 360-second "
        "backtest with a 300-second decision horizon, but got zero.  "
        "CompositionEngine may not be subscribing to HorizonTick or the "
        "360-second stream does not reach a 300-second boundary."
    )
    strategy_ids = {it.strategy_id for it in intents}
    assert "pofi_xsect_v1" in strategy_ids


def test_xsect_v1_e2e_per_strategy_positions_independent() -> None:
    """Layer-3 fills must never bleed across strategy boundaries."""
    orchestrator, _s, _i, _o = _build()
    sp = orchestrator._strategy_positions
    assert sp is not None
    for sym in _UNIVERSE:
        kyle_pos = sp.get("pofi_kyle_drift_v1", sym)
        inv_pos = sp.get("pofi_inventory_revert_v1", sym)
        xsect_pos = sp.get("pofi_xsect_v1", sym)
        # Distinct objects — StrategyPositionStore keys by (alpha, sym).
        assert kyle_pos is not inv_pos
        assert kyle_pos is not xsect_pos
        assert inv_pos is not xsect_pos


# ── Determinism (Inv-5) ─────────────────────────────────────────────────


def test_xsect_v1_e2e_intent_stream_is_deterministic() -> None:
    """Two identical replays must produce byte-identical intent streams.

    Covers Inv-5: the composition pipeline (ranker → factor-neutralizer
    → sector-matcher → turnover-optimizer) must produce the same output
    given the same bus-event sequence.  Any source of non-determinism
    (dict iteration order, float accumulation divergence, sequence-
    number drift) will surface here.
    """
    _o_a, _s_a, intents_a, _ord_a = _build()
    _o_b, _s_b, intents_b, _ord_b = _build()

    assert len(intents_a) == len(intents_b), (
        f"SizedPositionIntent count drifted across replays: "
        f"{len(intents_a)} vs {len(intents_b)}"
    )
    assert _hash_intents(intents_a) == _hash_intents(intents_b), (
        "pofi_xsect_v1 SizedPositionIntent hash drift across identical "
        "replays (Inv-5 violation)"
    )
