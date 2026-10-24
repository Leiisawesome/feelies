"""CI-watch derive: a known answer and the committed D-209 run set."""

from __future__ import annotations

import math
from pathlib import Path

from tools.exec.ci_watch import Run, derive, format_line, load

_ROOT = Path(__file__).resolve().parents[2]
_RUNS = _ROOT / "docs/architecture/target/out/exec/ci_watch_runs_T-5.csv"


def test_derive_known_answer() -> None:
    rows = (
        Run("2026-01-01T00:00:00Z", 100, math.exp(4.0)),
        Run("2026-01-02T00:00:00Z", 100, math.exp(4.2)),
        Run("2026-01-03T00:00:00Z", 200, math.exp(4.3)),
        Run("2026-01-04T00:00:00Z", 200, math.exp(4.5)),
    )
    derived = derive(rows, window=2)
    assert math.isclose(derived.sigma, math.sqrt(0.02), rel_tol=1e-12)
    assert math.isclose(derived.reference, math.exp(4.4), rel_tol=1e-12)
    assert math.isclose(derived.threshold, math.exp(4.7), rel_tol=1e-12)
    assert derived.runs == 4
    assert derived.groups == 2


def test_committed_run_set_reproduces_d209() -> None:
    line = format_line(derive(load(_RUNS)))
    assert line == "reference 75.09 sigma 0.0382 threshold 81.43 runs 50 groups 13"
