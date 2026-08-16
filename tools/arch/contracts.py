#!/usr/bin/env python3
"""
Contract inventory for Phase 0 / D0.3.  Standard library only.

Measures, over src/feelies/:
  1. every class transitively derived from feelies.core.events.Event;
  2. whether any event class carries a schema/contract version field;
  3. bus publish sites, resolved to the concrete event type where the first
     argument is a constructor call or a locally-assigned constructor result;
  4. bus subscribe sites, resolved to the subscribed event type;
  5. publisher/subscriber sets per event type, and the orphan sets
     (published-never-subscribed, subscribed-never-published);
  6. dispatch semantics of the bus itself (exact-type vs subtype), read off
     the bus implementation rather than assumed.

Writes evidence/contracts.json.

Usage:
    python tools/arch/contracts.py
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

VERSION_FIELD_HINT = re.compile(r"(schema|contract|event)_?version|^version$", re.I)

# Publish sites the static resolver cannot type, resolved by reading the source.
# Each entry is a hand-verified fact, kept here so the evidence file has no holes
# and so a future structural change surfaces as a resolver regression.
MANUAL_RESOLUTIONS = {
    # `def _publish_and_apply_order_acks(self, acks: list[OrderAck])` -> `for ack in acks`
    "src/feelies/kernel/orchestrator.py:3828": "OrderAck",
    # `intent = registered.alpha.construct(...)` -> `replace(intent, ...)`; the
    # PortfolioAlpha.construct protocol returns SizedPositionIntent.
    "src/feelies/composition/engine.py:276": "SizedPositionIntent",
}


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


# ---------------------------------------------------------------- event classes

def collect_classes():
    """name -> {path, line, bases, fields, is_dataclass, frozen, slots}"""
    out = {}
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.ClassDef):
                continue
            bases = [dotted(b).split(".")[-1] for b in n.bases]
            frozen = slots = False
            is_dc = False
            for d in n.decorator_list:
                nm = dotted(d.func) if isinstance(d, ast.Call) else dotted(d)
                if nm.split(".")[-1] == "dataclass":
                    is_dc = True
                    if isinstance(d, ast.Call):
                        for kw in d.keywords:
                            if kw.arg == "frozen" and isinstance(kw.value, ast.Constant):
                                frozen = bool(kw.value.value)
                            if kw.arg == "slots" and isinstance(kw.value, ast.Constant):
                                slots = bool(kw.value.value)
            fields = []
            for stmt in n.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    ann = ast.unparse(stmt.annotation)
                    fields.append({
                        "name": stmt.target.id,
                        "type": ann,
                        "has_default": stmt.value is not None,
                        "mutable_container": bool(
                            re.match(r"^(dict|list|set)\b", ann.strip())
                        ),
                    })
            out.setdefault(n.name, {
                "class": n.name, "path": rel(p), "line": n.lineno, "bases": bases,
                "fields": fields, "is_dataclass": is_dc, "frozen": frozen, "slots": slots,
            })
    return out


def event_closure(classes):
    """Transitive subclasses of Event, by name."""
    events, changed = {"Event"}, True
    while changed:
        changed = False
        for name, c in classes.items():
            if name in events:
                continue
            if any(b in events for b in c["bases"]):
                events.add(name)
                changed = True
    return {n: classes[n] for n in sorted(events) if n in classes}


# ---------------------------------------------------------------- bus sites

def _strip_optional(ann: str) -> str:
    ann = ann.strip().strip('"').strip("'")
    ann = re.sub(r"\s*\|\s*None$", "", ann)
    m = re.match(r"^(?:Optional|Iterable|Sequence|list|tuple)\[(.+?)[,\]]", ann)
    if m:
        ann = m.group(1)
    return ann.split(".")[-1].strip()


def global_returns(ev_names: set[str]) -> dict[str, str]:
    """method name -> return type, across all of src/.

    Needed because a publish site often reads `v = risk.check_order(...)` where
    the annotation lives in another module.  Ambiguous names (same method name,
    conflicting event return types) are dropped rather than guessed.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.returns is not None:
                seen[n.name].add(_strip_optional(ast.unparse(n.returns)))
    out = {}
    for name, types in seen.items():
        ev = {t for t in types if t in ev_names}
        if len(ev) == 1:
            out[name] = next(iter(ev))
        elif not ev and len(types) == 1:
            out[name] = next(iter(types))
    return out


