# Data adjustment policy (BT-18)

## Policy

Feelies backtests and intraday replays use **raw, unadjusted** L1 NBBO and trade
prints within a single regular-hours session. The ingestion layer does not apply
split or dividend adjustment factors, and the fill model does not synthesize
corporate-action price jumps.

## Why it matters

A split or dividend **ex-date** inside a replay window produces a real price
discontinuity on the tape. If the feed (or operator) silently mixes adjusted and
unadjusted marks across that boundary, level-anchored sensors — Kyle-lambda,
realized volatility, micro-price — will see a spurious structural break that is
not microstructure alpha.

## Operator contract

1. Keep each backtest replay inside **one session** on **one adjustment regime**
   (raw throughout).
2. Do **not** let a replay calendar span a known ex-date for a universe symbol
   unless you have explicitly adjusted prices at the boundary (not implemented in
   the platform today).
3. Maintain `ex_dates.yaml` under
   `src/feelies/storage/reference/corporate_actions/` (or point
   `ex_date_calendar_path` in `platform.yaml` at your own file).

## Load-time guard

When `backtest_enforce_ex_date_guard: true` (default) and `ex_date_calendar_path`
is set, `build_platform()` scans the replay event log’s ET date span and raises
`ConfigurationError` if any listed symbol has a split/dividend ex-date inside that
span. This is a **data-integrity** check only; it does not alter fills or sensor
math.

To disable (research escape hatch):

```yaml
backtest_enforce_ex_date_guard: false
```

## Reference calendar

See `src/feelies/storage/reference/corporate_actions/ex_dates.yaml`. Entries use:

```yaml
entries:
  - symbol: AAPL
    ex_date: "2026-06-15"
    kind: DIVIDEND
    note: "optional operator note"
```

Kinds: `SPLIT`, `DIVIDEND`.
