"""Shared scenario fixtures for backtest validation suite."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    PositionUpdate,
    RiskVerdict,
    Signal,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

PIPELINE_TEST_ALPHA_ID = "pipeline_test_smr"

PIPELINE_TEST_ALPHA_SPEC = """\
schema_version: "1.1"
layer: LEGACY_SIGNAL
alpha_id: pipeline_test_smr
version: "1.0.0"
description: "Minimal EWMA z-score alpha for pipeline integration testing"
hypothesis: "Mid-price deviation from EWMA generates mean reversion signals"
falsification_criteria:
  - "Test fixture only"
symbols:
  - AAPL
  - MSFT
parameters:
  ewma_span:
    type: float
    default: 5.0
  zscore_entry:
    type: float
    default: 1.0
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 10.0
  max_drawdown_pct: 2.0
  capital_allocation_pct: 20.0
features:
  - feature_id: mid_price
    version: "1.0"
    description: Mid price from NBBO
    depends_on: []
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
  - feature_id: ewma_mid
    version: "1.0"
    description: EWMA of mid price
    depends_on: [mid_price]
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {"ema": None}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          span = params.get("ewma_span", 5.0)
          a = 2.0 / (span + 1.0)
          if state["ema"] is None:
              state["ema"] = mid
          else:
              state["ema"] = a * mid + (1 - a) * state["ema"]
          return state["ema"]
  - feature_id: spread
    version: "1.0"
    description: Bid-ask spread
    depends_on: []
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float(quote.ask - quote.bid)
  - feature_id: mid_zscore
    version: "1.0"
    description: Z-score of mid relative to EWMA
    depends_on: [mid_price, ewma_mid]
    warm_up:
      min_events: 5
    computation: |
      def initial_state():
          return {"ema": None, "var": 0.0}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          span = params.get("ewma_span", 5.0)
          a = 2.0 / (span + 1.0)
          if state["ema"] is None:
              state["ema"] = mid
              return 0.0
          dev = mid - state["ema"]
          state["ema"] = a * mid + (1 - a) * state["ema"]
          state["var"] = a * dev * dev + (1 - a) * state["var"]
          if state["var"] < 1e-20:
              return 0.0
          return (mid - state["ema"]) / (state["var"] ** 0.5)
signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      zscore = features.values.get("mid_zscore", 0.0)
      spread = features.values.get("spread", 0.0)
      threshold = params.get("zscore_entry", 1.0)
      if spread > 0.5:
          return None
      if abs(zscore) < threshold:
          return None
      direction = SHORT if zscore > 0 else LONG
      strength = min(abs(zscore) / 5.0, 1.0)
      return Signal(
          timestamp_ns=features.timestamp_ns,
          correlation_id=features.correlation_id,
          sequence=features.sequence,
          symbol=features.symbol,
          strategy_id=alpha_id,
          direction=direction,
          strength=strength,
          edge_estimate_bps=2.5,
      )
