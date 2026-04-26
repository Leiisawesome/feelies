"""Workstream F-5: PlatformConfig ``gate_thresholds:`` block tests.

Pins the YAML / dataclass surface of platform-level
:class:`feelies.alpha.promotion_evidence.GateThresholds` overrides:

  * **Default** — ``gate_thresholds_overrides`` is ``{}`` and
    ``snapshot()`` records an empty mapping (no determinism drift on
    legacy configs).
  * **YAML happy path** — known keys with valid types are parsed and
    coerced.
  * **YAML sad path** — unknown keys, non-mapping blocks, and bad
    value types raise :class:`ConfigurationError` with the source
    path embedded.
  * **Snapshot stability** — the merged overrides are folded into
    ``_to_dict()`` in sorted-key order so two equivalent configs
    produce byte-identical checksums (audit A-DET-02).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import PlatformConfig


_MINIMAL_CONFIG_YAML = dedent(
    """
    version: "0.1.0"
    author: "test"
    symbols: ["AAPL"]
    mode: "BACKTEST"
    alpha_specs: ["dummy.alpha.yaml"]
    """
).strip()


def _write_yaml(tmp_path: Path, body: str) -> Path:
    cfg_path = tmp_path / "platform.yaml"
    cfg_path.write_text(body, encoding="utf-8")
    return cfg_path


# ─────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────


class TestPlatformConfigGateThresholdsDefault:
    def test_default_is_empty_mapping(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
        )
        assert cfg.gate_thresholds_overrides == {}

    def test_yaml_without_block_yields_empty_mapping(
        self, tmp_path: Path
    ) -> None:
        cfg = PlatformConfig.from_yaml(
            _write_yaml(tmp_path, _MINIMAL_CONFIG_YAML)
        )
        assert cfg.gate_thresholds_overrides == {}


# ─────────────────────────────────────────────────────────────────────
# YAML happy path
# ─────────────────────────────────────────────────────────────────────


class TestPlatformConfigGateThresholdsYAML:
    def test_parses_known_keys(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\n" + dedent(
            """
            gate_thresholds:
              dsr_min: 1.5
              paper_min_trading_days: 7
            """
        )
        cfg = PlatformConfig.from_yaml(_write_yaml(tmp_path, body))
        assert cfg.gate_thresholds_overrides == {
            "dsr_min": 1.5,
            "paper_min_trading_days": 7,
        }
        assert isinstance(
            cfg.gate_thresholds_overrides["dsr_min"], float
        )
        assert isinstance(
            cfg.gate_thresholds_overrides["paper_min_trading_days"], int
        )

    def test_int_value_coerced_to_float(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\n" + dedent(
            """
            gate_thresholds:
              dsr_min: 2
            """
        )
        cfg = PlatformConfig.from_yaml(_write_yaml(tmp_path, body))
        assert cfg.gate_thresholds_overrides == {"dsr_min": 2.0}

    def test_empty_block_yields_empty_dict(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\ngate_thresholds: {}\n"
        cfg = PlatformConfig.from_yaml(_write_yaml(tmp_path, body))
        assert cfg.gate_thresholds_overrides == {}


# ─────────────────────────────────────────────────────────────────────
# YAML sad path
# ─────────────────────────────────────────────────────────────────────


class TestPlatformConfigGateThresholdsErrors:
    def test_non_mapping_block_rejected(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\ngate_thresholds: [1, 2, 3]\n"
        with pytest.raises(
            ConfigurationError, match="gate_thresholds.*must be a mapping"
        ):
            PlatformConfig.from_yaml(_write_yaml(tmp_path, body))

    def test_unknown_key_rejected(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\n" + dedent(
            """
            gate_thresholds:
              not_a_real_threshold: 5
            """
        )
        with pytest.raises(ConfigurationError, match="unknown field"):
            PlatformConfig.from_yaml(_write_yaml(tmp_path, body))

    def test_bad_type_rejected(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\n" + dedent(
            """
            gate_thresholds:
              dsr_min: "not_a_number"
            """
        )
        with pytest.raises(ConfigurationError, match="expects float"):
            PlatformConfig.from_yaml(_write_yaml(tmp_path, body))

    def test_error_carries_source_path(self, tmp_path: Path) -> None:
        body = _MINIMAL_CONFIG_YAML + "\n" + dedent(
            """
            gate_thresholds:
              not_a_real_threshold: 5
            """
        )
        cfg_path = _write_yaml(tmp_path, body)
        with pytest.raises(ConfigurationError) as excinfo:
            PlatformConfig.from_yaml(cfg_path)
        assert "platform.yaml" in str(excinfo.value)


# ─────────────────────────────────────────────────────────────────────
# Snapshot stability
# ─────────────────────────────────────────────────────────────────────


class TestPlatformConfigGateThresholdsSnapshot:
    def test_snapshot_includes_overrides_sorted(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={
                "paper_min_trading_days": 7,
                "dsr_min": 1.5,
            },
        )
        snap = cfg.snapshot()
        assert snap.data["gate_thresholds_overrides"] == {
            "dsr_min": 1.5,
            "paper_min_trading_days": 7,
        }

    def test_snapshot_empty_overrides_is_empty_dict(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
        )
        snap = cfg.snapshot()
        assert snap.data["gate_thresholds_overrides"] == {}

    def test_snapshot_checksum_changes_when_overrides_change(self) -> None:
        cfg_a = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
        )
        cfg_b = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={"dsr_min": 1.5},
        )
        assert cfg_a.snapshot().checksum != cfg_b.snapshot().checksum

    def test_snapshot_checksum_stable_across_dict_orderings(self) -> None:
        # Insertion order should NOT affect the checksum since
        # _to_dict sorts the override keys.
        cfg_a = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={
                "dsr_min": 1.5,
                "paper_min_trading_days": 7,
            },
        )
        cfg_b = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={
                "paper_min_trading_days": 7,
                "dsr_min": 1.5,
            },
        )
        assert cfg_a.snapshot().checksum == cfg_b.snapshot().checksum
