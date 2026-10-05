# P-23g pre-registered prediction

BASE: `b7f14032c4ce9f56d6156c6fbac569c2352091f0` (branch `exec/P-23g`)
PATCH: `93b40d3b3d909fe654b96674680d5b75acb25e48608624960f2782542e87a7b5`

## Mechanism

On a symbol's first own event after a boundary, its regime, point and window state is captured before that event is applied. Boundaries are emitted in the normal horizon-check step with content as of the boundary time. Every boundary skipped by a real market event is emitted in order. Held-signal expiry reads the boundary-time field. Window statistics use one reduction. No flush occurs without a market event. Pipeline order, micro-state sequence and all existing timestamps are unchanged.

## Declared break (D-143 procedure; evaluation.md §2)

P-23a D-143: a locked determinism constant moves only through a pre-registered break verified by payload diff. The legacy oracle, which does not hash this stream, stays fixed. This rung is not a D-66 exemption.

OPERATOR DECISION (explicit, 2026-10-05): land census variant (g7). The locked level-3 snapshot-stream hash may change, `251cc109c25a4c1124c3dab32b7168c09b6a9126f4092d977df08a740c59d04b` -> `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce`, on condition that the stream diff shows 14 snapshots on both sides, every differing field is a windowed-feature value, and every difference is under 1e-9 relative (1e-9 absolute where the reference value is exactly zero). If the condition fails, do not update any locked hash.

Step D, measured on `b7f14032` against patch (g7) before this commit:

- snapshots 14 and 14
- differing field names: `ofi_ewma_zscore`
- differing values: 10
- largest absolute difference: 2.4424906541753444e-15
- largest relative difference: 6.294543275969185e-14
- condition holds
- attribution: 10 values from the single reduction path (`horizon_windowed.py` finalize); 0 from the capture fix

The field add alone leaves the level-3 hash unmoved. The remainder of (g7), which contains `boundary_ts_ns` on Signal, SafetyStateChange and CrossSectionalContext, replays to `251cc109…`. The reduction-only hunk replays to `f8824e5a…`. The level-3 hash moves because of the reduction change, not the field add. `test_s17a_field_add_moves_fingerprint_not_replay_hashes` keeps that name: a field add moves the manifest fingerprint and does not move replay hashes.

PREDICTED MOVES:

