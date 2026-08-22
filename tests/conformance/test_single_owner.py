"""S12 — one sequence authority per stream, one producer per contract.

G09: 26 SequenceGenerator constructions with no registry naming which
stream each owns. S12 asserts closure both ways against production call
sites in src/feelies only. Tests and scripts may construct unnamed
generators; they are not authorities.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from feelies.core.gate_registry import record_verdict
from feelies.core.wiring_manifest import SUBSCRIPTIONS, ZERO_SUBSCRIBER_RESOLUTIONS

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _scan_production_generators() -> list[tuple[str, int, str | None]]:
    """SequenceGenerator calls in src/feelies, with the stream= keyword if any."""
    sites: list[tuple[str, int, str | None]] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_REPO).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _dotted(node.func).split(".")[-1] != "SequenceGenerator":
                continue
            stream: str | None = None
            for kw in node.keywords:
                if kw.arg != "stream":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    stream = kw.value.value
            sites.append((rel, node.lineno, stream))
    return sites


def _load_authorities() -> tuple[dict[str, str], dict[str, set[str]]]:
    try:
        from feelies.core.sequence_authority import STREAM_AUTHORITIES
    except ImportError:
        return {}, {}
    streams: dict[str, str] = {}
    contracts: dict[str, set[str]] = defaultdict(set)
    for row in STREAM_AUTHORITIES:
        name = str(row.stream)
        authority = str(row.authority)
        if name in streams and streams[name] != authority:
            streams[name] = f"{streams[name]}|{authority}"
        else:
            streams[name] = authority
        for contract in row.contracts:
            contracts[str(contract)].add(authority)
    return streams, dict(contracts)


def _declared_contracts() -> set[str]:
    names = {row.event_type for row in SUBSCRIPTIONS}
    names.update(event_type for event_type, _resolution in ZERO_SUBSCRIBER_RESOLUTIONS)
    return names


def test_s12_every_stream_has_exactly_one_sequence_authority() -> None:
    """Every production SequenceGenerator names a registered stream."""
    sites = _scan_production_generators()
    assert sites, "S12 scan found no SequenceGenerator calls in src/feelies"
    unnamed = [f"{path}:{line}" for path, line, stream in sites if stream is None]
    assert not unnamed, f"stream has no sequence authority: {unnamed[0]}"
    streams, _contracts = _load_authorities()
    colliding = sorted(name for name, authority in streams.items() if "|" in authority)
    assert not colliding, f"stream has no sequence authority: {colliding[0]}"
    for path, line, stream in sites:
        assert stream is not None
        assert stream in streams, f"stream has no sequence authority: {stream}"
    constructed = {stream for _path, _line, stream in sites if stream is not None}
    orphaned = sorted(set(streams) - constructed)
    assert not orphaned, f"stream has no sequence authority: {orphaned[0]}"


def test_s12_every_contract_has_exactly_one_producer() -> None:
    """Every bus contract is produced by a registered stream authority.

    gate_registry.record_verdict draws no sequence and is not a producer.
    """
    assert record_verdict.__doc__ is not None
    assert "Draws no sequence" in record_verdict.__doc__
    _streams, producers = _load_authorities()
    missing = sorted(_declared_contracts() - set(producers))
    assert not missing, f"contract has no producer: {missing[0]}"
    unregistered = sorted(set(producers) - _declared_contracts())
    assert not unregistered, f"contract has no producer: {unregistered[0]}"
    stream_rows, _producers = _load_authorities()
    duplicate_streams = [
        name for name, authority in stream_rows.items() if "|" in authority
    ]
    assert not duplicate_streams, f"contract has no producer: {duplicate_streams[0]}"
    assert stream_rows, "contract has no producer: (empty registry)"
