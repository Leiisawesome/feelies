"""Tests for Phase-3.1 strict-mode field on PlatformConfig.

Covers ``enforce_trend_mechanism`` per §20.6.2:

  - Default is False → schema-1.1 SIGNAL/PORTFOLIO specs without
    ``trend_mechanism:`` continue to load (v0.2 parity preserved).
  - YAML round-trip (``True`` / ``False`` / absent) reflects the
    declared value with no surprises.
  - Snapshot checksum is *deterministic* across repeated calls and
    *changes* when the flag flips (Inv-13 provenance).
  - End-to-end through :class:`AlphaLoader`: with strict mode on, a
    schema-1.1 SIGNAL spec missing ``trend_mechanism:`` is refused
    via :class:`MissingTrendMechanismError`; with strict mode off it
    loads successfully.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from feelies.alpha.layer_validator import MissingTrendMechanismError
from feelies.alpha.loader import AlphaLoader
from feelies.core.platform_config import PlatformConfig


def _base_config(**overrides) -> PlatformConfig:
    base = dict(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[Path("dummy.alpha.yaml")],
    )
    base.update(overrides)
    return PlatformConfig(**base)


# ── Defaults ────────────────────────────────────────────────────────────


class TestDefaults:
    def test_default_value_is_false(self) -> None:
        cfg = _base_config()
        assert cfg.enforce_trend_mechanism is False

    def test_default_config_validates(self) -> None:
        _base_config().validate()


# ── YAML round-trip ─────────────────────────────────────────────────────


class TestYAMLRoundTrip:
    def test_omitted_yields_default_false(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
        """).strip())
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is False

    def test_explicit_true_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
            enforce_trend_mechanism: true
        """).strip())
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is True

    def test_explicit_false_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
            enforce_trend_mechanism: false
        """).strip())
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is False


# ── Snapshot ────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_value_recorded_in_snapshot(self) -> None:
        snap_off = _base_config(enforce_trend_mechanism=False).snapshot()
        snap_on = _base_config(enforce_trend_mechanism=True).snapshot()
        assert snap_off.data["enforce_trend_mechanism"] is False
        assert snap_on.data["enforce_trend_mechanism"] is True

    def test_snapshot_deterministic(self) -> None:
        cfg = _base_config(enforce_trend_mechanism=True)
        assert cfg.snapshot().checksum == cfg.snapshot().checksum

    def test_flipping_flag_changes_checksum(self) -> None:
        snap_off = _base_config(enforce_trend_mechanism=False).snapshot()
        snap_on = _base_config(enforce_trend_mechanism=True).snapshot()
        assert snap_off.checksum != snap_on.checksum


# ── End-to-end loader behaviour ─────────────────────────────────────────


_SIGNAL_SPEC_NO_MECHANISM = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "alpha_x",
    "version": "1.0.0",
    "description": "test alpha",
    "hypothesis": "test hypothesis",
    "falsification_criteria": ["criterion 1"],
    "horizon_seconds": 120,
    "depends_on_sensors": ["ofi_ewma", "spread_z_30d"],
    "regime_gate": {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.7",
        "off_condition": "P(normal) < 0.5",
    },
    "cost_arithmetic": {
        "edge_estimate_bps": 9.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 1.8,
    },
    "signal": (
        "def evaluate(snapshot, regime, params):\n"
        "    return None\n"
    ),
}


_SIGNAL_SPEC_WITH_MECHANISM = {
    **_SIGNAL_SPEC_NO_MECHANISM,
    "trend_mechanism": {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": 240,
        "l1_signature_sensors": ["kyle_lambda_60s", "ofi_ewma"],
        "failure_signature": ["spread_z_30d > 2.5"],
    },
}


class TestStrictLoaderBehaviour:
    def test_strict_off_accepts_v11_signal_without_mechanism(self) -> None:
        AlphaLoader(enforce_trend_mechanism=False).load_from_dict(
            dict(_SIGNAL_SPEC_NO_MECHANISM), source="<test>",
        )

    def test_strict_on_refuses_v11_signal_without_mechanism(self) -> None:
        with pytest.raises(MissingTrendMechanismError, match="strict-mode"):
            AlphaLoader(enforce_trend_mechanism=True).load_from_dict(
                dict(_SIGNAL_SPEC_NO_MECHANISM), source="<test>",
            )

    def test_strict_on_accepts_v11_signal_with_mechanism(self) -> None:
        AlphaLoader(enforce_trend_mechanism=True).load_from_dict(
            dict(_SIGNAL_SPEC_WITH_MECHANISM), source="<test>",
        )
