"""Unit tests for event schemas."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import (
    Alert,
    AlertSeverity,
    Event,
    KillSwitchActivation,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
    StateTransition,
    Trade,
)


class TestEvent:
    """Tests for base Event."""

    def test_required_fields(self) -> None:
        ev = Event(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
        )
        assert ev.timestamp_ns == 1000
        assert ev.correlation_id == "c1"
        assert ev.sequence == 1

    def test_event_is_frozen(self) -> None:
        ev = Event(timestamp_ns=0, correlation_id="", sequence=0)
        with pytest.raises(AttributeError):
            ev.sequence = 1  # type: ignore[misc]


class TestNBBOQuote:
    """Tests for NBBOQuote."""

    def test_creates_with_required_fields(self) -> None:
        q = NBBOQuote(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("150.00"),
            ask=Decimal("150.02"),
            bid_size=100,
            ask_size=50,
            exchange_timestamp_ns=1000,
        )
        assert q.symbol == "AAPL"
        assert q.bid == Decimal("150.00")
        assert q.ask == Decimal("150.02")
        assert q.bid_size == 100
        assert q.ask_size == 50

    def test_optional_fields_default(self) -> None:
        q = NBBOQuote(
            timestamp_ns=0,
            correlation_id="",
            sequence=0,
            symbol="X",
            bid=Decimal("1"),
            ask=Decimal("1"),
            bid_size=1,
            ask_size=1,
            exchange_timestamp_ns=0,
        )
        assert q.bid_exchange == 0
        assert q.ask_exchange == 0
        assert q.conditions == ()
        assert q.indicators == ()


class TestTrade:
    """Tests for Trade."""

    def test_creates_with_required_fields(self) -> None:
        t = Trade(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            symbol="AAPL",
            price=Decimal("150.01"),
            size=100,
            exchange_timestamp_ns=1000,
        )
        assert t.symbol == "AAPL"
        assert t.price == Decimal("150.01")
        assert t.size == 100


class TestSignal:
    """Tests for Signal."""

    def test_creates_with_direction(self) -> None:
        s = Signal(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            symbol="AAPL",
            strategy_id="test",
            direction=SignalDirection.LONG,
            strength=0.8,
            edge_estimate_bps=10.0,
        )
        assert s.direction == SignalDirection.LONG
        assert s.strength == 0.8
        assert s.edge_estimate_bps == 10.0


class TestSignalDirection:
    """Tests for SignalDirection enum."""

    def test_has_expected_members(self) -> None:
        assert SignalDirection.LONG
        assert SignalDirection.SHORT
        assert SignalDirection.FLAT


class TestOrderRequest:
    """Tests for OrderRequest."""

    def test_creates_order(self) -> None:
        req = OrderRequest(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            order_id="o1",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        assert req.side == Side.BUY
        assert req.order_type == OrderType.MARKET
        assert req.quantity == 100
        assert req.limit_price is None


class TestOrderAck:
    """Tests for OrderAck."""

    def test_creates_ack(self) -> None:
        ack = OrderAck(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            order_id="o1",
            symbol="AAPL",
            status=OrderAckStatus.FILLED,
            filled_quantity=100,
            fill_price=Decimal("150.00"),
        )
        assert ack.status == OrderAckStatus.FILLED
        assert ack.filled_quantity == 100


class TestRiskVerdict:
    """Tests for RiskVerdict."""

    def test_creates_verdict(self) -> None:
        v = RiskVerdict(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            symbol="AAPL",
            action=RiskAction.ALLOW,
            reason="ok",
            scaling_factor=1.0,
        )
        assert v.action == RiskAction.ALLOW
        assert v.scaling_factor == 1.0


class TestStateTransition:
    """Tests for StateTransition."""

    def test_creates_transition(self) -> None:
        st = StateTransition(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            machine_name="macro",
            from_state="READY",
            to_state="BACKTEST_MODE",
            trigger="CMD_BACKTEST",
        )
        assert st.machine_name == "macro"
        assert st.from_state == "READY"
        assert st.to_state == "BACKTEST_MODE"


class TestAlert:
    """Tests for Alert."""

    def test_creates_alert(self) -> None:
        a = Alert(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="test",
            message="msg",
        )
        assert a.severity == AlertSeverity.WARNING
        assert a.alert_name == "test"


class TestKillSwitchActivation:
    """Tests for KillSwitchActivation."""

    def test_creates_activation(self) -> None:
        k = KillSwitchActivation(
            timestamp_ns=1000,
            correlation_id="c1",
            sequence=1,
            reason="manual",
            activated_by="operator",
        )
        assert k.reason == "manual"
        assert k.activated_by == "operator"
