"""Enumerable gate registry — 19 governance + 34 runtime spine.

Identity is a stable string; ordinals are dense per ladder so a numbering
hole cannot recur. G1-G17 survive as aliases; G13 is retired (warm-up is
``RT.FEATURE_WARMTH`` and was never a LayerValidator method).

``RT.SCHEMA_SUPPORTED``, ``RT.CONTRACT_CONFORM`` and ``RT.IN_UNIVERSE`` are
per-boundary family templates (Phase 3 D.4). Their instance count is
generated from the wiring manifest at S-12; they are not registry rows.

Verdicts are recorded on engine 11's notification channel by
:func:`record_verdict`. That function does not import a sequence
generator, does not draw a sequence number, and does not publish on the
domain bus.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Literal

_OUTCOMES = frozenset({"PASS", "FAIL", "UNKNOWN", "NOT_EVALUATED"})
_KNOWN_TESTS = frozenset({"S13", "X6", "X3", "X4", "S8", "S9", "H1", "S6"})
_LEG_ORDER = ("E", "Q", "B", "D", "P", "S", "F")


@dataclass(frozen=True, kw_only=True)
class GateRecord:
    """One declared gate. Predicates live at the call site, not here."""

    stable_id: str
    ladder: str
    owner_engine: int
    latency_class: str
    leg: str
    rank: int
    ordinal: int = 0
    family: str = "none"
    predicate: str = ""
    on_fail: str = ""
    on_unknown: str = ""
    exposure_effect: str = "<= ungated"
    monotone: str = "yes"
    disableable: str = "no"
    tested_by: tuple[str, ...] = ()
    bind_markers: tuple[str, ...] = ()
    site_exemption: str = ""


@dataclass(frozen=True, kw_only=True)
class _Alias:
    stable_id: str | None
    kind: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class VerdictRecord:
    gate_id: str
    outcome: str
    reason: str = ""
    alias: str = ""


def _gov(
    stable_id: str,
    *,
    rank: int,
    predicate: str,
    on_fail: str,
    on_unknown: str | None = None,
    disableable: str = "no",
    bind_markers: tuple[str, ...] = (),
    site_exemption: str = "",
    tested_by: tuple[str, ...] = ("S13", "X6"),
) -> GateRecord:
    return GateRecord(
        stable_id=stable_id,
        ladder="governance",
        owner_engine=5,
        latency_class="cold",
        leg="GOV",
        rank=rank,
        predicate=predicate,
        on_fail=on_fail,
        on_unknown=on_fail if on_unknown is None else on_unknown,
        disableable=disableable,
        tested_by=tested_by,
        bind_markers=bind_markers,
        site_exemption=site_exemption,
    )


def _rt(
    stable_id: str,
    *,
    leg: str,
    rank: int,
    owner: int,
    predicate: str,
    on_fail: str,
    on_unknown: str,
    bind_markers: tuple[str, ...] = (),
    site_exemption: str = "",
    family: str = "none",
    monotone: str = "yes",
    exposure_effect: str = "<= ungated",
    tested_by: tuple[str, ...] = ("S13", "X6"),
) -> GateRecord:
    return GateRecord(
        stable_id=stable_id,
        ladder="runtime",
        owner_engine=owner,
        latency_class="hot",
        leg=leg,
        rank=rank,
        family=family,
        predicate=predicate,
        on_fail=on_fail,
        on_unknown=on_unknown,
        exposure_effect=exposure_effect,
        monotone=monotone,
        tested_by=tested_by,
        bind_markers=bind_markers,
        site_exemption=site_exemption,
    )


_STAGE_A_C = "Stage A/C not implemented; D.3: ladder guards alphas, not platform boot"
_NO_MARKER = "no gatescan marker; bind_markers empty by construction"

_ROWS: tuple[GateRecord, ...] = (
    _gov(
        "GOV.CONFIG_RESOLVE",
        rank=1,
        predicate="Config parses; fingerprint computable",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.SCHEMA_SUPPORT",
        rank=2,
        predicate="Declared-support set present; replayed log version in set",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.IDENTITY_RESOLVE",
        rank=3,
        predicate="IdentityMap resolved; identity_hash computed; as-of declared",
        on_fail="refuse",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.UNIVERSE_RESOLVE",
        rank=4,
        predicate="UniverseSnapshot ordered; universe_hash matches fingerprint",
        on_fail="refuse",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.MANIFEST_PARSE",
        rank=5,
        predicate="Schema-valid against alphas/SCHEMA.md",
        on_fail="refuse",
        site_exemption="AlphaLoader._validate_schema; " + _NO_MARKER,
    ),
    _gov(
        "GOV.MANIFEST_HASH",
        rank=6,
        predicate="Content hash computable",
        on_fail="refuse",
        site_exemption=_NO_MARKER,
    ),
    _gov(
        "GOV.LAYER_VALIDATE",
        rank=7,
        predicate="Layer checks pass (G1-G12, G14-G17)",
        on_fail="refuse",
        disableable="research-only",
        bind_markers=("LayerValidationError", "TrendMechanismError"),
    ),
    _gov(
        "GOV.DEPENDENCY_RESOLVE",
        rank=8,
        predicate="Dependency graph acyclic and resolvable",
        on_fail="refuse",
        site_exemption="G6 raises LayerValidationError; marker binds to GOV.LAYER_VALIDATE",
    ),
    _gov(
        "GOV.UNIVERSE_DISCLOSURE",
        rank=9,
        predicate="Declared universe is a subset of the platform universe",
        on_fail="refuse",
        site_exemption="G10 raises LayerValidationError; marker binds to GOV.LAYER_VALIDATE",
    ),
    _gov(
        "GOV.CONTRACT_SHAPE",
        rank=10,
        predicate="Declared emission shape conforms: direction, edge unit, half-life, anchor",
        on_fail="refuse",
        site_exemption="G2/G16 raise LayerValidationError; marker binds to GOV.LAYER_VALIDATE",
    ),
    _gov(
        "GOV.EVIDENCE_FRESHNESS",
        rank=11,
        predicate="Evidence within declared bound",
        on_fail="quarantine",
        on_unknown="quarantine",
        site_exemption=_NO_MARKER,
    ),
    _gov(
        "GOV.BUDGET_RESOLVE",
        rank=12,
        predicate="Budget resolvable",
        on_fail="zero budget",
        on_unknown="zero",
        site_exemption=_NO_MARKER,
    ),
    _gov(
        "GOV.LIFECYCLE_STATE",
        rank=13,
        predicate="Resulting state in {LIVE, QUARANTINED, REFUSED}",
        on_fail="quarantine",
        bind_markers=("AlphaLifecycleState.QUARANTINED", "quarantine("),
    ),
    _gov(
        "GOV.REGISTRY_FREEZE",
        rank=14,
        predicate="Registry complete; post-composition mutation raises",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.WIRING_CLOSURE",
        rank=15,
        predicate="Every manifest entry has a subscriber or absent_by_config; cascade acyclic",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.HANDLE_GRAPH",
        rank=16,
        predicate="The five permitted handle edges; no handle originates at 7 or 11",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.ABSENCE_RULE",
        rank=17,
        predicate="Engines 1, 7, 8, 11 present; 9 and 10 present or flat-and-declared",
        on_fail="refuse to arm",
        bind_markers=(
            "MacroState.DEGRADED",
            "MacroState.RISK_LOCKDOWN",
            "MacroState.HALTED",
            "MacroState.SHUTDOWN",
        ),
    ),
    _gov(
        "GOV.READINESS",
        rank=18,
        predicate="All twelve READY or ABSENT_BY_CONFIG",
        on_fail="refuse to arm",
        site_exemption=_STAGE_A_C,
    ),
    _gov(
        "GOV.FINGERPRINT_SEAL",
        rank=19,
        predicate="One hash over config, registry, universe, identity, wiring, support, parity",
        on_fail="halt-boot",
        site_exemption=_STAGE_A_C,
    ),
    _rt(
        "RT.KILL_SWITCH",
        leg="E",
        rank=1,
        owner=11,
        predicate="Switch inactive",
        on_fail="halt",
        on_unknown="treat as active",
        monotone="declared-exception",
        exposure_effect="declared-exception: stop acting, do not flatten",
        bind_markers=(
            "KillSwitchActivation",
            "kill_switch.activate",
            "is_active",
        ),
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.FRAME_PARSE",
        leg="Q",
        rank=1,
        owner=1,
        predicate="Frame parseable",
        on_fail="reject + emit",
        on_unknown="reject",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.SEQUENCE_REUSE",
        leg="Q",
        rank=2,
        owner=1,
        predicate="Not a duplicate (sequence_number, fingerprint)",
        on_fail="drop + count",
        on_unknown="CORRUPTED",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.STREAM_ORDER",
        leg="Q",
        rank=3,
        owner=1,
        predicate="Merge key strictly increasing",
        on_fail="count + emit",
        on_unknown="count + emit",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.QUALITY_CLASSIFY",
        leg="Q",
        rank=4,
        owner=1,
        predicate="Crossed / locked / zero-side / size / staleness classified",
        on_fail="degrade + emit",
        on_unknown="degrade",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.MARK_VALIDITY",
        leg="Q",
        rank=5,
        owner=7,
        predicate="Quote may move a mark",
        on_fail="retain last valid, flag stale, emit",
        on_unknown="retain + flag",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.FEATURE_WARMTH",
        leg="B",
        rank=1,
        owner=4,
        predicate="Input warm=True, or the declared reduced-confidence rule",
        on_fail="suppress + emit",
        on_unknown="suppress",
        bind_markers=("warm=False", "not warm", "is_warm"),
    ),
    _rt(
        "RT.FEATURE_VALIDITY",
        leg="B",
        rank=2,
        owner=4,
        predicate="Input valid and within staleness bound",
        on_fail="suppress + emit",
        on_unknown="suppress",
        bind_markers=("stale=True",),
    ),
    _rt(
        "RT.REGIME_PREDICATE",
        leg="B",
        rank=3,
        owner=4,
        predicate="The alpha's declared predicate over engine 3's label",
        on_fail="suppress + emit",
        on_unknown="declared no-regime branch",
        bind_markers=("regime_gate_state", "SafetyStateChange", "SafetyReason"),
    ),
    _rt(
        "RT.FORECAST_EXPIRY",
        leg="B",
        rank=4,
        owner=6,
        predicate="Within half-life from the forecast's own anchor",
        on_fail="exclude + record",
        on_unknown="exclude",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.BARRIER_COMPLETENESS",
        leg="B",
        rank=5,
        owner=6,
        predicate="Completeness >= threshold against UniverseSnapshot members",
        on_fail="skip boundary + emit",
        on_unknown="skip",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.NEUTRALITY_CERTIFIABLE",
        leg="B",
        rank=6,
        owner=6,
        predicate="Risk-model outputs present and versioned",
        on_fail="reduced gross, constraint marked unverified, or none",
        on_unknown="as fail",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.BOOK_VERIFIED",
        leg="D",
        rank=1,
        owner=8,
        predicate="Book reconciled; divergence not DIVERGED/UNDETERMINED",
        on_fail="no new exposure; reductions permitted",
        on_unknown="treated as breach",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.LATENCY_BUDGET",
        leg="D",
        rank=2,
        owner=8,
        predicate="LatencyBudgetState in {WITHIN, MARGINAL}",
        on_fail="stop opening; keep closing",
        on_unknown="treated as breach",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.DATA_HEALTH",
        leg="D",
        rank=3,
        owner=8,
        predicate="Per-instrument health healthy for opening only",
        on_fail="no new exposure in that instrument",
        on_unknown="treated as degraded",
        bind_markers=(
            "DataHealth.HALTED",
            "DataHealth.DEGRADED",
            "DataHealth.STALE",
            "DataHealth.GAP",
            "DataHealth.HEALTHY",
            "DataHealth.CORRUPT",
        ),
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.MARK_FRESHNESS",
        leg="D",
        rank=4,
        owner=8,
        predicate="Mark fresh and valid",
        on_fail="fail closed; reductions permitted",
        on_unknown="fail closed",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.BUDGET_RESOLVE",
        leg="D",
        rank=5,
        owner=8,
        predicate="strategy_id resolves to a budget",
        on_fail="zero budget, alert",
        on_unknown="zero",
        site_exemption="X4/X6 unregistered_id; KeyError is not a gatescan marker",
        tested_by=("S13", "X6", "X4"),
    ),
    _rt(
        "RT.EXPOSURE_LIMITS",
        leg="D",
        rank=6,
        owner=8,
        predicate="Per-symbol, per-strategy, gross, net, sector, factor",
        on_fail="scale factor < 1",
        on_unknown="zero",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.BUYING_POWER",
        leg="D",
        rank=7,
        owner=8,
        predicate="Sufficient buying power",
        on_fail="scale down",
        on_unknown="zero, not the previous value",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.DRAWDOWN_TIER",
        leg="D",
        rank=8,
        owner=8,
        predicate="Tier permits; hysteresis declared",
        on_fail="scale down / flat-only",
        on_unknown="more restrictive tier",
        bind_markers=("RiskLevel.",),
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.VERDICT_COMPOSE",
        leg="D",
        rank=9,
        owner=8,
        predicate="Composed factor <= min of inputs; zero yields no order",
        on_fail="no order",
        on_unknown="zero",
        bind_markers=(
            "RiskAction.REJECT",
            "RiskAction.SCALE_DOWN",
            "RiskAction.FORCE_FLATTEN",
            "RiskAction.ALLOW",
        ),
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.SESSION_ADMISSION",
        leg="P",
        rank=1,
        owner=9,
        predicate="Halt, SSR, locate, blackout permit construction now",
        on_fail="decline + emit",
        on_unknown="decline",
        bind_markers=(
            "BLOCK_HALT_BLACKOUT",
            "BLOCK_SESSION_FLATTEN_WINDOW",
            "BLOCK_SSR",
            "BLOCK_LOCATE_UNAVAILABLE",
        ),
    ),
    _rt(
        "RT.COST_GATE",
        leg="P",
        rank=2,
        owner=9,
        predicate="Edge clears round-trip cost at the declared model version",
        on_fail="decline opening; reductions proceed cost-unpriced-and-marked",
        on_unknown="decline",
        bind_markers=("BLOCK_EDGE_BELOW_COST", "BLOCK_EDGE_UNPRICEABLE"),
        tested_by=("S13", "X6", "S6"),
    ),
    _rt(
        "RT.LIMIT_PRICE_VALIDITY",
        leg="P",
        rank=3,
        owner=9,
        predicate="Book not crossed / zero-side at price derivation",
        on_fail="decline, or plan a style needing no limit",
        on_unknown="decline",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.MIN_SIZE",
        leg="P",
        rank=4,
        owner=9,
        predicate="Quantity >= minimum",
        on_fail="decline and emit",
        on_unknown="decline",
        bind_markers=("BLOCK_BELOW_MIN_ORDER_SHARES",),
    ),
    _rt(
        "RT.DUPLICATE_INTENT",
        leg="P",
        rank=5,
        owner=9,
        predicate="No outstanding order for the same target",
        on_fail="suppress + emit",
        on_unknown="suppress",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.NO_INCREASE",
        leg="P",
        rank=6,
        owner=9,
        predicate="Sum of |planned| <= approved, per symbol per tick, including exits",
        on_fail="no orders from that plan",
        on_unknown="no orders",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "X3"),
    ),
    _rt(
        "RT.JOURNAL_ABSENCE",
        leg="S",
        rank=1,
        owner=10,
        predicate="Order id provably absent from the durable journal",
        on_fail="refuse to submit",
        on_unknown="refuse",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "H1"),
    ),
    _rt(
        "RT.ORDER_EXPIRY",
        leg="S",
        rank=2,
        owner=10,
        predicate="Now <= the order's declared event-time expiry",
        on_fail="reject with reason, never work it",
        on_unknown="reject",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.SESSION_SUBMIT",
        leg="S",
        rank=3,
        owner=10,
        predicate="Venue open, tick size valid, auction eligibility",
        on_fail="do not submit + emit",
        on_unknown="do not submit",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.BROKER_STATE",
        leg="S",
        rank=4,
        owner=10,
        predicate="Connected and state known",
        on_fail="no new submissions; reconcile on reconnect",
        on_unknown="no submissions",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.STATE_TRANSITION_TOTAL",
        leg="S",
        rank=5,
        owner=10,
        predicate="(state, event) pair defined",
        on_fail="raise",
        on_unknown="raise",
        site_exemption=_NO_MARKER,
    ),
    _rt(
        "RT.FILL_ELIGIBILITY",
        leg="F",
        rank=1,
        owner=10,
        predicate="Resting order was live and latency-eligible at or before the market event, in exchange time",
        on_fail="no fill inferred",
        on_unknown="no fill",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "H1"),
    ),
    _rt(
        "RT.CROSSED_NO_FILL",
        leg="F",
        rank=2,
        owner=10,
        predicate="Book not crossed at the fill instant",
        on_fail="no fill inferred",
        on_unknown="no fill",
        site_exemption=_NO_MARKER,
        tested_by=("S13", "X6", "H1"),
    ),
)


def _index(rows: tuple[GateRecord, ...]) -> dict[str, GateRecord]:
    gov = [row for row in rows if row.ladder == "governance"]
    rt = [row for row in rows if row.ladder == "runtime"]
    gov_sorted = sorted(gov, key=lambda row: row.rank)
    rt_sorted = sorted(rt, key=lambda row: (_LEG_ORDER.index(row.leg), row.rank))
    out: dict[str, GateRecord] = {}
    for i, row in enumerate(gov_sorted, 1):
        out[row.stable_id] = replace(row, ordinal=i)
    for i, row in enumerate(rt_sorted, 1):
        out[row.stable_id] = replace(row, ordinal=i)
    return out


GATE_REGISTRY: dict[str, GateRecord] = _index(_ROWS)

GOV_IDS: frozenset[str] = frozenset(
    row.stable_id for row in _ROWS if row.ladder == "governance"
)
RT_IDS: frozenset[str] = frozenset(
    row.stable_id for row in _ROWS if row.ladder == "runtime"
)

FAMILY_TEMPLATES: dict[str, str] = {
    "RT.SCHEMA_SUPPORTED": "schema_version present and supported (per receiving boundary)",
    "RT.CONTRACT_CONFORM": "units, staleness metadata, source_layer, enums (per receiving boundary)",
    "RT.IN_UNIVERSE": "in_universe(instrument_id), total (per receiving boundary)",
}

GATE_ALIASES: dict[str, _Alias] = {
    "G1": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G2": _Alias(stable_id="GOV.CONTRACT_SHAPE", kind="current"),
    "G3": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G4": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G5": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G6": _Alias(stable_id="GOV.DEPENDENCY_RESOLVE", kind="current"),
    "G7": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G8": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G9": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G10": _Alias(stable_id="GOV.UNIVERSE_DISCLOSURE", kind="current"),
    "G11": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G12": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G13": _Alias(
        stable_id=None,
        kind="retired",
        reason="never implemented; warm-up is platform-owned as RT.FEATURE_WARMTH",
    ),
    "G14": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G15": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
    "G16": _Alias(stable_id="GOV.CONTRACT_SHAPE", kind="current"),
    "G17": _Alias(stable_id="GOV.LAYER_VALIDATE", kind="current"),
}

_NOTIFICATION: deque[VerdictRecord] = deque(maxlen=4096)


def clear_verdicts() -> None:
    _NOTIFICATION.clear()


def iter_verdicts() -> tuple[VerdictRecord, ...]:
    return tuple(_NOTIFICATION)


def record_verdict(
    gate_id: str,
    outcome: str,
    reason: str = "",
    *,
    alias: str = "",
) -> Literal[False]:
    """Append a notification-channel record. Draws no sequence; not an Event.

    Returns False so call sites can fold the emit into an existing
    ``return`` / ``if`` without adding a line or a sequence draw.
    """
    if gate_id not in GATE_REGISTRY:
        raise KeyError(gate_id)
    if outcome not in _OUTCOMES:
        raise ValueError(outcome)
    _NOTIFICATION.append(
        VerdictRecord(
            gate_id=gate_id,
            outcome=outcome,
            reason=reason,
            alias=alias,
        )
    )
    return False


def _check_registry_completeness() -> None:
    expected = GOV_IDS | RT_IDS
    missing = sorted(expected - set(GATE_REGISTRY))
    extra = sorted(set(GATE_REGISTRY) - expected)
    if missing or extra:
        raise RuntimeError(
            f"GATE_REGISTRY diverges from the declared identity set: "
            f"missing {missing}, extra {extra}"
        )
    if len(GOV_IDS) != 19:
        raise RuntimeError(f"governance rows {len(GOV_IDS)}, expected 19")
    if len(RT_IDS) != 34:
        raise RuntimeError(f"runtime rows {len(RT_IDS)}, expected 34")
    if len(GATE_REGISTRY) != 53:
        raise RuntimeError(f"GATE_REGISTRY has {len(GATE_REGISTRY)} rows, expected 53")
    leaked = sorted(gid for gid in FAMILY_TEMPLATES if gid in GATE_REGISTRY)
    if leaked:
        raise RuntimeError(f"family templates recorded as rows: {leaked}")
    seen_markers: dict[str, str] = {}
    for row in GATE_REGISTRY.values():
        unknown_tests = [t for t in row.tested_by if t not in _KNOWN_TESTS]
        if unknown_tests:
            raise RuntimeError(
                f"{row.stable_id} tested_by does not resolve: {unknown_tests}"
            )
        if not row.bind_markers and not row.site_exemption:
            raise RuntimeError(
                f"{row.stable_id} has neither bind_markers nor site_exemption"
            )
        if row.bind_markers and row.site_exemption:
            raise RuntimeError(
                f"{row.stable_id} has both bind_markers and site_exemption"
            )
        for marker in row.bind_markers:
            prior = seen_markers.get(marker)
            if prior is not None:
                raise RuntimeError(
                    f"marker {marker!r} bound to both {prior} and {row.stable_id}"
                )
            seen_markers[marker] = row.stable_id
    exceptions = [
        row.stable_id
        for row in GATE_REGISTRY.values()
        if row.monotone != "yes"
    ]
    if exceptions != ["RT.KILL_SWITCH"]:
        raise RuntimeError(
            f"monotone exceptions must be exactly RT.KILL_SWITCH: {exceptions}"
        )
    if GATE_ALIASES["G13"].kind != "retired" or GATE_ALIASES["G13"].stable_id is not None:
        raise RuntimeError("G13 must be a retired alias with no stable_id")


_check_registry_completeness()
