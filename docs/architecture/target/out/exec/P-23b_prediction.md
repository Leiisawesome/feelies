# P-23b pre-registered prediction

BASE: `ec94e6c24fcc30219d86577a886912b75a9c9bae` (`arch/exec`, branch `exec/P-23b`)
PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-P-23b.json`
BASELINE GREEN. 5247 passed / 0 failed / 44 skipped / 2 xfailed / exit 0.
Determinism corpus 148 passed / 0 failed. Parity count 64.

R2 prices a deferred aggressive fill on the quote prevailing at arrival
(`q_p`). R1 is not in this rung.

## Parity

NONE. All 64 constants unchanged.
APP oracle stays 10 fills / net 24.61 / trade hash
`18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`.

## R-SYN

Production engine, C_SYN seed 11, n = 36000, market tape. 29 aggressive
MARKET fills. 15 change. Fees on those 15 do not change. Cash, fees
included, +6.28. Store net (realized + unrealized − fees) −137.29 →
−131.01. No drawdown flip. The other 14 aggressive fills, and every
non-aggressive fill, are identical.

| # | order | side | qty | old | new |
|---:|---|---|---:|---:|---:|
| 1 | `30b2e0f84fbfc1ff` | BUY | 125 | 99.79 | 99.80 |
| 2 | `a4bcf2eb6ea86371` | SELL | 124 | 99.62 | 99.61 |
| 3 | `2dac5e4ad29ea13f` | SELL | 125 | 99.62 | 99.61 |
| 4 | `eeea0e1364fcd23a` | BUY | 125 | 99.61 | 99.60 |
| 5 | `80186822d3f0e4d0` | BUY | 125 | 99.61 | 99.60 |
| 6 | `1c297266b6dd5bee` | SELL | 125 | 99.33 | 99.34 |
| 7 | `bb7eb3562b12d7e3` | SELL | 125 | 99.33 | 99.34 |
| 8 | `74cee5cf7d1af21a` | BUY | 125 | 99.71 | 99.70 |
| 9 | `fcd631f3589e8434` | BUY | 125 | 99.71 | 99.70 |
| 10 | `d9b00d88b36e00f1` | BUY | 126 | 99.09 | 99.10 |
| 11 | `89e7c364bac79d9f` | BUY | 126 | 99.09 | 99.10 |
| 12 | `5258e8556c6d87eb` | SELL | 126 | 98.93 | 98.94 |
| 13 | `ce38101f97ce59a8` | SELL | 126 | 98.93 | 98.94 |
| 14 | `579ec9d803a66ba1` | SELL | 126 | 98.86 | 98.87 |
| 15 | `fa40a11edf997707` | SELL | 126 | 98.86 | 98.87 |

## R-FIX

Reference engine and rail, APP 2026-03-26. Shadow reprice of the
unmodified run: 32 aggressive MARKET exits, 21 change, 0 entries, cash
+$43.91, first-order store net −1252.59 → −1208.68. No `q_p` reject.

The live run matches that shadow up to the signal at 13:00:00.095 ET
(APP, `1774544400095864399`). That signal is admitted. Under today's
book it is rejected, `per-alpha drawdown 5.01% >= limit 5.0%`. Under
the repriced book the high-water mark is still the $25,000 alpha equity
and the drawdown is 4.83472%. Every one of the 21 exits is already in
the book at that check, so the equity adjustment is the full $43.91.
Divergence starts at that signal's `OrderRequest`. Nothing after it is
predicted. Nothing before it differs except these 21 exit prices, their
fees, and the PnL those fees and prices produce.

Legs are `qty@price fee`. Cash delta is the fill cash including fees.

| # | order | side | old | new | Δ |
|---:|---|---|---|---|---:|
| 1 | `APP\|sig_position_fixture_v1\|35357\|LONG\|EXIT\|1` | SELL | 40@394.00 fee 13.26 + 23@393.91 fee 7.78 | 40@393.99 fee 13.46 + 23@393.91 fee 7.89 | −0.71 |
| 2 | `APP\|sig_position_fixture_v1\|67658\|LONG\|EXIT\|1` | SELL | 47@395.98 fee 13.88 | 47@395.99 fee 9.18 | +5.17 |
| 3 | `APP\|sig_position_fixture_v1\|76561\|LONG\|EXIT\|1` | SELL | 20@395.07 fee 2.31 + 27@395.02 fee 2.99 | 20@395.05 fee 3.81 + 27@394.95 fee 5.02 | −5.82 |
| 4 | `APP\|sig_position_fixture_v1\|86512\|LONG\|EXIT\|1` | SELL | 20@390.71 fee 6.70 + 43@390.39 fee 14.01 | 20@390.71 fee 6.80 + 43@390.38 fee 14.23 | −0.75 |
| 5 | `APP\|sig_position_fixture_v1\|90028\|SHORT\|EXIT\|1` | BUY | 40@394.50 fee 5.67 + 7@394.52 fee 1.28 | 40@394.52 fee 7.67 + 7@394.53 fee 1.63 | −3.22 |
| 6 | `APP\|sig_position_fixture_v1\|97335\|SHORT\|EXIT\|1` | BUY | 63@394.05 fee 17.23 | 63@394.05 fee 17.55 | −0.32 |
| 7 | `APP\|sig_position_fixture_v1\|103211\|SHORT\|EXIT\|1` | BUY | 40@394.34 fee 0.94 + 23@394.43 fee 0.69 | 40@394.35 fee 0.94 + 23@394.45 fee 0.69 | −0.86 |
| 8 | `APP\|sig_position_fixture_v1\|110926\|LONG\|EXIT\|1` | SELL | 47@393.45 fee 10.59 | 40@393.44 fee 9.06 + 7@393.42 fee 1.87 | −0.95 |
| 9 | `APP\|sig_position_fixture_v1\|113838\|SHORT\|EXIT\|1` | BUY | 40@394.71 fee 6.67 + 7@394.73 fee 1.46 | 20@394.71 fee 3.51 + 27@394.82 fee 4.62 | −2.83 |
| 10 | `APP\|sig_position_fixture_v1\|117616\|LONG\|EXIT\|1` | SELL | 40@395.81 fee 25.47 + 7@395.76 fee 4.75 | 20@395.81 fee 12.91 + 27@395.41 fee 17.30 | −10.44 |
| 11 | `APP\|sig_position_fixture_v1\|124103\|LONG\|EXIT\|1` | SELL | 20@394.19 fee 4.11 + 27@394.07 fee 5.42 | 20@394.18 fee 4.21 + 27@394.07 fee 5.56 | −0.44 |
| 12 | `APP\|sig_position_fixture_v1\|125806\|SHORT\|EXIT\|1` | BUY | 40@394.01 fee 9.07 + 7@394.03 fee 1.88 | 40@394.02 fee 10.47 + 7@394.04 fee 2.12 | −2.11 |
| 13 | `APP\|sig_position_fixture_v1\|127601\|LONG\|EXIT\|1` | SELL | 40@394.57 fee 12.07 + 7@394.55 fee 2.40 | 20@394.68 fee 5.31 + 27@394.53 fee 7.04 | +3.38 |
| 14 | `APP\|sig_position_fixture_v1\|135672\|SHORT\|EXIT\|1` | BUY | 47@398.08 fee 15.53 | 40@398.10 fee 13.27 + 7@398.13 fee 2.61 | −1.50 |
| 15 | `APP\|sig_position_fixture_v1\|154530\|SHORT\|EXIT\|1` | BUY | 20@399.43 fee 7.31 + 42@399.79 fee 14.97 | 20@399.09 fee 4.41 + 42@399.30 fee 8.88 | +36.37 |
| 16 | `APP\|sig_position_fixture_v1\|158957\|LONG\|EXIT\|1` | SELL | 20@398.19 fee 1.05 + 27@398.19 fee 1.30 | 20@398.08 fee 8.71 + 27@397.81 fee 11.64 | −30.46 |
| 17 | `APP\|sig_position_fixture_v1\|160794\|SHORT\|EXIT\|1` | BUY | 20@396.60 fee 5.51 + 27@396.77 fee 7.32 | 40@396.10 fee 1.87 + 7@396.10 fee 0.62 | +38.43 |
| 18 | `APP\|sig_position_fixture_v1\|162329\|LONG\|EXIT\|1` | SELL | 40@396.59 fee 17.67 + 7@396.56 fee 3.38 | 20@396.59 fee 9.01 + 27@396.32 fee 12.04 | −7.08 |
| 19 | `APP\|sig_position_fixture_v1\|165073\|LONG\|EXIT\|1` | SELL | 60@398.05 fee 11.63 + 2@398.04 fee 0.73 | 40@398.05 fee 7.87 + 22@398.00 fee 4.49 | −1.08 |
| 20 | `APP\|sig_position_fixture_v1\|166905\|SHORT\|EXIT\|1` | BUY | 40@398.96 fee 13.67 + 22@399.05 fee 7.68 | 40@398.95 fee 11.47 + 22@399.02 fee 6.47 | +4.47 |
| 21 | `APP\|sig_position_fixture_v1\|169861\|SHORT\|EXIT\|1` | BUY | 20@399.06 fee 13.41 + 42@399.74 fee 27.78 | 20@398.83 fee 11.41 + 42@399.41 fee 23.58 | +24.66 |

## Battery and kill

Synthetic members stay green at stage E with A3b and A4 restated
(R2-2). Real `battery_real` stays 12/12.

m3, exact post-R2 statistics:

| tape | mean | share or counts |
|---|---:|---|
| barriers | 23.255 | share 0.685 |
| swapped | 128.415 | share 0.395 |
| deadline | 124.565 | 104 favorable / 80 horizon / 16 adverse |
| band | −64.945 | residual −0.0472; 122 / 78 |

Kill 11/11. `--control` 0 failures. B7 is killed by an A5 clause. B8 is
killed by an A2 clause.

## ADDED

Stage A, no `FEELIES_*` overrides. `pass` is a real pass. Each router
case is parametrized `backtest` and `passive` except the marketable-limit
mid, which is the passive router only.

| Node id | Stage A |
|---|---|
| `tests/execution/test_r2_pricing_at_arrival.py::test_no_quote_in_window_prices_the_submit_quote[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_no_quote_in_window_prices_the_submit_quote[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_flush_at_arrival_prices_the_flush_quote[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_flush_at_arrival_prices_the_flush_quote[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_locked_arrival_quote_rejects[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_locked_arrival_quote_rejects[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_locked_flush_quote_fills_at_arrival_quote[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_locked_flush_quote_fills_at_arrival_quote[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_other_symbol_does_not_price_the_order[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_other_symbol_does_not_price_the_order[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_in_window_quote_prices_over_the_flush_quote[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_in_window_quote_prices_over_the_flush_quote[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_zero_depth_on_arrival_quote_rejects[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_zero_depth_on_arrival_quote_rejects[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_depth_on_arrival_quote_fills_when_flush_is_empty[backtest]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_depth_on_arrival_quote_fills_when_flush_is_empty[passive]` | pass |
| `tests/execution/test_r2_pricing_at_arrival.py::test_marketable_limit_is_checked_on_the_arrival_mid` | pass |
| `tests/position_engine/test_battery_m6_injection_syn.py::test_a3b_rejects_an_exit_better_than_the_arrival_quote` | pass |

## Plain-pytest capture

| | passed | failed | skipped | xfailed |
|---|---:|---:|---:|---:|
| pre-P-23b | 5247 | 0 | 44 | 2 |
| post-P-23b | 5265 | 0 | 44 | 2 |

Pre-push under the gate expression moves 5232 passed / 5 skipped /
55 deselected / 1 xfailed to 5250 passed / 5 skipped / 55 deselected /
1 xfailed. Any other move is a STOP.

## MODIFIED

The 10 R2-PIN assertions. Each keeps its original intent in the docstring
and takes the Q5 value under R2-1.

| Node id | Today | After R2 |
|---|---|---|
| `tests/execution/test_router_latency.py::TestBacktestRouterLatencyQueue::test_nonzero_latency_defers_fill_until_post_eligibility_quote` | 99.10 | 100.10 |
| `tests/execution/test_router_latency.py::TestPassiveLimitRouterLatencyQueue::test_nonzero_latency_market_defers_to_later_quote` | 99.10 | 100.10 |
| `tests/execution/test_router_fill_timing_parity.py::TestThroughFillInsideLatencyWindow::test_fill_prices_off_post_eligibility_quote_not_stale_cross` | 99.98 | 99.90 |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_market_rejects_zero_depth_at_fill_quote` | REJECTED, zero depth on the flush quote | FILLED at 150.02 |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_market_queues_despite_zero_depth_on_submit_quote` | FILLED | REJECTED, zero depth on `q_p` |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_marketable_limit_rejects_when_mid_exceeds_limit_after_latency` | REJECTED, mid through the limit | FILLED at 150.02 |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_marketable_limit_same_order_id_retry_after_deferred_reject` | first terminal ack REJECTED | FILLED at 150.02 |
| `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_same_order_id_allowed_after_deferred_reject` | REJECTED, zero depth on the flush quote | FILLED at 100.10 |
| `tests/kernel/test_orchestrator.py::TestHaltModeling::test_halt_suppresses_passive_router_fill_paths` | 150.90 | 150.50 |
| `tests/kernel/test_position_requirement_execution.py::test_position_requirement_exits_the_full_slice_at_stop_slippage` | `later[0].bid` = 99.79 | 99.78 |

Member 6 helpers `check_a3` / `check_a4` in `tests/position_engine/scenarios.py`.
A3b compares an exit leg with the executable side of the quote prevailing
at arrival. A4 requires the V3a gap exit to equal that side (9976) and to
stay strictly worse than the barrier (9979).

## Amendment A

The original text above is unchanged. This section supersedes one row.

`tests/execution/test_router_fill_timing_parity.py::TestThroughFillInsideLatencyWindow::test_fill_prices_off_post_eligibility_quote_not_stale_cross`
moves from MODIFIED to UNCHANGED. The fill stays 99.98, `FILLED_BY_THROUGH`.
The census scratch patch also repriced resting limits that are marketable
when they go live. That is outside R2-1's approved scope, which is the
deferred aggressive flush only. MODIFIED is the other 9 R2-PINs. Those 9
census Q5 values were reproduced under R2-1 exactly. No other prediction
row changes.

## Amendment C

The original text above is unchanged. This section supersedes the R-FIX
divergence point.

R-FIX: exact through the predicted 21 repriced exits and the 110926
split; then a sequence shift of +2 renames all later orders (content
identical; D-1(c): only sequence fields differ, 991 RegimeState + 1
RiskVerdict); the first behavioural divergence is the renamed limit's
drain draw, FILLED on 113844 (1774536976116184797), reproduced by C-1.
Unpredicted after that point. The census path-dependence analysis
missed identity-keyed RNG.

## Amendment D

The original text above is unchanged. This section adds two known-answer
rows the census omitted.

Known-answer changes #3 and #4 are
`test_m5_invalidation_at_take_profit` and `test_m5_deadline_beyond_stop`.
The census Q4 kill run under R2 had no `--control`, so the reference's own
failure counted as a B2 kill. After the constructions place the tie off
the arrival quote, the prediction is: all three m5 collision tests green
on the reference; B2 still killed by an m5 collision property; control 0.
