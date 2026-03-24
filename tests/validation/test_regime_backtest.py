"""Regime engine integration in backtest tests.

Skills: regime-detection, risk-engine, feature-engine
Invariants: 5 (determinism), 11 (fail-safe)
"""

from __future__ import annotations

import pytest

from feelies.core.events import (
    FeatureVector,
    NBBOQuote,
    OrderRequest,
    RegimeState,
)

from .conftest import BusRecorder, _make_quotes, _run_scenario

pytestmark = pytest.mark.backtest_validation


class TestRegimeBacktest:
    """Regime engine integration within the backtest pipeline."""

    def test_regime_state_published_at_m2_every_tick(self, regime_scenario) -> None:
        _, recorder, _, _ = regime_scenario
        quotes = recorder.of_type(NBBOQuote)
        regime_states = recorder.of_type(RegimeState)

        assert len(regime_states) == len(quotes), (
            f"Expected {len(quotes)} RegimeState events, got {len(regime_states)}"
        )

        event_positions: dict[str, int] = {}
        for i, event in enumerate(recorder.events):
            key = f"{type(event).__name__}:{getattr(event, 'correlation_id', '')}"
            if key not in event_positions:
                event_positions[key] = i

        for rs in regime_states:
            rs_key = f"RegimeState:{rs.correlation_id}"
            fv_key = f"FeatureVector:{rs.correlation_id}"
            if rs_key in event_positions and fv_key in event_positions:
                assert event_positions[rs_key] < event_positions[fv_key], (
                    f"RegimeState should be published before FeatureVector "
                    f"for cid={rs.correlation_id}"
                )

    def test_regime_posteriors_sum_to_one(self, regime_scenario) -> None:
        _, recorder, _, _ = regime_scenario
        for rs in recorder.of_type(RegimeState):
            total = sum(rs.posteriors)
            assert abs(total - 1.0) < 1e-6, (
                f"Posteriors sum to {total}, expected ~1.0"
            )

    def test_regime_scaling_reduces_position_size(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        tmp_no_regime = tmp_path_factory.mktemp("no_regime")
        _, rec_no, _, _ = _run_scenario(tmp_no_regime, regime_engine=None)

        tmp_regime = tmp_path_factory.mktemp("with_regime")
        _, rec_with, _, _ = _run_scenario(
            tmp_regime, regime_engine="hmm_3state_fractional"
        )

        orders_no = rec_no.of_type(OrderRequest)
        orders_with = rec_with.of_type(OrderRequest)

        if orders_no and orders_with:
            qty_no = sum(o.quantity for o in orders_no)
            qty_with = sum(o.quantity for o in orders_with)
            assert qty_with <= qty_no, (
                f"Regime scaling should not increase total quantity: "
                f"without={qty_no}, with={qty_with}"
            )

    def test_no_regime_engine_defaults_neutral(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        tmp = tmp_path_factory.mktemp("no_regime_neutral")
        _, recorder, _, _ = _run_scenario(tmp, regime_engine=None)

        regime_states = recorder.of_type(RegimeState)
        assert len(regime_states) == 0

    def test_regime_deterministic_across_runs(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        results = []
        for i in range(2):
            tmp = tmp_path_factory.mktemp(f"regime_det_{i}")
            _, recorder, _, _ = _run_scenario(
                tmp, regime_engine="hmm_3state_fractional"
            )
            results.append(recorder.of_type(RegimeState))

        assert len(results[0]) == len(results[1])
        for rs_a, rs_b in zip(results[0], results[1]):
            assert rs_a.posteriors == rs_b.posteriors
            assert rs_a.dominant_state == rs_b.dominant_state
            assert rs_a.dominant_name == rs_b.dominant_name
