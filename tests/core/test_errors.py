"""Unit tests for error hierarchy."""

from __future__ import annotations

import pytest

from feelies.core.errors import (
    CausalityViolation,
    ConfigurationError,
    DataIntegrityError,
    DeterminismViolation,
    ExecutionError,
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
    def test_all_inherit_from_feelies_error(
        self, error_cls: type[FeeliesError]
    ) -> None:
        exc = error_cls("msg")
        assert isinstance(exc, FeeliesError)
        assert isinstance(exc, Exception)

    def test_raise_and_catch(self) -> None:
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("invalid config")
