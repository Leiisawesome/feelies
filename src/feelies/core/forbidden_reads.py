"""Forbidden-reads matrix (G37).

One row per forbidden (engine, fact) pair. Engines are the twelve
independence-contract modules transcribed from pyproject.toml. Facts are
the contracts already enumerated in wiring_manifest.SUBSCRIPTIONS,
gate_registry.GATE_REGISTRY, and sequence_authority.STREAM_AUTHORITIES.

A read is allowed when those registries attribute it to that engine
(subscription, gate ownership, or stream/contract authority). Otherwise
it is forbidden. Kernel, bootstrap, and features are not engines: a
Tier-1 read on an engine's behalf has no cell.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from feelies.core.gate_registry import GATE_REGISTRY
from feelies.core.sequence_authority import STREAM_AUTHORITIES
from feelies.core.wiring_manifest import SUBSCRIPTIONS, ZERO_SUBSCRIBER_RESOLUTIONS

_FEELIES = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class ForbiddenRead:
    """One forbidden (engine, fact) cell of the matrix."""

    engine: str
    kind: str
    fact: str


ENGINES: tuple[str, ...] = (
    "feelies.ingestion",
    "feelies.sensors",
    "feelies.services",
    "feelies.signals",
    "feelies.alpha",
    "feelies.composition",
    "feelies.portfolio",
    "feelies.risk",
    "feelies.execution",
    "feelies.broker",
    "feelies.monitoring",
    "feelies.forensics",
)


def _facts() -> tuple[tuple[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    def add(kind: str, fact: str) -> None:
        key = (kind, fact)
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    for sub in SUBSCRIPTIONS:
        add("event", sub.event_type)
    for event_type, _resolution in ZERO_SUBSCRIBER_RESOLUTIONS:
        add("event", event_type)
    for gid in GATE_REGISTRY:
        add("gate", gid)
    for row in STREAM_AUTHORITIES:
        add("stream", row.stream)
        for contract in row.contracts:
            add("event", contract)
    return tuple(ordered)


def _class_to_engine(engines: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    colliding: list[str] = []
    for engine in engines:
        pkg = engine.split(".", 1)[1]
        root = _FEELIES / pkg
        if not root.is_dir():
            raise RuntimeError(f"independence engine has no package: {engine}")
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                prior = mapping.get(node.name)
                if prior is not None and prior != engine:
                    colliding.append(f"{node.name}: {prior} vs {engine}")
                mapping[node.name] = engine
    if colliding:
        raise RuntimeError(f"cannot attribute class to one engine: {colliding[0]}")
    return mapping


def _allowed_pairs(
    engines: Sequence[str], class_engine: dict[str, str]
) -> set[tuple[str, str, str]]:
    allowed: set[tuple[str, str, str]] = set()
    for sub in SUBSCRIPTIONS:
        engine = class_engine.get(sub.subscriber)
        if engine is not None:
            allowed.add((engine, "event", sub.event_type))
    for row in STREAM_AUTHORITIES:
        engine = class_engine.get(row.authority)
        if engine is None:
            continue
        allowed.add((engine, "stream", row.stream))
        for contract in row.contracts:
            allowed.add((engine, "event", contract))
    n = len(engines)
    for rec in GATE_REGISTRY.values():
        owner = rec.owner_engine
        if not 1 <= owner <= n:
            raise RuntimeError(
                f"cannot attribute gate {rec.stable_id} owner_engine={owner}"
            )
        allowed.add((engines[owner - 1], "gate", rec.stable_id))
    return allowed


def _build_forbidden() -> tuple[ForbiddenRead, ...]:
    class_engine = _class_to_engine(ENGINES)
    allowed = _allowed_pairs(ENGINES, class_engine)
    rows: list[ForbiddenRead] = []
    for engine in ENGINES:
        for kind, fact in _facts():
            if (engine, kind, fact) not in allowed:
                rows.append(ForbiddenRead(engine=engine, kind=kind, fact=fact))
    return tuple(rows)


FORBIDDEN_READS: tuple[ForbiddenRead, ...] = _build_forbidden()
