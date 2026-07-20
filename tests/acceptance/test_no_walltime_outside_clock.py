"""Reject raw wall-clock reads outside explicitly replay-neutral files.

This AST check covers APIs such as ``time.time`` and ``perf_counter`` that
Ruff's datetime rules do not detect.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"

# Wall-clock and process-clock readers require explicit justification.
_BANNED_ATTRS = frozenset(
    {
        "now",
        "utcnow",
        "today",
        "time",
        "time_ns",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
    }
)
_BANNED_ROOTS = frozenset({"time", "datetime", "date"})

# file (relative to src/feelies) -> why a raw wall-clock read is justified.
_WALL_CLOCK_ALLOWLIST: dict[str, str] = {
    "core/clock.py": "canonical clock adapter — the only sanctioned wall-clock source (Inv-10)",
    "core/state_machine.py": (
        "perf_counter_ns transition-duration telemetry accumulated only when "
        "a timing sink is bound; transition records use the injected clock"
    ),
    "kernel/orchestrator.py": (
        "perf_counter_ns latency telemetry into _tick_timings (MetricEvent "
        "side-channel); all event timestamps use the injected clock, not this"
    ),
    # "bootstrap.py" is intentionally absent: factor-loadings freshness uses
    # session_open_ns (BACKTEST) or the injected Clock (PAPER/LIVE), never a
    # raw wall-clock read (Inv-5 / Inv-10).
    "harness/backtest_runner.py": "backtest run wall-time / progress reporting (not in the event stream)",
    "harness/backtest_prep.py": "backtest-prep progress timing (not in the event stream)",
    "broker/ib/connection.py": "live IB Gateway connection-ready timeout (live-only path)",
    "ingestion/massive_ingestor.py": "live REST page-fetch progress timing (live-only path)",
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


def test_no_raw_wall_clock_outside_allowlist() -> None:
    """Every raw wall-clock read in src/feelies must be allowlisted.

    Closes the DTZ blind spot for ``time.*``: an unjustified
    ``time.time()`` / ``time.monotonic()`` / ``time.perf_counter()`` (or a
    bare ``datetime.now()`` the linter happened to miss) in any module
    fails here even though ruff is silent.
    """
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _WALL_CLOCK_ALLOWLIST:
            continue
        for lineno, call in _wall_clock_calls(path):
            offenders.append(f"{rel}:{lineno}  {call}")

    assert not offenders, (
        "raw wall-clock reads found outside the Inv-10 allowlist — route the "
        "timestamp through the injected clock, or add the file to "
        "``_WALL_CLOCK_ALLOWLIST`` with a justification confirming it is "
        f"replay-neutral:\n  " + "\n  ".join(offenders)
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
    assert not stale, f"stale _WALL_CLOCK_ALLOWLIST entries: {stale}"
