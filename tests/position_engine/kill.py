"""Kill runner for the broken engines. A script: pytest does not collect it.

Usage: python tests/position_engine/kill.py [--shard A|B] [--only Bn] [--control]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.position_engine.mutants import REGISTRY, Mutant  # noqa: E402

_REFERENCE_ENGINE = "tests.position_engine.reference.engine.PositionEngine"
_REFERENCE_RAIL = "tests.position_engine.reference.rail.ReferenceRail"
_CLASSES = ("PROPERTY", "PRECONDITION", "NONVACUOUS", "CRASH", "TIMEOUT")


def classify(message: str, *, crashed: bool) -> str:
    """Census Q4. Only PROPERTY counts as a kill."""
    if crashed or "fresh child exited" in message:
        return "CRASH"
    if message.startswith("PRECONDITION:"):
        return "PRECONDITION"
    if message.startswith("NONVACUOUS:"):
        return "NONVACUOUS"
    return "PROPERTY"


def _node_id(case: ET.Element) -> str:
    name = case.get("name") or ""
    file = (case.get("file") or "").replace("\\", "/")
    if file:
        return f"{file}::{name}"
    classname = (case.get("classname") or "").replace(".", "/")
    return f"{classname}.py::{name}"


def _message_of(node: ET.Element) -> str:
    text = node.get("message") or (node.text or "")
    line = text.split("\n", 1)[0].strip()
    prefix = "AssertionError: "
    if line.startswith(prefix):
        line = line[len(prefix) :]
    return line


def _failures(path: Path) -> list[tuple[str, str, str]]:
    """(node id, class, message) for each failed or errored case."""
    if not path.exists() or path.stat().st_size == 0:
        return [("", "CRASH", "no junit")]
    root = ET.parse(path).getroot()
    cases = root.iter("testcase")
    found: list[tuple[str, str, str]] = []
    for case in cases:
        failure = case.find("failure")
        error = case.find("error")
        node = failure if failure is not None else error
        if node is None:
            continue
        message = _message_of(node)
        kind = node.get("type") or ""
        crashed = error is not None or (kind != "" and kind != "AssertionError")
        found.append((_node_id(case), classify(message, crashed=crashed), message))
    return found


def _child_env(spec: Mutant, stage_file: str, *, control: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["FEELIES_STAGE_FILE"] = stage_file
    env.pop("FEELIES_BROKER_TESTS", None)
    env.pop("FEELIES_NETWORK_TESTS", None)
    if control:
        env["FEELIES_ENGINE"] = _REFERENCE_ENGINE
        env["FEELIES_RAIL"] = _REFERENCE_RAIL
    elif spec.seam == "engine":
        env["FEELIES_ENGINE"] = spec.dotted
        env["FEELIES_RAIL"] = _REFERENCE_RAIL
    else:
        env["FEELIES_ENGINE"] = _REFERENCE_ENGINE
        env["FEELIES_RAIL"] = spec.dotted
    return env


def run_spec(spec: Mutant, *, timeout: float, control: bool) -> tuple[str, Counter[str], float]:
    """One fresh pytest process. Returns (line, counts, wall seconds)."""
    started = time.perf_counter()
    stage = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt")
    xml = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".xml")
    stage.write("E\n")
    stage.close()
    xml.close()
    command = [
        sys.executable,
        "-m",
        "pytest",
        *spec.tests,
        "-m",
        "not battery_real",
        "--junitxml",
        xml.name,
        "--maxfail=1",
        "-q",
        "--tb=line",
    ]
    counts: Counter[str] = Counter()
    try:
        try:
            subprocess.run(
                command,
                cwd=_ROOT,
                env=_child_env(spec, stage.name, control=control),
                timeout=timeout,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            counts["TIMEOUT"] = 1
            wall = time.perf_counter() - started
            return f"{spec.bid} SURVIVED (TIMEOUT 1)", counts, wall
        failures = _failures(Path(xml.name))
    finally:
        Path(stage.name).unlink(missing_ok=True)
        Path(xml.name).unlink(missing_ok=True)
    for _node, kind, _message in failures:
        counts[kind] += 1
    wall = time.perf_counter() - started
    if control:
        return "", counts, wall
    for node, kind, message in failures:
        if kind == "PROPERTY":
            prefix = message.split("\n", 1)[0][:160]
            return f"{spec.bid} KILLED by {node}: {prefix}", counts, wall
    rendered = ", ".join(f"{name} {counts[name]}" for name in _CLASSES if counts[name])
    if not rendered:
        rendered = "no failures"
    return f"{spec.bid} SURVIVED ({rendered})", counts, wall


def selected(
    argv: list[str], specs: list[Mutant] | None
) -> tuple[argparse.Namespace, list[Mutant]]:
    parser = argparse.ArgumentParser(description="Kill the broken engines.")
    parser.add_argument("--shard", choices=("A", "B"))
    parser.add_argument("--only")
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args(argv)
    rows = list(REGISTRY.values()) if specs is None else list(specs)
    if args.only:
        rows = [row for row in rows if row.bid == args.only]
        if not rows:
            parser.error(f"unknown mutant {args.only}")
    if args.shard:
        rows = [row for row in rows if row.shard == args.shard]
    return args, rows


def main(argv: list[str] | None = None, specs: list[Mutant] | None = None) -> int:
    args, rows = selected(sys.argv[1:] if argv is None else argv, specs)
    if not rows:
        print("no mutants selected")
        return 1
    if args.control:
        total: Counter[str] = Counter()
        for spec in rows:
            _line, counts, wall = run_spec(spec, timeout=args.timeout, control=True)
            total.update(counts)
            print(f"{spec.bid} wall {wall:.1f}s", file=sys.stderr, flush=True)
        failed = sum(total.values())
        print(f"CONTROL {failed} failures", flush=True)
        return 0 if failed == 0 else 1
    exit_code = 0
    for spec in rows:
        line, _counts, wall = run_spec(spec, timeout=args.timeout, control=False)
        print(line, flush=True)
        print(f"{spec.bid} wall {wall:.1f}s", file=sys.stderr, flush=True)
        if "KILLED by" not in line:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
