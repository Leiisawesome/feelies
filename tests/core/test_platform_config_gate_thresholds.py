"""``PlatformConfig.gate_thresholds`` block tests.

Pins the YAML / dataclass surface of the optional ``gate_thresholds``
mapping. Semantic key/type validation lives in bootstrap
(``_build_platform_gate_thresholds``); this module covers structure
and snapshot provenance:

  * **Default** — ``gate_thresholds_overrides`` is ``{}`` and
    ``snapshot()`` records an empty mapping (no determinism drift on
    legacy configs).
  * **YAML structure** — a non-mapping block is rejected; an empty
    block stores ``{}``.
  * **Snapshot stability** — the overrides are folded into
    ``_to_dict()`` in sorted-key order so two equivalent configs
    produce byte-identical checksums.
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

    def test_yaml_without_block_yields_empty_mapping(self, tmp_path: Path) -> None:
        cfg = PlatformConfig.from_yaml(_write_yaml(tmp_path, _MINIMAL_CONFIG_YAML))
        assert cfg.gate_thresholds_overrides == {}


# ─────────────────────────────────────────────────────────────────────
# YAML happy path
# ─────────────────────────────────────────────────────────────────────


class TestPlatformConfigGateThresholdsYAML:
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
        with pytest.raises(ConfigurationError, match="gate_thresholds.*must be a mapping"):
            PlatformConfig.from_yaml(_write_yaml(tmp_path, body))


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
