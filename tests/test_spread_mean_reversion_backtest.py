"""Backtest integration test for the v2.3 migrated spread_mean_reversion alpha.

Verifies the full pipeline using the nested-directory alpha with
computation_module references: discovery → load → register → boot →
feature computation → signal evaluation → risk check → order → fill.

Uses a synthetic NBBO sequence that drifts mid-price away from EWMA
to trigger the z-score threshold, then verifies a fill occurs.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.storage.memory_event_log import InMemoryEventLog

ALPHA_DIR = Path(__file__).resolve().parent.parent / "alphas"


def _make_quote(
    bid: float,
    ask: float,
    sequence: int,
    ts: int,
    symbol: str = "AAPL",
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"BT:{symbol}:{sequence}",
        sequence=sequence,
        symbol=symbol,
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=500,
        ask_size=500,
        exchange_timestamp_ns=ts - 100,
    )


def _build_warm_up_then_signal_quotes(
    n_warmup: int = 60,
    base_price: float = 150.0,
    spike_delta: float = 3.0,
) -> list[NBBOQuote]:
    """Build a quote sequence: stable warm-up period then a price spike.

    The first n_warmup quotes hover around base_price with tight spread
    so the EWMA converges.  Then several quotes spike upward to push
    the z-score past the entry threshold (default 2.0), triggering a
    SHORT signal from the mean reversion alpha.
    """
    quotes: list[NBBOQuote] = []
    spread = 0.02

    for i in range(n_warmup):
        noise = (i % 3 - 1) * 0.005
        mid = base_price + noise
        quotes.append(_make_quote(
            bid=mid - spread / 2,
            ask=mid + spread / 2,
            sequence=i + 1,
            ts=(i + 1) * 1_000_000_000,
        ))

    for j in range(10):
        seq = n_warmup + j + 1
        mid = base_price + spike_delta + j * 0.5
        quotes.append(_make_quote(
            bid=mid - spread / 2,
            ask=mid + spread / 2,
            sequence=seq,
            ts=seq * 1_000_000_000,
        ))

    return quotes


class TestSpreadMeanReversionBacktest:
    """Full backtest with the v2.3 nested spread_mean_reversion alpha."""

    def test_alpha_loads_from_nested_directory(self) -> None:
        """The nested alpha spec is discovered and loads without error."""
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=ALPHA_DIR / "spread_mean_reversion",
            account_equity=1_000_000.0,
            regime_engine="hmm_3state_fractional",
        )
        event_log = InMemoryEventLog()
        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)

        assert orchestrator.macro_state == MacroState.READY

    def test_warm_up_then_signal_produces_fill(self) -> None:
        """After warm-up, a price spike triggers SHORT signal → order → fill."""
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=ALPHA_DIR / "spread_mean_reversion",
            account_equity=1_000_000.0,
            regime_engine="hmm_3state_fractional",
        )

        event_log = InMemoryEventLog()
        quotes = _build_warm_up_then_signal_quotes(
            n_warmup=60, base_price=150.0, spike_delta=3.0,
        )
        event_log.append_batch(quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY

        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity != 0, (
            "Expected a non-zero position after price spike — "
            "the mean reversion alpha should have fired a SHORT signal"
        )
        assert pos.quantity < 0, (
            f"Expected SHORT position (negative qty), got {pos.quantity}. "
            f"Price spike above EWMA should trigger SHORT signal."
        )

    def test_no_signal_during_warm_up(self) -> None:
        """No orders fire during the warm-up phase (features not warm)."""
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=ALPHA_DIR / "spread_mean_reversion",
            account_equity=1_000_000.0,
            regime_engine="hmm_3state_fractional",
        )

        event_log = InMemoryEventLog()
        quotes = _build_warm_up_then_signal_quotes(n_warmup=60)
        warm_up_only = quotes[:30]
        event_log.append_batch(warm_up_only)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY
        pos = orchestrator._positions.get("AAPL")
        assert pos.quantity == 0, (
            f"Expected zero position during warm-up, got {pos.quantity}"
        )

    def test_trade_journal_records_fill(self) -> None:
        """After a signal fires and fills, the trade journal has a record."""
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=ALPHA_DIR / "spread_mean_reversion",
            account_equity=1_000_000.0,
            regime_engine="hmm_3state_fractional",
        )

        event_log = InMemoryEventLog()
        quotes = _build_warm_up_then_signal_quotes(
            n_warmup=60, base_price=150.0, spike_delta=3.0,
        )
        event_log.append_batch(quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        pos = orchestrator._positions.get("AAPL")
        if pos.quantity != 0:
            tj = orchestrator._trade_journal
            assert tj is not None
            trades = list(tj.query(symbol="AAPL"))
            assert len(trades) > 0, "Trade journal should have at least one trade"
            assert trades[0].symbol == "AAPL"
            assert trades[0].filled_quantity > 0

    def test_completes_cleanly_with_top_level_alphas_dir(self) -> None:
        """Discovery via top-level alphas/ dir finds the nested alpha."""
        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=ALPHA_DIR,
            account_equity=1_000_000.0,
            regime_engine="hmm_3state_fractional",
        )

        event_log = InMemoryEventLog()
        quotes = _build_warm_up_then_signal_quotes(n_warmup=60)
        event_log.append_batch(quotes)

        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.READY
