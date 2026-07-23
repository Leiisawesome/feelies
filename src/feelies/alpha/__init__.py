"""Pluggable alpha module system.

An AlphaModule is the atomic unit of plug/unplug.  It bundles
hypothesis metadata, feature/sensor declarations, signal logic, and
risk budget into a standardized template that the platform can load,
validate, and execute without modification to the orchestrator or core
pipeline.

Assembly flow (schema 1.1, SIGNAL / PORTFOLIO only):
  1. :class:`AlphaLoader` parses ``.alpha.yaml`` and dispatches on ``layer:``.
  2. SIGNAL → :class:`LoadedSignalLayerModule`; PORTFOLIO →
     :class:`LoadedPortfolioLayerModule`. Retired layers are hard-rejected
     (see ``docs/migration/schema_1_0_to_1_1.md``).
  3. :class:`AlphaRegistry` routes SIGNAL alphas to
     :class:`HorizonSignalEngine` and PORTFOLIO alphas to the composition
     engine.
  4. The orchestrator runs each layer on its event-time boundary
     (``HorizonTick`` / ``CrossSectionalContext``) via bus subscribers
     (``_on_bus_signal`` / ``_on_bus_sized_intent``).
"""

from feelies.alpha.aggregation import AggregatedOrders, aggregate_intents
from feelies.alpha.arbitration import EdgeWeightedArbitrator, SignalArbitrator
from feelies.alpha.discovery import (
    discover_alpha_specs,
    discover_research_alpha_specs,
    load_and_register,
)
from feelies.alpha.fill_attribution import (
    AlphaContribution,
    AttributionRecord,
    FillAttributionLedger,
)
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
from feelies.alpha.promotion_evidence import (
    GATE_EVIDENCE_REQUIREMENTS,
    KIND_TO_TYPE,
    PROMOTE_CAPITAL_TIER_TRIGGER,
    CapitalStageEvidence,
    CapitalStageTier,
    CPCVEvidence,
    DSREvidence,
    GateId,
    GateThresholds,
    PaperWindowEvidence,
    QuarantineTriggerEvidence,
    ResearchAcceptanceEvidence,
    RevalidationEvidence,
    evidence_to_metadata,
    metadata_to_evidence,
    required_evidence_types,
    validate_gate,
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
    "CapitalStageEvidence",
    "CapitalStageTier",
    "CPCVEvidence",
    "discover_alpha_specs",
    "discover_research_alpha_specs",
    "DSREvidence",
    "EdgeWeightedArbitrator",
    "evidence_to_metadata",
    "FillAttributionLedger",
    "GATE_EVIDENCE_REQUIREMENTS",
    "GateId",
    "GateRequirements",
    "GateThresholds",
    "KIND_TO_TYPE",
    "load_and_register",
    "metadata_to_evidence",
    "PaperWindowEvidence",
    "ParameterDef",
    "PROMOTE_CAPITAL_TIER_TRIGGER",
    "PromotionEvidence",
    "QuarantineTriggerEvidence",
    "required_evidence_types",
    "ResearchAcceptanceEvidence",
    "RevalidationEvidence",
    "SignalArbitrator",
    "validate_alpha_set",
    "validate_gate",
]
