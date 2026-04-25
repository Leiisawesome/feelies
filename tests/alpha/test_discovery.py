"""Unit tests for alpha spec discovery and load_and_register.

Workstream D.2: the fixture template is a minimal ``layer: SIGNAL``
alpha (LEGACY_SIGNAL was retired from the loader's accepted layer
set).  The discovery layer is layer-agnostic — these tests assert
filename selection, sort order, and per-alpha-fault tolerance, not
loader semantics — so the migration is mechanical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.discovery import discover_alpha_specs, load_and_register
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.registry import AlphaRegistry

ALPHA_SPEC_TEMPLATE = """\
schema_version: "1.1"
layer: SIGNAL
alpha_id: {alpha_id}
version: "1.0.0"
author: test
description: test alpha
hypothesis: test
falsification_criteria:
  - test criterion
symbols:
  - AAPL
parameters: {{}}
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 5.0
  max_drawdown_pct: 1.0
  capital_allocation_pct: 10.0
horizon_seconds: 120
depends_on_sensors:
  - ofi_ewma
  - spread_z_30d
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "P(normal) > 0.7"
  off_condition: "P(normal) < 0.5"
cost_arithmetic:
  edge_estimate_bps: 9.0
  half_spread_bps: 2.0
  impact_bps: 2.0
  fee_bps: 1.0
  margin_ratio: 1.8
signal: |
  def evaluate(snapshot, regime, params):
      return None
"""

INVALID_ALPHA_SPEC_YAML = """\
alpha_id: bad_alpha
version: "1.0"
description: bad alpha
features: []
signal: |
  def evaluate(features, params):
      return None
"""


def _write_spec(directory: Path, filename: str, alpha_id: str) -> Path:
    spec_file = directory / filename
    content = ALPHA_SPEC_TEMPLATE.format(alpha_id=alpha_id)
    spec_file.write_text(content, encoding="utf-8")
    return spec_file


class TestDiscoverAlphaSpecs:

    def test_finds_alpha_yaml_files(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "a.alpha.yaml", "alpha_a")
        _write_spec(tmp_path, "b.alpha.yaml", "alpha_b")

        specs = discover_alpha_specs(tmp_path)

        assert len(specs) == 2
        names = [s.name for s in specs]
        assert "a.alpha.yaml" in names
        assert "b.alpha.yaml" in names

    def test_raises_for_nonexistent_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError, match="Alpha spec directory not found"):
            discover_alpha_specs(missing)

    def test_returns_empty_for_empty_directory(self, tmp_path: Path) -> None:
        specs = discover_alpha_specs(tmp_path)
        assert specs == []

    def test_ignores_non_alpha_yaml_files(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "config.yaml").write_text("x: 1", encoding="utf-8")
        (tmp_path / "notes.md").write_text("# notes", encoding="utf-8")
        _write_spec(tmp_path, "valid.alpha.yaml", "valid")

        specs = discover_alpha_specs(tmp_path)

        assert len(specs) == 1
        assert specs[0].name == "valid.alpha.yaml"

    def test_results_sorted_alphabetically(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "z_alpha.alpha.yaml", "z_alpha")
        _write_spec(tmp_path, "a_alpha.alpha.yaml", "a_alpha")
        _write_spec(tmp_path, "m_alpha.alpha.yaml", "m_alpha")

        specs = discover_alpha_specs(tmp_path)

        names = [s.name for s in specs]
        assert names == sorted(names)


class TestLoadAndRegister:

    def test_loads_and_registers_multiple_alphas(self, tmp_path: Path) -> None:
        _write_spec(tmp_path, "alpha_a.alpha.yaml", "alpha_a")
        _write_spec(tmp_path, "alpha_b.alpha.yaml", "alpha_b")

        registry = AlphaRegistry()
        loader = AlphaLoader()
        loaded_ids = load_and_register(tmp_path, registry, loader)

        assert sorted(loaded_ids) == ["alpha_a", "alpha_b"]
        assert "alpha_a" in registry
        assert "alpha_b" in registry

    def test_continues_on_error_for_individual_alphas(
        self, tmp_path: Path
    ) -> None:
        _write_spec(tmp_path, "good.alpha.yaml", "good_alpha")
        bad_file = tmp_path / "bad.alpha.yaml"
        bad_file.write_text(INVALID_ALPHA_SPEC_YAML, encoding="utf-8")

        registry = AlphaRegistry()
        loader = AlphaLoader()
        loaded_ids = load_and_register(tmp_path, registry, loader)

        assert loaded_ids == ["good_alpha"]
        assert "good_alpha" in registry
        assert "bad_alpha" not in registry

    def test_raises_when_no_specs_found(self, tmp_path: Path) -> None:
        registry = AlphaRegistry()
        loader = AlphaLoader()
        with pytest.raises(RuntimeError, match="No .alpha.yaml files found"):
            load_and_register(tmp_path, registry, loader)

    def test_raises_when_all_specs_fail(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.alpha.yaml"
        bad_file.write_text(INVALID_ALPHA_SPEC_YAML, encoding="utf-8")

        registry = AlphaRegistry()
        loader = AlphaLoader()
        with pytest.raises(RuntimeError, match="No alphas loaded successfully"):
            load_and_register(tmp_path, registry, loader)

    def test_applies_parameter_overrides(self, tmp_path: Path) -> None:
        spec_yaml = """\
schema_version: "1.1"
layer: SIGNAL
alpha_id: my_alpha
version: "1.0.0"
author: test
description: test alpha
hypothesis: test
falsification_criteria:
  - test criterion
parameters:
  threshold:
    type: float
    default: 0.0
    description: threshold
horizon_seconds: 120
depends_on_sensors:
  - ofi_ewma
  - spread_z_30d
regime_gate:
  regime_engine: hmm_3state_fractional
  on_condition: "P(normal) > 0.7"
  off_condition: "P(normal) < 0.5"
cost_arithmetic:
  edge_estimate_bps: 9.0
  half_spread_bps: 2.0
  impact_bps: 2.0
  fee_bps: 1.0
  margin_ratio: 1.8
signal: |
  def evaluate(snapshot, regime, params):
      return None
"""
        (tmp_path / "my_alpha.alpha.yaml").write_text(spec_yaml, encoding="utf-8")

        registry = AlphaRegistry()
        loader = AlphaLoader()
        overrides = {"my_alpha": {"threshold": 5.0}}
        loaded_ids = load_and_register(tmp_path, registry, loader, parameter_overrides=overrides)

        assert "my_alpha" in loaded_ids
        alpha = registry.get("my_alpha")
        assert alpha.manifest.parameters["threshold"] == 5.0
