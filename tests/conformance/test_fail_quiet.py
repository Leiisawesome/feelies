"""S6 — no unallowlisted fail-quiet exception handler.

S-30g adjudicates the seventeen handlers S-30a left outside FILES.
An ``except`` whose body neither raises, returns, nor logs is quiet;
a keeper is permitted only as an explicit allowlist row this test reads.
A quiet handler that is not in the allowlist fails. A stale row fails.
G36.
"""

from __future__ import annotations

from typing import NamedTuple

from tools.arch.gatescan import fail_quiet_handlers


class FailQuietKeep(NamedTuple):
    path: str
    line: int
    exc_type: str
    reason: str


# Converted set is empty: every conversion would propagate KernelFault where
# the caller currently continues (behaviour change, not a type change).
# Nested raise/catch to hide from the scanner is the S-28a shape.
FAIL_QUIET_KEEP: tuple[FailQuietKeep, ...] = (
    FailQuietKeep(
        "src/feelies/alpha/layer_validator.py",
        1190,
        "(TypeError, ValueError)",
        "G17 parse fallback: malformed half-life becomes 0; the check below raises LayerValidationError",
    ),
    FailQuietKeep(
        "src/feelies/bootstrap.py",
        1607,
        "KeyError",
        "unregistered upstream SIGNAL id skipped when unioning signal_horizons; raising would fail boot",
    ),
    FailQuietKeep(
        "src/feelies/bootstrap.py",
        1825,
        "(TypeError, ValueError)",
        "malformed trend_mechanism half-life becomes 0 so derived hard_exit_age is None; raising would change HazardPolicy construction",
    ),
    FailQuietKeep(
        "src/feelies/broker/ib/connection.py",
        337,
        "queue.Empty",
        "writer-thread poll timeout; fall through to drain cancels; raising would abort the IB writer loop",
    ),
    FailQuietKeep(
        "src/feelies/broker/ib/connection.py",
        413,
        "(TypeError, ValueError)",
        "ibapi Decimal filled/remaining coerced via str; raising would drop the fill",
    ),
    FailQuietKeep(
        "src/feelies/cli/env.py",
        22,
        "ImportError",
        "optional python-dotenv; absence is a supported operator path",
    ),
    FailQuietKeep(
        "src/feelies/cli/promote.py",
        172,
        "StopIteration",
        "iterator exhausted in _read_entries_safely; standard next() termination",
    ),
    FailQuietKeep(
        "src/feelies/cli/promote.py",
        174,
        "ValueError",
        "corrupt ledger line appended to errors and returned; the caller surfaces it",
    ),
    FailQuietKeep(
        "src/feelies/composition/factor_neutralizer.py",
        28,
        "ImportError",
        "optional numpy; _HAS_NUMPY gates the numeric path",
    ),
    FailQuietKeep(
        "src/feelies/composition/factor_neutralizer.py",
        139,
        "np.linalg.LinAlgError",
        "documented lstsq fallback on singular B.T @ B; raising would change neutralization",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        591,
        "Exception",
        "stdout/stderr reconfigure best-effort on consoles that reject encoding changes",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        796,
        "Exception",
        "optional psutil HIGH_PRIORITY_CLASS; missing psutil must not skip the replay",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        833,
        "Exception",
        "best-effort nice() restore in finally; raising would mask the original exception",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ingestor.py",
        73,
        "TypeError",
        "Massive REST clone failed; reuse the caller-provided client (mocks and wrappers)",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        185,
        "queue.Empty",
        "drain-to-empty of stale stop sentinels; empty is the loop terminal",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        228,
        "asyncio.CancelledError",
        "shutdown cancellation of the background loop task; re-raising would surface as thread death",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        344,
        "asyncio.TimeoutError",
        "subscribe ack wait ended; partial subscribe is documented warn-not-raise",
    ),
)


def test_no_unallowlisted_fail_quiet_exception_handler() -> None:
    quiet = fail_quiet_handlers()
    assert quiet is not None
    found = frozenset(
        (h["path"].replace("\\", "/"), int(h["line"]), str(h["exc_type"])) for h in quiet
    )
    allowed = frozenset((k.path, k.line, k.exc_type) for k in FAIL_QUIET_KEEP)
    extra = sorted(found - allowed)
    missing = sorted(allowed - found)
    assert extra == [], (
        f"{len(extra)} fail-quiet handler(s) not in FAIL_QUIET_KEEP. First: "
        f"{extra[0][0]}:{extra[0][1]} except {extra[0][2]}"
    )
    assert missing == [], (
        f"{len(missing)} FAIL_QUIET_KEEP row(s) are not quiet. First: "
        f"{missing[0][0]}:{missing[0][1]} except {missing[0][2]}"
    )
    assert all(k.reason.strip() for k in FAIL_QUIET_KEEP), (
        "every allowlisted keeper must carry a named reason"
    )
