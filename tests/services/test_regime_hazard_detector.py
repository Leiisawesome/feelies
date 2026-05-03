"""Unit tests for :mod:`feelies.services.regime_hazard_detector`.

Covers §20.3.1 + §20.7.3 contract:

* Cold-start (``prev=None``) ⇒ no spike.
* No decay (``p_now >= p_prev``) ⇒ no spike.
* Decay above the dominance floor and not flipped ⇒ no spike.
* Decay through the floor ⇒ spike with correct ``hazard_score``.
* Dominant flip even with mild decay ⇒ spike.
* Suppression: at most one spike per
  ``(symbol, engine_name, departing_state)`` transition.
* Re-arming when a different state becomes dominant.
* Cross-channel safety (different symbol / engine_name pairs).
* Contract validation (``HazardDetectorContractError``).
* ``incoming_state`` selection, including the tied-runners-up case.
* The pure ``detect()`` form mirrors the stateful detector.
"""

from __future__ import annotations

import pytest

from feelies.core.events import RegimeState
from feelies.services.regime_hazard_detector import (
    DEFAULT_HYSTERESIS_THRESHOLD,
    HazardDetectorContractError,
    RegimeHazardDetector,
    detect,
)


_STATE_NAMES = ("compression", "normal", "vol_breakout")


def _state(
    *,
    posteriors: tuple[float, float, float],
    dominant_idx: int | None = None,
    sequence: int = 0,
    timestamp_ns: int = 1_000,
    correlation_id: str = "corr-1",
    symbol: str = "AAPL",
    engine_name: str = "HMM3StateFractional",
) -> RegimeState:
    if dominant_idx is None:
        dominant_idx = max(range(3), key=lambda i: posteriors[i])
    return RegimeState(
        timestamp_ns=timestamp_ns,
        correlation_id=correlation_id,
        sequence=sequence,
        symbol=symbol,
        engine_name=engine_name,
        state_names=_STATE_NAMES,
        posteriors=posteriors,
        dominant_state=dominant_idx,
        dominant_name=_STATE_NAMES[dominant_idx],
    )


class TestColdStart:
    def test_prev_none_returns_none(self) -> None:
        det = RegimeHazardDetector()
        spike = det.detect(None, _state(posteriors=(0.1, 0.8, 0.1)))
        assert spike is None


class TestNoDecay:
    def test_p_now_equal_to_p_prev_no_spike(self) -> None:
        det = RegimeHazardDetector()
        prev = _state(posteriors=(0.1, 0.8, 0.1), sequence=0)
        curr = _state(posteriors=(0.1, 0.8, 0.1), sequence=1)
        assert det.detect(prev, curr) is None

    def test_p_now_increasing_no_spike(self) -> None:
        det = RegimeHazardDetector()
        prev = _state(posteriors=(0.1, 0.7, 0.2), sequence=0)
        curr = _state(posteriors=(0.05, 0.85, 0.10), sequence=1)
        assert det.detect(prev, curr) is None


class TestMildDecayNoFlip:
    def test_above_floor_no_flip_no_spike(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        curr = _state(posteriors=(0.10, 0.85, 0.05), sequence=1)
        assert curr.dominant_state == prev.dominant_state
        assert det.detect(prev, curr) is None


class TestSpikeOnDecayThroughFloor:
    def test_drop_below_floor_emits_spike(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        curr = _state(
            posteriors=(0.40, 0.55, 0.05),
            dominant_idx=1,
            sequence=1,
        )
        spike = det.detect(prev, curr)
        assert spike is not None
        assert spike.departing_state == "normal"
        assert spike.departing_posterior_prev == pytest.approx(0.95)
        assert spike.departing_posterior_now == pytest.approx(0.55)
        expected_score = (0.95 - 0.55) / 0.95
        assert spike.hazard_score == pytest.approx(expected_score, rel=1e-9)
        assert spike.incoming_state == "compression"

    def test_drop_above_threshold_score_clipped_to_one(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.0, 0.99, 0.01), sequence=0)
        curr = _state(
            posteriors=(0.5, 0.0, 0.5),
            dominant_idx=0,
            sequence=1,
        )
        spike = det.detect(prev, curr)
        assert spike is not None
        assert spike.hazard_score == pytest.approx(1.0, abs=1e-9)


class TestSpikeOnDominantFlip:
    def test_flip_even_with_mild_decay_emits_spike(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.30, 0.45, 0.25), sequence=0)
        curr = _state(
            posteriors=(0.40, 0.40, 0.20),
            dominant_idx=0,
            sequence=1,
        )
        spike = det.detect(prev, curr)
        assert spike is not None
        assert spike.departing_state == "normal"
        assert spike.incoming_state == "compression"


