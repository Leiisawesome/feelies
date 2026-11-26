# P-23a2 pre-registered prediction

BASE: `154ee44c7dfaa21539ba19519678d795ac2ac781` (`arch/exec`, `exec/P-23a2`, 0 commits)
PATCH: `fcc9c2d341e19d5aa1e4be0557cb22e8bcb53ed3af12b5a9313eb2a93cc8ba25` (landing patch s2, 42787 bytes, 19 tracked files)

Committed before any production or test change. The sources at this commit are still `154ee44c`.

## Mechanism

A fill ack is published only once the simulated clock has reached that order's arrival time (`ack_timestamp_ns`). `require_fill_live` raises `FillBeforeLiveError` when `clock_ns < ack_timestamp_ns`. Equality is allowed, and the published stamp is the clock. Reject and cancel acks stamp the clock and have no guard. `HorizonMetricsCollector`, `BasicRiskEngine._emit_dropped_legs_alert`, and `HorizonSignalEngine._emit_metric` stamp the publication clock. `_cached_real` folds `-0.0` to `0.0` before the cache key. The `_session_digest_key` docstring matches the key it builds.

The ratchet shrinks from 14 to exactly these five keys: IB `_fill_to_ack`, `sized_intent_legs._mint`, `sized_intent_orders._mint`, `registry._emit_reading_metrics`, `registry._emit_nonfinite_metric`. PENDING stays empty. `wiring_manifest.py` and the composition-root scanner rows stay unchanged.

## Baseline captured on `154ee44c` before this commit

`tools/exec/baseline.py capture --label pre-P-23a2` on the clean tree: 5329 passed, 0 failed, 44 skipped, exit 0. Determinism 148 passed, 0 failed. Parity constants 64 across 25 modules. BASELINE GREEN. `git.dirty` was false and `git.sha` was `154ee44c`. The JSON stays outside the repo until the baseline commit. No `## P-23a2` heading exists.

