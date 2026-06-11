"""Unit tests for ``scripts/analyze_size_divergence.py`` aggregation logic."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load():
    spec = importlib.util.spec_from_file_location(
        "_analyze_sizediv_test",
        Path("scripts/analyze_size_divergence.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_analyze_sizediv_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def test_classify(mod) -> None:
    assert mod.classify(100, 200) == "upsize"
    assert mod.classify(100, 50) == "downsize"
    assert mod.classify(100, 100) == "equal"


def test_parse_line_accepts_prefixed_and_raw(mod) -> None:
    raw = '{"base_target_qty":100,"tilted_target_qty":200,"symbol":"APP"}'
    assert mod.parse_line(raw)["tilted_target_qty"] == 200
    assert mod.parse_line("SIZEDIV_JSONL " + raw)["tilted_target_qty"] == 200
    assert mod.parse_line("") is None
    assert mod.parse_line("not json") is None
    assert mod.parse_line('{"unrelated":1}') is None


def test_summarize_counts_and_rate(mod) -> None:
    records = [
        {
            "symbol": "APP",
            "strategy_id": "a",
            "edge_bps": 40.0,
            "base_target_qty": 100,
            "tilted_target_qty": 200,
            "combined_tilt": 2.0,
        },
        {
            "symbol": "APP",
            "strategy_id": "b",
            "edge_bps": 5.0,
            "base_target_qty": 100,
            "tilted_target_qty": 50,
            "combined_tilt": 0.5,
        },
    ]
    text = mod.summarize(records, total_decisions=1000)
    assert "Divergent sizes           2" in text
    assert "Divergence rate           0.20%" in text
    assert "upsize" in text and "downsize" in text

    empty = mod.summarize([], total_decisions=None)
    assert "No divergent sizes recorded" in empty
