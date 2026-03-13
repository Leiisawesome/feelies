"""Unit tests for AlphaManifest, AlphaRiskBudget, AlphaModule protocol."""

from __future__ import annotations

import pytest

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget

from tests.alpha.conftest import MockAlpha


class TestAlphaRiskBudget:
    """Tests for AlphaRiskBudget dataclass."""

    def test_default_values(self) -> None:
        budget = AlphaRiskBudget(
            max_position_per_symbol=100,
            max_gross_exposure_pct=5.0,
            max_drawdown_pct=1.0,
            capital_allocation_pct=10.0,
        )
        assert budget.max_position_per_symbol == 100
        assert budget.max_gross_exposure_pct == 5.0
        assert budget.max_drawdown_pct == 1.0
        assert budget.capital_allocation_pct == 10.0

    def test_is_frozen(self) -> None:
        budget = AlphaRiskBudget(
            max_position_per_symbol=50,
            max_gross_exposure_pct=2.0,
            max_drawdown_pct=0.5,
            capital_allocation_pct=5.0,
        )
        with pytest.raises(AttributeError):
            budget.max_position_per_symbol = 200


class TestAlphaManifest:
    """Tests for AlphaManifest dataclass."""

    def test_creates_with_required_fields(self) -> None:
        manifest = AlphaManifest(
            alpha_id="test_alpha",
            version="1.0",
            description="Test",
            hypothesis="H0",
            falsification_criteria=("fail",),
            required_features=frozenset({"f1"}),
        )
        assert manifest.alpha_id == "test_alpha"
        assert manifest.version == "1.0"
        assert manifest.required_features == frozenset({"f1"})
        assert manifest.symbols is None
        assert manifest.parameters == {}

    def test_has_default_risk_budget(self) -> None:
        manifest = AlphaManifest(
            alpha_id="x",
            version="1",
            description="d",
            hypothesis="h",
            falsification_criteria=(),
            required_features=frozenset(),
        )
        assert manifest.risk_budget.max_position_per_symbol == 100
        assert manifest.risk_budget.max_gross_exposure_pct == 5.0


class TestAlphaModuleProtocol:
    """Tests for AlphaModule protocol conformance via MockAlpha."""

    def test_mock_alpha_has_manifest(self, mock_alpha: MockAlpha) -> None:
        assert mock_alpha.manifest.alpha_id == "mock_alpha"
        assert mock_alpha.manifest.version == "1.0"

    def test_mock_alpha_feature_definitions(self, mock_alpha: MockAlpha) -> None:
        defs = mock_alpha.feature_definitions()
        assert len(defs) == 1
        assert defs[0].feature_id == "spread"
        assert defs[0].version == "1.0"

    def test_mock_alpha_validate_returns_empty(self, mock_alpha: MockAlpha) -> None:
        assert mock_alpha.validate() == []
