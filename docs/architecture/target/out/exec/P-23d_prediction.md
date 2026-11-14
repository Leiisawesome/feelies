# P-23d pre-registered prediction

BASE: `f4e615bb412a6d67b1880ff92919e01d10d17161` (`arch/exec`, branch `exec/P-23d`)
PATCH: `a5663badc0a54fdae8680391800cf1bd3a7607dec9e313cfeb75b5aeec94ac26`
Option C. Order ids are unchanged. The drain draw is the only production change.

## Seed

```python
seed = (
    f"{quote.symbol}|{quote.sequence_number}|"
    f"{quote.exchange_timestamp_ns}|{pending.side.name}|{pending.limit_price}"
)
```

`quote.sequence_number` is the vendor field. `ticks_at_level` and `order_id` are not inputs. Orders at the same side, level and event share one draw (comonotone).

## Declared break

PREDICTED MOVES: `_BASELINE_NET_PNL` changed; `_BASELINE_TRADE_PARITY_HASH` changed; `_BASELINE_FILL_COUNT` unchanged.
FILLS: yes, through the drain draw.
MECHANISM: the drain uniform is keyed on market content (symbol, vendor sequence number, exchange timestamp, side, level). Orders at the same side, level and event share one draw. `order_id` and `ticks_at_level` are per-order state and are not inputs.

The operator declares the break at merge, after the exact-match check.

## Approved exemption

Exactly 10 fills / net 26.61 / trade hash `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`, replacing 24.61 / `18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`. Any other value stops the rung.

32-draw ensembles (net -> count), recorded with the pin:

- old: {24.03: 2, 24.61: 1, 25.70: 1, 26.61: 12, 27.19: 16}. Mean 26.6478125, range 24.03 to 27.19.
- C: {24.03: 1, 24.61: 3, 26.61: 12, 27.19: 16}. Mean 26.631875, range 24.03 to 27.19.

The pinned realization is the unsalted C draw, net 26.61.

## Oracle fills under C

Order ids are the legacy ids. Rows 4 and 7 differ from legacy `18f6bb4e` in timestamp only (hash-inert). Rows 6 and 9 differ in timestamp, price and type.

| # | time_ns | price | qty | type | side | order_id |
|---:|---:|---:|---:|---|---|---|
| 1 | 1774536328002102739 | 393.29 | 19 | DRAIN | BUY | 5c49cedfaaee8215 |
| 2 | 1774536615403234682 | 393.66 | 19 | DRAIN | SELL | f7c25acacee26c2b |
| 3 | 1774539482694291617 | 394.53 | 21 | THROUGH | BUY | 6ef58dc5fb2cc1a3 |
| 4 | 1774539601841579983 | 395.49 | 21 | DRAIN | SELL | 47afc75a80a0ce38 |
| 5 | 1774544099152748135 | 397.55 | 20 | DRAIN | SELL | 7c68729d85f36fde |
| 6 | 1774544292131306598 | 397.07 | 20 | THROUGH | BUY | 9c9f010d7db482b7 |
| 7 | 1774545744382117348 | 396.47 | 16 | DRAIN | SELL | 03911f55b9bd00d5 |
| 8 | 1774546293576312646 | 396.03 | 16 | THROUGH | BUY | 99356493ad32e866 |
| 9 | 1774547955413224159 | 390.50 | 24 | DRAIN | BUY | d6759e840549e27e |
| 10 | 1774548002289888557 | 390.95 | 24 | DRAIN | SELL | c95639ac66cadbcd |

Field-by-field against legacy `18f6bb4e` (qty, side, order_id unchanged on every row):

| # | field | legacy | C |
|---:|---|---|---|
| 4 | time_ns | 1774539601841740034 | 1774539601841579983 |
| 6 | time_ns | 1774544292131273148 | 1774544292131306598 |
| 6 | price | 397.16 | 397.07 |
| 6 | type | DRAIN | THROUGH |
| 7 | time_ns | 1774545744382433717 | 1774545744382117348 |
| 9 | time_ns | 1774547958580901923 | 1774547955413224159 |
| 9 | price | 390.49 | 390.50 |
| 9 | type | THROUGH | DRAIN |

## R-FIX and R-SYN

