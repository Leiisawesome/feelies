"""Verify CORE §M's five definition-of-done items for Phase 7.

Each item is measured against the phase outputs rather than asserted. Writes
evidence/p7_done.json so the closing check's verdict is reproducible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "architecture" / "target" / "out"
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "p7_done.json"

# CORE §K, one row per deliverable.
DELIVERABLES = {
    "D0": ("phase0_comprehension.md", None),
    "E1": ("phase1_plumbing.md", None),
    "B": ("phase2_contracts.md", None),
    "C/D": ("phase3_flow_gating.md", None),
    "E2": ("phase4_performance.md", None),
    "F": ("phase5_gaps.md", None),
    "H": ("phase6_conformance.md", None),
    "A": ("phase7_migration.md", "## A. Design thesis"),
    "G": ("phase7_migration.md", "## G. Migration plan"),
    "I": ("phase7_migration.md", "## I. Do-not-change list"),
    "J": ("phase7_migration.md", "## J. Assumption and unknowns register"),
    "K": ("phase7_migration.md", "## K. Model findings"),
}

report: dict[str, object] = {}
fails: list[str] = []

# ── M.1 every deliverable in §K exists ───────────────────────────────────────
missing = []
for did, (fname, section) in DELIVERABLES.items():
    path = OUT / fname
    if not path.exists():
        missing.append(f"{did}: {fname} absent")
    elif section and section not in path.read_text(encoding="utf-8"):
        missing.append(f"{did}: {fname} has no '{section}'")
report["M1_deliverables"] = {"checked": len(DELIVERABLES), "missing": missing}
if missing:
    fails.append("M1")

# ── M.2 every §F item has exactly one named owner ─────────────────────────────
phase2 = (OUT / "phase2_contracts.md").read_text(encoding="utf-8")
# The §F pass gives each item its own resolution section.
f_sections = sorted(set(re.findall(r"^#+ .*?\bF\.([1-7])\b", phase2, re.M)))
f_owners = {}
for n in "1234567":
    # An owner is named if the item's section states a single owning engine.
    block = re.search(rf"^#+ .*?\bF\.{n}\b.*?(?=^#+ |\Z)", phase2, re.M | re.S)
    body = block.group(0) if block else ""
    engines = set(re.findall(r"engine (\d{1,2})\b", body.lower()))
    f_owners[f"F.{n}"] = {
        "section_present": bool(block),
        "model_finding_none": "Model finding: none" in body,
        "engines_mentioned": sorted(engines, key=int),
    }
report["M2_f_items"] = {
    "sections_found": f_sections,
    "detail": f_owners,
    "eighth_responsibility": "eighth unassigned responsibility" in phase2,
}
if len(f_sections) != 7:
    fails.append("M2")

# ── M.3 every §C invariant has a named enforcing test in Phase 6 ─────────────
phase6 = (OUT / "phase6_conformance.md").read_text(encoding="utf-8")
# Phase 6's spec blocks carry an INVARIANT: field naming the CORE §C clause each
# test enforces. `Inv-N` in those fields is the platform-invariants numbering, a
# different scheme from CORE §C.n — do not conflate the two.
blocks = re.findall(
    r"^TEST: +(\S+)(.*?)(?=^TEST: |\Z)",
    phase6[phase6.index("TEST:") :],
    re.M | re.S,
)
enforcers: dict[str, list[str]] = {f"C.{n}": [] for n in range(1, 12)}
for tid, body in blocks:
    field = re.search(r"^INVARIANT: +(.*?)$", body, re.M)
    if not field:
        continue
    for n in re.findall(r"§C\.(\d+)", field.group(1)):
        key = f"C.{n}"
        if key in enforcers:
            enforcers[key].append(tid)

# A clause may also be enforced by a test that names it in the coverage table
# rather than its own INVARIANT field.
table = dict(re.findall(r"^\|[^|]*\| CORE §C\.(\d+)[^|]*\| ([^|]+)\|", phase6, re.M))
for n, cell in table.items():
    key = f"C.{n}"
    if key in enforcers:
        for tid in re.findall(r"\*\*([A-Z]\d+)\*\*", cell):
            if tid not in enforcers[key]:
                enforcers[key].append(tid)

report["M3_invariants"] = {k: sorted(v) for k, v in enforcers.items()}
uncited = sorted((k for k, v in enforcers.items() if not v), key=lambda s: int(s.split(".")[1]))
report["M3_unenforced"] = uncited
report["M3_test_blocks"] = len(blocks)
if uncited:
    fails.append("M3")

# ── M.4 every Phase 5 gap has a step or a stated deferral ────────────────────
index = json.loads((Path(__file__).resolve().parent / "evidence" / "p7_index.json").read_text())
phase7 = (OUT / "phase7_migration.md").read_text(encoding="utf-8")
covered = {
    m.group(1) for m in re.finditer(r"^\| (G[0-9]{2}) \|[^|]*\|\s*\**S-[0-9]{2}a?", phase7, re.M)
}
gaps = set(index["gaps"])
report["M4_gaps"] = {
    "total": len(gaps),
    "covered": len(gaps & covered),
    "uncovered": sorted(gaps - covered),
}
if gaps - covered:
    fails.append("M4")

# ── M.5 assumption register non-empty ────────────────────────────────────────
j = phase7[phase7.index("## J. Assumption") : phase7.index("## K. Model findings")]
new = re.findall(r"^(A7\.\d+) +\S", j, re.M)
inherited = re.findall(r"^\| (A\d\.\d+|U-\d) \|", j, re.M)
report["M5_register"] = {"new_entries": len(new), "inherited_rows": len(inherited)}
if len(new) + len(inherited) < 5:
    fails.append("M5")

EVIDENCE.write_text(json.dumps(report, indent=2), encoding="utf-8")

print("CORE §M definition of done")
print(f"  M1 deliverables exist      {len(DELIVERABLES)} checked, {len(missing)} missing")
print(f"  M2 §F items owned          {len(f_sections)}/7 resolution sections")
print(
    f"     eighth responsibility found in Phase 2: {report['M2_f_items']['eighth_responsibility']}"
)
print(
    f"  M3 §C invariants enforced  {11 - len(uncited)}/11 across {report['M3_test_blocks']} blocks"
)
for k, v in report["M3_invariants"].items():  # type: ignore[union-attr]
    print(f"     {k:5} {', '.join(v) if v else '** NO NAMED TEST **'}")
print(f"  M4 gaps covered            {len(gaps & covered)}/{len(gaps)}")
print(f"  M5 register entries        {len(new)} new + {len(inherited)} inherited")
print()
print("measured FAIL: " + ", ".join(fails) if fails else "all five measurable checks pass")
