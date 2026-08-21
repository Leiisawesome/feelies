"""S17 — external assignment only at the composition-root allowlist.

G39: objects must be valid after ``__init__``. The five post-construction
assignments in ``bootstrap.py`` move into constructor injection; every
remaining external assignment and cross-object private access is a
declared composition-root allowlist row, not an implicit patch.
"""

from __future__ import annotations

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


def _load_allowlists() -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    try:
        from feelies.core.wiring_manifest import (
            COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST,
            COMPOSITION_ROOT_PRIVATE_ALLOWLIST,
        )
    except ImportError:
        return frozenset(), frozenset()
    return (
        frozenset(COMPOSITION_ROOT_ASSIGNMENT_ALLOWLIST),
        frozenset(COMPOSITION_ROOT_PRIVATE_ALLOWLIST),
    )


def test_s17_bootstrap_assignments_are_constructor_injected() -> None:
    patched = external_attribute_assignment()
    bootstrap = {
        h["target"]
        for h in patched
        if h["path"] == "src/feelies/bootstrap.py"
    }
    leftover = sorted(bootstrap & _INJECTED_BOOTSTRAP_TARGETS)
    assert leftover == [], (
        "post-construction assignment still on bootstrap; "
        "constructor injection required: " + ", ".join(leftover)
    )


def test_s17_external_assignment_only_on_composition_root_allowlist() -> None:
    allowed, _private = _load_allowlists()
    patched = external_attribute_assignment()
    extra = [h for h in patched if (h["path"], h["target"]) not in allowed]
    assert extra == [], (
        f"{len(extra)} external attribute assignment(s) outside the "
        f"composition-root allowlist. First: {extra[0]['path']}:{extra[0]['line']} "
        f"{extra[0]['target']}"
    )


def test_s17_private_reach_only_on_composition_root_allowlist() -> None:
    _allowed, private_allowed = _load_allowlists()
    private = cross_object_private()
    extra = [h for h in private if (h["path"], h["expr"]) not in private_allowed]
    assert extra == [], (
        f"{len(extra)} cross-object private access site(s) outside the "
        f"composition-root allowlist. First: {extra[0]['path']}:{extra[0]['line']} "
        f"{extra[0]['expr']}"
    )
