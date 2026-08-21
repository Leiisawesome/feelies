"""S13 — every gate is enumerable from one registry; call sites bind to rows.

G17/G38: two ladders, no common registry. G1-G17 are string-keyed method
calls in LayerValidator (G13 has zero references in src/feelies). Runtime
gating is 329 call sites across 10 families.

S13 asserts closure the way GATE_EVIDENCE_REQUIREMENTS does at
src/feelies/promotion/evidence.py:1720-1731: an expected identity set
versus the row map, failing at import if they diverge. A test that only
checks row count or field presence passes over a registry whose rows are
wrong. Removing one row must name the unbound call sites.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from feelies.core.gate_registry import (
    FAMILY_TEMPLATES,
    GATE_ALIASES,
    GATE_REGISTRY,
    GOV_IDS,
    RT_IDS,
)
from tools.arch.gatescan import GATE_FAMILIES, SRC, py_files, rel

_REPO = Path(__file__).resolve().parents[2]
_CONFIGS = _REPO / "configs"
_REQUIRED_FIELDS = (
    "stable_id",
    "ladder",
    "owner_engine",
    "latency_class",
    "on_fail",
    "exposure_effect",
    "monotone",
    "disableable",
    "predicate",
    "tested_by",
    "ordinal",
)


def _scan_sites() -> list[dict[str, str]]:
    """Replay gatescan's marker walk; do not write evidence/gatescan.json."""
    sites: list[dict[str, str]] = []
    for family, markers in GATE_FAMILIES.items():
        for path in py_files(SRC):
            text = path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for marker in markers:
                    if marker in line:
                        sites.append(
                            {
                                "family": family,
                                "marker": marker,
                                "path": rel(path),
                                "line": str(i),
                            }
                        )
    return sites


def _marker_to_gate() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in GATE_REGISTRY.values():
        for marker in row.bind_markers:
            mapping[marker] = row.stable_id
    return mapping


def test_s13_expected_ids_match_registry_rows() -> None:
    """Import-time identity set versus the row map — the evidence.py pattern."""
    expected = GOV_IDS | RT_IDS
    missing = sorted(expected - set(GATE_REGISTRY))
    extra = sorted(set(GATE_REGISTRY) - expected)
    assert not missing and not extra, (
        f"GATE_REGISTRY diverges from the declared identity set: "
        f"missing {missing}, extra {extra}"
    )
    gov = {gid for gid, row in GATE_REGISTRY.items() if row.ladder == "governance"}
    rt = {gid for gid, row in GATE_REGISTRY.items() if row.ladder == "runtime"}
    assert gov == GOV_IDS
    assert rt == RT_IDS
    assert len(GATE_REGISTRY) == 53
    assert len(gov) == 19
    assert len(rt) == 34
    assert len(gov) + len(rt) == 53


def test_s13_family_templates_are_templates_not_rows() -> None:
    """D.4: SCHEMA_SUPPORTED / CONTRACT_CONFORM / IN_UNIVERSE are not extra rows."""
    expected = frozenset(
        {
            "RT.SCHEMA_SUPPORTED",
            "RT.CONTRACT_CONFORM",
            "RT.IN_UNIVERSE",
        }
    )
    assert frozenset(FAMILY_TEMPLATES) == expected
    leaked = sorted(gid for gid in FAMILY_TEMPLATES if gid in GATE_REGISTRY)
    assert leaked == [], (
        "family templates recorded as registry rows "
        f"(56 instead of 53): {leaked}"
    )


def test_s13_generated_family_instances_match_wiring_manifest() -> None:
    """D.4: instance count comes from the wiring manifest, not a hand count.

    Generated instances are additional to the 53 hand-written rows and live
    in FAMILY_INSTANCES (family = template id). GATE_REGISTRY stays the
    53 rows (family = "none"). Template ids remain absent as rows.
    """
    from feelies.core import gate_registry as gr
    from feelies.core.wiring_manifest import SUBSCRIPTIONS

    expected = {
        f"{template}:{sub.event_type}:{sub.subscriber}"
        for template in FAMILY_TEMPLATES
        for sub in SUBSCRIPTIONS
    }
    generated = getattr(gr, "FAMILY_INSTANCES", {})
    actual = set(generated)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    assert not missing and not extra, (
        "generated family instances diverge from the wiring manifest: "
        f"missing {missing}, extra {extra}"
    )
    leaked = sorted(gid for gid in FAMILY_TEMPLATES if gid in GATE_REGISTRY)
    assert leaked == [], (
        "family templates recorded as hand-written rows: " + ", ".join(leaked)
    )
    overlap = sorted(actual & set(GATE_REGISTRY))
    assert overlap == [], (
        "generated instances collided with hand-written rows: "
        + ", ".join(overlap)
    )
    from tests.conformance.test_wiring_manifest import _measure_phase4

    runtime = _measure_phase4()
    needed = {
        f"{template}:{event_type}:{subscriber}"
        for template in FAMILY_TEMPLATES
        for event_type, subscriber in runtime
    }
    missing_runtime = sorted(needed - actual)
    assert not missing_runtime, (
        "generated family instances missing for receiving boundaries: "
        + ", ".join(missing_runtime)
    )
    handwritten = {
        gid for gid, row in GATE_REGISTRY.items() if row.family == "none"
    }
    assert handwritten == set(GATE_REGISTRY)
    assert len(handwritten) == 53
    for inst in generated.values():
        assert inst.family in FAMILY_TEMPLATES
        assert inst.stable_id not in GATE_REGISTRY
        assert inst.stable_id not in FAMILY_TEMPLATES


