"""S6 — no fail-quiet exception handler.

Promotes ``tools.arch.gatescan.fail_quiet_handlers``.  An ``except``
whose body neither raises, returns, nor logs is a gate that silently
passed.  G20, G23, G36.
"""

from __future__ import annotations

import pytest

from tools.arch.gatescan import fail_quiet_handlers


@pytest.mark.xfail(strict=True, reason="GAP G20 G23 G36")
def test_no_fail_quiet_exception_handler() -> None:
    quiet = fail_quiet_handlers()
    assert quiet is not None
    assert not quiet, (
        f"{len(quiet)} fail-quiet except handler(s). First: "
        f"{quiet[0]['path']}:{quiet[0]['line']} except {quiet[0]['exc_type']}"
    )
