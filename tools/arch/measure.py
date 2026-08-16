#!/usr/bin/env python3
"""
Architecture measurement harness. Standard library only.

Produces deterministic evidence files under tools/arch/evidence/ so that
architecture claims are VERIFIED rather than INFERRED.

Usage:
    python tools/arch/measure.py all
    python tools/arch/measure.py modules
    python tools/arch/measure.py imports
    python tools/arch/measure.py clock
    python tools/arch/measure.py nondet
    python tools/arch/measure.py bus
    python tools/arch/measure.py handlers
    python tools/arch/measure.py gates
    python tools/arch/measure.py alphaleak
    python tools/arch/measure.py discover
    python tools/arch/measure.py spotcheck docs/architecture/target/out/phase0_comprehension.md

Every subcommand writes evidence/<name>.json and prints a short summary.
The CONFIG block below is pre-derived from Leiisawesome/feelies @ main
(verified 2026-08-14). Re-derive with `discover` after structural changes.
Do not touch it mid-review -- changing the measurement invalidates the evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

# --------------------------------------------------------------------------
# CONFIG -- derived from Leiisawesome/feelies @ main, verified 2026-08-14.
# Re-derive after structural changes with:  python3 tools/arch/measure.py discover
# Do not edit mid-review -- changing the measurement invalidates the evidence.
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

# Engine directory hints, used only to bucket modules for the inventory.
# Longest prefix wins, so file-level hints override directory-level ones
# (this is how engines 9 and 10 split the single execution/ package).
# Wrong buckets are fine -- the agent corrects them in D0.2.
ENGINE_HINTS = {
    1: ["ingestion", "storage"],
    2: ["sensors", "features"],
    3: ["services"],
    4: ["signals"],
    5: ["alpha", "promotion"],
    6: ["composition"],
    7: ["portfolio"],
    8: ["risk"],
    9: ["execution/intent", "execution/position_manager", "execution/portfolio_netter",
        "execution/min_cost_policy", "execution/sized_intent_legs",
        "execution/order_admission"],
    10: ["execution", "broker"],
    11: ["monitoring"],
    12: ["harness", "research", "forensics"],
    0: ["core", "bus", "kernel", "cli", "bootstrap", "__init__", "__main__"],
}

# Wall-clock reads. Presence on the tick-critical path is a determinism defect.
CLOCK_CALLS = [
    "time.time", "time.monotonic", "time.perf_counter", "time.time_ns",
    "datetime.now", "datetime.utcnow", "datetime.today", "date.today",
]

# Nondeterminism heuristics. Each hit is a candidate, not a verdict.
NONDET_PATTERNS = {
    "uuid4": r"\buuid4\s*\(",
    "random": r"\brandom\.(?!Random\()\w+\s*\(",
    "hash_builtin": r"(?<![\w.])hash\s*\(",
    "set_iteration": r"for\s+\w+\s+in\s+(?:\w+\.)?(?:set\(|\{[^}:]+\}\s*\))",
    "dir_listing": r"\b(?:os\.listdir|os\.scandir|\.glob\(|\.iterdir\(|\.rglob\()",
    "threading": r"\b(?:threading\.|ThreadPoolExecutor|ProcessPoolExecutor|asyncio\.create_task)",
    "env_read": r"\bos\.environ\b",
    "id_builtin": r"(?<![\w.])id\s*\(",
}

# Bus API, derived from src/feelies/bus/event_bus.py.
# The bus exposes exactly three public methods: subscribe, subscribe_all, publish.
# NOTE for Phase 0: subscribe_all is DEFINED but has ZERO call sites outside its
# own definition. Dead public API surface on the bus is a D0.3 finding.
BUS_PUBLISH = ["publish"]
BUS_SUBSCRIBE = ["subscribe", "subscribe_all"]

# Non-bus dispatch verbs seen in src/, kept separate because they are handler
# entry points rather than bus operations. Counted for D0.3 completeness.
HANDLER_HINTS = ["on_quote", "on_trade", "on_event", "on_message", "on_transition",
                 "on_health_transition", "on_alert_event"]

# Gate heuristics: functions whose names suggest a guard.
GATE_NAME_HINTS = ["validate", "check", "gate", "allow", "reject", "guard",
                   "approve", "veto", "can_", "is_eligible", "verify", "assert_",
                   "admit", "eligible", "permit", "block", "halt", "quarantine"]

# Alpha-agnosticism check (CORE §I).
# Every alpha_id declared in alphas/**/*.alpha.yaml. Eleven, across three tiers:
# shipped signal alphas, research-tier alphas under alphas/research/, and the
# two template placeholders. Template IDs are included deliberately -- a
# placeholder ID appearing in src/ would itself be a finding.
ALPHA_IDS = [
    # shipped
    "paper_smoke_v1",
    "sig_benign_midcap_v1",
    "sig_contra_fixture_v1",
    "sig_hawkes_burst_v1",
    "sig_inventory_revert_v1",
    "sig_kyle_drift_v1",
    "sig_moc_imbalance_v1",
    # alphas/research/
    "pro_burst_revert_v1",
    "pro_kyle_benign_v1",
    # alphas/_template/
    "my_portfolio_alpha",
    "my_signal_alpha",
]

# Traded symbols appearing in configs/ and platform.yaml, plus symbols named in
# alpha evidence blocks. APP dominates (36 config references vs AAPL 4, SPY 1) --
# the universe is effectively single-symbol, which is what CORE §I calls the
# test-flight payload.
SYMBOL_LITERALS = ["APP", "AAPL", "SPY", "INTC", "SNDU"]

ALPHA_LITERALS = ALPHA_IDS + SYMBOL_LITERALS

# Scanned for leaks. Alphas legitimately name themselves; production code may not.
LEAK_SCAN_ROOTS = ["src"]
# Specific files inside the scan roots that are permitted to contain a literal.
# Empty by design: any entry here is an accepted defect and must be justified.
LEAK_EXEMPT_FILES: list[str] = []

# --------------------------------------------------------------------------


def py_files(base: Path):
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def engine_of(relpath: str):
    best, best_len = None, -1
    for eng, hints in ENGINE_HINTS.items():
        for h in hints:
            token = f"src/feelies/{h}"
            if relpath.startswith(token) and len(h) > best_len:
                best, best_len = eng, len(h)
    return best


def parse(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
    except SyntaxError as e:
        print(f"  !! parse error {rel(p)}: {e}", file=sys.stderr)
        return None


def write(name: str, payload) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"{name}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_modules(_args):
    rows = []
    for p in py_files(SRC):
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        sloc = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        tree = parse(p)
        classes = funcs = public = 0
        if tree:
            for n in tree.body:
                if isinstance(n, ast.ClassDef):
                    classes += 1
                    if not n.name.startswith("_"):
                        public += 1
                elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs += 1
                    if not n.name.startswith("_"):
                        public += 1
        r = rel(p)
        rows.append({"path": r, "engine_hint": engine_of(r), "loc": len(lines),
                     "sloc": sloc, "classes": classes, "functions": funcs,
                     "public_symbols": public})
    rows.sort(key=lambda x: -x["sloc"])
    by_engine = defaultdict(lambda: {"files": 0, "sloc": 0})
    for r in rows:
        b = by_engine[str(r["engine_hint"])]
        b["files"] += 1
        b["sloc"] += r["sloc"]
    out = write("modules", {"modules": rows, "by_engine_hint": dict(by_engine),
                            "total_files": len(rows),
                            "total_sloc": sum(r["sloc"] for r in rows)})
    print(f"modules: {len(rows)} files, {sum(r['sloc'] for r in rows)} sloc -> {rel(out)}")
    print("  largest:")
    for r in rows[:10]:
        print(f"    {r['sloc']:>6}  {r['path']}")


def cmd_imports(_args):
    mod_of = {}
    for p in py_files(SRC):
        m = rel(p)[len("src/"):].removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        mod_of[m] = rel(p)

    edges = defaultdict(set)
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        src_mod = rel(p)[len("src/"):].removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        pkg = src_mod.rsplit(".", 1)[0] if "." in src_mod else src_mod
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.startswith("feelies"):
                        edges[src_mod].add(a.name)
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    parts = pkg.split(".")
                    base_pkg = ".".join(parts[: len(parts) - n.level + 1])
                    base = f"{base_pkg}.{base}" if base else base_pkg
                if base.startswith("feelies"):
                    edges[src_mod].add(base)

    def resolve(m):
        if m in mod_of:
            return m
        cand = [k for k in mod_of if k == m or k.startswith(m + ".")]
        return m if not cand else sorted(cand, key=len)[0]

    graph = {s: sorted({resolve(t) for t in ts if resolve(t) != s}) for s, ts in edges.items()}

    # Tarjan SCC
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    sys.setrecursionlimit(10000)

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in list(graph):
        if v not in index:
            strong(v)

    ev = write("imports", {"edges": {k: v for k, v in sorted(graph.items())},
                           "cycles": out, "n_modules": len(graph),
                           "n_edges": sum(len(v) for v in graph.values())})
    print(f"imports: {len(graph)} modules, {sum(len(v) for v in graph.values())} internal edges, "
          f"{len(out)} cycle(s) -> {rel(ev)}")
    for c in out:
        print(f"    CYCLE ({len(c)}): {' -> '.join(c)}")


def _scan_calls(matcher):
    hits = []
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        r = rel(p)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                name = dotted(n.func)
                if name and matcher(name):
                    hits.append({"path": r, "line": n.lineno, "call": name,
                                 "engine_hint": engine_of(r)})
    return hits


def cmd_clock(_args):
    def m(name):
        return any(name == c or name.endswith("." + c.split(".")[-1]) and c.split(".")[-1] in
                   ("now", "utcnow", "today") and name.split(".")[-1] == c.split(".")[-1]
                   or name == c for c in CLOCK_CALLS)
    hits = _scan_calls(lambda n: any(n == c or n.endswith("." + c) or
                                     n.split(".")[-1] == c.split(".")[-1] for c in CLOCK_CALLS))
    by_engine = defaultdict(int)
    for h in hits:
        by_engine[str(h["engine_hint"])] += 1
    out = write("clock", {"hits": hits, "by_engine_hint": dict(by_engine), "n": len(hits)})
    print(f"clock: {len(hits)} wall-clock call sites -> {rel(out)}")
    for k in sorted(by_engine, key=lambda x: -by_engine[x])[:8]:
        print(f"    engine {k}: {by_engine[k]}")


def cmd_nondet(_args):
    hits = []
    for p in py_files(SRC):
        r = rel(p)
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for kind, pat in NONDET_PATTERNS.items():
                if re.search(pat, line):
                    hits.append({"path": r, "line": i, "kind": kind,
                                 "text": line.strip()[:160], "engine_hint": engine_of(r)})
    by_kind = defaultdict(int)
    for h in hits:
        by_kind[h["kind"]] += 1
    out = write("nondet", {"hits": hits, "by_kind": dict(by_kind), "n": len(hits)})
    print(f"nondet: {len(hits)} candidate sites -> {rel(out)}")
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"    {k:<16} {v}")


def cmd_bus(_args):
    pub, sub = [], []
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        r = rel(p)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = dotted(n.func)
            leaf = name.split(".")[-1] if name else ""
            arg = ""
            if n.args:
                a = n.args[0]
                if isinstance(a, ast.Name):
                    arg = a.id
                elif isinstance(a, ast.Call):
                    arg = dotted(a.func)
                elif isinstance(a, ast.Attribute):
                    arg = dotted(a)
                elif isinstance(a, ast.Constant):
                    arg = repr(a.value)
            rec = {"path": r, "line": n.lineno, "call": name, "first_arg": arg,
                   "engine_hint": engine_of(r)}
            if leaf in BUS_PUBLISH:
                pub.append(rec)
            elif leaf in BUS_SUBSCRIBE:
                sub.append(rec)
    out = write("bus", {"publish_sites": pub, "subscribe_sites": sub,
                        "n_publish": len(pub), "n_subscribe": len(sub)})
    print(f"bus: {len(pub)} publish, {len(sub)} subscribe call sites -> {rel(out)}")
    print("  NOTE: bus API is pre-derived. Re-verify with `measure.py discover`.")


def cmd_gates(_args):
    hits = []
    for p in py_files(SRC):
        tree = parse(p)
        if not tree:
            continue
        r = rel(p)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nm = n.name.lower()
                if any(h in nm for h in GATE_NAME_HINTS):
                    raises = sum(1 for x in ast.walk(n) if isinstance(x, ast.Raise))
                    returns = sum(1 for x in ast.walk(n) if isinstance(x, ast.Return))
                    bare_excepts = sum(1 for x in ast.walk(n)
                                       if isinstance(x, ast.ExceptHandler) and x.type is None)
                    silent = sum(1 for x in ast.walk(n) if isinstance(x, ast.ExceptHandler)
                                 and len(x.body) == 1 and isinstance(x.body[0], ast.Pass))
                    hits.append({"path": r, "line": n.lineno, "function": n.name,
                                 "raises": raises, "returns": returns,
                                 "bare_excepts": bare_excepts, "silent_excepts": silent,
                                 "engine_hint": engine_of(r)})
    silent_total = sum(h["silent_excepts"] for h in hits)
    out = write("gates", {"candidates": hits, "n": len(hits),
                          "silent_except_total": silent_total})
    print(f"gates: {len(hits)} guard-like functions, {silent_total} silent except blocks -> {rel(out)}")
    print("  NOTE: heuristic. Every hit needs manual classification in D0.5.")


def cmd_alphaleak(_args):
    hits = []
    for root in LEAK_SCAN_ROOTS:
        for p in py_files(ROOT / root):
            r = rel(p)
            if r in LEAK_EXEMPT_FILES:
                continue
            for i, line in enumerate(
                    p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for lit in ALPHA_LITERALS:
                    if re.search(rf"[\"']{re.escape(lit)}[\"']", line):
                        hits.append({"path": r, "line": i, "literal": lit,
                                     "kind": "alpha_id" if lit in ALPHA_IDS else "symbol",
                                     "engine_hint": engine_of(r),
                                     "text": line.strip()[:160]})
    by_kind = defaultdict(int)
    for h in hits:
        by_kind[h["kind"]] += 1
    out = write("alphaleak", {"hits": hits, "n": len(hits), "by_kind": dict(by_kind),
                              "alpha_ids": ALPHA_IDS, "symbols": SYMBOL_LITERALS,
                              "scan_roots": LEAK_SCAN_ROOTS,
                              "exempt": LEAK_EXEMPT_FILES})
    status = "CLEAN" if not hits else f"{len(hits)} LEAK(S)"
    print(f"alphaleak: {status} -> {rel(out)}")
    for h in hits[:25]:
        print(f"    [{h['kind']:<8}] {h['path']}:{h['line']}  {h['text']}")


def cmd_handlers(_args):
    """Non-bus dispatch entry points -- D0.3 completeness."""
    hits = _scan_calls(lambda n: n.split(".")[-1] in HANDLER_HINTS)
    by_name = defaultdict(int)
    for h in hits:
        by_name[h["call"].split(".")[-1]] += 1
    out = write("handlers", {"hits": hits, "by_name": dict(by_name), "n": len(hits)})
    print(f"handlers: {len(hits)} non-bus dispatch call sites -> {rel(out)}")
    for k, v in sorted(by_name.items(), key=lambda x: -x[1]):
        print(f"    {k:<24} {v}")


def cmd_discover(_args):
    """Re-derive CONFIG values from the repo. Review before pasting."""
    print("# --- paste-ready CONFIG, review every line ---\n")

    bus_file = SRC / "bus" / "event_bus.py"
    if bus_file.exists():
        pub_defs = re.findall(r"^\s*(?:async\s+)?def\s+([a-z]\w*)\s*\(",
                              bus_file.read_text(encoding="utf-8"), re.M)
        pub_defs = [d for d in pub_defs if not d.startswith("_")]
        counts = {}
        for d in pub_defs:
            counts[d] = sum(1 for p in py_files(SRC)
                            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                            if f".{d}(" in ln)
        print(f"# bus public API ({rel(bus_file)}), with call-site counts:")
        for d, c in sorted(counts.items(), key=lambda x: -x[1]):
            flag = "   <-- DEAD API" if c <= 1 else ""
            print(f"#   {d:<16} {c}{flag}")
        print()

    ids = []
    for f in sorted((ROOT / "alphas").rglob("*.alpha.yaml")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^alpha_id:\s*([A-Za-z][\w]*)", line)
            if m:
                ids.append(m.group(1))
                break
    print("ALPHA_IDS = [")
    for i in sorted(set(ids)):
        print(f'    "{i}",')
    print("]\n")

    stop = {"RTH", "NBBO", "USD", "MKT", "LMT", "STK", "OK", "ON", "OFF", "GTC",
            "DAY", "IOC", "FOK", "SIP", "UTC", "API", "URL", "CSV", "YAML", "ID"}
    freq = defaultdict(int)
    files = list((ROOT / "configs").rglob("*.y*ml")) if (ROOT / "configs").exists() else []
    if (ROOT / "platform.yaml").exists():
        files.append(ROOT / "platform.yaml")
    for f in files:
        for tok in re.findall(r"\b([A-Z]{1,5})\b", f.read_text(encoding="utf-8", errors="replace")):
            if tok not in stop:
                freq[tok] += 1
    print("# symbol candidates from configs/ + platform.yaml, by frequency:")
    print("SYMBOL_LITERALS = [")
    for tok, c in sorted(freq.items(), key=lambda x: -x[1])[:12]:
        print(f'    "{tok}",   # {c} references')
    print("]")


# Line ranges (``:86-88``) are matched too. Without the ``-\d+`` branch the whole
# citation failed to match and was silently skipped, so a range citation whose path
# did not resolve could never be reported -- a clean sample did not mean every
# citation resolved.
CITATION = re.compile(r"`([\w./\-]+\.py)(?::(\d+(?:-\d+)?|[A-Za-z_][\w]*))?`")


def cmd_spotcheck(args):
    """Sample citations from a phase output and verify they resolve."""
    # Accept Windows-style separators from PowerShell as well as POSIX ones.
    target = Path(str(args.file).replace("\\", "/"))
    if not target.is_absolute():
        target = ROOT / target
    if not target.exists():
        print(f"spotcheck: file not found: {target}")
        sys.exit(2)
    text = target.read_text(encoding="utf-8", errors="replace")
    cites = sorted(set(CITATION.findall(text)))
    if not cites:
        print("spotcheck: no path:symbol citations found. That is itself a finding.")
        return
    rng = random.Random(args.seed)
    sample = rng.sample(cites, min(args.n, len(cites)))
    failures = []
    for path, sym in sample:
        f = ROOT / path
        if not f.exists():
            failures.append((path, sym, "file missing"))
            continue
        if not sym:
            continue
        if re.fullmatch(r"\d+(?:-\d+)?", sym):
            # Both endpoints of a range must land inside the file.
            n_lines = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            bounds = [int(x) for x in sym.split("-")]
            if max(bounds) > n_lines:
                failures.append((path, sym, f"line beyond EOF ({n_lines} lines)"))
            elif len(bounds) == 2 and bounds[0] > bounds[1]:
                failures.append((path, sym, "inverted line range"))
        elif sym not in f.read_text(encoding="utf-8", errors="replace"):
            failures.append((path, sym, "symbol not found in file"))
    print(f"spotcheck: {len(cites)} distinct citations, sampled {len(sample)}, "
          f"{len(failures)} failure(s)")
    for p, s, why in failures:
        print(f"    FAIL {p}:{s}  ({why})")
    if failures:
        print("\n  VERDICT: phase output is UNTRUSTED. Re-run the phase.")
        sys.exit(1)
    print("  VERDICT: sample clean.")


def cmd_all(args):
    for fn in (cmd_modules, cmd_imports, cmd_clock, cmd_nondet, cmd_bus, cmd_handlers,
               cmd_gates, cmd_alphaleak):
        print()
        fn(args)
    print(f"\nevidence written to {rel(EVIDENCE)}/")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("all", "modules", "imports", "clock", "nondet", "bus", "handlers",
                 "gates", "alphaleak", "discover"):
        sp.add_parser(name)
    p = sp.add_parser("spotcheck")
    p.add_argument("file")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()
