"""Fill-report latency on the two backtest routers.

``None`` is today's immediate poll. A non-negative delay hides FILLED and
PARTIALLY_FILLED until the clock is at or past born plus the delay.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from feelies.bootstrap import _create_backend
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.storage.memory_event_log import InMemoryEventLog

_BORN_NS = 1_000_000_000
_LATENCY_MS = 20
_LATENCY_NS = _LATENCY_MS * 1_000_000
_ROUTERS = (BacktestOrderRouter, PassiveLimitOrderRouter)
_OMIT = object()


def _quote(symbol: str, bid: str, ask: str, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{symbol}-{ts}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _buy(symbol: str, order_id: str) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=_BORN_NS,
        correlation_id=f"o-{order_id}",
        sequence=2,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=50,
    )


def _router(
    cls: type[BacktestOrderRouter] | type[PassiveLimitOrderRouter],
    latency_ms: int | None | object,
) -> tuple[SimulatedClock, BacktestOrderRouter | PassiveLimitOrderRouter]:
    clock = SimulatedClock(start_ns=_BORN_NS)
    kwargs: dict[str, object] = {"latency_ns": 0, "cost_model": ZeroCostModel()}
    if latency_ms is not _OMIT:
        kwargs["fill_report_latency_ms"] = latency_ms
    router = cls(clock, **kwargs)  # type: ignore[arg-type]
    return clock, router


def _arm(router: BacktestOrderRouter | PassiveLimitOrderRouter, symbol: str = "AAPL") -> None:
    router.on_quote(_quote(symbol, "100.00", "100.10", ts=_BORN_NS - 1))
    router.submit(_buy(symbol, f"{symbol}-buy"))


def _filled(acks: list[OrderAck]) -> list[OrderAck]:
    return [ack for ack in acks if ack.status == OrderAckStatus.FILLED]


def test_none_matches_immediate_poll() -> None:
    """L=None leaves the pending list unchanged, including a zero receive time."""
    for cls in _ROUTERS:
        _, plain = _router(cls, _OMIT)
        _arm(plain, "AAPL")
        assert plain.release_due_fill_reports() == []
        plain_acks = plain.poll_acks()

        _, explicit = _router(cls, None)
        _arm(explicit, "AAPL")
        assert explicit.release_due_fill_reports() == []
        explicit_acks = explicit.poll_acks()

        def _sig(ack: OrderAck) -> tuple[object, ...]:
            return (
                ack.order_id,
                ack.status,
                ack.timestamp_ns,
                ack.report_received_ns,
                ack.fill_price,
            )

        assert [_sig(ack) for ack in plain_acks] == [_sig(ack) for ack in explicit_acks]
        assert _filled(plain_acks)
        assert all(ack.report_received_ns == 0 for ack in plain_acks)


def test_fill_invisible_until_born_plus_l() -> None:
    """A fill stays hidden through the nanosecond before it is due."""
    for cls in _ROUTERS:
        clock, router = _router(cls, _LATENCY_MS)
        _arm(router)
        early = router.poll_acks()
        assert any(ack.status == OrderAckStatus.ACKNOWLEDGED for ack in early)
        assert not _filled(early)
        clock.set_time(_BORN_NS + _LATENCY_NS - 1)
        assert not _filled(router.poll_acks())


def test_equal_clock_releases() -> None:
    """now == born + L releases. A strict greater-than would keep the fill."""
    for cls in _ROUTERS:
        clock, router = _router(cls, _LATENCY_MS)
        _arm(router)
        clock.set_time(_BORN_NS + _LATENCY_NS)
        filled = _filled(router.poll_acks())
        assert len(filled) == 1
        assert filled[0].timestamp_ns == _BORN_NS + _LATENCY_NS
        assert filled[0].report_received_ns == _BORN_NS + _LATENCY_NS


def test_receive_time_is_born_plus_l() -> None:
    """A late poll stamps the release clock and keeps receive time at born + L."""
    late_ns = _BORN_NS + _LATENCY_NS + 10_000_000
    for cls in _ROUTERS:
        clock, router = _router(cls, _LATENCY_MS)
        _arm(router)
        clock.set_time(late_ns)
        filled = _filled(router.poll_acks())
        assert len(filled) == 1
        assert filled[0].report_received_ns == _BORN_NS + _LATENCY_NS
        assert filled[0].timestamp_ns == late_ns
        assert filled[0].timestamp_ns != filled[0].report_received_ns


def test_zero_field_falls_back_to_timestamp() -> None:
    """0 means unset, so the reader uses timestamp_ns. A set field wins."""
    from feelies.kernel.orchestrator import _fill_report_received_ns

    unset = OrderAck(
        timestamp_ns=10,
        correlation_id="unset",
        sequence=1,
        order_id="unset",
        symbol="AAPL",
        status=OrderAckStatus.FILLED,
        report_received_ns=0,
    )
    stamped = OrderAck(
        timestamp_ns=10,
        correlation_id="stamped",
        sequence=2,
        order_id="stamped",
        symbol="AAPL",
        status=OrderAckStatus.FILLED,
        report_received_ns=25,
    )
    assert _fill_report_received_ns(unset) == 10
    assert _fill_report_received_ns(stamped) == 25


def test_non_fill_acks_are_immediate() -> None:
    """A reject is visible on the submit poll. The fill on the other symbol is not."""
    for cls in _ROUTERS:
        _, router = _router(cls, _LATENCY_MS)
        _arm(router, "AAPL")
        router.submit(_buy("MSFT", "MSFT-buy"))
        acks = router.poll_acks()
        assert any(ack.symbol == "MSFT" and ack.status == OrderAckStatus.REJECTED for ack in acks)
        assert not _filled(acks)


def test_paper_mode_does_not_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """PAPER does not construct the backtest routers and does not forward L."""
    monkeypatch.setenv("MASSIVE_API_KEY", "not-a-real-key")
    backtest_calls: list[object] = []
    passive_calls: list[object] = []

    def _backtest(*args: object, **kwargs: object) -> object:
        backtest_calls.append(kwargs)
        raise AssertionError("paper mode constructed a backtest backend")

    def _passive(*args: object, **kwargs: object) -> object:
        passive_calls.append(kwargs)
        raise AssertionError("paper mode constructed a passive backend")

    monkeypatch.setattr("feelies.bootstrap.build_backtest_backend", _backtest)
    monkeypatch.setattr("feelies.bootstrap.build_passive_limit_backend", _passive)
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[Path("alpha.yaml")],
        mode=OperatingMode.PAPER,
        fill_report_latency_ms=50,
    )
    clock = SimulatedClock()
    with patch("feelies.execution.paper_backend.build_paper_backend") as paper:
        paper.return_value = (object(), object(), object())
        _create_backend(
            config,
            InMemoryEventLog(),
            clock,
            normalizer=MassiveNormalizer(clock=clock),
            cost_model=DefaultCostModel(),
        )
    assert backtest_calls == []
    assert passive_calls == []
    assert paper.call_count == 1
    assert "fill_report_latency_ms" not in paper.call_args.kwargs
    assert not hasattr(paper.call_args.kwargs["order_router"], "release_due_fill_reports")
