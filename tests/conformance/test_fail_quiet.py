"""S6 — no unallowlisted fail-quiet exception handler.

S-30g adjudicates the seventeen handlers S-30a left outside FILES.
An ``except`` whose body neither raises, returns, nor logs is quiet;
a keeper is permitted only as an explicit allowlist row this test reads.
A quiet handler that is not in the allowlist fails. A stale row fails.
G36.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from tools.arch.gatescan import fail_quiet_handlers

_ROOT = Path(__file__).resolve().parents[2]


class FailQuietKeep(NamedTuple):
    path: str
    enclosing_symbol: str
    exc_type: str
    reason: str


def _function_spans(tree: ast.AST) -> list[tuple[int, int, str]]:
    """``def`` line, last line, name for every function in *tree*."""
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            spans.append((node.lineno, end, node.name))
    return spans


def _enclosing_symbol(spans: list[tuple[int, int, str]], lineno: int) -> str | None:
    covering = [(end - start, name) for start, end, name in spans if start <= lineno <= end]
    if not covering:
        return None
    covering.sort()
    return covering[0][1]


# Converted set is empty: every conversion would propagate KernelFault where
# the caller currently continues (behaviour change, not a type change).
# Nested raise/catch to hide from the scanner is the S-28a shape.
FAIL_QUIET_KEEP: tuple[FailQuietKeep, ...] = (
    FailQuietKeep(
        "src/feelies/alpha/layer_validator.py",
        "_check_g17_safety_exit_policy",
        "(TypeError, ValueError)",
        "G17 parse fallback: malformed half-life becomes 0; the check below raises LayerValidationError",
    ),
    FailQuietKeep(
        "src/feelies/bootstrap.py",
        "_create_composition_layer",
        "KeyError",
        "unregistered upstream SIGNAL id skipped when unioning signal_horizons; raising would fail boot",
    ),
    FailQuietKeep(
        "src/feelies/bootstrap.py",
        "_create_hazard_exit_controller",
        "(TypeError, ValueError)",
        "malformed trend_mechanism half-life becomes 0 so derived hard_exit_age is None; raising would change HazardPolicy construction",
    ),
    FailQuietKeep(
        "src/feelies/broker/ib/connection.py",
        "_drain_writer_queues",
        "queue.Empty",
        "writer-thread poll timeout; fall through to drain cancels; raising would abort the IB writer loop",
    ),
    FailQuietKeep(
        "src/feelies/broker/ib/connection.py",
        "orderStatus",
        "(TypeError, ValueError)",
        "ibapi Decimal filled/remaining coerced via str; raising would drop the fill",
    ),
    FailQuietKeep(
        "src/feelies/cli/env.py",
        "load_dotenv_optional",
        "ImportError",
        "optional python-dotenv; absence is a supported operator path",
    ),
    FailQuietKeep(
        "src/feelies/cli/promote.py",
        "_read_entries_safely",
        "StopIteration",
        "iterator exhausted in _read_entries_safely; standard next() termination",
    ),
    FailQuietKeep(
        "src/feelies/cli/promote.py",
        "_read_entries_safely",
        "ValueError",
        "corrupt ledger line appended to errors and returned; the caller surfaces it",
    ),
    FailQuietKeep(
        "src/feelies/composition/factor_neutralizer.py",
        "<module>",
        "ImportError",
        "optional numpy; _HAS_NUMPY gates the numeric path",
    ),
    FailQuietKeep(
        "src/feelies/composition/factor_neutralizer.py",
        "neutralize",
        "np.linalg.LinAlgError",
        "documented lstsq fallback on singular B.T @ B; raising would change neutralization",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        "_force_utf8_console",
        "Exception",
        "stdout/stderr reconfigure best-effort on consoles that reject encoding changes",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        "_run_backtest_phases_2_7",
        "Exception",
        "optional psutil HIGH_PRIORITY_CLASS; missing psutil must not skip the replay",
    ),
    FailQuietKeep(
        "src/feelies/harness/backtest_runner.py",
        "_run_backtest_phases_2_7",
        "Exception",
        "best-effort nice() restore in finally; raising would mask the original exception",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ingestor.py",
        "_clone_parallel_clients",
        "TypeError",
        "Massive REST clone failed; reuse the caller-provided client (mocks and wrappers)",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        "_drain_stale_sentinels",
        "queue.Empty",
        "drain-to-empty of stale stop sentinels; empty is the loop terminal",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        "_run_loop",
        "asyncio.CancelledError",
        "shutdown cancellation of the background loop task; re-raising would surface as thread death",
    ),
    FailQuietKeep(
        "src/feelies/ingestion/massive_ws.py",
        "_subscribe",
        "asyncio.TimeoutError",
        "subscribe ack wait ended; partial subscribe is documented warn-not-raise",
    ),
)


def test_no_unallowlisted_fail_quiet_exception_handler() -> None:
    quiet = fail_quiet_handlers()
    assert quiet is not None
    found: Counter[tuple[str, str, str]] = Counter()
    spans_by_path: dict[str, list[tuple[int, int, str]]] = {}
    for h in quiet:
        path = h["path"].replace("\\", "/")
        if path not in spans_by_path:
            tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
            spans_by_path[path] = _function_spans(tree)
        raw = _enclosing_symbol(spans_by_path[path], int(h["line"]))
        symbol = "<module>" if raw is None else raw
        found[(path, symbol, str(h["exc_type"]))] += 1
    allowed: Counter[tuple[str, str, str]] = Counter(
        (k.path, k.enclosing_symbol, k.exc_type) for k in FAIL_QUIET_KEEP
    )
    extra = found - allowed
    missing = allowed - found
    extra_keys = sorted(extra)
    missing_keys = sorted(missing)
    assert extra == Counter(), (
        f"{sum(extra.values())} fail-quiet handler(s) not in FAIL_QUIET_KEEP. First: "
        f"{extra_keys[0][0]}:{extra_keys[0][1]} except {extra_keys[0][2]}"
    )
    assert missing == Counter(), (
        f"{sum(missing.values())} FAIL_QUIET_KEEP row(s) are not quiet. First: "
        f"{missing_keys[0][0]}:{missing_keys[0][1]} except {missing_keys[0][2]}"
    )
    assert all(k.reason.strip() for k in FAIL_QUIET_KEEP), (
        "every allowlisted keeper must carry a named reason"
    )
