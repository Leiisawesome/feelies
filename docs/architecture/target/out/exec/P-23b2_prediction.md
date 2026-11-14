# P-23b2 pre-registered prediction

BASE: `07cfbb0b603ec61276839493219d625345013910` (`arch/exec`, `exec/P-23b2`)
PATCH: `649f6225fb21ceb93ae3862aa3733f7963f5abc4bee02bdb05692229a2a629e1` (landing patch f+e)

Committed before any production or test change. The sources at this commit are still `07cfbb0b`.

## Mechanism

Backtest routers hold `FILLED` and `PARTIALLY_FILLED` until the simulated clock is at or past born plus `fill_report_latency_ms`. `None` is today's immediate poll: the pending list is returned unchanged and `report_received_ns` stays 0. On release, `OrderAck.timestamp_ns` is the release clock and `report_received_ns` is born plus the delay. Economic readers use `report_received_ns` when it is non-zero and otherwise `timestamp_ns`. A due report is released at the start of each quote tick and each trade tick, before quote-health, stops, de-risk, and hazard. No mode compare. Paper does not construct those routers. `SCHEMA_VERSION` stays 1.

## Baseline captured on `07cfbb0b` before this commit

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Config hash `7c5f1e8d7cdaea16770a2c35c2f7632796f0247737dd120d984afdcb4e55aef5`.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`. Config hash `7d04fad61db4e3d2a85a68bb388185fd88c3bce58559ad3f262b888064d0a55d`.
- R-SYN (C_SYN seed 11, n=36000): 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Config hash `1a6372533bf92f86dfcccc19409d16e1d2de4b85771c839d02473b685ff5c783`.
- Level-3 snapshot hash: `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce` (14 snapshots). Fixture replay, no platform config.
- Manifest fingerprint: `3584bbafa3655ee336b1db04099b5a3c417dd8a0febfc967c69e3dc85a52ec32`.
- Schema-drift hash (SHA-256 of the canonical event field sets): `14e9e3913d3a73e0d8026ee62b277eef722d0b2d4dbdb299f9c5a233473f25e2`. Cache `event_schema_hash`: `sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa`.
- Eight-name 2026-03-26: 12 / +19.43 / `6219609611306a8871aeb1cc11d2f3128f43ebe40c6931dc912d44d0d504542d`. Config hash `84a57c87ac3ddb4269fa452f42db636cebb6ae8c1708bc2ab8b6a6618dabee1e`.
- Parity-constant count: 64 across 25 modules.
- `tools/exec/baseline.py capture` on this clean tree: 5299 passed, 0 failed, 44 skipped; determinism 148 passed, 0 failed. The JSON stays outside the repo until the baseline commit.

## Predictions

At L=None:

- E0.1 Oracle stays 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`.
- E0.2 R-FIX stays 98 / −1317.04 / `0ec66a9a`. R-SYN stays 29 / −131.01 / `ffc9161e`.
- E0.3 Level-3 hash stays `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce`.
- E0.4 Eight-name day stays 12 / +19.43 / `62196096`.
- E0.5 Config hashes stay the four values above. `fill_report_latency_ms` is popped from the snapshot when it is None.
- E0.6 Mover 1: `EXPECTED_MANIFEST_FINGERPRINT` `3584bbafa3655ee336b1db04099b5a3c417dd8a0febfc967c69e3dc85a52ec32` → `fdf270da3b4384f5af5c29bd2fb3bb3b6f38690944104709384b085d0bbe8e05`. Operator decision, precedent D-143. Any other fingerprint stops the rung.
- E0.7 Mover 2: `PINNED_PAYLOAD["OrderAck"]` gains `report_received_ns`. Schema-drift hash `14e9e3913d3a73e0d8026ee62b277eef722d0b2d4dbdb299f9c5a233473f25e2` → `b8f2c819b344da5db7de08169530a1fc33cf41541fce8c31ec4e03b2f25c316f`. Cache `event_schema_hash` stays `sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa`. The 28 replay hashes do not move.
- E0.8 No other parity constant, pin, or locked hash moves.
- E0.9 Oracle 8-phase grid: trade hash equal, `07cfbb0b` versus final.

At L in {20, 50, 100, 250}:

- E0.10 Oracle and eight-name: fills / net / hash unchanged versus L=None. Per-fill economic diff 0.
- E0.11 R-SYN unchanged. R-FIX: L20 92 / −1351.45 / `97c9cec8`; L50 82 / −1290.78 / `222a9cb3`; L100 81 / −1279.52 / `5f0044a7`; L250 87 / −1264.34 / `687e7a65`.
- E0.12 p1, p2, p3a, p3b, p3c `econ_c` 0 at every L. Controls move.
- E0.13 Cap-neutral eight-name joint versus solo: 0 diffs at every L.
- E0.14 I1/I2/I3 violators 0 at L=20 and L=250.
- E0.15 Receive delay exactly L. Causality reads 0.

Tests:

- E0.16 Added: `tests/execution/test_fill_report_latency.py` (T1–T7), `tests/kernel/test_orchestrator_async_fill_latency.py` (T8–T9), `tests/conformance/test_drain_content_invariance.py::test_fill_report_stamp_independent_of_other_symbol` (T10), `tests/conformance/test_causality_invariant.py::test_synthetic_seed11_i2_at_fill_report_latency` (T11, L in {20, 250}). Re-pinned: `EXPECTED_MANIFEST_FINGERPRINT` and `PINNED_PAYLOAD["OrderAck"]`. No other test modified.
- E0.17 Final gate failures: none.

`HorizonTick.boundary_ts_ns` defaults to 0. Zero means unset for direct construction; the scheduler always sets it (`events.py:850-852`). P-23g did not bump a schema version when it added that field. `SCHEMA_VERSION` stays 1 (`events.py:30`).

Any post-capture move this file does not predict blocks the rung.
