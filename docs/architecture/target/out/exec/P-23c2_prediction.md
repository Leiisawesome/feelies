# P-23c2 pre-registered prediction

BASE: `883e36bec18acff519c7193a7a656ec4b6c05157` (branch `exec/P-23c2`)
PATCH: `595a179b1ac1aac3462874b52a39b9c786d02bd86a1fffdf913db62a6978c3c6`

## Mechanism

A held single-alpha signal is released only by an NBBOQuote of its own symbol, and is priced and sized from that quote. Horizon closure stays global. The portfolio path is untouched.

## Predictions

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 fills / net 26.61 / trade hash `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`. Per-fill diff 0. 32-salt ensemble `{24.03: 1, 24.61: 3, 26.61: 12, 27.19: 16}`.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 95 fills / net −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee`.
- R-SYN (market mode, `BacktestOrderRouter`): 29 fills / net −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`.
- All 81 pins, including the parity oracle: movers none.
- Cross-symbol pricing 0 on the oracle, p3a, p3b, p3c and m1.
- P1/P2/P3a/P3b/P3c = 0/0/0/0/0, with negative controls 7/7/5/5/5.
- P4: each symbol's joint-run fills equal its solo-run fills (0/0), with control 3.
- Delays unchanged. Oracle signal-to-order 1058/3014/3075 ms (n=10). R-FIX 460/5441/5925 ms (n=33).
- I1, I2, and I3 empty. PENDING empty. `KNOWN_NONCLOCK` ratchet 14.
- Wiring manifest unchanged.

Any post-capture move this file does not predict blocks the rung.

## MODIFIED

- `tests/conformance/test_drain_content_invariance.py::test_p3c_shifted_symbol_does_not_move_app_fills` — the strict xfail is removed. It becomes a passing invariance test, and its negative control is retained.
- `tests/position_engine/test_battery_m1_reproducibility.py::test_m1_multiname` — retargeted. Its intent, multi-name reproducibility, is preserved. It now asserts that both names trade, that each is sized from its own quote, and that each name's result is reproducible.
- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — profile regenerated ("hot-path edit reviewed under P-23c2").

## ADDED

Fail-first on `883e36be` before the production change, except the expiry test.

- `tests/conformance/test_own_quote_release.py::test_held_signal_is_priced_from_its_own_quote`
- `tests/conformance/test_own_quote_release.py::test_foreign_quote_does_not_release_a_held_signal`
- `tests/conformance/test_own_quote_release.py::test_joint_run_fills_equal_solo_run_fills` — P4. Red on `883e36be` with changes `{AAA: 0, BBB: 3}`, the control of 3.
- `tests/conformance/test_own_quote_release.py::test_held_signal_expires_when_horizon_elapses_without_own_quote` — GREEN on `883e36be`. Kept as a regression guard.

### Expiry anchor

The anchor is the trigger stamp, not nominal T.

The age compare is `quote.timestamp_ns - sig.timestamp_ns <= sig.horizon_seconds * 1_000_000_000` at `orchestrator.py:4226`. `_now_ns` is `quote.timestamp_ns` at `orchestrator.py:4219`. `sig.timestamp_ns` is the trigger: `HorizonTick.timestamp_ns` is the crossing event (`horizon_scheduler.py:355`; the nominal boundary is `boundary_ts_ns` at `:363`), `HorizonFeatureSnapshot.timestamp_ns` copies it (`aggregator.py:437`; `events.py:741`), and `_patch_signal` keeps that stamp (`horizon_engine.py:755`).

An expired signal is removed from `_signal_buffer`, its sequence is discarded from `_carryover_signal_sequences`, and it produces no order. When a trace sink and a prior quote context exist, the row is `NO_ORDER` with reason `signal_buffer_cleared_unprocessed_at_tick_boundary` (`orchestrator.py:4242`).

## Findings

- F-P23c-e: closed by this rung.
- F-P23c-k: the expiry anchor is the trigger stamp, so a universe-dependent margin remains at expiry. The signal stays eligible for `(trigger − nominal T)` past a nominal-T expiry. That margin is the closure lateness and depends on the universe (F-P23c-h). Recorded. Not fixed.
- F-P23c-l: on the portfolio path, the guard at `orchestrator.py:2069` covers opening legs only while B4 is armed. Reducing legs and a disarmed gate return before the check (`:2062–:2064`). A refused leg is dropped while sibling legs submit. An intent whose legs are all refused is abandoned (`:4047`). A census is required before any PORTFOLIO alpha is wired.
- F-P23c-m: the measured actuation delays above. Oracle signal-to-order 1058/3014/3075 ms (n=10). R-FIX 460/5441/5925 ms (n=33).
