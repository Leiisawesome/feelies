"""Phase 5: re-verify the load-bearing claims of Phases 0-4 against current source.

Two jobs:

1. Confirm every ``path:line:symbol`` citation carried into a Phase 1-4 target
   still resolves. A citation that has drifted is not evidence, and a gap row
   built on it is unverified.
2. Re-measure the counts that gap rows quantify, so each row's Current column is
   a number measured today rather than one copied forward.

Writes tools/arch/evidence/gapscan.json.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
OUT = Path(__file__).resolve().parent / "evidence" / "gapscan.json"

# ---------------------------------------------------------------- citations

# (engine, path, symbol, claimed_line) drawn from the GAP-vs-CURRENT paragraph of
# each Phase 2 engine sheet plus the Phase 1 sections they lean on.
CITATIONS: list[tuple[str, str, str, int]] = [
    ("E1", "kernel/orchestrator.py", "_update_halt_state", 5014),
    ("E1", "kernel/orchestrator.py", "_verify_data_integrity", 5379),
    ("E2", "kernel/orchestrator.py", "_restore_feature_snapshots", 5423),
    ("E2", "kernel/orchestrator.py", "_checkpoint_feature_snapshots", 5454),
    ("E3", "kernel/orchestrator.py", "_calibrate_regime_engine", 2335),
    ("E3", "kernel/orchestrator.py", "_update_regime", 2432),
    ("E3", "kernel/orchestrator.py", "_maybe_publish_hazard_spike", 2501),
    ("E3", "kernel/orchestrator.py", "_regime_label_for", 4556),
    ("E3", "kernel/orchestrator.py", "_checkpoint_regime_snapshot", 5460),
    ("E4", "composition/selection_policy.py", "select", 127),
    ("E7", "kernel/orchestrator.py", "_reconcile_fills", 4229),
    ("E7", "kernel/orchestrator.py", "_distribute_fill_to_strategies", 4577),
    ("E7", "kernel/orchestrator.py", "_record_fill_attribution", 4057),
    ("E8", "kernel/orchestrator.py", "_compute_target_quantity", 2718),
    ("E8", "kernel/orchestrator.py", "_escalate_risk", 2530),
    ("E8", "kernel/orchestrator.py", "_emergency_flatten_all", 2601),
    ("E8", "kernel/orchestrator.py", "_maybe_flip_buying_power_at_rth_close", 782),
    ("E9", "kernel/orchestrator.py", "_plan_for_signal", 2814),
    ("E9", "kernel/orchestrator.py", "_try_build_order_from_intent", 3278),
    ("E9", "kernel/orchestrator.py", "_resolve_order_route", 3371),
    ("E9", "kernel/orchestrator.py", "_filter_portfolio_orders_for_admission", 3505),
    ("E9", "kernel/orchestrator.py", "_execute_reverse", 2984),
    ("E10", "kernel/orchestrator.py", "_submit_tracked_order", 3831),
    ("E10", "kernel/orchestrator.py", "_poll_order_router_acks", 3793),
    ("E10", "kernel/orchestrator.py", "_apply_ack_to_order", 4103),
    ("E10", "kernel/orchestrator.py", "_transition_order", 4086),
    ("E10", "kernel/orchestrator.py", "_drain_async_fills", 3936),
    ("E10", "kernel/orchestrator.py", "cancel_order", 3438),
]

# Line-only citations: assert the line still contains the claimed token.
LINE_TOKENS: list[tuple[str, str, int, str]] = [
    ("E3", "bootstrap.py", 289, "regime"),
    ("E4", "signals/horizon_engine.py", 196, "regime"),
    ("E6", "composition/cross_sectional.py", 75, "sort"),
    ("E5/E12", "forensics/cost_circuit_breaker.py", 159, "QUARANTINE"),
    ("E11", "core/events.py", 416, "published on the bus"),
]


def _funcs(path: Path) -> dict[str, list[int]]:
    """Map function name -> every def line in the file (methods included)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, list[int]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out[node.name].append(node.lineno)
    return out


