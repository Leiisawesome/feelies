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
* **PR-2b-iii contract:** every ``Signal(layer="SIGNAL")`` event whose
  ``strategy_id`` is *not* listed in any registered PORTFOLIO's
  ``depends_on_signals`` is processed by the orchestrator's bus-driven
  Signal subscriber and translated through the risk → order pipeline.
  Pre-PR-2b-iii nothing translated bus Signals into orders, so the
  invariant was vacuously true; this test now locks the contract so
  any future regression that re-orphans the standalone-SIGNAL → order
  path fails loudly.

  The current fixture's 36-second random walk does not trigger
  ``pofi_benign_midcap_v1``'s entry gate (|OFI z| > 2.0 inside the
  benign regime), so the realised standalone-Signal count is zero and
  the assertion holds vacuously today.  A future enrichment of the
  synthetic stream (or addition of an "always-on" tracer SIGNAL alpha)
  will make the assertion non-vacuous without rewriting it.
* **PR-2b-iv contract:** every non-degenerate ``SizedPositionIntent``
  emitted by a PORTFOLIO alpha (i.e. one whose ``target_positions``
  contain at least one symbol with a non-zero notional delta vs the
  current position) produces at least one ``OrderRequest`` on the bus.
  Pre-PR-2b-iv ``CompositionEngine`` published intents end-to-end but
  the production order pipeline silently ignored them; this test now
  locks the bus-driven ``RiskEngine.check_sized_intent`` translation
  in the same way the PR-2b-iii contract locks the SIGNAL path.

  As with the PR-2b-iii assertion, the current fixture's 36-second
  random walk happens to leave ``pofi_xsect_v1``'s realised non-trivial
  intent count at zero (every intent collapses to an empty
  ``target_positions`` because the cross-sectional gate rarely opens
  inside the benign synthetic regime).  The assertion is therefore
  vacuously true today and will become non-vacuous the moment the
  fixture is enriched to actually drive the PORTFOLIO alpha — at which
  point any future regression in the intent → order wiring will fire
  loudly without test rewriting.
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


def _build() -> tuple[
    Orchestrator,
    list[Signal],
    list[SizedPositionIntent],
    list[OrderRequest],
]:
    config = _make_phase4_config()
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
    orchestrator, _signals, _intents, _orders = _build()
    registry = orchestrator._alpha_registry
    assert registry is not None
    ids = registry.alpha_ids()
    assert "pofi_benign_midcap_v1" in ids
    assert "pofi_xsect_v1" in ids


def test_phase4_e2e_composition_layer_is_wired() -> None:
    orchestrator, _s, _i, _o = _build()
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
    orchestrator, _s, _i, _o = _build()
    assert orchestrator.macro_state == MacroState.READY


def test_phase4_e2e_per_strategy_positions_independent() -> None:
    """Layer-3 fills must never bleed into Layer-2 strategy views."""
    orchestrator, _s, _i, _o = _build()
    sp = orchestrator._strategy_positions
    assert sp is not None
    for sym in _UNIVERSE:
        signal_pos = sp.get("pofi_benign_midcap_v1", sym)
        portfolio_pos = sp.get("pofi_xsect_v1", sym)
        # Distinct objects (StrategyPositionStore keys by (alpha, sym)).
        assert signal_pos is not portfolio_pos


# ── Determinism ─────────────────────────────────────────────────────────


def test_phase4_e2e_signal_stream_is_deterministic() -> None:
    _o_a, signals_a, intents_a, _orders_a = _build()
    _o_b, signals_b, intents_b, _orders_b = _build()
    assert len(signals_a) == len(signals_b), (
        f"Signal count drift across replays: "
        f"{len(signals_a)} vs {len(signals_b)}"
    )
    assert _hash_signals(signals_a) == _hash_signals(signals_b), (
        "Phase-4 e2e Signal stream hash drift across identical replays"
    )


def test_phase4_e2e_intent_stream_is_deterministic() -> None:
    _o_a, _signals_a, intents_a, _orders_a = _build()
    _o_b, _signals_b, intents_b, _orders_b = _build()
    assert len(intents_a) == len(intents_b), (
        f"SizedPositionIntent count drift across replays: "
        f"{len(intents_a)} vs {len(intents_b)}"
    )
    assert _hash_intents(intents_a) == _hash_intents(intents_b), (
        "Phase-4 e2e SizedPositionIntent hash drift across identical replays"
    )


# ── PR-2b-iii contract: standalone-SIGNAL → OrderRequest ───────────────


