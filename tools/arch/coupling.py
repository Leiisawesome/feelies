#!/usr/bin/env python3
"""
Coupling and mode-seam measurement for Phase 0 (D0.3 / D0.4).  Stdlib only.

Measures, over src/feelies/:
  1. mode branches -- every read of an operating mode outside the declared mode
     seam.  CORE §C.4 puts mode differences behind ExecutionBackend and nowhere
     else, so each hit outside execution/ + broker/ is a candidate defect.
  2. direct collaborator calls from the orchestrator -- `self._x.method(...)`
     grouped by collaborator attribute.  These are the calls that bypass the
     event bus and therefore form the real tick-critical chain.
  3. cross-object private access -- `obj._attr` where obj is not `self`, i.e.
     one module reaching through another's encapsulation.
  4. attributes assigned onto an object from outside its own class
     (monkey-patched fields), which do not appear in any type contract.

Writes evidence/coupling.json.

Usage:
    python tools/arch/coupling.py
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

# The declared mode seam per CORE §C.4.  Anything here is allowed to know the mode.
MODE_SEAM_PREFIXES = ("src/feelies/execution/", "src/feelies/broker/")

MODE_TOKEN = re.compile(r"\bOperatingMode\.\w+|\.mode\b|\bmode\s*==|\bis_backtest\b|\bis_live\b")


def py_files(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def parse(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
    except SyntaxError:
        return None


def mode_branches():
    """Reads of the operating mode, split by whether they sit in the mode seam."""
    hits = []
    for p in py_files(SRC):
        r = rel(p)
        tree = parse(p)
        if not tree:
            continue
        # Only count comparisons/branches, not the enum definition itself.
        for n in ast.walk(tree):
            texts = []
            if isinstance(n, ast.Compare):
                texts.append(ast.unparse(n))
            elif isinstance(n, ast.If):
                texts.append(ast.unparse(n.test))
            elif isinstance(n, ast.IfExp):
                texts.append(ast.unparse(n.test))
            for t in texts:
                is_op = "OperatingMode." in t
                if is_op or re.search(r"\bmode\s*(==|!=)", t):
                    hits.append({
                        "path": r, "line": n.lineno, "test": t[:200],
                        # False positives exist: the alpha layer uses `mode` for
                        # the safety-exit policy, unrelated to OperatingMode.
                        "kind": "operating_mode" if is_op else "other_mode_concept",
                        "in_mode_seam": r.startswith(MODE_SEAM_PREFIXES),
                    })
    # de-duplicate: an If test also appears as a Compare
    seen, uniq = set(), []
    for h in sorted(hits, key=lambda x: (x["path"], x["line"], -len(x["test"]))):
        key = (h["path"], h["line"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return uniq


def orchestrator_collaborators():
    """`self._x.method()` call sites in the orchestrator, grouped by collaborator."""
    f = SRC / "kernel" / "orchestrator.py"
    tree = parse(f)
    by_attr = defaultdict(lambda: defaultdict(int))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = dotted(n.func)
        m = re.match(r"^self\.(_\w+)\.(\w+)$", name)
        if m:
            by_attr[m.group(1)][m.group(2)] += 1
    return {a: dict(sorted(ms.items())) for a, ms in sorted(by_attr.items())}


def cross_object_private():
    """`obj._attr` reads/writes where obj is neither `self` nor `cls`."""
    hits = []
    for p in py_files(SRC):
        r = rel(p)
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Attribute) or not n.attr.startswith("_"):
                continue
            if n.attr.startswith("__"):
                continue
            base = n.value
            if isinstance(base, ast.Name) and base.id not in ("self", "cls"):
                hits.append({"path": r, "line": n.lineno, "expr": dotted(n)[:120],
                             "owner": base.id, "attr": n.attr})
            elif isinstance(base, ast.Attribute):
                b = dotted(base)
                if not b.startswith("self.") and "." in b:
                    hits.append({"path": r, "line": n.lineno, "expr": dotted(n)[:120],
                                 "owner": b, "attr": n.attr})
    return hits


def external_attribute_assignment():
    """Assignments of a new attribute onto a non-self object (monkey patching)."""
    hits = []
    for p in py_files(SRC):
        r = rel(p)
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            targets = []
            if isinstance(n, ast.Assign):
                targets = n.targets
            elif isinstance(n, ast.AnnAssign):
                targets = [n.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                    if t.value.id not in ("self", "cls"):
                        hits.append({"path": r, "line": n.lineno,
                                     "target": f"{t.value.id}.{t.attr}"})
    return hits


def main():
    modes = mode_branches()
    op_modes = [h for h in modes if h["kind"] == "operating_mode"]
    outside = [h for h in op_modes if not h["in_mode_seam"]]
    by_file = defaultdict(int)
    for h in outside:
        by_file[h["path"]] += 1

    collab = orchestrator_collaborators()
    private = cross_object_private()
    priv_by_file = defaultdict(int)
    for h in private:
        priv_by_file[h["path"]] += 1

    patched = external_attribute_assignment()

    payload = {
        "mode_branches": modes,
        "n_mode_branches": len(modes),
        "n_operating_mode_branches": len(op_modes),
        "n_other_mode_concept_branches": len(modes) - len(op_modes),
        "n_mode_branches_outside_seam": len(outside),
        "mode_branches_outside_seam_by_file": dict(sorted(by_file.items(),
                                                          key=lambda x: -x[1])),
        "mode_seam_prefixes": list(MODE_SEAM_PREFIXES),
        "orchestrator_collaborators": collab,
        "n_orchestrator_collaborators": len(collab),
        "orchestrator_collaborator_call_sites": {
            a: sum(ms.values()) for a, ms in collab.items()
        },
        "cross_object_private_access": private,
        "n_cross_object_private_access": len(private),
        "cross_object_private_by_file": dict(sorted(priv_by_file.items(),
                                                    key=lambda x: -x[1])),
        "external_attribute_assignment": patched,
        "n_external_attribute_assignment": len(patched),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "coupling.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"coupling -> {rel(out)}")
    print(f"  mode branches: {len(modes)} matched, {len(op_modes)} are OperatingMode, "
          f"{len(outside)} of those OUTSIDE the execution/broker mode seam")
    for f, c in list(by_file.items())[:12]:
        print(f"      {c:>3}  {f}")
    print(f"  orchestrator collaborators: {len(collab)} attributes, "
          f"{sum(sum(m.values()) for m in collab.values())} direct call sites")
    for a, c in sorted(payload["orchestrator_collaborator_call_sites"].items(),
                       key=lambda x: -x[1])[:15]:
        print(f"      {c:>4}  self.{a}")
    print(f"  cross-object private access: {len(private)} sites")
    for f, c in list(priv_by_file.items())[:10]:
        print(f"      {c:>3}  {f}")
    print(f"  external attribute assignment: {len(patched)} sites")
    for h in patched[:12]:
        print(f"      {h['path']}:{h['line']}  {h['target']}")


if __name__ == "__main__":
    main()
