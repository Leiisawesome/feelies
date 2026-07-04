"""Tests for YAML ``extends:`` inheritance used by platform configs."""

from __future__ import annotations

import copy
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


def test_deep_merge_mapping_does_not_mutate_inputs() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 9, "z": 3}, "b": 2}
    base_before = copy.deepcopy(base)
    override_before = copy.deepcopy(override)
    deep_merge_mapping(base, override)
    assert base == base_before
    assert override == override_before


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


def test_load_yaml_mapping_rejects_missing_extends_target(tmp_path: Path) -> None:
    child = tmp_path / "child.yaml"
    child.write_text(yaml.dump({"extends": "does_not_exist.yaml"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="target not found"):
        load_yaml_mapping(child)


def test_load_yaml_mapping_rejects_non_mapping_root(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="root must be a YAML mapping"):
        load_yaml_mapping(bad)


def test_load_yaml_mapping_rejects_extends_depth_exceeded(tmp_path: Path) -> None:
    # A linear chain of 17 files (level_0 .. level_16), each extending the
    # next, exceeds _MAX_EXTENDS_DEPTH (16).
    depth = 17
    for i in range(depth):
        target = tmp_path / f"level_{i}.yaml"
        if i < depth - 1:
            target.write_text(yaml.dump({"extends": f"level_{i + 1}.yaml"}), encoding="utf-8")
        else:
            target.write_text(yaml.dump({"mode": "BACKTEST"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="depth exceeds"):
        load_yaml_mapping(tmp_path / "level_0.yaml")