"""


def _write_test_alpha(alpha_dir: Path) -> None:
    """Write the pipeline test alpha spec to the given directory."""
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / f"{PIPELINE_TEST_ALPHA_ID}.alpha.yaml").write_text(
        PIPELINE_TEST_ALPHA_SPEC
    )

TICK_DATA: list[dict] = [
    {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
    {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
]


@dataclass
class BusRecorder:
    events: list[Event] = field(default_factory=list)
    by_type: dict[type, list[Event]] = field(default_factory=lambda: defaultdict(list))

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


def _make_quotes(
    symbol: str = "AAPL",
    tick_data: list[dict] | None = None,
) -> list[NBBOQuote]:
    data = tick_data or TICK_DATA
    quotes = []
    for i, td in enumerate(data, start=1):
        ts = td["ts"]
        quotes.append(NBBOQuote(
            timestamp_ns=ts,
            correlation_id=f"{symbol}:{ts}:{i}",
            sequence=i,
            symbol=symbol,
            bid=Decimal(td["bid"]),
            ask=Decimal(td["ask"]),
            bid_size=td.get("bid_size", 100),
            ask_size=td.get("ask_size", 100),
            exchange_timestamp_ns=ts,
        ))
    return quotes


def _run_scenario(
    tmp_path: Path,
    quotes: list[NBBOQuote | Trade] | None = None,
    symbols: frozenset[str] = frozenset({"AAPL"}),
    parameter_overrides: dict | None = None,
    regime_engine: str | None = None,
    account_equity: float = 100_000.0,
    backtest_fill_latency_ns: int = 0,
    risk_max_drawdown_pct: float = 5.0,
    risk_max_position_per_symbol: int = 1000,
    risk_max_gross_exposure_pct: float = 20.0,
) -> tuple:
    alpha_dir = tmp_path / "alphas"
    _write_test_alpha(alpha_dir)

    if parameter_overrides is None:
        parameter_overrides = {PIPELINE_TEST_ALPHA_ID: {"ewma_span": 5, "zscore_entry": 1.0}}

    config = PlatformConfig(
        symbols=symbols,
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=account_equity,
        regime_engine=regime_engine,
        parameter_overrides=parameter_overrides,
        backtest_fill_latency_ns=backtest_fill_latency_ns,
        risk_max_drawdown_pct=risk_max_drawdown_pct,
        risk_max_position_per_symbol=risk_max_position_per_symbol,
        risk_max_gross_exposure_pct=risk_max_gross_exposure_pct,
    )

    event_log = InMemoryEventLog()
    if quotes is None:
        quotes = _make_quotes()
    if quotes:
        event_log.append_batch(quotes)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)

    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)

    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    return orchestrator, recorder, resolved_config, event_log


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="class")
def single_symbol_scenario(tmp_path_factory: pytest.TempPathFactory):
    """8-tick AAPL scenario reusing the standard pattern."""
    tmp = tmp_path_factory.mktemp("single_symbol")
    return _run_scenario(tmp)


@pytest.fixture(scope="class")
def multi_symbol_scenario(tmp_path_factory: pytest.TempPathFactory):
    """2 symbols (AAPL + MSFT), 12 ticks interleaved by timestamp."""
    tmp = tmp_path_factory.mktemp("multi_symbol")

    aapl_ticks = [
        {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 7_000_000_000},
        {"bid": "160.00", "ask": "160.01", "ts": 9_000_000_000},
        {"bid": "140.00", "ask": "140.01", "ts": 11_000_000_000},
    ]
    msft_ticks = [
        {"bid": "350.00", "ask": "350.01", "ts": 2_000_000_000},
        {"bid": "350.00", "ask": "350.01", "ts": 4_000_000_000},
        {"bid": "350.00", "ask": "350.01", "ts": 6_000_000_000},
        {"bid": "350.00", "ask": "350.01", "ts": 8_000_000_000},
        {"bid": "360.00", "ask": "360.01", "ts": 10_000_000_000},
        {"bid": "340.00", "ask": "340.01", "ts": 12_000_000_000},
    ]

    aapl_quotes = _make_quotes("AAPL", aapl_ticks)
    msft_quotes = _make_quotes("MSFT", msft_ticks)

    all_quotes = sorted(
        aapl_quotes + msft_quotes, key=lambda q: q.exchange_timestamp_ns
    )
    for i, q in enumerate(all_quotes, start=1):
        all_quotes[i - 1] = NBBOQuote(
            timestamp_ns=q.timestamp_ns,
            correlation_id=q.correlation_id,
            sequence=i,
            symbol=q.symbol,
            bid=q.bid,
            ask=q.ask,
            bid_size=q.bid_size,
            ask_size=q.ask_size,
            exchange_timestamp_ns=q.exchange_timestamp_ns,
        )

    return _run_scenario(
        tmp,
        quotes=all_quotes,
        symbols=frozenset({"AAPL", "MSFT"}),
    )


TRADE_ALPHA_SPEC = """\
schema_version: "1.1"
layer: LEGACY_SIGNAL
alpha_id: trade_aware
version: "1.0.0"
author: validation_test
description: Feature that updates on both quotes and trades
hypothesis: Trade events affect feature state
falsification_criteria:
  - Feature state unchanged after trade events
symbols:
  - AAPL
parameters: {}
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 10.0
  max_drawdown_pct: 2.0
  capital_allocation_pct: 20.0
features:
  - feature_id: mid_price
    version: "1.0"
    description: Mid price from NBBO
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {"trade_count": 0}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
      def update_trade(trade, state, params):
          state["trade_count"] = state.get("trade_count", 0) + 1
          return float(trade.price)
  - feature_id: spread
    version: "1.0"
    description: Spread
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float(quote.ask - quote.bid)
signal: |
  def evaluate(features, params):
      return None