- `EXPECTED_LEVEL3_SNAPSHOT_HASH` changed: `251cc109c25a4c1124c3dab32b7168c09b6a9126f4092d977df08a740c59d04b` → `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce` (count 14 → 14)
- `EXPECTED_MANIFEST_FINGERPRINT` changed: `97b2c4148e25e9e4151f3d78915f884541bf7641b1e92e5c521646470f28ce58` → `4d3586adc75ce29e0d5c37cbcc44ea1ddd0d6401ddb390a944bb5a4b7a995ee2`
- schema field tuples for Signal, SafetyStateChange and CrossSectionalContext gain `boundary_ts_ns`. `SCHEMA_VERSION` stays 1
- every other parity constant: none
- legacy oracle: unchanged. 10 fills / net 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`

FILLS: no. The legacy oracle fill count, net and trade hash stay put.

MECHANISM: one reduction for window statistics replaces the Welford branch with the filtered two-pass moments. The bit-level change is confined to windowed-feature values on the level-3 stream.

## Predictions

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 fills / net 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Per-fill diff 0. Salt ensemble `{24.03: 1, 26.61: 20, 27.19: 11}`.
- R-FIX: 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`, unchanged.
- R-SYN: 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`, unchanged.
- Pin movers, and only these:
  - level-3 snapshot hash `251cc109…` → `f8824e5a…` (14 → 14 snapshots)
  - manifest fingerprint `97b2c4148e25e9e4151f3d78915f884541bf7641b1e92e5c521646470f28ce58` → `4d3586adc75ce29e0d5c37cbcc44ea1ddd0d6401ddb390a944bb5a4b7a995ee2`
  - schema field tuples for Signal, SafetyStateChange and CrossSectionalContext gain `boundary_ts_ns`; `SCHEMA_VERSION` stays 1
- The diagnostic phase ensemble moves at 90 s (−20.10 → −17.34) and 105 s (−20.59 → −37.11). The other six phases are unchanged.
- Oracle feature effect against `b7f14032`: `book_imbalance_mean` 75 boundaries, `book_imbalance_zscore` 76, `ofi_ewma_zscore` 80.
- Eight-name 2026-03-26 (local evidence, not a pin): 12 / +19.43 / `6219609611306a8871aeb1cc11d2f3128f43ebe40c6931dc912d44d0d504542d`. Salt ensemble mean 19.21625 [17.15, 19.43].
- Boundary content bit-exact, solo against joint: 100% on all eight symbols (decision content, and full content excluding the trigger stamp).
- Boundary sets identical on all eight.
- Joint-versus-solo economic differences as configured: APP 8, all others 0. Cause: the shared per-alpha exposure check (`risk_wrapper.py:145-156`).
- Joint-versus-solo with the part-5 cap-neutral config: 0 on all eight, risk rejects 0/0.
- I1/I2/I3 empty. PENDING empty. Ratchet 14.
- Wiring manifest and composition-root allowlist unchanged.

Any post-capture move this file does not predict blocks the rung.

## MODIFIED

- `tests/sensors/test_boundary_ts.py::test_scheduler_stamps_nominal_boundary_vs_trigger_on_sparse_tape` — the landing-index-only pin becomes catch-up; the nominal-versus-trigger guarantee is kept.
- `tests/conformance/test_horizon_grid_universe.py::test_p5_boundary_sets_are_identical_alone_and_in_a_wider_universe` — strict xfail removed.
- `tests/conformance/test_schema_drift.py::test_s8_every_event_class_resolves_schema_version` — updated per the field-addition procedure (`test_parity_manifest.py:377-381`).
- `tests/conformance/test_schema_drift.py::test_s17a_field_add_moves_fingerprint_not_replay_hashes` — same procedure. The name stays: a field add does not move replay hashes. The level-3 hash moves because of the reduction, shown by the step-D attribution above.
- `tests/determinism/test_parity_manifest.py::test_manifest_fingerprint_matches_locked_value` — fingerprint re-baselined with the level-3 hash, same procedure.
- `tests/acceptance/test_bt11_parity_post_fill_model.py::test_locked_parity_baseline_matches_replay_after_fill_model_changes[level3_horizon_feature_snapshot]` — level-3 pin.
- `tests/acceptance/test_v02_no_trend_mechanism_parity.py::test_baseline_alpha_level3_snapshot_hash_unchanged` — level-3 pin.
- `tests/determinism/test_horizon_feature_snapshot_replay.py::test_snapshot_stream_matches_locked_baseline` — level-3 pin.
- `tests/determinism/test_parity_manifest.py::test_manifest_entry_matches_replay[level3_horizon_feature_snapshot]` — level-3 pin.
- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — profile refresh.

## ADDED

Fail-first status on `b7f14032`, as the census predicted.

- `test_window_for_boundary_t_complete_regardless_of_later_events` — red
- `test_catchup_emits_every_skipped_boundary_in_order` — red
- `test_held_signal_expiry_anchored_on_boundary_time` — red
- `test_tie_membership_event_exactly_at_boundary` — green (regression guard)
- `test_boundary_0_uses_pre_event_state` — red
- `test_finalize_bit_identical_across_paths` — red
- `test_boundary_content_identical_solo_and_two_symbol` — red
- `test_joint_fills_equal_solo_when_no_risk_limit_binds` — red

## Findings

- F-P23f-7 and F-P23f-8: closed by this rung.
- F-P23c-k (expiry anchored on the trigger stamp): closed.
- F-P23g-8: windowed features were computed on a window truncated by the emission lateness (h30 median 0.9%, max 14.6%; h120 median 0.2%, max 3.6%).
- F-P23g-9 / F-P23g-13 (operator risk-policy item): the per-alpha exposure cap of 3,125 is shared across symbols and checked before the trade; sizing uses the full 12,500 allocation and ignores the cap; a first order of about 2.4 to 2.9 times the cap passes, and all other entries are then rejected. Not changed here.
- F-P23g-14: a trade that cannot emit must not claim capture keys.
- F-P23g-15 / F-P23g-16: one reduction path; the level-3 hash moves by bit-level numerics.
- F-P23g-17 (next rung): the fix deep-copies every windowed deque for the symbol once per claiming event; peak memory on the eight-name run rises 899 MB → 1,188 MB; the copy is on shared live code. Replace it with deferred eviction, which is now possible with one reduction path, and require bit-identical output.
- F-P23g-2: a session-close flush needs an explicit session-close event injected only for a complete session. Deferred with the timer design.
- Phase ensemble: oracle mean +0.28 [−37.11, +115.07]; eight-name mean −58.82 [−134.08, +19.43]. Recorded as a robustness concern. Status of the alpha on this evidence: hypothesis.

## Amendment A

Append-only. The original prediction above is unchanged.

`4d3586adc75ce29e0d5c37cbcc44ea1ddd0d6401ddb390a944bb5a4b7a995ee2` is the manifest fingerprint with the new field tuples and the level-3 constant still locked at `251cc109…`. That is the value the census gate printed before the constant was re-pinned. The fingerprint hashes the locked baselines, so re-pinning `EXPECTED_LEVEL3_SNAPSHOT_HASH` to `f8824e5a…` composes it to `3584bbafa3655ee336b1db04099b5a3c417dd8a0febfc967c69e3dc85a52ec32`. The field-addition procedure (`test_parity_manifest.py:377-381`) pins the composed value. No other parity constant moves.
