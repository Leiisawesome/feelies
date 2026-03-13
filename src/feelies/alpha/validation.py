"""Cross-alpha validation — feature conflicts, dependency cycles, coverage.

Validates constraints that span multiple alpha modules.  Per-alpha
validation is handled by each module's ``validate()`` method; this
module handles the interactions between modules.
"""

from __future__ import annotations

from collections.abc import Sequence

from feelies.alpha.module import AlphaModule
from feelies.features.definition import FeatureDefinition


def validate_alpha_set(alphas: Sequence[AlphaModule]) -> list[str]:
    """Run all cross-alpha validation checks.

    Returns a list of error messages.  Empty list means the set is
    valid.
    """
    errors: list[str] = []
    errors.extend(_check_feature_version_conflicts(alphas))
    errors.extend(_check_dependency_cycles(alphas))
    errors.extend(_check_required_features_coverage(alphas))
    return errors


def _check_feature_version_conflicts(
    alphas: Sequence[AlphaModule],
) -> list[str]:
    """Detect when two alphas declare the same feature_id with different versions."""
    errors: list[str] = []
    seen: dict[str, tuple[str, str]] = {}

    for alpha in alphas:
        alpha_id = alpha.manifest.alpha_id
        for fdef in alpha.feature_definitions():
            prev = seen.get(fdef.feature_id)
            if prev is None:
                seen[fdef.feature_id] = (fdef.version, alpha_id)
            elif prev[0] != fdef.version:
                errors.append(
                    f"Feature '{fdef.feature_id}' version conflict: "
                    f"alpha '{prev[1]}' declares v{prev[0]}, "
                    f"alpha '{alpha_id}' declares v{fdef.version}"
                )

    return errors


def _check_dependency_cycles(
    alphas: Sequence[AlphaModule],
) -> list[str]:
    """Detect circular dependencies in the merged feature dependency graph."""
    all_defs = _collect_feature_defs(alphas)
    dep_graph: dict[str, frozenset[str]] = {
        fdef.feature_id: fdef.depends_on for fdef in all_defs.values()
    }
    return _find_cycles(dep_graph)


def _check_required_features_coverage(
    alphas: Sequence[AlphaModule],
) -> list[str]:
    """Verify every alpha's required_features are provided by some module."""
    errors: list[str] = []
    all_defs = _collect_feature_defs(alphas)
    available = frozenset(all_defs.keys())

    for alpha in alphas:
        manifest = alpha.manifest
        missing = manifest.required_features - available
        if missing:
            errors.append(
                f"Alpha '{manifest.alpha_id}' requires features not "
                f"provided by any registered module: {sorted(missing)}"
            )

    return errors


# ── Internal helpers ─────────────────────────────────────────────────


def _collect_feature_defs(
    alphas: Sequence[AlphaModule],
) -> dict[str, FeatureDefinition]:
    """Merge feature definitions across alphas (first-seen wins for dedup)."""
    merged: dict[str, FeatureDefinition] = {}
    for alpha in alphas:
        for fdef in alpha.feature_definitions():
            if fdef.feature_id not in merged:
                merged[fdef.feature_id] = fdef
    return merged


def _find_cycles(graph: dict[str, frozenset[str]]) -> list[str]:
    """Detect cycles in a directed graph via iterative DFS.

    Returns a list of error messages describing each cycle found.
    """
    errors: list[str] = []
    white = set(graph.keys())
    gray: set[str] = set()
    black: set[str] = set()

    for start in list(graph.keys()):
        if start not in white:
            continue

        stack: list[tuple[str, bool]] = [(start, False)]
        path: list[str] = []

        while stack:
            node, returning = stack.pop()

            if returning:
                gray.discard(node)
                black.add(node)
                if path and path[-1] == node:
                    path.pop()
                continue

            if node in black:
                continue

            if node in gray:
                cycle_start = path.index(node) if node in path else 0
                cycle = path[cycle_start:] + [node]
                errors.append(
                    f"Feature dependency cycle: {' -> '.join(cycle)}"
                )
                continue

            white.discard(node)
            gray.add(node)
            path.append(node)

            stack.append((node, True))

            for dep in graph.get(node, frozenset()):
                if dep in graph:
                    stack.append((dep, False))

    return errors
