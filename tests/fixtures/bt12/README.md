# BT-12 post-fix backtest return fixtures

Per-alpha OOS daily return series consumed by
`tests/acceptance/test_bt12_reference_alpha_validation.py`.

Each JSON file is a **deterministic surrogate** (seeded Gaussian, μ=0.006,
σ=0.005, 240 bars) calibrated to clear the F-2 CPCV and DSR gates. Replace
with artefact-store equity curves from a full post-fix `run_backtest.py` replay
when available; update the JSON and the acceptance test commit message in the
same PR.

Regenerate (after intentional algorithm change):

```bash
uv run python scripts/generate_bt12_fixtures.py
uv run pytest tests/acceptance/test_bt12_reference_alpha_validation.py -q
```

## Replay-derived fixtures (operator)

Short synth replays produce zero PnL for most reference alphas; CI keeps
**surrogate** series (`source: surrogate_v1`) for gate wiring.

When disk-cache backtests are available::

    uv run python scripts/collect_bt12_replay_returns.py   # probe only
    # After gates pass on full-session curves:
    uv run python scripts/collect_bt12_replay_returns.py --write-fixtures

Then re-pin ``_FIXTURE_GOLDEN_HASHES`` in
``tests/acceptance/test_bt12_reference_alpha_validation.py``.

