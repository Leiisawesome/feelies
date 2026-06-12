<!--
  File:   docs/research/realized_vol_aggregation_ic.md
  Status: tracked research artifact (audit P2-5).
  Owner:  feature-engine.
-->

# Aggregation policy for `realized_vol_30s` — count-window vs horizon-window

**Decision (locked):** `realized_vol_30s` is exposed to Layer-2 as a
**count-window** z-score (`RollingZscoreFeature`), *not* the event-time
horizon-window z-score (`HorizonWindowedFeature`) used by `ofi_ewma`,
`micro_price`, and `kyle_lambda_60s`. Wiring: `bootstrap._HORIZON_FEATURE_FACTORIES["realized_vol_30s"]`.

This file promotes that decision out of an inline code comment (audit P2-5) so
it is auditable and revisitable rather than buried next to the wiring.

## Why this is the odd one out

Audit P1-1 moved most rolling z-score features from a horizon-blind count
window to a genuine event-time window of width `h`, so the G16
`horizon / half_life` binding has real effect. The natural follow-up was to do
the same for `realized_vol_30s`. The offline IC run (sensor-level RankIC vs
forward mid log-return, cached AAPL) showed the windowing change **regressed**
this sensor:

| horizon | count-window RankIC | horizon-window RankIC |
|--------:|--------------------:|----------------------:|
|   300 s | ~neutral            | ~neutral              |
|   900 s | ~neutral            | ~neutral              |
|  1800 s | **0.523**           | **0.191**             |

Mechanism: volatility is a slowly-varying, persistent quantity. Standardizing
it against a *longer* count baseline (default 2000 samples) preserves the
regime-level signal, whereas a 1800 s event-time window re-references it to a
shorter, noisier local baseline and discards the cross-regime contrast that
carries the predictive content.

## Reproduce

```
uv run python scripts/sensor_feature_ic.py \
    --cache-dir data/cache --symbol AAPL --date 2026-03-26 \
    --horizons 30,120,300,900,1800
```

The harness (`scripts/sensor_feature_ic.py`) replays both feature variants
through the real Layer-1 → Layer-1.5 pipeline and reports RankIC / IC per
`(feature, horizon, variant)`. The `count_window` vs `horizon_window` rows for
`realized_vol_30s_zscore` are the relevant comparison.

## Revisit triggers

Re-run and reconsider if any of these change:

- the sensor's `window_seconds` (currently 30 s) or `warm_after`;
- the universe (the 1800 s result above is single-name AAPL — confirm on a
  thinner mid-cap and a multi-day pool before generalizing);
- the consuming alpha's horizon (the regression is concentrated at 1800 s).

## Status / follow-up

The numbers above were produced during the audit P1-1 follow-up run and are
recorded here verbatim from the wiring comment. They are **single-symbol,
single-day** and should be re-run on the multi-day, multi-symbol panel
described in the sensor audit's Appendix (open question #1) before being
treated as a stable result.
