"""S6 — no unallowlisted fail-quiet exception handler.

S-30g adjudicates the seventeen handlers S-30a left outside FILES.
An ``except`` whose body neither raises, returns, nor logs is quiet;
a keeper is permitted only as an explicit allowlist row this test reads.
A quiet handler that is not in the allowlist fails. A stale row fails.
G36.
"""

from __future__ import annotations

from typing import NamedTuple

from tools.arch.gatescan import fail_quiet_handlers


class FailQuietKeep(NamedTuple):
    path: str
    line: int
    exc_type: str
    reason: str


# Empty until the seventeen are classified. A passing run with this tuple
# empty would mean the scanner went silent, not that G36 closed.
FAIL_QUIET_KEEP: tuple[FailQuietKeep, ...] = ()


def test_no_unallowlisted_fail_quiet_exception_handler() -> None:
    quiet = fail_quiet_handlers()
    assert quiet is not None
    found = frozenset(
        (h["path"].replace("\\", "/"), int(h["line"]), str(h["exc_type"])) for h in quiet
    )
    allowed = frozenset((k.path, k.line, k.exc_type) for k in FAIL_QUIET_KEEP)
    extra = sorted(found - allowed)
    missing = sorted(allowed - found)
    assert extra == [], (
        f"{len(extra)} fail-quiet handler(s) not in FAIL_QUIET_KEEP. First: "
        f"{extra[0][0]}:{extra[0][1]} except {extra[0][2]}"
    )
    assert missing == [], (
        f"{len(missing)} FAIL_QUIET_KEEP row(s) are not quiet. First: "
        f"{missing[0][0]}:{missing[0][1]} except {missing[0][2]}"
    )
    assert all(k.reason.strip() for k in FAIL_QUIET_KEEP), (
        "every allowlisted keeper must carry a named reason"
    )
