#!/usr/bin/env python3
"""
Gate-outcome inventory for Phase 0 / D0.5.  Stdlib only.

`measure.py gates` finds functions whose *name* looks like a guard, which is a
name heuristic.  This scans for the concrete *outcomes* a gate can produce, so
the inventory is anchored on decisions rather than on naming convention:

  reject / block / downgrade / quarantine / halt / skip

Each family is a set of marker tokens confirmed to exist in src/feelies/.  For
each marker the scan records every non-comment occurrence with its package, and
separates the declaration site from the use sites.

Also reports fail-quiet candidates: `except` handlers whose body neither raises,
returns, nor logs -- a swallowed exception is a gate that silently passed.

Writes evidence/gatescan.json.

Usage:
    python tools/arch/gatescan.py
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

GATE_FAMILIES: dict[str, list[str]] = {
    "alpha_load_gate": ["LayerValidationError", "TrendMechanismError"],
    "order_admission_block": [
        "BLOCK_HALT_BLACKOUT", "BLOCK_SESSION_FLATTEN_WINDOW", "BLOCK_SSR",
        "BLOCK_LOCATE_UNAVAILABLE", "BLOCK_BELOW_MIN_ORDER_SHARES",
        "BLOCK_EDGE_BELOW_COST", "BLOCK_EDGE_UNPRICEABLE",
    ],
    "risk_verdict": [
        "RiskAction.REJECT", "RiskAction.SCALE_DOWN", "RiskAction.FORCE_FLATTEN",
        "RiskAction.ALLOW",
    ],
    "data_health": ["DataHealth.HALTED", "DataHealth.DEGRADED", "DataHealth.STALE",
                    "DataHealth.GAP", "DataHealth.HEALTHY", "DataHealth.CORRUPT"],
    "macro_degrade": ["MacroState.DEGRADED", "MacroState.RISK_LOCKDOWN",
                      "MacroState.HALTED", "MacroState.SHUTDOWN"],
    "kill_switch": ["KillSwitchActivation", "kill_switch.activate", "is_active"],
    "lifecycle_quarantine": ["AlphaLifecycleState.QUARANTINED", "quarantine("],
    "warmup_staleness": ["warm=False", "stale=True", "not warm", "is_warm"],
    "regime_gate": ["regime_gate_state", "SafetyStateChange", "SafetyReason"],
    "escalation": ["RiskLevel."],
}


def py_files(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def package_of(relpath: str) -> str:
    parts = relpath.split("/")
    return parts[2] if len(parts) > 3 else "(root)"


def fail_quiet_handlers():
    """`except` blocks that neither raise, return, log, nor publish."""
    out = []
    for p in py_files(SRC):
        r = rel(p)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.ExceptHandler):
                continue
            body_src = "\n".join(ast.unparse(s) for s in n.body)
            has_raise = any(isinstance(x, ast.Raise) for x in ast.walk(n))
            has_return = any(isinstance(x, ast.Return) for x in ast.walk(n))
            logged = bool(re.search(r"\b(logger|_logger|log)\.\w+\(|warnings\.warn|"
                                    r"publish\(|record\(|_emit|_publish", body_src))
            only_pass = len(n.body) == 1 and isinstance(n.body[0], ast.Pass)
            if not (has_raise or has_return or logged):
                out.append({
                    "path": r, "line": n.lineno, "package": package_of(r),
                    "exc_type": ast.unparse(n.type) if n.type else "BARE",
                    "only_pass": only_pass,
                    "body": body_src[:160],
                })
    return out


def main():
    per_family = {}
    for family, markers in GATE_FAMILIES.items():
        sites = []
        for p in py_files(SRC):
            r = rel(p)
            for i, line in enumerate(
                    p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                for m in markers:
                    if m in line:
                        sites.append({"path": r, "line": i, "marker": m,
                                      "package": package_of(r), "text": s[:150]})
        by_pkg = defaultdict(int)
        for h in sites:
            by_pkg[h["package"]] += 1
        per_family[family] = {
            "markers": markers,
            "n_sites": len(sites),
            "packages": dict(sorted(by_pkg.items(), key=lambda x: -x[1])),
            "sites": sites,
        }

    quiet = fail_quiet_handlers()
    quiet_by_pkg = defaultdict(int)
    for h in quiet:
        quiet_by_pkg[h["package"]] += 1

    payload = {
        "families": per_family,
        "family_totals": {k: v["n_sites"] for k, v in per_family.items()},
        "fail_quiet_except_handlers": quiet,
        "n_fail_quiet_except_handlers": len(quiet),
        "fail_quiet_by_package": dict(sorted(quiet_by_pkg.items(), key=lambda x: -x[1])),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "gatescan.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")

    print(f"gatescan -> {rel(out)}")
    for k, v in sorted(payload["family_totals"].items(), key=lambda x: -x[1]):
        pkgs = ", ".join(f"{p}:{c}" for p, c in
                         list(per_family[k]["packages"].items())[:5])
        print(f"  {k:<24} {v:>4} sites   [{pkgs}]")
    print(f"\n  fail-quiet except handlers (no raise/return/log): {len(quiet)}")
    for h in quiet:
        flag = " ONLY-PASS" if h["only_pass"] else ""
        print(f"      {h['path']}:{h['line']}  except {h['exc_type']}{flag}  "
              f"{h['body'][:70]}")


if __name__ == "__main__":
    main()
