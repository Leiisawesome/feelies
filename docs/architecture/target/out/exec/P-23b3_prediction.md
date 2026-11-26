# P-23b3 pre-registered prediction

BASE: `49bbabd1eeb5bc808d25b95fae333b68327fa2a5` (`arch/exec`, `exec/P-23b3`)
PATCH: `2ffbf64c529a2700fa314ac98e623aa68d08626e3e98a529b399dfbe84f4b990` (landing patch t-agg)

Committed before any production or test change. The sources at this commit are still `49bbabd1`.

## Mechanism

A resting limit that locks or crosses the quote prevailing at go-live (q_p) is filled by `_execute_market_fill` on that book. The flush quote is the trigger. Submit-time routing, `_submit_aggressive_market`, and `market_fill.py` stay as they are. The resting path already emitted `ACKNOWLEDGED`, so the take does not emit a second one. A crossed book or a zero-depth side rejects with the same reason the submit path uses. Size above the displayed touch walks the existing impact model and is clamped to the limit. `reason` stays `""`. No `OrderAck` field. No config key. Paper does not construct this router.

## Snapping (P5)

`snap_limit_price` (`src/feelies/execution/tick_size.py:41-45`) floors a BUY limit and ceils a SELL limit. The router snaps at `src/feelies/execution/passive_limit_router.py:594`, after the submit check at lines 587-591, which uses the requested limit. Arrival classification uses the stored limit.

On a penny-grid contra, that snap does not change the classification. A penny-grid ask `a` and a buy limit `L` at or above `$1` (tick `$0.01`): if `L >= a` then `floor(L) >= a`, because every value in `[a, a+0.01)` floors to `a`; if `L < a` then `floor(L) < a`. A sell is the mirror with the ceiling. A sub-dollar limit uses a `$0.0001` tick, and a penny-grid quote sits on that grid, so the same side argument holds. T8 is the check. A disagreeing cell on the patched tree stops the rung.

## Baseline captured on `49bbabd1` before this commit

`tools/exec/baseline.py capture --label pre-P-23b3` on the clean tree: 5320 passed, 0 failed, 44 skipped, exit 0. Determinism 148 passed, 0 failed. Parity constants 64 across 25 modules. BASELINE GREEN. The JSON stays outside the repo until the baseline commit. No `## P-23b3` heading exists.

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Config hash `7c5f1e8d7cdaea16770a2c35c2f7632796f0247737dd120d984afdcb4e55aef5`.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`. Config hash `7d04fad61db4e3d2a85a68bb388185fd88c3bce58559ad3f262b888064d0a55d`.
- R-SYN (C_SYN seed 11, n=36000): 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Config hash `1a6372533bf92f86dfcccc19409d16e1d2de4b85771c839d02473b685ff5c783`.
- Level-3 snapshot hash: `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce` (14 snapshots).
- Manifest fingerprint: `fdf270da3b4384f5af5c29bd2fb3bb3b6f38690944104709384b085d0bbe8e05`.
- Schema-drift hash: `b8f2c819b344da5db7de08169530a1fc33cf41541fce8c31ec4e03b2f25c316f`. Cache `event_schema_hash`: `sha256:18e8861f5ff92ff6e8a779e4ddd6b1c0ab04a453bf6fcd08e16e5ce55e2cc2fa`.
- Eight-name 2026-03-26: 12 / +19.43 / `6219609611306a8871aeb1cc11d2f3128f43ebe40c6931dc912d44d0d504542d`. Config hash `84a57c87ac3ddb4269fa452f42db636cebb6ae8c1708bc2ab8b6a6618dabee1e`.
- Oracle phase 1: 2 / −13.00 / `5e1cee0ec2391ae3318caf19ae87f1d946571cd4380a51485631ee03e661ed1a`. Config hash `b13bd01df51cd4beed766e903e17065822d1fb855ceaaeac095a03ea8d0689d5`.
- Eight-name phase 1: 18 / −89.75 / `53f6cf467e86b1e783b47945fde948e391aae1a6fa5cbedbe74d5bdadc6bac47`. Config hash `592b677c450557f0da30ef17c71349206640e404f59607a18a7953dddb42e4a8`.
- Salt ensembles: oracle mean 26.72875 [24.03, 27.19], `{26.61: 20, 27.19: 11, 24.03: 1}`; eight-name mean 19.21625 [17.15, 19.43], `{19.43: 29, 17.15: 3}`.
- Phase ensembles: oracle mean 0.27625 [−37.11, 115.07]; eight-name mean −58.81875 [−134.08, 19.43].
- Pre-live fill rows in the 82 observer logs: 0.
- Cap-neutral joint versus solo: joint 16 / 68.08 / `66329ce280c733857cf2ff61418de0da89c8cbde25f5cab8ff0b6c7bd8f080f0`. APP 11 / 119.22, CROX 3 / −84.90, OLN 2 / 33.76, DIOD ENSG MLI PCTY RMBS 0 / 0. Risk rejects empty. Per-symbol diffs 0.

## Predictions

- E0.1 Oracle stays 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`.
- E0.2 R-FIX stays 98 / −1317.04 / `0ec66a9a`. R-SYN stays 29 / −131.01 / `ffc9161e`.
- E0.3 Level-3 stays `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce`. Fingerprint stays `fdf270da3b4384f5af5c29bd2fb3bb3b6f38690944104709384b085d0bbe8e05`. Schema-drift stays `b8f2c819b344da5db7de08169530a1fc33cf41541fce8c31ec4e03b2f25c316f`. Parity-constant count stays 64. No mover.
- E0.4 Phase 1 moves, and only phase 1. Oracle 2 / −8.35 / `da5bc4e4169728fcf7504f04881210f0e5ce9a7b044730b0061115b48ad4da75`. Eight-name 18 / −85.10 / `540c9dc15b030c096c383e770cc94fe83e12469713e1b45a646a4a71225a86fa`. The affected order is `FILLED` qty 30 px 399.93 fee 0.80 reason `""`. These hashes are evidence. They are not locked pins.
- E0.5 Salt ensembles stay at the means above. Phase-ensemble means become oracle 0.8575 and eight-name −58.2375, because phase 1 is the only cell that moves (+4.65 on both).
- E0.6 I1, I2, and I3 stay empty. PENDING stays empty. Ratchet stays 14. Causality reads stay 0. Numbering p1, p2, p3a, p3b, p3c stay `econ_c` 0. Cap-neutral joint stays 16 / 68.08 / `66329ce2…` with per-symbol diffs 0.
- E0.7 Tests added: `tests/execution/test_arrival_marketable_limit.py` (T1–T9). Test modified: `tests/execution/test_router_fill_timing_parity.py::TestThroughFillInsideLatencyWindow::test_fill_prices_off_post_eligibility_quote_not_stale_cross`, retargeted to the taker fill on q_p (99.90 on that test's zero within-L1 router). The two revert twins stay as they are. `tools/arch/evidence/hotpath_executed.json` is regenerated locally and not committed.
- E0.8 Final prepush failures: none.

T1, T2, T3, T5, T6, T7, T8, T9, and T10 fail on this commit. T4 passes on this commit and on the patch: a reverted q_p does not fill. A mutant that takes that book anyway is no longer resting.

`src/feelies/execution/passive_limit_router.py` becomes byte-identical to the patch. `wiring_manifest.py`, `market_fill.py`, `bootstrap.py`, and every schema and manifest pin stay unchanged.

Any post-capture move this file does not predict blocks the rung.