## Pre-capture

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Config hash `0a7b81645822f593fe65e6c45fb618940e06c0c9cb116df8e466ea17c4a274ed`. Journal sha256 `03227bb10c52ea32e85ed5ab290a6cf7d5f74ebfcd4683f7b14fa05632cd80be`.
- R-FIX (reference engine): 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`. Config hash `7d04fad61db4e3d2a85a68bb388185fd88c3bce58559ad3f262b888064d0a55d`. Journal sha256 `b00801b20dd306061680249c8c991f635838bdd4ebdeb4f934f24ec4cd346945`.
- R-SYN (C_SYN seed 11, n=36000): 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Config hash `1a6372533bf92f86dfcccc19409d16e1d2de4b85771c839d02473b685ff5c783`. Journal sha256 `6410ad7abc3fba49dd257e548ae6d92f0cc8cfde4bf8b206746459519eee6c5f`.
- Eight-name 2026-03-26: 12 / +19.43 / `6219609611306a8871aeb1cc11d2f3128f43ebe40c6931dc912d44d0d504542d`. Config hash `4a057dbd67c6e5ab8dade98dafef3f2803b8a430f281828c6553e1f6a7ce875b`. Journal sha256 `a7cceaa4bd71ac6ed3ed57f3f5305ab22401cb307e92615fe0e19cd7cc636238`.
- Level-3 snapshot hash: `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce` (14 snapshots). `test_horizon_feature_snapshot_replay` passed.
- Manifest fingerprint: `fdf270da3b4384f5af5c29bd2fb3bb3b6f38690944104709384b085d0bbe8e05`.
- Schema-drift hash: `b8f2c819b344da5db7de08169530a1fc33cf41541fce8c31ec4e03b2f25c316f`.
- Parity-constant count: 64. Ratchet count: 14. PENDING: empty.
- I1, I2, and I3: `test_synthetic_seed11_i1_i2_i3`, `test_reference_app_i2_only_pending`, and `test_pending_allowlist_stays_empty` passed.
- Cap-neutral joint: 18 / +41.49 / `f98a588d1f79f639308439da7437a2b5b66fa343d71d35a3632db12e3ffb0da8`. Per-symbol economic fields match the solos (diffs 0). Order ids differ in the joint universe. Solos: APP 10 / 26.61, CROX 2 / 11.87, OLN 6 / 3.01, DIOD ENSG MLI PCTY RMBS 0 / 0.
- Numbering: p1 econ_c 0 control 5; p2 econ_c 0 control 5; p3a econ_c 0 control 7; p3b econ_c 0 control 4; p3c econ_c 0 control 3.
- `FillBeforeLiveError` trips: 0. The type does not exist on this commit.

## Predictions

- E0.1 Oracle stays 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`.
- E0.2 R-FIX stays 98 / −1317.04 / `0ec66a9a`. R-SYN stays 29 / −131.01 / `ffc9161e`.
- E0.3 Eight-name stays 12 / +19.43 / `62196096`. Level-3 stays `f8824e5a…`. Fingerprint stays `fdf270da…`. Schema-drift stays `b8f2c819…`. Parity-constant count stays 64. Journals stay byte-identical on all four runs. No mover.
- E0.4 Ensembles: 32 salts and 8 phases, oracle and eight-name. Trade hash, per-fill economics, and journal times stay equal to `154ee44c` in all 80 cells.
- E0.5 Ratchet = exactly {IB `_fill_to_ack`, `sized_intent_legs._mint`, `sized_intent_orders._mint`, `registry._emit_reading_metrics`, `registry._emit_nonfinite_metric`}. PENDING empty. I1, I2, and I3 empty.
- E0.6 Cap-neutral joint stays 18 / +41.49 / `f98a588d1f79f639308439da7437a2b5b66fa343d71d35a3632db12e3ffb0da8` on this tree and on the final tree. Per-symbol joint-versus-solo economic diffs stay 0 on all eight.
- E0.7 Numbering p1..p3c `econ_c` stays 0 with controls 5, 5, 7, 4, 3.
- E0.8 Battery. CI reference battery at stage E, synthetic, 76 nodes, forward and reversed: 76/76. Real battery, 12 nodes, forward and reversed: 12/12. Stage-E real failing set, production engine, stays exactly `test_m1_clock_real`, `test_m1_gates_real`, `test_m1_fresh_real`, `test_m1_sinks_real`, `test_m2_real`, `test_m4_birth_real`, `test_m5_real`, `test_m6_real`.
- E0.9 `FillBeforeLiveError` trips stay 0 in every run above and in prepush.
- E0.10 Tests added: `test_run_real_fraction_folds_signed_zero_before_the_cache`, `test_market_fill_published_before_live_raises`, `test_passive_fill_published_before_live_raises`, `test_fill_at_exactly_live_time_is_allowed`. Tests modified: the 30 node ids below. Locked lines stay byte-identical: `EXPECTED_ALERT_TAXONOMY_HASH` `f6b784b275a549e169f7075ca583b9f198966f802216fbf7e8eb835d6f31b557` and the scenarios digest `00b7771e3c9b3718f21b313b208bf920bcf53e0c822c35fbb99be227c97eec57`.
- E0.11 Final prepush failures: none.

The four new tests fail or error on `154ee44c` and pass on the patched tree.

`src/feelies/core/wiring_manifest.py` stays unchanged. `tools/arch/evidence/hotpath_executed.json` is regenerated locally and not committed.

Any post-capture move this file does not predict blocks the rung.

## Modified node ids (30)

