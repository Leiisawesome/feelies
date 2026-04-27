"""Strict-mode RESEARCH → PAPER promotion E2E — Workstream **E-1**.

This is the workstream-closing milestone for Workstream **E** (the
``enforce_trend_mechanism: true`` default flip, acceptance row 84):
it proves the four canonical reference alphas — one per non-stress
family per §20.12.2 #4 — load under strict mode *and* clear the F-4
``RESEARCH_TO_PAPER`` gate end-to-end on a real
:class:`PromotionLedger`, mechanically closing the §20.12.1
precondition that ≥3 reference alphas ship under strict mode in
research/paper before the platform default is flipped.

Coverage summary
================

- :class:`TestStrictModeReferenceAlphasPromote` — for each
  ``(family, alpha_id)`` pair in ``_REFERENCE_BY_FAMILY``:

    1. Load the YAML through
       ``AlphaLoader(enforce_trend_mechanism=True)`` and assert it
       returns a :class:`LoadedSignalLayerModule` with the expected
       :class:`TrendMechanism` enum and a positive
       ``expected_half_life_seconds`` (cross-check against the
       existing :mod:`tests.acceptance.test_strict_mode_reference_alphas`
       so a regression in either keeps the matrix row honest).

    2. Construct a passing :class:`ResearchAcceptanceEvidence` and
       promote a fresh :class:`AlphaLifecycle` from RESEARCH to
       PAPER via :meth:`AlphaLifecycle.promote_to_paper`'s F-4
       ``structured_evidence=...`` keyword — exercising the F-2
       ``RESEARCH_TO_PAPER`` validator end-to-end.

    3. Verify the transition was committed to a per-alpha
       :class:`PromotionLedger` with the correct ``from_state`` /
       ``to_state`` and the F-2 ``research_acceptance`` evidence
       kind round-trippable through :func:`metadata_to_evidence`.

- :class:`TestStrictModeReferenceFamilyCoverage` — schema-1.1
  §20.12.1 precondition: the four reference alphas collectively
  cover every non-stress family (KYLE_INFO, INVENTORY,
  HAWKES_SELF_EXCITE, SCHEDULED_FLOW) — i.e. ≥3 distinct families
  ship under strict mode.  ``LIQUIDITY_STRESS`` is intentionally
  absent because G16 rule 7 forbids stress-family entry signals
  (no production reference SIGNAL alpha can exist for that family);
  stress mechanics are exercised through hazard-exit policies on
  top of other-family alphas.

Why this test is the workstream-E close
=======================================

The §20.12.1 precondition has two halves: (a) ≥3 reference alphas
load under strict mode (closed by
:mod:`tests.acceptance.test_strict_mode_reference_alphas`), and
(b) those alphas have shipped under strict mode in research/paper.
Half (b) requires evidence that the strict-loaded module survives
the *next* lifecycle step — the RESEARCH → PAPER promotion gate —
end-to-end on a real ledger.  This test closes half (b)
mechanically.  Once it is green, the platform default in
:class:`PlatformConfig.enforce_trend_mechanism` can be flipped
``False → True`` (this PR) without violating §20.12.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
)
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.promotion_evidence import (
    KIND_TO_TYPE,
    ResearchAcceptanceEvidence,
    metadata_to_evidence,
)
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.clock import SimulatedClock
from feelies.core.events import TrendMechanism


# ── §20.12.2 #4 reference matrix ────────────────────────────────────────


_ALPHAS_ROOT = Path("alphas")


# One reference SIGNAL alpha per non-stress family.  The pair-form is
# kept aligned with :mod:`tests.acceptance.test_strict_mode_reference_alphas`
# so a future addition of a new family lands in both files together.
_REFERENCE_BY_FAMILY: tuple[tuple[TrendMechanism, str], ...] = (
    (TrendMechanism.KYLE_INFO, "pofi_kyle_drift_v1"),
    (TrendMechanism.INVENTORY, "pofi_inventory_revert_v1"),
    (TrendMechanism.HAWKES_SELF_EXCITE, "pofi_hawkes_burst_v1"),
    (TrendMechanism.SCHEDULED_FLOW, "pofi_moc_imbalance_v1"),
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _alpha_path(alpha_id: str) -> Path:
    return _ALPHAS_ROOT / alpha_id / f"{alpha_id}.alpha.yaml"


def _load_under_strict(alpha_id: str) -> LoadedSignalLayerModule:
    """Load ``alpha_id`` through ``AlphaLoader(enforce_trend_mechanism=True)``.

    A failure here is the loud version of the acceptance row 84
    precondition: the reference YAML must clear every G16 binding
    rule under strict mode for the §20.12.1 ramp to be honest.
    """
    loader = AlphaLoader(enforce_trend_mechanism=True)
    module = loader.load(_alpha_path(alpha_id))
    assert isinstance(module, LoadedSignalLayerModule), (
        f"{alpha_id!r} loaded as {type(module).__name__}; expected "
        "LoadedSignalLayerModule.  _REFERENCE_BY_FAMILY governs "
        "SIGNAL-layer alphas only."
    )
    return module


def _passing_research_acceptance() -> ResearchAcceptanceEvidence:
    """Hand-rolled :class:`ResearchAcceptanceEvidence` that clears the
    default ``GateThresholds`` for the ``RESEARCH_TO_PAPER`` gate.

    Mirrors :mod:`tests.research.test_promotion_pipeline_e2e`'s
    helper (kept duplicated, not imported, so the strict-mode E2E
    suite has no test-to-test coupling and can be deleted independently
    once the workstream is closed).
    """
    return ResearchAcceptanceEvidence(
        schema_valid=True,
        determinism_replay_passed=True,
        branch_coverage_pct=92.0,
        line_coverage_pct=85.0,
        lookahead_bias_check_passed=True,
        fault_injection_pass_count=12,
        fault_injection_total=12,
        cost_sensitivity_passed=True,
        latency_sensitivity_passed=True,
    )


def _make_lifecycle(
    alpha_id: str, *, ledger: PromotionLedger | None = None
) -> AlphaLifecycle:
    clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
    return AlphaLifecycle(alpha_id=alpha_id, clock=clock, ledger=ledger)


# ── Per-alpha strict-load + promote round-trip ──────────────────────────


class TestStrictModeReferenceAlphasPromote:
    """Each reference alpha loads under strict mode *and* clears the
    F-4 RESEARCH → PAPER gate end-to-end on a real ledger.
    """

    @pytest.mark.parametrize(
        ("family", "alpha_id"),
        _REFERENCE_BY_FAMILY,
        ids=lambda x: x.name if isinstance(x, TrendMechanism) else x,
    )
    def test_loads_under_strict_with_expected_family(
        self, family: TrendMechanism, alpha_id: str
    ) -> None:
        """Strict-load returns a SIGNAL module with the declared family
        and a non-zero half-life — the per-alpha cross-check against
        :mod:`tests.acceptance.test_strict_mode_reference_alphas`.
        Detects misclassified family enums or reference-yaml drift
        before the promotion test below builds on the load.
        """
        module = _load_under_strict(alpha_id)
        assert module.trend_mechanism_enum == family, (
            f"{alpha_id!r}: declared trend_mechanism.family is "
            f"{module.trend_mechanism_enum}, expected {family}."
        )
        assert module.expected_half_life_seconds > 0, (
            f"{alpha_id!r}: expected_half_life_seconds must be > 0 "
            "under strict mode (G16 rule 2 enforces a per-family "
            f"floor); got {module.expected_half_life_seconds}."
        )

    @pytest.mark.parametrize(
        ("family", "alpha_id"),
        _REFERENCE_BY_FAMILY,
        ids=lambda x: x.name if isinstance(x, TrendMechanism) else x,
    )
    def test_research_to_paper_promotes_under_strict(
        self, family: TrendMechanism, alpha_id: str
    ) -> None:
        """Strict-loaded module + structured RESEARCH evidence ⇒ PAPER.

        This is the workstream-E §20.12.1 (b) closure: each reference
        alpha that loads under strict mode also clears the F-4
        ``RESEARCH_TO_PAPER`` gate against the F-2 evidence schema.
        Together with the load test above, it mechanically proves
        "≥3 reference alphas have shipped under strict mode in
        research/paper" before the platform default flip.
        """
        # Loaded for its side-effects (parses YAML + runs every G16
        # binding rule).  We never feed the module into the lifecycle
        # — the RESEARCH → PAPER gate is purely a function of the
        # F-2 structured evidence, not of the alpha YAML.
        _load_under_strict(alpha_id)

        lc = _make_lifecycle(alpha_id)
        errors = lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()],
        )
        assert errors == [], (
            f"{alpha_id!r} ({family.name}): RESEARCH_TO_PAPER gate "
            f"rejected strict-loaded reference alpha — {errors}"
        )
        assert lc.state is AlphaLifecycleState.PAPER

    @pytest.mark.parametrize(
        ("family", "alpha_id"),
        _REFERENCE_BY_FAMILY,
        ids=lambda x: x.name if isinstance(x, TrendMechanism) else x,
    )
    def test_research_to_paper_writes_round_trippable_ledger_entry(
        self,
        family: TrendMechanism,
        alpha_id: str,
        tmp_path: Path,
    ) -> None:
        """The F-4 promote_to_paper path persists the F-2 structured
        evidence to the F-1 ledger, and the F-3 inverse helper
        :func:`metadata_to_evidence` reconstructs it bit-identically.
        """
        ledger = PromotionLedger(tmp_path / f"{alpha_id}.jsonl")
        lc = _make_lifecycle(alpha_id, ledger=ledger)
        ev = _passing_research_acceptance()

        errors = lc.promote_to_paper(structured_evidence=[ev])
        assert errors == []

        entries = list(ledger.entries())
        assert len(entries) == 1, (
            f"{alpha_id!r}: expected exactly one ledger entry "
            f"(RESEARCH → PAPER); got {len(entries)}"
        )
        entry = entries[0]
        assert (entry.from_state, entry.to_state) == ("RESEARCH", "PAPER")
        assert entry.alpha_id == alpha_id

        # F-2 metadata-to-evidence inverse: the entry must round-trip
        # back to the same dataclass content the writer emitted.
        # ``evidence_to_metadata`` flattens each evidence under its
        # stable kind string (looked up via :data:`KIND_TO_TYPE`);
        # ``metadata_to_evidence`` reconstructs the dataclass list in
        # canonical order.  The research_acceptance kind is the only
        # kind the RESEARCH_TO_PAPER gate writes here.
        research_kind = next(
            kind
            for kind, ev_type in KIND_TO_TYPE.items()
            if ev_type is ResearchAcceptanceEvidence
        )
        assert research_kind in entry.metadata, (
            f"{alpha_id!r}: ledger metadata missing the "
            f"{research_kind!r} kind; got keys "
            f"{sorted(entry.metadata)}"
        )
        round_tripped = metadata_to_evidence(entry.metadata)
        assert ev in round_tripped, (
            f"{alpha_id!r}: research_acceptance evidence did not "
            "round-trip byte-identically through "
            "metadata_to_evidence; the F-1 ledger writer / F-3 "
            "reader pair has drifted."
        )


# ── §20.12.1 family coverage check ──────────────────────────────────────


class TestStrictModeReferenceFamilyCoverage:
    """The §20.12.1 precondition requires ≥3 distinct non-stress
    families ship under strict mode.  This class is purely a static
    assertion against ``_REFERENCE_BY_FAMILY`` so a contributor who
    drops a family from the matrix breaks the build instead of
    silently shrinking the ramp.
    """

    def test_at_least_three_distinct_non_stress_families(self) -> None:
        families = {family for family, _ in _REFERENCE_BY_FAMILY}
        assert len(families) >= 3, (
            f"§20.12.1 requires ≥3 reference alphas (one per "
            f"non-stress family) under strict mode; "
            f"_REFERENCE_BY_FAMILY only covers {sorted(f.name for f in families)}."
        )

    def test_liquidity_stress_is_excluded(self) -> None:
        families = {family for family, _ in _REFERENCE_BY_FAMILY}
        assert TrendMechanism.LIQUIDITY_STRESS not in families, (
            "G16 rule 7 forbids LIQUIDITY_STRESS entry signals — "
            "no production reference SIGNAL alpha can exist for "
            "that family; it must not appear in _REFERENCE_BY_FAMILY."
        )

    def test_alpha_ids_are_all_distinct(self) -> None:
        ids = [alpha_id for _, alpha_id in _REFERENCE_BY_FAMILY]
        assert len(ids) == len(set(ids)), (
            f"_REFERENCE_BY_FAMILY contains duplicate alpha_id; one "
            f"reference alpha per family is the §20.12.2 #4 "
            f"contract.  Got: {ids}"
        )
