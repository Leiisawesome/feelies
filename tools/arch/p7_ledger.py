"""Rebuild Deliverable G's net-delta ledger from its per-step deltas.

The ledger's running columns are a cumulative sum of its delta columns, so they
can be recomputed rather than hand-maintained. Inserting a step mid-plan shifts
every subsequent running total; doing that by hand across 35 rows is how a
ledger stops reconciling. Run with --check to verify without writing.

Usage: python tools/arch/p7_ledger.py [--check]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC = Path("docs/architecture/target/out/phase7_migration.md")
MINUS = "\u2212"  # the ledger uses U+2212, not hyphen-minus
BASELINE = (196, 551, 356)
# Three other tables in the document start "| Step | ", so anchor on the ledger's
# own first column pair rather than on "| Step | " alone.
HEADER = "| Step | \u0394 mod | "

WAVES = {
    "A": ["S-01", "S-02", "S-03", "S-04"],
    "B": ["S-05", "S-06", "S-07", "S-08"],
    "C": [
        "S-09",
        "S-10",
        "S-11",
        "S-11a",
        "S-12",
        "S-13",
        "S-14",
        "S-15",
        "S-16",
        "S-17",
        "S-18",
    ],
    "D": [f"S-{n}" for n in range(19, 31)],
    "E": ["S-31", "S-32", "S-33", "S-34"],
}


def parse(cell: str) -> int:
    cell = cell.strip().strip("*").replace(MINUS, "-")
    return 0 if cell in {"0", ""} else int(cell)


def fmt(n: int) -> str:
    if n == 0:
        return "0"
    return f"+{n}" if n > 0 else f"{MINUS}{abs(n)}"


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    head, _, rest = text.partition(HEADER)
    table, _, tail = rest.partition("\n\n")
    rows = table.splitlines()[2:]  # skip the header remainder and separator

    # Collect per-step deltas in document order.
    deltas: dict[str, tuple[int, int, int, int]] = {}
    order: list[str] = []
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        name = cells[0].strip("*")
        if not re.fullmatch(r"S-\d+a?", name):
            continue
        order.append(name)
        deltas[name] = (parse(cells[1]), parse(cells[2]), parse(cells[3]), parse(cells[7]))

    expected = [s for wave in WAVES.values() for s in wave]
    if order != expected:
        print(f"FAIL step order in ledger != wave map\n  ledger: {order}\n  map:    {expected}")
        return 1

    out = [
        HEADER + "Δ sym | Δ branch | Running mod | Running sym | Running branch | Δ test files |",
        "|---|---|---|---|---|---|---|---|",
        f"| baseline | — | — | — | {BASELINE[0]} | {BASELINE[1]} | {BASELINE[2]} | — |",
    ]
    run = list(BASELINE)
    plan = [0, 0, 0, 0]
    for wave, steps in WAVES.items():
        sub = [0, 0, 0, 0]
        for step in steps:
            d = deltas[step]
            for i in range(3):
                run[i] += d[i]
                sub[i] += d[i]
            sub[3] += d[3]
            out.append(
                f"| {step} | {fmt(d[0])} | {fmt(d[1])} | {fmt(d[2])} "
                f"| {run[0]} | {run[1]} | {run[2]} | {fmt(d[3])} |"
            )
        for i in range(4):
            plan[i] += sub[i]
        out.append(
            f"| **wave {wave}** | **{fmt(sub[0])}** | **{fmt(sub[1])}** | **{fmt(sub[2])}** "
            f"| **{run[0]}** | **{run[1]}** | **{run[2]}** | **{fmt(sub[3])}** |"
        )
    out.append(
        f"| **whole plan** | **{fmt(plan[0])}** | **{fmt(plan[1])}** | **{fmt(plan[2])}** "
        f"| **{run[0]}** | **{run[1]}** | **{run[2]}** | **{fmt(plan[3])}** |"
    )

    rebuilt = "\n".join(out)
    if rebuilt == HEADER + table:
        print("ledger reconciles; no change")
        return 0
    if "--check" in sys.argv:
        print("FAIL ledger does not reconcile with its own deltas")
        return 1

    DOC.write_text(head + rebuilt + "\n\n" + tail, encoding="utf-8")

    # The console codepage may be GBK, which cannot encode U+2212.
    def ascii_fmt(n: int) -> str:
        return fmt(n).replace(MINUS, "-")

    print(f"rebuilt: {len(order)} steps")
    print(
        f"  whole plan: mod {ascii_fmt(plan[0])}, sym {ascii_fmt(plan[1])}, "
        f"branch {ascii_fmt(plan[2])}"
    )
    print(f"  final running: {run[0]} modules, {run[1]} symbols, {run[2]} branch points")
    print(f"  test files: {ascii_fmt(plan[3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
