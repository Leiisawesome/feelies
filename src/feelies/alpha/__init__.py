"""Pluggable alpha module system.

An AlphaModule is the atomic unit of plug/unplug.  It bundles
hypothesis metadata, feature/sensor declarations, signal logic, and
risk budget into a standardized template that the platform can load,
validate, and execute without modification to the orchestrator or core
pipeline.

Assembly flow (post-D.2 PR-2b-ii, schema 1.1 only, single-path):
  1. :class:`AlphaLoader` parses ``.alpha.yaml`` files and dispatches on
     the declared ``layer:`` field.
  2. ``layer: SIGNAL`` resolves to a :class:`LoadedSignalLayerModule`
     (Phase-3 horizon-anchored, regime-gated contract);
     ``layer: PORTFOLIO`` resolves to a
     :class:`LoadedPortfolioLayerModule` (Phase-4 cross-sectional
     construction).  ``layer: LEGACY_SIGNAL`` is hard-rejected at parse
     time with a migration pointer (workstream D.2 PR-1).
  3. Loaded modules are registered with :class:`AlphaRegistry`; the
     registry routes SIGNAL alphas to :class:`HorizonSignalEngine` and
     PORTFOLIO alphas to :class:`CrossSectionalEngine` via the
     bootstrap-built composition engine.
  4. The orchestrator runs each layer engine on its own event-time
     boundary (``HorizonTick`` for SIGNAL, ``CrossSectionalContext``
     for PORTFOLIO) — there is no per-tick alpha dispatch.

The historical per-tick :class:`CompositeFeatureEngine` /
:class:`CompositeSignalEngine` / :class:`MultiAlphaEvaluator` plumbing
was deleted by workstream D.2 PR-2b-ii along with the
:class:`feelies.features.engine.FeatureEngine` and
:class:`feelies.signals.engine.SignalEngine` protocols.  D.2 PR-2b-iv
then deleted the surviving test scaffolding: the
:class:`feelies.core.events.FeatureVector` event,
:py:meth:`AlphaModule.evaluate`, the orchestrator's
``feature_engine``/``signal_engine`` constructor parameters, and the
gated single-alpha branch in ``_process_tick_inner``.  All Signal /
SizedPositionIntent → OrderRequest dispatch now flows through the
orchestrator's bus subscribers (``_on_bus_signal`` /
``_on_bus_sized_intent``).
"""

from feelies.alpha.aggregation import AggregatedOrders, aggregate_intents
from feelies.alpha.arbitration import EdgeWeightedArbitrator, SignalArbitrator
from feelies.alpha.discovery import discover_alpha_specs, load_and_register
from feelies.alpha.fill_attribution import (
    AlphaContribution,
    AttributionRecord,
    FillAttributionLedger,
)
from feelies.alpha.intent_set import IntentSet
from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
)
from feelies.alpha.loader import AlphaLoadError, AlphaLoader
from feelies.alpha.module import (
    AlphaManifest,
    AlphaModule,
    AlphaRiskBudget,
    ParameterDef,
)
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.alpha.validation import validate_alpha_set

__all__ = [
    "AggregatedOrders",
    "aggregate_intents",
    "AlphaBudgetRiskWrapper",
    "AlphaContribution",
    "AlphaLifecycle",
    "AlphaLifecycleState",
    "AlphaLoadError",
    "AlphaLoader",
    "AlphaManifest",
    "AlphaModule",
    "AlphaRegistry",
    "AlphaRegistryError",
    "AlphaRiskBudget",
    "AttributionRecord",
    "discover_alpha_specs",
    "EdgeWeightedArbitrator",
    "FillAttributionLedger",
    "GateRequirements",
    "IntentSet",
    "load_and_register",
    "ParameterDef",
    "PromotionEvidence",
    "SignalArbitrator",
    "validate_alpha_set",
]
