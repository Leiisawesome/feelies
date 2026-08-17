#!/usr/bin/env python3
"""
Module inventory renderer for Phase 0 / D0.1 + D0.2.  Stdlib only.

Emits a markdown table of every module under src/feelies/ with sloc, public
symbol count, the measure.py engine bucket, and the module docstring's first
sentence.  The docstring is the module's *declared* responsibility -- a claim,
not verified behaviour -- and is labelled as such in the output.

Also emits per-package aggregates used for the D0.2 engine mapping.

Writes evidence/inventory.json and evidence/inventory_table.md.

Usage:
    python tools/arch/inventory.py
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


def py_files(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def package_of(relpath: str) -> str:
    parts = relpath.split("/")
    return "/".join(parts[2:-1]) if len(parts) > 3 else "(root)"


def top_package(relpath: str) -> str:
    parts = relpath.split("/")
    return parts[2] if len(parts) > 3 else "(root)"


def first_sentence(doc: str | None) -> str:
    if not doc:
        return "(no module docstring)"
    text = " ".join(doc.strip().split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    return out[:180]


def main():
    rows = []
    for p in py_files(SRC):
        src = p.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        sloc = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree)
        except SyntaxError:
            tree, doc = None, None
        public = 0
        if tree:
            for n in tree.body:
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not n.name.startswith("_"):
                        public += 1
        r = rel(p)
        rows.append({
            "path": r,
            "package": top_package(r),
            "subpackage": package_of(r),
            "sloc": sloc,
            "public_symbols": public,
            "declared_responsibility": first_sentence(doc),
        })

    by_pkg = defaultdict(lambda: {"files": 0, "sloc": 0, "public": 0})
    for r in rows:
        b = by_pkg[r["package"]]
        b["files"] += 1
        b["sloc"] += r["sloc"]
        b["public"] += r["public_symbols"]

    payload = {
        "modules": rows,
        "total_files": len(rows),
        "total_sloc": sum(r["sloc"] for r in rows),
        "total_public_symbols": sum(r["public_symbols"] for r in rows),
        "by_package": {k: v for k, v in sorted(by_pkg.items(),
                                               key=lambda x: -x[1]["sloc"])},
        "modules_without_docstring": [r["path"] for r in rows
                                      if r["declared_responsibility"].startswith("(no ")],
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "inventory.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")

    md = ["| module | sloc | public | declared responsibility (docstring — a claim) |",
          "|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["path"]):
        resp = r["declared_responsibility"].replace("|", "\\|")
        md.append(f"| `{r['path']}` | {r['sloc']} | {r['public_symbols']} | {resp} |")
    (EVIDENCE / "inventory_table.md").write_text("\n".join(md) + "\n",
                                                 encoding="utf-8", newline="\n")

    print(f"inventory: {len(rows)} modules, {payload['total_sloc']} sloc, "
          f"{payload['total_public_symbols']} public symbols")
    print(f"  -> {rel(EVIDENCE / 'inventory.json')}")
    print(f"  -> {rel(EVIDENCE / 'inventory_table.md')}")
    print(f"  modules without a docstring: {len(payload['modules_without_docstring'])}")
    print("\n  per top-level package (sloc desc):")
    for k, v in payload["by_package"].items():
        print(f"      {k:<14} {v['files']:>4} files  {v['sloc']:>6} sloc  "
              f"{v['public']:>4} public")


if __name__ == "__main__":
    main()
