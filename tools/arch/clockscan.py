#!/usr/bin/env python3
"""
Complete wall-clock / monotonic-clock scan.  Stdlib only.

Why this exists as a separate script: `measure.py`'s CLOCK_CALLS list omits the
`_ns` variants of the perf counters, and its matcher compares only the final
dotted segment, so `time.perf_counter_ns()` matches neither `time.perf_counter`
nor `time.time_ns`.  The tick-critical path in
`src/feelies/kernel/orchestrator.py` calls `time.perf_counter_ns()`, so
evidence/clock.json under-reports wall-clock reads on exactly the path where
they matter most.  measure.py's CONFIG is frozen for the duration of the
review, so this scan is additive rather than an edit to it.

Classification: engines 1,2,3,4,6,7,8,9,10 are the tick-critical path per
CORE §D; engines 5, 11, 12 and the CLI are cold.

Writes evidence/clockscan.json.

Usage:
    python tools/arch/clockscan.py
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feelies"
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

# Final-segment names that read the machine clock outside the injected Clock.
CLOCK_LEAVES = {
    "time", "time_ns", "monotonic", "monotonic_ns",
    "perf_counter", "perf_counter_ns", "process_time", "process_time_ns",
    "thread_time", "thread_time_ns",
    "now", "utcnow", "today",
}

# Not clock reads: these convert a timestamp the caller already holds.  Tracked
# separately because a tz-dependent conversion is still a determinism question,
# but it is not a wall-clock read and must not inflate that count.
CONVERSION_LEAVES = {"fromtimestamp", "utcfromtimestamp"}

# Receivers that make a bare leaf name a genuine clock read.
CLOCK_RECEIVERS = {"time", "datetime", "date", "dt"}

# Package -> hot (on the tick-critical path) or cold, per CORE §D.
HOT_PACKAGES = {
    "ingestion", "storage", "sensors", "features", "services", "signals",
    "composition", "portfolio", "risk", "execution", "broker", "kernel", "bus", "core",
}
COLD_PACKAGES = {"harness", "research", "forensics", "cli", "monitoring", "promotion",
                 "alpha"}


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


def package_of(relpath: str) -> str:
    parts = relpath.split("/")
    return parts[2] if len(parts) > 3 else "(root)"


def main():
    hits = []
    for p in py_files(SRC):
        r = rel(p)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = dotted(n.func)
            if not name:
                continue
            segs = name.split(".")
            leaf = segs[-1]
            if leaf in CLOCK_LEAVES:
                kind = "clock_read"
            elif leaf in CONVERSION_LEAVES:
                kind = "timestamp_conversion"
            else:
                continue
            recv = segs[-2] if len(segs) > 1 else ""
            # `self._clock.now_ns()` is the injected abstraction, not a raw read.
            if recv in ("clock", "_clock", "session_clock", "_session_clock"):
                continue
            if len(segs) == 1:
                continue
            if recv not in CLOCK_RECEIVERS and leaf in ("now", "utcnow", "today",
                                                        "fromtimestamp",
                                                        "utcfromtimestamp"):
                # e.g. `datetime.now`, `date.today`; skip unrelated `.now()` on
                # domain objects unless the receiver is a datetime-ish name.
                if not any(t in recv.lower() for t in ("datetime", "date", "time")):
                    continue
            pkg = package_of(r)
            hits.append({
                "path": r, "line": n.lineno, "call": name, "package": pkg, "kind": kind,
                "tick_critical_package": pkg in HOT_PACKAGES,
                "text": lines[n.lineno - 1].strip()[:160] if n.lineno <= len(lines) else "",
            })

    reads = [h for h in hits if h["kind"] == "clock_read"]
    conversions = [h for h in hits if h["kind"] == "timestamp_conversion"]
    by_pkg = defaultdict(int)
    by_call = defaultdict(int)
    for h in reads:
        by_pkg[h["package"]] += 1
        by_call[h["call"]] += 1
    hot = [h for h in reads if h["tick_critical_package"]]

    # What measure.py's clock.json reported, for the delta.
    prior = EVIDENCE / "clock.json"
    prior_keys, prior_hits = set(), []
    if prior.exists():
        prior_hits = json.loads(prior.read_text(encoding="utf-8"))["hits"]
        for h in prior_hits:
            prior_keys.add((h["path"], h["line"]))
    missed = [h for h in reads if (h["path"], h["line"]) not in prior_keys]
    # The reverse delta: clock.json hits this scan does not classify as a clock
    # read.  `datetime.time(hour, minute)` is a constructor, not a clock read.
    mine = {(h["path"], h["line"]) for h in reads}
    false_pos = [h for h in prior_hits if (h["path"], h["line"]) not in mine]

    payload = {
        "hits": hits,
        "n": len(hits),
        "n_clock_reads": len(reads),
        "n_timestamp_conversions": len(conversions),
        "timestamp_conversions": conversions,
        "by_package": dict(sorted(by_pkg.items(), key=lambda x: -x[1])),
        "by_call": dict(sorted(by_call.items(), key=lambda x: -x[1])),
        "hot_package_hits": hot,
        "n_hot_package_hits": len(hot),
        "hot_packages": sorted(HOT_PACKAGES),
        "cold_packages": sorted(COLD_PACKAGES),
        "not_reported_by_measure_py_clock_json": missed,
        "n_not_reported_by_measure_py": len(missed),
        "measure_py_hits_not_clock_reads": false_pos,
        "n_measure_py_hits_not_clock_reads": len(false_pos),
        "measure_py_clock_json_total": len(prior_hits),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "clockscan.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"clockscan: {len(reads)} raw clock reads "
          f"(+{len(conversions)} timestamp conversions) -> {rel(out)}")
    print(f"  by call: {dict(list(payload['by_call'].items())[:10])}")
    print(f"  clock reads in tick-critical packages: {len(hot)}")
    print(f"  clock reads MISSED by evidence/clock.json: {len(missed)}")
    for h in missed:
        print(f"      {h['path']}:{h['line']}  {h['call']}()   {h['text'][:80]}")
    print(f"  clock.json hits that are NOT clock reads: {len(false_pos)} "
          f"of {len(prior_hits)}")
    for h in false_pos:
        print(f"      {h['path']}:{h['line']}  {h['call']}")


if __name__ == "__main__":
    main()
