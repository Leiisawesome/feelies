"""End-to-end research → promotion integration suite — Workstream **C-3**.

This is the workstream-closing milestone for Workstream C: it
proves the C-1 (CPCV) and C-2 (DSR) builders work in concert with
the F-2 gate matrix, the F-4 ``AlphaLifecycle.promote_*(structured_evidence=...)``
path, the F-1 promotion ledger, and the F-3 ``feelies promote
replay-evidence`` operator CLI — all driven by **synthetic OOS
return data** rather than hand-rolled evidence numbers.

Coverage summary
================

- :class:`TestStrongAlphaPipeline` — happy path:

    1. Synthesise a strong-alpha 240-bar daily-return series with a
       seeded ``random.Random``.
    2. Compute :class:`CPCVEvidence` via
       :func:`build_cpcv_evidence` against the series.
    3. Compute :class:`DSREvidence` via
       :func:`build_dsr_evidence_from_returns` against the same
       series.
    4. Walk the alpha through ``RESEARCH → PAPER → LIVE`` using the
       computed evidence (plus a hand-rolled
       :class:`ResearchAcceptanceEvidence` for the
       ``RESEARCH_TO_PAPER`` gate and a hand-rolled
       :class:`PaperWindowEvidence` for the ``PAPER_TO_LIVE`` gate).
    5. Verify the promotion ledger contains both transitions, every
       computed evidence dataclass round-trips byte-for-byte through
       :func:`metadata_to_evidence`, and the F-3 ``feelies promote
       replay-evidence`` CLI re-validates every entry as ``OK``.

- :class:`TestWeakAlphaPipeline` — negative paths driven by data:
  a low-Sharpe synthetic return series produces CPCV / DSR
  evidence that *organically* fails the gate (no fudged numbers).

- :class:`TestPipelineDeterminism` — Inv-5: two pipeline runs on
  the same seeded return series produce bit-identical evidence
  *and* bit-identical ledger metadata payloads.

These tests deliberately do not exercise the underlying CPCV /
DSR math (covered exhaustively in the C-1 / C-2 unit / property /
reference suites) — they verify that valid evidence flows
end-to-end through the promotion pipeline without integration
seams.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from pathlib import Path

import pytest

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
)
from feelies.alpha.promotion_evidence import (
    CPCVEvidence,
    DSREvidence,
    EVIDENCE_SCHEMA_VERSION,
    PaperWindowEvidence,
    ResearchAcceptanceEvidence,
    metadata_to_evidence,
)
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.cli.main import EXIT_OK, main as cli_main
from feelies.core.clock import SimulatedClock
from feelies.research.cpcv import (
    CPCVConfig,
    build_cpcv_evidence,
    generate_cpcv_splits,
)
from feelies.research.dsr import build_dsr_evidence_from_returns


# ─────────────────────────────────────────────────────────────────────
#   Shared deterministic synthetic-return generators
# ─────────────────────────────────────────────────────────────────────


def _strong_alpha_returns(seed: int = 42, n_bars: int = 240) -> list[float]:
    """Synthesise a strong-alpha daily-return series.

    With ``μ ≈ 0.005`` and ``σ ≈ 0.005`` the per-day Sharpe is ~1.0
    (annualised ~16) — well above every default CPCV / DSR
    threshold even after deflation by 50–100 trials.  Seeded so the
    series is bit-identical across runs and hosts (Inv-5).
    """
    rng = random.Random(seed)
    return [rng.gauss(0.005, 0.005) for _ in range(n_bars)]


def _weak_alpha_returns(seed: int = 7, n_bars: int = 240) -> list[float]:
    """Synthesise a weak-alpha daily-return series.

    With ``μ ≈ 0.0001`` and ``σ ≈ 0.005`` the per-day Sharpe is ~0.02
    (annualised ~0.32) — below the default ``cpcv_min_mean_sharpe =
    1.0`` threshold and below the default ``dsr_min = 1.0``
    falsification floor.
    """
    rng = random.Random(seed)
    return [rng.gauss(0.0001, 0.005) for _ in range(n_bars)]


def _identity_test_returns_by_split(
    *,
    returns: Sequence[float],
    config: CPCVConfig,
) -> list[list[float]]:
    """Project a single return series into the per-split OOS shape.

    Stand-in for the "train then predict" step: the synthetic model
    perfectly forecasts the realised return, so ``test_returns[s][i]
    = returns[splits[s].test_indices[i]]`` for every split ``s``
    and every position ``i``.  This isolates the integration test
    from any ML training and exercises only the CPCV scaffolding.
    """
    splits = generate_cpcv_splits(len(returns), config)
    return [[returns[i] for i in split.test_indices] for split in splits]


def _build_cpcv_from_returns(
    returns: Sequence[float],
    *,
    n_groups: int = 10,
    k_test_groups: int = 2,
    embargo_bars: int = 5,
    seed: int = 0,
    n_bootstrap: int = 1_000,
) -> CPCVEvidence:
    """Convenience wrapper around :func:`build_cpcv_evidence` with
    the identity-model OOS projection helper above.

    Default hyperparameters (``n_groups=10, k_test_groups=2,
    embargo_bars=5``) produce ``C(9, 1) = 9`` reconstructed paths,
    just above the platform default ``cpcv_min_folds = 8``.

    Uses ``n_bootstrap = 1_000`` (not the platform default 10_000)
    for test-suite speed; the bootstrap p-value's behaviour is
    deterministically locked at every count by the C-1 reference
    suite, so 1_000 is sufficient for the integration check here.
    """
    config = CPCVConfig(
        n_groups=n_groups,
        k_test_groups=k_test_groups,
        embargo_bars=embargo_bars,
    )
    test_returns_by_split = _identity_test_returns_by_split(
        returns=returns, config=config
    )
    return build_cpcv_evidence(
        config=config,
        n_bars=len(returns),
        test_returns_by_split=test_returns_by_split,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )


def _build_dsr_from_returns(
    returns: Sequence[float],
    *,
    trials_count: int = 50,
) -> DSREvidence:
    """Convenience wrapper around
    :func:`build_dsr_evidence_from_returns` with annualisation
    factor pinned to ``sqrt(252)`` — the per-day → per-year
    convention the F-2 ``GateThresholds`` defaults are anchored
    against.
    """
    return build_dsr_evidence_from_returns(
        returns=returns,
        trials_count=trials_count,
        annualization_factor=math.sqrt(252),
    )


def _passing_research_acceptance() -> ResearchAcceptanceEvidence:
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


def _passing_paper_window() -> PaperWindowEvidence:
    return PaperWindowEvidence(
        trading_days=10,
        sample_size=400,
        slippage_residual_bps=0.7,
        fill_rate_drift_pct=2.0,
        latency_ks_p=0.5,
        pnl_compression_ratio=0.85,
        anomalous_event_count=0,
    )


def _make_lifecycle(
    *, ledger: PromotionLedger | None = None
) -> AlphaLifecycle:
    clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
    return AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)


# ─────────────────────────────────────────────────────────────────────
#   Strong-alpha happy path
# ─────────────────────────────────────────────────────────────────────


class TestStrongAlphaPipeline:
    """End-to-end research → promotion happy path.

    The strong-alpha synthetic return series produces CPCV and DSR
    evidence well above the default ``GateThresholds``, so both
    transitions land in their target states and the ledger captures
    every committed evidence dataclass round-trippably.
    """

    def test_strong_alpha_cpcv_passes_default_thresholds(self) -> None:
        # Sanity: confirm the synthetic returns are actually strong
        # enough that the C-1 evidence clears every CPCV threshold.
        # Drift in the synthetic generator (or in CPCV defaults)
        # will surface here before it cascades into the lifecycle
        # tests below.
        returns = _strong_alpha_returns()
        cpcv = _build_cpcv_from_returns(returns)
        assert cpcv.fold_count >= 8
        assert cpcv.mean_sharpe >= 1.0
        assert cpcv.p_value <= 0.05

    def test_strong_alpha_dsr_passes_default_thresholds(self) -> None:
        # Sanity: same for the C-2 evidence.
        returns = _strong_alpha_returns()
        dsr = _build_dsr_from_returns(returns)
        assert dsr.dsr >= 1.0
        assert dsr.dsr_p_value <= 0.05
        assert dsr.trials_count > 0

    def test_research_to_paper_transitions_with_research_acceptance(
        self,
    ) -> None:
        lc = _make_lifecycle()
        errors = lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()],
        )
        assert errors == []
        assert lc.state is AlphaLifecycleState.PAPER

    def test_paper_to_live_transitions_with_computed_cpcv_and_dsr(
        self,
    ) -> None:
        # The end-to-end milestone: synthetic returns drive C-1 +
        # C-2 evidence which drive F-4 ``promote_to_live`` against
        # the F-2 gate matrix.  No hand-rolled evidence numbers in
        # the path that matters.
        returns = _strong_alpha_returns()
        cpcv = _build_cpcv_from_returns(returns)
        dsr = _build_dsr_from_returns(returns)

        lc = _make_lifecycle()
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        errors = lc.promote_to_live(
            structured_evidence=[_passing_paper_window(), cpcv, dsr],
        )
        assert errors == [], f"gate rejected strong alpha: {errors}"
        assert lc.state is AlphaLifecycleState.LIVE

    def test_paper_to_live_ledger_round_trips_computed_evidence(
        self, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        lc = _make_lifecycle(ledger=ledger)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )

        returns = _strong_alpha_returns()
        cpcv = _build_cpcv_from_returns(returns)
        dsr = _build_dsr_from_returns(returns)
        paper = _passing_paper_window()
        lc.promote_to_live(structured_evidence=[paper, cpcv, dsr])

        entries = list(ledger.entries())
        assert len(entries) == 2
        assert (entries[0].from_state, entries[0].to_state) == (
            "RESEARCH",
            "PAPER",
        )
        assert (entries[1].from_state, entries[1].to_state) == (
            "PAPER",
            "LIVE",
        )

        live_entry = entries[1]
        assert live_entry.metadata["schema_version"] == EVIDENCE_SCHEMA_VERSION

        reconstructed = metadata_to_evidence(live_entry.metadata)
        by_kind = {type(e).__name__: e for e in reconstructed}
        assert set(by_kind) == {
            "PaperWindowEvidence",
            "CPCVEvidence",
            "DSREvidence",
        }
        # Every reconstructed evidence dataclass is byte-identical
        # to what we submitted — the F-2 metadata round-trip is
        # lossless.
        assert by_kind["CPCVEvidence"] == cpcv
        assert by_kind["DSREvidence"] == dsr
        assert by_kind["PaperWindowEvidence"] == paper

    def test_cli_replay_evidence_reports_ok_for_strong_alpha(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Round out the integration loop: the F-3 operator CLI must
        # be able to read the ledger this pipeline produced and
        # re-validate every committed evidence package against
        # current ``GateThresholds`` without surfacing any FAIL.
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        lc = _make_lifecycle(ledger=ledger)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        returns = _strong_alpha_returns()
        lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _build_cpcv_from_returns(returns),
                _build_dsr_from_returns(returns),
            ],
        )

        rc = cli_main(
            [
                "promote",
                "replay-evidence",
                "kyle",
                "--ledger",
                str(ledger_path),
            ]
        )
        out = capsys.readouterr().out
        assert rc == EXIT_OK, out
        # Every transition must report OK (no SKIPPED, no FAIL).
        # Both transitions (RESEARCH→PAPER, PAPER→LIVE) carry F-2
        # evidence so neither should be skipped.
        assert out.count("OK") >= 2
        assert "FAIL" not in out
        assert "SKIPPED" not in out

    def test_cli_replay_evidence_json_payload_is_well_formed(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import json

        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        lc = _make_lifecycle(ledger=ledger)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        returns = _strong_alpha_returns()
        lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _build_cpcv_from_returns(returns),
                _build_dsr_from_returns(returns),
            ],
        )

        rc = cli_main(
            [
                "promote",
                "replay-evidence",
                "kyle",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        payload = json.loads(out)
        assert payload["alpha_id"] == "kyle"
        assert len(payload["results"]) == 2
        for result in payload["results"]:
            assert result["ok"] is True
            assert result["errors"] == []


# ─────────────────────────────────────────────────────────────────────
#   Negative paths driven by data
# ─────────────────────────────────────────────────────────────────────


class TestWeakAlphaPipeline:
    """Weak-alpha synthetic returns must *organically* fail the
    PAPER→LIVE gate — no hand-rolled "bad" evidence numbers.

    The weak-alpha series has per-day Sharpe ~ 0.02 (annualised
    ~ 0.32), well below every default ``GateThresholds``.  The
    CPCV and DSR builders see exactly the same series the strong-
    alpha tests above use, so this is a true integration check
    that the threshold logic fires on real data.
    """

    def test_weak_alpha_cpcv_fails_default_gate(self) -> None:
        # Sanity: confirm the weak series does not clear the C-1
        # defaults.  If this slips, the gate-rejection test below
        # would falsely look like success.
        returns = _weak_alpha_returns()
        cpcv = _build_cpcv_from_returns(returns)
        assert cpcv.mean_sharpe < 1.0

    def test_weak_alpha_dsr_fails_default_gate(self) -> None:
        returns = _weak_alpha_returns()
        dsr = _build_dsr_from_returns(returns)
        assert dsr.dsr < 1.0

    def test_paper_to_live_blocked_by_weak_alpha_evidence(self) -> None:
        # Walk to PAPER, then attempt PAPER → LIVE with computed
        # evidence from the weak series.  Gate must reject and the
        # state machine must stay in PAPER (Inv-11: fail-safe by
        # default).
        lc = _make_lifecycle()
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        returns = _weak_alpha_returns()
        errors = lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _build_cpcv_from_returns(returns),
                _build_dsr_from_returns(returns),
            ],
        )
        assert errors  # at least one threshold violated
        assert lc.state is AlphaLifecycleState.PAPER

    def test_failed_promotion_writes_no_ledger_entry_for_live(
        self, tmp_path: Path
    ) -> None:
        # Inv-13: provenance.  A blocked promotion writes nothing to
        # the ledger past the previous transition.
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        lc = _make_lifecycle(ledger=ledger)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        returns = _weak_alpha_returns()
        lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _build_cpcv_from_returns(returns),
                _build_dsr_from_returns(returns),
            ],
        )
        entries = list(ledger.entries())
        assert len(entries) == 1
        assert (entries[0].from_state, entries[0].to_state) == (
            "RESEARCH",
            "PAPER",
        )

    def test_weak_alpha_blocks_at_paper_to_live_with_cpcv_error(
        self,
    ) -> None:
        # The weak-alpha returns specifically violate the CPCV
        # mean-Sharpe threshold; the gate's joint validator surfaces
        # the CPCV error so an operator triaging the failure can
        # attribute it to the right evidence layer.
        lc = _make_lifecycle()
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        returns = _weak_alpha_returns()
        errors = lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _build_cpcv_from_returns(returns),
                _build_dsr_from_returns(returns),
            ],
        )
        assert any("CPCV" in e for e in errors)
        assert lc.state is AlphaLifecycleState.PAPER


# ─────────────────────────────────────────────────────────────────────
#   Determinism (Inv-5)
# ─────────────────────────────────────────────────────────────────────


class TestPipelineDeterminism:
    """Inv-5: same event log + parameters → bit-identical signals,
    orders, PnL.  At the research layer, this means: same return
    series + same hyperparameters → bit-identical evidence
    dataclasses → bit-identical ledger metadata payloads.
    """

    def test_cpcv_evidence_is_bit_identical_across_runs(self) -> None:
        returns = _strong_alpha_returns()
        cpcv1 = _build_cpcv_from_returns(returns)
        cpcv2 = _build_cpcv_from_returns(returns)
        assert cpcv1 == cpcv2

    def test_dsr_evidence_is_bit_identical_across_runs(self) -> None:
        returns = _strong_alpha_returns()
        dsr1 = _build_dsr_from_returns(returns)
        dsr2 = _build_dsr_from_returns(returns)
        assert dsr1 == dsr2

    def test_ledger_metadata_round_trip_is_bit_identical(
        self, tmp_path: Path
    ) -> None:
        # Two full pipeline runs against separate ledgers must
        # produce metadata payloads that — when round-tripped back
        # through ``metadata_to_evidence`` — yield identical evidence
        # dataclasses.  (The ledger entry envelopes themselves carry
        # different timestamps and possibly different correlation
        # IDs, so we compare the metadata content, not the entry
        # bytes.)
        def _run(ledger_path: Path) -> tuple[CPCVEvidence, DSREvidence]:
            ledger = PromotionLedger(ledger_path)
            lc = _make_lifecycle(ledger=ledger)
            lc.promote_to_paper(
                structured_evidence=[_passing_research_acceptance()]
            )
            returns = _strong_alpha_returns()
            cpcv = _build_cpcv_from_returns(returns)
            dsr = _build_dsr_from_returns(returns)
            lc.promote_to_live(
                structured_evidence=[_passing_paper_window(), cpcv, dsr],
            )
            entries = list(ledger.entries())
            reconstructed = metadata_to_evidence(entries[1].metadata)
            by_kind = {type(e).__name__: e for e in reconstructed}
            return (
                _expect_cpcv(by_kind["CPCVEvidence"]),
                _expect_dsr(by_kind["DSREvidence"]),
            )

        cpcv_a, dsr_a = _run(tmp_path / "a.jsonl")
        cpcv_b, dsr_b = _run(tmp_path / "b.jsonl")
        assert cpcv_a == cpcv_b
        assert dsr_a == dsr_b

    def test_distinct_returns_produce_distinct_evidence(self) -> None:
        # Counter-evidence: a *different* return series (different
        # synthetic seed) must produce different CPCV and DSR
        # evidence — the pipeline truly consumes the input series
        # and is not silently constant.  We deliberately do not
        # bootstrap-seed-vary the CPCV here: with the identity-
        # model OOS projection above, all reconstructed paths
        # cover every bar with the same realised return so every
        # path's Sharpe is identical and the bootstrap p-value is
        # degenerate at every seed (a known property of the
        # synthetic test scaffold, exercised by the C-1 reference
        # suite).
        a = _strong_alpha_returns(seed=42)
        b = _strong_alpha_returns(seed=43)
        assert _build_cpcv_from_returns(a) != _build_cpcv_from_returns(b)
        assert _build_dsr_from_returns(a) != _build_dsr_from_returns(b)


# Helper functions for narrowing reconstructed evidence types in the
# determinism test above; keeping them at module scope so mypy strict
# can see the cast without a per-call type: ignore.


def _expect_cpcv(obj: object) -> CPCVEvidence:
    assert isinstance(obj, CPCVEvidence)
    return obj


def _expect_dsr(obj: object) -> DSREvidence:
    assert isinstance(obj, DSREvidence)
    return obj