- `tests/conformance/test_action_time_producers.py::test_action_time_constructors_are_approved_or_known`
- `tests/determinism/test_alert_taxonomy_replay.py::test_alert_taxonomy_replay_matches_locked_hash`
- `tests/monitoring/test_solver_degraded_alert.py::test_degraded_status_raises_alert`
- `tests/monitoring/test_solver_degraded_alert.py::test_healthy_statuses_do_not_alert`
- `tests/monitoring/test_solver_degraded_alert.py::test_repeated_same_status_is_throttled`
- `tests/monitoring/test_solver_degraded_alert.py::test_rearms_after_healthy_boundary`
- `tests/monitoring/test_solver_degraded_alert.py::test_throttle_is_per_alpha`
- `tests/signals/test_horizon_engine_metrics.py::test_entry_suppressed_counter_increments_when_required_feature_cold`
- `tests/signals/test_horizon_engine_metrics.py::test_gate_transition_not_double_counted_across_entry_blocked_boundary`
- `tests/signals/test_horizon_engine_metrics.py::test_gate_transition_on_and_emitted_counters_on_real_signal`
- `tests/signals/test_horizon_engine_metrics.py::test_duplicate_boundary_is_metered_but_still_dispatched`
- `tests/signals/test_horizon_engine_metrics.py::test_increasing_boundary_index_never_flagged_as_duplicate`
- `tests/acceptance/test_inv12_stress_gate.py::test_router_deferred_fill_uses_doubled_latency`
- `tests/acceptance/test_inv12_stress_gate.py::test_passive_router_aggressive_fallback_uses_doubled_latency`
- `tests/acceptance/test_inv12_stress_gate.py::test_passive_router_resting_post_uses_doubled_latency`
- `tests/causality/test_anti_lookahead.py::TestDeferredMarketAntiLookahead::test_fill_at_t_unchanged_by_later_quote`
- `tests/causality/test_anti_lookahead.py::TestPassiveDrainAntiLookahead::test_prefix_ack_stream_immune_to_appended_future_quote`
- `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_latency_injection`
- `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_deferred_market_queues_despite_zero_depth_on_submit_quote`
- `tests/execution/test_backtest_router.py::TestBacktestOrderRouter::test_same_order_id_allowed_after_deferred_reject`
- `tests/execution/test_execution_realism_knobs.py::TestPassiveThroughFillCap::test_default_fills_whole_order_on_through`
- `tests/execution/test_execution_realism_knobs.py::TestPassiveThroughFillCap::test_cap_partial_fills_and_rests_remainder`
- `tests/execution/test_execution_realism_knobs.py::TestVolumeGatedLevelFill::test_default_gate_off_can_fill_without_volume`
- `tests/execution/test_execution_realism_knobs.py::TestVolumeGatedLevelFill::test_gate_on_suppresses_fill_without_volume`
- `tests/execution/test_execution_realism_knobs.py::TestVolumeGatedLevelFill::test_gate_on_allows_fill_with_volume`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_market_fill_latency`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_market_rejects_zero_depth_at_fill_quote`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_market_partial_fill_walk_the_book`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_deferred_marketable_limit_rejects_when_mid_exceeds_limit_after_latency`
- `tests/execution/test_passive_limit_router.py::TestLatency::test_marketable_limit_same_order_id_retry_after_deferred_reject`

## CI battery commands (P-23b2, unchanged on this commit)

Stage file contains `E`. `PYTHONHASHSEED=0`.

Reference battery (stage E, synthetic, 76 nodes):

```
FEELIES_ENGINE=tests.position_engine.reference.engine.PositionEngine
FEELIES_RAIL=tests.position_engine.reference.rail.ReferenceRail
uv run pytest tests/position_engine/test_battery_m1_reproducibility.py tests/position_engine/test_battery_m2_no_lookahead.py tests/position_engine/test_battery_m3_known_answer_conservation.py tests/position_engine/test_battery_m4_side_correctness.py tests/position_engine/test_battery_m5_precedence.py tests/position_engine/test_battery_m6_injection_syn.py tests/position_engine/test_battery_m6_injection_real.py tests/position_engine/test_battery_m11_audit.py tests/position_engine/test_reference_engine.py tests/position_engine/test_reference_trace.py -m "not battery_real" -q
```

Real battery (12 nodes):

```
FEELIES_REQUIRE_BASELINE_CACHE=1
FEELIES_ENGINE=tests.position_engine.reference.engine.PositionEngine
FEELIES_RAIL=tests.position_engine.reference.rail.ReferenceRail
uv run pytest -m battery_real -q
```
