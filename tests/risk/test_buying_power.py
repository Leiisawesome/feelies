"""Unit tests for Reg-T buying-power helpers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.risk.buying_power import (
    BuyingPowerConfig,
    BuyingPowerPhase,
    buying_power_limit,
)


def test_margin_25k_intraday_four_x() -> None:
    cfg = BuyingPowerConfig(account_type="margin_25k")
    assert buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.INTRADAY,
        cfg,
    ) == Decimal("200000")


def test_margin_25k_overnight_two_x() -> None:
    cfg = BuyingPowerConfig(account_type="margin_25k")
    assert buying_power_limit(
        Decimal("50000"),
        BuyingPowerPhase.OVERNIGHT,
        cfg,
    ) == Decimal("100000")


def test_unimplemented_account_type_raises() -> None:
    with pytest.raises(NotImplementedError, match="margin_25k"):
        BuyingPowerConfig(account_type="cash")


def test_zero_equity_returns_zero_limit() -> None:
    """Zero equity blocks entry buying power in every phase."""
    cfg = BuyingPowerConfig(account_type="margin_25k")
    assert buying_power_limit(Decimal("0"), BuyingPowerPhase.INTRADAY, cfg) == Decimal("0")
    assert buying_power_limit(Decimal("0"), BuyingPowerPhase.OVERNIGHT, cfg) == Decimal("0")


def test_negative_equity_returns_zero_limit() -> None:
    cfg = BuyingPowerConfig(account_type="margin_25k")
    assert buying_power_limit(Decimal("-1000"), BuyingPowerPhase.INTRADAY, cfg) == Decimal("0")
