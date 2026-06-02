# Paper RTH Test Runbook

## Prerequisites

1. IB Gateway paper account on `localhost:4002`
2. `MASSIVE_API_KEY` in environment or `.env`
3. US RTH (9:30–16:00 ET) unless `PAPER_RTH_FORCE=1`

## session_open_ns

Compute for the run day (DST-safe):

```python
from datetime import datetime
from zoneinfo import ZoneInfo

session_open_ns = int(
    datetime(2026, 5, 25, 9, 30, tzinfo=ZoneInfo("America/New_York")).timestamp() * 1e9
)
```

Set in `configs/paper_smoke_rth.yaml` before each session.

## Tier 1 (every PR)

```bash
uv run pytest -m "not functional and not slow"
```

## Tier 2–3 (RTH)

```bash
uv run pytest tests/broker/ib/test_ib_functional.py tests/integration/test_paper_rth_e2e.py -m paper_rth
```

## Manual paper session

```bash
uv run python scripts/run_paper.py \
  --config configs/paper_smoke_rth.yaml \
  --max-runtime-s 600 \
  --run-dir runs/paper_$(date +%F) \
  --emit-timing-jsonl --emit-order-acks-jsonl --emit-signals-jsonl --emit-fills-jsonl
```

## Backtest vs paper compare

```bash
uv run python scripts/run_backtest.py --emit-fills-jsonl ... | tee backtest.log
uv run python scripts/split_backtest_emit.py --run-dir runs/backtest_today --input backtest.log
uv run python scripts/compare_paper_backtest.py \
  --paper-run-dir runs/paper_today \
  --backtest-run-dir runs/backtest_today --json
```

## Weekly soak

```bash
uv run python scripts/run_paper_soak.py \
  --config configs/paper_smoke_rth.yaml \
  --duration-s 7200 \
  --run-dir runs/soak_$(date +%F)
```

## Failure injection (manual)

| Fault | Expected |
|-------|----------|
| IB Gateway kill mid-session | DEGRADED; no duplicate submits on restart |
| WS disconnect | Macro DEGRADED when `degrade_on_data_gap: true` |
| Wrong ib_port 4001 | Bootstrap warning or connect failure |
| SIGINT during fill drain | Phase 0 teardown preserves fill in journal |

Use `kill -INT` (not SIGTERM) until SIGTERM handler is wired.
