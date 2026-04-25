"""Pluggable alpha module system.

An AlphaModule is the atomic unit of plug/unplug.  It bundles
hypothesis metadata, feature/sensor declarations, signal logic, and
risk budget into a standardized template that the platform can load,
validate, and execute without modification to the orchestrator or core
pipeline.

Assembly flow (post-D.2 PR-2a, schema 1.1 only):
  1. AlphaLoader parses ``.alpha.yaml`` files and dispatches on the
     declared ``layer:`` field.
  2. ``layer: SIGNAL`` resolves to a :class:`LoadedSignalLayerModule`
     (Phase-3 horizon-anchored, regime-gated contract);
     ``layer: PORTFOLIO`` resolves to a
     :class:`LoadedPortfolioLayerModule` (Phase-4 cross-sectional
     construction).  ``layer: LEGACY_SIGNAL`` is hard-rejected at parse
     time with a migration pointer.
  3. Loaded modules are registered with :class:`AlphaRegistry`; the
     registry routes SIGNAL alphas to :class:`HorizonSignalEngine` and
     PORTFOLIO alphas to :class:`CrossSectionalEngine` via the
     bootstrap-built composition engine.
  4. The orchestrator runs each layer engine on its own event-time
     boundary (``HorizonTick`` for SIGNAL, ``CrossSectionalContext``
     for PORTFOLIO) — there is no longer a per-tick alpha dispatch.

The historical per-tick :class:`CompositeFeatureEngine` /
:class:`CompositeSignalEngine` / :class:`MultiAlphaEvaluator` plumbing
remains importable for backward compatibility but is unreachable from
the post-D.2 load path; D.2 PR-2b will delete it along with the
:class:`feelies.core.events.FeatureVector` event itself.
"""

from feelies.alpha.aggregation import AggregatedOrders, aggregate_intents
from feelies.alpha.arbitration import EdgeWeightedArbitrator, SignalArbitrator
from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
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
from feelies.alpha.multi_alpha_evaluator import MultiAlphaEvaluator
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
    "CompositeFeatureEngine",
    "CompositeSignalEngine",
    "discover_alpha_specs",
    "EdgeWeightedArbitrator",
    "FillAttributionLedger",
    "GateRequirements",
    "IntentSet",
    "load_and_register",
    "MultiAlphaEvaluator",
    "ParameterDef",
    "PromotionEvidence",
    "SignalArbitrator",
    "validate_alpha_set",
]
