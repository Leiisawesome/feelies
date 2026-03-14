"""Unit tests for AlphaManifest, AlphaRiskBudget, AlphaModule protocol, ParameterDef."""

from __future__ import annotations

import pytest

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget, ParameterDef

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


class TestParameterDef:
    """Tests for ParameterDef typed parameter validation."""

    def test_validate_value_correct_type_int(self) -> None:
        pdef = ParameterDef(name="x", param_type="int", default=5)
        assert pdef.validate_value(10) == []

    def test_validate_value_correct_type_float(self) -> None:
        pdef = ParameterDef(name="x", param_type="float", default=1.5)
        assert pdef.validate_value(2.5) == []

    def test_validate_value_int_acceptable_for_float(self) -> None:
        pdef = ParameterDef(name="x", param_type="float", default=1.0)
        assert pdef.validate_value(5) == []

    def test_validate_value_wrong_type(self) -> None:
        pdef = ParameterDef(name="x", param_type="int", default=5)
        errs = pdef.validate_value("hello")
        assert len(errs) == 1
        assert "expected int" in errs[0]

    def test_validate_value_unknown_type(self) -> None:
        pdef = ParameterDef(name="x", param_type="unknown_type", default=1)
        errs = pdef.validate_value(1)
        assert len(errs) == 1
        assert "unknown type" in errs[0]

    def test_validate_value_range_within(self) -> None:
        pdef = ParameterDef(
            name="x", param_type="float", default=2.0, range=(1.0, 10.0)
        )
        assert pdef.validate_value(5.0) == []

    def test_validate_value_range_below(self) -> None:
        pdef = ParameterDef(
            name="x", param_type="float", default=2.0, range=(1.0, 10.0)
        )
        errs = pdef.validate_value(0.5)
        assert len(errs) == 1
        assert "outside range" in errs[0]

    def test_validate_value_range_above(self) -> None:
        pdef = ParameterDef(
            name="x", param_type="int", default=5, range=(1, 10)
        )
        errs = pdef.validate_value(15)
        assert len(errs) == 1
        assert "outside range" in errs[0]

    def test_validate_value_range_ignored_for_str(self) -> None:
        pdef = ParameterDef(
            name="x", param_type="str", default="a", range=(0, 1)
        )
        assert pdef.validate_value("hello") == []
