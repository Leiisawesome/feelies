"""Tests for strict trend-mechanism validation in ``PlatformConfig``.

The suite covers defaults, YAML parsing, snapshot provenance, and loader
behavior with strict mode enabled or explicitly disabled.
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
    def test_default_value_is_true(self) -> None:
        """The default is true.

        Operators relying on a v0.2-baseline alpha (no
        ``trend_mechanism:`` block) must now explicitly pin
        ``enforce_trend_mechanism: false`` in their ``platform.yaml``;
        the reference yaml at the repo root documents this opt-out.
        """
        cfg = _base_config()
        assert cfg.enforce_trend_mechanism is True

    def test_default_config_validates(self) -> None:
        _base_config().validate()


# ── YAML round-trip ─────────────────────────────────────────────────────


class TestYAMLRoundTrip:
    def test_omitted_yields_default_true(self, tmp_path: Path) -> None:
        """An absent ``enforce_trend_mechanism:`` key in
        the YAML now resolves to ``True`` (the new platform default),
        not ``False`` as in v0.2.  The dataclass default and the YAML
        parser default are kept in sync so a YAML omission and a
        Python ``PlatformConfig(...)`` construction agree.
        """
        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
        """).strip()
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is True

    def test_explicit_true_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
            enforce_trend_mechanism: true
        """).strip()
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is True

    def test_explicit_false_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
            symbols: [AAPL]
            alpha_specs: [dummy.alpha.yaml]
            enforce_trend_mechanism: false
        """).strip()
        )
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
    "signal": ("def evaluate(snapshot, regime, params):\n    return None\n"),
}


_SIGNAL_SPEC_WITH_MECHANISM = {
    **_SIGNAL_SPEC_NO_MECHANISM,
    # Signature sensors must also be declared dependencies.
    "depends_on_sensors": ["kyle_lambda_60s", "ofi_ewma", "spread_z_30d"],
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
            dict(_SIGNAL_SPEC_NO_MECHANISM),
            source="<test>",
        )

    def test_strict_on_refuses_v11_signal_without_mechanism(self) -> None:
        with pytest.raises(MissingTrendMechanismError, match="strict-mode"):
            AlphaLoader(enforce_trend_mechanism=True).load_from_dict(
                dict(_SIGNAL_SPEC_NO_MECHANISM),
                source="<test>",
            )

    def test_strict_on_accepts_v11_signal_with_mechanism(self) -> None:
        AlphaLoader(enforce_trend_mechanism=True).load_from_dict(
            dict(_SIGNAL_SPEC_WITH_MECHANISM),
            source="<test>",
        )
