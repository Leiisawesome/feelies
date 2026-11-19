# P-23g2 pre-registered prediction

BASE: `0fda7491a1566f2fb87dea48521421268f5d2e62` (`arch/exec`, `exec/P-23g2`)
PATCH: `eac7b5567852358b10781cf79d730f2ca458a0bd5ce03ac19842f073d77e18b4` (landing patch x)

Committed before any production change. The sources at this commit are still `0fda7491`.

## Mechanism

Point state is still captured before a symbol's first own event after a boundary. Windowed deques stay live. While that event is in flight, eviction is held at the oldest unfinalised boundary for the symbol and horizon, so `finalize` over the closed window `[T-W, T]` sees the same samples the previous deep copy saw. `events.py` gains no dataclass field.

## Baseline captured on `0fda7491` before this commit

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Config hash `7c5f1e8d7cdaea16770a2c35c2f7632796f0247737dd120d984afdcb4e55aef5`.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`. Config hash `7d04fad61db4e3d2a85a68bb388185fd88c3bce58559ad3f262b888064d0a55d`.
- R-SYN (C_SYN seed 11, n=36000): 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Config hash `1a6372533bf92f86dfcccc19409d16e1d2de4b85771c839d02473b685ff5c783`.
- Level-3 snapshot hash: `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce` (14 snapshots). Fixture replay, no platform config.
- Manifest fingerprint: `3584bbafa3655ee336b1db04099b5a3c417dd8a0febfc967c69e3dc85a52ec32`.
- Schema-drift hash (SHA-256 of the canonical event field sets): `14e9e3913d3a73e0d8026ee62b277eef722d0b2d4dbdb299f9c5a233473f25e2`. Cache `event_schema_hash`: `sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa`.
- Eight-name 2026-03-26: 12 / +19.43 / `6219609611306a8871aeb1cc11d2f3128f43ebe40c6931dc912d44d0d504542d`. Config hash `84a57c87ac3ddb4269fa452f42db636cebb6ae8c1708bc2ab8b6a6618dabee1e`.
- Cap-neutral joint-versus-solo fill diffs: 0 on APP, CROX, DIOD, ENSG, MLI, OLN, PCTY, RMBS. Risk rejects 0 solo / 0 joint.

## Predictions

- E0.1 Oracle stays 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`.
- E0.2 R-FIX stays 98 / −1317.04 / `0ec66a9a`. R-SYN stays 29 / −131.01 / `ffc9161e`.
- E0.3 Level-3 hash stays `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce`.
- E0.4 Manifest fingerprint stays `3584bbafa3655ee336b1db04099b5a3c417dd8a0febfc967c69e3dc85a52ec32`.
- E0.5 Schema-drift hash stays `14e9e3913d3a73e0d8026ee62b277eef722d0b2d4dbdb299f9c5a233473f25e2`. Cache `event_schema_hash` stays `sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa`.
- E0.6 No pin movers. No locked-hash movers.
- E0.7 Boundary streams bit-identical to `0fda7491` for APP, CROX, DIOD, ENSG, MLI, OLN, PCTY, RMBS, solo and joint.
- E0.8 Eight-name day stays 12 / +19.43 / `62196096`.
- E0.9 Cap-neutral joint-versus-solo differences stay 0 on all eight. Rejects stay 0/0.
- E0.10 Eight-phase grid: trade hash and boundary-stream hash equal, head versus patch, in every phase, for the oracle and the eight-name day.
- E0.11 Tests added: `tests/sensors/test_windowed_deferred_eviction.py` (T1–T4). Tests modified: none. Evidence regenerated: `tools/arch/evidence/hotpath_executed.json` only.
- E0.12 Cost, informational: full gate about 565 s, oracle wall about 32 s, eight-name peak memory about 940 MB. Flag if the gate exceeds 700 s or the oracle wall exceeds 38 s.

T1 is fail-first on this commit: one boundary capture at 4N versus N is about 4 on the copy path, so the ratio is not under 1.5. The deque-copy control is above 3. T2–T4 pass here and on the patch. Outside this repo, eager eviction is killed by T2 and T3, a latest-boundary anchor is killed by T3, and a strict edge is killed by T4. The unmutated patch passes all four.

Any post-capture move this file does not predict blocks the rung.
