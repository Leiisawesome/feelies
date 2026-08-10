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
| Alpha YAML gates (G1–G17; G13 no-op) | `alphas/SCHEMA.md` |
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

`.github/workflows/ci.yml` runs lint, format, `mypy src/feelies`, and
`pytest -m "not functional and not paper_rth"` on every push and PR. It does not
replace the local full run: `functional` and `paper_rth` never execute in CI, so
anything touching the live Massive feed or IB Gateway is still only ever verified
by hand.

## Adding a test for a safety branch

A green run does not prove the branch executed. Mutate the source and confirm
the new test fails; if it still passes, it is not testing what you think.

This is not a general policy — it is specific to guards on the fail-safe paths
(Inv-11 exits, per-alpha attribution, parity clamps), where the failure mode is
silent. Every defect found in the 2026-08 architecture review was hiding behind a
fixture that covered the one input shape the buggy logic happened to handle:
five in #220 (no `StrategyPositionStore` wired, no resting order live at exit, no
fill landing on cancel, no partial cover, identical entry prices), and in #221 a
test written to pin the `max()` in `_forced_exit_closable_quantity` never reached
it, because that clamp only ran when a resting order existed.

```bash
# Break the guard deliberately, run only the new test, restore, prove the restore.
cp src/feelies/<file>.py /tmp/f.bak
# ...edit the guard to a no-op...
find . -name __pycache__ -type d -prune -exec rm -rf {} +
PYTHONHASHSEED=0 uv run pytest <test file> -q -k <new test>   # MUST fail
cp /tmp/f.bak src/feelies/<file>.py
find . -name __pycache__ -type d -prune -exec rm -rf {} +
PYTHONHASHSEED=0 uv run pytest <test file> -q -k <new test>   # MUST pass again
```

The two `find` calls are not decoration. `cp` back and forth inside one shell
loop can leave Python reusing a `.pyc` built from the other version, and the run
then reports the wrong file's behaviour — in #226 that produced two rounds of
confident nonsense before the cache was cleared.

**Always end on a pristine run and require it green.** A red "pristine" means the
restore failed, not that the test is wrong; #226 also lost a fix to a `git
checkout --` buried in a mutation helper and spent a while reading the resulting
failures as real. Verify the restore before believing anything the mutation told
you.

Surviving a mutation is acceptable when a second guard independently holds the
same invariant — that is the right shape for a behavioural test. Establish it by
removing both and confirming the test then fails, and say so in the docstring.

## Gotchas

- All extras (`dev`, `massive`, `portfolio`, `ib`) must be installed for the
  mypy acceptance test (`test_mypy_strict_clean_on_src_feelies`).
- `uv` is installed via pip and typically lives at `~/.local/bin/uv`.
- Do not restate platform invariants, Karpathy guidelines, or skill tables in
  agent config files — link to the canonical sources above.
