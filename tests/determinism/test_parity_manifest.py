"""Verify locked parity manifest matches live replay outputs (BT-11)."""

from __future__ import annotations

import pytest

from tests.determinism import parity_manifest
from tests.determinism.test_hazard_exit_replay import _replay as hazard_exit_replay
from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
from tests.determinism.test_portfolio_order_replay import _replay as portfolio_order_replay
from tests.determinism.test_regime_hazard_replay import _replay as regime_hazard_replay
from tests.determinism.test_regime_state_replay import (
    EXPECTED_LEVEL6_REGIME_STATE_COUNT,
    _drive_regime_states,
    _hash_regime_stream,
)
from tests.determinism.test_sensor_reading_replay import _replay as sensor_replay
from tests.determinism.test_signal_replay import _replay as signal_replay
from tests.determinism.test_sized_intent_replay import _replay as intent_replay
from tests.determinism.test_v03_sensor_replay import _replay as v03_sensor_replay
from tests.fixtures.replay import (
    hash_horizon_tick_stream,
    replay_quotes_through_scheduler,
)


def _replay_horizon_tick() -> tuple[str, int]:
    ticks, _ = replay_quotes_through_scheduler()
    return hash_horizon_tick_stream(ticks), len(ticks)


def _replay_regime_state() -> tuple[str, int]:
    states = _drive_regime_states()
    return _hash_regime_stream(states), len(states)


_REPLAY_BY_NAME = {
    "level1_sensor_reading": sensor_replay,
    "level1_v03_sensor_reading": v03_sensor_replay,
    "level2_horizon_tick": _replay_horizon_tick,
    "level2_signal": signal_replay,
    "level3_horizon_feature_snapshot": snapshot_replay,
    "level3_sized_intent_decay_off": lambda: intent_replay(decay=False),
    "level3_sized_intent_decay_on": lambda: intent_replay(decay=True),
    "level4_portfolio_order": portfolio_order_replay,
    "level4_hazard_exit_order": hazard_exit_replay,
    "level5_regime_hazard_spike": regime_hazard_replay,
    "level6_regime_state": _replay_regime_state,
}


@pytest.mark.parametrize(
    "name",
    list(parity_manifest.LOCKED_PARITY_BASELINES.keys()),
    ids=list(parity_manifest.LOCKED_PARITY_BASELINES.keys()),
)
def test_manifest_entry_matches_replay(name: str) -> None:
    expected = parity_manifest.LOCKED_PARITY_BASELINES[name]
    actual = _REPLAY_BY_NAME[name]()
    assert actual == expected, (
        f"manifest drift for {name!r}: locked {expected}, replay produced {actual}"
    )


def test_regime_state_count_matches_manifest() -> None:
    assert _replay_regime_state()[1] == EXPECTED_LEVEL6_REGIME_STATE_COUNT
