"""Repo-root pytest configuration.

Surface and check ``PYTHONHASHSEED`` for the test session (audit kernel-P1 /
the ``docs/three_layer_architecture.md`` §12.5 non-determinism inventory).

Inv-5 replay is only *guaranteed* at a fixed hash seed: ``set`` / ``frozenset``
iteration order is salted by ``PYTHONHASHSEED``.  The tick-path set-ordering
dependency was removed (the fill distribution now sorts strategy ids), so a
non-zero seed no longer breaks replay correctness, but a pinned seed remains the
documented contract and a cheap backstop.  ``PYTHONHASHSEED`` can only take
effect *before* the interpreter starts, so this file does not try to set it
mid-session (an ``os.execv`` re-exec from conftest corrupts pytest's output
capture); instead it makes the active seed visible in the run header and warns
when it is not pinned, so CI and local runs configure it explicitly
(``PYTHONHASHSEED=0 uv run pytest``).
"""

from __future__ import annotations

import os

import pytest

_EXPECTED_HASH_SEED = "0"


def pytest_report_header() -> str:
    return f"PYTHONHASHSEED={os.environ.get('PYTHONHASHSEED', '<unset>')}"


def pytest_configure(config: pytest.Config) -> None:
    seed = os.environ.get("PYTHONHASHSEED")
    if seed != _EXPECTED_HASH_SEED:
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(
                f"PYTHONHASHSEED={seed!r} (expected {_EXPECTED_HASH_SEED!r}). "
                "Inv-5 determinism is contractually pinned at PYTHONHASHSEED=0 "
                "(docs/three_layer_architecture.md §12.5); run "
                "`PYTHONHASHSEED=0 uv run pytest ...` so set/frozenset iteration "
                "order is reproducible across hosts."
            ),
            stacklevel=2,
        )