def _file_maps(tree: ast.AST, ev_names: set[str]):
    """Per-file resolution tables: local var -> type, func name -> return type."""
    local_ctor: dict[str, str] = {}
    func_ret: dict[str, str] = {}
    param_ann: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.returns is not None:
                func_ret[n.name] = _strip_optional(ast.unparse(n.returns))
            for a in list(n.args.args) + list(n.args.kwonlyargs):
                if a.annotation is not None:
                    param_ann[a.arg] = _strip_optional(ast.unparse(a.annotation))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            local_ctor[n.target.id] = _strip_optional(ast.unparse(n.annotation))
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            cname = dotted(n.value.func).split(".")[-1]
            for t in n.targets:
                if isinstance(t, ast.Name):
                    local_ctor.setdefault(t.id, cname)
        elif isinstance(n, ast.For) and isinstance(n.target, ast.Name):
            # `for tick in scheduler.on_event(ev): bus.publish(tick)`
            if isinstance(n.iter, ast.Call):
                local_ctor.setdefault(n.target.id, dotted(n.iter.func).split(".")[-1])
            elif isinstance(n.iter, (ast.Name, ast.Attribute)):
                local_ctor.setdefault(n.target.id, dotted(n.iter).split(".")[-1])
    return local_ctor, func_ret, param_ann


def _resolve(arg, local_ctor, func_ret, gret, param_ann, ev_names, depth=0):
    """Return (type_name, how). Follows replace() targets and return annotations."""
    if arg is None or depth > 5:
        return None, "none"
    if isinstance(arg, ast.Call):
        fname = dotted(arg.func).split(".")[-1]
        # dataclasses.replace(ev, ...) has the type of its first positional arg
        if fname == "replace" and arg.args:
            t, how = _resolve(arg.args[0], local_ctor, func_ret, gret, param_ann,
                              ev_names, depth + 1)
            return t, f"replace<-{how}"
        if fname in ev_names:
            return fname, "ctor"
        for table, how in ((func_ret, "return_annotation"),
                           (gret, "global_return_annotation")):
            if fname in table:
                return table[fname], how
        return fname, "call_unresolved"
    if isinstance(arg, ast.Name):
        for table, how in ((local_ctor, "local_assign"), (param_ann, "param_annotation")):
            v = table.get(arg.id)
            if v:
                if v in ev_names:
                    return v, how
                for t2, how2 in ((func_ret, "return_annotation"),
                                 (gret, "global_return_annotation")):
                    if v in t2:
                        return t2[v], f"{how}<-{how2}"
                # `for ack in acks:` where `acks: list[OrderAck]` is a parameter,
                # or a chain of local rebindings.  Follow the alias.
                if v != arg.id and (v in local_ctor or v in param_ann):
                    t3, how3 = _resolve(ast.Name(id=v), local_ctor, func_ret, gret,
                                        param_ann, ev_names, depth + 1)
                    if t3 in ev_names:
                        return t3, f"{how}<-alias<-{how3}"
                return v, f"{how}_nonevent"
        return arg.id, "name_unresolved"
    if isinstance(arg, ast.Attribute):
        return dotted(arg).split(".")[-1], "attribute"
    return None, "none"


def bus_sites(ev_names: set[str], gret: dict[str, str]):
    """Resolve publish/subscribe call sites to event type names."""
    pubs, subs, unresolved_pub = [], [], []
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        r = rel(p)
        local_ctor, func_ret, param_ann = _file_maps(tree, ev_names)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            leaf = dotted(n.func).split(".")[-1] if n.func else ""
            if leaf not in ("publish", "subscribe", "subscribe_all"):
                continue
            recv = dotted(n.func).rsplit(".", 1)[0] if "." in dotted(n.func) else ""
            arg0 = n.args[0] if n.args else None
            if leaf == "subscribe":
                resolved = dotted(arg0).split(".")[-1] if arg0 is not None else None
                how = "subscribe_arg"
            else:
                resolved, how = _resolve(arg0, local_ctor, func_ret, gret,
                                         param_ann, ev_names)
            manual = MANUAL_RESOLUTIONS.get(f"{r}:{n.lineno}")
            if manual and leaf == "publish":
                resolved, how = manual, "manual_verified"
            rec = {"path": r, "line": n.lineno, "receiver": recv, "call": leaf,
                   "event_type": resolved, "resolution": how}
            if leaf == "publish":
                pubs.append(rec)
                if resolved not in ev_names:
                    unresolved_pub.append(rec)
            else:
                subs.append(rec)
    return pubs, subs, unresolved_pub