def check_citations() -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []
    cache: dict[str, dict[str, list[int]]] = {}
    for engine, rel, symbol, claimed in CITATIONS:
        path = SRC / rel
        if rel not in cache:
            cache[rel] = _funcs(path)
        lines = cache[rel].get(symbol, [])
        # a def line is often preceded by a decorator; allow +/- 3
        at_def = any(abs(actual - claimed) <= 3 for actual in lines)
        # Phase 0's tick-path hops cite the CALL site, not the def.
        text = (SRC / rel).read_text(encoding="utf-8").splitlines()
        claimed_text = text[claimed - 1] if 0 < claimed <= len(text) else ""
        at_call = symbol in claimed_text
        resolved.append(
            {
                "engine": engine,
                "path": f"src/feelies/{rel}",
                "symbol": symbol,
                "claimed_line": claimed,
                "actual_def_lines": lines,
                "claimed_line_text": claimed_text.strip()[:120],
                "kind": "def" if at_def else ("call" if at_call else "unresolved"),
                "resolves": at_def or at_call,
            }
        )
    tokens: list[dict[str, Any]] = []
    for engine, rel, line, token in LINE_TOKENS:
        text = (SRC / rel).read_text(encoding="utf-8").splitlines()
        window = "\n".join(text[max(0, line - 4) : line + 4])
        tokens.append(
            {
                "engine": engine,
                "path": f"src/feelies/{rel}",
                "claimed_line": line,
                "token": token,
                "resolves": token.lower() in window.lower(),
            }
        )
    return {"symbol_citations": resolved, "line_citations": tokens}


# ------------------------------------------------------- orchestrator shape


def orchestrator_shape() -> dict[str, Any]:
    """Size and store-access profile of the god orchestrator (CORE §J.1)."""
    path = SRC / "kernel" / "orchestrator.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    methods: list[str] = []
    cls_name = ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and "rchestrator" in node.name:
            cls_name = node.name
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    methods.append(item.name)
    # Distinguish a method call THROUGH a collaborator from a bare read of it:
    # only the former is the orchestrator exercising another engine's authority.
    stores: dict[str, dict[str, int]] = {}
    for attr in (
        "_positions",
        "_strategy_positions",
        "_risk_engine",
        "_regime_engine",
        "_router",
        "_backend",
        "_aggregator",
        "_sensor_registry",
        "_position_store",
    ):
        total = len(re.findall(rf"self\.{attr}\b", text))
        called = len(re.findall(rf"self\.{attr}\.\w+\s*\(", text))
        if total:
            stores[attr] = {"references": total, "method_calls_through": called}
    return {
        "class_name": cls_name,
        "file_lines": len(text.splitlines()),
        "orchestrator_methods": len(methods),
        "private_methods": sum(1 for m in methods if m.startswith("_")),
        "public_methods": sum(1 for m in methods if not m.startswith("_")),
        "store_access": stores,
    }


# ------------------------------------------------------------ mode branches


def mode_branches() -> dict[str, Any]:
    """OperatingMode / is_live style branches, by package (Inv-4 seam)."""
    pat = re.compile(
        r"OperatingMode\.|\bis_live\b|\bmode\s*==\s*[\"']|\.mode\s+is\s+OperatingMode"
    )
    by_pkg: Counter[str] = Counter()
    sites: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        pkg = rel.parts[0] if len(rel.parts) > 1 else "<root>"
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and not line.lstrip().startswith("#"):
                by_pkg[pkg] += 1
                sites.append(f"src/feelies/{rel.as_posix()}:{i}")
    outside = {k: v for k, v in by_pkg.items() if k not in {"execution", "broker"}}
    return {
        "total": sum(by_pkg.values()),
        "by_package": dict(by_pkg.most_common()),
        "outside_execution_and_broker": sum(outside.values()),
        "outside_by_package": dict(sorted(outside.items(), key=lambda kv: -kv[1])),
        "sites": sites,
    }


# ------------------------------------------------------------- alpha leaks


