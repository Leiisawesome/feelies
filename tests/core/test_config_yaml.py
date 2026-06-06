"""Tests for YAML ``extends:`` inheritance used by platform configs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from feelies.core.config_yaml import deep_merge_mapping, load_yaml_mapping
from feelies.core.errors import ConfigurationError

pytestmark = pytest.mark.usefixtures("tmp_path")


def test_deep_merge_mapping_merges_nested_dicts() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 9, "z": 3}, "b": 2}
    merged = deep_merge_mapping(base, override)
    assert merged == {"a": 1, "b": 2, "nested": {"x": 1, "y": 9, "z": 3}}


def test_load_yaml_mapping_extends_relative_path(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    child = tmp_path / "child.yaml"
    base.write_text(yaml.dump({"mode": "BACKTEST", "symbols": ["AAPL"]}), encoding="utf-8")
    child.write_text(
        yaml.dump({"extends": "base.yaml", "symbols": ["APP"]}),
        encoding="utf-8",
    )
    merged = load_yaml_mapping(child)
    assert merged["mode"] == "BACKTEST"
    assert merged["symbols"] == ["APP"]


def test_load_yaml_mapping_rejects_extends_cycle(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text(yaml.dump({"extends": "b.yaml"}), encoding="utf-8")
    b.write_text(yaml.dump({"extends": "a.yaml"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cycle"):
        load_yaml_mapping(a)
