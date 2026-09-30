# P-23a pre-registered prediction

BASE: `b7242774ec5778f5044dcb0878c87abcc3102044` (`arch/exec`, branch `exec/P-23a`)
PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-P-23a.json`
BASELINE GREEN. 5234 passed / 0 failed / 44 skipped / 2 xfailed / exit 0.
Determinism corpus 148 passed / 0 failed. Parity count 64.

## Parity

NONE. 64/64 constants unchanged.
APP oracle stays 10 fills / net 24.61 / trade hash
`18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`.

## Fills and PnL

Measured at the base, before any stamp change. Identity is order, quantity,
and price of each journal leg, plus the position-store net
(realized + unrealized − position fees), which is the report net.

| Run | Engine | Fills | Store net |
|---|---|---:|---:|
| R-ORC | production, `configs/bt_app.yaml`, APP 2026-03-26 | 10 | 24.61 |
| R-FIX | reference engine and rail, same APP session | 91 | −1252.59 |
| R-SYN | production, C_SYN seed 11, n = 36000, market tape | 29 | −137.29 |

After the change these three are identical. If `hazard_exit` or
`deferral_cap` moves any fill or exit on any of the three, this prediction
is false: revert.

## Invariants

After the change, on R-ORC, R-FIX, and R-SYN: I1 violations 0; I3 violations
0; I2 violations only on PENDING (`GateDecision`, `DeRiskRequirement`,
`PositionSnapshot`). PENDING stays strict.

## Reference battery and kill

Unchanged. Synthetic members 1–6 and 11 stay green at stage E. Real
`battery_real` stays 9/9 plus the one test this rung adds. Kill 11/11.
Reference control 0 failures.

## ADDED

Stage A, no `FEELIES_*` overrides. `pass` is a real pass.

| Node id | Stage A |
|---|---|
| `tests/conformance/test_time_classes.py::test_every_bus_event_declares_time_class` | pass |
| `tests/conformance/test_time_classes.py::test_time_class_is_not_a_field_and_canonical_omits_it` | pass |
| `tests/conformance/test_causality_invariant.py::test_synthetic_seed11_i1_i2_i3` | pass |
| `tests/conformance/test_causality_invariant.py::test_reference_app_i2_only_pending` | pass |
| `tests/conformance/test_cross_class_age.py::test_hazard_age_uses_visible_time` | pass |
| `tests/conformance/test_cross_class_age.py::test_deferral_deadline_uses_visible_time` | pass |
| `tests/conformance/test_action_time_producers.py::test_action_time_constructors_are_approved_or_known` | pass |

## Plain-pytest capture

| | passed | failed | skipped | xfailed |
|---|---:|---:|---:|---:|
| pre-P-23a | 5234 | 0 | 44 | 2 |
| post-P-23a | 5241 | 0 | 44 | 2 |

The gate expression is unchanged (`not functional and not paper_rth and not battery_real`).
Pre-push under that expression moves 5220 passed / 5 skipped / 54 deselected to
5226 passed / 5 skipped / 55 deselected (the reference-session test is
deselected; the other six added tests pass). Any other move is a STOP.

## MODIFIED (A4)

Tests that pin a behaviour this rung deliberately changes. Each keeps its
protective intent. The published ACK stamp becomes the clock at publication.
The old clock-plus-latency value remains the fill-eligibility time. Any red
test not in this table or in ADDED is a STOP; it is not edited to green.

| Node id | Before | After |
|---|---|---|
| `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_latency_injection` | published ACK `timestamp_ns == 6000` | published `== 5000` (clock); eligibility stays 6000 |
| `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_deferred_market_fill_ts_no_double_latency_when_clock_tracks_exchange` | published ACK `== 2000` | published `== 1000`; eligibility stays 2000; FILLED `== 2500` unchanged |
| `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_deferred_market_timeout_reject_ts_not_before_ack_when_clock_tracks_exchange` | published ACK `== 2000` | published `== 1000`; eligibility stays 2000; reject still `>=` the published ack |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_market_fill_latency` | published ACK `== 6000` | published `== 5000`; eligibility stays 6000 |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_aggressive_fill_ts_no_double_latency_when_clock_tracks_exchange` | published ACK `== 2000` | published `== 1000`; eligibility stays 2000; FILLED `== 2500` unchanged |
| `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_aggressive_timeout_reject_ts_not_before_ack_when_clock_tracks_exchange` | published ACK `== 2000` | published `== 1000`; eligibility stays 2000 |
| `tests/execution/test_router_fill_timing_parity.py::TestCancelReplenishAtRestingLevel::test_explicit_cancel_inside_window_floors_ts_and_blocks_fill` | published ACK `== 7000` | published `== 5000`; eligibility stays 7000 |
| `tests/execution/test_pr12_cleanup.py::TestPartialFillDistinctTimestamps::test_partial_and_final_fill_have_distinct_timestamps` | final stamp `>` partial stamp | renamed `test_partial_and_final_fill_order_by_sequence`: bus order, ack sequence, both stamps equal the publication clock |

## MODIFIED (B-3)

The shared helper `_submit_both` is one ACK pin. Both callers are in the
modified set. The helper is rewritten once: published stamp is the clock at
publication (5000); eligibility stays 6000 on both the resting limit and the
deferred market.

| Node id | Before | After |
|---|---|---|
| `tests/execution/test_router_fill_timing_parity.py::TestPassiveAggressiveEligibilityParity::test_both_paths_share_one_exchange_time_deadline` | both published acks `== 6000` | published `== 5000`; both paths' eligibility stays 6000 |
| `tests/execution/test_router_fill_timing_parity.py::TestPassiveAggressiveEligibilityParity::test_a_wall_clock_past_the_deadline_makes_neither_path_eligible` | both published acks `== 6000` | published `== 5000`; both paths' eligibility stays 6000 |

## Parity amendment (C-2)

The NONE paragraph above is the prediction as first written. It is superseded
by this pre-registered break. Exactly two constants move. Every other
constant is unchanged. The legacy APP oracle is unchanged.

| Constant | Payload diff |
|---|---|
| `EXPECTED_MARKET_FILL_HASH` | OrderAck FILLED (depth-walk final leg, order o3) `timestamp_ns` 1 → 0, ×1. ACKNOWLEDGED and PARTIALLY_FILLED stay 0. Count unchanged. |
| `EXPECTED_RISK_VERDICT_HASH` | RiskVerdict `timestamp_ns` 1000000000 → 0, 2000000000 → 0, 3000000000 → 0, 4000000000 → 0, ×4. Actions stay ALLOW, SCALE_DOWN, REJECT, FORCE_FLATTEN. Count unchanged. |

No predicted diff touches price, quantity, side, order_id, status, or ordering.
The other 62 constants, including `_BASELINE_TRADE_PARITY_HASH`,
`_BASELINE_NET_PNL`, `_BASELINE_FILL_COUNT`, and `_BASELINE_CONFIG_HASH`,
are NONE.

Constant-value edits only, added to the modified set:

| Node id | Before | After |
|---|---|---|
| `tests/determinism/test_market_fill_replay.py::test_market_fill_replay_matches_locked_baseline` | hash `da66dd36…` | the hash of the payload above |
| `tests/determinism/test_risk_verdict_replay.py::test_risk_verdict_stream_matches_locked_baseline` | hash `b388a2c5…` | the hash of the four zero stamps |
| `tests/determinism/test_parity_manifest.py::test_manifest_fingerprint_matches_locked_value` | fingerprint `3ae15104…` | the checksum of the manifest after the two hashes above move. Not one of the 64. |

## Wrapper stamps (E-1 / D-3)

The six `risk_wrapper.py` action-time constructors move to the publication
clock. D-3 for that edit, recorded before the edit: no parity constant moves.
The C-1 payload diffs stay exactly the two timestamp hashes above. The legacy
oracle stays fixed.
