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

Lifecycle integration:
  - Each registered alpha optionally carries an AlphaLifecycle SM.
  - ``active_alphas()`` filters by lifecycle state when lifecycles
    are attached (PAPER and LIVE are active; RESEARCH and
    QUARANTINED generate paper signals only on explicit request).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
)
from feelies.alpha.module import AlphaModule
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.alpha.validation import validate_alpha_set
from feelies.core.clock import Clock
from feelies.features.definition import FeatureDefinition

_logger = logging.getLogger(__name__)


class AlphaRegistryError(Exception):
    """Raised when alpha registration fails validation."""


class UnresolvedDependencyError(AlphaRegistryError):
    """Raised when a SIGNAL alpha declares ``depends_on_sensors`` that
    references a sensor not registered in the platform's
    :class:`feelies.sensors.registry.SensorRegistry`.

    Plan §6.6 / §10 P3-α: the loader records the declared sensor IDs on
    a SIGNAL alpha; bootstrap then calls
    :py:meth:`AlphaRegistry.resolve_signal_dependencies` to fail fast at
    boot rather than silently evaluating with missing sensors.
    """


class AlphaRegistry:
    """Manages the set of registered alpha modules.

    Thread-safety: not thread-safe.  All registration happens at
    boot time before the pipeline runs (single-threaded init phase).

    Lifecycle: when a ``clock`` is provided at construction, each
    registered alpha gets an ``AlphaLifecycle`` state machine.
    ``active_alphas()`` then returns only alphas in PAPER or LIVE state.
    Without a clock, lifecycle tracking is disabled and all registered
    alphas are considered active (backward compatible).
    """

    def __init__(
        self,
        clock: Clock | None = None,
        gate_requirements: GateRequirements | None = None,
        promotion_ledger: PromotionLedger | None = None,
    ) -> None:
        self._alphas: dict[str, AlphaModule] = {}
        self._lifecycles: dict[str, AlphaLifecycle] = {}
        self._clock = clock
        self._gate_requirements = gate_requirements
        self._promotion_ledger = promotion_ledger
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
        if self._clock is not None:
            self._lifecycles[alpha_id] = AlphaLifecycle(
                alpha_id=alpha_id,
                clock=self._clock,
                gate_requirements=self._gate_requirements,
                ledger=self._promotion_ledger,
            )
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
        self._lifecycles.pop(alpha_id, None)
        self._feature_cache = None

    def get(self, alpha_id: str) -> AlphaModule:
        """Retrieve a registered alpha by ID.

        Raises ``KeyError`` if not found.
        """
        return self._alphas[alpha_id]

    def active_alphas(self) -> Sequence[AlphaModule]:
        """Alpha modules eligible for signal evaluation.

        When lifecycle tracking is enabled, returns only alphas in
        PAPER or LIVE state.  When disabled (no clock), returns all
        registered alphas (backward compatible).
        """
        if not self._lifecycles:
            return list(self._alphas.values())

        return [
            alpha for alpha_id, alpha in self._alphas.items()
            if alpha_id in self._lifecycles
            and self._lifecycles[alpha_id].is_active
        ]

    def alpha_ids(self) -> frozenset[str]:
        """Set of all registered alpha IDs."""
        return frozenset(self._alphas.keys())

    # ── SIGNAL-layer helpers (Phase 3-α) ──────────────────────────────

    def signal_alphas(self) -> list[AlphaModule]:
        """SIGNAL-layer alphas in deterministic registration order.

        A SIGNAL-layer alpha is identified by ``manifest.layer == "SIGNAL"``.
        The returned list preserves registration order so any
        downstream consumer (e.g. :class:`HorizonSignalEngine`) sees
        alphas in the same sequence across runs (Inv-C).

        Returns an empty list when no SIGNAL alphas are loaded — the
        bootstrap layer treats this as a signal to skip the entire
        Phase-3 wiring path (Inv-A).
        """
        return [
            alpha for alpha in self._alphas.values()
            if alpha.manifest.layer == "SIGNAL"
        ]

    def has_signal_alphas(self) -> bool:
        """True iff at least one ``layer: SIGNAL`` alpha is registered.

        The orchestrator and bootstrap use this to gate the
        :class:`SIGNAL_GATE` micro-state and the
        :class:`HorizonSignalEngine` subscription respectively.  When
        false, the bootstrap layer skips wiring the horizon signal
        engine entirely (Inv-A: SIGNAL-only deployments without
        portfolio layers take the short path).
        """
        return any(
            alpha.manifest.layer == "SIGNAL"
            for alpha in self._alphas.values()
        )

    # ── PORTFOLIO-layer helpers (Phase 4) ────────────────────────────

    def portfolio_alphas(self) -> list[AlphaModule]:
        """PORTFOLIO-layer alphas in deterministic registration order.

        A PORTFOLIO-layer alpha is identified by
        ``manifest.layer == "PORTFOLIO"``.  Returns an empty list when
        no PORTFOLIO alphas are loaded — the bootstrap layer treats this
        as a signal to skip the entire Phase-4 composition wiring path
        (Inv-A: SIGNAL-only deployments without portfolio layers do
        not pay for the cross-sectional construction pipeline).
        """
        return [
            alpha for alpha in self._alphas.values()
            if alpha.manifest.layer == "PORTFOLIO"
        ]

    def has_portfolio_alphas(self) -> bool:
        """True iff at least one ``layer: PORTFOLIO`` alpha is registered."""
        return any(
            alpha.manifest.layer == "PORTFOLIO"
            for alpha in self._alphas.values()
        )

    def resolve_signal_dependencies(
        self, known_sensor_ids: frozenset[str]
    ) -> None:
        """Validate every SIGNAL alpha's ``depends_on_sensors`` block.

        Called once at bootstrap, after all SIGNAL alphas are
        registered and the :class:`SensorRegistry` is fully populated.
        Raises :class:`UnresolvedDependencyError` listing every
        unsatisfied ``(alpha_id, sensor_id)`` pair so the operator sees
        all issues in a single error rather than fail-on-first.

        Topological-order note: SIGNAL alphas declare a flat
        ``depends_on_sensors`` list (no inter-alpha dependencies in
        Phase 3-α), so no DAG construction is required here.  The
        ordering invariant (Inv-C) is preserved because
        :py:meth:`signal_alphas` returns alphas in registration order
        and :py:meth:`AlphaLoader` enforces ``depends_on_sensors`` to
        be sorted+deduplicated at load time.
        """
        missing: list[tuple[str, str]] = []
        for alpha in self.signal_alphas():
            depends = getattr(alpha, "depends_on_sensors", ())
            for sensor_id in depends:
                if sensor_id not in known_sensor_ids:
                    missing.append((alpha.manifest.alpha_id, sensor_id))

        if missing:
            details = ", ".join(
                f"{alpha_id!r} requires {sid!r}" for alpha_id, sid in missing
            )
            raise UnresolvedDependencyError(
                "SIGNAL alpha(s) reference sensor IDs that are not "
                f"registered in the SensorRegistry: {details}.  Add the "
                "sensor specs to platform.yaml's sensors: block before "
                "loading these alphas."
            )

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

    # ── Lifecycle management ────────────────────────────────────

    def get_lifecycle(self, alpha_id: str) -> AlphaLifecycle | None:
        """Get the lifecycle state machine for an alpha.

        Returns ``None`` if lifecycle tracking is disabled or the alpha
        is not registered.
        """
        return self._lifecycles.get(alpha_id)

    def promote(
        self,
        alpha_id: str,
        evidence: PromotionEvidence,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """Promote an alpha to its next lifecycle state.

        Automatically determines the correct gate based on current state.
        Returns gate check errors (empty = success).

        Raises ``KeyError`` if alpha not registered.
        Raises ``AlphaRegistryError`` if lifecycle tracking is disabled.
        """
        lc = self._lifecycles.get(alpha_id)
        if lc is None:
            if alpha_id not in self._alphas:
                raise KeyError(f"Alpha '{alpha_id}' is not registered")
            raise AlphaRegistryError(
                "Lifecycle tracking is disabled (no clock provided)"
            )

        state = lc.state
        if state == AlphaLifecycleState.RESEARCH:
            return lc.promote_to_paper(evidence, correlation_id=correlation_id)
        if state == AlphaLifecycleState.PAPER:
            return lc.promote_to_live(evidence, correlation_id=correlation_id)
        if state == AlphaLifecycleState.QUARANTINED:
            return lc.revalidate_to_paper(evidence, correlation_id=correlation_id)

        return [f"Alpha '{alpha_id}' in state {state.name} cannot be promoted"]

    def quarantine(
        self,
        alpha_id: str,
        reason: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Move a LIVE alpha to QUARANTINED state.

        Raises ``KeyError`` if alpha not registered.
        Raises ``AlphaRegistryError`` if lifecycle tracking is disabled.
        """
        lc = self._lifecycles.get(alpha_id)
        if lc is None:
            if alpha_id not in self._alphas:
                raise KeyError(f"Alpha '{alpha_id}' is not registered")
            raise AlphaRegistryError(
                "Lifecycle tracking is disabled (no clock provided)"
            )
        lc.quarantine(reason, correlation_id=correlation_id)

    def decommission(
        self,
        alpha_id: str,
        reason: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Move a QUARANTINED alpha to DECOMMISSIONED state.

        Raises ``KeyError`` if alpha not registered.
        Raises ``AlphaRegistryError`` if lifecycle tracking is disabled.
        """
        lc = self._lifecycles.get(alpha_id)
        if lc is None:
            if alpha_id not in self._alphas:
                raise KeyError(f"Alpha '{alpha_id}' is not registered")
            raise AlphaRegistryError(
                "Lifecycle tracking is disabled (no clock provided)"
            )
        lc.decommission(reason, correlation_id=correlation_id)

    def lifecycle_states(self) -> dict[str, AlphaLifecycleState]:
        """Current lifecycle state for all registered alphas."""
        return {
            alpha_id: lc.state
            for alpha_id, lc in self._lifecycles.items()
        }

    @property
    def promotion_ledger(self) -> PromotionLedger | None:
        """The :class:`PromotionLedger` shared across all registered
        alphas, or ``None`` when forensic ledgering is disabled.

        Workstream F-1: read-only accessor for downstream tooling
        (operator CLI, audit reports, CPCV+DSR gate in workstream C)
        that needs to inspect committed transitions without holding a
        direct reference to the bootstrap-side ledger instance.
        """
        return self._promotion_ledger

    # ── Dunder methods ────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._alphas)

    def __contains__(self, alpha_id: str) -> bool:
        return alpha_id in self._alphas