def test_s13_every_row_has_required_fields_and_a_bound_test() -> None:
    missing: list[str] = []
    for gate_id, row in GATE_REGISTRY.items():
        for field in _REQUIRED_FIELDS:
            if getattr(row, field) in (None, "", (), []):
                missing.append(f"{gate_id}.{field}")
        if "S13" not in row.tested_by:
            missing.append(f"{gate_id}.tested_by")
    assert not missing, f"registry rows missing required fields: {missing}"


def test_s13_no_ordinal_gap_or_duplicate() -> None:
    by_ladder: dict[str, list[int]] = defaultdict(list)
    for row in GATE_REGISTRY.values():
        by_ladder[row.ladder].append(row.ordinal)
    for ladder, ordinals in by_ladder.items():
        assert len(ordinals) == len(set(ordinals)), f"duplicate ordinals on {ladder}"
        expected = list(range(1, len(ordinals) + 1))
        assert sorted(ordinals) == expected, (
            f"{ladder} ordinals are not dense 1..{len(ordinals)}: {sorted(ordinals)}"
        )


def test_s13_call_sites_bind_to_registry() -> None:
    """Every gatescan marker site resolves to a row; name the unbound ones."""
    mapping = _marker_to_gate()
    unbound: list[str] = []
    bound_ids: set[str] = set()
    for site in _scan_sites():
        gate_id = mapping.get(site["marker"])
        if gate_id is None or gate_id not in GATE_REGISTRY:
            unbound.append(
                f"{site['path']}:{site['line']} marker={site['marker']!r} "
                f"family={site['family']}"
            )
        else:
            bound_ids.add(gate_id)
    assert not unbound, (
        "unbound gate call sites (no registry row for marker): " + "; ".join(unbound)
    )
    unlocated = sorted(
        gate_id
        for gate_id, row in GATE_REGISTRY.items()
        if not row.bind_markers and not row.site_exemption
    )
    assert not unlocated, (
        "registry rows with neither bind_markers nor site_exemption: "
        + ", ".join(unlocated)
    )
    assert bound_ids, "scan found no sites — the binding assertion is vacuous"


def test_s13_g13_is_a_retired_alias_and_binds_to_nothing() -> None:
    alias = GATE_ALIASES["G13"]
    assert alias.kind == "retired"
    assert alias.stable_id is None
    assert "G13" not in GATE_REGISTRY
    mapping = _marker_to_gate()
    assert "G13" not in mapping.values()
    sites = [
        f"{s['path']}:{s['line']}"
        for s in _scan_sites()
        if mapping.get(s["marker"]) == "G13"
    ]
    assert sites == []


def test_s13_kill_switch_is_the_sole_monotone_exception() -> None:
    exceptions = sorted(
        row.stable_id
        for row in GATE_REGISTRY.values()
        if row.monotone != "yes"
    )
    assert exceptions == ["RT.KILL_SWITCH"]
    assert GATE_REGISTRY["RT.KILL_SWITCH"].monotone == "declared-exception"


def test_s13_governance_is_cold_and_disableable_only_where_declared() -> None:
    hot_gov = [
        row.stable_id
        for row in GATE_REGISTRY.values()
        if row.ladder == "governance" and row.latency_class != "cold"
    ]
    assert hot_gov == []
    disableable = sorted(
        row.stable_id
        for row in GATE_REGISTRY.values()
        if row.disableable != "no"
    )
    assert disableable == ["GOV.LAYER_VALIDATE"]
    hits: list[str] = []
    for path in sorted(_CONFIGS.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        if "enforce_layer_gates" in text:
            rel_path = path.relative_to(_REPO).as_posix()
            hits.append(rel_path)
    assert hits == [], (
        "enforce_layer_gates appears in shipped configs "
        f"(I-24: disableable in principle, disabled in none): {hits}"
    )
