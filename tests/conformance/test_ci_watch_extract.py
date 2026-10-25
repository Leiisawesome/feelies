"""-Attempt in ci_watch_extract.ps1 accepts only its exact values (D-212, F-T6a-1)."""

from __future__ import annotations

import re
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "exec" / "ci_watch_extract.ps1"


def test_attempt_accepts_only_exact_values() -> None:
    lines = _SCRIPT.read_text(encoding="utf-8-sig").splitlines()
    declared = [line for line in lines if re.search(r"\]\[string\]\$Attempt\b", line)]
    assert len(declared) == 1, declared
    assert re.search(r"\[ValidateSet\('latest', 'first', IgnoreCase = \$false\)\]", declared[0]), (
        declared[0]
    )
