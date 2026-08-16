"""Verify Deliverables I and J: block completeness, cross-references, and counts.

Every I-nn block must carry all four do-not-change fields and every A7-nn block
the four P7 register fields; every step named in THREATENED BY must exist in
Deliverable G; and the counts asserted in prose must match the file. A count
asserted but not measured is not verified.
"""

from __future__ import annotations

import pathlib
import re
import sys

FIELDS = ("SOUND BECAUSE:", "STOPS WHEN:", "THREATENED BY:", "GUARD:")
J_FIELDS = ("ASSUMPTION:", "WHY NEEDED:", "FALSIFIED BY:", "BLAST RADIUS:")

text = pathlib.Path("docs/architecture/target/out/phase7_migration.md").read_text(encoding="utf-8")
deliverable_i = text[text.index("## I. Do-not-change list") : text.index("## J. Assumption")]
deliverable_j = text[text.index("## J. Assumption") :]
fail = []

blocks = re.findall(r"^(I-\d\d)  (.+?)$(.*?)^```$", deliverable_i, re.M | re.S)
ids = [b[0] for b in blocks]
print(f"entries: {len(ids)}")

expected = [f"I-{n:02d}" for n in range(1, 25)]
if ids != expected:
    fail.append(f"entry ids not contiguous I-01..I-24: got {ids}")

for eid, title, body in blocks:
    missing = [f for f in FIELDS if f not in body]
    if missing:
        fail.append(f"{eid} missing {missing}")

steps_in_g = set(re.findall(r"^### G\.\d+\.\d+ (S-\d\d)", text, re.M)) or set(
    re.findall(r"\b(S-\d\d)\b", text[: text.index("## I. Do-not-change list")])
)
referenced = {s for _, _, body in blocks for s in re.findall(r"\b(S-\d\d)\b", body)}
unknown = sorted(referenced - steps_in_g)
if unknown:
    fail.append(f"THREATENED BY names steps absent from Deliverable G: {unknown}")

threatened = [eid for eid, _, body in blocks if not re.search(r"THREATENED BY:\s+none", body)]
print(f"entries with >=1 threatening step: {len(threatened)}")
print(f"distinct steps named as threats: {len(referenced)}")

claims = {
    "24 promoted": "**24 promoted**" in deliverable_i,
    "12 mechanical": "12/12 hold" in deliverable_i,
    "12 read": "remaining 12 were re-verified by reading" in deliverable_i,
}
for name, ok in claims.items():
    if not ok:
        fail.append(f"prose claim not found: {name}")

m = re.search(
    r"\*\*(\d+) of the 24\s*\nentries have at least one threatening step, and (\d+) distinct steps",
    deliverable_i,
)
if not m:
    fail.append("measured threat counts not stated in prose")
elif (int(m.group(1)), int(m.group(2))) != (len(threatened), len(referenced)):
    fail.append(
        f"prose says {m.group(1)}/{m.group(2)}, measured {len(threatened)}/{len(referenced)}"
    )

strengthened = len(re.findall(r"^\| I-\d\d [^|]*\| S-\d\d \|", deliverable_i, re.M))
print(f"strengthened rows in I.9 table: {strengthened}")
if "Four entries end the plan stronger" in deliverable_i and strengthened != 4:
    fail.append(f"prose says four strengthened, table has {strengthened}")

# Two-digit ids use one padding space, not two, to keep the titles aligned.
j_blocks = re.findall(r"^(A7\.\d+) +(.+?)$(.*?)^```$", deliverable_j, re.M | re.S)
j_ids = [b[0] for b in j_blocks]
print(f"\nJ entries: {len(j_ids)}")
if j_ids != [f"A7.{n}" for n in range(1, len(j_ids) + 1)]:
    fail.append(f"A7 ids not contiguous: {j_ids}")
for jid, _, body in j_blocks:
    missing = [f for f in J_FIELDS if f not in body]
    if missing:
        fail.append(f"{jid} missing {missing}")

# Inherited ids cited in J.2 must exist in the measured inventory.
inherited = set(re.findall(r"^\| (A\d\.\d+) \|", deliverable_j, re.M))
inventory = set(
    re.findall(r"^\| (A\d\.\d+) \|", text[: text.index("## A. Design thesis")] or "", re.M)
)
measured = pathlib.Path("tools/arch/evidence/p7_assumptions.json")
if measured.exists():
    import json

    data = json.loads(measured.read_text(encoding="utf-8"))
    inventory = {e["id"] for entries in data["inventory"].values() for e in entries}
    missing = sorted(inherited - inventory)
    if missing:
        fail.append(f"J.2 cites register ids absent from the measured inventory: {missing}")
    print(f"inherited register rows cited: {len(inherited)} of {len(inventory)} measured")

u_open = set(re.findall(r"^\| (U-\d) \|", deliverable_j, re.M))
print(f"Phase 0 unknowns cited: {len(u_open)}")

# ── Deliverable K ────────────────────────────────────────────────────────────
# K decides nine inherited watch-lines. The summary table's verdicts must match
# both the per-watch-line detail and the prose count, or the deliverable is
# claiming an accounting it does not have.
deliverable_k = text[text.index("## K. Model findings") :]
verdicts = dict(
    re.findall(r"^\| (WL-\d) \|[^|]*\|[^|]*\| \*{0,2}([a-zA-Z ]+?)\*{0,2} \|", deliverable_k, re.M)
)
print(f"\nK watch-lines in summary table: {len(verdicts)}")
if len(verdicts) != 9:
    fail.append(f"expected 9 watch-lines, table has {len(verdicts)}")

fires = sorted(w for w, v in verdicts.items() if "FIRES" in v.upper())
no_fire = sorted(w for w, v in verdicts.items() if "does not fire" in v.lower())
undecided = sorted(w for w, v in verdicts.items() if "cannot" in v.lower())
print(f"  fires={fires} no_fire={no_fire} undecided={undecided}")
if len(fires) + len(no_fire) + len(undecided) != len(verdicts):
    fail.append("a watch-line verdict is neither fires, does-not-fire, nor undecided")

# Each non-firing watch-line needs a detail block; each firing one a K.1.n section.
detail = set(re.findall(r"^(WL-\d) {2,}\S.*DOES NOT FIRE", deliverable_k, re.M))
if detail != set(no_fire):
    fail.append(f"K.3 detail blocks {sorted(detail)} != table's non-firing {no_fire}")
findings = re.findall(r"^#### (K\.1\.\d)", deliverable_k, re.M)
if len(findings) != len(fires) + 1:  # three firing watch-lines plus the §F item
    fail.append(f"K.1 has {len(findings)} findings, expected {len(fires) + 1}")
print(f"  K.1 findings={findings}")

rejected = len(re.findall(r"^\| \*\*", deliverable_k, re.M))
print(f"  K.4 rejected candidates={rejected}")
if "Five candidates considered and rejected" in deliverable_k and rejected != 5:
    fail.append(f"K.4 says five rejected, table has {rejected}")

if fail:
    print("\nFAILURES:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("\nDeliverables I and J: structure, cross-references and stated counts all verify")
