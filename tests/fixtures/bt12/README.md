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
