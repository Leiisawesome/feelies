"""End-to-end mixed SIGNAL and PORTFOLIO operation over ten symbols.

The suite covers registration, composition wiring, replay determinism,
strategy attribution, standalone signal orders, and intent-to-order routing.
The short fixture may produce empty trading streams; locked counts and hashes
still pin that behavior.
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
from feelies.sensors.impl.book_imbalance import BookImbalanceSensor
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.reference.paths import FACTOR_LOADINGS_DIR, SECTOR_MAP_PATH
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.integration.portfolio_test_constants import (
    FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE,
)


pytestmark = pytest.mark.backtest_validation


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIGNAL_ALPHA = _REPO_ROOT / "alphas" / "sig_benign_midcap_v1" / "sig_benign_midcap_v1.alpha.yaml"
_KYLE_ALPHA = _REPO_ROOT / "alphas" / "sig_kyle_drift_v1" / "sig_kyle_drift_v1.alpha.yaml"
_PORTFOLIO_ALPHA = (
    _REPO_ROOT / "alphas" / "research" / "pro_kyle_benign_v1" / "pro_kyle_benign_v1.alpha.yaml"
)
_FACTOR_LOADINGS_DIR = FACTOR_LOADINGS_DIR
_SECTOR_MAP_PATH = SECTOR_MAP_PATH

# 10-symbol reference universe — wider than pro_kyle_benign_v1's single-symbol
# universe (AAPL); the PORTFOLIO alpha filters to its declared universe internally.
_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "AMZN",
    "BAC",
    "CVX",
    "GOOG",
    "JPM",
    "META",
    "MSFT",
    "NVDA",
    "XOM",
)
_QUOTES_PER_SYMBOL: int = 360  # 36 seconds @ 10 Hz — short by design


_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    # Required by sig_benign_midcap_v1.
    SensorSpec(
        sensor_id="book_imbalance",
        sensor_version="1.0.0",
        cls=BookImbalanceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 8},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        # Pin the causal alignment used by production.
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 5},
        subscribes_to=(NBBOQuote, Trade),
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
        "AAPL": 18000,
        "AMZN": 13000,
        "BAC": 3000,
        "CVX": 14000,
        "GOOG": 14000,
        "JPM": 14500,
        "META": 31000,
        "MSFT": 37000,
        "NVDA": 45000,
        "XOM": 10500,
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
                all_events.append((ts_ns + 1, symbol, {"event": trade, "kind": "T"}))

    # Sort by (timestamp_ns, symbol) for deterministic interleaving.
    all_events.sort(key=lambda r: (r[0], r[1]))
    return [r[2]["event"] for r in all_events]


def _make_phase4_config() -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_SIGNAL_ALPHA, _KYLE_ALPHA, _PORTFOLIO_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        factor_loadings_dir=_FACTOR_LOADINGS_DIR,
        factor_loadings_max_age_seconds=FACTOR_LOADINGS_MAX_AGE_SECONDS_FIXTURE,
        sector_map_path=_SECTOR_MAP_PATH,
        # Reference SIGNAL alpha carries ``trend_mechanism:`` (G16); keep
        # strict mechanism enforcement off here so the fixture focuses on
        # Exercise composition wiring rather than strict-loader defaults.
        enforce_trend_mechanism=False,
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


def _hash_orders(orders: list[OrderRequest]) -> str:
    lines: list[str] = []
    for o in sorted(orders, key=lambda x: (x.sequence, x.order_id)):
        lp = "" if o.limit_price is None else str(o.limit_price)
        lines.append(
            f"{o.sequence}|{o.order_id}|{o.symbol}|{o.side.name}|"
            f"{o.order_type.name}|{o.quantity}|{lp}|"
            f"{o.strategy_id}|{o.timestamp_ns}|{o.correlation_id}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _hash_positions_book(orch: Orchestrator) -> str:
    store = orch._positions
    lines: list[str] = []
    for sym in sorted(store.all_positions()):
        p = store.get(sym)
        lines.append(
            f"{sym}|{p.quantity}|{p.avg_entry_price}|"
            f"{p.realized_pnl}|{p.cumulative_fees}|{p.unrealized_pnl}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _hash_trade_journal(orch: Orchestrator) -> str:
    tj = orch._trade_journal
    if tj is None:
        return hashlib.sha256(b"").hexdigest()
    recs = list(tj.query())
    lines: list[str] = []
    for r in sorted(recs, key=lambda x: (x.fill_timestamp_ns or 0, x.order_id)):
        fp = "" if r.fill_price is None else str(r.fill_price)
        lines.append(
            f"{r.order_id}|{r.symbol}|{r.strategy_id}|{r.side.name}|"
            f"{r.requested_quantity}|{r.filled_quantity}|{fp}|"
            f"{r.signal_timestamp_ns}|{r.submit_timestamp_ns}|"
            f"{r.fill_timestamp_ns}|{r.cost_bps}|{r.fees}|"
            f"{r.realized_pnl}|{r.correlation_id}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _hash_intents(intents: list[SizedPositionIntent]) -> str:
    lines: list[str] = []
    for it in intents:
        targets = "|".join(
            f"{s}={it.target_positions[s].target_usd:.2f}" for s in sorted(it.target_positions)
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

    This covers SIGNAL inputs feeding PORTFOLIO composition.
    """
    orchestrator, _signals, _intents, _orders = _build()
    registry = orchestrator._alpha_registry
    assert registry is not None
    ids = registry.alpha_ids()
    assert "sig_benign_midcap_v1" in ids
    assert "sig_kyle_drift_v1" in ids
    assert "pro_kyle_benign_v1" in ids


