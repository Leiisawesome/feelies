"""Alpha registry — lifecycle management for pluggable alpha modules.

The registry is the single point of registration for all alpha modules.
It collects feature definitions across modules, detects conflicts, and
provides the module set to the composite engines.

Registration rules:
  - Alphas must be registered before orchestrator.boot(), not during
    pipeline execution.
  - Feature ID + version conflicts across alphas are rejected.
  - Unregistration only when macro state is READY or INIT (enforced
    by the caller; the registry itself is state-agnostic).
"""

from __future__ import annotations

from collections.abc import Sequence

from feelies.alpha.module import AlphaModule
from feelies.alpha.validation import validate_alpha_set
from feelies.features.definition import FeatureDefinition


class AlphaRegistryError(Exception):
    """Raised when alpha registration fails validation."""


class AlphaRegistry:
    """Manages the set of registered alpha modules.

    Thread-safety: not thread-safe.  All registration happens at
    boot time before the pipeline runs (single-threaded init phase).
    """

    def __init__(self) -> None:
        self._alphas: dict[str, AlphaModule] = {}
        self._feature_cache: list[FeatureDefinition] | None = None

    def register(self, alpha: AlphaModule) -> None:
        """Register an alpha module.

        Validates the module in isolation (via ``alpha.validate()``)
        and checks for ID conflicts with already-registered modules.

        Raises ``AlphaRegistryError`` on validation failure or
        duplicate alpha_id.
        """
        manifest = alpha.manifest
        alpha_id = manifest.alpha_id

        if alpha_id in self._alphas:
            raise AlphaRegistryError(
                f"Alpha '{alpha_id}' is already registered"
            )

        errors = alpha.validate()
        if errors:
            raise AlphaRegistryError(
                f"Alpha '{alpha_id}' failed validation: "
                + "; ".join(errors)
            )

        self._alphas[alpha_id] = alpha
        self._feature_cache = None

    def unregister(self, alpha_id: str) -> None:
        """Remove an alpha module from the registry.

        The caller is responsible for ensuring the pipeline is not
        running when this is called.

        Raises ``KeyError`` if the alpha_id is not registered.
        """
        if alpha_id not in self._alphas:
            raise KeyError(f"Alpha '{alpha_id}' is not registered")
        del self._alphas[alpha_id]
        self._feature_cache = None

    def get(self, alpha_id: str) -> AlphaModule:
        """Retrieve a registered alpha by ID.

        Raises ``KeyError`` if not found.
        """
        return self._alphas[alpha_id]

    def active_alphas(self) -> Sequence[AlphaModule]:
        """All currently registered alpha modules in registration order."""
        return list(self._alphas.values())

    def alpha_ids(self) -> frozenset[str]:
        """Set of all registered alpha IDs."""
        return frozenset(self._alphas.keys())

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        """Merged, deduplicated feature definitions across all alphas.

        Features with the same feature_id + version are deduplicated.
        This method caches the result until the registry changes.

        Raises ``AlphaRegistryError`` if feature version conflicts
        exist (same feature_id, different version across alphas).
        """
        if self._feature_cache is not None:
            return self._feature_cache

        seen: dict[str, FeatureDefinition] = {}
        for alpha in self._alphas.values():
            for fdef in alpha.feature_definitions():
                existing = seen.get(fdef.feature_id)
                if existing is None:
                    seen[fdef.feature_id] = fdef
                elif existing.version != fdef.version:
                    raise AlphaRegistryError(
                        f"Feature '{fdef.feature_id}' version conflict: "
                        f"'{existing.version}' vs '{fdef.version}'"
                    )

        self._feature_cache = list(seen.values())
        return self._feature_cache

    def validate_all(self) -> dict[str, list[str]]:
        """Run full validation across all registered alphas.

        Returns a mapping of alpha_id to error messages.  Empty dict
        means all alphas are valid.  Runs both per-alpha validation
        and cross-alpha checks (feature conflicts, dependency cycles,
        required features coverage).
        """
        per_alpha: dict[str, list[str]] = {}

        for alpha_id, alpha in self._alphas.items():
            errors = alpha.validate()
            if errors:
                per_alpha[alpha_id] = errors

        cross_errors = validate_alpha_set(list(self._alphas.values()))
        if cross_errors:
            per_alpha["__cross_alpha__"] = cross_errors

        return per_alpha

    def __len__(self) -> int:
        return len(self._alphas)

    def __contains__(self, alpha_id: str) -> bool:
        return alpha_id in self._alphas
