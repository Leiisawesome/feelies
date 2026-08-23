"""Reject raw wall-clock reads outside explicitly replay-neutral files.

This AST check covers APIs such as ``time.time`` and ``perf_counter`` that
Ruff's datetime rules do not detect.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from tools.arch.clockscan import CLOCK_LEAVES, CLOCK_RECEIVERS

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"

# Promoted from clockscan: the leaf names that read the machine clock.
_BANNED_ATTRS = CLOCK_LEAVES
_BANNED_ROOTS = CLOCK_RECEIVERS

# file (relative to src/feelies) -> why a raw wall-clock read is justified.
# The orchestrator is not on this list: a whole-file exemption covered 5,480
# lines. Call-granular entries live in _WALL_CLOCK_CALL_ALLOWLIST (S4 / G01).
_WALL_CLOCK_ALLOWLIST: dict[str, str] = {
    "core/clock.py": "canonical clock adapter — the only sanctioned wall-clock source (Inv-10)",
    "core/state_machine.py": (
        "perf_counter_ns transition-duration telemetry accumulated only when "
        "a timing sink is bound; transition records use the injected clock"
    ),
    # "bootstrap.py" is intentionally absent: factor-loadings freshness uses
    # session_open_ns (BACKTEST) or the injected Clock (PAPER), never a
    # raw wall-clock read (Inv-5 / Inv-10).
    "harness/backtest_runner.py": "backtest run wall-time / progress reporting (not in the event stream)",
    "harness/backtest_prep.py": "backtest-prep progress timing (not in the event stream)",
    "broker/ib/connection.py": "live IB Gateway connection-ready timeout (live-only path)",
    "ingestion/massive_ingestor.py": "live REST page-fetch progress timing (live-only path)",
}

# Call-granular orchestrator entries. Seven are (lineno, "root.attr()") and
# stay line-pinned. G01's three proven per-event residuals are keyed by
# enclosing symbol so S-32 survives insertions: _process_tick_inner,
# _finalize_tick, _drain_async_fills. Latency telemetry into _tick_timings;
# event timestamps still use the injected clock. G01 residual closed by S-32.
_WALL_CLOCK_CALL_ALLOWLIST: dict[str, frozenset[tuple[int | str, str]]] = {
    "kernel/orchestrator.py": frozenset(
        {
            (1642, "time.perf_counter_ns()"),
            (1644, "time.perf_counter_ns()"),
            (1684, "time.perf_counter_ns()"),
            (1686, "time.perf_counter_ns()"),
            (1780, "time.perf_counter_ns()"),
            (1782, "time.perf_counter_ns()"),
            (3794, "time.perf_counter_ns()"),
            ("_process_tick_inner", "time.perf_counter_ns()"),
            ("_finalize_tick", "time.perf_counter_ns()"),
            ("_drain_async_fills", "time.perf_counter_ns()"),
        }
    ),
}


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _wall_clock_calls(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _BANNED_ATTRS
        ):
            root = _root_name(node.func.value)
            if root in _BANNED_ROOTS:
                hits.append((node.lineno, f"{root}.{node.func.attr}()"))
    return hits


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


def _split_allowlist(
    allowed: frozenset[tuple[int | str, str]],
) -> tuple[frozenset[tuple[int, str]], frozenset[tuple[str, str]]]:
    by_line: set[tuple[int, str]] = set()
    by_symbol: set[tuple[str, str]] = set()
    for key, call in allowed:
        if isinstance(key, int):
            by_line.add((key, call))
        else:
            by_symbol.add((key, call))
    return frozenset(by_line), frozenset(by_symbol)


def _consume_allowlist(
    path: Path,
    allowed: frozenset[tuple[int | str, str]],
) -> tuple[list[tuple[int, str]], list[tuple[str, str]]]:
    """Return (offenders, unused symbol entries) after applying line then symbol keys.

    Each symbol entry admits one leftover call inside that function. A second
    unmatched read in a symbol-keyed function is still an offender.
    """
    hits = _wall_clock_calls(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    spans = _function_spans(tree)
    by_line, by_symbol = _split_allowlist(allowed)
    leftover: list[tuple[int, str, str | None]] = []
    for lineno, call in hits:
        if (lineno, call) in by_line:
            continue
        leftover.append((lineno, call, _enclosing_symbol(spans, lineno)))
    budget: Counter[tuple[str, str]] = Counter(by_symbol)
    offenders: list[tuple[int, str]] = []
    for lineno, call, symbol in leftover:
        key = (symbol, call) if symbol is not None else None
        if key is not None and budget[key] > 0:
            budget[key] -= 1
            continue
        offenders.append((lineno, call))
    unused = [entry for entry, n in budget.items() if n > 0]
    return offenders, unused


def test_no_raw_wall_clock_outside_allowlist() -> None:
    """Every raw wall-clock read in src/feelies must be allowlisted.

    Closes the DTZ blind spot for ``time.*``: an unjustified
    ``time.time()`` / ``time.monotonic()`` / ``time.perf_counter()`` (or a
    bare ``datetime.now()`` the linter happened to miss) in any module
    fails here even though ruff is silent.  The orchestrator is gated
    per call, not per file (G01).
    """
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _WALL_CLOCK_ALLOWLIST:
            continue
        allowed_calls = _WALL_CLOCK_CALL_ALLOWLIST.get(rel, frozenset())
        offenders_here, _unused = _consume_allowlist(path, allowed_calls)
        for lineno, call in offenders_here:
            offenders.append(f"{rel}:{lineno}  {call}")

    assert not offenders, (
        "raw wall-clock reads found outside the Inv-10 allowlist — route the "
        "timestamp through the injected clock, or add the file to "
        "``_WALL_CLOCK_ALLOWLIST`` / the call-granular list with a "
        "justification confirming it is replay-neutral:\n  " + "\n  ".join(offenders)
    )


def test_wall_clock_allowlist_has_no_stale_entries() -> None:
    """Keep the allowlist honest: every entry must exist and still use a clock.

    Prevents the allowlist from rubber-stamping files that were renamed or
    have since dropped their wall-clock use (which would let a later
    re-introduction slip through silently).
    """
    stale: list[str] = []
    for rel in _WALL_CLOCK_ALLOWLIST:
        path = _SRC / rel
        if not path.is_file():
            stale.append(f"{rel} (file missing)")
        elif not _wall_clock_calls(path):
            stale.append(f"{rel} (no wall-clock call left — drop the allowlist entry)")
    for rel, allowed in _WALL_CLOCK_CALL_ALLOWLIST.items():
        path = _SRC / rel
        if not path.is_file():
            stale.append(f"{rel} (call-allowlist file missing)")
            continue
        present = set(_wall_clock_calls(path))
        by_line, _ = _split_allowlist(allowed)
        for entry in sorted(by_line):
            if entry not in present:
                stale.append(
                    f"{rel}:{entry[0]} {entry[1]} (call gone — drop the call-allowlist entry)"
                )
        _, unused_symbols = _consume_allowlist(path, allowed)
        for symbol, call in sorted(unused_symbols):
            stale.append(f"{rel}:{symbol} {call} (call gone — drop the call-allowlist entry)")
    assert not stale, f"stale _WALL_CLOCK_ALLOWLIST entries: {stale}"
