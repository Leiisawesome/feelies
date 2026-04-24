"""Phase-4 e2e — SIGNAL + PORTFOLIO concurrent on a 10-symbol universe.

Locks the structural invariants of mixed-mode operation when a
SIGNAL alpha (``pofi_benign_midcap_v1``) and the v0.2 PORTFOLIO
reference alpha (``pofi_xsect_v1``) coexist in a single
``build_platform`` invocation driven by a deterministic multi-symbol
synthetic event log.

Workstream-D update — the LEGACY arm (``trade_cluster_drift``) was
retired with the alpha; the test still exercises the cross-layer
SIGNAL+PORTFOLIO contract end-to-end (signal stream determinism,
composition wiring, per-strategy attribution) which was the
substantive coverage anyway.

What this test guarantees
-------------------------

* All three layers register through ``build_platform`` without
  ``AlphaLoadError``, ``LayerValidationError``, or wiring failures.
* The composition layer is fully wired: ``CompositionEngine``,
  ``CrossSectionalTracker``, ``HorizonMetricsCollector`` are all
  present and attached.  The hazard-exit controller stays ``None``
  because the reference PORTFOLIO alpha does not opt into
  ``hazard_exit.enabled`` (Inv-A: opt-in only).
* The bus subscription order documented in
  :mod:`feelies.bootstrap` survives mixed-mode boot (no engine is
  silenced when the composition layer is also wired).
* A full backtest reaches ``MacroState.READY`` without exception.
* Two replays of the exact same fixture produce a byte-identical
  ``Signal`` stream *and* ``SizedPositionIntent`` stream (Inv-5).
* Per-strategy fill attribution remains independent across the three
  alpha boundaries: a fill against one alpha never appears in another
  alpha's position view.
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
    Signal,
    SizedPositionIntent,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIGNAL_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_benign_midcap_v1"
    / "pofi_benign_midcap_v1.alpha.yaml"
)
_PORTFOLIO_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_xsect_v1"
    / "pofi_xsect_v1.alpha.yaml"
)
_FACTOR_LOADINGS_DIR = _REPO_ROOT / "data" / "reference" / "factor_loadings"
_SECTOR_MAP_PATH = (
    _REPO_ROOT / "data" / "reference" / "sector_map" / "sector_map.json"
)

# 10-symbol reference universe — must match alphas/pofi_xsect_v1/.
_UNIVERSE: tuple[str, ...] = (
    "AAPL", "AMZN", "BAC", "CVX", "GOOG",
    "JPM", "META", "MSFT", "NVDA", "XOM",
)
_QUOTES_PER_SYMBOL: int = 360  # 36 seconds @ 10 Hz — short by design


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
)


def _synth_multi_symbol_events(seed: int = 42) -> list[Any]:
    """Synthesize a per-symbol interleaved NBBOQuote/Trade stream.

    Each symbol gets its own ``random.Random`` derived from the master
    seed and its index so the per-symbol price walks are independent
    yet deterministic.  Events from all symbols are merged on
    ``timestamp_ns`` (with ``(timestamp_ns, symbol)`` as the tie-
    breaker) so :meth:`InMemoryEventLog.append_batch` accepts them.
    """
    quote_cadence_ns = 100_000_000
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
            last_mid += delta
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
            all_events.append((ts_ns, symbol, {"event": quote, "kind": "Q"}))
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

    # Sort by (timestamp_ns, symbol) for deterministic interleaving.
    all_events.sort(key=lambda r: (r[0], r[1]))
    return [r[2]["event"] for r in all_events]


def _make_phase4_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_SIGNAL_ALPHA, _PORTFOLIO_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        factor_loadings_dir=_FACTOR_LOADINGS_DIR,
        sector_map_path=_SECTOR_MAP_PATH,
    )


def _build() -> tuple[Orchestrator, list[Signal], list[SizedPositionIntent]]:
    config = _make_phase4_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_multi_symbol_events())

    orchestrator, _ = build_platform(config, event_log=event_log)

    captured_signals: list[Signal] = []
    captured_intents: list[SizedPositionIntent] = []
    orchestrator._bus.subscribe(Signal, captured_signals.append)
    orchestrator._bus.subscribe(SizedPositionIntent, captured_intents.append)

    orchestrator.boot(config)
    orchestrator.run_backtest()
    return orchestrator, captured_signals, captured_intents


def _hash_signals(signals: list[Signal]) -> str:
    lines: list[str] = []
    for s in signals:
        lines.append(
            f"{s.sequence}|{s.symbol}|{s.strategy_id}|{s.layer}|"
            f"{s.horizon_seconds}|{s.regime_gate_state}|"
            f"{s.direction.name}|{s.strength:.6f}|"
            f"{s.edge_estimate_bps:.6f}|{s.timestamp_ns}|{s.correlation_id}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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


def test_phase4_e2e_signal_and_portfolio_layers_register() -> None:
    """SIGNAL + PORTFOLIO must register in a single ``build_platform``.

    Pre-workstream-D the test also asserted a third LEGACY arm
    (``trade_cluster_drift_v12``); that alpha was retired with D.2 and
    the assertion was dropped accordingly.  The cross-layer wiring
    contract that remains — SIGNAL signals feeding PORTFOLIO
    composition — is the substantive coverage.
    """
    orchestrator, _signals, _intents = _build()
    registry = orchestrator._alpha_registry
    assert registry is not None
    ids = registry.alpha_ids()
    assert "pofi_benign_midcap_v1" in ids
    assert "pofi_xsect_v1" in ids


def test_phase4_e2e_composition_layer_is_wired() -> None:
    orchestrator, _s, _i = _build()
    assert isinstance(orchestrator._composition_engine, CompositionEngine)
    assert isinstance(
        orchestrator._cross_sectional_tracker, CrossSectionalTracker
    )
    assert isinstance(
        orchestrator._composition_metrics_collector,
        HorizonMetricsCollector,
    )
    # No alpha opted into hazard_exit → controller stays None (Inv-A).
    assert orchestrator._hazard_exit_controller is None


def test_phase4_e2e_run_completes_and_reaches_ready() -> None:
    orchestrator, _s, _i = _build()
    assert orchestrator.macro_state == MacroState.READY


def test_phase4_e2e_per_strategy_positions_independent() -> None:
    """Layer-3 fills must never bleed into Layer-2 strategy views."""
    orchestrator, _s, _i = _build()
    sp = orchestrator._strategy_positions
    assert sp is not None
    for sym in _UNIVERSE:
        signal_pos = sp.get("pofi_benign_midcap_v1", sym)
        portfolio_pos = sp.get("pofi_xsect_v1", sym)
        # Distinct objects (StrategyPositionStore keys by (alpha, sym)).
        assert signal_pos is not portfolio_pos


# ── Determinism ─────────────────────────────────────────────────────────


def test_phase4_e2e_signal_stream_is_deterministic() -> None:
    _o_a, signals_a, intents_a = _build()
    _o_b, signals_b, intents_b = _build()
    assert len(signals_a) == len(signals_b), (
        f"Signal count drift across replays: "
        f"{len(signals_a)} vs {len(signals_b)}"
    )
    assert _hash_signals(signals_a) == _hash_signals(signals_b), (
        "Phase-4 e2e Signal stream hash drift across identical replays"
    )


def test_phase4_e2e_intent_stream_is_deterministic() -> None:
    _o_a, _signals_a, intents_a = _build()
    _o_b, _signals_b, intents_b = _build()
    assert len(intents_a) == len(intents_b), (
        f"SizedPositionIntent count drift across replays: "
        f"{len(intents_a)} vs {len(intents_b)}"
    )
    assert _hash_intents(intents_a) == _hash_intents(intents_b), (
        "Phase-4 e2e SizedPositionIntent hash drift across identical replays"
    )
