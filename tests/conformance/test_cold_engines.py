"""A2 — governance and forensics stay off the tick path.

CORE §C.10: whether an alpha is live is resolved at composition, never
re-evaluated per event. Phase 6 requires both halves in one test:
zero reads under instrumentation, and no import/write edge from
engine 12 onto engine 5. Asserting only the read half would report
the invariant as satisfied while G18's cross-engine write remains.
"""

from __future__ import annotations

import ast
from pathlib import Path

from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import build_platform
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.promotion.lifecycle import AlphaLifecycle
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.harness.engine_probe import EngineProbe
from tests.conformance.test_null_alpha_conservation import (
    _HORIZON_SECONDS,
    _NULL_ALPHA,
    _SENSOR_SPECS,
    _UNIVERSE,
    _synth_events,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_BREAKER = _SRC / "forensics" / "cost_circuit_breaker.py"


def _promotion_import_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod == "feelies.promotion" or mod.startswith("feelies.promotion."):
                hits.append(f"{path.as_posix()}:{node.lineno} import {mod}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "feelies.promotion" or name.startswith("feelies.promotion."):
                    hits.append(f"{path.as_posix()}:{node.lineno} import {name}")
    return hits


def _quarantine_call_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else ""
        )
        if name == "quarantine":
            lines.append(node.lineno)
    return lines


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_governance_and_forensics_zero_reads_on_tick_path() -> None:
    """A2 both halves: composition-time governance, engine 12 does not write."""
    reads: list[str] = []
    orig_live = AlphaLifecycle.is_live.fget
    orig_active = AlphaLifecycle.is_active.fget
    orig_active_alphas = AlphaRegistry.active_alphas
    orig_get = AlphaRegistry.get_lifecycle
    orig_states = AlphaRegistry.lifecycle_states
    assert orig_live is not None
    assert orig_active is not None

    def _live(self: AlphaLifecycle) -> bool:
        reads.append("is_live")
        return orig_live(self)

    def _active(self: AlphaLifecycle) -> bool:
        reads.append("is_active")
        return orig_active(self)

    def _active_alphas(self: AlphaRegistry) -> object:
        reads.append("active_alphas")
        return orig_active_alphas(self)

    def _get(self: AlphaRegistry, alpha_id: str) -> object:
        reads.append("get_lifecycle")
        return orig_get(self, alpha_id)

    def _states(self: AlphaRegistry) -> object:
        reads.append("lifecycle_states")
        return orig_states(self)

    AlphaLifecycle.is_live = property(_live)
    AlphaLifecycle.is_active = property(_active)
    AlphaRegistry.active_alphas = _active_alphas  # type: ignore[method-assign]
    AlphaRegistry.get_lifecycle = _get  # type: ignore[method-assign]
    AlphaRegistry.lifecycle_states = _states  # type: ignore[method-assign]
    try:
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
        events = _synth_events()
        event_log = InMemoryEventLog()
        event_log.append_batch(events)
        orchestrator, _ = build_platform(config, event_log=event_log)
        probe = EngineProbe(
            positions=orchestrator._positions,
            symbols=tuple(sorted(config.symbols)),
            engine_modules=("feelies.promotion", "feelies.forensics", "feelies.alpha"),
        )
        probe.attach(orchestrator._bus)
        orchestrator.boot(config)
        reads_at_arm = list(reads)
        orchestrator.run_backtest()
    finally:
        AlphaLifecycle.is_live = property(orig_live)
        AlphaLifecycle.is_active = property(orig_active)
        AlphaRegistry.active_alphas = orig_active_alphas
        AlphaRegistry.get_lifecycle = orig_get
        AlphaRegistry.lifecycle_states = orig_states

    assert probe.event_count >= len(events), (
        f"probe saw {probe.event_count} events but {len(events)} were fed — "
        "the replay did not run, so the read half is vacuous"
    )
    tick_reads = reads[len(reads_at_arm) :]
    assert not tick_reads, f"governance read on the tick path: {tick_reads[0]}"
    promo_reads = [r for r in probe.fact_reads if r.engine.startswith("feelies.promotion")]
    forensic_reads = [r for r in probe.fact_reads if r.engine.startswith("feelies.forensics")]
    assert not promo_reads, (
        f"engine 5 bus read on the tick path: {promo_reads[0].engine} {promo_reads[0].fact}"
    )
    assert not forensic_reads, (
        f"engine 12 bus read on the tick path: {forensic_reads[0].engine} {forensic_reads[0].fact}"
    )

    promo_imports = _promotion_import_sites(_BREAKER)
    assert not promo_imports, (
        "engine 12 imports engine 5 — G18 write authority is still an import "
        f"edge: {promo_imports[0]}"
    )
    q_calls = _quarantine_call_lines(_BREAKER)
    assert not q_calls, (
        "engine 12 still calls quarantine — LIVE->QUARANTINED is written "
        f"from forensics at cost_circuit_breaker.py:{q_calls[0]}"
    )
    assert "apply_cost_circuit_breaker" not in _function_names(_BREAKER), (
        "apply_cost_circuit_breaker still defined — engine 12 still writes "
        "lifecycle state"
    )