R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, PassiveLimitOrderRouter): 95 fills / net −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee`. 66 OrderRequests, 62 drain draws. No numeric `EXPECTED_*` / `_BASELINE_*` pin.

R-SYN (market mode, BacktestOrderRouter): 29 fills / net −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Drain evaluations 0. The seed is not on this path.

## S0 movers

Of the 81 module-level `EXPECTED_*` / `_BASELINE_*` names, the bt_app trade oracle is pinned only by `tests/acceptance/test_backtest_app_baseline.py::test_app_20260326_backtest_baseline_from_disk_cache` (`functional`; prepush deselects it; CI job `parity oracle` runs it with `-m ""` and `FEELIES_REQUIRE_BASELINE_CACHE=1`). Under C that test failed on the legacy pins with net 26.61 and hash `c95f4e5c…`. `test_app_baseline_config_contract_hash` pins the config snapshot and passed. Fill count stayed 10.

Movers:

- `_BASELINE_NET_PNL`: 24.61 -> 26.61
- `_BASELINE_TRADE_PARITY_HASH`: `18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb` -> `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`

## S1 classification

32 salts. A salt is PRECONDITION when the scenario the assertion needs did not occur, PROPERTY when the invariant was violated. PROPERTY is 0 on both seeds.

| test | old PRE | old PROP | C PRE | C PROP |
|---|---:|---:|---:|---:|
| test_level_fill_stays_at_limit | 15 | 0 | 14 | 0 |
| test_no_drain_fill_while_off_level | 24 | 0 | 19 | 0 |
| test_passive_fill_zero_spread_cost | 15 | 0 | 14 | 0 |
| test_maker_path_cheaper_than_taker_path | 15 | 0 | 14 | 0 |
| test_passive_fill_latency | 16 | 0 | 14 | 0 |

Precondition held on at least 8 salts in every row (off-level on the old seed is exactly 8).

## Tests

ADDED:

- `tests/execution/test_drain_comonotone.py::test_back_order_does_not_drain_ahead_of_the_front_order`
- `tests/conformance/test_drain_content_invariance.py::test_p1_fill_economics_are_invariant`
- `tests/conformance/test_drain_content_invariance.py::test_p2_fill_economics_are_invariant`
- `tests/conformance/test_drain_content_invariance.py::test_p3_drain_uniforms_follow_content[p3a]`
- `tests/conformance/test_drain_content_invariance.py::test_p3_drain_uniforms_follow_content[p3b]`
- `tests/conformance/test_drain_content_invariance.py::test_p3c_shifted_symbol_does_not_move_app_fills` (`xfail(strict=True)`; reason names P-23c and `horizon_scheduler.py:259`)

MODIFIED:

- `tests/execution/test_passive_limit_router.py::TestThroughFillPriceImprovement::test_level_fill_stays_at_limit`
- `tests/execution/test_passive_limit_router.py::TestLevelFill::test_no_drain_fill_while_off_level`
- `tests/execution/test_passive_limit_router.py::TestCostModel::test_passive_fill_zero_spread_cost`
- `tests/execution/test_passive_limit_router.py::TestCostModel::test_maker_path_cheaper_than_taker_path`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_passive_fill_latency`
- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — router hot-path edit reviewed under P-23d C (source fingerprint refreshed; CI regenerates it via `perfmeasure --mode profile`)
- `tests/acceptance/test_backtest_app_baseline.py::test_app_20260326_backtest_baseline_from_disk_cache` — pins updated to the approved exemption

The five rewritten drain tests pass on `f4e615bb` and on C. The coupling test fails on `f4e615bb` (260 violations) and passes on C.

Fail-first, red on `f4e615bb` before the seed change:

- `tests/execution/test_drain_comonotone.py::test_back_order_does_not_drain_ahead_of_the_front_order`
- `tests/conformance/test_drain_content_invariance.py::test_p1_fill_economics_are_invariant`
- `tests/conformance/test_drain_content_invariance.py::test_p2_fill_economics_are_invariant`

## Findings

- F-P23d-a: the census per-fill time column cannot be reproduced. Moot once the census drain numbers were voided. Record only.
- F-P23d-b: the original D2 spec keyed the draw on a router ordinal, against the standing rule that randomness and identity are keyed on economic content, never on counters.
- F-P23d-c: the census (a) prototype was keyed on the ingest counter `quote.sequence`. Its invariance test only perturbed orchestrator counters, so the counter key passed. Census numbers that depend on the drain key are void.
- F-P23d-d: amendment 1 named `quote.sequence_number` for a probe that had actually used `quote.sequence`. Provenance caught it.
- F-P23d-f: non-trace reads of counter fields. `regime_engine.py:416`; `backtest_prep.py:58`; `backtest_report.py:270,279,383,403-406`; `gate_close_attribution.py:223`; `cross_sectional_tracker.py:132`; `orchestrator.py:3312,4224,4231,4236,4446,5563`. Not fixed here.
- F-P23d-g: five mint sites with no content-derivable trigger (`hazard_exit.py:246`, `exit_composer.py:447` and `:412`, `sized_intent_legs.py:170`, `sized_intent_orders.py:101`); the global `SequenceGenerator` ordinal at `orchestrator.py:3114`; synthetic tapes with vendor `sequence_number` 0. Identity-model track: census and a design decision, scheduled before P-30. Not fixed here.
- F-P23d-h: `horizon_scheduler.py:259` closes horizons for every configured symbol on any symbol's event, so horizons close late in a thin stream when a second symbol is interleaved. Routed to P-23c. P3c is the strict xfail that forces the fix to remove it.
- F-P23d-i: the synthetic battery has 0 passive-drain evaluations (market mode). Coverage gap. Record only.
