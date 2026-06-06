# BT-12 post-fix backtest return fixtures

Per-alpha OOS daily return series consumed by
`tests/acceptance/test_bt12_reference_alpha_validation.py`.

Each JSON file is a **deterministic surrogate** (seeded Gaussian, μ=0.006,
σ=0.005, 240 bars) calibrated to clear the F-2 CPCV and DSR gates (`source:
surrogate_v1`).  Short synth replays do not produce usable per-alpha return
curves for most reference alphas, so CI keeps these surrogates for gate wiring
until full-session backtest artefacts land in the research store.

Regenerate (after intentional algorithm or fixture-policy change):

```bash
uv run python scripts/generate_bt12_fixtures.py
uv run pytest tests/acceptance/test_bt12_reference_alpha_validation.py -q
```

Then re-pin ``_FIXTURE_GOLDEN_HASHES`` in
``tests/acceptance/test_bt12_reference_alpha_validation.py`` in the same PR.

Replacing surrogates with replay-derived curves requires a new fixture schema,
a working artefact pipeline (disk-cache or research store), and an explicit
re-baseline of the golden hashes — not a one-off script in ``scripts/``.
