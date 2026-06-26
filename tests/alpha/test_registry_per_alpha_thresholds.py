"""Workstream F-5: AlphaRegistry per-alpha gate-threshold override tests.

Pins the layering rules that
:class:`feelies.alpha.registry.AlphaRegistry` honours when a manifest
carries ``gate_thresholds_overrides``:

  1. **No registry base + no manifest overrides** — lifecycle uses the
     skill-pinned :class:`GateThresholds` defaults (current F-2 / F-4
     baseline).
  2. **Registry base only** — every alpha picks up the same base.
  3. **Manifest overrides only** — registry's ``None`` is upgraded to
     a fresh :class:`GateThresholds` and the manifest values are
     layered on top.
  4. **Both layers present** — manifest values win for the keys they
     set; the rest fall back to the registry base.
  5. **Empty / falsy manifest overrides** — treated as "no per-alpha
     overrides" (identity).
  6. **Per-alpha isolation** — overrides on one alpha do not bleed
     into another alpha registered into the same registry.
"""

from __future__ import annotations

import pytest

from feelies.alpha.lifecycle import AlphaLifecycle, AlphaLifecycleState
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.promotion_evidence import (
    GateThresholds,
    ResearchAcceptanceEvidence,
    apply_gate_thresholds_overrides,
)
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.core.clock import SimulatedClock
from feelies.features.definition import FeatureDefinition


class _StubModule:
    """Minimal AlphaModule implementation that exposes per-alpha
    ``gate_thresholds_overrides`` via its manifest.
    """

    def __init__(
        self,
        alpha_id: str,
        *,
        gate_thresholds_overrides: dict[str, object] | None = None,
    ) -> None:
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description=f"stub for {alpha_id}",
            hypothesis="test",
            falsification_criteria=("none",),
            required_features=frozenset(),
            layer="SIGNAL",
            risk_budget=AlphaRiskBudget(
                max_position_per_symbol=100,
                max_gross_exposure_pct=5.0,
                max_drawdown_pct=1.0,
                capital_allocation_pct=10.0,
            ),
            gate_thresholds_overrides=gate_thresholds_overrides,
        )

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> tuple[FeatureDefinition, ...]:
        return ()

    def validate(self) -> list[str]:
        return []


def _passing_research_acceptance(
    branch_coverage_pct: float = 92.0,
) -> ResearchAcceptanceEvidence:
    return ResearchAcceptanceEvidence(
        schema_valid=True,
        determinism_replay_passed=True,
        branch_coverage_pct=branch_coverage_pct,
        line_coverage_pct=85.0,
        lookahead_bias_check_passed=True,
        fault_injection_pass_count=12,
        fault_injection_total=12,
        cost_sensitivity_passed=True,
        latency_sensitivity_passed=True,
    )


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=1_700_000_000_000_000_000)


# ─────────────────────────────────────────────────────────────────────
# Layering semantics
# ─────────────────────────────────────────────────────────────────────


