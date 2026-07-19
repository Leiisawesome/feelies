"""Unit tests for split_backtest_emit.py."""

from __future__ import annotations

import importlib.util
import json
import re
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
    # Real emitter format: ``PREFIX {json}`` (single space; the JSON itself
    # contains ``": "``).  See backtest_jsonl._emit_jsonl_line.
    lines = [
        'SIGNAL_JSONL {"timestamp_ns": 100, "sequence": 1, "symbol": "SPY"}',
        'SIGNAL_JSONL {"timestamp_ns": 200, "sequence": 2, "symbol": "SPY"}',
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
    assert counts1 == {"signals.jsonl": 2}
    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["prefixes_seen"] == ["SIGNAL_JSONL"]
    assert meta["first_timestamp_ns"] == 100
    assert meta["last_timestamp_ns"] == 200


def test_split_emit_matches_real_emitter_output(tmp_path: Path) -> None:
    """Round-trip a line produced by the actual backtest emitter."""
    import io
    from contextlib import redirect_stdout

    from feelies.harness.backtest_jsonl import _emit_jsonl_line

    mod = _load_splitter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        _emit_jsonl_line("FILL_JSONL", {"sequence": 1, "symbol": "SPY", "order_id": "abc"})
    counts = mod.split_emit_stream(buf.getvalue().splitlines(), tmp_path)
    assert counts == {"fills.jsonl": 1}
    row = json.loads((tmp_path / "fills.jsonl").read_text(encoding="utf-8").strip())
    assert row == {"order_id": "abc", "sequence": 1, "symbol": "SPY"}


def test_split_emit_tolerates_legacy_colon_form(tmp_path: Path) -> None:
    mod = _load_splitter()
    lines = ['SIGNAL_JSONL: {"timestamp_ns": 100, "sequence": 1, "symbol": "SPY"}']
    counts = mod.split_emit_stream(lines, tmp_path)
    assert counts == {"signals.jsonl": 1}


def test_prefix_map_covers_every_backtest_jsonl_prefix() -> None:
    """Audit P2-3: ``_PREFIX_MAP`` must stay in sync with what
    ``backtest_jsonl._emit_jsonl_line`` actually emits — neither missing a
    prefix (silently falling through to an uncurated ``{prefix.lower()}.jsonl``
    filename) nor carrying a stale entry nothing emits any more."""
    backtest_jsonl_src = (
        Path(__file__).resolve().parents[2] / "src" / "feelies" / "harness" / "backtest_jsonl.py"
    ).read_text(encoding="utf-8")
    emitted_prefixes = set(
        re.findall(r'_emit_jsonl_line\(\s*"([A-Z_]+_JSONL)"', backtest_jsonl_src)
    )
    assert emitted_prefixes, "regex found no _emit_jsonl_line(...) call sites — check the pattern"

    mod = _load_splitter()
    mapped_prefixes = set(mod._PREFIX_MAP)

    missing_from_map = emitted_prefixes - mapped_prefixes
    assert not missing_from_map, (
        f"backtest_jsonl emits {sorted(missing_from_map)} but _PREFIX_MAP has no "
        "entry for them (falls through to an uncurated filename)"
    )
    stale_in_map = mapped_prefixes - emitted_prefixes
    assert not stale_in_map, (
        f"_PREFIX_MAP still lists {sorted(stale_in_map)}, which backtest_jsonl no longer emits"
    )
