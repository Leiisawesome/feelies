"""The gap-to-test registry — provenance for every remediation step.

Inv-13 requires each change to trace to the gap it closes.  This is that
map: one entry per Phase 5 gap, naming the migration step(s) that address
it and the conformance test(s) that enforce it afterwards.  Transcribed
from the coverage table in ``docs/architecture/target/out/phase7_migration.md``
(§G.8); the plan is the source of truth, this is the executable copy.

Registering a test here is what lets a later step say which gap it closed.
An empty ``tests`` tuple means the gap currently has no guard at all —
``test_registry_closure`` (S1) is the assertion over that.

The module-level completeness check mirrors ``GATE_EVIDENCE_REQUIREMENTS``
in ``src/feelies/promotion/evidence.py``: a structurally broken registry
fails on import rather than producing a quietly wrong closure result.
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITIES = ("P0", "P1", "P2")

#: Phase 5 catalogued gaps G01..G45.  G46 is a Phase 6 §8.1 proposal and is
#: registered by S-10, the step that closes it.
GAP_ID_RANGE = range(1, 46)


@dataclass(frozen=True)
class GapEntry:
    """One Phase 5 gap: how severe, who fixes it, what holds it fixed."""

    severity: str
    steps: tuple[str, ...]
    tests: tuple[str, ...]


GAP_REGISTRY: dict[str, GapEntry] = {
    "G01": GapEntry("P2", ("S-03", "S-32"), ("S4",)),
    "G02": GapEntry("P1", ("S-12",), ("S15", "R3", "X8")),
    "G03": GapEntry("P0", ("S-08",), ("X9", "X11", "H2")),
    "G04": GapEntry("P1", ("S-15",), ("S16", "R6")),
    "G05": GapEntry("P1", ("S-17",), ("R2", "R9")),
    "G06": GapEntry("P1", ("S-16",), ("R4",)),
    "G07": GapEntry("P1", ("S-09",), ("S8", "R5")),
    "G08": GapEntry("P2", ("S-02", "S-32"), ("R1", "R8")),
    "G09": GapEntry("P2", ("S-13",), ("S12",)),
    "G10": GapEntry("P1", ("S-12", "S-31"), ("S11", "X2")),
    "G11": GapEntry("P1", ("S-20", "S-17"), ("R2", "C3")),
    "G12": GapEntry("P1", ("S-18",), ("S10", "S13")),
    "G13": GapEntry("P2", ("S-20",), ("S2", "S13", "S15")),
    "G14": GapEntry("P1", ("S-19",), ("S2", "S12", "S13")),
    "G15": GapEntry("P1", ("S-26",), ("S12", "C6", "A3")),
    "G16": GapEntry("P2", ("S-04",), ("S2", "A2")),
    "G17": GapEntry("P1", ("S-11",), ("S13", "X6")),
    "G18": GapEntry("P1", ("S-27",), ("A2",)),
    "G19": GapEntry("P1", ("S-23", "S-26"), ("S12", "C6")),
    "G20": GapEntry("P0", ("S-05",), ("S6", "X1", "X5", "X7")),
    "G21": GapEntry("P1", ("S-21",), ("S2", "S12", "R8", "C2", "C5")),
    "G22": GapEntry("P1", ("S-22",), ("S2", "X2")),
    "G23": GapEntry("P0", ("S-06",), ("S6", "X1", "X4", "X6", "X7")),
    "G24": GapEntry("P1", ("S-24",), ("S2", "C4")),
    "G25": GapEntry("P1", ("S-29",), ("S3", "A3")),
    "G26": GapEntry("P1", ("S-28",), ("S7",)),
    "G27": GapEntry("P1", ("S-25",), ("S2", "H4")),
    "G28": GapEntry("P1", ("S-12",), ("S11", "X9")),
    "G29": GapEntry("P2", ("S-17",), ("R9",)),
    "G30": GapEntry("P1", ("S-16", "S-27"), ("S2", "R4", "C5")),
    # G31 and G32 are named by no Phase 6 test (§G.0.4).  S-30 authors their
    # gates and registers them here; until then S1 fails on exactly these two.
    "G31": GapEntry("P1", ("S-30",), ()),
    "G32": GapEntry("P1", ("S-30",), ()),
    "G33": GapEntry("P1", ("S-30",), ("C3",)),
    "G34": GapEntry("P1", ("S-21",), ("C2", "X11")),
    "G35": GapEntry("P1", ("S-30",), ("X1",)),
    "G36": GapEntry("P1", ("S-05", "S-06", "S-30"), ("S6", "R6", "X6", "X7")),
    "G37": GapEntry("P1", ("S-14",), ("S14",)),
    "G38": GapEntry("P1", ("S-11",), ("S13", "C4", "X6")),
    "G39": GapEntry("P1", ("S-12",), ("S15", "S17")),
    "G40": GapEntry("P1", ("S-34",), ("S2",)),
    "G41": GapEntry("P1", ("S-07", "S-33"), ("S5",)),
    "G42": GapEntry("P1", ("S-33",), ("S5", "R7")),
    "G43": GapEntry("P0", ("S-07",), ("X1", "X10")),
    "G44": GapEntry("P2", ("S-31",), ("S5",)),
    "G45": GapEntry("P2", ("S-32",), ("S5",)),
}


def _check_registry_completeness() -> None:
    """Fail on import if the registry is not a faithful copy of the inventory.

    A gap silently missing from the map reads as "covered" to every closure
    assertion over it, which is the one failure mode a provenance registry
    must not have.
    """
    expected = {f"G{n:02d}" for n in GAP_ID_RANGE}
    missing = sorted(expected - set(GAP_REGISTRY))
    unknown = sorted(set(GAP_REGISTRY) - expected)
    if missing or unknown:
        raise RuntimeError(
            f"GAP_REGISTRY does not match the Phase 5 inventory: "
            f"missing {missing}, unrecognised {unknown}"
        )

    bad_severity = sorted(
        gap_id for gap_id, entry in GAP_REGISTRY.items() if entry.severity not in SEVERITIES
    )
    if bad_severity:
        raise RuntimeError(
            f"GAP_REGISTRY entries carry a severity outside {SEVERITIES}: {bad_severity}"
        )

    no_step = sorted(gap_id for gap_id, entry in GAP_REGISTRY.items() if not entry.steps)
    if no_step:
        raise RuntimeError(f"GAP_REGISTRY entries name no remediation step: {no_step}")


_check_registry_completeness()
