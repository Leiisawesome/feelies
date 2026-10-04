# P-23f pre-registered prediction

BASE: `7b296839e1fb5dfc1f8567e14f59b8d6c5096b74` (branch `exec/P-23f`)
PATCH: `6f81c79fca0db585dd508a94b26c2d25f4b003c6e044c0fe29cef592ab92e823`

## Mechanism

An unset backtest `session_open` resolves to the exchange regular-session open, so boundary `k` at horizon `h` is `open + k·h` for every symbol. The open is `rth_open_ns` (09:30 America/New_York). `k` starts at 0. An event before the open emits nothing.

`bootstrap.py` is not changed. The live and paper anchor stays the boot wall clock.

## Declared break (evaluation.md §2)

PREDICTED MOVES:

- `tests/acceptance/test_backtest_app_baseline.py::_BASELINE_TRADE_PARITY_HASH` changed: `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf` → `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`
- `_BASELINE_NET_PNL` unchanged (`26.61`)
- `_BASELINE_FILL_COUNT` unchanged (`10`)
- every other parity constant: none

FILLS: no. The fill count stays 10. Side, quantity, price, time, type, pnl, fees and cost are identical to `c95f4e5c` on all 10 fills. `order_id` differs on fills 1–9. The trade hash includes `order_id` (`orchestrator.py:2196`, hashed at `backtest_report.py:822`).

MECHANISM: an unset backtest `session_open` resolves to the exchange regular-session open, so boundary `k` at horizon `h` is `open + k·h` for every symbol (`session_clock.py:5-6`).

## Predictions

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 fills / net 26.61 / trade hash `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. Side, quantity, price, time, type, pnl, fees and cost are identical to `c95f4e5c` on all 10 fills. `order_id` differs on fills 1–9.
- 32-salt ensemble `{26.61:20, 27.19:11, 24.03:1}`, mean 26.72875, range [24.03, 27.19].
- Movers: the oracle trade-hash pin only. The net pin is unchanged. No other pin moves.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 95 / −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee` → 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`. Declared reference move. R-FIX is not CI-pinned.
- R-SYN (market mode, `BacktestOrderRouter`): 29 fills / net −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`, unchanged. Explicit T0.
- Grid shift: APP and R-FIX −25.823081 ms; joint −10.733594 ms.
- Eight-name 2026-03-26 (local evidence, not a pin): 14 filled acks / net +38.08 / trade hash `2fa81942c3da8d4a83a0bff509e8fff3d8cf9261b3fb254ad59d1af94631402b`. Ensemble mean 37.837812, range [35.80, 38.08].
- Boundary share solo-in-joint 100% on all eight. Cross-section alignment 100%.
- Joint-versus-solo economic differences: APP 8, CROX 2, OLN 0, others 0. These are predicted residuals. Their cause is F-P23f-7.
- P1–P4 unchanged, with their controls holding.
- I1, I2, and I3 empty. PENDING empty. `KNOWN_NONCLOCK` ratchet 14.
- Wiring manifest and composition root unchanged.
- Suite: post-capture passed = pre-capture passed + 2. Post-capture xfailed = pre-capture xfailed + 1. Determinism unchanged. The added xfail is P5-identity.

Any post-capture move this file does not predict blocks the rung.

## MODIFIED

- `tests/acceptance/test_backtest_app_baseline.py::test_app_20260326_backtest_baseline_from_disk_cache` — the hash pin changes to `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`. The net pin stays 26.61. The fill count stays 10.
- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — profile refresh ("hot-path edit reviewed under P-23f").

## ADDED

Fail-first on `7b296839` before the production change.

- `tests/harness/test_backtest_session_anchor.py::test_unset_backtest_session_open_equals_rth_open_ns` — RED on `7b296839`. An unset backtest `session_open` is still the first kept event, not `rth_open_ns` for the session date.
- `tests/conformance/test_horizon_grid_universe.py::test_p5_solo_boundaries_are_a_subset_of_the_wider_universe` — RED on `7b296839`. Status-quo overlap is 0%.
- `tests/conformance/test_horizon_grid_universe.py::test_p5_boundary_sets_are_identical_alone_and_in_a_wider_universe` — `xfail(strict=True)`. The assertion is false on `7b296839` (the sets differ). The reason cites F-P23f-8 and the next rung, P-23g. It is not green.

## Findings

- F-P23f-1: the runner's first-event override contradicted `session_clock.py:5-6`. Closed by this rung.
- F-P23f-2 (HIGH, paper campaign): in live and paper, `session_open` is the boot wall clock (`bootstrap.py:885`), while its docstring (`:878`) says RTH open. A mid-session restart rebinds the grid. Identified fix: `rth_open_ns(clock.now_ns())`. Not changed here.
- F-P23f-3: the oracle hash moves only via `order_id` (`orchestrator.py:2196`, hashed at `backtest_report.py:822`).
- F-P23f-4: variant (b) rejected. Alignment 0% and 12 gate failures.
- F-P23f-5: `events.py:675` says `k = 1, 2, …`; the scheduler emits `k = 0, 1, 2, …`. The docstring is corrected here.
- F-P23f-6: the static pin-name scan finds 78 names; the gate's mover list is authoritative.
- F-P23f-7 (HIGH, next rung): a boundary's emitted state and stamp come from the crossing event (`horizon_scheduler.py:298-311`, `:373`). Alone, that is the symbol's own next event. In a universe, it is often another symbol's earlier event. This is the cause of the residual APP 8 / CROX 2.
- F-P23f-8 (next rung): on sparse tapes a symbol run alone emits fewer boundaries than in a universe (DIOD 778, ENSG 767, MLI 778, PCTY 779, against 780).
- F-P23f-9, the grid-phase sensitivity table. Oracle net by anchor shift: −60 s: −33.75; −10 s: −74.99; −1 s: +106.13; −100 ms to +10 ms: 26.61; +100 ms: 26.42; +1 s: 23.18; +10 s: 10.55; +60 s: −33.75. Eight-name net ranges from −169.25 to +52.61. Recorded as a robustness concern: single-day nets are not evidence of edge.
