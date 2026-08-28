"""S7 — mode branches only at the composition root and the declared seam.

Promotes ``tools.arch.coupling.mode_branches``.  Composition-root
selection (bootstrap) is legitimate; in-engine ``OperatingMode``
branches are G26.  The root is an explicit allowlist, not a hard-coded
``{execution, broker}`` set.
"""

from __future__ import annotations

from tools.arch.coupling import mode_branches

_SEAM_PREFIXES = ("src/feelies/execution/", "src/feelies/broker/")
_COMPOSITION_ROOT = "src/feelies/bootstrap.py"


def _allowed(path: str) -> bool:
    return path == _COMPOSITION_ROOT or path.startswith(_SEAM_PREFIXES)


def test_mode_branches_only_at_composition_root() -> None:
    hits = [h for h in mode_branches() if h["kind"] == "operating_mode"]
    assert hits, "scanner found no OperatingMode branch — the seam check is vacuous"
    outside = [h for h in hits if not _allowed(h["path"])]
    assert not outside, (
        f"{len(outside)} OperatingMode branch(es) outside the composition root "
        f"and mode seam. First: {outside[0]['path']}:{outside[0]['line']} "
        f"{outside[0]['test']}"
    )
