"""Unit tests for Reg-T buying-power helpers (BT-15)."""

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
