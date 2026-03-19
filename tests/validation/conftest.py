"""Shared scenario fixtures for backtest validation suite."""

from __future__ import annotations

import shutil
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

ALPHA_SRC = Path(__file__).resolve().parent.parent.parent / "alphas" / "mean_reversion.alpha.yaml"

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
) -> tuple:
    alpha_dir = tmp_path / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    shutil.copy2(ALPHA_SRC, alpha_dir / "mean_reversion.alpha.yaml")

    if parameter_overrides is None:
        parameter_overrides = {"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}}

    config = PlatformConfig(
        symbols=symbols,
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=account_equity,
        regime_engine=regime_engine,
        parameter_overrides=parameter_overrides,
        backtest_fill_latency_ns=backtest_fill_latency_ns,
        risk_max_drawdown_pct=risk_max_drawdown_pct,
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
alpha_id: trade_aware
version: "1.0"
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
        else:
            ticks = TICK_DATA

        return _run_scenario(tmp_path, quotes=_make_quotes("AAPL", ticks))

    return _create


@pytest.fixture
def alpha_spec_dir(tmp_path: Path) -> Path:
    """Temporary directory with mean_reversion.alpha.yaml."""
    alpha_dir = tmp_path / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    shutil.copy2(ALPHA_SRC, alpha_dir / "mean_reversion.alpha.yaml")
    return alpha_dir
