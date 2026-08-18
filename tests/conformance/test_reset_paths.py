"""S16 — reset-path totality; I-01 uuid/RNG scan.

Promotes ``tools.arch.substrate``.  A class that mutates outside
``__init__`` and exposes no reset path cannot share a process across
runs (G04).  The uuid/RNG clause is the I-01 static assertion.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

import tools.arch.substrate as substrate

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_COLD_RNG_PREFIX = "src/feelies/research/"


@pytest.fixture(scope="module")
def substrate_payload(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("substrate")
    orig = substrate.EVIDENCE
    substrate.EVIDENCE = tmp
    try:
        # main() prints rel(out) against the repo root; a tmp evidence dir
        # is outside ROOT and that print raises after the JSON is written.
        try:
            substrate.main()
        except ValueError as exc:
            if "is not in the subpath" not in str(exc):
                raise
    finally:
        substrate.EVIDENCE = orig
    return json.loads((tmp / "substrate.json").read_text(encoding="utf-8"))


@pytest.mark.xfail(strict=True, reason="GAP G04")
def test_reset_path_totality(substrate_payload: dict[str, Any]) -> None:
    n_classes = int(substrate_payload["n_stateful_classes"])
    assert n_classes > 0, "substrate scanner found no stateful classes"
    n_no_reset = int(substrate_payload["n_stateful_no_reset"])
    top = substrate_payload["stateful_no_reset_top"]
    assert n_no_reset == 0, (
        f"{n_no_reset} stateful class(es) mutate outside __init__ with no reset "
        f"path. First: {top[0]['cls']} ({top[0]['path']})"
        if top
        else f"{n_no_reset} stateful class(es) have no reset path"
    )


def test_no_uuid_or_non_research_rng(substrate_payload: dict[str, Any]) -> None:
    """I-01: identity is derived; uuid/RNG in src/feelies is only legal in research/."""
    uuid_hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_SRC.parents[1]).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "uuid" or alias.name.startswith("uuid."):
                        uuid_hits.append(f"{rel}:{node.lineno}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.split(".")[0] == "uuid"
            ):
                uuid_hits.append(f"{rel}:{node.lineno}")
    assert not uuid_hits, f"uuid import(s) in src/feelies: {uuid_hits}"

    rng = substrate_payload["rng_sites"]
    hot_rng = [s for s in rng if not str(s["path"]).startswith(_COLD_RNG_PREFIX)]
    assert not hot_rng, f"RNG site(s) outside research/: {hot_rng}"