class TestSuppression:
    def test_only_one_spike_per_transition(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        first = _state(
            posteriors=(0.40, 0.55, 0.05),
            dominant_idx=1,
            sequence=1,
        )
        second = _state(
            posteriors=(0.50, 0.45, 0.05),
            dominant_idx=0,
            sequence=2,
        )
        assert det.detect(prev, first) is not None
        assert det.detect(first, second) is None

    def test_re_arms_when_departure_episode_resolves(self) -> None:
        """A spike can fire again once the departed state's posterior
        recovers above the dominance floor (the wobble has resolved).
        """
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        s0 = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        s1 = _state(
            posteriors=(0.45, 0.55, 0.0),
            dominant_idx=1,
            sequence=1,
        )
        s2 = _state(
            posteriors=(0.49, 0.51, 0.0),
            dominant_idx=1,
            sequence=2,
        )
        s3 = _state(
            posteriors=(0.05, 0.95, 0.0),
            dominant_idx=1,
            sequence=3,
        )
        s4 = _state(
            posteriors=(0.45, 0.55, 0.0),
            dominant_idx=1,
            sequence=4,
        )
        spike1 = det.detect(s0, s1)
        spike2 = det.detect(s1, s2)
        spike3 = det.detect(s2, s3)
        spike4 = det.detect(s3, s4)
        assert spike1 is not None and spike1.departing_state == "normal"
        assert spike2 is None
        assert spike3 is None
        assert spike4 is not None and spike4.departing_state == "normal"


class TestCrossChannelIsolation:
    def test_different_symbol_independent_suppression(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev_a = _state(posteriors=(0.05, 0.95, 0.0), symbol="AAPL", sequence=0)
        curr_a = _state(
            posteriors=(0.40, 0.55, 0.05),
            symbol="AAPL",
            dominant_idx=1,
            sequence=1,
        )
        prev_b = _state(posteriors=(0.05, 0.95, 0.0), symbol="MSFT", sequence=0)
        curr_b = _state(
            posteriors=(0.40, 0.55, 0.05),
            symbol="MSFT",
            dominant_idx=1,
            sequence=1,
        )
        assert det.detect(prev_a, curr_a) is not None
        assert det.detect(prev_b, curr_b) is not None


class TestContractValidation:
    def test_symbol_mismatch_raises(self) -> None:
        det = RegimeHazardDetector()
        prev = _state(posteriors=(0.0, 1.0, 0.0), symbol="AAPL", sequence=0)
        curr = _state(posteriors=(0.0, 1.0, 0.0), symbol="MSFT", sequence=1)
        with pytest.raises(HazardDetectorContractError):
            det.detect(prev, curr)

    def test_engine_mismatch_raises(self) -> None:
        det = RegimeHazardDetector()
        prev = _state(posteriors=(0.0, 1.0, 0.0), engine_name="A", sequence=0)
        curr = _state(posteriors=(0.0, 1.0, 0.0), engine_name="B", sequence=1)
        with pytest.raises(HazardDetectorContractError):
            det.detect(prev, curr)

    def test_dominant_index_name_mismatch_raises(self) -> None:
        """Producers must publish self-consistent dominance fields."""
        det = RegimeHazardDetector()
        # Hand-build a RegimeState whose dominant_state and
        # dominant_name disagree.  The dataclass is frozen so we
        # construct it directly rather than via _state().
        prev = RegimeState(
            timestamp_ns=1_000,
            correlation_id="corr-1",
            sequence=0,
            symbol="AAPL",
            engine_name="HMM3StateFractional",
            state_names=_STATE_NAMES,
            posteriors=(0.05, 0.95, 0.0),
            dominant_state=1,
            dominant_name="vol_breakout",  # mismatch — should be "normal"
        )
        curr = _state(posteriors=(0.4, 0.55, 0.05), dominant_idx=1, sequence=1)
        with pytest.raises(HazardDetectorContractError, match="dominant_name"):
            det.detect(prev, curr)

    def test_dominant_index_out_of_range_raises(self) -> None:
        det = RegimeHazardDetector()
        prev = RegimeState(
            timestamp_ns=1_000,
            correlation_id="corr-1",
            sequence=0,
            symbol="AAPL",
            engine_name="HMM3StateFractional",
            state_names=_STATE_NAMES,
            posteriors=(0.05, 0.95, 0.0),
            dominant_state=99,
            dominant_name="normal",
        )
        curr = _state(posteriors=(0.4, 0.55, 0.05), dominant_idx=1, sequence=1)
        with pytest.raises(HazardDetectorContractError, match="out of range"):
            det.detect(prev, curr)

    def test_posteriors_state_names_length_mismatch_raises(self) -> None:
        det = RegimeHazardDetector()
        prev = RegimeState(
            timestamp_ns=1_000,
            correlation_id="corr-1",
            sequence=0,
            symbol="AAPL",
            engine_name="HMM3StateFractional",
            state_names=("a", "b"),  # 2 names
            posteriors=(0.5, 0.3, 0.2),  # 3 posteriors
            dominant_state=0,
            dominant_name="a",
        )
        curr = RegimeState(
            timestamp_ns=2_000,
            correlation_id="corr-2",
            sequence=1,
            symbol="AAPL",
            engine_name="HMM3StateFractional",
            state_names=("a", "b"),
            posteriors=(0.4, 0.4, 0.2),
            dominant_state=0,
            dominant_name="a",
        )
        with pytest.raises(HazardDetectorContractError, match="equal"):
            det.detect(prev, curr)


class TestIncomingState:
    def test_tied_runners_up_returns_none_incoming(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        curr = _state(
            posteriors=(0.30, 0.40, 0.30),
            dominant_idx=1,
            sequence=1,
        )
        spike = det.detect(prev, curr)
        assert spike is not None
        assert spike.departing_state == "normal"
        assert spike.incoming_state is None


class TestPureDetect:
    def test_pure_detect_matches_stateful(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        curr = _state(
            posteriors=(0.40, 0.55, 0.05),
            dominant_idx=1,
            sequence=1,
        )
        stateful = det.detect(prev, curr)
        pure = detect(prev, curr, hysteresis_threshold=0.30)
        assert stateful is not None
        assert pure is not None
        assert stateful.symbol == pure.symbol
        assert stateful.departing_state == pure.departing_state
        assert stateful.hazard_score == pytest.approx(pure.hazard_score)
        assert stateful.incoming_state == pure.incoming_state

    def test_pure_detect_suppression_via_external_set(self) -> None:
        suppressed: set[tuple[str, str, str]] = set()
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        c1 = _state(
            posteriors=(0.40, 0.55, 0.05),
            dominant_idx=1,
            sequence=1,
        )
        c2 = _state(
            posteriors=(0.50, 0.45, 0.05),
            dominant_idx=0,
            sequence=2,
        )
        s1 = detect(prev, c1, suppressed=suppressed)
        s2 = detect(c1, c2, suppressed=suppressed)
        assert s1 is not None
        assert s2 is None


class TestReset:
    def test_reset_clears_suppression(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), sequence=0)
        curr = _state(
            posteriors=(0.40, 0.55, 0.05),
            dominant_idx=1,
            sequence=1,
        )
        assert det.detect(prev, curr) is not None
        assert det.detect(prev, curr) is None
        det.reset()
        assert det.detect(prev, curr) is not None


class TestThresholdValidation:
    @pytest.mark.parametrize("threshold", [0.0, 1.0, -0.1, 1.5])
    def test_invalid_threshold_raises(self, threshold: float) -> None:
        with pytest.raises(ValueError):
            RegimeHazardDetector(hysteresis_threshold=threshold)


def test_default_threshold_constant_matches_module() -> None:
    det = RegimeHazardDetector()
    assert det.hysteresis_threshold == DEFAULT_HYSTERESIS_THRESHOLD
