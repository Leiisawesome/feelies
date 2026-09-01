"""G35 — engine 1 owns live ingress shedding; ReplayFeed cannot shed.

G35 said no queue-depth or drop policy on ingest. The live feed has one
bounded queue; ``_consume`` is the drop policy this step keeps.
``_drain_stale_sentinels`` restored into a full queue by warning and
breaking, dropping buffered events without a count or health notify.
X1 stays degradation monotonicity for G20/G23/G43; this file is the
G35 scan.

``KernelFault(kind=INGRESS_ADMIT)`` must be constructed — a taxonomy
member with no caller is an unused seam. Shedding is live-only: a
replayed tape goes through ``ReplayFeed.events()``, which has no queue.
"""

from __future__ import annotations

import ast
import queue
from pathlib import Path

from feelies.core.clock import SimulatedClock
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed
from feelies.kernel.exception_taxonomy import KernelFault

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]
_AUTHORITY = "src/feelies/ingestion/massive_ws.py"
_REPLAY = "src/feelies/ingestion/replay_feed.py"

_DRAIN = "_drain_stale_sentinels"
_POLICY_DROP = "_consume"
_SENTINEL_SKIP = "_enqueue_sentinel_nowait"
_QUEUE_TOKENS = frozenset({"Queue", "put_nowait", "Full"})


def _rel(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _is_queue_full(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    return "Full" in ast.unparse(handler.type)


def _raises_kernel_fault(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        if "KernelFault" in ast.unparse(node.exc):
            return True
    return False


def _full_handler_sites() -> list[tuple[str, int, str, bool]]:
    """Production ``except queue.Full`` handlers: (path, line, func, raises KernelFault)."""
    sites: list[tuple[str, int, str, bool]] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.ExceptHandler) or not _is_queue_full(node):
                    continue
                sites.append((rel, node.lineno, fn.name, _raises_kernel_fault(node)))
    return sites


def _ingress_admit_constructions() -> list[str]:
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func).split(".")[-1] != "KernelFault":
                continue
            for kw in node.keywords:
                if kw.arg != "kind":
                    continue
                if "INGRESS_ADMIT" in ast.unparse(kw.value):
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def _replay_queue_tokens() -> list[str]:
    path = _REPO / _REPLAY
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=_REPLAY)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _QUEUE_TOKENS:
            hits.append(f"{_REPLAY}:{node.lineno} {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _QUEUE_TOKENS:
            hits.append(f"{_REPLAY}:{node.lineno} {node.attr}")
    return hits


def test_g35_market_data_full_writers_are_in_massive_ws() -> None:
    """Market-data ``queue.Full`` handlers live on the live feed, not ReplayFeed."""
    sites = _full_handler_sites()
    assert sites, "G35 scan found no queue.Full handlers — the guard would be vacuous"
    illegal = [f"{path}:{line} {name}" for path, line, name, _ in sites if path != _AUTHORITY]
    assert not illegal, (
        "market-data queue.Full has a writer outside engine 1 "
        f"({_AUTHORITY}). First: {illegal[0]}"
    )
    names = {name for _, _, name, _ in sites}
    assert _POLICY_DROP in names, "_consume drop policy is missing"
    assert _SENTINEL_SKIP in names, "_enqueue_sentinel_nowait Full skip is missing"


def test_g35_drain_full_fails_into_ingress_admit() -> None:
    """Restore-into-full must raise KernelFault, not warn-and-break."""
    drain = [
        (path, line, raises)
        for path, line, name, raises in _full_handler_sites()
        if name == _DRAIN
    ]
    assert drain, (
        f"{_DRAIN} has no except queue.Full; G35 cannot see the silent restore drop"
    )
    silent = [f"{path}:{line}" for path, line, raises in drain if not raises]
    assert not silent, (
        f"{_DRAIN} still drops on queue.Full without KernelFault. First: {silent[0]}"
    )


def test_g35_ingress_admit_kind_is_constructed() -> None:
    """INGRESS_ADMIT must be raised, not left as an unused Kind member."""
    hits = _ingress_admit_constructions()
    assert hits, (
        "KernelFault(kind=INGRESS_ADMIT) is never constructed in src/feelies; "
        "S-30a left the Kind unused for this step to fail into"
    )
    assert any(h.startswith(_AUTHORITY) for h in hits), (
        f"INGRESS_ADMIT is constructed, but not in the engine-1 authority: {hits}"
    )


def test_g35_replay_feed_has_no_queue() -> None:
    """A replayed tape cannot hit Full — ReplayFeed has no queue."""
    hits = _replay_queue_tokens()
    assert not hits, (
        "ReplayFeed carries a queue token; shedding could engage in BACKTEST. "
        f"First: {hits[0]}"
    )


def test_g35_drain_full_raises_ingress_admit() -> None:
    clock = SimulatedClock()
    feed = MassiveLiveFeed("key", ["AAPL"], MassiveNormalizer(clock=clock), clock)
    feed._queue = _RestoreFullQueue([object()])  # type: ignore[assignment]
    try:
        feed._drain_stale_sentinels()
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.INGRESS_ADMIT
    else:
        raise AssertionError(
            "queue.Full while restoring buffered events must raise KernelFault(INGRESS_ADMIT)"
        )


class _RestoreFullQueue:
    """Yields retained items, then refuses every put — the drain-Full case."""

    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def get_nowait(self) -> object:
        if not self._items:
            raise queue.Empty
        return self._items.pop(0)

    def put_nowait(self, _item: object) -> None:
        raise queue.Full
