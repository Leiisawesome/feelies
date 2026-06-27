"""No-disk-cache backtest trade-path determinism guard (audit P2-14).

The APP baseline test (``tests/acceptance/test_backtest_app_baseline.py``) is
``@pytest.mark.functional`` and **skips on cache miss**, so in a clean CI
checkout the backtest trade-path bit-identity is otherwise unverified.  This
test runs the real bootstrap + ``run_backtest`` path twice over the same
synthetic tape (no disk cache, no API key) and asserts the trade-sequence parity
hash is identical — pinning Inv-5 for the harness run path itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from feelies.harness.backtest_report import compute_parity_hash

_REPO = Path(__file__).resolve().parents[2]
_SMOKE = _REPO / "scripts" / "smoke_pipeline.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_pipeline_parity", _SMOKE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_pipeline_parity"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_smoke_alphas(mod, tmp_path: Path) -> list[Path]:
    paths: list[Path] = []
    for name, yaml in (
        ("smoke_always_on_v1", mod._SMOKE_SIGNAL_YAML),
        ("smoke_portfolio_feeder_v1", mod._SMOKE_FEEDER_YAML),
        ("smoke_portfolio_v1", mod._SMOKE_PORTFOLIO_YAML),
    ):
        p = tmp_path / f"{name}.alpha.yaml"
        p.write_text(yaml, encoding="utf-8")
        paths.append(p)
    return paths


def test_backtest_trade_path_parity_hash_stable_no_cache(tmp_path: Path) -> None:
    mod = _load_smoke()
    paths = _write_smoke_alphas(mod, tmp_path)

    c1 = mod._build(paths, seed=42)
    c2 = mod._build(paths, seed=42)

    orch1 = c1["_orchestrator"][0]
    orch2 = c2["_orchestrator"][0]

    # The run must actually trade, else the parity hash is trivially equal.
    assert orch1.trade_journal is not None
    assert len(list(orch1.trade_journal.query())) > 0

    assert compute_parity_hash(orch1) == compute_parity_hash(orch2)
