"""Verify locked parity manifest matches live replay outputs (BT-11)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.determinism import parity_manifest
from tests.determinism.test_hazard_exit_replay import _replay as hazard_exit_replay
from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
from tests.determinism.test_market_fill_replay import _replay as market_fill_replay
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
    "market_fill_acks": market_fill_replay,
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


# ── Completeness: no locked baseline may silently escape the registry ───

_DETERMINISM_DIR = Path(__file__).resolve().parent

# Locked ``EXPECTED_*_HASH`` constants intentionally *not* in the manifest,
# each with the reason.  Anything else defining such a constant must be
# wired into LOCKED_PARITY_BASELINES + _REPLAY_BY_NAME.
_UNREGISTERED_HASH_EXEMPTIONS: dict[str, str] = {
    # cvxpy/ECOS solver path is skipped unless the [portfolio] extra is
    # installed, so it cannot be a mandatory manifest entry (the manifest
    # self-test must run without cvxpy).  Locked + guarded locally in
    # tests/determinism/test_sized_intent_solver_replay.py.
    "EXPECTED_LEVEL3_SOLVER_HASH": "cvxpy-conditional baseline (test_sized_intent_solver_replay.py)",
}


def test_replay_map_matches_manifest_keys() -> None:
    """``_REPLAY_BY_NAME`` and ``LOCKED_PARITY_BASELINES`` cover the same set.

    A baseline registered in the manifest without a wired replay (or a
    replay wired without registration) would make the parametrized
    self-test silently skip it.  Lock the two sets to be identical.
    """
    replay_keys = set(_REPLAY_BY_NAME)
    manifest_keys = set(parity_manifest.LOCKED_PARITY_BASELINES)
    assert replay_keys == manifest_keys, (
        "drift between _REPLAY_BY_NAME and LOCKED_PARITY_BASELINES — "
        f"only in replay map={sorted(replay_keys - manifest_keys)}; "
        f"only in manifest={sorted(manifest_keys - replay_keys)}"
    )


def test_every_locked_hash_is_registered_or_exempt() -> None:
    """No locked ``EXPECTED_*_HASH`` may escape the manifest unnoticed.

    Audit P1: the old self-test only iterated the manifest, so a new
    ``EXPECTED_*_HASH`` added to a determinism module but never registered
    in LOCKED_PARITY_BASELINES was silently uncovered (how the market-fill
    and solver baselines started out).  Scan the determinism package for
    locked-hash constants and assert each is either referenced by the
    manifest or explicitly exempted above.
    """
    manifest_src = (_DETERMINISM_DIR / "parity_manifest.py").read_text(encoding="utf-8")
    const_re = re.compile(r"^(EXPECTED_\w*_HASH)\b", re.MULTILINE)

    unregistered: list[str] = []
    for path in sorted(_DETERMINISM_DIR.glob("test_*replay*.py")):
        for const in const_re.findall(path.read_text(encoding="utf-8")):
            if re.search(rf"\b{re.escape(const)}\b", manifest_src):
                continue  # imported / referenced by the manifest
            if const in _UNREGISTERED_HASH_EXEMPTIONS:
                continue
            unregistered.append(f"{const} ({path.name})")

    assert not unregistered, (
        "locked parity hashes neither registered in parity_manifest.py nor "
        f"exempted: {unregistered}.  Add them to LOCKED_PARITY_BASELINES + "
        "_REPLAY_BY_NAME, or to _UNREGISTERED_HASH_EXEMPTIONS with a reason."
    )