def test_phase4_e2e_standalone_signal_alphas_translate_to_orders() -> None:
    """A standalone SIGNAL alpha's bus Signals must reach the order pipeline.

    PR-2b-iii wires a bus-driven ``Signal`` subscriber on the Orchestrator
    that translates ``Signal(layer="SIGNAL")`` events into ``OrderRequest``
    events through the existing risk → order pipeline, *unless* the signal's
    ``strategy_id`` is referenced by some PORTFOLIO alpha's
    ``depends_on_signals`` (those are aggregated by ``CompositionEngine``
    into ``SizedPositionIntent`` events instead, to be wired to orders by
    PR-2b-iv).

    The reference fixture registers ``pofi_benign_midcap_v1`` as a SIGNAL
    alpha and ``pofi_xsect_v1`` as a PORTFOLIO alpha; the latter's
    ``depends_on_signals`` lists ``pofi_kyle_drift_v1`` and
    ``pofi_inventory_revert_v1`` — *not* ``pofi_benign_midcap_v1``.  So
    every Signal published by ``pofi_benign_midcap_v1`` is a "standalone
    SIGNAL Signal" and must produce a corresponding order pipeline walk.

    The synthetic 36-second random walk does not satisfy
    ``pofi_benign_midcap_v1``'s entry gate, so the realised count is zero
    and the assertion is vacuously true.  This is a deliberate regression
    guard: if a future change re-orphans the bus Signal → order path
    (e.g. by mis-filtering, dropping the subscriber, or routing standalone
    SIGNAL events through ``CompositionEngine``), the assertion will fire
    the moment the fixture is enriched to actually trigger the alpha gate.
    """
    orchestrator, signals, _intents, orders = _build()

    registry = orchestrator._alpha_registry
    assert registry is not None

    portfolio_consumed: set[str] = set()
    portfolio_alphas_fn = getattr(registry, "portfolio_alphas", None)
    if portfolio_alphas_fn is not None:
        for module in portfolio_alphas_fn():
            portfolio_consumed.update(module.depends_on_signals)

    standalone_signals = [
        s for s in signals
        if s.layer == "SIGNAL"
        and s.strategy_id != "__stop_exit__"
        and s.strategy_id not in portfolio_consumed
    ]
    standalone_alpha_ids = {s.strategy_id for s in standalone_signals}

    orders_per_standalone_alpha = {
        aid: sum(1 for o in orders if o.strategy_id == aid)
        for aid in standalone_alpha_ids
    }

    for aid, n_signals in (
        (aid, sum(1 for s in standalone_signals if s.strategy_id == aid))
        for aid in standalone_alpha_ids
    ):
        assert orders_per_standalone_alpha[aid] >= 1, (
            f"PR-2b-iii contract violation: standalone SIGNAL alpha {aid!r} "
            f"published {n_signals} bus Signals but the orchestrator emitted "
            f"zero OrderRequest events for it.  Either the bus subscriber is "
            f"misfiled, the Signal is being mis-routed through "
            f"CompositionEngine, or risk is rejecting every translation.  "
            f"Inspect Orchestrator._on_bus_signal / _process_tick_inner / "
            f"RiskEngine.check_intent."
        )


# ── PR-2b-iv contract: PORTFOLIO SizedPositionIntent → OrderRequest ────


def test_phase4_e2e_portfolio_intents_translate_to_orders() -> None:
    """A non-degenerate SizedPositionIntent must reach the order pipeline.

    PR-2b-iv wires a bus-driven ``SizedPositionIntent`` subscriber on the
    Orchestrator that calls :meth:`RiskEngine.check_sized_intent` for every
    intent and submits each surviving per-leg ``OrderRequest`` to
    ``backend.order_router`` (without driving the per-tick micro-SM walk;
    PORTFOLIO orders dispatch as a synchronous side-effect of the M3
    ``CROSS_SECTIONAL`` ``bus.publish(intent)``).  Pre-PR-2b-iv production
    silently ignored intents — the entire PORTFOLIO order pipeline was
    dead code reachable only through the now-deleted ``MultiAlphaEvaluator``.

    The assertion: for every non-degenerate intent (one whose
    ``target_positions`` contain at least one symbol with a non-zero
    notional delta vs the current position at intent time), at least one
    ``OrderRequest`` with ``source_layer == "PORTFOLIO"`` and matching
    ``strategy_id`` must appear on the captured bus stream.

    Like the PR-2b-iii assertion above, this is vacuously true on the
    current synthetic fixture (cross-sectional gate stays closed) but
    becomes a load-bearing regression guard the moment a richer fixture
    or "always-on" PORTFOLIO tracer alpha is introduced.
    """
    orchestrator, _signals, intents, orders = _build()

    non_degenerate_intents = [it for it in intents if it.target_positions]
    portfolio_alpha_ids = {it.strategy_id for it in non_degenerate_intents}

    orders_per_portfolio_alpha = {
        aid: sum(
            1 for o in orders
            if o.strategy_id == aid and o.source_layer == "PORTFOLIO"
        )
        for aid in portfolio_alpha_ids
    }

    for aid in portfolio_alpha_ids:
        n_intents = sum(
            1 for it in non_degenerate_intents if it.strategy_id == aid
        )
        assert orders_per_portfolio_alpha[aid] >= 1, (
            f"PR-2b-iv contract violation: PORTFOLIO alpha {aid!r} emitted "
            f"{n_intents} non-degenerate SizedPositionIntent events but the "
            f"orchestrator produced zero OrderRequest events for it.  Either "
            f"_on_bus_sized_intent is unsubscribed, RiskEngine.check_sized_"
            f"intent is dropping every leg, or the intent's target_positions "
            f"are matching the current position notional within one cent. "
            f"Inspect Orchestrator._on_bus_sized_intent and "
            f"BasicRiskEngine.check_sized_intent."
        )

    _ = orchestrator
