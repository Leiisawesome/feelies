"""Fail closed unless an IB target is a paper port and, when known, paper accounts."""

from __future__ import annotations

import pytest

_PAPER_PORTS = frozenset({4002, 7497})


def assert_paper_target(port: int, managed_accounts: list[str] | None = None) -> None:
    """Reject a live port, and reject accounts that are not all non-empty ``DU*``.

    ``managed_accounts is None`` checks the port only. An empty list fails.
    """
    if port not in _PAPER_PORTS:
        pytest.fail(f"refusing broker port {port}; paper ports are 4002 and 7497")
    if managed_accounts is None:
        return
    if not managed_accounts or any(not account.startswith("DU") for account in managed_accounts):
        pytest.fail(
            f"refusing managed accounts {managed_accounts!r}; "
            "expected a non-empty list of DU* paper accounts"
        )
