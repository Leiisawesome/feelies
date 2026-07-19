# AGENTS.md

Shared operator reference for Cursor, Claude Code, and other agents working
in this repo. Domain depth lives in `.cursor/skills/`; always-applied rules
live in `.cursor/rules/`.

## Canonical references (do not duplicate elsewhere)

| Topic | Canonical source |
|-------|------------------|
| Platform invariants + glossary | `.cursor/rules/platform-invariants.mdc` |
| Coding behavior (simplicity, surgical diffs) | `.cursor/rules/karpathy-guidelines.mdc` |
| Skill routing + layer map | `.cursor/skills/README.md` |
| Alpha YAML gates (G2–G16) | `alphas/SCHEMA.md` |
| Architecture spec | `docs/three_layer_architecture.md` |

## Overview

Feelies is a self-contained pure-Python deterministic intraday trading platform.
No external databases, message queues, Docker, or web servers are required. The
only external dependency is the optional Massive (Polygon.io) API for market data,
which is mocked/stubbed in the standard test suite.

## Environment

- **Python 3.12+** required
- **Package manager:** `uv` — lockfile is `uv.lock`; always `uv run <cmd>`
- **Virtual env:** `.venv/` at repo root (`uv sync --all-extras` recommended)
- **Credentials:** copy `.env.example` → `.env` for `MASSIVE_API_KEY`; not needed
  for the default test suite. Paper/live requires IB Gateway on port 4002.

## Common commands

```bash
# Fast local test run (skips network and benchmarks)
uv run pytest -m "not functional and not slow"

# Full suite (~4300 tests)
uv run pytest

# Determinism parity hashes
uv run pytest tests/determinism/

# E2E pipeline (no API key)
uv run pytest tests/integration/test_phase4_e2e.py

# Lint + strict mypy (needs dev, massive, portfolio, ib extras)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/feelies

# Operator CLI (read-only promotion forensics)
uv run feelies promote gate-matrix --json

# Smoke pipeline
uv run python scripts/smoke_pipeline.py

# APP backtest baseline (disk cache for APP/2026-03-26 required)
uv run pytest tests/acceptance/test_backtest_app_baseline.py
uv run feelies backtest --config configs/bt_app.yaml --symbol APP --date 2026-03-26
```

Paper RTH (IB Gateway + `MASSIVE_API_KEY` + RTH):

```bash
uv run pytest tests/broker/ib/test_ib_functional.py tests/integration/test_paper_rth_e2e.py -m paper_rth
uv run python scripts/run_paper.py --config configs/paper_smoke_rth.yaml --max-runtime-s 60 --run-dir /tmp/paper_smoke
```

## Test status

The full suite is green on `main` (skips are gated `functional` / `paper_rth` /
per-host perf tests). Re-verify with `uv run pytest` before claiming otherwise.

## Gotchas

- All extras (`dev`, `massive`, `portfolio`, `ib`) must be installed for the
  mypy acceptance test (`test_mypy_strict_clean_on_src_feelies`).
- `uv` is installed via pip and typically lives at `~/.local/bin/uv`.
- Do not restate platform invariants, Karpathy guidelines, or skill tables in
  agent config files — link to the canonical sources above.
