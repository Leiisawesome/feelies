# P-22b pre-registered prediction

BASE: `8e0413c7493aea386c48ede01a52165f7a437ce2` (`arch/exec`)
PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-P-22b.json`
BASELINE GREEN. 5223 passed / 0 failed / 44 skipped / 0 deselected / exit 0
(tail also records 2 xfailed). Parity count 64.

## Parity

NONE. 64/64 constants unchanged.
APP oracle stays 10 fills / net 24.61 / trade hash
`18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`.

## ADDED

Stage A, no `FEELIES_*` overrides. `pass` is a real pass. `gated` is a
`battery_member` failure rewritten to pass because the message matches
`red_reason`.

| Node id | Stage A |
|---|---|
| `tests/position_engine/test_kill_runner.py::test_fixture_catcher` | pass |
| `tests/position_engine/test_kill_runner.py::test_classify_case_kinds` | pass |
| `tests/position_engine/test_kill_runner.py::test_noop_mutant_survives` | pass |
| `tests/position_engine/test_kill_runner.py::test_init_raise_is_crash_not_killed` | pass |
| `tests/position_engine/test_kill_runner.py::test_sleep_mutant_times_out` | pass |
| `tests/position_engine/test_kill_runner.py::test_control_reference_has_zero_failures` | pass |
| `tests/position_engine/test_kill_runner.py::test_registry_names_eleven_mutants` | pass |
| `tests/position_engine/test_kill_runner.py::test_mutants_import_only_reference_and_stdlib` | pass |
| `tests/position_engine/test_scenarios.py::test_favorable_tie_precondition_is_tape_computed` | pass |
| `tests/position_engine/test_scenarios.py::test_barrier_precondition_is_tape_computed` | pass |
| `tests/position_engine/test_battery_m11_audit.py::test_m11_gap_through` | gated (`green_from` E, `red_reason` `NONVACUOUS`) |

## MODIFIED

Stage A outcome before and after. Expected unchanged.

| Node id | Before | After |
|---|---|---|
| `tests/position_engine/test_battery_m5_precedence.py::test_m5_invalidation_at_take_profit` | gated (`^NONVACUOUS:`) | gated (`^NONVACUOUS:`) |
| `tests/position_engine/test_battery_m5_precedence.py::test_m5_deadline_beyond_stop` | gated (`^NONVACUOUS:`) | gated (`^NONVACUOUS:`) |
| `tests/position_engine/test_battery_m5_precedence.py::test_m5_gap_through_trail_and_stop` | gated (`^NONVACUOUS:`) | gated (`^NONVACUOUS:`) |
| `tests/position_engine/test_battery_m2_no_lookahead.py::test_m2_dwell_favorable_ignores_stale_cross` | gated (`NONVACUOUS`, `green_from` C) | gated (`NONVACUOUS`, `green_from` C) |
| `tests/position_engine/test_battery_m3_known_answer_conservation.py::test_m3_barriers_and_deadline` | gated (`^NONVACUOUS:`) | gated (`^NONVACUOUS:`) |

## Kill

11/11 killed by the named catcher at PROPERTY level.
Reference control: 0 failures.

## Reference battery

Synthetic member modules (1–6 and 11): all green. Count = 44 + 1
(`test_m11_gap_through`) = 45.
Real (`battery_real`, cache required): 9/9.

## Plain-pytest capture

| | passed | failed | skipped | deselected |
|---|---:|---:|---:|---:|
| pre-P-22b | 5223 | 0 | 44 | 0 |
| post-P-22b | 5234 | 0 | 44 | 0 |

The gate expression is unchanged (`not functional and not paper_rth and not battery_real`).
Pre-push under that expression moves 5209 passed / 5 skipped / 54 deselected to
5220 passed / 5 skipped / 54 deselected. Any other move is a STOP.
