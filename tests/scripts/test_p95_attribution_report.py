"""Drift and counting tests for the real-day P-95 report (P-99a)."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import yaml

from feelies.core.events import Alert, AlertSeverity, GateDecision, PositionClosed
from feelies.core.platform_config import PlatformConfig

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "p95_attribution_report.py"
_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_LEGACY_SPEC = Path("tests/position_engine/fixtures/sig_position_fixture_v1_legacy.alpha.yaml")
_ENGINE_CONFIG = Path("configs/bt_position_arbitrary_not_calibrated.yaml")
_LEGACY_CONFIG = Path("configs/bt_position_legacy_arm.yaml")


def _load():
    spec = importlib.util.spec_from_file_location("p95_attribution_report", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["p95_attribution_report"] = mod
    spec.loader.exec_module(mod)
    return mod


def _closed(reason: str, seq: int) -> PositionClosed:
    return PositionClosed(
        timestamp_ns=seq,
        correlation_id=f"close-{seq}",
        sequence=seq,
        cell_id=f"APP|sig|{seq}",
        symbol="APP",
        strategy_id="sig_position_fixture_v1",
        side="LONG",
        declared_archetype="liquidity_provision",
        entry_fills=(),
        exit_fills=(),
        entry_spread_ticks=1,
        horizon_deadline_ns=0,
        drawn_level_ticks=0,
        exit_reason=reason,
        triggered_paths=(),
        closed_on_stale_data=False,
        exited_on_unusable_data=False,
        lived_through_feed_gap=False,
        first_event_exit=False,
        stop_inside_round_trip=False,
        target_inside_round_trip=False,
        uncalibrated=True,
        supersedes="",
    )


def _alert(name: str, reason: str, seq: int) -> Alert:
    return Alert(
        timestamp_ns=seq,
        correlation_id=f"alert-{seq}",
        sequence=seq,
        severity=AlertSeverity.WARNING,
        layer="kernel",
        alert_name=name,
        message=name,
        context={"refusal_reason": reason},
    )


def _decision(outcome: str, suppressions: tuple[str, ...], seq: int) -> GateDecision:
    return GateDecision(
        timestamp_ns=seq,
        correlation_id=f"gate-{seq}",
        sequence=seq,
        cell_id="APP|sig|1",
        rail_sequence=seq,
        gate="favorable",
        outcome=outcome,
        reason="",
        form="fixed",
        proposed_price_cents=None,
        reference_ticks=0,
        reference_sequence=0,
        drawn_level_ticks=0,
        suppressions=suppressions,
    )


def test_legacy_spec_equals_fixture_minus_exit_policy() -> None:
    fixture = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    legacy = yaml.safe_load(_LEGACY_SPEC.read_text(encoding="utf-8"))
    assert isinstance(fixture, dict)
    assert isinstance(legacy, dict)
    assert "exit_policy" not in legacy
    assert fixture.pop("exit_policy") is not None
    assert fixture == legacy


def test_legacy_config_differs_in_alpha_specs_only() -> None:
    legacy = PlatformConfig.from_yaml(_LEGACY_CONFIG)
    engine = PlatformConfig.from_yaml(_ENGINE_CONFIG)
    assert legacy.alpha_specs == [_LEGACY_SPEC]
    for item in dataclasses.fields(PlatformConfig):
        if item.name == "alpha_specs":
            continue
        assert getattr(legacy, item.name) == getattr(engine, item.name)


def test_exit_mix() -> None:
    mod = _load()
    closed = (
        _closed("HORIZON", 1),
        _closed("HORIZON", 2),
        _closed("FAVORABLE", 3),
        _closed("EXTERNAL:SIGN_FLIP", 4),
    )
    assert mod.exit_mix(closed) == {
        "EXTERNAL:SIGN_FLIP": 1,
        "FAVORABLE": 1,
        "HORIZON": 2,
    }


def test_refusal_counts() -> None:
    mod = _load()
    alerts = (
        _alert("position_entry_refused", "NO_SCALE_IN", 1),
        _alert("position_entry_refused", "NO_SCALE_IN", 2),
        _alert("position_entry_refused", "CUTOFF_ALREADY_PASSED", 3),
        _alert("other", "NO_SCALE_IN", 4),
    )
    assert mod.refusal_counts(alerts) == {
        "CUTOFF_ALREADY_PASSED": 1,
        "NO_SCALE_IN": 2,
    }


def test_suppression_counts() -> None:
    mod = _load()
    decisions = (
        _decision("suppressed", ("QUIET",), 1),
        _decision("suppressed", ("QUIET", "SPREAD"), 2),
        _decision("hold", (), 3),
        _decision("fire", (), 4),
    )
    assert mod.suppression_counts(decisions) == (2, {"QUIET": 2, "SPREAD": 1})


def test_empty_inputs() -> None:
    mod = _load()
    assert mod.exit_mix(()) == {}
    assert mod.refusal_counts(()) == {}
    assert mod.suppression_counts(()) == (0, {})
