#!/usr/bin/env python3
"""
Execution baseline capture and comparison.

The parity manifest is the objective before/after oracle for every migration
step. This records it -- alongside git state, the test summary, and a fresh
measure.py evidence snapshot -- so "did this step change what it declared"
is answerable rather than asserted.

Usage:
    uv run python tools/exec/baseline.py capture --label pre
    uv run python tools/exec/baseline.py capture --label post-S-07 --skip-tests
    uv run python tools/exec/baseline.py compare --before <a.json> --after <b.json>
    uv run python tools/exec/baseline.py compare --before <a.json> --after <b.json> --parity-only

Captures land in docs/architecture/target/out/exec/baseline_<label>.json.

This tool NEVER writes to tests/ or src/. It reads and records only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXEC_TOOLS = Path(__file__).resolve().parent
OUT = ROOT / "docs" / "architecture" / "target" / "out" / "exec"
DETERMINISM = ROOT / "tests" / "determinism"

# The APP acceptance oracle pins the trade parity hash, the config-contract
# hash, net PnL and fill count. It sits outside tests/determinism/ and uses the
# _BASELINE_ prefix, so it has to be named here or it is never captured -- and
# S-16 declares _BASELINE_CONFIG_HASH as its re-pin target.
ACCEPTANCE = (ROOT / "tests" / "acceptance" / "test_backtest_app_baseline.py",)

# EXPECTED_LEVEL2_SIGNAL_HASH = "e3b0c442..."   /  EXPECTED_LEVEL2_SIGNAL_COUNT = 0
# Eleven manifest hashes wrap their value in parentheses on the following line,
# and _BASELINE_NET_PNL wraps it in Decimal(...), so the value is matched across
# an optional paren, newline and constructor call rather than same-line only.
CONST = re.compile(
    r"^(EXPECTED_\w+_(?:HASH|COUNT)|_BASELINE_[A-Z0-9_]+)"
    r"\s*(?::\s*[^=\n]+)?=\s*\(?\s*(?:[A-Za-z_][\w.]*\(\s*)?"
    r"(?:\"([^\"]+)\"|'([^']+)'|(\d+(?:\.\d+)?))",
    re.M,
)

# pytest -q summary: "4600 passed, 5 skipped, 43 deselected in 128.44s"
SUMMARY = re.compile(
    r"(?:(\d+) failed,\s*)?.*?(\d+) passed"
    r"(?:,\s*(\d+) skipped)?(?:,\s*(\d+) deselected)?(?:,\s*(\d+) error)?",
)


def run(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"


def git(*args: str) -> str:
    _, out = run(["git", *args])
    return out.strip()


def tools_fingerprint() -> dict:
    """Fingerprint the frozen oracle (``tools/exec/``) that produced a capture.

    X0 D2: a capture records the tool's fingerprint so ``compare`` can warn when
    two captures were taken by different tool versions -- "nothing moved" over a
    shrunken constant set (the documented 43 -> 62 blind spot) is not evidence
    that anything held.
    """
    h = hashlib.sha256()
    files = sorted(EXEC_TOOLS.rglob("*.py"))
    for p in files:
        h.update(p.relative_to(EXEC_TOOLS).as_posix().encode("utf-8") + b"\0")
        h.update(p.read_bytes() + b"\0")
    return {"sha256": h.hexdigest(), "files": len(files)}


def parity_constants() -> dict[str, str]:
    """Every pinned parity constant, by name.

    EXPECTED_*_HASH / _COUNT under tests/determinism/, plus the APP acceptance
    oracle's _BASELINE_* constants.
    """
    found: dict[str, str] = {}
    files = sorted(DETERMINISM.rglob("*.py")) if DETERMINISM.exists() else []
    files += [p for p in ACCEPTANCE if p.exists()]
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, dq, sq, num in CONST.findall(text):
            value = dq or sq or num
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            key = f"{rel}::{name}"
            found[key] = value
    return found


def test_summary(cmd: list[str]) -> dict:
    code, out = run(cmd)
    tail = "\n".join(out.strip().splitlines()[-15:])
    m = None
    for line in reversed(out.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            m = SUMMARY.search(line)
            if m:
                break
    d = {"command": " ".join(cmd), "exit_code": code, "tail": tail}
    if m:
        failed, passed, skipped, deselected, errors = m.groups()
        d.update({"failed": int(failed or 0), "passed": int(passed or 0),
                  "skipped": int(skipped or 0), "deselected": int(deselected or 0),
                  "errors": int(errors or 0)})
    else:
        d["parse"] = "FAILED -- could not read pytest summary"
    return d


def evidence_snapshot() -> dict:
    """Re-run measure.py if present; return its module/import counts."""
    mp = ROOT / "tools" / "arch" / "measure.py"
    if not mp.exists():
        return {"available": False}
    run([sys.executable, str(mp), "modules"])
    run([sys.executable, str(mp), "imports"])
    run([sys.executable, str(mp), "alphaleak"])
    ev = ROOT / "tools" / "arch" / "evidence"
    snap: dict = {"available": True}
    for name, keys in (("modules", ("total_files", "total_sloc")),
                       ("imports", ("n_modules", "n_edges")),
                       ("alphaleak", ("n",))):
        f = ev / f"{name}.json"
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            snap[name] = {k: data.get(k) for k in keys}
            if name == "modules":
                snap["modules"]["public_symbols"] = sum(
                    m.get("public_symbols", 0) for m in data.get("modules", []))
            if name == "imports":
                snap["imports"]["n_cycles"] = len(data.get("cycles", []))
    return snap


def cmd_capture(args):
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"==> capturing baseline '{args.label}'")

    print("    git state")
    payload = {
        "label": args.label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "tools_fingerprint": tools_fingerprint(),
        "git": {
            "sha": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
            "porcelain": git("status", "--porcelain").splitlines(),
        },
    }

    print("    parity constants")
    consts = parity_constants()
    payload["parity"] = consts
    payload["parity_count"] = len(consts)
    print(f"      {len(consts)} constants across {len({k.split('::')[0] for k in consts})} modules")

    if args.skip_tests:
        payload["tests"] = {"skipped_by_flag": True}
        print("    tests SKIPPED (--skip-tests)")
    else:
        print("    full suite (this takes a while)")
        payload["tests"] = test_summary(["uv", "run", "pytest", "-q"])
        t = payload["tests"]
        print(f"      {t.get('passed','?')} passed, {t.get('failed','?')} failed, "
              f"{t.get('skipped','?')} skipped, exit {t['exit_code']}")
        print("    determinism corpus")
        payload["determinism"] = test_summary(
            ["uv", "run", "pytest", "tests/determinism", "-q"])
        d = payload["determinism"]
        print(f"      {d.get('passed','?')} passed, {d.get('failed','?')} failed, "
              f"exit {d['exit_code']}")

    print("    evidence snapshot")
    payload["evidence"] = evidence_snapshot()

    dest = OUT / f"baseline_{args.label}.json"
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(f"\n    -> {dest.relative_to(ROOT)}")

    green = (payload.get("tests", {}).get("exit_code") == 0
             and payload.get("determinism", {}).get("exit_code", 0) == 0)
    if not args.skip_tests:
        print(f"\n    BASELINE: {'GREEN' if green else 'RED -- do not start execution'}")
        if not green:
            sys.exit(1)


def _load(p: str) -> dict:
    f = Path(str(p).replace("\\", "/"))
    if not f.is_absolute():
        f = ROOT / f
    if not f.exists():
        print(f"not found: {f}")
        sys.exit(2)
    return json.loads(f.read_text(encoding="utf-8"))


def cmd_compare(args):
    a, b = _load(args.before), _load(args.after)
    print(f"comparing '{a['label']}' -> '{b['label']}'\n")

    fa = a.get("tools_fingerprint", {}).get("sha256")
    fb = b.get("tools_fingerprint", {}).get("sha256")
    if fa != fb:
        print("  WARNING: captures taken by different tools/exec versions "
              f"({(fa or 'none')[:12]} -> {(fb or 'none')[:12]}) -- a hold over a "
              "changed constant set is not evidence (X0 D2). Re-capture both "
              "with the frozen oracle before trusting this comparison.\n")

    pa, pb = a.get("parity", {}), b.get("parity", {})
    moved = sorted(k for k in set(pa) & set(pb) if pa[k] != pb[k])
    added = sorted(set(pb) - set(pa))
    removed = sorted(set(pa) - set(pb))

    print("PARITY")
    print(f"  constants   {len(pa)} -> {len(pb)}")
    print(f"  changed     {len(moved)}")
    for k in moved:
        print(f"    ~ {k}")
        print(f"        before {pa[k][:16]}...  after {pb[k][:16]}...")
    for k in added:
        print(f"    + {k}")
    for k in removed:
        print(f"    - {k}")
    if not (moved or added or removed):
        print("  VERDICT: parity HOLDS -- no constant moved")
    else:
        print("  VERDICT: parity CHANGED -- every entry above must be DECLARED")

    if args.parity_only:
        sys.exit(1 if (moved or added or removed) else 0)

    print("\nTESTS")
    for key in ("tests", "determinism"):
        ta, tb = a.get(key, {}), b.get(key, {})
        if "passed" in ta and "passed" in tb:
            dp = tb["passed"] - ta["passed"]
            df = tb.get("failed", 0) - ta.get("failed", 0)
            flag = "  <-- REGRESSION" if tb.get("failed", 0) > ta.get("failed", 0) else ""
            print(f"  {key:<12} passed {ta['passed']} -> {tb['passed']} ({dp:+d}), "
                  f"failed {ta.get('failed',0)} -> {tb.get('failed',0)} ({df:+d}){flag}")
        else:
            print(f"  {key:<12} (not captured on one side)")

    print("\nEVIDENCE / NET DELTA")
    ea, eb = a.get("evidence", {}), b.get("evidence", {})
    for grp, keys in (("modules", ("total_files", "total_sloc", "public_symbols")),
                      ("imports", ("n_modules", "n_edges", "n_cycles")),
                      ("alphaleak", ("n",))):
        ga, gb = ea.get(grp, {}), eb.get(grp, {})
        for k in keys:
            va, vb = ga.get(k), gb.get(k)
            if isinstance(va, int) and isinstance(vb, int):
                print(f"  {grp}.{k:<16} {va} -> {vb} ({vb - va:+d})")

    print("\nGIT")
    print(f"  {a['git']['sha'][:10]} ({a['git']['branch']}) -> "
          f"{b['git']['sha'][:10]} ({b['git']['branch']})")

    sys.exit(1 if moved or added or removed else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("capture")
    c.add_argument("--label", required=True)
    c.add_argument("--skip-tests", action="store_true")
    d = sp.add_parser("compare")
    d.add_argument("--before", required=True)
    d.add_argument("--after", required=True)
    d.add_argument("--parity-only", action="store_true")
    args = ap.parse_args()
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()
