#!/usr/bin/env python3
"""
Phase 1 (Axis A) substrate scan.  Stdlib only.

Measures the plumbing facts P1 asks for that no existing evidence file covers:

  1. sequence spaces        -- every ``SequenceGenerator`` construction and its
                               ``thread_safe`` argument (P1 section 2, 4).
  2. bus re-entrancy        -- which bus handlers can reach ``.publish(`` from
                               inside their own dispatch (P1 section 3).
  3. subscription order     -- bus ``subscribe`` calls in source order per file,
                               since dispatch is registration-ordered.
  4. identity generation    -- uuid / random / secrets / ``id()`` / ``hash()`` /
                               ``derive_order_id`` / ``make_correlation_id``
                               (P1 section 4).
  5. state and reset        -- classes holding mutable instance state and
                               whether they expose a reset path (P1 section 5).
  6. nondeterminism budget  -- filesystem enumeration, unsorted mapping/set
                               iteration, float reductions, RNG, locale/tz,
                               threading (P1 required artifact).

Writes evidence/substrate.json.

Usage:
    python tools/arch/substrate.py
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

# Mirrors clockscan.py so hot/cold classification stays consistent across
# Phase 0 and Phase 1 evidence.  Per CORE section D.
HOT_PACKAGES = {
    "ingestion", "storage", "sensors", "features", "services", "signals",
    "composition", "portfolio", "risk", "execution", "broker", "kernel", "bus", "core",
}

RESET_METHOD_NAMES = {"reset", "restore", "clear", "checkpoint", "reset_state", "flush"}

FS_ENUM_LEAVES = {"rglob", "glob", "iterdir", "listdir", "scandir", "walk"}
RNG_ROOTS = {"random", "secrets", "uuid"}
FLOAT_REDUCTION_LEAVES = {"fsum", "mean", "median", "stdev", "variance"}
LOCALE_LEAVES = {"setlocale", "getlocale", "getpreferredencoding", "tzset", "astimezone"}


def py_files(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def package_of(relpath: str) -> str:
    parts = relpath.split("/")
    return parts[2] if len(parts) > 3 else "(root)"


def dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def src_line(lines: list[str], lineno: int) -> str:
    return lines[lineno - 1].strip()[:160] if 0 < lineno <= len(lines) else ""


class FileScan:
    """One module's AST facts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rel = rel(path)
        self.pkg = package_of(self.rel)
        self.hot = self.pkg in HOT_PACKAGES
        text = path.read_text(encoding="utf-8", errors="replace")
        self.lines = text.splitlines()
        self.tree = ast.parse(text, filename=str(path))
        # method qualname -> set of attribute names it calls on ``self``
        self.self_calls: dict[str, set[str]] = defaultdict(set)
        # method qualname -> True when its own body contains ``.publish(``
        self.publishes: dict[str, bool] = {}
        # Names annotated ``set[...]`` / ``frozenset[...]`` anywhere in the
        # module, so iteration over them can be told apart from dict iteration.
        self.set_names: set[str] = set()
        self._index_functions()
        self._index_set_names()

    def _index_set_names(self) -> None:
        for n in ast.walk(self.tree):
            if not isinstance(n, ast.AnnAssign) or n.annotation is None:
                continue
            ann = ast.unparse(n.annotation)
            if not (ann.startswith("set[") or ann.startswith("frozenset[")):
                continue
            tgt = n.target
            if isinstance(tgt, ast.Name):
                self.set_names.add(tgt.id)
            elif isinstance(tgt, ast.Attribute):
                self.set_names.add(ast.unparse(tgt))

    def _index_functions(self) -> None:
        for cls in ast.walk(self.tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                qual = f"{cls.name}.{fn.name}"
                pub = False
                for n in ast.walk(fn):
                    if not isinstance(n, ast.Call):
                        continue
                    name = dotted(n.func)
                    if name.endswith(".publish"):
                        pub = True
                    # ``self._foo(...)`` / ``self.foo(...)``
                    segs = name.split(".")
                    if len(segs) == 2 and segs[0] == "self":
                        self.self_calls[qual].add(segs[1])
                self.publishes[qual] = pub


def transitive_publishes(scan: FileScan, qual: str, depth: int = 4) -> tuple[bool, str]:
    """Does ``qual`` reach a ``.publish(`` within ``depth`` self-call hops?"""
    cls = qual.split(".")[0]
    seen = {qual}
    frontier = [(qual, 0)]
    while frontier:
        cur, d = frontier.pop()
        if scan.publishes.get(cur):
            return True, cur
        if d >= depth:
            continue
        for attr in scan.self_calls.get(cur, ()):
            nxt = f"{cls}.{attr}"
            if nxt in seen or nxt not in scan.publishes:
                continue
            seen.add(nxt)
            frontier.append((nxt, d + 1))
    return False, ""


def main() -> None:
    scans = [FileScan(p) for p in py_files(SRC)]

    sequence_generators: list[dict] = []
    bus_subscriptions: list[dict] = []
    identity_sites: list[dict] = []
    fs_enumeration: list[dict] = []
    rng_sites: list[dict] = []
    float_reductions: list[dict] = []
    locale_tz_sites: list[dict] = []
    unsorted_mapping_iteration: list[dict] = []
    classes: list[dict] = []

    for scan in scans:
        L = scan.lines

        for n in ast.walk(scan.tree):
            # ---- calls -------------------------------------------------
            if isinstance(n, ast.Call):
                name = dotted(n.func)
                leaf = name.split(".")[-1]
                root = name.split(".")[0]

                if leaf == "SequenceGenerator":
                    thread_safe = "<default True>"
                    for kw in n.keywords:
                        if kw.arg == "thread_safe":
                            thread_safe = (
                                repr(kw.value.value)
                                if isinstance(kw.value, ast.Constant)
                                else ast.unparse(kw.value)
                            )
                    sequence_generators.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "thread_safe": thread_safe, "text": src_line(L, n.lineno),
                    })

                if leaf in ("subscribe", "subscribe_all") and name.endswith(
                    ("bus.subscribe", "bus.subscribe_all",
                     "_bus.subscribe", "_bus.subscribe_all")
                ):
                    event = ast.unparse(n.args[0]) if n.args else "<all>"
                    handler = ast.unparse(n.args[1]) if len(n.args) > 1 else (
                        ast.unparse(n.args[0]) if leaf == "subscribe_all" and n.args else "?"
                    )
                    bus_subscriptions.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "method": leaf, "event": event, "handler": handler,
                        "text": src_line(L, n.lineno),
                    })

                if leaf in ("derive_order_id", "make_correlation_id"):
                    seed = ast.unparse(n.args[0])[:120] if n.args else ""
                    identity_sites.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "kind": leaf, "seed": seed, "text": src_line(L, n.lineno),
                    })
                if leaf in ("id", "hash") and isinstance(n.func, ast.Name):
                    identity_sites.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "kind": f"builtin_{leaf}", "seed": "",
                        "text": src_line(L, n.lineno),
                    })
                if root in RNG_ROOTS:
                    rng_sites.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "call": name, "text": src_line(L, n.lineno),
                    })

                # ``ast.walk`` shares the leaf name and is not a filesystem read.
                if leaf in FS_ENUM_LEAVES and not name.startswith("ast."):
                    fs_enumeration.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "call": name, "text": src_line(L, n.lineno),
                        # ``sorted(p.rglob(...))`` neutralizes FS order.
                        "sorted_on_same_line": "sorted(" in src_line(L, n.lineno),
                    })
                if leaf in FLOAT_REDUCTION_LEAVES or (leaf == "sum" and isinstance(n.func, ast.Name)):
                    float_reductions.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "call": name, "hot": scan.hot, "text": src_line(L, n.lineno),
                    })
                if leaf in LOCALE_LEAVES:
                    locale_tz_sites.append({
                        "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                        "call": name, "text": src_line(L, n.lineno),
                    })

            # ---- iteration order ---------------------------------------
            # dict iteration is insertion-ordered and therefore deterministic;
            # set iteration is hash-ordered and is not.  Counted separately.
            if isinstance(n, (ast.For, ast.comprehension)):
                it = n.iter
                itxt = ast.unparse(it)
                if "sorted(" in itxt:
                    continue
                lineno = getattr(n, "lineno", getattr(it, "lineno", 0))
                leaf = dotted(it.func).split(".")[-1] if isinstance(it, ast.Call) else ""
                is_set = (
                    isinstance(it, (ast.Set, ast.SetComp))
                    or (isinstance(it, ast.Call) and leaf in ("set", "frozenset"))
                    or itxt in scan.set_names
                    or (isinstance(it, ast.Attribute) and ast.unparse(it) in scan.set_names)
                )
                is_mapping = leaf in ("values", "keys", "items")
                if not (is_set or is_mapping):
                    continue
                unsorted_mapping_iteration.append({
                    "path": scan.rel, "line": lineno, "package": scan.pkg,
                    "hot": scan.hot, "iter": itxt[:120],
                    "kind": "set" if is_set else "mapping",
                    "text": src_line(L, lineno),
                })

            # ---- classes: mutable state and reset path -----------------
            if isinstance(n, ast.ClassDef):
                attrs_init: set[str] = set()
                attrs_mutated: set[str] = set()
                methods = {
                    m.name for m in n.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for m in n.body:
                    if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for a in ast.walk(m):
                        tgts = []
                        if isinstance(a, ast.Assign):
                            tgts = a.targets
                        elif isinstance(a, (ast.AugAssign, ast.AnnAssign)):
                            tgts = [a.target]
                        for t in tgts:
                            if (
                                isinstance(t, ast.Attribute)
                                and isinstance(t.value, ast.Name)
                                and t.value.id == "self"
                            ):
                                (attrs_init if m.name == "__init__" else attrs_mutated).add(t.attr)
                if not attrs_init and not attrs_mutated:
                    continue
                classes.append({
                    "path": scan.rel, "line": n.lineno, "package": scan.pkg,
                    "hot": scan.hot, "cls": n.name,
                    "n_init_attrs": len(attrs_init),
                    "n_mutated_outside_init": len(attrs_mutated - {"_state"}),
                    "reset_methods": sorted(methods & RESET_METHOD_NAMES),
                })

    # ---- bus re-entrancy -------------------------------------------------
    by_path = {s.rel: s for s in scans}
    reentrant: list[dict] = []
    for sub in bus_subscriptions:
        h = sub["handler"]
        if not h.startswith("self."):
            continue
        scan = by_path[sub["path"]]
        attr = h.split(".", 1)[1]
        # Find the class that owns this method name in this module.
        for qual in scan.publishes:
            if qual.endswith("." + attr):
                reaches, via = transitive_publishes(scan, qual)
                if reaches:
                    reentrant.append({
                        "path": sub["path"], "line": sub["line"],
                        "event": sub["event"], "handler": qual,
                        "publishes_via": via,
                    })
                break

    subs_per_file = defaultdict(list)
    for s in bus_subscriptions:
        subs_per_file[s["path"]].append(s["line"])

    stateful_no_reset = [
        c for c in classes
        if c["n_mutated_outside_init"] > 0 and not c["reset_methods"]
    ]

    payload = {
        "sequence_generators": sequence_generators,
        "n_sequence_generators": len(sequence_generators),
        "sequence_generators_by_thread_safe": dict(sorted(
            ((k, sum(1 for s in sequence_generators if s["thread_safe"] == k))
             for k in {s["thread_safe"] for s in sequence_generators}),
            key=lambda kv: -kv[1],
        )),

        "bus_subscriptions": bus_subscriptions,
        "n_bus_subscriptions": len(bus_subscriptions),
        "bus_subscriptions_per_file": {
            k: len(v) for k, v in sorted(subs_per_file.items(), key=lambda kv: -len(kv[1]))
        },
        "reentrant_handlers": reentrant,
        "n_reentrant_handlers": len(reentrant),

        "identity_sites": identity_sites,
        "identity_by_kind": dict(sorted(
            ((k, sum(1 for i in identity_sites if i["kind"] == k))
             for k in {i["kind"] for i in identity_sites}),
            key=lambda kv: -kv[1],
        )),
        "rng_sites": rng_sites,
        "n_rng_sites": len(rng_sites),

        "fs_enumeration": fs_enumeration,
        "n_fs_enumeration": len(fs_enumeration),
        "n_fs_enumeration_unsorted": sum(
            1 for f in fs_enumeration if not f["sorted_on_same_line"]
        ),

        "float_reductions_hot": [f for f in float_reductions if f["hot"]],
        "n_float_reductions": len(float_reductions),
        "n_float_reductions_hot": sum(1 for f in float_reductions if f["hot"]),

        "locale_tz_sites": locale_tz_sites,
        "n_locale_tz_sites": len(locale_tz_sites),

        # dict iteration is insertion-ordered (deterministic); set iteration is
        # hash-ordered.  Only the set rows are a nondeterminism source.
        "unsorted_set_iteration": [
            u for u in unsorted_mapping_iteration if u["kind"] == "set"
        ],
        "n_unsorted_set_iteration": sum(
            1 for u in unsorted_mapping_iteration if u["kind"] == "set"
        ),
        "n_unsorted_set_iteration_hot": sum(
            1 for u in unsorted_mapping_iteration if u["kind"] == "set" and u["hot"]
        ),
        "n_unsorted_mapping_iteration": sum(
            1 for u in unsorted_mapping_iteration if u["kind"] == "mapping"
        ),
        "n_unsorted_mapping_iteration_hot": sum(
            1 for u in unsorted_mapping_iteration
            if u["kind"] == "mapping" and u["hot"]
        ),
        "unsorted_set_iteration_by_package": dict(sorted(
            ((k, sum(1 for u in unsorted_mapping_iteration
                     if u["kind"] == "set" and u["package"] == k))
             for k in {u["package"] for u in unsorted_mapping_iteration
                       if u["kind"] == "set"}),
            key=lambda kv: -kv[1],
        )),

        "n_stateful_classes": len(classes),
        "n_stateful_classes_mutating_outside_init": sum(
            1 for c in classes if c["n_mutated_outside_init"] > 0
        ),
        "n_stateful_no_reset": len(stateful_no_reset),
        "classes_with_reset": [c for c in classes if c["reset_methods"]],
        "stateful_no_reset_top": sorted(
            stateful_no_reset, key=lambda c: -c["n_mutated_outside_init"]
        )[:25],
    }

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "substrate.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"substrate -> {rel(out)}")
    print(f"  SequenceGenerator constructions: {payload['n_sequence_generators']} "
          f"{payload['sequence_generators_by_thread_safe']}")
    print(f"  bus subscribe call sites: {payload['n_bus_subscriptions']}  "
          f"re-entrant handlers (handler reaches publish): "
          f"{payload['n_reentrant_handlers']}")
    print(f"  identity sites: {payload['identity_by_kind']}")
    print(f"  RNG sites: {payload['n_rng_sites']}")
    print(f"  filesystem enumeration: {payload['n_fs_enumeration']} "
          f"({payload['n_fs_enumeration_unsorted']} not sorted on the same line)")
    print(f"  float reductions: {payload['n_float_reductions']} "
          f"({payload['n_float_reductions_hot']} in tick-critical packages)")
    print(f"  locale / tz sites: {payload['n_locale_tz_sites']}")
    print(f"  unsorted SET iteration (hash-ordered): "
          f"{payload['n_unsorted_set_iteration']} "
          f"({payload['n_unsorted_set_iteration_hot']} hot) "
          f"{payload['unsorted_set_iteration_by_package']}")
    print(f"  unsorted dict iteration (insertion-ordered, informational): "
          f"{payload['n_unsorted_mapping_iteration']} "
          f"({payload['n_unsorted_mapping_iteration_hot']} hot)")
    print(f"  stateful classes: {payload['n_stateful_classes']}; "
          f"mutating outside __init__: "
          f"{payload['n_stateful_classes_mutating_outside_init']}; "
          f"of those with no reset path: {payload['n_stateful_no_reset']}")


if __name__ == "__main__":
    main()
