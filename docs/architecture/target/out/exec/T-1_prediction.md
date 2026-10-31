# T-1 pre-registered prediction

BASE: `c53be29c3043fcccb8c0295e8dc57749ee1be63e` (`arch/exec`)
PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-T-1.json`
with the D-110 deselect (39 node ids: 21 broker, 18 network).
BASELINE GREEN. 5216 passed / 0 failed / 5 skipped / 39 deselected / exit 0.

## Parity

NONE. 64/64 constants unchanged.
APP oracle stays 10 fills / net 24.61 / trade hash
`18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`.

## Gate expression

Unchanged: `not functional and not paper_rth and not battery_real`.
Every newly marked broker or network test is already `functional`, so the
expression selects the same set.

## Parity oracle job

Unchanged collected/passed counts.
Command (from `ci.yml`): `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q -m ""`.
On `c53be29c` (run 36511340767): 2 passed.

## Plain-pytest capture

Exactly the 39 tests newly marked broker or network move from deselected
(D-110 deselect) to skipped (opt-in). Nothing else changes.

| | passed | failed | skipped | deselected |
|---|---:|---:|---:|---:|
| pre-T-1 | 5216 | 0 | 5 | 39 |
| post-T-1 | 5216 | 0 | 44 | 0 |

Any other move is a STOP.

## E0 amendment A (post-observation, accounting only)

E0 omitted the rung's own added tests. The table above left the passed count
at 5216. The observed delta is the accounting below, and nothing else.

| | passed | failed | skipped | deselected |
|---|---:|---:|---:|---:|
| pre-T-1 | 5216 | 0 | 5 | 39 |
| post-T-1 | 5223 | 0 | 44 | 0 |

Collect-only (`pytest --collect-only -q`), D-110 deselect of the 39 applied
to `c53be29c` only: HEAD 5269, `c53be29c` without deselect 5262,
`c53be29c` with the deselect 5223 (39 deselected).

### (a) ADDED

`HEAD` collected minus `c53be29c` collected (no deselect on either side).
Exactly these 7. Each was PASSED in the post run.

- `tests/conformance/test_ci_gate_single_source.py::test_ci_gate_is_single_source`
- `tests/conformance/test_hot_path_allow_list.py::test_profile_fingerprint_rejects_stale_and_accepts_match`
- `tests/conformance/test_optin_markers.py::test_census_markers_match_the_optin_inventory`
- `tests/conformance/test_optin_markers.py::test_functional_and_oracle_are_not_optin_skipped`
- `tests/conformance/test_optin_markers.py::test_optin_flag_runs_only_the_matching_marker`
- `tests/conformance/test_optin_markers.py::test_optin_skips_without_flags`
- `tests/conformance/test_optin_markers.py::test_paper_guard_ports_and_accounts`

### (b) MOVED

Present in `HEAD` collect, absent from the deselected `c53be29c` collect,
and not in (a). Deselected in the pre run and SKIPPED in the post run.
Equals the census: 21 broker + 18 network.

- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_connect_handshake_and_next_order_id`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_duplicate_submit_rejected`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_submit_buy_limit_and_cancel`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_submit_sell_limit_and_cancel`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_cancel_unknown_order_returns_false`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_two_orders_cancelled_without_cross_drain_race`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_pending_cancel_does_not_emit_spurious_ack`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayFunctional::test_after_hours_reject_surfaces_as_rejected`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayReconnect::test_reconnect_after_clean_disconnect`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayReconnect::test_double_connect_raises`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_market_order_submit_and_cancel`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_ten_orders_rapid_submit_cancel`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_partial_fill_then_cancel`
- `tests/broker/ib/test_ib_functional.py::TestIBGatewayRTHFills::test_fill_ack_lag_exceeds_idle_tick_interval`
- `tests/integration/test_paper_rth_e2e.py::test_cold_start_smoke`
- `tests/integration/test_paper_rth_e2e.py::test_quote_sensor_warmup`
- `tests/integration/test_paper_rth_e2e.py::test_signal_path`
- `tests/integration/test_paper_rth_e2e.py::test_shutdown_in_flight`
- `tests/integration/test_paper_rth_safety.py::test_data_gap_degrades_macro`
- `tests/integration/test_paper_rth_safety.py::test_risk_lockdown_on_force_flatten`
- `tests/integration/test_paper_rth_safety.py::test_g12_cost_exceeds_disclosure_alert`
- `tests/ingestion/test_massive_functional.py::test_rest_ingest_uses_live_massive_data`
- `tests/ingestion/test_massive_functional.py::test_websocket_feed_emits_live_massive_event`
- `tests/ingestion/test_massive_functional.py::test_multi_symbol_subscribe`
- `tests/ingestion/test_massive_functional.py::test_sustained_quotes_with_idle_ticks`
- `tests/ingestion/test_parallel_ingest_integration.py::TestRawDownload::test_downloads_quotes`
- `tests/ingestion/test_parallel_ingest_integration.py::TestRawDownload::test_downloads_trades`
- `tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_events_in_chronological_order`
- `tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_contains_both_quotes_and_trades`
- `tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_sequences_are_monotonic`
- `tests/ingestion/test_parallel_ingest_integration.py::TestParallelIngestChronological::test_correlation_ids_are_unique`
- `tests/ingestion/test_parallel_ingest_integration.py::TestDiskCacheIntegration::test_cache_round_trip`
- `tests/ingestion/test_parallel_ingest_integration.py::TestDiskCacheIntegration::test_cache_reuse_skips_api`
- `tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_produces_contiguous_sequences`
- `tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_rebuilds_correlation_ids`
- `tests/ingestion/test_parallel_ingest_integration.py::TestResequencing::test_resequence_preserves_chronological_order`
- `tests/ingestion/test_parallel_ingest_integration.py::TestMultiDayCacheResequence::test_two_days_resequenced_are_globally_monotonic`
- `tests/ingestion/test_parallel_ingest_integration.py::TestFieldFidelity::test_quote_fields_survive_pipeline`
- `tests/ingestion/test_parallel_ingest_integration.py::TestFieldFidelity::test_trade_fields_survive_pipeline`

### (c) Nothing else

Per-node outcomes outside (a) ∪ (b) are identical. The post-only node ids
are exactly (a) ∪ (b). The pre-only set is empty. No shared node changed
outcome.

The `c53be29c` worktree re-run first reported `test_g45_keep` failed: a
fresh worktree does not contain the gitignored
`tools/arch/evidence/hotpath_executed.json`. With that file present, the
same `c53be29c` test passes, matching the pre-capture (0 failed). That
corrected outcome is the one compared above.
