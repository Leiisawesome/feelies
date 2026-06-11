# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Feelies is a self-contained pure-Python deterministic intraday trading platform. No external databases, message queues, Docker, or web servers are required. The only external dependency is the optional Massive (Polygon.io) API for market data, which is mocked/stubbed in the standard test suite.

### Environment

- **Python 3.12+** required (system Python is fine)
- **Package manager:** `uv` — the lockfile is `uv.lock`
- **Virtual env:** `.venv/` at repo root, created by `uv sync`
- All commands should be run via `uv run <cmd>` to use the project venv

### Running services

There are no long-running services. The platform is a library + CLI; the "application" is exercised via:

- **Operator CLI:** `uv run feelies promote gate-matrix --json`
- **Smoke pipeline:** `uv run python scripts/smoke_pipeline.py`
- **E2E integration test:** `uv run pytest tests/integration/test_phase4_e2e.py`
- **APP backtest baseline:** `uv run pytest tests/acceptance/test_backtest_app_baseline.py` (disk cache for `APP/2026-03-26` required)
- **APP backtest CLI:** `uv run feelies backtest --config configs/backtest_app.yaml --symbol APP --date 2026-03-26`

### Linting and type checking

- `uv run ruff check src/ tests/` — linting (must pass)
- `uv run ruff format --check src/ tests/` — formatting check (pre-existing 212 files unformatted in repo)
- `uv run mypy src/feelies` — strict type checking (requires all extras installed including `massive`)

### Testing

- `uv run pytest` — full suite (~3350 tests)
- `uv run pytest -m "not functional and not slow"` — skip network/benchmark tests
- `uv run pytest tests/determinism/` — determinism parity hash tests (90 tests)
- `uv run pytest tests/integration/test_phase4_e2e.py` — e2e pipeline test (10 tests)
- **Paper RTH (Tier 2–3, requires IB Gateway + MASSIVE_API_KEY + RTH):** `uv run pytest tests/broker/ib/test_ib_functional.py tests/integration/test_paper_rth_e2e.py -m paper_rth`
- **Paper smoke config:** `uv run python scripts/run_paper.py --config configs/paper_smoke_rth.yaml --max-runtime-s 60 --run-dir /tmp/paper_smoke`

### Known pre-existing acceptance test failures (as of main)

None — the full suite is green on `main` (verified 2026-06-11: 3319 passed, 27 skipped;
the skips are gated `functional` / `paper_rth` / per-host perf tests). The historical
`sig_benign_midcap_v1` trend-mechanism parity failures have been resolved.

### Gotchas

- All three extras (`dev`, `massive`, `portfolio`) must be installed for the mypy acceptance test to pass (`test_mypy_strict_clean_on_src_feelies`). If `massive` is not installed, mypy reports `import-not-found` errors for `massive` and `websockets`.
- The `uv` binary is installed via pip (`pip install uv`) and lives at `~/.local/bin/uv`. Ensure `~/.local/bin` is on `PATH`.
- No `.env` file is needed to run the test suite. `MASSIVE_API_KEY` is only required for `pytest -m functional` (network-backed) tests and `scripts/run_backtest.py`.