class TestAlphaRegistryPerAlphaThresholds:
    def test_no_overrides_anywhere_uses_skill_defaults(self, clock: SimulatedClock) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))

        # 92% branch coverage > skill-default 90% → passes.
        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert errors == []
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.PAPER

    def test_manifest_overrides_only_tightens_threshold(self, clock: SimulatedClock) -> None:
        # No registry base; the manifest tightens branch coverage to 99%
        # so the same evidence (92%) must now fail.
        registry = AlphaRegistry(clock=clock)
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={"research_min_branch_coverage_pct": 99.0},
            )
        )

        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert any("branch coverage" in e for e in errors)
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.RESEARCH

    def test_manifest_overrides_loosens_threshold_off_skill_default(
        self, clock: SimulatedClock
    ) -> None:
        # Borderline 80% branch coverage would fail the 90% skill
        # default but pass once the manifest lowers the threshold.
        registry = AlphaRegistry(clock=clock)
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={
                    "research_min_branch_coverage_pct": 75.0,
                    "research_min_line_coverage_pct": 70.0,
                },
            )
        )

        errors = registry.promote(
            "kyle",
            structured_evidence=[_passing_research_acceptance(branch_coverage_pct=80.0)],
        )
        assert errors == []
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.PAPER

    def test_manifest_overrides_layered_on_top_of_registry_base(
        self, clock: SimulatedClock
    ) -> None:
        # Registry tightens branch coverage to 99%; manifest tightens
        # line coverage to 99% but leaves branch unchanged.  Net
        # result: lifecycle uses 99% branch (from registry) AND 99%
        # line (from manifest).  Evidence at 92%/85% must fail BOTH.
        registry = AlphaRegistry(
            clock=clock,
            gate_thresholds=GateThresholds(research_min_branch_coverage_pct=99.0),
        )
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={"research_min_line_coverage_pct": 99.0},
            )
        )

        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert any("branch coverage" in e for e in errors)
        assert any("line coverage" in e for e in errors)

    def test_manifest_override_wins_when_both_layers_set_same_key(
        self, clock: SimulatedClock
    ) -> None:
        # Registry says branch=70 (loose); manifest says branch=99
        # (tight).  Manifest must win.
        registry = AlphaRegistry(
            clock=clock,
            gate_thresholds=GateThresholds(research_min_branch_coverage_pct=70.0),
        )
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={"research_min_branch_coverage_pct": 99.0},
            )
        )

        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert any("branch coverage" in e for e in errors)

    def test_empty_manifest_overrides_treated_as_none(self, clock: SimulatedClock) -> None:
        # Registry tightens branch to 99%; manifest carries an empty
        # dict → falls back to registry base, which still rejects 92%.
        registry = AlphaRegistry(
            clock=clock,
            gate_thresholds=GateThresholds(research_min_branch_coverage_pct=99.0),
        )
        registry.register(_StubModule("kyle", gate_thresholds_overrides={}))

        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert any("branch coverage" in e for e in errors)

    def test_per_alpha_isolation_no_bleed_through(self, clock: SimulatedClock) -> None:
        # Two alphas in the same registry: 'tight' carries an
        # override; 'loose' does not.  The override must NOT affect
        # 'loose'.
        registry = AlphaRegistry(clock=clock)
        registry.register(
            _StubModule(
                "tight",
                gate_thresholds_overrides={"research_min_branch_coverage_pct": 99.0},
            )
        )
        registry.register(_StubModule("loose"))

        tight_errors = registry.promote(
            "tight", structured_evidence=[_passing_research_acceptance()]
        )
        loose_errors = registry.promote(
            "loose", structured_evidence=[_passing_research_acceptance()]
        )

        assert any("branch coverage" in e for e in tight_errors)
        assert loose_errors == []
        states = registry.lifecycle_states()
        assert states["tight"] == AlphaLifecycleState.RESEARCH
        assert states["loose"] == AlphaLifecycleState.PAPER

    def test_lifecycle_resolves_thresholds_at_construction_time(
        self, clock: SimulatedClock
    ) -> None:
        # The merged thresholds are baked into the AlphaLifecycle at
        # registration; later mutation of the registry's base must not
        # retroactively affect already-registered alphas.  This pins
        # the immutability guarantee that simplifies replay reasoning.
        registry = AlphaRegistry(
            clock=clock,
            gate_thresholds=GateThresholds(research_min_branch_coverage_pct=70.0),
        )
        registry.register(_StubModule("kyle"))

        # Mutate the registry's base (treating ``_gate_thresholds`` as
        # a private attribute is intentional — the public API doesn't
        # offer a re-bind path).
        registry._gate_thresholds = GateThresholds(  # noqa: SLF001
            research_min_branch_coverage_pct=99.0
        )

        # The kyle lifecycle was bound to the *old* base, so 92%
        # coverage must still pass.
        errors = registry.promote("kyle", structured_evidence=[_passing_research_acceptance()])
        assert errors == []

    def test_lifecycle_object_carries_resolved_thresholds(self, clock: SimulatedClock) -> None:
        # White-box: confirm the merge path actually constructs the
        # AlphaLifecycle with the materialised thresholds (not just
        # passes through the registry's base).  ``_gate_thresholds``
        # is private; ``AlphaLifecycle.__init__`` materialises the
        # skill-pinned defaults whenever ``None`` is passed, so the
        # presence of the override is observable here.
        registry = AlphaRegistry(clock=clock)
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={"dsr_min": 2.0},
            )
        )
        lc = registry.get_lifecycle("kyle")
        assert isinstance(lc, AlphaLifecycle)
        assert lc._gate_thresholds.dsr_min == 2.0  # noqa: SLF001

    def test_lifecycle_thresholds_match_skill_defaults_when_no_overrides(
        self, clock: SimulatedClock
    ) -> None:
        # No registry base + no manifest overrides: the registry
        # passes ``None`` through, and ``AlphaLifecycle.__init__``
        # materialises the skill-pinned ``GateThresholds()`` defaults.
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        lc = registry.get_lifecycle("kyle")
        assert isinstance(lc, AlphaLifecycle)
        assert (
            lc._gate_thresholds.dsr_min  # noqa: SLF001
            == GateThresholds().dsr_min
        )


