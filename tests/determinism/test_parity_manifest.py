"""Verify the locked parity manifest against live replay outputs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.determinism import parity_manifest
from tests.determinism.test_cross_sectional_context_replay import _replay as xsect_context_replay
from tests.determinism.test_hazard_exit_replay import _replay as hazard_exit_replay
from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
from tests.determinism.test_market_fill_replay import _replay as market_fill_replay
from tests.determinism.test_multi_symbol_sensor_replay import _replay as multi_symbol_sensor_replay
from tests.determinism.test_portfolio_order_replay import _replay as portfolio_order_replay
from tests.determinism.test_position_pnl_replay import _replay as position_pnl_replay
from tests.determinism.test_reference_alpha_signal_fires_replay import (
    _replay as reference_alpha_signal_fires_replay,
)
from tests.determinism.test_regime_hazard_replay import _replay as regime_hazard_replay
from tests.determinism.test_risk_verdict_replay import _replay as risk_verdict_replay
from tests.determinism.test_regime_state_replay import (
    EXPECTED_LEVEL6_REGIME_STATE_COUNT,
    _drive_regime_states,
    _hash_regime_stream,
)
from tests.determinism.test_sensor_reading_replay import _replay as sensor_replay
from tests.determinism.test_signal_fires_replay import _replay as signal_fires_replay
from tests.determinism.test_signal_replay import _replay as signal_replay
from tests.determinism.test_state_transition_replay import _replay as state_transition_replay
from tests.determinism.test_symbol_halted_replay import _replay as symbol_halted_replay
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


def _replay_symbol_halted() -> tuple[str, int]:
    return symbol_halted_replay()["symbol_halted"]


def _replay_halt_order() -> tuple[str, int]:
    return symbol_halted_replay()["order"]


def _replay_halt_ack() -> tuple[str, int]:
    return symbol_halted_replay()["ack"]


def _replay_halt_position_update() -> tuple[str, int]:
    return symbol_halted_replay()["position_update"]


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
    "position_pnl": position_pnl_replay,
    "state_transition": state_transition_replay,
    "cross_sectional_context": xsect_context_replay,
    "signal_fires": signal_fires_replay,
    "multi_symbol_sensor_reading": multi_symbol_sensor_replay,
    "reference_alpha_signal_fires": reference_alpha_signal_fires_replay,
    "symbol_halted": _replay_symbol_halted,
    "halt_order": _replay_halt_order,
    "halt_ack": _replay_halt_ack,
    "halt_position_update": _replay_halt_position_update,
    "risk_verdict": risk_verdict_replay,
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
    # Orchestrator hashes stay local because regime math is host-sensitive.
    "EXPECTED_ORCHESTRATOR_SIGNAL_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_INTENT_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_ORDER_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_POSITION_UPDATE_HASH": (
        "orchestrator-level baseline (test_orchestrator_replay.py)"
    ),
    "EXPECTED_ORCHESTRATOR_SMOKE_SIGNAL_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_SMOKE_INTENT_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_SMOKE_ORDER_HASH": "orchestrator-level baseline (test_orchestrator_replay.py)",
    "EXPECTED_ORCHESTRATOR_SMOKE_POSITION_UPDATE_HASH": (
        "orchestrator-level baseline (test_orchestrator_replay.py)"
    ),
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

    Scan the determinism package for
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


# ── Manifest fingerprint ─────────────────────────────────────────────────

# A single SHA-256 covers the sorted manifest. Re-baseline it with any
# intentional baseline change.
EXPECTED_MANIFEST_FINGERPRINT = "6c1318a79d2132abd49f1bb4d09ab96e5073cb98e9230b7a37b829b411719eae"


def test_manifest_fingerprint_matches_locked_value() -> None:
    actual = parity_manifest.manifest_fingerprint()
    assert actual == EXPECTED_MANIFEST_FINGERPRINT, (
        "Manifest fingerprint drift — one or more locked baselines changed!\n"
        f"  Expected: {EXPECTED_MANIFEST_FINGERPRINT}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_MANIFEST_FINGERPRINT here in the same "
        "commit as the baseline change(s) that moved it, with the same "
        "re-baseline justification."
    )
