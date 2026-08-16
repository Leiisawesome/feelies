"""Re-verify Phase 5's do-not-change candidate list against current source.

Deliverable I *promotes* the candidates, so each must be re-measured rather than
carried forward. This checks the mechanically checkable ones and reports the rest
as needing a read. Emits tools/arch/evidence/p7_dnc.json.

Each check returns (holds, measured) so a candidate that has silently stopped
being true is reported rather than restated.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = Path(__file__).resolve().parent / "evidence"

TICK_CRITICAL = ("kernel", "bus", "sensors", "features", "signals", "composition", "risk")


def modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py"))


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def check_no_uuid() -> tuple[bool, dict[str, Any]]:
    hits = [rel(p) for p in modules() if re.search(r"^\s*(import uuid|from uuid)", p.read_text(encoding="utf-8"), re.M)]
    rng = [
        f"{rel(p)}:{i}"
        for p in modules()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\b(random\.|np\.random|numpy\.random|Random\()", line)
        and not line.lstrip().startswith("#")
    ]
    return (not hits, {"uuid_imports": hits, "rng_sites": rng})


def check_type_rank() -> tuple[bool, dict[str, Any]]:
    path = SRC / "storage" / "event_resequence.py"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"_TYPE_RANK: dict\[type, int\] = \{([^}]*)\}", text)
    ranked = sorted(re.findall(r"(\w+):\s*\d+", m.group(1))) if m else []
    sig = re.search(r"def event_merge_sort_key\(\s*event: ([^\n]*?),?\s*\n\) ->", text)
    key_fields = re.search(r"return \(\s*(.*?)\s*\)", text, re.S)
    # A second encoding of the same ordering rule.
    ing = SRC / "ingestion" / "massive_ingestor.py"
    ing_text = ing.read_text(encoding="utf-8")
    dup = sorted(re.findall(r"(_TYPE_RANK_\w+)\s*=\s*\d+", ing_text))
    ing_key = re.search(r"key=lambda d: \(\s*(.*?)\s*\)\s*\)", ing_text, re.S)
    return (
        len(ranked) == 2,
        {
            "ranked_types": ranked,
            "accepts": (sig.group(1) if sig else "?"),
            "canonical_key_fields": [
                f.strip().rstrip(",") for f in (key_fields.group(1).splitlines() if key_fields else [])
            ],
            "second_encoding_in": rel(ing),
            "second_encoding_constants": dup,
            "second_encoding_key": (
                [f.strip().rstrip(",") for f in ing_key.group(1).splitlines()] if ing_key else []
            ),
        },
    )


def check_frozen_events() -> tuple[bool, dict[str, Any]]:
    path = SRC / "core" / "events.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    frozen, not_frozen = [], []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        decos = [ast.unparse(d) for d in node.decorator_list]
        if not any("dataclass" in d for d in decos):
            continue
        (frozen if any("frozen=True" in d for d in decos) else not_frozen).append(node.name)
    return (not not_frozen, {"frozen": len(frozen), "not_frozen": not_frozen})


def check_subscribe_all() -> tuple[bool, dict[str, Any]]:
    """Zero *call* sites is the property; the definition itself does not count."""
    sites, calls = [], []
    for p in modules():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "subscribe_all" not in line:
                continue
            sites.append(f"{rel(p)}:{i}")
            if "def subscribe_all" not in line:
                calls.append(f"{rel(p)}:{i}: {line.strip()}")
    return (not calls, {"all_sites": sites, "call_sites": calls})


def check_mode_branches_in_seam() -> tuple[bool, dict[str, Any]]:
    pat = re.compile(r"OperatingMode\.|\bmode\s*==|\bmode\s*!=|is_backtest|is_live\b|is_paper\b")
    hits = [
        f"{rel(p)}:{i}"
        for p in modules()
        if p.parts[len(SRC.parts)] in ("execution", "broker")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.search(line) and not line.lstrip().startswith("#")
    ]
    return (not hits, {"mode_branch_sites_inside_execution_or_broker": hits})


def check_alpha_leaks() -> tuple[bool, dict[str, Any]]:
    # Alpha ids come from manifest filenames, not directory names: alphas/research/
    # is a lifecycle directory, and treating it as an id matches "research"
    # everywhere and reports 30+ spurious leaks.
    ids = sorted(p.name.removesuffix(".alpha.yaml") for p in (ROOT / "alphas").rglob("*.alpha.yaml"))
    hits = [
        f"{rel(p)}:{i}:{aid}"
        for p in modules()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        for aid in ids
        if aid in line
    ]
    return (len(hits) <= 3, {"alpha_ids_declared": len(ids), "leak_sites": hits})


def check_decimal_money() -> tuple[bool, dict[str, Any]]:
    """Locate the Decimal/float boundary rather than pass-fail the whole claim.

    Phase 5's candidate reads "money is Decimal end to end". Measured, the
    boundary is the fill: realised money is Decimal, intended/estimated money is
    float. The claim is sound on the realised side only, so this reports the
    partition and treats a float on the *realised* side as the failure.
    """
    path = SRC / "core" / "events.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    money = re.compile(r"(price|pnl|cost|notional|usd|premium|exposure|turnover)", re.I)
    realised, intended = [], []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for b in node.body:
            if not (isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)):
                continue
            name, ann = b.target.id, ast.unparse(b.annotation)
            if not money.search(name):
                continue
            entry = f"{node.name}.{name}: {ann}"
            (realised if "Decimal" in ann else intended).append(entry)
    return (bool(realised) and not any("price" in e or "pnl" in e for e in intended),
            {"decimal_fields": realised, "float_fields": intended})


def check_ci_guards() -> tuple[bool, dict[str, Any]]:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return (
        "PYTHONHASHSEED: random" in ci and "FEELIES_REQUIRE_BASELINE_CACHE" in ci,
        {
            "random_seed_job": "PYTHONHASHSEED: random" in ci,
            "require_baseline_cache": "FEELIES_REQUIRE_BASELINE_CACHE" in ci,
            "pinned_seed_present": 'PYTHONHASHSEED: "0"' in ci,
        },
    )


def check_gate_evidence_completeness() -> tuple[bool, dict[str, Any]]:
    """A completeness check counts only if it is *invoked* at module import.

    The assertion lives inside a function, so searching for a raise near the
    matrix name misses it. What makes it load-bearing is the bare call at module
    level, which is what this looks for.
    """
    path = SRC / "promotion" / "evidence.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    invoked = [
        f"{rel(path)}:{i}: {line.strip()}"
        for i, line in enumerate(lines, 1)
        if re.fullmatch(r"_check_\w+\(\)", line.strip())
    ]
    raising = [
        f"{rel(path)}:{i}"
        for i, line in enumerate(lines, 1)
        if re.match(r"def _check_\w+\(\) -> None:", line.strip())
    ]
    return (bool(invoked), {"module_level_invocations": invoked, "check_definitions": raising})


def check_sensor_input_closure() -> tuple[bool, dict[str, Any]]:
    text = (SRC / "core" / "platform_config.py").read_text(encoding="utf-8")
    closed = bool(re.search(r"\{\s*[\"']?NBBOQuote|NBBOQuote\b[^\n]*Trade", text))
    raises = "ConfigurationError" in text
    dyn = [
        f"{rel(p)}:{i}"
        for p in modules()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "import_module" in line and not line.lstrip().startswith("#")
    ]
    return (closed and raises, {"closed_map": closed, "raises": raises, "dynamic_import_sites": dyn})


def check_throttle_time_base() -> tuple[bool, dict[str, Any]]:
    text = (SRC / "sensors" / "registry.py").read_text(encoding="utf-8")
    m = [
        f"registry.py:{i}: {line.strip()}"
        for i, line in enumerate(text.splitlines(), 1)
        if "throttle_ns" in line and ("timestamp_ns" in line or "last" in line)
    ]
    wall = [
        f"registry.py:{i}"
        for i, line in enumerate(text.splitlines(), 1)
        if re.search(r"time\.(time|perf_counter|monotonic)|datetime\.now", line)
    ]
    return (bool(m) and not wall, {"throttle_comparison": m, "wall_clock_in_registry": wall})


def check_layer_gates_strict() -> tuple[bool, dict[str, Any]]:
    """Strict is the default *and* no config opts out. Both halves are required.

    The default protects a config that omits the key; it does nothing about one
    that sets it false, so the absence over configs/ is the other half.
    """
    declared = []
    for path in (SRC / "core" / "platform_config.py", SRC / "alpha" / "layer_validator.py", SRC / "alpha" / "loader.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"enforce_layer_gates(: bool)? ?= ?True|enforce_layer_gates\", True", line):
                declared.append(f"{rel(path)}:{i}: {line.strip()}")
    in_configs = [
        f"{rel(p)}:{i}"
        for p in sorted((ROOT / "configs").rglob("*.yaml"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "enforce_layer_gates" in line
    ]
    return (bool(declared) and not in_configs,
            {"strict_defaults": declared, "occurrences_in_configs": in_configs})


CHECKS = {
    "I-01 content-derived identity, no uuid": check_no_uuid,
    "I-02 deterministic total order on merge": check_type_rank,
    "I-03 all event classes frozen": check_frozen_events,
    "I-04 no global handler fan-in (subscribe_all)": check_subscribe_all,
    "I-05 money is Decimal": check_decimal_money,
    "I-08/09 CI determinism guards": check_ci_guards,
    "I-11 zero mode branches inside the seam": check_mode_branches_in_seam,
    "I-17 gate-evidence self-completeness": check_gate_evidence_completeness,
    "I-18 alpha-id leaks bounded": check_alpha_leaks,
    "I-21 sensor input closure + dynamic imports": check_sensor_input_closure,
    "I-22 throttle in event time": check_throttle_time_base,
    "I-24 layer gates ship strict": check_layer_gates_strict,
}


def main() -> None:
    out: dict[str, Any] = {}
    for name, fn in CHECKS.items():
        holds, measured = fn()
        out[name] = {"holds": holds, "measured": measured}
        status = "HOLDS" if holds else "**CHANGED**"
        print(f"{status:12} {name}")
        if not holds:
            print(f"             {json.dumps(measured)[:400]}")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "p7_dnc.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    n_hold = sum(1 for v in out.values() if v["holds"])
    print(f"\n{n_hold}/{len(out)} re-verified as still holding")


if __name__ == "__main__":
    main()