# ─────────────────────────────────────────────────────────────────────
# Audit P0-1: per-alpha overrides may not loosen an operator-pinned floor
# ─────────────────────────────────────────────────────────────────────


def _floored_registry(
    clock: SimulatedClock,
    overrides: dict[str, object],
) -> AlphaRegistry:
    """A registry whose operator (platform.yaml) explicitly pinned
    ``overrides`` — mirroring how ``bootstrap.build_platform`` wires the
    materialised floor *and* the raw pinned-field dict together.
    """
    base = apply_gate_thresholds_overrides(GateThresholds(), overrides)
    return AlphaRegistry(
        clock=clock,
        gate_thresholds=base,
        platform_gate_threshold_overrides=overrides,
    )


class TestPerAlphaFloorEnforcement:
    def test_rejects_loosening_below_pinned_min_floor(self, clock: SimulatedClock) -> None:
        registry = _floored_registry(clock, {"cpcv_min_mean_sharpe": 2.0})
        with pytest.raises(AlphaRegistryError, match="may not loosen"):
            registry.register(
                _StubModule("kyle", gate_thresholds_overrides={"cpcv_min_mean_sharpe": 0.1})
            )

    def test_rejects_loosening_above_pinned_max_ceiling(self, clock: SimulatedClock) -> None:
        registry = _floored_registry(clock, {"cpcv_max_p_value": 0.01})
        with pytest.raises(AlphaRegistryError, match="may not loosen"):
            registry.register(
                _StubModule("kyle", gate_thresholds_overrides={"cpcv_max_p_value": 0.2})
            )

    def test_allows_tightening_a_pinned_floor(self, clock: SimulatedClock) -> None:
        registry = _floored_registry(clock, {"cpcv_min_mean_sharpe": 2.0})
        registry.register(
            _StubModule("kyle", gate_thresholds_overrides={"cpcv_min_mean_sharpe": 3.0})
        )
        lc = registry.get_lifecycle("kyle")
        assert lc is not None
        assert lc._gate_thresholds.cpcv_min_mean_sharpe == 3.0  # noqa: SLF001

    def test_allows_loosening_a_field_the_operator_did_not_pin(self, clock: SimulatedClock) -> None:
        # Operator pinned cpcv only; per-alpha loosens dsr_min (still at
        # skill default) — preserves documented F-5 "per-alpha wins over
        # skill defaults" behavior.
        registry = _floored_registry(clock, {"cpcv_min_mean_sharpe": 2.0})
        registry.register(_StubModule("kyle", gate_thresholds_overrides={"dsr_min": 0.0}))
        lc = registry.get_lifecycle("kyle")
        assert lc is not None
        assert lc._gate_thresholds.dsr_min == 0.0  # noqa: SLF001

    def test_quarantine_consistency_field_is_not_floored(self, clock: SimulatedClock) -> None:
        # Quarantine-trigger thresholds never gate a transition (FREE
        # direction), so a per-alpha override may move them even when the
        # operator pinned them.
        registry = _floored_registry(clock, {"quarantine_max_net_alpha_negative_days": 10})
        registry.register(
            _StubModule(
                "kyle",
                gate_thresholds_overrides={"quarantine_max_net_alpha_negative_days": 999},
            )
        )
        assert registry.get_lifecycle("kyle") is not None

    def test_rejected_override_leaves_registry_clean(self, clock: SimulatedClock) -> None:
        registry = _floored_registry(clock, {"cpcv_min_mean_sharpe": 2.0})
        with pytest.raises(AlphaRegistryError):
            registry.register(
                _StubModule("kyle", gate_thresholds_overrides={"cpcv_min_mean_sharpe": 0.1})
            )
        # No half-registration: the alpha is absent and no lifecycle exists.
        assert "kyle" not in registry
        assert len(registry) == 0
        assert registry.get_lifecycle("kyle") is None

    def test_no_pinned_floors_means_no_enforcement(self, clock: SimulatedClock) -> None:
        # Without an operator-pinned override dict (e.g. a registry
        # constructed directly with a GateThresholds base), the floor
        # rule does not fire — per-alpha may loosen freely.
        registry = AlphaRegistry(
            clock=clock,
            gate_thresholds=GateThresholds(cpcv_min_mean_sharpe=2.0),
        )
        registry.register(
            _StubModule("kyle", gate_thresholds_overrides={"cpcv_min_mean_sharpe": 0.1})
        )
        lc = registry.get_lifecycle("kyle")
        assert lc is not None
        assert lc._gate_thresholds.cpcv_min_mean_sharpe == 0.1  # noqa: SLF001
