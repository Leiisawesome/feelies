"""Unit tests for validate_alpha_set."""

from __future__ import annotations

import pytest

from feelies.alpha.validation import validate_alpha_set
from feelies.features.definition import FeatureDefinition, WarmUpSpec

from tests.alpha.conftest import MockAlpha, _make_spread_feature


class TestValidateAlphaSet:
    """Tests for cross-alpha validation."""

    def test_empty_set_valid(self) -> None:
        assert validate_alpha_set([]) == []

    def test_single_alpha_valid(self) -> None:
        alpha = MockAlpha(
            required_features=frozenset({"spread"}),
            feature_defs=[_make_spread_feature()],
        )
        errors = validate_alpha_set([alpha])
        assert errors == []

    def test_chain_no_cycle_backtrack_path_pop(self) -> None:
        """Two-node chain A->B exercises path.pop() during DFS backtrack."""
        f = _make_spread_feature()
        base = FeatureDefinition(
            feature_id="base",
            version="1",
            description="base",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(),
            compute=f.compute,
        )
        derived = FeatureDefinition(
            feature_id="derived",
            version="1",
            description="derived",
            depends_on=frozenset({"base"}),
            warm_up=WarmUpSpec(),
            compute=f.compute,
        )
        alpha = MockAlpha(
            alpha_id="chain",
            feature_defs=[base, derived],
        )
        errors = validate_alpha_set([alpha])
        assert errors == []

    def test_feature_version_conflict(self) -> None:
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
        errors = validate_alpha_set([a1, a2])
        assert any("version conflict" in e for e in errors)

    def test_dependency_cycle_three_nodes(self) -> None:
        """Three-node cycle A->B->C->A exercises path.pop in cycle detection."""
        f = _make_spread_feature()
        a1 = MockAlpha(
            alpha_id="a1",
            feature_defs=[
                FeatureDefinition(
                    feature_id="a", version="1", description="a",
                    depends_on=frozenset({"c"}), warm_up=WarmUpSpec(), compute=f.compute,
                ),
                FeatureDefinition(
                    feature_id="b", version="1", description="b",
                    depends_on=frozenset({"a"}), warm_up=WarmUpSpec(), compute=f.compute,
                ),
                FeatureDefinition(
                    feature_id="c", version="1", description="c",
                    depends_on=frozenset({"b"}), warm_up=WarmUpSpec(), compute=f.compute,
                ),
            ],
        )
        errors = validate_alpha_set([a1])
        assert any("cycle" in e.lower() for e in errors)

    def test_dependency_cycle(self) -> None:
        f = _make_spread_feature()
        base = FeatureDefinition(
            feature_id="base",
            version="1.0",
            description="base",
            depends_on=frozenset(),
            warm_up=WarmUpSpec(),
            compute=f.compute,
        )
        derived = FeatureDefinition(
            feature_id="derived",
            version="1.0",
            description="derived",
            depends_on=frozenset({"base"}),
            warm_up=WarmUpSpec(),
            compute=f.compute,
        )
        cycle = FeatureDefinition(
            feature_id="base",
            version="1.0",
            description="cycle",
            depends_on=frozenset({"derived"}),
            warm_up=WarmUpSpec(),
            compute=f.compute,
        )
        # We need base -> derived -> base cycle. So base depends on derived, derived depends on base.
        # In _collect_feature_defs, first-seen wins. So we need one alpha with base (depends on derived)
        # and one with derived (depends on base). The merged graph: base.depends_on = {derived},
        # derived.depends_on = {base}. That's a cycle.
        a1 = MockAlpha(alpha_id="a1", feature_defs=[
            FeatureDefinition(
                feature_id="base",
                version="1.0",
                description="b",
                depends_on=frozenset({"derived"}),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            ),
            FeatureDefinition(
                feature_id="derived",
                version="1.0",
                description="d",
                depends_on=frozenset({"base"}),
                warm_up=WarmUpSpec(),
                compute=f.compute,
            ),
        ])
        errors = validate_alpha_set([a1])
        assert any("cycle" in e.lower() for e in errors)

    def test_required_features_missing(self) -> None:
        alpha = MockAlpha(
            alpha_id="needs_more",
            required_features=frozenset({"spread", "nonexistent"}),
            feature_defs=[_make_spread_feature()],
        )
        errors = validate_alpha_set([alpha])
        assert any("nonexistent" in e for e in errors)
        assert any("requires" in e for e in errors)
