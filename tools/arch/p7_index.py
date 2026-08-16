"""Index Phase 5 gaps and Phase 6 tests so Phase 7's plan can be checked mechanically.

Emits tools/arch/evidence/p7_index.json with:
  gaps    : gap id -> {severity, engine_axis, invariant}
  tests    : test id -> {name, path, fails_today, wave, gaps_named}
  gap_to_tests : gap id -> [test ids that name it]
  unmapped  : gap ids named by no test

Phase 7 uses this to assert that every gap has a step and that the conformance
tests a step depends on exist in Phase 6. Read-only over docs/.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "architecture" / "target" / "out"
EVIDENCE = Path(__file__).resolve().parent / "evidence"

SECTION_PREFIX = {"5.1": "S", "5.2": "R", "5.3": "C", "5.4": "X", "5.5": "H", "5.6": "A"}
GAP_RE = re.compile(r"\bG[0-9]{2}\b")
FENCE = "`" * 3


def parse_gaps(text: str) -> dict[str, dict[str, str]]:
    gaps: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("| G"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        gid = cells[0]
        if not re.fullmatch(r"G[0-9]{2}", gid):
            continue
        # Cells 4..6 (evidence, invariant, severity) can themselves contain a
        # pipe inside a backticked regex, so index severity from the right.
        gaps[gid] = {
            "engine_axis": cells[1],
            "invariant": re.sub(r"\*\*", "", cells[-3]),
            "severity": re.sub(r"\*\*", "", cells[-2]),
            "blast_radius": cells[-1][:120],
        }
    return gaps


def parse_tests(text: str) -> dict[str, dict[str, object]]:
    start = text.index("## 5. Per-test specifications")
    end = text.index("## 6. Build order")
    section = text[start:end]
    parts = re.split(r"^### (5\.[0-9])[^\n]*$", section, flags=re.M)
    tests: dict[str, dict[str, object]] = {}
    for i in range(1, len(parts), 2):
        prefix = SECTION_PREFIX[parts[i]]
        blocks = re.findall(FENCE + r"\n(.*?)" + FENCE, parts[i + 1], flags=re.S)
        for n, block in enumerate(blocks, 1):
            name_m = re.search(r"TEST:\s*(\S+)\n(?:\s+(\S+))?", block)
            fails_m = re.search(r"FAILS TODAY:\s*(\w+)", block)
            wave_m = re.search(r"BUILD ORDER:\s*([0-9]+)", block)
            tests[f"{prefix}{n}"] = {
                "name": name_m.group(1) if name_m else "",
                "path": (name_m.group(2) or "") if name_m else "",
                "fails_today": fails_m.group(1) if fails_m else "unknown",
                "wave": int(wave_m.group(1)) if wave_m else None,
                "gaps_named": sorted(set(GAP_RE.findall(block))),
            }
    return tests


def main() -> None:
    gaps = parse_gaps((OUT / "phase5_gaps.md").read_text(encoding="utf-8"))
    tests = parse_tests((OUT / "phase6_conformance.md").read_text(encoding="utf-8"))

    gap_to_tests: dict[str, list[str]] = {g: [] for g in gaps}
    for tid, t in tests.items():
        for g in t["gaps_named"]:  # type: ignore[union-attr]
            gap_to_tests.setdefault(g, []).append(tid)

    payload = {
        "gaps": gaps,
        "gap_count": len(gaps),
        "tests": tests,
        "test_count": len(tests),
        "gap_to_tests": gap_to_tests,
        "unmapped": sorted(g for g, ts in gap_to_tests.items() if not ts and g in gaps),
        "severity_counts": {
            s: sum(1 for g in gaps.values() if g["severity"] == s)
            for s in sorted({g["severity"] for g in gaps.values()})
        },
        "tests_by_wave": {
            str(w): sorted(
                (tid for tid, t in tests.items() if t["wave"] == w),
                key=lambda x: (x[0], int(x[1:])),
            )
            for w in sorted({t["wave"] for t in tests.values() if t["wave"] is not None})
        },
        "fails_today_counts": {
            v: sum(1 for t in tests.values() if t["fails_today"] == v)
            for v in sorted({str(t["fails_today"]) for t in tests.values()})
        },
    }

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "p7_index.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"gaps={payload['gap_count']} tests={payload['test_count']}")
    print(f"severity={payload['severity_counts']}")
    print(f"fails_today={payload['fails_today_counts']}")
    print(f"unmapped_gaps={payload['unmapped']}")
    for w, ts in payload["tests_by_wave"].items():
        print(f"wave {w}: {' '.join(ts)}")


if __name__ == "__main__":
    main()