"""


@pytest.fixture(scope="class")
def trade_mixed_scenario(tmp_path_factory: pytest.TempPathFactory):
    """Quotes interleaved with Trade events."""
    tmp = tmp_path_factory.mktemp("trade_mixed")
    alpha_dir = tmp / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    (alpha_dir / "trade_aware.alpha.yaml").write_text(TRADE_ALPHA_SPEC)

    quotes_and_trades: list[NBBOQuote | Trade] = [
        NBBOQuote(
            timestamp_ns=1_000_000_000,
            correlation_id="AAPL:1000000000:1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("150.00"),
            ask=Decimal("150.02"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1_000_000_000,
        ),
        Trade(
            timestamp_ns=1_500_000_000,
            correlation_id="AAPL:1500000000:2",
            sequence=2,
            symbol="AAPL",
            price=Decimal("150.01"),
            size=500,
            exchange_timestamp_ns=1_500_000_000,
        ),
        NBBOQuote(
            timestamp_ns=2_000_000_000,
            correlation_id="AAPL:2000000000:3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("150.01"),
            ask=Decimal("150.03"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=2_000_000_000,
        ),
        Trade(
            timestamp_ns=2_500_000_000,
            correlation_id="AAPL:2500000000:4",
            sequence=4,
            symbol="AAPL",
            price=Decimal("150.02"),
            size=300,
            exchange_timestamp_ns=2_500_000_000,
        ),
        NBBOQuote(
            timestamp_ns=3_000_000_000,
            correlation_id="AAPL:3000000000:5",
            sequence=5,
            symbol="AAPL",
            bid=Decimal("150.02"),
            ask=Decimal("150.04"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=3_000_000_000,
        ),
    ]

    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
    )

    event_log = InMemoryEventLog()
    event_log.append_batch(quotes_and_trades)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)
    orchestrator.boot(resolved_config)
    orchestrator.run_backtest()

    return orchestrator, recorder, resolved_config, event_log


@pytest.fixture(scope="class")
def regime_scenario(tmp_path_factory: pytest.TempPathFactory):
    """8 ticks with regime_engine='hmm_3state_fractional' enabled."""
    tmp = tmp_path_factory.mktemp("regime")
    return _run_scenario(tmp, regime_engine="hmm_3state_fractional")


@pytest.fixture(scope="class")
def latency_injection_scenario(tmp_path_factory: pytest.TempPathFactory):
    """4-tick scenario with backtest_fill_latency_ns=5000."""
    tmp = tmp_path_factory.mktemp("latency")
    ticks = [
        {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
        {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
        {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
        {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
    ]
    return _run_scenario(
        tmp,
        quotes=_make_quotes("AAPL", ticks),
        backtest_fill_latency_ns=5000,
    )


@pytest.fixture(scope="class")
def drawdown_scenario(tmp_path_factory: pytest.TempPathFactory):
    """Price series generating losses exceeding max_drawdown_pct."""
    tmp = tmp_path_factory.mktemp("drawdown")

    ticks = [
        {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
        # Spike triggers SHORT signal at tick 6 → short position entered
        {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
        # Price rises further → large loss on short position
        {"bid": "200.00", "ask": "200.01", "ts": 7_000_000_000},
        # Price rises even more → drawdown breach
        {"bid": "300.00", "ask": "300.01", "ts": 8_000_000_000},
    ]

    return _run_scenario(
        tmp,
        quotes=_make_quotes("AAPL", ticks),
        account_equity=10_000.0,
        risk_max_drawdown_pct=1.0,
    )


@pytest.fixture(scope="class")
def all_suppressed_scenario(tmp_path_factory: pytest.TempPathFactory):
    """4 ticks where the signal engine always returns None (flat range)."""
    tmp = tmp_path_factory.mktemp("suppressed")
    ticks = [
        {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
        {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
    ]
    return _run_scenario(tmp, quotes=_make_quotes("AAPL", ticks))


@pytest.fixture
def fault_scenario_factory(tmp_path: Path):
    """Factory producing event logs with injected faults."""

    def _create(fault_type: str) -> tuple:
        if fault_type == "zero_size":
            ticks = [
                {"bid": "150.00", "ask": "150.01", "ts": 1_000, "bid_size": 0, "ask_size": 0},
                {"bid": "150.00", "ask": "150.01", "ts": 2_000, "bid_size": 100, "ask_size": 100},
            ]
        elif fault_type == "extreme_spike":
            ticks = [
                {"bid": "150.00", "ask": "150.01", "ts": 1_000},
                {"bid": "15000.00", "ask": "15000.01", "ts": 2_000},
            ]
        elif fault_type == "duplicate_ts":
            ticks = [
                {"bid": "150.00", "ask": "150.01", "ts": 1_000},
                {"bid": "150.02", "ask": "150.03", "ts": 1_000},
            ]
        elif fault_type == "negative_spread":
            ticks = [
                {"bid": "150.05", "ask": "150.00", "ts": 1_000},
                {"bid": "150.00", "ask": "150.01", "ts": 2_000},
            ]
        elif fault_type == "empty_event_log":
            ticks = []
        else:
            ticks = TICK_DATA

        return _run_scenario(tmp_path, quotes=_make_quotes("AAPL", ticks))

    return _create
