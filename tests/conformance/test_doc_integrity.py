"""Registries count once, and the ledger has no byte-identical blocks."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.exec.doc_integrity import (
    identical_ledger_blocks,
    load_text,
    registry_duplicates,
    require_ledger,
    require_registry,
)

_ROOT = Path(__file__).resolve().parents[2]
DECISIONS = _ROOT / "docs/architecture/target/position_engine/decisions.md"
BATTERY = _ROOT / "docs/architecture/target/position_engine/battery.md"
LADDER = _ROOT / "docs/architecture/target/out/phase14_position_engine.md"
LEDGER = _ROOT / "docs/architecture/target/out/exec/LEDGER.md"

_DECISION = r"^\| (D-\d+) \|"
_MEMBER = r"^MEMBER:\s+(\d+)\b"
_RUNG = r"^\| (P-\d+[a-z]*) \|"


def _rel(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def test_clean_registry_passes() -> None:
    text = "| D-01 | a |\n| D-02 | b |\n"
    assert registry_duplicates(text, _DECISION) == {}
    require_registry("decisions.md", text, _DECISION)


def test_duplicated_decision_id_names_lines() -> None:
    text = "| D-01 | a |\n| D-01 | b |\n"
    with pytest.raises(AssertionError, match=r"^decisions.md: D-01 count 2 at lines 1, 2$"):
        require_registry("decisions.md", text, _DECISION)


def test_duplicated_member_names_lines() -> None:
    text = "MEMBER: 1 Alpha\nMEMBER: 1 Beta\n"
    with pytest.raises(AssertionError, match=r"^battery.md: 1 count 2 at lines 1, 2$"):
        require_registry("battery.md", text, _MEMBER)


def test_duplicated_ladder_row_names_lines() -> None:
    text = "| P-21e | a |\n| P-21e | b |\n"
    with pytest.raises(AssertionError, match=r"^ladder.md: P-21e count 2 at lines 1, 2$"):
        require_registry("ladder.md", text, _RUNG)


def test_identical_ledger_blocks_name_hash_and_lines() -> None:
    text = "## S-01 one\nbody\n\n## S-01 one\nbody\n"
    digest = hashlib.sha256(b"## S-01 one\nbody").hexdigest()
    groups = identical_ledger_blocks(text)
    assert groups == [[(1, 3, digest), (4, 5, digest)]]
    message = f"ledger.md: block {digest[:12]} identical at lines 1-3 and 4-5"
    with pytest.raises(AssertionError, match=f"^{message}$"):
        require_ledger("ledger.md", text)


def test_distinct_blocks_with_the_same_id_pass() -> None:
    text = "## S-01 one\nalpha\n\n## S-01 one\nbeta\n"
    assert identical_ledger_blocks(text) == []
    require_ledger("ledger.md", text)


def test_live_decisions_are_unique() -> None:
    require_registry(_rel(DECISIONS), load_text(DECISIONS), _DECISION)


def test_live_members_are_unique() -> None:
    require_registry(_rel(BATTERY), load_text(BATTERY), _MEMBER)


def test_live_ladder_rows_are_unique() -> None:
    require_registry(_rel(LADDER), load_text(LADDER), _RUNG)


def test_live_ledger_has_no_identical_blocks() -> None:
    require_ledger(_rel(LEDGER), load_text(LEDGER))
