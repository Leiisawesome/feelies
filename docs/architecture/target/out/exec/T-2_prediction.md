# T-2 pre-registered prediction

BASE: `1672070cd1db2bf06cac606ded000a10af171833` (`arch/exec`, `exec/T-2`)

PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-T-2.json`

Captured on the clean base, before any `## T-2` ledger heading. BASELINE GREEN.
5311 passed / 0 failed / 44 skipped / exit 0. Determinism 148 passed / 0 failed.

## Precedent

T-1 stored `baseline_pre-T-1.json` (captured at the clean base `c53be29c`,
committed in `4b728d81`) and `baseline_post-T-1.json` (committed in
`1460475b`). The heading `## T-1` was not on the exec branch; `8e0413c7`
added it after the merges. This rung uses the same two files. The heading
is in the PR, because L-03 requires both captures once `## T-2` exists.

## Pins read on this commit

`src/` and `tests/` are identical from `a2f1fa32` (the merge that recorded
the runtime pins) to this commit. No replay was re-run for R-FIX or R-SYN.

- Oracle: 10 / 26.61 / `ab3a2b3fa673c0cbd746a8518c03fde0ee397114ceb64ea2ce3074e1f0d7795e`
- R-FIX: 98 / −1317.04 / `0ec66a9a48190680e564d519505ff9ed87e063ac4343c40040a590b85b38e9c2`
- R-SYN: 29 / −131.01 / `ffc9161eb542967c93012064371dbff819e2b8c4d7485fcedfb175eb7fcfd575`
- Level-3 snapshot hash: `f8824e5a288d64a3922c333a51416ce4b2db1251e6b2d8c815102fd81e6840ce`
- Manifest fingerprint: `fdf270da3b4384f5af5c29bd2fb3bb3b6f38690944104709384b085d0bbe8e05`
- Schema-drift hash: `b8f2c819b344da5db7de08169530a1fc33cf41541fce8c31ec4e03b2f25c316f`
- Parity-constant count: 64

## What the check job's tests do with a missing event-cache file

The gate is `scripts/ci_gate_expr.txt`. The only selected tests that read
`~/.feelies/cache` are the six in
`tests/conformance/test_drain_content_invariance.py`. `replay_case` loads
APP/2026-03-26 at line 151 and does not catch `CacheReplayError`, so a
missing file is an error. The same replay asks the runner for the prior
session. A missing APP/2026-03-25 returns None
(`src/feelies/harness/backtest_runner.py:742`) and is not a skip.

`test_app_20260326_backtest_baseline_from_disk_cache` and every
`battery_real` test also read APP/2026-03-26. The gate deselects both
(`functional`, `battery_real`). With `FEELIES_REQUIRE_BASELINE_CACHE=1`
a miss is a failure (`test_backtest_app_baseline.py:282`,
`tests/position_engine/scenarios.py:2597`); without the flag it is a skip.
The parity-oracle and real-data jobs set the flag. A missing APP/2026-03-25
on the oracle replay fails the calibration assertion at
`test_backtest_app_baseline.py:402`.

Mutant-kill runs `-m "not battery_real"` (`tests/position_engine/kill.py:111`)
on synthetic catchers. Those tests do not read the event cache.

## Predictions

- E0.1 `src/` diff empty. The pins above hold. No mover.
- E0.2 `uv.lock` adds pytest-xdist and execnet only.
- E0.3 A local serial gate and a local `-n 4` gate collect the same node
  ids, and each node has the same outcome.
- E0.4 Five consecutive local `-n 4` runs pass, and per-node outcomes are
  identical across the five.
- E0.5 CI check job on the PR head: 523 s median, 743 s worst, under the
  1200 s cap. The Tests step's count line equals the local serial run.
- E0.6 On that run the guard reports `complete` in check and parity oracle.
  Every ingest step is skipped. No job saves the event cache.
- E0.7 Tests added: T1–T9 in
  `tests/conformance/test_ci_event_cache_guard.py`. Modified: the assertion
  in `tests/conformance/test_ci_gate_single_source.py` that pins the check
  job's Tests command, and only that assertion.

The check job's Tests step gains `-n 4`. prepush stays serial. pytest-xdist
is a dev extra. Every event-cache use is restore-only. check, parity oracle,
and the real-data job run the guard after restore and fail the job when a
file is missing. Ingest runs only on `workflow_dispatch` with
`inputs.allow_fetch == true`, then one explicit save, then the guard again.
Mutant-kill reports the guard and does not enforce it, and never fetches
or saves. `workflow_dispatch` still skips the check job (`ci.yml` job `if`).

Any pin move this file does not predict blocks the rung.
