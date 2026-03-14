"""Unit tests for AlphaRegistry."""

from __future__ import annotations

import pytest

from feelies.alpha.lifecycle import AlphaLifecycleState, GateRequirements, PromotionEvidence
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.core.clock import SimulatedClock
from feelies.features.definition import FeatureDefinition, WarmUpSpec

from tests.alpha.conftest import MockAlpha, _make_spread_feature, mock_alpha


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

    def test_feature_definitions_cache_hit(self) -> None:
        """Calling feature_definitions twice returns cached result."""
        registry = AlphaRegistry()
        registry.register(MockAlpha(feature_defs=[_make_spread_feature()]))
        first = registry.feature_definitions()
        second = registry.feature_definitions()
        assert first is second

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


class TestAlphaRegistryLifecycle:
    """Tests for lifecycle-enabled registry."""

    def test_get_lifecycle_returns_none_when_disabled(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        assert registry.get_lifecycle("mock_alpha") is None

    def test_get_lifecycle_returns_none_for_nonexistent(
        self, registry: AlphaRegistry
    ) -> None:
        assert registry.get_lifecycle("nonexistent") is None

    def test_promote_raises_when_lifecycle_disabled(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        from feelies.alpha.lifecycle import PromotionEvidence

        registry.register(mock_alpha)
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        with pytest.raises(AlphaRegistryError, match="Lifecycle tracking is disabled"):
            registry.promote("mock_alpha", evidence)

    def test_promote_raises_when_alpha_not_registered(self) -> None:
        from feelies.core.clock import SimulatedClock

        from feelies.alpha.lifecycle import GateRequirements, PromotionEvidence

        clock = SimulatedClock(start_ns=0)
        registry = AlphaRegistry(clock=clock, gate_requirements=GateRequirements())
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        with pytest.raises(KeyError, match="not registered"):
            registry.promote("nonexistent", evidence)

    def test_quarantine_raises_when_lifecycle_disabled(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        with pytest.raises(AlphaRegistryError, match="Lifecycle tracking is disabled"):
            registry.quarantine("mock_alpha", "test reason")

    def test_decommission_raises_when_lifecycle_disabled(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        with pytest.raises(AlphaRegistryError, match="Lifecycle tracking is disabled"):
            registry.decommission("mock_alpha", "test reason")

    def test_quarantine_raises_when_alpha_not_registered(self) -> None:
        from feelies.core.clock import SimulatedClock

        from feelies.alpha.lifecycle import GateRequirements

        clock = SimulatedClock(start_ns=0)
        registry = AlphaRegistry(clock=clock, gate_requirements=GateRequirements())
        with pytest.raises(KeyError, match="not registered"):
            registry.quarantine("nonexistent", "reason")

    def test_decommission_raises_when_alpha_not_registered(self) -> None:
        from feelies.core.clock import SimulatedClock

        from feelies.alpha.lifecycle import GateRequirements

        clock = SimulatedClock(start_ns=0)
        registry = AlphaRegistry(clock=clock, gate_requirements=GateRequirements())
        with pytest.raises(KeyError, match="not registered"):
            registry.decommission("nonexistent", "reason")

    def test_feature_definitions_cache_invalidated_on_unregister(
        self, registry: AlphaRegistry, mock_alpha: MockAlpha
    ) -> None:
        registry.register(mock_alpha)
        _ = registry.feature_definitions()
        registry.unregister("mock_alpha")
        assert "mock_alpha" not in registry

    def test_full_lifecycle_promotion_flow(
        self, mock_alpha: MockAlpha
    ) -> None:
        from feelies.core.clock import SimulatedClock

        from feelies.alpha.lifecycle import (
            AlphaLifecycleState,
            GateRequirements,
            PromotionEvidence,
        )

        clock = SimulatedClock(start_ns=0)
        gate = GateRequirements(
            paper_min_days=1,
            paper_min_sharpe=0.5,
            paper_min_hit_rate=0.48,
            paper_max_drawdown_pct=10.0,
        )
        registry = AlphaRegistry(clock=clock, gate_requirements=gate)
        registry.register(mock_alpha)

        assert registry.get_lifecycle("mock_alpha") is not None
        assert registry.lifecycle_states() == {"mock_alpha": AlphaLifecycleState.RESEARCH}

        paper_evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        errors = registry.promote("mock_alpha", paper_evidence)
        assert errors == []
        assert registry.lifecycle_states()["mock_alpha"] == AlphaLifecycleState.PAPER
        assert registry.active_alphas() == [mock_alpha]

        live_evidence = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            paper_max_drawdown_pct=2.0,
            cost_model_validated=True,
        )
        errors = registry.promote("mock_alpha", live_evidence)
        assert errors == []
        assert registry.lifecycle_states()["mock_alpha"] == AlphaLifecycleState.LIVE

        registry.quarantine("mock_alpha", "edge decay detected")
        assert registry.lifecycle_states()["mock_alpha"] == AlphaLifecycleState.QUARANTINED
        assert registry.active_alphas() == []

        reval_evidence = PromotionEvidence(
            determinism_test_passed=True,
            revalidation_notes="human reviewed",
        )
        errors = registry.promote("mock_alpha", reval_evidence)
        assert errors == []
        assert registry.lifecycle_states()["mock_alpha"] == AlphaLifecycleState.PAPER

        # Must promote to LIVE again before quarantine (quarantine only from LIVE)
        errors = registry.promote("mock_alpha", live_evidence)
        assert errors == []
        registry.quarantine("mock_alpha", "again")
        registry.decommission("mock_alpha", "retired")
        assert registry.lifecycle_states()["mock_alpha"] == AlphaLifecycleState.DECOMMISSIONED

    def test_promote_from_live_returns_error(
        self, mock_alpha: MockAlpha
    ) -> None:
        from feelies.core.clock import SimulatedClock

        from feelies.alpha.lifecycle import (
            GateRequirements,
            PromotionEvidence,
        )

        clock = SimulatedClock(start_ns=0)
        gate = GateRequirements(paper_min_days=1, paper_min_sharpe=0.0)
        registry = AlphaRegistry(clock=clock, gate_requirements=gate)
        registry.register(mock_alpha)

        paper_evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        registry.promote("mock_alpha", paper_evidence)
        live_evidence = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            paper_max_drawdown_pct=0.0,
            cost_model_validated=True,
        )
        registry.promote("mock_alpha", live_evidence)

        errors = registry.promote("mock_alpha", live_evidence)
        assert len(errors) == 1
        assert "cannot be promoted" in errors[0]
