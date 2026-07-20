"""Unit tests for ``scripts/record_paper_perf_baseline.py``.

Every test that calls ``main()`` monkeypatches the module's ``_BASELINE``
constant to a temp path first — ``main()`` otherwise reads/writes the real
committed ``tests/perf/baselines/v02_baseline.json``, which must never be
mutated by a test run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "record_paper_perf_baseline.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("record_paper_perf_baseline", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["record_paper_perf_baseline"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_timing(run_dir: Path, rows: list[dict[str, object]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "timing.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_refuses_when_timing_jsonl_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _load_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rc = mod.main(["--run-dir", str(run_dir), "--host-label", "dev_local"])
    assert rc == 1
    assert "refusing to record" in capsys.readouterr().err


def test_refuses_when_timing_jsonl_has_no_tick_process_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A timing file without tick samples cannot define a p99 baseline.
    mod = _load_module()
    monkeypatch.setattr(mod, "_BASELINE", tmp_path / "v02_baseline.json")
    run_dir = tmp_path / "run"
    _write_timing(run_dir, [{"kind": "drain_async_fills", "duration_ns": 500}])

    rc = mod.main(["--run-dir", str(run_dir), "--host-label", "dev_local"])

    assert rc == 1
    assert "refusing to record" in capsys.readouterr().err
    assert not (tmp_path / "v02_baseline.json").exists()


def test_records_baseline_when_samples_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_module()
    baseline_path = tmp_path / "v02_baseline.json"
    monkeypatch.setattr(mod, "_BASELINE", baseline_path)
    run_dir = tmp_path / "run"
    _write_timing(
        run_dir,
        [
            {"kind": "tick_process", "duration_ns": 1_000_000},
            {"kind": "tick_process", "duration_ns": 2_000_000},
            {"kind": "drain_async_fills", "duration_ns": 500_000},
        ],
    )

    rc = mod.main(["--run-dir", str(run_dir), "--host-label", "dev_local"])

    assert rc == 0
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    paper_rth = data["hosts"]["dev_local"]["paper_rth"]
    assert paper_rth["tick_processing_p99_s"] > 0.0
    assert paper_rth["drain_p99_s"] > 0.0
