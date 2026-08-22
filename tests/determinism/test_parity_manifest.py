"""Verify the locked parity manifest against live replay outputs."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.conformance.test_market_data_canonical import _replay as market_data_canonical_replay
from tests.determinism import parity_manifest
from tests.determinism.test_alert_taxonomy_replay import _replay as alert_taxonomy_replay
from tests.determinism.test_cross_sectional_context_replay import _replay as xsect_context_replay
from tests.determinism.test_decoupled_safety_replay import (
    _replay_risk_flatten as decoupled_risk_flatten_replay,
)
from tests.determinism.test_decoupled_safety_replay import (
    _replay_safety_state_change as decoupled_safety_state_change_replay,
)
from tests.determinism.test_forced_exit_attribution_replay import (
    _replay as forced_exit_attribution_replay,
)
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
    "forced_exit_attribution": forced_exit_attribution_replay,
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
    "decoupled_safety_state_change": decoupled_safety_state_change_replay,
    "decoupled_risk_flatten_order": decoupled_risk_flatten_replay,
    "market_data_canonical": market_data_canonical_replay,
    "alert_taxonomy": alert_taxonomy_replay,
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
_TESTS_DIR = _DETERMINISM_DIR.parent

# Every module-level binding under ``tests/`` that holds a locked hash literal
# and is *not* in the manifest, each with the reason.  Anything else must be
# wired into LOCKED_PARITY_BASELINES + _REPLAY_BY_NAME.
#
# Exemption is by binding name, not by naming convention.  A leading underscore
# used to opt a constant out implicitly — the scanner only matched
# ``EXPECTED_*_HASH``, so anything named otherwise was invisible rather than
# exempt.  Those are different things, and the difference was load-bearing: see
# ``_scan_locked_hash_bindings`` for what that cost.
#
# The scan covers the whole test tree, not just this package.  Locked baselines
# do not stop being baselines by living elsewhere: ``_FIXTURE_GOLDEN_HASHES``
# cites Inv-5 and calls itself "like the determinism parity hashes" from
# tests/acceptance/, and phase-4's E2E stream hashes are parity pins in
# tests/integration/.  Both were unregistered, unexempted, and unwatched.
_UNREGISTERED_HASH_EXEMPTIONS: dict[str, str] = {
    # cvxpy/ECOS solver path is skipped unless the [portfolio] extra is
    # installed, so it cannot be a mandatory manifest entry (the manifest
    # self-test must run without cvxpy).  Locked + guarded locally in
    # tests/determinism/test_sized_intent_solver_replay.py.
    "EXPECTED_LEVEL3_SOLVER_HASH": "cvxpy-conditional baseline (test_sized_intent_solver_replay.py)",
    # Orchestrator streams stay local because these fixtures build the whole
    # platform, regime engine included, and its transcendental math is stable
    # only for a fixed host + libm (see this module's docstring).  The manifest
    # is a portable cross-machine contract, so host-sensitive hashes cannot be
    # mandatory entries.  Locked + guarded locally in test_orchestrator_replay.py.
    "EXPECTED_ORCHESTRATOR_STREAMS": "host-sensitive orchestrator baseline (test_orchestrator_replay.py)",
    "EXPECTED_STOP_EXIT_STREAMS": "host-sensitive orchestrator baseline (test_orchestrator_replay.py)",
    # SHA-256 of the empty string — a shared spelling of "this stream is empty",
    # not a baseline of anything.
    "_EMPTY_SHA": "sha256(b'') helper constant (test_orchestrator_replay.py)",
    # Signal-stream migration goldens: local assertions that promotion moves a
    # gate-close FLAT off the Signal stream, not cross-layer parity baselines.
    "_NON_PROMOTED_SIGNAL_HASH": "module-local migration golden (test_decoupled_safety_replay.py)",
    "_PROMOTED_SIGNAL_HASH": "module-local migration golden (test_decoupled_safety_replay.py)",
    # ── Outside tests/determinism/ ──────────────────────────────────────
    # The APP config *contract* hash: sha256 of the resolved PlatformConfig
    # snapshot, not a replay stream.  It has no event count, so it does not fit
    # the (hash, count) manifest shape or a _REPLAY_BY_NAME entry, and the
    # fingerprint's purpose does not apply to it — that exists so a coordinated
    # re-pin of several baselines is one line in review rather than a pile of
    # individually plausible literals, and there is only ever one config hash to
    # move.  It is also data-free and always runs (unlike the trade-path test,
    # which skips on cache miss), and each re-baseline is justified inline above
    # the constant.  Guarded by test_app_baseline_config_contract_hash.
    "_BASELINE_CONFIG_HASH": "config-contract hash, not a replay baseline "
    "(tests/acceptance/test_backtest_app_baseline.py)",
    # Genuine trade-sequence parity baseline, but its replay requires the
    # external APP/2026-03-26 disk cache and skips in standard CI when that
    # cache is absent. Locked locally in the cache-gated acceptance test.
    "_BASELINE_TRADE_PARITY_HASH": "data-gated APP trade baseline "
    "(tests/acceptance/test_backtest_app_baseline.py)",
    # CPCV fold-PnL-curve hashes over committed JSON fixtures — they pin fixture
    # *data* against silent regeneration, not an event stream produced by a
    # replay, so there is nothing for _REPLAY_BY_NAME to call.
    "_FIXTURE_GOLDEN_HASHES": "fixture-data goldens "
    "(tests/acceptance/test_bt12_reference_alpha_validation.py)",
    # Phase-4 E2E stream pins.  These are genuine parity baselines, but the
    # fixture builds the whole platform, so they carry the same host-sensitive
    # regime math that keeps the orchestrator streams out of a portable manifest.
    "_EMPTY_SHA256": "sha256(b'') helper constant (tests/integration/test_phase4_e2e.py)",
    "EXPECTED_E2E_INTENT_HASH": "host-sensitive E2E baseline "
    "(tests/integration/test_phase4_e2e.py)",
}


# Engine outputs that must appear as LOCKED_PARITY_BASELINES keys (hashed)
# or be named in _ENGINE_OUTPUT_EXEMPTIONS (exempt-with-a-reason).  The 26
# existing replay streams are already keys in the manifest; this table is
# the closure over the two engines whose outputs were previously unhashed.
_REQUIRED_ENGINE_OUTPUT_KEYS: dict[str, str] = {
    "market_data_canonical": "engine 1 NBBOQuote/Trade canonical stream (G05)",
    "alert_taxonomy": "engine 11 Alert taxonomy, alert_name and severity only (G29)",
}

_REQUIRED_ENGINE_OUTPUT_BINDINGS: dict[str, str] = {
    "EXPECTED_MARKET_DATA_CANONICAL_HASH": "engine 1 canonical stream (G05)",
    "EXPECTED_ALERT_TAXONOMY_HASH": "engine 11 Alert taxonomy (G29)",
}

# Remaining engine-11 stream: MetricEvent is a diagnostic counter, not a
# trading stream.  Pinning it would convert every metric increment into a
# parity break.  KillSwitchActivation is kernel/bootstrap, not engine 11.
_ENGINE_OUTPUT_EXEMPTIONS: dict[str, str] = {
    "metric_event": "engine 11 MetricEvent — diagnostic counters, not a trading stream",
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


# Case-insensitive: ``hexdigest()`` is lowercase, but a baseline pasted from a
# tool that upper-cases it is no less a locked hash, and a scanner that cannot
# see a constant has not exempted it.
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")

# The manifest and this module are the registry itself, not places baselines live.
_REGISTRY_MODULES = frozenset({"parity_manifest.py", "test_parity_manifest.py"})


def _scannable_modules() -> list[Path]:
    """Every test module that could hold a locked baseline, in a stable order."""
    return [
        path for path in sorted(_TESTS_DIR.rglob("*.py")) if path.name not in _REGISTRY_MODULES
    ]


def _scan_locked_hash_bindings(path: Path) -> list[str]:
    """Names of module-level bindings in *path* whose value holds a 64-hex literal.

    Detection is by **shape**, not by name.  The previous scanner matched the
    regex ``^(EXPECTED_\\w*_HASH)\\b`` over the raw source, which required a
    baseline to be a top-level constant whose name ended in ``_HASH``.  Two
    locked orchestrator baselines are ``dict``s named ``*_STREAMS`` holding five
    hashes between them, so the scanner never saw them — and ``82dfd20``
    re-pinned three of those with ``EXPECTED_MANIFEST_FINGERPRINT`` green,
    which is exactly the coordinated re-pin the fingerprint exists to surface.
    Meanwhile all eight ``EXPECTED_ORCHESTRATOR_*_HASH`` names it exempted had
    been gone for some time: the allow-list was documenting constants that no
    longer existed while their replacements went unwatched.

    Walking the AST for any top-level assignment whose value contains a 64-hex
    literal catches dicts, tuples, lists, and underscore-prefixed names alike,
    so opting out is a deliberate entry in ``_UNREGISTERED_HASH_EXEMPTIONS``
    rather than a side effect of what a constant is called.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None or not _HEX64.search(ast.unparse(value)):
            continue
        names.extend(t.id for t in targets if isinstance(t, ast.Name))
    return names


