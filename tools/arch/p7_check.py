"""Check Deliverable G's step blocks against P7's template.

Asserts every step block carries all twelve required fields, that step IDs are
contiguous, and that every Phase 5 gap ID appears in some step's CLOSES or in
the coverage table. Run after editing phase7_migration.md.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "architecture" / "target" / "out" / "phase7_migration.md"
INDEX = Path(__file__).resolve().parent / "evidence" / "p7_index.json"

FENCE = "`" * 3
REQUIRED = [
    "STEP:",
    "CLOSES:",
    "PROBLEM:",
    "FILES:",
    "WHY THIS OWNER:",
    "REFACTOR PATH:",
    "BLAST RADIUS:",
    "VALIDATED BY:",
    "PARITY IMPACT:",
    "DELETES:",
    "NET DELTA:",
    "ROLLBACK:",
]


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    # Scope to Deliverable G. Later deliverables use fenced blocks of their own
    # (I's 23 do-not-change entries), which are not step blocks and would
    # otherwise be reported as 23 malformed steps.
    start = text.index("## G. Migration plan")
    end = (
        text.index("## I. Do-not-change list") if "## I. Do-not-change list" in text else len(text)
    )
    section = text[start:end]
    blocks = re.findall(FENCE + r"\n(.*?)" + FENCE, section, flags=re.S)
    failures = 0

    print(f"step blocks: {len(blocks)}")
    ids: list[str] = []
    for block in blocks:
        m = re.search(r"STEP:\s*(\S+)", block)
        sid = m.group(1) if m else "?"
        ids.append(sid)
        missing = [f for f in REQUIRED if f not in block]
        if missing:
            failures += 1
            print(f"  {sid}: MISSING {missing}")

    # Contiguous numbering, tolerating one lettered insertion per number. S-11a is
    # inserted rather than renumbering S-12..S-34, which would invalidate every
    # step cross-reference in Deliverables I, J and K.
    numbers = [int(re.sub(r"\D", "", sid)) for sid in ids]
    expected = sorted(set(numbers))
    if numbers != sorted(numbers) or expected != list(range(1, max(numbers) + 1)):
        failures += 1
        print(f"  step ids not contiguous or out of order: {ids}")
    else:
        lettered = [sid for sid in ids if not re.fullmatch(r"S-\d+", sid)]
        note = f" (+{len(lettered)} inserted: {lettered})" if lettered else ""
        print(f"step ids contiguous: S-01..S-{max(numbers):02d}{note}")

    gaps = set(json.loads(INDEX.read_text(encoding="utf-8"))["gaps"])
    # A gap is covered if the coverage table has a row for it with a step.
    covered = {
        m.group(1)
        for m in re.finditer(r"^\| (G[0-9]{2}) \|[^|]*\|\s*\**S-[0-9]{2}a?", text, flags=re.M)
    }
    uncovered = sorted(gaps - covered)
    if uncovered:
        failures += 1
        print(f"  gaps with no step in the coverage table: {uncovered}")
    else:
        print(f"all {len(gaps)} gaps have a step in the coverage table")

    print("OK" if not failures else f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
