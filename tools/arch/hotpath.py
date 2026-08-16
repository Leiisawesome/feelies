#!/usr/bin/env python3
"""Phase 4 (Axis E) hot-path allow-list and dead-computation scanner.

Standard library only.  Writes ``tools/arch/evidence/hotpath.json``.

WHAT MAKES A VIOLATION A VIOLATION
----------------------------------
A prohibited construct in ``src/feelies/`` is only a hot-path violation if the
function containing it actually runs on the tick-critical path.  A static grep
cannot tell the difference, so this tool intersects two measurements:

* the **executed set** -- every function in ``src/feelies/`` that cProfile
  observed during ``Orchestrator.run_backtest()``, produced by
  ``perfmeasure.py --mode profile`` into ``evidence/hotpath_executed.json``;
* the **static set** -- an AST scan of every function in ``src/feelies/``.

Only the intersection is reported as a hot-path violation.  Everything else is
reported as ``cold`` and is not a finding for this axis.

MATCHING CAVEAT, stated because it bounds the numbers: cProfile keys code
objects by ``(file, first line, bare function name)``.  Where two functions in
one module share a bare name (``update`` on two sensor classes, say), a
name-only match cannot tell them apart.  The scan therefore reports
``matched_exact`` (file + name + line agree) separately from
``matched_name_only``, and the hot set is the union -- which errs toward
flagging, never toward silence.

Usage:

    uv run python tools/arch/perfmeasure.py --mode profile   # first
    uv run python tools/arch/hotpath.py
    uv run python tools/arch/hotpath.py --report
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"
EXECUTED = EVIDENCE / "hotpath_executed.json"

# --------------------------------------------------------------------------
# Prohibition set.  The first six are named by P4; the rest extend it.
# Each entry: id -> (human label, why it is prohibited on the tick path)
# --------------------------------------------------------------------------

PROHIBITIONS: dict[str, tuple[str, str]] = {
    "logging_with_formatting": (
        "logging call that formats or interpolates",
        "P4-named. Builds a message and an args tuple per event even when the "
        "level is disabled, unless the call is guarded.",
    ),
    "per_event_dict_construction": (
        "dict literal / dict comprehension / dict() per event",
        "P4-named. Allocation per event; feeds the GC the harness has to "
        "disable to keep latency stable.",
    ),
    "dynamic_dispatch": (
        "getattr / hasattr / setattr / vars / deferred import",
        "P4-named. Name-resolved dispatch defeats the type-level contract and "
        "makes an absent attribute a silent no-op rather than an error.",
    ),
    "governance_evaluation": (
        "reference to promotion / lifecycle / gate-matrix machinery",
        "P4-named and CORE C.10. Whether an alpha is live is resolved at "
        "composition and must never be re-evaluated per event.",
    ),
    "disk_io": (
        "filesystem read/write/stat/glob",
        "P4-named. Unbounded, host-dependent latency inside a synchronous "
        "dispatch that has no queue to absorb it.",
    ),
    "serialization": (
        "json / pickle / hashing / encode / asdict",
        "P4-named. Cost is proportional to payload size and is only ever "
        "needed off the decision path.",
    ),
    # ---- extensions -----------------------------------------------------
    "string_formatting": (
        "f-string, %-format, .format(), .join() outside a logging call",
        "Extension. Builds a string per event for a value that is usually "
        "discarded; the correlation-id and reason-tuple paths are the "
        "measured carriers.",
    ),
    "per_event_set_construction": (
        "set literal / set comprehension / set() / frozenset() per event",
        "Extension. Allocation plus, per Phase 1 budget row 3, a "
        "hash-ordered iteration whose order is seed-dependent.",
    ),
    "sorting": (
        "sorted() / list.sort() per event",
        "Extension. O(n log n) per event; also the determinism neutralizer "
        "for rows 2a/3, so it may not simply be deleted -- it must move to "
        "the producer.",
    ),
    "deep_copy": (
        "copy.copy / copy.deepcopy",
        "Extension. Unbounded in the size of the copied graph.",
    ),
    "dataclass_replace": (
        "dataclasses.replace() per event",
        "Extension. Full field re-construction of a frozen event to change one field.",
    ),
    "wall_clock_read": (
        "time.* / datetime.now on the tick path",
        "Extension. Phase 1 budget row 7: the allowlist is file-granular, so "
        "a call-granular census is the only way to know the real count.",
    ),
    "regex": (
        "re.compile / match / search / sub / findall",
        "Extension. Pattern work per event, usually on a string that was itself built per event.",
    ),
    "transcendental": (
        "math.log / exp / sqrt / pow and friends",
        "Extension, and NOT prohibited -- declared allowed with a stated "
        "cost, because Phase 1 row 12a makes libm the reason whole-platform "
        "parity is host-local. Counted so the allow list is honest.",
    ),
    "decimal_arithmetic": (
        "Decimal() construction",
        "Extension, and NOT prohibited -- declared allowed. Money is Decimal "
        "end to end and that is what makes P&L reductions order-free "
        "(Phase 1 budget row 4).",
    ),
}

ALLOWED_NOT_PROHIBITED = {"transcendental", "decimal_arithmetic"}

_LOG_LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_FS_ATTRS = {
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "mkdir",
    "rglob",
    "glob",
    "iterdir",
    "unlink",
    "rmdir",
    "touch",
    "stat",
    "exists",
    "is_file",
    "is_dir",
    "resolve",
    "listdir",
    "scandir",
    "makedirs",
    "remove",
}
_SER_ATTRS = {"dumps", "dump", "loads", "load", "asdict", "astuple", "hexdigest", "digest"}
_SER_MODS = {"json", "pickle", "hashlib", "marshal", "base64", "csv"}
_HASH_FUNCS = {"sha256", "sha1", "sha512", "md5", "blake2b", "blake2s"}
_CLOCK_ATTRS = {
    "time",
    "time_ns",
    "monotonic",
    "monotonic_ns",
    "perf_counter",
    "perf_counter_ns",
    "now",
    "utcnow",
    "today",
    "process_time",
}
_MATH_ATTRS = {
    "log",
    "log1p",
    "log2",
    "log10",
    "exp",
    "expm1",
    "sqrt",
    "pow",
    "erf",
    "erfc",
    "sin",
    "cos",
    "tan",
    "atan",
    "atan2",
    "gamma",
    "lgamma",
}
_GOV_TOKENS = (
    "promotion",
    "lifecycle",
    "quarantin",
    "gate_matrix",
    "promote",
    "promotion_ledger",
    "evidence",
)
_DYNAMIC_FUNCS = {
    "getattr",
    "setattr",
    "hasattr",
    "delattr",
    "vars",
    "globals",
    "locals",
    "eval",
    "exec",
    "__import__",
}


class FnScan(ast.NodeVisitor):
    """Collect prohibition hits inside one function body.

    Two things this does that a grep cannot, and without which the counts are
    not evidence:

    **Guard tracking.** A hit is recorded as ``unconditional`` only if it is
    reached on every call -- not inside an ``if``, loop, ``except``, ternary, or
    the right-hand side of a short-circuit.  ``horizon_windowed.py:202`` is an
    f-string in an ``if i >= len(v_raw):`` error branch; calling the enclosing
    function 15 times per quote does not make that f-string run 15 times per
    quote, and reporting it as a per-event cost would be wrong.  Combined with
    the measured call rate, ``unconditional`` + ``per_event`` is the only
    combination that *proves* a per-event cost.

    **Nested-scope attribution.** Comprehension bodies count against the
    enclosing function (they run when it runs), but a nested ``def``/``lambda``
    body is marked conditional -- defining a closure is not calling it.
    """

    def __init__(self) -> None:
        self.hits: dict[str, list[tuple[int, bool]]] = defaultdict(list)
        self._in_logging_call = 0
        self._cond = False

    def _hit(self, kind: str, node: ast.AST) -> None:
        self.hits[kind].append((getattr(node, "lineno", 0), not self._cond))

    # -- guard-aware statement walk ---------------------------------------
    def walk_body(self, stmts: list[ast.stmt], *, cond: bool) -> None:
        """Walk a statement list, degrading to conditional after an early exit.

        ``_process_tick_inner`` is 500 lines of ``if ...: return`` guards.  A
        statement at its top level is not nested inside an ``if``, but it is
        still only reached when no earlier guard fired -- ``orchestrator.py:2067``
        sits on the order-submitted path, which the census measures at 21 orders
        against 82,678 quotes.  So once a preceding sibling contains a ``return``
        or ``raise`` at any depth, everything after it is conditional.
        """
        prev, self._cond = self._cond, self._cond or cond
        for stmt in stmts:
            self.walk_stmt(stmt)
            if not self._cond and _may_exit(stmt):
                self._cond = True
        self._cond = prev

    def walk_stmt(self, node: ast.stmt) -> None:
        if isinstance(node, ast.If):
            self.visit(node.test)
            self.walk_body(node.body, cond=True)
            self.walk_body(node.orelse, cond=True)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.visit(node.iter)
            self.walk_body(node.body, cond=True)
            self.walk_body(node.orelse, cond=True)
        elif isinstance(node, ast.While):
            self.visit(node.test)
            self.walk_body(node.body, cond=True)
            self.walk_body(node.orelse, cond=True)
        elif isinstance(node, ast.Try):
            # The try body runs; the handlers and else are conditional.
            self.walk_body(node.body, cond=False)
            for handler in node.handlers:
                self.walk_body(handler.body, cond=True)
            self.walk_body(node.orelse, cond=True)
            self.walk_body(node.finalbody, cond=False)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.visit(item.context_expr)
            self.walk_body(node.body, cond=False)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.walk_body(node.body, cond=True)
        elif isinstance(node, ast.Match):
            self.visit(node.subject)
            for case in node.cases:
                self.walk_body(case.body, cond=True)
        else:
            self.generic_visit(node)

    # -- conditional expression forms -------------------------------------
    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        prev, self._cond = self._cond, True
        self.visit(node.body)
        self.visit(node.orelse)
        self._cond = prev

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if node.values:
            self.visit(node.values[0])
        prev, self._cond = self._cond, True
        for value in node.values[1:]:
            self.visit(value)
        self._cond = prev

    def visit_Lambda(self, node: ast.Lambda) -> None:
        prev, self._cond = self._cond, True
        self.visit(node.body)
        self._cond = prev

    # -- calls ----------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = (
            f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        )
        root = ""
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            root = f.value.id
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute):
            root = f.value.attr

        is_logging = name in _LOG_LEVELS and ("log" in root.lower() or root == "self")
        if is_logging:
            formats = len(node.args) > 1 or any(isinstance(a, ast.JoinedStr) for a in node.args)
            if formats:
                self._hit("logging_with_formatting", node)
            self._in_logging_call += 1

        if name in _DYNAMIC_FUNCS:
            self._hit("dynamic_dispatch", node)
        if name == "dict":
            self._hit("per_event_dict_construction", node)
        if name in {"set", "frozenset"}:
            self._hit("per_event_set_construction", node)
        if name == "sorted" or (isinstance(f, ast.Attribute) and name == "sort"):
            self._hit("sorting", node)
        if name == "open" or name in _FS_ATTRS:
            self._hit("disk_io", node)
        if name in _HASH_FUNCS or (name in _SER_ATTRS and root in _SER_MODS | {"", "self"}):
            self._hit("serialization", node)
        if name in {"encode", "decode"} and root not in {"", "self"}:
            self._hit("serialization", node)
        if root in {"copy"} and name in {"copy", "deepcopy"}:
            self._hit("deep_copy", node)
        if name == "replace" and (isinstance(f, ast.Name) or root in {"dataclasses", "dc"}):
            self._hit("dataclass_replace", node)
        if name in _CLOCK_ATTRS and root in {"time", "datetime", "date"}:
            self._hit("wall_clock_read", node)
        if root == "re" and name in {"compile", "match", "search", "sub", "findall", "fullmatch"}:
            self._hit("regex", node)
        if root == "math" and name in _MATH_ATTRS:
            self._hit("transcendental", node)
        if name == "Decimal":
            self._hit("decimal_arithmetic", node)
        if name == "format" and isinstance(f, ast.Attribute):
            self._hit("string_formatting", node)
        if name == "join" and isinstance(f, ast.Attribute) and not self._in_logging_call:
            self._hit("string_formatting", node)
        if any(tok in name.lower() for tok in _GOV_TOKENS):
            self._hit("governance_evaluation", node)

        self.generic_visit(node)
        if is_logging:
            self._in_logging_call -= 1

    # -- literals and comprehensions ------------------------------------
    def visit_Dict(self, node: ast.Dict) -> None:
        # ``{}`` counts.  ``orchestrator.py:1525`` allocates an empty dict per
        # tick to hold the timing attribution, and an empty dict literal is a
        # real allocation -- CPython interns ``()`` but not ``{}``.
        self._hit("per_event_dict_construction", node)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._hit("per_event_dict_construction", node)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        self._hit("per_event_set_construction", node)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._hit("per_event_set_construction", node)
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        if not self._in_logging_call:
            self._hit("string_formatting", node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if (
            isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            if not self._in_logging_call:
                self._hit("string_formatting", node)
        self.generic_visit(node)

    # -- deferred imports ------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        self._hit("dynamic_dispatch", node)
        for alias in node.names:
            if any(tok in alias.name.lower() for tok in _GOV_TOKENS):
                self._hit("governance_evaluation", node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._hit("dynamic_dispatch", node)
        if node.module and any(tok in node.module.lower() for tok in _GOV_TOKENS):
            self._hit("governance_evaluation", node)
        self.generic_visit(node)


def _may_exit(stmt: ast.stmt) -> bool:
    """True if this statement can end the call before the next sibling runs.

    Nested function bodies are skipped -- a ``return`` inside a closure exits the
    closure, not the function that defines it.
    """
    if isinstance(stmt, (ast.Return, ast.Raise)):
        return True
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return False
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, ast.stmt) and _may_exit(child):
            return True
        if isinstance(child, ast.excepthandler):
            if any(_may_exit(s) for s in child.body):
                return True
    return False


def _band(calls_per_quote: float) -> str:
    """Bucket a measured call rate.

    A dict literal in a function called once per run is not a per-event
    allocation, and reporting it as one would be dishonest.  ``per_event`` means
    the containing function was measured at >= 0.5 calls per quote; ``frequent``
    at >= 0.01; ``rare`` below that -- which is where once-per-run setup,
    end-of-day reporting, and per-fill paths land.
    """
    if calls_per_quote >= 0.5:
        return "per_event"
    if calls_per_quote >= 0.01:
        return "frequent"
    return "rare"


def _iter_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    out: list[Any] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out


def _load_executed() -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    if not EXECUTED.exists():
        raise SystemExit(
            f"missing {EXECUTED.relative_to(ROOT).as_posix()} -- run:\n"
            "  uv run python tools/arch/perfmeasure.py --mode profile"
        )
    blob = json.loads(EXECUTED.read_text(encoding="utf-8"))
    prof = blob["profile"]
    by_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in prof["executed"].values():
        by_name[(rec["file"], rec["func"])].append(rec)
    return by_name, {
        "n_quotes": prof["n_quotes"],
        "parity_hash": prof["parity_hash"],
        "n_executed_functions": prof["n_executed_functions"],
    }


def _resolve(candidates: list[dict[str, Any]], def_line: int) -> tuple[dict[str, Any] | None, str]:
    """Pick the profile record for one ``def``, by line, never by call count.

    cProfile reports ``co_firstlineno``, which is the ``def`` line for an
    undecorated function and the first decorator line for a decorated one, so an
    exact match is tried first and then the nearest record within 4 lines.  If
    nothing lands in that window the function is treated as not executed rather
    than matched to a same-named sibling: attributing one function's call count
    to another is worse than missing it.
    """
    if not candidates:
        return None, "none"
    for rec in candidates:
        if int(rec["line"]) == def_line:
            return rec, "exact"
    near = min(candidates, key=lambda r: abs(int(r["line"]) - def_line))
    if abs(int(near["line"]) - def_line) <= 4:
        return near, "near"
    return None, "unmatched_sibling"


def scan() -> dict[str, Any]:
    executed, prof_meta = _load_executed()

    hot_functions: dict[str, dict[str, Any]] = {}
    cold_counts: dict[str, int] = defaultdict(int)
    hot_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    match_modes: dict[str, int] = defaultdict(int)
    n_functions = 0

    for path in sorted(SRC.rglob("*.py")):
        rel_src = path.relative_to(SRC.parent).as_posix()  # feelies/...
        rel_repo = path.relative_to(ROOT).as_posix()  # src/feelies/...
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for fn in _iter_functions(tree):
            n_functions += 1
            rec, match = _resolve(executed.get((rel_src, fn.name), []), fn.lineno)
            scanner = FnScan()
            scanner.walk_body(fn.body, cond=False)
            if rec is None:
                match_modes[match] += 1
                for kind, hits in scanner.hits.items():
                    cold_counts[kind] += len(hits)
                continue
            match_modes[match] += 1
            key = f"{rel_repo}:{fn.lineno}:{fn.name}"
            ncalls = int(rec["ncalls"]) if rec else 0
            rate = ncalls / prof_meta["n_quotes"] if prof_meta["n_quotes"] else 0.0
            hot_functions[key] = {
                "file": rel_repo,
                "func": fn.name,
                "def_line": fn.lineno,
                "profile_line": rec["line"] if rec else None,
                "match": match,
                "ncalls": ncalls,
                "calls_per_quote": round(rate, 5),
                "band": _band(rate),
                "hits": {k: len(v) for k, v in sorted(scanner.hits.items())},
            }
            for kind, hits in scanner.hits.items():
                merged: dict[int, bool] = {}
                for line, unconditional in hits:
                    merged[line] = merged.get(line, False) or unconditional
                for line in sorted(merged):
                    hot_hits[kind].append(
                        {
                            "site": f"{rel_repo}:{line}",
                            "func": fn.name,
                            "ncalls": ncalls,
                            "calls_per_quote": round(rate, 5),
                            "band": _band(rate),
                            "unconditional": merged[line],
                        }
                    )

    summary: dict[str, Any] = {}
    for kind, (label, why) in PROHIBITIONS.items():
        sites = hot_hits.get(kind, [])
        proven = [s for s in sites if s["band"] == "per_event" and s["unconditional"]]
        summary[kind] = {
            "label": label,
            "why": why,
            "status": "allowed" if kind in ALLOWED_NOT_PROHIBITED else "prohibited",
            "hot_sites": len(sites),
            "hot_functions": len({s["func"] for s in sites}),
            # proven == reached on EVERY call of a function measured at >= 0.5
            # calls/quote.  This is the only count that is a per-event cost.
            "proven_per_event_sites": len(proven),
            "per_event_sites": sum(1 for s in sites if s["band"] == "per_event"),
            "frequent_sites": sum(1 for s in sites if s["band"] == "frequent"),
            "rare_sites": sum(1 for s in sites if s["band"] == "rare"),
            "guarded_sites": sum(1 for s in sites if not s["unconditional"]),
            "cold_sites": cold_counts.get(kind, 0),
            "proven_sites": sorted(proven, key=lambda s: -s["ncalls"]),
            "top_sites": sorted(sites, key=lambda s: -s["ncalls"])[:14],
        }

    return {
        "measurement": {
            "tool": "tools/arch/hotpath.py",
            "executed_set_from": EXECUTED.relative_to(ROOT).as_posix(),
            "n_functions_in_src": n_functions,
            "n_hot_functions": len(hot_functions),
            "match_modes": dict(sorted(match_modes.items())),
            **prof_meta,
        },
        "prohibitions": summary,
        "hot_functions": hot_functions,
    }


# --------------------------------------------------------------------------
# Dead computation (P4 section 6)
# --------------------------------------------------------------------------


def dead_compute() -> dict[str, Any]:
    """Find computed-but-unread surface.

    Four measures, each with a stated false-positive mode:

    1.  event dataclass fields never read anywhere in ``src/feelies`` outside
        their own class body.  False positive: a field read only by ``tests/``
        or reached via ``getattr``.
    2.  metric names **observed being recorded during a real replay** (from
        ``evidence/perf_census.json``, since most ``MetricEvent``s pass
        ``name=name`` and no AST scan can resolve them), cross-referenced
        against readers in ``src/`` and in ``tests/`` separately.  A name read
        only by a test is computed on the tick path for nobody.
    3.  public methods on ``src/feelies`` classes with zero call sites by name
        anywhere in ``src/feelies``.  False positive: protocol methods invoked
        through an interface, and anything called from ``tests/`` or ``scripts/``.
    4.  the inverse of 2: names the reporting layer *reads* that the replay
        never recorded -- a permanently-``None`` read.
    """
    texts: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        texts[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    all_text = "\n".join(texts.values())
    # ``scripts/`` is a first-class caller -- run_paper.py drives the whole
    # PaperSessionRecorder API -- so it belongs in the non-src corpus, not in the
    # deletion list.
    tests_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for root in (ROOT / "tests", ROOT / "scripts")
        for p in sorted(root.rglob("*.py"))
    )

    # -- 1. unread event fields -------------------------------------------
    events_path = "src/feelies/core/events.py"
    tree = ast.parse(texts[events_path])
    unread_fields: list[dict[str, Any]] = []
    dynamic_reads: list[dict[str, Any]] = []
    n_fields = 0
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            field = stmt.target.id
            if field.startswith("_"):
                continue
            n_fields += 1
            attr_reads = all_text.count(f".{field}")
            # A field can also be read by name.  regime_gate.py:358 fetches
            # RegimeState.discriminability as getattr(regime, "discriminability",
            # float("inf")), which no attribute-syntax scan can see -- and which
            # is itself a finding, since the default disables the check.
            name_reads = all_text.count(f'"{field}"') + all_text.count(f"'{field}'")
            if attr_reads == 0 and name_reads == 0:
                unread_fields.append(
                    {
                        "event": node.name,
                        "field": field,
                        "site": f"{events_path}:{stmt.lineno}",
                        "read_by": "nothing",
                    }
                )
            elif attr_reads == 0:
                dynamic_reads.append(
                    {
                        "event": node.name,
                        "field": field,
                        "site": f"{events_path}:{stmt.lineno}",
                        "name_literal_sites_in_src": name_reads,
                    }
                )

    # -- 2. metric names recorded during replay, vs their readers ----------
    import re

    census_path = EVIDENCE / "perf_census.json"
    metric_rows: list[dict[str, Any]] = []
    dead_reads: list[dict[str, Any]] = []
    if census_path.exists():
        census = json.loads(census_path.read_text(encoding="utf-8"))["census"]
        n_quotes = census["n_quotes"]
        for key, count in census["metric_by_name"].items():
            bare = key.split(".", 1)[1]
            src_reads = len(re.findall(rf'"{re.escape(bare)}"', all_text))
            # the recording site itself matches; a reader is any additional site
            recorded_here = len(re.findall(rf'name="{re.escape(bare)}"', all_text))
            metric_rows.append(
                {
                    "metric": key,
                    "records_in_replay": count,
                    "records_per_quote": round(count / n_quotes, 4),
                    "name_sites_in_src": src_reads,
                    "literal_record_sites_in_src": recorded_here,
                    "read_by_src": src_reads - recorded_here > 0,
                    "read_by_tests": bool(re.search(rf'"{re.escape(bare)}"', tests_text)),
                }
            )
        read_pairs = set(re.findall(r'get_summary\(\s*"([^"]+)",\s*"([^"]+)"', all_text))
        recorded_keys = set(census["metric_by_name"])
        for layer, name in sorted(read_pairs):
            if f"{layer}.{name}" not in recorded_keys and layer in {"kernel", "signal", "risk"}:
                dead_reads.append({"read": f"{layer}.{name}"})
    unread_metrics = [r["metric"] for r in metric_rows if not r["read_by_src"]]

    # -- 3. public methods with no call site by name ----------------------
    zero_call_methods: list[dict[str, Any]] = []
    n_public_methods = 0
    n_properties = 0
    for rel, text in texts.items():
        try:
            t = ast.parse(text)
        except SyntaxError:
            continue
        for cls in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name.startswith("_"):
                    continue
                n_public_methods += 1
                # A @property is read as ``x.name``, not ``x.name(``.  Counting
                # only call syntax reports every property accessor in the repo as
                # uncalled, which is how this measure produced 132 false hits
                # before the decorator was taken into account.
                is_property = any(
                    (isinstance(d, ast.Name) and d.id in {"property", "cached_property"})
                    or (isinstance(d, ast.Attribute) and d.attr in {"property", "cached_property"})
                    for d in fn.decorator_list
                )
                if is_property:
                    n_properties += 1
                    calls = all_text.count(f".{fn.name}") - 1  # minus the def itself
                else:
                    calls = all_text.count(f".{fn.name}(")
                if calls <= 0:
                    # Called nowhere in src.  Splitting on whether tests call it
                    # separates "reached only through a protocol, exercised by a
                    # test" from "nothing anywhere refers to this at all" -- only
                    # the second is a deletion candidate worth an operator's time.
                    probe = f".{fn.name}" if is_property else f".{fn.name}("
                    # Reached by name instead of by syntax: getattr(engine,
                    # "refresh_high_water_mark", None).  These are live code that
                    # no static tool can see -- the reason the dynamic-dispatch
                    # prohibition is about analyzability, not nanoseconds.
                    by_name = f'"{fn.name}"' in all_text
                    zero_call_methods.append(
                        {
                            "cls": cls.name,
                            "method": fn.name,
                            "site": f"{rel}:{fn.lineno}",
                            "kind": "property" if is_property else "method",
                            "called_by_tests": probe in tests_text,
                            "reached_by_name_literal": by_name,
                        }
                    )

    return {
        "unread_event_fields": {
            "n_fields_scanned": n_fields,
            "n_unread": len(unread_fields),
            "fields": unread_fields,
            "n_read_only_by_name_literal": len(dynamic_reads),
            "read_only_by_name_literal": dynamic_reads,
        },
        "metric_names_recorded_never_read": {
            "n_recorded": len(metric_rows),
            "n_unread": len(unread_metrics),
            "names": unread_metrics,
            "rows": metric_rows,
            "read_but_never_recorded": dead_reads,
        },
        "public_methods_zero_call_sites_in_src": {
            "n_public_methods": n_public_methods,
            "n_properties": n_properties,
            "n_zero_call": len(zero_call_methods),
            "n_zero_call_anywhere": sum(1 for m in zero_call_methods if not m["called_by_tests"]),
            "methods": zero_call_methods,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true", help="print tables from the evidence file")
    args = ap.parse_args(argv)

    dest = EVIDENCE / "hotpath.json"
    if args.report:
        data = json.loads(dest.read_text(encoding="utf-8"))
    else:
        data = scan()
        data["dead_compute"] = dead_compute()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote {dest.relative_to(ROOT).as_posix()}", flush=True)

    m = data["measurement"]
    print(
        f"\nhot scope: {m['n_hot_functions']} of {m['n_functions_in_src']} functions in "
        f"src/feelies executed inside run_backtest; match modes {m['match_modes']}"
    )
    print(
        f"{'prohibition':30s} {'status':10s} {'PROVEN':>7} {'per-ev':>7} "
        f"{'freq':>6} {'rare':>6} {'guarded':>8} {'cold':>6}"
    )
    for kind, v in data["prohibitions"].items():
        print(
            f"{kind[:30]:30s} {v['status']:10s} {v['proven_per_event_sites']:7d} "
            f"{v['per_event_sites']:7d} {v['frequent_sites']:6d} {v['rare_sites']:6d} "
            f"{v['guarded_sites']:8d} {v['cold_sites']:6d}"
        )

    dc = data.get("dead_compute")
    if dc:
        print(
            f"\ndead compute: {dc['unread_event_fields']['n_unread']} unread event fields of "
            f"{dc['unread_event_fields']['n_fields_scanned']}; "
            f"{dc['metric_names_recorded_never_read']['n_unread']} unread metric names of "
            f"{dc['metric_names_recorded_never_read']['n_recorded']}; "
            f"{dc['public_methods_zero_call_sites_in_src']['n_zero_call']} public methods with "
            f"zero in-src call sites of "
            f"{dc['public_methods_zero_call_sites_in_src']['n_public_methods']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
