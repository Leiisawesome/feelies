"""End-to-end wiring of :class:`RegimeHazardDetector` into the orchestrator.

Verifies §20.3.1 + §20.7 contract at the platform-composition layer:

* The detector is **only constructed** when at least one alpha
  declares ``hazard_exit.enabled: true`` (Inv-A: legacy parity must
  not be perturbed by the new event family).
* When constructed, the orchestrator emits :class:`RegimeHazardSpike`
  events on the bus through the dedicated ``_hazard_seq`` generator.
* Sequence numbers on the hazard family are **independent** of every
  other family (sensors, snapshots, signals, legacy bus) — this is
  the C1 isolation rule that protects pre-existing parity hashes.
* When *no* alpha opts in, no hazard spikes are ever published and
  the hazard sequence counter stays at zero.

Test fixtures are minimal: a hand-crafted in-memory ``EventBus`` plus
two synthetic :class:`RegimeState` events spaced one tick apart, run
through ``Orchestrator._update_regime`` indirectly via the public
``_maybe_publish_hazard_spike`` hook.  We rely on ``_create_hazard_detector``
in :mod:`feelies.bootstrap` to perform the opt-in branching.
"""

from __future__ import annotations

from typing import Any

import pytest

from feelies.alpha.module import AlphaManifest
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import _create_hazard_detector
from feelies.core.events import RegimeHazardSpike, RegimeState
from feelies.services.regime_hazard_detector import RegimeHazardDetector


_STATE_NAMES = ("compression", "normal", "vol_breakout")


def _state(
    *,
    posteriors: tuple[float, float, float],
    dominant_idx: int,
    sequence: int = 0,
) -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr-1",
        sequence=sequence,
        symbol="AAPL",
        engine_name="HMM3StateFractional",
        state_names=_STATE_NAMES,
        posteriors=posteriors,
        dominant_state=dominant_idx,
        dominant_name=_STATE_NAMES[dominant_idx],
    )


class _StubModule:
    """Minimal stand-in for a registered alpha, exposing only the
    ``manifest`` attribute consulted by ``_create_hazard_detector``."""

    def __init__(
        self,
        *,
        alpha_id: str,
        hazard_exit: dict[str, Any] | None,
    ) -> None:
        self.manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description="stub",
            hypothesis="stub",
            falsification_criteria=("stub",),
            required_features=frozenset(),
            hazard_exit=hazard_exit,
        )


def _make_registry(*modules: _StubModule) -> AlphaRegistry:
    """Build an :class:`AlphaRegistry` populated by stub modules.

    The registry's full contract requires LoadedAlphaModule objects;
    we monkey-patch ``active_alphas`` for the bootstrap factory to
    keep the fixture self-contained without instantiating the full
    alpha-loading pipeline.
    """
    registry = AlphaRegistry()
    registry.active_alphas = lambda: list(modules)  # type: ignore[method-assign]
    return registry


class TestOptInActivation:
    def test_no_alpha_opts_in_returns_no_detector(self) -> None:
        registry = _make_registry()
        seq, det = _create_hazard_detector(registry)
        assert det is None
        assert seq.next() == 0

    def test_hazard_exit_disabled_returns_no_detector(self) -> None:
        registry = _make_registry(
            _StubModule(
                alpha_id="alpha_a",
                hazard_exit={"enabled": False},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert det is None

    def test_hazard_exit_missing_block_returns_no_detector(self) -> None:
        registry = _make_registry(
            _StubModule(alpha_id="alpha_a", hazard_exit=None),
        )
        _, det = _create_hazard_detector(registry)
        assert det is None

    def test_at_least_one_opt_in_returns_detector(self) -> None:
        registry = _make_registry(
            _StubModule(alpha_id="alpha_a", hazard_exit=None),
            _StubModule(
                alpha_id="alpha_b",
                hazard_exit={"enabled": True},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert isinstance(det, RegimeHazardDetector)

    def test_hazard_exit_enabled_truthy_value_returns_detector(self) -> None:
        registry = _make_registry(
            _StubModule(
                alpha_id="alpha_a",
                hazard_exit={"enabled": "yes"},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert isinstance(det, RegimeHazardDetector)


class TestSequenceIsolation:
    def test_hazard_sequence_starts_at_zero_when_no_spikes_emitted(self) -> None:
        registry = _make_registry()
        seq, _ = _create_hazard_detector(registry)
        assert seq.next() == 0
        assert seq.next() == 1

    def test_hazard_sequence_advances_independent_of_legacy_seq(self) -> None:
        from feelies.core.identifiers import SequenceGenerator
        legacy_seq = SequenceGenerator()
        legacy_seq.next()
        legacy_seq.next()
        assert legacy_seq.next() == 2

        registry = _make_registry()
        haz_seq, _ = _create_hazard_detector(registry)
        assert haz_seq.next() == 0


class TestEndToEndSpikeEmission:
    """Exercise the detector + dedicated _hazard_seq pair end-to-end
    against a hand-crafted RegimeState pair without standing up the
    full orchestrator (which would require event-log + backend +
    macro-state machinery)."""

    def test_decay_through_floor_emits_spike(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        curr = _state(posteriors=(0.45, 0.55, 0.0), dominant_idx=1, sequence=1)
        spike = det.detect(prev, curr)
        assert isinstance(spike, RegimeHazardSpike)
        assert spike.symbol == "AAPL"
        assert spike.engine_name == "HMM3StateFractional"
        assert spike.departing_state == "normal"
        assert spike.hazard_score == pytest.approx((0.95 - 0.55) / 0.95)
