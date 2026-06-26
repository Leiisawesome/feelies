"""Unit tests for error hierarchy."""

from __future__ import annotations

import pytest

from feelies.core.errors import (
    CausalityViolation,
    ConfigurationError,
    DataIntegrityError,
    DeterminismViolation,
    ExecutionError,
    FailureMode,
    FeeliesError,
    RiskBreachError,
    StaleDataError,
)


class TestErrorHierarchy:
    """Tests for error class inheritance."""

    @pytest.mark.parametrize(
        "error_cls",
        [
            ConfigurationError,
            DataIntegrityError,
            CausalityViolation,
            DeterminismViolation,
            RiskBreachError,
            ExecutionError,
            StaleDataError,
        ],
    )
    def test_all_inherit_from_feelies_error(self, error_cls: type[FeeliesError]) -> None:
        exc = error_cls("msg")
        assert isinstance(exc, FeeliesError)
        assert isinstance(exc, Exception)

    def test_raise_and_catch(self) -> None:
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("invalid config")

    @pytest.mark.parametrize(
        ("error_cls", "expected_mode"),
        [
            (ConfigurationError, FailureMode.CRASH),
            (CausalityViolation, FailureMode.CRASH),
            (DeterminismViolation, FailureMode.CRASH),
            (DataIntegrityError, FailureMode.DEGRADE),
            (StaleDataError, FailureMode.DEGRADE),
            (ExecutionError, FailureMode.RETRY),
            (RiskBreachError, FailureMode.LOCKDOWN),
        ],
    )
    def test_failure_mode_classification(
        self, error_cls: type[FeeliesError], expected_mode: FailureMode
    ) -> None:
        assert error_cls.failure_mode is expected_mode
        assert error_cls("m").failure_mode is expected_mode
