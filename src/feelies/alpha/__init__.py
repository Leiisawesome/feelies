"""Pluggable alpha module system.

An AlphaModule is the atomic unit of plug/unplug.  It bundles
hypothesis metadata, feature definitions, signal logic, and risk
budget into a standardized template that the system can load, validate,
and execute without modification to the orchestrator or core pipeline.

Assembly flow:
  1. Create AlphaModule implementations
  2. Register them with AlphaRegistry
  3. Build CompositeFeatureEngine and CompositeSignalEngine from the registry
  4. Inject composites into the Orchestrator as FeatureEngine / SignalEngine
  5. The orchestrator runs identically to the single-alpha case
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
from feelies.alpha.loader import AlphaLoadError, AlphaLoader, LoadedAlphaModule
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
    "LoadedAlphaModule",
    "MultiAlphaEvaluator",
    "ParameterDef",
    "PromotionEvidence",
    "SignalArbitrator",
    "validate_alpha_set",
]
