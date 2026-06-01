"""Unit tests for split_backtest_emit.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "split_backtest_emit.py"


def _load_splitter():
    spec = importlib.util.spec_from_file_location("split_backtest_emit", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["split_backtest_emit"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_split_emit_idempotent(tmp_path: Path) -> None:
    mod = _load_splitter()
    lines = [
        'SIGNAL_JSONL: {"timestamp_ns": 100, "sequence": 1, "symbol": "SPY"}',
        'SIGNAL_JSONL: {"timestamp_ns": 200, "sequence": 2, "symbol": "SPY"}',
    ]
    counts1 = mod.split_emit_stream(lines, tmp_path)
    data1 = (tmp_path / "signals.jsonl").read_text(encoding="utf-8")
    for f in tmp_path.glob("*.jsonl"):
        f.unlink()
    (tmp_path / "metadata.json").unlink()
    counts2 = mod.split_emit_stream(lines, tmp_path)
    data2 = (tmp_path / "signals.jsonl").read_text(encoding="utf-8")
    assert counts1 == counts2
    assert data1 == data2
    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["prefixes_seen"] == ["SIGNAL_JSONL"]
