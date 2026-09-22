"""S17 — external assignment and private reach match the composition-root pin.

G39: objects must be valid after ``__init__``. The five post-construction
assignments in ``bootstrap.py`` move into constructor injection. Every
remaining external assignment and cross-object private access is a counted
row with a reason. A second copy of a key already in the pin fails.
"""

from __future__ import annotations

from collections import Counter

from feelies.core.wiring_manifest import (
    COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST,
    COMPOSITION_ROOT_PRIVATE_ALLOWLIST,
)
from tools.arch.coupling import cross_object_private, external_attribute_assignment

# These must be constructor-injected, not patched after init.
_INJECTED_BOOTSTRAP_TARGETS = frozenset(
    {
        "metric_collector._store_raw_events",
        "orchestrator.config_snapshot",
        "orchestrator.live_feed",
        "orchestrator.ib_connection",
        "module._construct",
    }
)


def _pin_counters(
    found: Counter[tuple[str, str]],
    allowed: Counter[tuple[str, str]],
    kind: str,
) -> None:
    extra = found - allowed
    missing = allowed - found
    extra_keys = sorted(extra)
    missing_keys = sorted(missing)
    assert extra == Counter(), (
        f"{sum(extra.values())} {kind} site(s) not in the composition-root pin. "
        f"First: {extra_keys[0][0]} {extra_keys[0][1]}"
    )
    assert missing == Counter(), (
        f"{sum(missing.values())} composition-root pin row(s) are not live {kind}. "
        f"First: {missing_keys[0][0]} {missing_keys[0][1]}"
    )


def test_s17_bootstrap_assignments_are_constructor_injected() -> None:
    patched = external_attribute_assignment()
    bootstrap = {h["target"] for h in patched if h["path"] == "src/feelies/bootstrap.py"}
    leftover = sorted(bootstrap & _INJECTED_BOOTSTRAP_TARGETS)
    assert leftover == [], (
        "post-construction assignment still on bootstrap; "
        "constructor injection required: " + ", ".join(leftover)
    )


def test_s17_external_assignment_only_on_composition_root_allowlist() -> None:
    found: Counter[tuple[str, str]] = Counter(
        (h["path"].replace("\\", "/"), h["target"]) for h in external_attribute_assignment()
    )
    allowed: Counter[tuple[str, str]] = Counter(
        (row.path, row.target) for row in COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST
    )
    _pin_counters(found, allowed, "external attribute assignment")
    assert all(row.reason.strip() for row in COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST)


def test_s17_private_reach_only_on_composition_root_allowlist() -> None:
    found: Counter[tuple[str, str]] = Counter(
        (h["path"].replace("\\", "/"), h["expr"]) for h in cross_object_private()
    )
    allowed: Counter[tuple[str, str]] = Counter(
        (row.path, row.expr) for row in COMPOSITION_ROOT_PRIVATE_ALLOWLIST
    )
    _pin_counters(found, allowed, "cross-object private reach")
    assert all(row.reason.strip() for row in COMPOSITION_ROOT_PRIVATE_ALLOWLIST)
