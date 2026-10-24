# P-23e pre-registered prediction

BASE: `60cfc37cd5cd6a1607db07f2f065f39a61b87746` (branch `exec/P-23e`)
PATCH: `1c827ad5b0ccb7d0a667dda4d2fe914007cca0b157466106d520915f38c74fab`

## Mechanism

One regime calibration per symbol, fitted on that symbol's own prior-session quotes. The cap is applied per symbol as a prefix of that symbol's prior-session RTH quotes. The quotes are then concatenated and passed to `calibrate()`.

`per_symbol_calibration` is the existing `RegimeEngine` constructor flag (default `False`; commented out under `regime_engine_options` in `platform.yaml`). `calibrate()` already honors it: when the flag is true, a symbol with enough valid log-spreads stores its own emission triple, and every other symbol uses the pooled global fit.

Patch (s) does not read the config key. In `backtest_runner.py`, a universe of more than one symbol calls `prior_session_calibration_quotes` once per symbol, each call with that symbol alone and the same `max_quotes` cap, and concatenates the parts. In `orchestrator.py`, when the supplied quote tuple spans more than one symbol, `_calibrate_regime_engine` assigns `self._regime_engine._per_symbol_calibration = True` immediately before `calibrate()`.

On that multi-symbol backtest path the configured key does not select the fit: the attribute is forced on. The key still selects the branch on the single-symbol path, where (s) does not assign it. With one symbol the private fit and the pooled fit are the same quotes. Paper and live do not reach this calibration (F-P23e-7).

A symbol with zero own prior-session quotes contributes nothing to the concatenation. If any other symbol contributed quotes, that symbol is absent from `_emission_by_symbol` and `_emission_for_symbol` returns the pooled global fit of the quotes that were included. If every symbol is empty, the quote tuple is empty and calibration is skipped (the existing uncalibrated fallback). (s) adds no minimum-sample rule of its own: any symbol with at least one kept RTH quote is included, up to the cap. `RegimeEngine._MIN_CALIBRATION_SAMPLES` (30 valid log-spreads) remains the engine's pre-existing floor for storing a private emission; below it, that symbol also uses the pooled fit (F-P23e-8).

## Predictions

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 fills / net 26.61 / trade hash `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 95 fills / net −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee`.
- R-SYN (market mode, `BacktestOrderRouter`): 29 fills / net −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`.
- All 81 pins, including the parity oracle: movers none.
- All eight solo runs for 2026-03-26 are byte-identical to their runs at `60cfc37c`.
- Eight-name 2026-03-26 (local evidence, not a pin): 16 filled acks / net +34.56 / trade hash `696d0d3069c08a63c02114a61a2eff7762ed0b92bd40ed0a4bac81cf877d73bd`. Ensemble mean 34.316875, range [32.27, 34.56].
- Each symbol's emission equals its solo fit. Quote-level regime agreement is 100% on all eight.
- Output is identical under a permuted symbol order.
- Joint-versus-solo economic differences remain at APP 6, CROX 4, OLN 14. This is predicted. The cause is F-P23e-6.
- P1–P4 unchanged, with their controls holding. P-23c2 values: P1/P2/P3a/P3b/P3c = 0/0/0/0/0, controls 7/7/5/5/5; P4 joint equals solo (0/0), control 3.
- I1, I2, and I3 empty. PENDING empty. `KNOWN_NONCLOCK` ratchet 14.
- Wiring manifest and composition root unchanged.

Any post-capture move this file does not predict blocks the rung.

## MODIFIED

- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — profile refreshed ("hot-path edit reviewed under P-23e").

## ADDED

Fail-first on `60cfc37c` before the production change, except the fallback test.

- `tests/kernel/test_orchestrator.py::test_regime_calibration_fits_per_symbol_when_quotes_span_symbols` — RED on `60cfc37c`. The engine flag stays `False` and no per-symbol emission is stored.
- `tests/harness/test_prior_session_calibration.py::test_multi_symbol_run_keeps_a_capped_prefix_per_symbol` — RED on `60cfc37c`. The cap is still one prefix of the merged prior session (observed AAPL 1, MSFT 1, NVDA 0 at cap 2).
- `tests/harness/test_prior_session_calibration.py::test_symbol_without_prior_quotes_uses_the_stated_fallback` — GREEN on `60cfc37c`. Kept as a regression guard. A symbol absent from the prior quotes uses the pooled emission and has no private fit.

## Findings

- F-D1-1: CROX trade-sequence duplicate pairs; no effect on replay identity (F-P23e-3).
- F-D1-2: closed by this rung. F-D1-3: order ids move with universe width (identity track).
- F-P23e-1: the "digest" label in D-1 was not the operator config hash. From now on the config identity is the report field `config_hash (cfg)`: `compute_config_hash` of the resolved `PlatformConfig`, which is `snapshot().checksum`.
- F-P23e-2: cold start is the opening boundary-0 fan-out, 5 ticks, ending at each symbol's first quote.
- F-P23e-4: `test_g45_keep` fails on any `src` edit until the profile is refreshed.
- F-P23e-5: `-m battery_real` at `60cfc37c` collects 12 node ids, identical to the P-23c2 EXEC verification list, including `tests/conformance/test_causality_invariant.py::test_reference_app_i2_only_pending`. The count was not 11. A path-limited list that omitted that conformance test is not the root collection. `test_ci_real_job_selection` did not miss a marker change: the marker is unchanged and the job selects `battery_real` from the root.
- F-P23e-6 (HIGH, next rung): `session_open` is the first merged event (`backtest_runner.py:197`) and the horizon grid fans out from it (`horizon_scheduler.py:291`), so boundary timestamps depend on the universe.
- F-P23e-7 (HIGH, paper campaign): paper/live does not calibrate (`run_paper.py:212`, `orchestrator.py:889-895`). Backtest and live regime behaviour differ.
- F-P23e-8: no minimum-sample rule for a per-symbol fit. (s) includes every symbol with at least one prior-session RTH quote, up to the cap. The engine's pre-existing floor of 30 valid log-spreads still withholds a private emission below that count.
- F-P23e-9: `per_symbol_calibration` remains the constructor flag, default `False`, still commented out in `platform.yaml`. On the multi-symbol backtest path (s) forces the engine attribute on before `calibrate()`, so the configured value does not select that fit. The flag is what `calibrate()` honors. It is not assigned on the single-symbol path.
- Sensitivity record: eight-name net under three calibrations (+13.72 as-is, +34.56 per-symbol, −53.80 pooled uncapped). Recorded as fit sensitivity on one day, not as performance. The choice was made on mechanism.
