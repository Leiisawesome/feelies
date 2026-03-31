"""Tests for the H002 alpha across inline-spec and on-disk replay paths.

This module covers two cases:
1. An inline factory spec used for focused unit tests around ``mu_drift``.
2. The current on-disk H002 alpha used for end-to-end backtest replay.

Synthetic inline tick data:
    Ticks 1–5: stable quotes (warm-up, mu ≈ 0)
    Tick 6:    microprice rises  → positive drift → LONG
    Tick 7:    microprice drops  → negative drift → SHORT
    Tick 8:    stable (same as tick 7) → drift = 0 → no signal
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import pytest

from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    Signal,
    SignalDirection,
    StateTransition,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)


# ── H002 Alpha Factory ──────────────────────────────────────────────

H002_SPEC: dict = {
    "schema_version": "1.0",
    "alpha_id": "h002_sde_pde_mu_drift",
    "version": "4.0.0",
    "description": (
        "L1 microstructure alpha: EWMA microprice drift, "
        "normalized by mean absolute drift."
    ),
    "hypothesis": (
        "EWMA of microprice change dS, normalized by EWMA(|dS|), "
        "isolates persistent directional drift from noise."
    ),
    "falsification_criteria": [
        "OOS Sharpe < 0.80 net of costs",
        "Bootstrap p-value > 0.05",
    ],
    "symbols": ["AAPL"],
    "parameters": {
        "mu_threshold": {
            "type": "float",
            "default": 0.0005,
            "range": [0.0001, 0.01],
            "description": "Minimum |drift_z| for signal trigger.",
        },
        "max_spread_bp": {
            "type": "float",
            "default": 3.0,
            "range": [1.0, 10.0],
            "description": "Tight-spread regime filter (basis points).",
        },
        "mu_ema_alpha": {
            "type": "float",
            "default": 0.0,
            "range": [0.0, 0.999],
            "description": "EMA decay for drift.  0.0 = no smoothing (raw delta).",
        },
    },
    "risk_budget": {
        "max_position_per_symbol": 50000,
        "max_gross_exposure_pct": 100.0,
        "max_drawdown_pct": 1.0,
        "capital_allocation_pct": 100.0,
    },
    "features": {
        "mu_drift": {
            "version": "2.0.0",
            "description": "EWMA of microprice drift dS, normalized by EWMA(|dS|).",
            "warm_up": {"min_events": 5, "min_duration_ns": 0},
            "computation": (
                "def initial_state():\n"
                "    return {\n"
                '        "prev_microprice": None,\n'
                '        "ewma_drift": 0.0,\n'
                '        "ewma_abs_drift": 1e-12,\n'
                "    }\n"
                "\n"
                "def update(quote, state, params):\n"
                "    bid = float(quote.bid)\n"
                "    ask = float(quote.ask)\n"
                "    bid_size = float(quote.bid_size)\n"
                "    ask_size = float(quote.ask_size)\n"
                "\n"
                "    total_size = bid_size + ask_size\n"
                "    if total_size > 0:\n"
                "        microprice = (bid * ask_size + ask * bid_size)"
                " / total_size\n"
                "    else:\n"
                "        microprice = (bid + ask) / 2.0\n"
                "\n"
                '    if state["prev_microprice"] is None:\n'
                '        state["prev_microprice"] = microprice\n'
                "        return 0.0\n"
                "\n"
                '    delta = microprice - state["prev_microprice"]\n'
                '    state["prev_microprice"] = microprice\n'
                "\n"
                '    ema_alpha = params["mu_ema_alpha"]\n'
                '    state["ewma_drift"] = ema_alpha * state["ewma_drift"]'
                " + (1.0 - ema_alpha) * delta\n"
                '    state["ewma_abs_drift"] = ema_alpha * state["ewma_abs_drift"]'
                " + (1.0 - ema_alpha) * abs(delta)\n"
                "\n"
                '    norm = state["ewma_abs_drift"] + 1e-12\n'
                '    return float(state["ewma_drift"] / norm)\n'
            ),
        },
    },
    "signal": (
        "def evaluate(features, params):\n"
        '    mu = features.values.get("mu_drift", 0.0)\n'
        '    threshold = params["mu_threshold"]\n'
        "    if mu > threshold:\n"
        "        return Signal(\n"
        "            timestamp_ns=features.timestamp_ns,\n"
        "            correlation_id=features.correlation_id,\n"
        "            sequence=features.sequence,\n"
        "            symbol=features.symbol,\n"
        "            strategy_id=alpha_id,\n"
        "            direction=LONG,\n"
        "            strength=min(abs(mu) / (threshold * 3.0), 1.0),\n"
        "            edge_estimate_bps=abs(float(mu)) * 10000.0,\n"
        "        )\n"
        "    elif mu < -threshold:\n"
        "        return Signal(\n"
        "            timestamp_ns=features.timestamp_ns,\n"
        "            correlation_id=features.correlation_id,\n"
        "            sequence=features.sequence,\n"
        "            symbol=features.symbol,\n"
        "            strategy_id=alpha_id,\n"
        "            direction=SHORT,\n"
        "            strength=min(abs(mu) / (threshold * 3.0), 1.0),\n"
        "            edge_estimate_bps=abs(float(mu)) * 10000.0,\n"
        "        )\n"
        "    return None\n"
    ),
}


# ── Synthetic Tick Data ──────────────────────────────────────────────
#
# Ticks 1–5: stable (bid=150.00, ask=150.02) → warm-up, mu=0
# Tick 6:    bid=150.10, ask=150.20 → microprice rises (~150.01 → ~150.15)
#            delta=+0.14, |delta|=0.14, normalized=+1.0 → LONG
# Tick 7:    bid=149.80, ask=150.00 → microprice drops (~150.15 → ~149.90)
#            delta=-0.25, |delta|=0.25, normalized=-1.0 → SHORT
# Tick 8:    bid=149.80, ask=150.00 → unchanged → delta=0 → no signal

TICK_DATA: list[dict] = [
    {"bid": "150.00", "ask": "150.02", "bs": 100, "as": 100, "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.02", "bs": 100, "as": 100, "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.02", "bs": 100, "as": 100, "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.02", "bs": 100, "as": 100, "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.02", "bs": 100, "as": 100, "ts": 5_000_000_000},
    {"bid": "150.10", "ask": "150.20", "bs": 100, "as": 100, "ts": 6_000_000_000},
    {"bid": "149.80", "ask": "150.00", "bs": 100, "as": 100, "ts": 7_000_000_000},
    {"bid": "149.80", "ask": "150.00", "bs": 100, "as": 100, "ts": 8_000_000_000},
]

ALPHA_SRC_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "alphas"
    / "h002_sde_pde_mu_drift"
)


def _make_quotes() -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    for i, td in enumerate(TICK_DATA, start=1):
        ts = td["ts"]
        quotes.append(
            NBBOQuote(
                timestamp_ns=ts,
                exchange_timestamp_ns=ts,
                correlation_id=f"AAPL:{ts}:{i}",
                sequence=i,
                symbol="AAPL",
                bid=Decimal(td["bid"]),
                ask=Decimal(td["ask"]),
                bid_size=td["bs"],
                ask_size=td["as"],
            )
        )
    return quotes


# ── E2E Tick Data & Overrides (current on-disk alpha) ───────────────
#
# The on-disk alpha has a longer warm-up and a broader feature set than
# the inline unit-test spec above, so the replay assertions below verify
# current v5 behavior instead of the compact 8-tick scenario.
#
# Tick layout:
#   1-100: stable warm-up  (bid=150.00, ask=150.02, bs=100, as=100)
#   101:   entry trigger — slight spread widening + microprice rise
#          + bid-heavy imbalance
#   102-201: stable hold period
#   202:   exit-style pressure — large spread widening + microprice drop
#          + ask-heavy imbalance

_E2E_OVERRIDES: dict[str, object] = {
    "entry_drift_z": 0.15,
    "exit_drift_z": 0.05,
    "imbalance_delta_threshold": 0.0001,
    "min_hold_ticks": 100,
    "cooldown_ticks": 200,
    "max_hold_ticks": 1000,
    "max_spread_bp": 10.0,
}


def _make_e2e_quotes() -> list[NBBOQuote]:
    """202-tick sequence for E2E backtest with v3.0.0 on-disk alpha.

    Layout:
      Ticks 1-100:  stable warm-up  (spread 2¢, equal sizes)
      Tick 101:     entry trigger — spread widens to 8¢, microprice rises,
                    heavy bid imbalance → LONG
      Ticks 102-201: stable hold (100 ticks to satisfy min_hold_ticks)
      Tick 202:     exit trigger  — spread blows out to 40¢, microprice drops,
                    heavy ask imbalance → FLAT (exit via drift + spread)
    """
    quotes: list[NBBOQuote] = []

    def _q(i: int, bid: str, ask: str, bs: int, ats: int) -> NBBOQuote:
        ts = i * 1_000_000_000
        return NBBOQuote(
            timestamp_ns=ts,
            exchange_timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:{i}",
            sequence=i,
            symbol="AAPL",
            bid=Decimal(bid),
            ask=Decimal(ask),
            bid_size=bs,
            ask_size=ats,
        )

    for i in range(1, 101):
        quotes.append(_q(i, "150.00", "150.02", 100, 100))

    quotes.append(_q(101, "150.04", "150.12", 400, 100))

    for i in range(102, 202):
        quotes.append(_q(i, "150.00", "150.02", 100, 100))

    quotes.append(_q(202, "149.80", "150.20", 100, 300))

    return quotes


# ── Bus Recorder ─────────────────────────────────────────────────────


@dataclass
class BusRecorder:
    events: list[Event] = field(default_factory=list)
    by_type: dict[type, list[Event]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


# ── E2E backtest helper ──────────────────────────────────────────────


def _run_h002_backtest(
    tmp_path: Path,
    quotes: list[NBBOQuote] | None = None,
    overrides: dict[str, object] | None = None,
) -> tuple:
    """Build platform with the on-disk H002 alpha and run a replay."""
    alpha_dir = tmp_path / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    shutil.copytree(ALPHA_SRC_DIR, alpha_dir / "h002_sde_pde_mu_drift")

    if overrides is None:
        overrides = dict(_E2E_OVERRIDES)

    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
        risk_max_position_per_symbol=50_000,
        risk_max_gross_exposure_pct=200.0,
        risk_max_drawdown_pct=5.0,
        parameter_overrides={"h002_sde_pde_mu_drift": overrides},
    )

    event_log = InMemoryEventLog()
    if quotes is None:
        quotes = _make_e2e_quotes()
    if quotes:
        event_log.append_batch(quotes)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)

    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    return orchestrator, recorder, resolved_config


# ══════════════════════════════════════════════════════════════════════
# Tests: Spec Loading
# ══════════════════════════════════════════════════════════════════════


class TestH002SpecLoading:
    """AlphaLoader correctly parses the H002 factory dict."""

    def test_load_from_dict(self) -> None:
        alpha = AlphaLoader().load_from_dict(H002_SPEC)
        assert alpha.manifest.alpha_id == "h002_sde_pde_mu_drift"
        assert alpha.manifest.version == "4.0.0"

    def test_feature_definitions(self) -> None:
        alpha = AlphaLoader().load_from_dict(H002_SPEC)
        fdefs = alpha.feature_definitions()
        assert len(fdefs) == 1
        assert fdefs[0].feature_id == "mu_drift"
        assert fdefs[0].version == "2.0.0"
        assert fdefs[0].warm_up.min_events == 5

    def test_manifest_metadata(self) -> None:
        m = AlphaLoader().load_from_dict(H002_SPEC).manifest
        assert "mu_drift" in m.required_features
        assert m.symbols == frozenset(["AAPL"])
        assert m.risk_budget.max_position_per_symbol == 50000
        assert m.risk_budget.capital_allocation_pct == 100.0

    def test_parameters_resolved(self) -> None:
        p = AlphaLoader().load_from_dict(H002_SPEC).manifest.parameters
        assert p["mu_threshold"] == 0.0005
        assert p["max_spread_bp"] == 3.0
        assert p["mu_ema_alpha"] == 0.0

    def test_parameter_overrides(self) -> None:
        alpha = AlphaLoader().load_from_dict(
            H002_SPEC, param_overrides={"mu_threshold": 0.001}
        )
        assert alpha.manifest.parameters["mu_threshold"] == 0.001

    def test_validate_passes(self) -> None:
        assert AlphaLoader().load_from_dict(H002_SPEC).validate() == []

    def test_registry_smoke_test(self) -> None:
        alpha = AlphaLoader().load_from_dict(H002_SPEC)
        registry = AlphaRegistry()
        registry.register(alpha)
        assert len(registry) == 1


# ══════════════════════════════════════════════════════════════════════
# Tests: Feature Computation (mu_drift)
# ══════════════════════════════════════════════════════════════════════


class TestH002FeatureComputation:
    """mu_drift = EWMA(microprice_delta) / EWMA(|microprice_delta|)."""

    @pytest.fixture()
    def engine(self) -> CompositeFeatureEngine:
        alpha = AlphaLoader().load_from_dict(H002_SPEC)
        registry = AlphaRegistry()
        registry.register(alpha)
        clock = SimulatedClock(start_ns=1_000_000_000)
        return CompositeFeatureEngine(registry=registry, clock=clock)

    def test_first_tick_returns_zero(
        self, engine: CompositeFeatureEngine
    ) -> None:
        fv = engine.update(_make_quotes()[0])
        assert fv.values["mu_drift"] == pytest.approx(0.0)

    def test_stable_ticks_zero_mu(
        self, engine: CompositeFeatureEngine
    ) -> None:
        for q in _make_quotes()[:5]:
            fv = engine.update(q)
        assert fv.values["mu_drift"] == pytest.approx(0.0)

    def test_warmup_flag(self, engine: CompositeFeatureEngine) -> None:
        quotes = _make_quotes()
        for i, q in enumerate(quotes[:5]):
            fv = engine.update(q)
            if i < 4:
                assert fv.warm is False, f"tick {i + 1} should be cold"
            else:
                assert fv.warm is True, f"tick {i + 1} should be warm"

    def test_tick6_positive_mu(
        self, engine: CompositeFeatureEngine
    ) -> None:
        quotes = _make_quotes()
        for q in quotes[:5]:
            engine.update(q)
        fv = engine.update(quotes[5])
        # microprice: ~150.01 → ~150.15, delta=+0.14
        # With mu_ema_alpha=0: drift=delta, abs_drift=|delta|
        # normalized = delta / (|delta| + 1e-12) ≈ 1.0
        assert fv.values["mu_drift"] == pytest.approx(1.0, abs=0.01)
        assert fv.warm is True

    def test_tick7_negative_mu(
        self, engine: CompositeFeatureEngine
    ) -> None:
        quotes = _make_quotes()
        for q in quotes[:6]:
            engine.update(q)
        fv = engine.update(quotes[6])
        # microprice: ~150.15 → ~149.90, delta=-0.25
        # normalized = delta / (|delta| + 1e-12) ≈ -1.0
        assert fv.values["mu_drift"] == pytest.approx(-1.0, abs=0.01)

    def test_tick8_stable_zero_mu(
        self, engine: CompositeFeatureEngine
    ) -> None:
        quotes = _make_quotes()
        for q in quotes[:7]:
            engine.update(q)
        fv = engine.update(quotes[7])
        assert fv.values["mu_drift"] == pytest.approx(0.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════
# Tests: Signal Evaluation
# ══════════════════════════════════════════════════════════════════════


class TestH002SignalEvaluation:
    """Signal fires LONG on μ > threshold, SHORT on μ < -threshold."""

    def _alpha(self, **overrides):  # type: ignore[no-untyped-def]
        return AlphaLoader().load_from_dict(
            H002_SPEC, param_overrides=overrides or None
        )

    def _fv(
        self,
        mu: float,
        *,
        warm: bool = True,
        ts: int = 6_000_000_000,
    ) -> FeatureVector:
        return FeatureVector(
            timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:1",
            sequence=1,
            symbol="AAPL",
            feature_version="v1",
            values={"mu_drift": mu},
            warm=warm,
        )

    def test_long_on_positive_mu(self) -> None:
        signal = self._alpha().evaluate(self._fv(1.0))
        assert signal is not None
        assert signal.direction == SignalDirection.LONG
        assert signal.strategy_id == "h002_sde_pde_mu_drift"
        expected_strength = min(1.0 / (0.0005 * 3.0), 1.0)
        assert signal.strength == pytest.approx(expected_strength, abs=1e-4)

    def test_short_on_negative_mu(self) -> None:
        signal = self._alpha().evaluate(self._fv(-1.0))
        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_below_threshold(self) -> None:
        signal = self._alpha().evaluate(self._fv(0.0001))
        assert signal is None

    def test_no_signal_at_zero(self) -> None:
        signal = self._alpha().evaluate(self._fv(0.0))
        assert signal is None

    def test_edge_estimate_bps_populated(self) -> None:
        signal = self._alpha().evaluate(self._fv(1.0))
        assert signal is not None
        assert signal.edge_estimate_bps == pytest.approx(10000.0, abs=0.1)

    def test_threshold_override_changes_sensitivity(self) -> None:
        alpha = self._alpha(mu_threshold=0.005)
        assert alpha.evaluate(self._fv(0.001)) is None
        sig = alpha.evaluate(self._fv(0.006))
        assert sig is not None
        assert sig.direction == SignalDirection.LONG
        expected = min(0.006 / (0.005 * 3.0), 1.0)
        assert sig.strength == pytest.approx(expected, abs=1e-4)

    def test_strength_capped_at_one(self) -> None:
        signal = self._alpha().evaluate(self._fv(0.5))
        assert signal is not None
        assert signal.strength == 1.0

    def test_provenance_fields_propagated(self) -> None:
        fv = self._fv(1.0, ts=42_000_000_000)
        signal = self._alpha().evaluate(fv)
        assert signal is not None
        assert signal.correlation_id == fv.correlation_id
        assert signal.sequence == fv.sequence
        assert signal.symbol == "AAPL"


# ══════════════════════════════════════════════════════════════════════
# Tests: Integrated Pipeline (CompositeFeatureEngine + SignalEngine)
# ══════════════════════════════════════════════════════════════════════


class TestH002IntegratedPipeline:
    """Feature engine → signal engine wired through AlphaRegistry."""

    @pytest.fixture()
    def pipeline(self) -> tuple[CompositeFeatureEngine, CompositeSignalEngine]:
        alpha = AlphaLoader().load_from_dict(H002_SPEC)
        registry = AlphaRegistry()
        registry.register(alpha)
        clock = SimulatedClock(start_ns=1_000_000_000)
        fe = CompositeFeatureEngine(registry=registry, clock=clock)
        se = CompositeSignalEngine(registry)
        return fe, se

    def test_warmup_suppression(
        self,
        pipeline: tuple[CompositeFeatureEngine, CompositeSignalEngine],
    ) -> None:
        fe, se = pipeline
        quotes = _make_quotes()
        for q in quotes[:4]:
            fv = fe.update(q)
            sig = se.evaluate(fv)
            assert sig is None, "warm-up ticks must not produce signals"

    def test_signal_on_price_shock(
        self,
        pipeline: tuple[CompositeFeatureEngine, CompositeSignalEngine],
    ) -> None:
        fe, se = pipeline
        quotes = _make_quotes()
        for q in quotes[:5]:
            fv = fe.update(q)
            se.evaluate(fv)

        fv6 = fe.update(quotes[5])
        sig6 = se.evaluate(fv6)
        assert sig6 is not None
        assert sig6.direction == SignalDirection.LONG

        fv7 = fe.update(quotes[6])
        sig7 = se.evaluate(fv7)
        assert sig7 is not None
        assert sig7.direction == SignalDirection.SHORT

    def test_no_signal_on_stable_tick(
        self,
        pipeline: tuple[CompositeFeatureEngine, CompositeSignalEngine],
    ) -> None:
        fe, se = pipeline
        quotes = _make_quotes()
        for q in quotes[:7]:
            fv = fe.update(q)
            se.evaluate(fv)

        fv8 = fe.update(quotes[7])
        sig8 = se.evaluate(fv8)
        assert sig8 is None


# ══════════════════════════════════════════════════════════════════════
# Tests: End-to-End Backtest
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="class")
def h002_scenario(tmp_path_factory: pytest.TempPathFactory):
    """Run the 202-tick on-disk H002 replay once; share across class tests."""
    tmp = tmp_path_factory.mktemp("h002_e2e")
    orchestrator, recorder, config = _run_h002_backtest(tmp)
    return orchestrator, recorder, config


class TestH002BacktestIngestion:
    """Layer 1 — 202 NBBOQuote events replayed."""

    def test_quote_count(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(NBBOQuote)) == 202

    def test_timestamps_monotonic(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        quotes = recorder.of_type(NBBOQuote)
        for i in range(len(quotes) - 1):
            assert quotes[i].timestamp_ns < quotes[i + 1].timestamp_ns


class TestH002BacktestFeatures:
    """Layer 2 — replay emits current on-disk feature vectors."""

    def test_feature_vector_count(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(FeatureVector)) == 202

    def test_warmup_gate(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        fvs = recorder.of_type(FeatureVector)
        for fv in fvs[:99]:
            assert fv.warm is False
        for fv in fvs[99:]:
            assert fv.warm is True

    def test_first_warm_vector_contains_expected_features(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        fv = recorder.of_type(FeatureVector)[99]
        assert set(fv.values) == {
            "current_spread_bp",
            "drift_bps",
            "imbalance_delta",
            "imbalance_pressure",
            "mu_ema",
            "spread_z",
        }

    def test_entry_setup_features(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        fv = recorder.of_type(FeatureVector)[100]
        assert fv.values["mu_ema"] > 0.99
        assert fv.values["imbalance_pressure"] == pytest.approx(0.6)
        assert fv.values["spread_z"] > 9.0

    def test_exit_setup_features(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        fv = recorder.of_type(FeatureVector)[-1]
        assert fv.values["mu_ema"] < -0.4
        assert fv.values["imbalance_pressure"] == pytest.approx(-0.5)
        assert fv.values["spread_z"] > 9.0


class TestH002BacktestSignals:
    """Layer 3 — current replay emits no signals under default gates."""

    def test_signal_count(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(Signal)) == 0

    def test_no_signal_at_entry_setup_tick(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        signal_cids = {sig.correlation_id for sig in recorder.of_type(Signal)}
        assert "AAPL:101000000000:101" not in signal_cids

    def test_no_signal_at_exit_setup_tick(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        signal_cids = {sig.correlation_id for sig in recorder.of_type(Signal)}
        assert "AAPL:202000000000:202" not in signal_cids


class TestH002BacktestExecution:
    """Layer 5 — no orders (warmup not reached)."""

    def test_no_orders(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(OrderRequest)) == 0

    def test_no_fills(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(OrderAck)) == 0


class TestH002BacktestPortfolio:
    """Layer 6 — no position updates (no fills)."""

    def test_no_position_updates(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        assert len(recorder.of_type(PositionUpdate)) == 0


class TestH002BacktestProvenance:
    """Invariant 13 — feature vectors trace to quotes."""

    def test_feature_traces_to_quote(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        quote_cids = {q.correlation_id for q in recorder.of_type(NBBOQuote)}
        for fv in recorder.of_type(FeatureVector):
            assert fv.correlation_id in quote_cids

    def test_order_traces_to_signal(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        _, recorder, _ = h002_scenario
        signal_cids = {s.correlation_id for s in recorder.of_type(Signal)}
        for order in recorder.of_type(OrderRequest):
            assert order.correlation_id in signal_cids


class TestH002BacktestStateMachines:
    """Macro lifecycle completes cleanly."""

    def test_macro_state_ready(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        orchestrator, _, _ = h002_scenario
        assert orchestrator.macro_state == MacroState.READY

    def test_kill_switch_inactive(self, h002_scenario) -> None:  # type: ignore[no-untyped-def]
        orchestrator, _, _ = h002_scenario
        assert orchestrator._kill_switch.is_active is False  # type: ignore[attr-defined]


# ══════════════════════════════════════════════════════════════════════
# Tests: Deterministic Replay (Invariant 5)
# ══════════════════════════════════════════════════════════════════════


class TestH002DeterministicReplay:
    """Two independent runs produce bit-identical outputs."""

    def test_two_runs_identical(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        runs = []
        for i in range(2):
            tmp = tmp_path_factory.mktemp(f"h002_replay_{i}")
            orch, rec, _ = _run_h002_backtest(tmp)
            runs.append((orch, rec))

        sigs_a = runs[0][1].of_type(Signal)
        sigs_b = runs[1][1].of_type(Signal)
        assert len(sigs_a) == len(sigs_b) == 0

        fvs_a = runs[0][1].of_type(FeatureVector)
        fvs_b = runs[1][1].of_type(FeatureVector)
        assert len(fvs_a) == len(fvs_b) == 202
        for fa, fb in zip(fvs_a, fvs_b):
            assert fa.values == fb.values
            assert fa.warm == fb.warm
            assert fa.correlation_id == fb.correlation_id

        pos_a = runs[0][0]._positions.get("AAPL")  # type: ignore[attr-defined]
        pos_b = runs[1][0]._positions.get("AAPL")  # type: ignore[attr-defined]
        assert pos_a.quantity == pos_b.quantity
        assert pos_a.realized_pnl == pos_b.realized_pnl