def test_every_locked_hash_is_registered_or_exempt() -> None:
    """No locked hash literal may escape the manifest unnoticed.

    Scan every module in the determinism package for locked-hash bindings and
    assert each is either referenced by the manifest or explicitly exempted
    above.  The scan is the whole ``tests/`` tree, not ``test_*replay*.py`` in
    this package: a fixture that pins a hash without ``replay`` in its filename,
    or from ``tests/acceptance/``, is no less a baseline.
    """
    manifest_src = (_DETERMINISM_DIR / "parity_manifest.py").read_text(encoding="utf-8")

    unregistered: list[str] = []
    for path in _scannable_modules():
        for const in _scan_locked_hash_bindings(path):
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

    missing_engine_outputs = sorted(
        name
        for name in _REQUIRED_ENGINE_OUTPUT_KEYS
        if name not in parity_manifest.LOCKED_PARITY_BASELINES
        and name not in _ENGINE_OUTPUT_EXEMPTIONS
    )
    assert not missing_engine_outputs, (
        "engine outputs neither hashed nor exempt-with-a-reason: "
        + "; ".join(
            f"{n} ({_REQUIRED_ENGINE_OUTPUT_KEYS[n]})" for n in missing_engine_outputs
        )
    )


def test_every_exemption_names_a_binding_that_exists() -> None:
    """A stale exemption is worse than none — it reads as coverage that is gone.

    All eight ``EXPECTED_ORCHESTRATOR_*_HASH`` exemptions outlived the constants
    they named, so the list asserted a deliberate choice about baselines that no
    longer existed.  Tie each entry to a live binding.
    """
    live: set[str] = set()
    for path in _scannable_modules():
        live.update(_scan_locked_hash_bindings(path))

    stale = sorted(set(_UNREGISTERED_HASH_EXEMPTIONS) - live)
    assert not stale, (
        f"_UNREGISTERED_HASH_EXEMPTIONS names bindings that no longer hold a "
        f"locked hash: {stale}.  Drop them."
    )

    missing_engine_bindings = sorted(
        name for name in _REQUIRED_ENGINE_OUTPUT_BINDINGS if name not in live
    )
    assert not missing_engine_bindings, (
        "engine-output hash bindings missing from scannable modules: "
        + "; ".join(
            f"{n} ({_REQUIRED_ENGINE_OUTPUT_BINDINGS[n]})" for n in missing_engine_bindings
        )
    )