def test_phase4_e2e_composition_layer_is_wired() -> None:
    orchestrator, _s, _i, _o = _build()
    assert isinstance(orchestrator._composition_engine, CompositionEngine)
    assert isinstance(orchestrator._cross_sectional_tracker, CrossSectionalTracker)
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
        signal_pos = sp.get("sig_benign_midcap_v1", sym)
        kyle_pos = sp.get("sig_kyle_drift_v1", sym)
        portfolio_pos = sp.get("pro_kyle_benign_v1", sym)
        # Distinct objects (StrategyPositionStore keys by (alpha, sym)).
        assert signal_pos is not kyle_pos
        assert signal_pos is not portfolio_pos
        assert kyle_pos is not portfolio_pos


# ── Determinism ─────────────────────────────────────────────────────────


def test_phase4_e2e_signal_stream_is_deterministic() -> None:
    _o_a, signals_a, intents_a, _orders_a = _build()
    _o_b, signals_b, intents_b, _orders_b = _build()
    assert len(signals_a) == len(signals_b), (
        f"Signal count drift across replays: {len(signals_a)} vs {len(signals_b)}"
    )
    assert _hash_signals(signals_a) == _hash_signals(signals_b), (
        "Phase-4 e2e Signal stream hash drift across identical replays"
    )


def test_phase4_e2e_intent_stream_is_deterministic() -> None:
    _o_a, _signals_a, intents_a, _orders_a = _build()
    _o_b, _signals_b, intents_b, _orders_b = _build()
    assert len(intents_a) == len(intents_b), (
        f"SizedPositionIntent count drift across replays: {len(intents_a)} vs {len(intents_b)}"
    )
    assert _hash_intents(intents_a) == _hash_intents(intents_b), (
        "Phase-4 e2e SizedPositionIntent hash drift across identical replays"
    )


def test_phase4_e2e_order_stream_is_deterministic() -> None:
    """Same synthetic log + config → identical OrderRequest bus stream."""
    _o_a, _sa, _ia, orders_a = _build()
    _o_b, _sb, _ib, orders_b = _build()
    assert len(orders_a) == len(orders_b), (
        f"OrderRequest count drift: {len(orders_a)} vs {len(orders_b)}"
    )
    assert _hash_orders(orders_a) == _hash_orders(orders_b), (
        "Phase-4 e2e OrderRequest hash drift across identical replays"
    )


def test_phase4_e2e_final_positions_and_journal_are_deterministic() -> None:
    """Full replay outcomes (positions + trade journal) are replay-stable."""
    o_a, *_rest_a = _build()
    o_b, *_rest_b = _build()
    assert _hash_positions_book(o_a) == _hash_positions_book(o_b), (
        "Position book hash drift across identical replays"
    )
    assert _hash_trade_journal(o_a) == _hash_trade_journal(o_b), (
        "Trade journal hash drift across identical replays"
    )


# ── Locked end-to-end baselines ─────────────────────────────────────────
#
# These constants catch stable drift as well as nondeterminism. The fixture's
# uncalibrated regime keeps all entry gates off, so it emits no signals or
# orders and leaves the book and journal empty. Composition still emits one
# empty intent, whose hash pins the output.
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

