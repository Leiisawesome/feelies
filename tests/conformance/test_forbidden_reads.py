"""S14 — forbidden-reads matrix, static and dynamic.

G37: no forbidden-read assertion exists in src/feelies. S14 materialises
one row per (engine, fact) pair and checks both halves against it.

Engines are the twelve independence-contract modules in pyproject.toml.
Facts are the contracts already enumerated in wiring_manifest.SUBSCRIPTIONS,
gate_registry.GATE_REGISTRY, and sequence_authority.STREAM_AUTHORITIES.
A pair is allowed only when those registries attribute a subscription,
gate ownership, or stream/contract authority to that engine. Kernel,
bootstrap, and features are not engines — a Tier-1 read on an engine's
behalf has no cell.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Sequence
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.gate_registry import GATE_REGISTRY
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.sequence_authority import STREAM_AUTHORITIES
from feelies.core.wiring_manifest import SUBSCRIPTIONS, ZERO_SUBSCRIBER_RESOLUTIONS
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.harness.engine_probe import EngineProbe, FactRead
from tests.conformance.test_null_alpha_conservation import (
    _HORIZON_SECONDS,
    _NULL_ALPHA,
    _SENSOR_SPECS,
    _UNIVERSE,
    _synth_events,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.integration.test_phase4_e2e import (
    _make_phase4_config,
    _synth_multi_symbol_events,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]


def _load_matrix() -> tuple[object, ...]:
    try:
        from feelies.core.forbidden_reads import FORBIDDEN_READS
    except ImportError:
        return ()
    return tuple(FORBIDDEN_READS)


def _independence_engines() -> tuple[str, ...]:
    raw = tomllib.loads((_REPO / "pyproject.toml").read_bytes().decode())
    for contract in raw["tool"]["importlinter"]["contracts"]:
        if contract.get("id") == "engines" and contract.get("type") == "independence":
            return tuple(contract["modules"])
    raise AssertionError("pyproject.toml has no twelve-engine independence contract")


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


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _class_to_engine(engines: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    colliding: list[str] = []
    for engine in engines:
        pkg = engine.split(".", 1)[1]
        root = _SRC / pkg
        if not root.is_dir():
            raise AssertionError(f"independence engine has no package: {engine}")
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
    assert not colliding, f"cannot attribute class to one engine: {colliding[0]}"
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
        assert 1 <= owner <= n, (
            f"cannot attribute gate {rec.stable_id} owner_engine={owner}"
        )
        allowed.add((engines[owner - 1], "gate", rec.stable_id))
    return allowed


def _expected_forbidden() -> list[tuple[str, str, str]]:
    engines = _independence_engines()
    class_engine = _class_to_engine(engines)
    allowed = _allowed_pairs(engines, class_engine)
    out: list[tuple[str, str, str]] = []
    for engine in engines:
        for kind, fact in _facts():
            if (engine, kind, fact) not in allowed:
                out.append((engine, kind, fact))
    return out


def _row_key(row: object) -> tuple[str, str, str]:
    return (
        str(getattr(row, "engine", "")),
        str(getattr(row, "kind", "")),
        str(getattr(row, "fact", "")),
    )


def _engine_of_module(mod: str, engines: Sequence[str]) -> str | None:
    for engine in engines:
        if mod == engine or mod.startswith(engine + "."):
            return engine
    return None


def _scan_forbidden_accesses(
    engines: Sequence[str],
    event_facts: set[str],
    stream_facts: set[str],
    allowed: set[tuple[str, str, str]],
) -> list[str]:
    """Import and attribute-access sites that the matrix forbids."""
    hits: list[str] = []
    for engine in engines:
        pkg = engine.split(".", 1)[1]
        for path in sorted((_SRC / pkg).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(_REPO).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    src_engine = _engine_of_module(node.module, engines)
                    if src_engine is None or src_engine == engine:
                        continue
                    for alias in node.names:
                        name = alias.name
                        if name in event_facts:
                            key = (engine, "event", name)
                            if key not in allowed:
                                hits.append(
                                    f"{rel}:{node.lineno} {engine} event {name}"
                                )
                        if name in stream_facts:
                            key = (engine, "stream", name)
                            if key not in allowed:
                                hits.append(
                                    f"{rel}:{node.lineno} {engine} stream {name}"
                                )
                if not isinstance(node, ast.Call):
                    continue
                func = _dotted(node.func).split(".")[-1]
                if func == "subscribe" and node.args:
                    arg = node.args[0]
                    fact: str | None = None
                    if isinstance(arg, ast.Name):
                        fact = arg.id
                    elif isinstance(arg, ast.Attribute):
                        fact = arg.attr
                    if fact is not None and fact in event_facts:
                        key = (engine, "event", fact)
                        if key not in allowed:
                            hits.append(
                                f"{rel}:{node.lineno} {engine} event {fact}"
                            )
                for kw in node.keywords:
                    if kw.arg != "stream":
                        continue
                    if not isinstance(kw.value, ast.Constant):
                        continue
                    if not isinstance(kw.value.value, str):
                        continue
                    fact = kw.value.value
                    if fact not in stream_facts:
                        continue
                    key = (engine, "stream", fact)
                    if key not in allowed:
                        hits.append(
                            f"{rel}:{node.lineno} {engine} stream {fact}"
                        )
    return hits


def test_s14_static_matrix_and_access_analysis() -> None:
    """Every (engine, fact) pair has a row; no engine accesses a forbidden fact."""
    engines = _independence_engines()
    assert engines, "twelve-engine independence contract is empty"
    expected = _expected_forbidden()
    assert expected, "derived forbidden-reads set is empty"
    matrix = _load_matrix()
    actual = {_row_key(row) for row in matrix}
    missing = [pair for pair in expected if pair not in actual]
    assert not missing, (
        "forbidden-reads matrix missing pair: "
        f"{missing[0][0]} {missing[0][1]} {missing[0][2]}"
    )
    extra = sorted(actual - set(expected))
    assert not extra, (
        "forbidden-reads matrix missing pair: "
        f"{extra[0][0]} {extra[0][1]} {extra[0][2]}"
    )
    class_engine = _class_to_engine(engines)
    allowed = _allowed_pairs(engines, class_engine)
    event_facts = {fact for kind, fact in _facts() if kind == "event"}
    stream_facts = {fact for kind, fact in _facts() if kind == "stream"}
    hits = _scan_forbidden_accesses(engines, event_facts, stream_facts, allowed)
    assert not hits, f"forbidden read: {hits[0]}"


def _subscriber_engines() -> frozenset[str]:
    """Engines that own a wiring-manifest subscriber. Derived, not chosen."""
    class_engine = _class_to_engine(_independence_engines())
    return frozenset(
        class_engine[sub.subscriber]
        for sub in SUBSCRIPTIONS
        if sub.subscriber in class_engine
    )


def _run_replay(config: PlatformConfig, events: list[object]) -> EngineProbe:
    event_log = InMemoryEventLog()
    event_log.append_batch(events)
    orchestrator, _ = build_platform(config, event_log=event_log)
    probe = EngineProbe(
        positions=orchestrator._positions,
        symbols=tuple(sorted(config.symbols)),
        engine_modules=_independence_engines(),
    )
    probe.attach(orchestrator._bus)
    orchestrator.boot(config)
    orchestrator.run_backtest()
    assert probe.event_count >= len(events), (
        f"probe saw {probe.event_count} events but {len(events)} were fed in — "
        "the replay did not run, so the forbidden-read check is vacuous"
    )
    return probe


def _replay_null_alpha() -> EngineProbe:
    config = PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine="hmm_3state_fractional",
        sensor_specs=_SENSOR_SPECS,
        horizons_seconds=frozenset({_HORIZON_SECONDS}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        enforce_trend_mechanism=False,
    )
    return _run_replay(config, _synth_events())


def _replay_phase4() -> EngineProbe:
    config = _make_phase4_config()
    return _run_replay(config, _synth_multi_symbol_events())


def _forbidden_hits(
    reads: tuple[FactRead, ...], forbidden: set[tuple[str, str, str]]
) -> list[FactRead]:
    return [
        read
        for read in reads
        if (read.engine, read.kind, read.fact) in forbidden
    ]


def test_s14_dynamic_no_forbidden_read_during_tick_sequence() -> None:
    """HARN-1 instruments each engine read surface and asserts none are forbidden.

    Null-alpha covers the SIGNAL-only subscribers. Phase-4 wires PORTFOLIO so
    composition, portfolio, and monitoring attach. Together they are the
    engines that own a bus subscription.
    """
    matrix = _load_matrix()
    assert matrix, "no forbidden-reads matrix"
    forbidden = {_row_key(row) for row in matrix}
    expected_engines = _subscriber_engines()
    assert len(expected_engines) == 7, (
        f"wiring manifest attributes {len(expected_engines)} subscriber "
        f"engines, expected 7: {sorted(expected_engines)}"
    )

    null_probe = _replay_null_alpha()
    assert null_probe.fact_reads, "probe observed no reads"
    null_hits = _forbidden_hits(null_probe.fact_reads, forbidden)
    assert not null_hits, (
        f"forbidden read: {null_hits[0].engine} {null_hits[0].kind} "
        f"{null_hits[0].fact}"
    )

    phase4_probe = _replay_phase4()
    assert phase4_probe.fact_reads, "probe observed no reads"
    phase4_hits = _forbidden_hits(phase4_probe.fact_reads, forbidden)
    assert not phase4_hits, (
        f"forbidden read: {phase4_hits[0].engine} {phase4_hits[0].kind} "
        f"{phase4_hits[0].fact}"
    )

    observed = {read.engine for read in null_probe.fact_reads} | {
        read.engine for read in phase4_probe.fact_reads
    }
    missing = sorted(expected_engines - observed)
    extra = sorted(observed - expected_engines)
    assert not missing and not extra, (
        f"subscriber engines not observed: missing {missing}; extra {extra}"
    )
