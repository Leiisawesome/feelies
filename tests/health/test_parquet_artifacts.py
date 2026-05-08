from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

HAS_PYARROW = pa is not None and pq is not None

from feelies.health import load_run_directory


@pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow not installed")
def test_load_signals_parquet(tmp_path: Path) -> None:
    assert pa is not None and pq is not None
    root = tmp_path / "pq_run"
    root.mkdir()

    rows = [
        {"timestamp": 1_700_000_000_000_000_000, "symbol": "AAA", "signal": 0.1, "forward_return": 0.001},
        {"timestamp": 1_700_000_000_000_000_001, "symbol": "BBB", "signal": -0.2, "forward_return": -0.0005},
    ]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, root / "signals.parquet")

    meta = {
        "alpha_name": "pq_alpha",
        "universe": ["AAA", "BBB"],
        "timeframe": "2024-01-01/2024-01-31",
        "data_source": "test",
        "prediction_horizon": "30s",
        "execution_assumption": "sim",
        "cost_assumption": "1bp",
    }
    (root / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    ctx = load_run_directory(root)
    assert len(ctx.signals) == 2
    assert ctx.signals[0]["symbol"] == "AAA"
    assert float(ctx.signals[0]["signal"]) == pytest.approx(0.1)


@pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow not installed")
def test_csv_preferred_when_both_present(tmp_path: Path) -> None:
    assert pa is not None and pq is not None
    root = tmp_path / "both"
    root.mkdir()

    (root / "signals.csv").write_text(
        "timestamp,symbol,signal\n9,X,1.0\n",
        encoding="utf-8",
    )
    table = pa.Table.from_pylist([{"timestamp": 8, "symbol": "Y", "signal": 2.0}])
    pq.write_table(table, root / "signals.parquet")

    (root / "metadata.json").write_text(
        json.dumps(
            {
                "alpha_name": "x",
                "universe": ["X"],
                "timeframe": "t",
                "data_source": "d",
                "prediction_horizon": "1s",
                "execution_assumption": "e",
                "cost_assumption": "c",
            }
        ),
        encoding="utf-8",
    )

    ctx = load_run_directory(root)
    assert len(ctx.signals) == 1
    assert ctx.signals[0]["symbol"] == "X"