EXPECTED_E2E_SIGNAL_COUNT = 0
EXPECTED_E2E_SIGNAL_HASH = _EMPTY_SHA256
EXPECTED_E2E_INTENT_COUNT = 1
EXPECTED_E2E_INTENT_HASH = "e1250a7e84eb1e102ab25c0777b308b4cf8f9354954f9088c07f6a113e04c24e"
EXPECTED_E2E_ORDER_COUNT = 0
EXPECTED_E2E_ORDER_HASH = _EMPTY_SHA256
EXPECTED_E2E_POSITIONS_HASH = _EMPTY_SHA256
EXPECTED_E2E_JOURNAL_HASH = _EMPTY_SHA256


def test_phase4_e2e_matches_locked_baselines() -> None:
    """End-to-end orchestrator-boot baseline (not just two-run identity)."""
    orch, signals, intents, orders = _build()

    assert len(signals) == EXPECTED_E2E_SIGNAL_COUNT, (
        f"e2e signal count drift: expected {EXPECTED_E2E_SIGNAL_COUNT}, got {len(signals)} "
        "— the fixture's gates fail safe to OFF; a non-zero count means "
        "regime/gate semantics changed (investigate before re-baselining)"
    )
    assert _hash_signals(signals) == EXPECTED_E2E_SIGNAL_HASH

    assert len(intents) == EXPECTED_E2E_INTENT_COUNT, (
        f"e2e intent count drift: expected {EXPECTED_E2E_INTENT_COUNT}, got {len(intents)}"
    )
    assert _hash_intents(intents) == EXPECTED_E2E_INTENT_HASH, (
        "Phase-4 e2e SizedPositionIntent baseline drift!\n"
        f"  Expected: {EXPECTED_E2E_INTENT_HASH}\n"
        f"  Actual:   {_hash_intents(intents)}\n"
        "If intentional, update the constant in the same commit and justify."
    )

    assert len(orders) == EXPECTED_E2E_ORDER_COUNT, (
        f"e2e order count drift: expected {EXPECTED_E2E_ORDER_COUNT}, got {len(orders)} "
        "— a non-zero count means the fixture started trading (investigate)"
    )
    assert _hash_orders(orders) == EXPECTED_E2E_ORDER_HASH

    assert _hash_positions_book(orch) == EXPECTED_E2E_POSITIONS_HASH, (
        "Phase-4 e2e final position-book baseline drift"
    )
    assert _hash_trade_journal(orch) == EXPECTED_E2E_JOURNAL_HASH, (
        "Phase-4 e2e trade-journal baseline drift"
    )


# Standalone signal-to-order contract.


def test_phase4_e2e_standalone_signal_alphas_translate_to_orders() -> None:
    """Standalone bus signals reach orders unless a portfolio consumes them."""
    orchestrator, signals, _intents, orders = _build()

    registry = orchestrator._alpha_registry
    assert registry is not None

    portfolio_consumed: set[str] = set()
    portfolio_alphas_fn = getattr(registry, "portfolio_alphas", None)
    if portfolio_alphas_fn is not None:
        for module in portfolio_alphas_fn():
            portfolio_consumed.update(module.depends_on_signals)

    standalone_signals = [
        s
        for s in signals
        if s.layer == "SIGNAL"
        and s.strategy_id != "__stop_exit__"
        and s.strategy_id not in portfolio_consumed
    ]
    standalone_alpha_ids = {s.strategy_id for s in standalone_signals}

    orders_per_standalone_alpha = {
        aid: sum(1 for o in orders if o.strategy_id == aid) for aid in standalone_alpha_ids
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


# Portfolio intent-to-order contract.


def test_phase4_e2e_portfolio_intents_translate_to_orders() -> None:
    """Each nonzero portfolio intent produces a matching portfolio order."""
    orchestrator, _signals, intents, orders = _build()

    non_degenerate_intents = [it for it in intents if it.target_positions]
    portfolio_alpha_ids = {it.strategy_id for it in non_degenerate_intents}

    orders_per_portfolio_alpha = {
        aid: sum(1 for o in orders if o.strategy_id == aid and o.source_layer == "PORTFOLIO")
        for aid in portfolio_alpha_ids
    }

    for aid in portfolio_alpha_ids:
        n_intents = sum(1 for it in non_degenerate_intents if it.strategy_id == aid)
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
