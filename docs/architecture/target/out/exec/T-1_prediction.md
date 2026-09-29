# T-1 pre-registered prediction

BASE: `c53be29c3043fcccb8c0295e8dc57749ee1be63e` (`arch/exec`)
PRE-CAPTURE: `docs/architecture/target/out/exec/baseline_pre-T-1.json`
with the D-110 deselect (39 node ids: 21 broker, 18 network).
BASELINE GREEN. 5216 passed / 0 failed / 5 skipped / 39 deselected / exit 0.

## Parity

NONE. 64/64 constants unchanged.
APP oracle stays 10 fills / net 24.61 / trade hash
`18f6bb4ecd7b1b1aad5158077cd6ebbc3e6db27fdab2e2effaf5a74e98545bfb`.

## Gate expression

Unchanged: `not functional and not paper_rth and not battery_real`.
Every newly marked broker or network test is already `functional`, so the
expression selects the same set.

## Parity oracle job

Unchanged collected/passed counts.
Command (from `ci.yml`): `uv run pytest tests/acceptance/test_backtest_app_baseline.py -q -m ""`.
On `c53be29c` (run 36511340767): 2 passed.

## Plain-pytest capture

Exactly the 39 tests newly marked broker or network move from deselected
(D-110 deselect) to skipped (opt-in). Nothing else changes.

| | passed | failed | skipped | deselected |
|---|---:|---:|---:|---:|
| pre-T-1 | 5216 | 0 | 5 | 39 |
| post-T-1 | 5216 | 0 | 44 | 0 |

Any other move is a STOP.
