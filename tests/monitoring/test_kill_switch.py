"""Tests for the KillSwitch protocol contract."""

from __future__ import annotations


class SimpleKillSwitch:
    """Minimal concrete KillSwitch implementation for testing the protocol."""

    def __init__(self) -> None:
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self, reason: str, *, activated_by: str = "automated") -> None:
        self._active = True

    def reset(self, *, operator: str, audit_token: str) -> None:
        self._active = False


class TestKillSwitch:
    def test_starts_inactive(self) -> None:
        ks = SimpleKillSwitch()
        assert ks.is_active is False

    def test_activate_engages_switch(self) -> None:
        ks = SimpleKillSwitch()
        ks.activate("test emergency", activated_by="test")
        assert ks.is_active is True

    def test_reset_with_audit_token_disengages(self) -> None:
        ks = SimpleKillSwitch()
        ks.activate("drawdown breach")
        assert ks.is_active is True

        ks.reset(operator="human_operator", audit_token="AUDIT-2026-001")
        assert ks.is_active is False

    def test_double_activate_stays_active(self) -> None:
        ks = SimpleKillSwitch()
        ks.activate("first reason")
        ks.activate("second reason")
        assert ks.is_active is True

    def test_reset_without_prior_activation_stays_inactive(self) -> None:
        ks = SimpleKillSwitch()
        ks.reset(operator="op", audit_token="tok")
        assert ks.is_active is False
