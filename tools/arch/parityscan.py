#!/usr/bin/env python3
"""
Parity-surface measurement for Phase 0 / D0.6.  Stdlib only.

The determinism oracle is not a bit-level digest of the event stream.  Each
locked baseline is a hand-written f-string field list hashed with sha256, so the
protected surface is exactly the set of fields those f-strings name, at the
float precision they format with.  This script extracts that surface instead of
trusting the docstrings.

For every module under tests/determinism/ it reports:
  - the stream-hash helper functions and the event type each consumes;
  - every event field referenced inside the hashed f-strings;
  - the float format specifiers used (precision ceiling of the oracle);
  - the EXPECTED_*_HASH / _COUNT constants declared.

Then, per event class in feelies.core.events, it reports which declared fields
appear in ANY parity hash and which appear in none -- the unprotected surface.

Writes evidence/parity.json.

Usage:
    python tools/arch/parityscan.py
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
DET = ROOT / "tests" / "determinism"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

FLOAT_FMT = re.compile(r"\.(\d+)f")

# Hash helpers are not all in tests/determinism/; several baselines import a
# shared recorder/hasher from the fixture packages.
SCAN_DIRS = [
    ROOT / "tests" / "determinism",
    ROOT / "tests" / "fixtures",
    ROOT / "tests" / "_fixtures",
]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def event_fields() -> dict[str, list[str]]:
    """Declared field names per Event subclass, from core/events.py."""
    tree = ast.parse((SRC / "core" / "events.py").read_text(encoding="utf-8"))
    base = {"Event"}
    out: dict[str, list[str]] = {}
    for n in tree.body:
        if not isinstance(n, ast.ClassDef):
            continue
        bases = {b.id for b in n.bases if isinstance(b, ast.Name)}
        fields = [s.target.id for s in n.body
                  if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
        if n.name == "Event" or bases & base:
            base.add(n.name)
            out[n.name] = fields
    # subclasses inherit the base envelope
    envelope = out.get("Event", [])
    for k in out:
        if k != "Event":
            out[k] = envelope + out[k]
    return out


def scan_hash_helpers():
    """Find hash helpers and every event attribute they read.

    A field counts as protected if the helper touches it anywhere, not only
    inside an f-string: several helpers pre-format via a local
    (`value_repr = repr(float(r.value))`).  Collecting all attribute reads makes
    the protected set a superset, so the reported *unprotected* set is
    conservative.
    """
    # Pass A: collect every function in the scan dirs with its callees.
    funcs = []
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = ast.unparse(n)
                    callees = set()
                    for x in ast.walk(n):
                        if isinstance(x, ast.Call):
                            f = x.func
                            callees.add(f.id if isinstance(f, ast.Name)
                                        else getattr(f, "attr", ""))
                    funcs.append({"path": p, "node": n, "src": src,
                                  "direct": "hashlib" in body or "sha256" in body,
                                  "callees": callees})

    # Pass B: a function is a hash helper if it hashes directly or calls one.
    hashing_names = {f["node"].name for f in funcs if f["direct"]}
    changed = True
    while changed:
        changed = False
        for f in funcs:
            if f["node"].name in hashing_names:
                continue
            if f["callees"] & hashing_names:
                hashing_names.add(f["node"].name)
                changed = True

    helpers = []
    for f in funcs:
        n, p = f["node"], f["path"]
        if n.name not in hashing_names:
            continue
        fields, precisions = set(), set()
        for x in ast.walk(n):
            if isinstance(x, ast.Attribute):
                fields.add(x.attr)
            elif isinstance(x, ast.JoinedStr):
                for v in x.values:
                    if isinstance(v, ast.FormattedValue) and v.format_spec:
                        for fm in FLOAT_FMT.finditer(ast.unparse(v.format_spec)):
                            precisions.add(int(fm.group(1)))
        helpers.append({
            "path": rel(p), "line": n.lineno, "function": n.name,
            "param_annotations": [ast.unparse(a.annotation) for a in n.args.args
                                  if a.annotation is not None],
            "hashed_field_names": sorted(fields),
            "float_precisions": sorted(precisions),
        })

    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            consts = sorted(set(re.findall(
                r"^(EXPECTED_\w+)\s*[:=]",
                p.read_text(encoding="utf-8", errors="replace"), re.M)))
            if consts:
                helpers.append({"path": rel(p), "line": 0, "function": "(constants)",
                                "param_annotations": [], "hashed_field_names": [],
                                "float_precisions": [], "expected_constants": consts})
    return helpers


def main():
    fields_by_event = event_fields()
    helpers = scan_hash_helpers()

    hashed_names = set()
    all_precisions = defaultdict(int)
    for h in helpers:
        hashed_names.update(h["hashed_field_names"])
        for p in h["float_precisions"]:
            all_precisions[p] += 1

    # Which declared fields never appear in any parity hash?
    unprotected = {}
    for ev, fields in sorted(fields_by_event.items()):
        missing = [f for f in fields if f not in hashed_names]
        if missing:
            unprotected[ev] = missing

    # Which event classes have no hash helper naming them at all?
    annotated = " ".join(a for h in helpers for a in h["param_annotations"])
    no_helper = sorted(ev for ev in fields_by_event
                       if ev != "Event" and ev not in annotated)

    payload = {
        "hash_helpers": helpers,
        "n_hash_helpers": sum(1 for h in helpers if h["function"] != "(constants)"),
        "float_precision_histogram": dict(sorted(all_precisions.items())),
        "all_hashed_field_names": sorted(hashed_names),
        "declared_fields_by_event": fields_by_event,
        "fields_in_no_parity_hash": unprotected,
        "event_classes_with_no_hash_helper_annotation": no_helper,
        "determinism_test_modules": sorted(rel(p) for p in DET.glob("test_*.py")),
        "n_determinism_test_modules": len(list(DET.glob("test_*.py"))),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "parityscan.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"parityscan -> {rel(out)}")
    print(f"  determinism test modules: {payload['n_determinism_test_modules']}")
    print(f"  stream-hash helpers:      {payload['n_hash_helpers']}")
    print(f"  float precisions used:    {payload['float_precision_histogram']}")
    print(f"  distinct hashed fields:   {len(hashed_names)}")
    print("\n  fields declared on events but in NO parity hash:")
    for ev, miss in payload["fields_in_no_parity_hash"].items():
        print(f"      {ev:<26} {miss}")
    print(f"\n  event classes with no hash helper: {no_helper}")


if __name__ == "__main__":
    main()
