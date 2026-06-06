"""Shared IB Gateway client-id allocator for functional / paper-RTH tests.

Both ``tests/broker/ib/test_ib_functional.py`` and Tier-3 paper E2E
suites import this module so parallel test runs never collide on IB
error 326 (duplicate client id).
"""

from __future__ import annotations

import os

_DEFAULT_BASE = 500
_client_id_seq = 0


def unique_ib_client_id() -> int:
    """Return a monotonically increasing client id for this process."""
    global _client_id_seq
    _client_id_seq += 1
    base = int(os.getenv("IB_FUNCTIONAL_CLIENT_ID", str(_DEFAULT_BASE)))
    return base + _client_id_seq
