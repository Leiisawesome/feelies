"""Inventory every prior-phase assumption register entry.

Deliverable J must carry forward the still-open assumptions the migration plan
depends on, so the inherited set has to be measured rather than recalled. Writes
tools/arch/evidence/p7_assumptions.json.

Console output is ASCII-folded: the phase docs contain micro signs and en dashes
that a gbk console cannot encode.
"""

from __future__ import annotations

import json
import pathlib
import re

OUT = pathlib.Path("docs/architecture/target/out")
EVIDENCE = pathlib.Path("tools/arch/evidence")


def fold(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def main() -> None:
    inventory: dict[str, list[dict[str, str]]] = {}
    for path in sorted(OUT.glob("phase*.md")):
        text = path.read_text(encoding="utf-8")
        rows = re.findall(r"^\| (A\d\.\d+) \|(.*)$", text, re.M)
        if not rows:
            continue
        entries = []
        for rid, rest in rows:
            cells = [c.strip() for c in rest.split("|")]
            entries.append(
                {
                    "id": rid,
                    "assumption": cells[0] if cells else "",
                    "why": cells[1] if len(cells) > 1 else "",
                    "falsifier": cells[2] if len(cells) > 2 else "",
                }
            )
        inventory[path.name] = entries

    total = sum(len(v) for v in inventory.values())
    for name, entries in inventory.items():
        print(f"== {name} -- {len(entries)} entries")
        for e in entries:
            print(f"   {e['id']:<6} {fold(e['assumption'])[:100]}")

    # Which inherited ids does the Phase 7 deliverable already lean on?
    p7 = (OUT / "phase7_migration.md").read_text(encoding="utf-8")
    body = p7[: p7.index("## J.")] if "## J." in p7 else p7
    cited = sorted({m for m in re.findall(r"\bA\d\.\d+\b", body)})
    print(f"\ntotal inherited entries: {total}")
    print(f"cited by deliverables A/G/I: {len(cited)} -> {cited}")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "p7_assumptions.json").write_text(
        json.dumps({"inventory": inventory, "cited_in_phase7": cited}, indent=1) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
