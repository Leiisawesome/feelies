"""Unit tests for AlphaRegistry."""

from __future__ import annotations

import pytest

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.features.definition import FeatureDefinition, WarmUpSpec

from tests.alpha.conftest import MockAlpha, _make_spread_feature


class TestAlphaRegistry:
    """Tests for AlphaRegistry registration and lifecycle."""

    def test_register_and_get(self, registry: AlphaRegistry, mock_alpha: MockAlpha) -> None:
        registry.register(mock_alpha)
        assert registry.get("mock_alpha") is mock_alpha
        assert "mock_alpha" in registry
        assert len(registry) == 1

    def test_register_duplicate_raises(self, registry: AlphaRegistry, mock_alpha: MockAlpha) -> None:
        registry.register(mock_alpha)
        with pytest.raises(AlphaRegistryError, match="already registered"):
            registry.register(mock_alpha)

    def test_unregister(self, registry: AlphaRegistry, mock_alpha: MockAlpha) -> None:
        registry.register(mock_alpha)
        registry.unregister("mock_alpha")
        assert "mock_alpha" not in registry
        assert len(registry) == 0
        with pytest.raises(KeyError, match="mock_alpha"):
            registry.get("mock_alpha")

    def test_unregister_nonexistent_raises(self, registry: AlphaRegistry) -> None:
        with pytest.raises(KeyError):
            registry.unregister("nonexistent")

    def test_register_invalid_alpha_raises(self, registry: AlphaRegistry) -> None:
        class InvalidAlpha(MockAlpha):
            def validate(self) -> list[str]:
                return ["validation error"]

        invalid = InvalidAlpha(alpha_id="invalid")
        with pytest.raises(AlphaRegistryError, match="failed validation"):
            registry.register(invalid)

    def test_active_alphas_returns_registration_order(
        self, registry: AlphaRegistry
    ) -> None:
        a1 = MockAlpha(alpha_id="alpha1")
        a2 = MockAlpha(alpha_id="alpha2")
        registry.register(a1)
        registry.register(a2)
        assert registry.active_alphas() == [a1, a2]

    def test_alpha_ids(self, registry: AlphaRegistry, mock_alpha: MockAlpha) -> None:
        registry.register(mock_alpha)
        assert registry.alpha_ids() == frozenset({"mock_alpha"})


class TestAlphaRegistryFeatureDefinitions:
    """Tests for feature_definitions() and version conflict detection."""

    def test_feature_definitions_returns_merged_defs(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        defs = registry.feature_definitions()
        assert len(defs) == 1
        assert defs[0].feature_id == "spread"

    def test_feature_version_conflict_raises(self, registry: AlphaRegistry) -> None:
        class SpreadV1(MockAlpha):
            pass

        class SpreadV2(MockAlpha):
            pass

        def make_v1() -> FeatureDefinition:
            f = _make_spread_feature()
            return FeatureDefinition(
                feature_id="spread",
                version="1.0",
                description="v1",
                depends_on=frozenset(),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            )

        def make_v2() -> FeatureDefinition:
            f = _make_spread_feature()
            return FeatureDefinition(
                feature_id="spread",
                version="2.0",
                description="v2",
                depends_on=frozenset(),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            )

        a1 = MockAlpha(alpha_id="a1", feature_defs=[make_v1()])
        a2 = MockAlpha(alpha_id="a2", feature_defs=[make_v2()])
        registry.register(a1)
        registry.register(a2)
        with pytest.raises(AlphaRegistryError, match="version conflict"):
            registry.feature_definitions()

    def test_same_feature_same_version_deduplicated(
        self, registry: AlphaRegistry
    ) -> None:
        spread = _make_spread_feature()
        a1 = MockAlpha(alpha_id="a1", feature_defs=[spread])
        a2 = MockAlpha(alpha_id="a2", feature_defs=[spread])
        registry.register(a1)
        registry.register(a2)
        defs = registry.feature_definitions()
        assert len(defs) == 1


class TestAlphaRegistryValidateAll:
    """Tests for validate_all() cross-alpha validation."""

    def test_validate_all_empty_when_valid(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        result = registry.validate_all()
        assert result == {}

    def test_validate_all_reports_cross_alpha_errors(
        self, registry: AlphaRegistry
    ) -> None:
        def make_v1() -> FeatureDefinition:
            f = _make_spread_feature()
            return FeatureDefinition(
                feature_id="spread",
                version="1.0",
                description="v1",
                depends_on=frozenset(),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            )

        def make_v2() -> FeatureDefinition:
            f = _make_spread_feature()
            return FeatureDefinition(
                feature_id="spread",
                version="2.0",
                description="v2",
                depends_on=frozenset(),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            )

        a1 = MockAlpha(alpha_id="a1", feature_defs=[make_v1()])
        a2 = MockAlpha(alpha_id="a2", feature_defs=[make_v2()])
        registry.register(a1)
        registry.register(a2)

        result = registry.validate_all()
        assert "__cross_alpha__" in result
        assert any("version conflict" in msg for msg in result["__cross_alpha__"])
