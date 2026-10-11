# P-23c1 pre-registered prediction

BASE: `1a630cfe8c1f5bf2033abddc4f663b7726ae55b5` (`arch/exec`, branch `exec/P-23c1`)
PATCH: `d0512145781bd88e8f1083008c2997a98eac476f427a7a7e2f33a9346477bd4f`

## Mechanism

The three producers are stamped with the publication clock (action class): `GateDecision`, `DeRiskRequirement`, and `PositionSnapshot`. The policy-deadline compare operand is unchanged.

## Predictions

- Oracle (`configs/bt_app.yaml`, APP 2026-03-26): 10 fills / net 26.61 / trade hash `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`. Unchanged. No exemption.
- R-FIX (`configs/bt_position_arbitrary_not_calibrated.yaml`, reference engine): 95 fills / net −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee`.
- R-SYN (market mode, `BacktestOrderRouter`): 29 fills / net −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`.
- All 81 pins, including the parity oracle: movers none.
- PENDING empty.
- `KNOWN_NONCLOCK` ratchet 14.
- I1, I2, and I3 violators empty on R-FIX and R-SYN.

Any post-capture move this file does not predict blocks the rung.

## MODIFIED

- `tests/conformance/test_causality_invariant.py::test_reference_app_i2_only_pending` — rewritten to assert that the three stamps equal the publication clock and that the PENDING set is empty. Its intent is preserved: I2 is fully enforced on the reference run.
- `tests/conformance/test_hot_path_allow_list.py::test_g45_keep` — fingerprint update ("hot-path edit reviewed under P-23c1"). CI regenerates the profile via `perfmeasure --mode profile`.

## ADDED

Fail-first, red on `1a630cfe` before the production change. One test per producer: the stamp equals the clock at publication.

- `tests/conformance/test_causality_invariant.py::test_gate_decision_stamp_equals_publication_clock`
- `tests/conformance/test_causality_invariant.py::test_derisk_requirement_stamp_equals_publication_clock`
- `tests/conformance/test_causality_invariant.py::test_position_snapshot_stamp_equals_publication_clock`

The PENDING allowlist is empty and stays empty. Adding an entry fails the test.

- `tests/conformance/test_causality_invariant.py::test_pending_allowlist_stays_empty`

## Findings

Record only. Not fixed on this rung, except that the three stamps are the rung.

- F-P23c-a: the lateness floor is the 20 ms visibility delay.
- F-P23c-b: the lookahead count of 788 is the trigger stamp; feature math drops ts > T.
- F-P23c-c: a backtest-only timer breaks I3 and is not live's IdleTick.
- F-P23c-d: carryover release by any symbol's NBBOQuote (`orchestrator.py:5562`, `:4218`).
- F-P23c-e (HIGH): on the single-alpha path, an order is priced and sized from another symbol's quote (`orchestrator.py:1305`, `:2002`; the portfolio path guards at `:2069`). 7/10 orders in the P3c run. Latent in all single-symbol pins. Next rung P-23c2.
- F-P23c-f: research labels are anchored at T (`scripts/sensor_feature_ic.py:327`), while actuation occurs at T + closure lateness + release wait. IC overstates capturable edge. Research backlog: report IC from the actionable time.
- F-P23c-g: no current-schema multi-symbol dataset produces orders. Every multi-symbol day is old schema `8ff53428`. Coverage gap; a fetch needs operator authorisation.
- F-P23c-h: closure lateness depends on the universe (APP p50 294 ms alone vs 95 ms in 8 names, 2026-04-10).
- F-P23c-i: IdleTick cadence is 1.0 s (`massive_ws.py:104`); a live boundary timer is fake-clock testable.

## Amendment A

Accounting only. The text above is unchanged. No behaviour change.

The prepush on the docs head (`94b24f2b`) was red on three node ids, and only these:

- `tests/conformance/test_composition_root.py::test_s17_external_assignment_only_on_composition_root_allowlist` — the assignment pin had no row for `src/feelies/bootstrap.py` `_position_target._clock`.
- `tests/conformance/test_composition_root.py::test_s17_private_reach_only_on_composition_root_allowlist` — the private-reach pin had no row for the same expression.
- `tests/docs/test_exec_ledger_captures.py::test_capture_misses_equal_keep` — `## P-23c1` is a rung id, and `baseline_pre-P-23c1.json` and `baseline_post-P-23c1.json` were not tracked.

### MODIFIED

- `tests/conformance/test_composition_root.py::test_s17_external_assignment_only_on_composition_root_allowlist` — pin. One assignment row in `src/feelies/core/wiring_manifest.py`: path `src/feelies/bootstrap.py`, target `_position_target._clock`.
- `tests/conformance/test_composition_root.py::test_s17_private_reach_only_on_composition_root_allowlist` — pin. One private-reach row, same path and expression. One site, two scanners, so two rows. The reference `PositionEngine` takes no clock argument; bootstrap stamps `_clock` after construction (`bootstrap.py:747`); publication reads it (`engine.py:58`).

### Docs requirement

`test_capture_misses_equal_keep` requires a committed pre and post capture for every `## <rung-id>` heading. `## P-23c1` matches. The captures are `baseline_pre-P-23c1.json` and `baseline_post-P-23c1.json`.

### Why E0 missed both

F-P23c-j. The census full-gate run was not on the final patch `d0512145781bd88e8f1083008c2997a98eac476f427a7a7e2f33a9346477bd4f`.

- `preflight_prepush.txt` (2026-10-02 10:31) is green (`5255 passed`, `prepush: ok`) and predates the patch file (12:22:21).
- `d_gate.xml` (12:19:37) is 5262 cases and 6 failures: `test_g45_keep`, `test_reference_imports_only_the_allowed_set` (`engine.py` imported `feelies.core.clock`), and four resolution tests (`ProbeEngine` received an unexpected `clock` keyword). None of those is an S17 allowlist test or the ledger-capture test. The exported final patch does not import `Clock` and does not add a clock constructor argument.
- Nothing after 12:22:21 is a full gate. The later files are pins, the oracle, and the battery.

The final patch replaced a constructor argument with the post-construction stamp. That is the site S17 counts, and the gate never re-ran on it. The ledger heading was written in the docs commit, after E0.

### A3 evidence

- Without the rows, both S17 node ids failed. The extra key was `('src/feelies/bootstrap.py', '_position_target._clock')`. With the rows, both passed (`2 passed`).
- Fresh processes, no run cache, after the rows: oracle 10 fills / net 26.61 / `c95f4e5ca7942fed550411bacb5785ff2e5923bb40c7a55d01c6565302284ecf`; R-FIX 95 / −1258.93 / `657d248ec4dadd160dbb61463077e7a59ba5749f7fab8bd0c6ff4c033fe739ee`; R-SYN 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`. Identical to the predictions above.
- `git diff --stat` for `src/feelies/core/wiring_manifest.py` before the pin commit `594e3278`: `1 file changed, 10 insertions(+)`. The ten lines are the two rows for that one site.
