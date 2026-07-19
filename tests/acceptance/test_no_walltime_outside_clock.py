"""Inv-10 lint guard — no raw wall-clock reads outside the sanctioned set.

Ruff's ``DTZ`` rule flags ``datetime.now()`` / ``datetime.utcnow()`` but is
**blind** to ``time.time()`` / ``time.monotonic()`` / ``time.perf_counter()``
(determinism-audit P1 #10).  CLAUDE.md and Inv-10 nonetheless ban *all* raw
wall-clock reads in production logic — "all timestamps via the injectable
clock".  This AST-based acceptance test closes the half of that ban the
linter cannot see: every ``time.*`` / ``datetime.*`` / ``date.*`` wall-clock
call under ``src/feelies`` must live in one of the explicitly-justified files
in ``_WALL_CLOCK_ALLOWLIST``.  A new wall-clock read anywhere else fails
loudly, so a contributor cannot slip a non-deterministic timestamp into the
replay path unnoticed.

This is a *scope* guard, not a determinism proof: the allowlisted uses below
were each verified to be replay-neutral (telemetry, live-only paths, or
provenance fields excluded from the hashed/parity surface).  The point is
that any *new* use becomes a deliberate, reviewed allowlist edit instead of a
silent regression.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"

# Absolute wall-clock readers (``time.time``/``time_ns``) and process-clock
# readers (``monotonic``/``perf_counter``); the latter cannot be a logical
# timestamp but are still raw wall-clock reads Inv-10 wants funnelled through
# the injected clock or explicitly justified.
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
# Each entry was confirmed replay-neutral during the determinism audit.
_WALL_CLOCK_ALLOWLIST: dict[str, str] = {
    "core/clock.py": "canonical clock adapter — the only sanctioned wall-clock source (Inv-10)",
    "core/platform_config.py": (
        "ConfigSnapshot provenance timestamp; excluded from the deterministic "
        "config checksum (snapshot() hashes data only) so it never perturbs replay"
    ),
    "kernel/orchestrator.py": (
        "perf_counter_ns latency telemetry into _tick_timings (MetricEvent "
        "side-channel); all event timestamps use the injected clock, not this"
    ),
    # "bootstrap.py" entry removed (composition audit 2026-07-02, P1 finding):
    # the session-gated factor-loadings freshness escape it justified now
    # fails closed (raises StaleFactorLoadingsError) instead of reading the
    # wall clock when session_open_ns is unset, so bootstrap.py no longer
    # makes a raw wall-clock call at all.
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