def _declared_alpha_ids() -> list[str]:
    """Every ``alpha_id`` declared in alphas/**/*.alpha.yaml -- the field, not the
    filename stem (a template file is named ``template_signal`` but declares
    ``my_signal_alpha``)."""
    ids: set[str] = set()
    for f in sorted((ROOT / "alphas").rglob("*.alpha.yaml")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^alpha_id:\s*([A-Za-z][\w]*)", line)
            if m:
                ids.add(m.group(1))
                break
    return sorted(ids)


def alpha_literal_leaks() -> dict[str, Any]:
    """Alpha ids appearing as literals in core code (Inv-6 alpha-agnosticism)."""
    ids = _declared_alpha_ids()
    hits: list[dict[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for aid in ids:
                if re.search(rf"[\"']{re.escape(aid)}[\"']", line):
                    hits.append(
                        {
                            "path": f"src/feelies/{rel}",
                            "line": str(i),
                            "alpha_id": aid,
                            "text": line.strip()[:160],
                        }
                    )
    return {"known_alpha_ids": ids, "leak_sites": hits, "leak_count": len(hits)}


# --------------------------------------------------------------- G13 / gates


def gate_registry() -> dict[str, Any]:
    """Which G-numbers the layer validator actually implements."""
    path = SRC / "alpha" / "layer_validator.py"
    text = path.read_text(encoding="utf-8")
    declared = sorted(set(re.findall(r"\bG(\d{1,2})\b", text)), key=int)
    # GateId enum members, if present
    enum_members = re.findall(r"^\s*(G\d{1,2})\s*=\s*", text, re.M)
    noop: list[str] = []
    for g in declared:
        # a gate is a no-op if its check body is only pass/return
        m = re.search(rf"def _?check_?g{g}\b.*?(?=\n    def |\nclass |\Z)", text, re.S | re.I)
        if m and re.fullmatch(
            r"[^\n]*\n(\s*(\"\"\".*?\"\"\"|#.*|pass|return|return None)\s*\n)+", m.group(0), re.S
        ):
            noop.append(f"G{g}")
    return {
        "g_numbers_referenced": [f"G{g}" for g in declared],
        "enum_members": enum_members,
        "apparent_noop": noop,
        "validator_lines": len(text.splitlines()),
    }


# ------------------------------------------------------------ event schema


def event_versioning() -> dict[str, Any]:
    """Which events carry a schema version and which are hot-path (Inv-10).

    Only classes in the ``Event`` inheritance tree count as events; enums and
    plain value objects (``SensorProvenance``, ``TargetPosition``) are excluded.
    A *schema* version is a ``schema_version`` field on the contract itself --
    producer/estimator fields like ``sensor_version`` / ``feature_versions`` are
    not schema versions (Phase 0's schema-vs-producer distinction).
    """
    path = SRC / "core" / "events.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    event_classes: set[str] = {"Event"}
    events: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {ast.unparse(b) for b in node.bases}
        if node.name != "Event" and not (bases & event_classes):
            continue
        event_classes.add(node.name)
        fields = [
            item.target.id
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        ]
        events[node.name] = {
            "bases": sorted(bases),
            "line": node.lineno,
            "n_fields": len(fields),
            "has_version_field": "schema_version" in fields,
        }
    return {
        "n_event_classes": len(events),
        "with_version_field": sorted(k for k, v in events.items() if v["has_version_field"]),
        "without_version_field": sorted(
            k for k, v in events.items() if not v["has_version_field"]
        ),
        "events": events,
    }


def main() -> None:
    data = {
        "citations": check_citations(),
        "orchestrator": orchestrator_shape(),
        "mode_branches": mode_branches(),
        "alpha_leaks": alpha_literal_leaks(),
        "gates": gate_registry(),
        "events": event_versioning(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2, sort_keys=True),
                   encoding="utf-8", newline="\n")

    c = data["citations"]
    bad = [x for x in c["symbol_citations"] if not x["resolves"]]
    badt = [x for x in c["line_citations"] if not x["resolves"]]
    print(f"gapscan -> {OUT.relative_to(ROOT).as_posix()}")
    print(
        f"  symbol citations: {len(c['symbol_citations'])} checked, "
        f"{len(c['symbol_citations']) - len(bad)} resolve, {len(bad)} DRIFTED"
    )
    for x in bad:
        print(
            f"      {x['engine']} {x['symbol']} claimed {x['claimed_line']} "
            f"actual defs {x['actual_def_lines']}"
        )
    kinds = Counter(x["kind"] for x in c["symbol_citations"])
    print(f"      citation kinds: {dict(kinds)}")
    print(f"  line citations:   {len(c['line_citations'])} checked, {len(badt)} DRIFTED")
    for x in badt:
        print(f"      {x['engine']} {x['path']}:{x['claimed_line']} token {x['token']!r}")
    o = data["orchestrator"]
    print(
        f"  orchestrator: class {o['class_name']}, {o['file_lines']} lines, "
        f"{o['orchestrator_methods']} methods ({o['public_methods']} public)"
    )
    for attr, counts in o["store_access"].items():
        print(
            f"      self.{attr}: {counts['references']} refs, "
            f"{counts['method_calls_through']} calls through"
        )
    m = data["mode_branches"]
    print(
        f"  mode branches: {m['total']} total, "
        f"{m['outside_execution_and_broker']} outside execution/+broker/ "
        f"{m['outside_by_package']}"
    )
    a = data["alpha_leaks"]
    print(f"  alpha-id literals in src: {a['leak_count']} {[h['path'] for h in a['leak_sites']]}")
    g = data["gates"]
    print(
        f"  gate registry: {len(g['g_numbers_referenced'])} G-numbers, noop={g['apparent_noop']}"
    )
    e = data["events"]
    print(
        f"  events: {e['n_event_classes']} classes, "
        f"{len(e['with_version_field'])} with a version field"
    )


if __name__ == "__main__":
    main()