def test_scanner_sees_dict_and_underscore_bindings(tmp_path: Path) -> None:
    """Pin the two shapes the name-based scanner was blind to.

    Without this, the widened scanner could quietly narrow back to the old
    behaviour and the same class of baseline would go unwatched again.
    """
    digest = "0" * 64
    module = tmp_path / "test_shapes_replay.py"
    module.write_text(
        f'EXPECTED_PLAIN_HASH = "{digest}"\n'
        f'_UNDERSCORED_HASH = "{digest}"\n'
        f'EXPECTED_STREAMS: dict[str, tuple[str, int]] = {{"a": ("{digest}", 1)}}\n'
        f'NOT_A_HASH = "too short"\n',
        encoding="utf-8",
    )
    assert _scan_locked_hash_bindings(module) == [
        "EXPECTED_PLAIN_HASH",
        "_UNDERSCORED_HASH",
        "EXPECTED_STREAMS",
    ]


# ── Manifest fingerprint ─────────────────────────────────────────────────

# A single SHA-256 over the sorted manifest.  Any re-pin — one baseline or
# several at once — changes this one line, so a coordinated re-pin is a
# one-line diff in review instead of several hash literals that each look
# individually plausible. Re-baseline alongside whatever baseline change
# caused it to move, in the same commit, with the same justification.
# Re-baselined 2026-07-02 alongside the ``reference_alpha_signal_fires`` entry:
# sig_benign_midcap_v1 dropped its cosmetic ``micro_price`` dependency
# (sensor_audit_2026-07-02 P1), changing that alpha's emitted
# ``Signal.consumed_features`` provenance (count and behaviour unchanged). See
# ``test_reference_alpha_signal_fires_replay.py`` for the full justification.
# Re-baselined again (Stage-0 dual-permission decoupling, design rev 5 / Phase 5)
# to REGISTER — not change — two brand-new cross-layer baselines:
# ``decoupled_safety_state_change`` and ``decoupled_risk_flatten_order``. No
# existing baseline moved; the fingerprint shifts purely because the manifest set
# grew (23 → 25). See ``test_decoupled_safety_replay.py`` for the migration note.
# Re-baselined again to REGISTER — not change — one brand-new baseline:
# ``forced_exit_attribution``. No existing baseline moved; the fingerprint shifts
# purely because the manifest set grew (25 → 26). The new entry is the first to
# observe *which alpha* a fill is booked to: every prior fixture either wires no
# ``StrategyPositionStore`` or hashes order/state streams rather than the journal,
# so per-strategy re-attribution was invisible to the whole corpus. See
# ``test_forced_exit_attribution_replay.py``.
EXPECTED_MANIFEST_FINGERPRINT = "dbcde6a64447f6c55cde6a1221a873ddfacd7d4ab4a42af71b7cc692b8e5e41b"


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
