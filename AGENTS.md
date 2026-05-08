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

### Linting and type checking

- `uv run ruff check src/ tests/` — linting (must pass)
- `uv run ruff format --check src/ tests/` — formatting check (pre-existing 212 files unformatted in repo)
- `uv run mypy src/feelies` — strict type checking (requires all extras installed including `massive`)

### Testing

- `uv run pytest` — full suite (~2095 tests)
- `uv run pytest -m "not functional and not slow"` — skip network/benchmark tests
- `uv run pytest tests/determinism/` — determinism parity hash tests (54 tests)
- `uv run pytest tests/integration/test_phase4_e2e.py` — e2e pipeline test (8 tests)

### Known pre-existing acceptance test failures (as of main)

Two acceptance tests fail because `alphas/pofi_benign_midcap_v1/` already contains a `trend_mechanism:` block but the acceptance test expects it to be absent (v0.2 baseline parity):
- `tests/acceptance/test_strict_mode_default_true.py::TestV02ParityPreservedOnExplicitOptOut::test_v02_baseline_alpha_refused_under_default`
- `tests/acceptance/test_v02_no_trend_mechanism_parity.py::test_baseline_alpha_yaml_has_no_trend_mechanism_block`
- `tests/acceptance/test_v02_no_trend_mechanism_parity.py::test_baseline_alpha_loads_under_v03_default`

These are not environment issues — they reflect a drift between the reference alpha YAML and the acceptance test expectations on the `main` branch.

### Gotchas

- All three extras (`dev`, `massive`, `portfolio`) must be installed for the mypy acceptance test to pass (`test_mypy_strict_clean_on_src_feelies`). If `massive` is not installed, mypy reports `import-not-found` errors for `massive` and `websockets`.
- The `uv` binary is installed via pip (`pip install uv`) and lives at `~/.local/bin/uv`. Ensure `~/.local/bin` is on `PATH`.
- No `.env` file is needed to run the test suite. `MASSIVE_API_KEY` is only required for `pytest -m functional` (network-backed) tests and `scripts/run_backtest.py`.