def dispatch_semantics():
    """Read the bus implementation; classify dispatch as exact-type or subtype."""
    f = SRC / "bus" / "event_bus.py"
    text = f.read_text(encoding="utf-8")
    exact = "self._handlers.get(type(event))" in text or "_handlers[type(event)]" in text
    mro_walk = bool(re.search(r"type\(event\)\.__mro__|isinstance\(event", text))
    pub_methods = [m for m in re.findall(r"^\s*def\s+([a-z]\w*)", text, re.M)
                   if not m.startswith("_")]
    # call-site count per public bus method across src/
    counts = {}
    for m in pub_methods:
        counts[m] = sum(
            1 for p in py_files(SRC)
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if f".{m}(" in ln
        )
    return {"path": rel(f), "exact_type_dispatch": exact, "subtype_dispatch": mro_walk,
            "public_methods": pub_methods, "call_site_counts": counts}


def main():
    classes = collect_classes()
    events = event_closure(classes)

    versioned = {n: [f["name"] for f in c["fields"] if VERSION_FIELD_HINT.search(f["name"])]
                 for n, c in events.items()}
    versioned = {n: v for n, v in versioned.items() if v}

    mutable_fields = {
        n: [f["name"] for f in c["fields"] if f["mutable_container"]]
        for n, c in events.items()
    }
    mutable_fields = {n: v for n, v in mutable_fields.items() if v}

    gret = global_returns(set(events))
    pubs, subs, unresolved = bus_sites(set(events), gret)
    pub_by_type = defaultdict(set)
    sub_by_type = defaultdict(set)
    for r in pubs:
        if r["event_type"]:
            pub_by_type[r["event_type"]].add(f"{r['path']}:{r['line']}")
    for r in subs:
        if r["call"] == "subscribe" and r["event_type"]:
            sub_by_type[r["event_type"]].add(f"{r['path']}:{r['line']}")

    ev_names = set(events)
    published = {t for t in pub_by_type if t in ev_names}
    subscribed = {t for t in sub_by_type if t in ev_names}

    payload = {
        "event_classes": {n: {k: v for k, v in c.items() if k != "fields"} | {
            "field_names": [f["name"] for f in c["fields"]],
            "n_fields": len(c["fields"]),
        } for n, c in events.items()},
        "n_event_classes": len(events),
        "event_classes_outside_core_events": sorted(
            n for n, c in events.items() if c["path"] != "src/feelies/core/events.py"
        ),
        "events_with_version_field": versioned,
        "events_with_mutable_container_fields": mutable_fields,
        "non_frozen_event_classes": sorted(
            n for n, c in events.items() if c["is_dataclass"] and not c["frozen"]
        ),
        "dispatch": dispatch_semantics(),
        "publishers_by_type": {k: sorted(v) for k, v in sorted(pub_by_type.items())},
        "subscribers_by_type": {k: sorted(v) for k, v in sorted(sub_by_type.items())},
        "dynamic_subscribe_sites": [
            r for r in subs if r["call"] == "subscribe" and r["event_type"] not in ev_names
        ],
        "published_never_subscribed": sorted(published - subscribed),
        "subscribed_never_published": sorted(subscribed - published),
        "event_classes_never_published": sorted(ev_names - published - {"Event"}),
        "unresolved_publish_sites": unresolved,
        "n_publish_sites": len(pubs),
        "n_subscribe_sites": len(subs),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "contracts.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"contracts: {len(events)} Event subclasses -> {rel(out)}")
    print(f"  outside core/events.py: {payload['event_classes_outside_core_events']}")
    print(f"  with a version field:   {payload['events_with_version_field'] or 'NONE'}")
    print(f"  non-frozen:             {payload['non_frozen_event_classes'] or 'none'}")
    d = payload["dispatch"]
    print(f"  dispatch: exact_type={d['exact_type_dispatch']} subtype={d['subtype_dispatch']}")
    print(f"  bus public methods + call sites: {d['call_site_counts']}")
    print(f"  publish sites {len(pubs)} ({len(unresolved)} unresolved), "
          f"subscribe sites {len(subs)}")
    print(f"  published-never-subscribed: {payload['published_never_subscribed']}")
    print(f"  subscribed-never-published: {payload['subscribed_never_published']}")
    print(f"  never published at all:     {payload['event_classes_never_published']}")
    print(f"  mutable containers in frozen events: "
          f"{sorted(payload['events_with_mutable_container_fields'])}")


if __name__ == "__main__":
    main()
