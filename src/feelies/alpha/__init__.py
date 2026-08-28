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

Lifecycle, promotion gates, evidence schemas and the promotion ledger are
NOT here — they moved to :mod:`feelies.promotion` (2026-08-12). This package
is load-time and runtime only. ``AlphaRegistry`` depends on that package;
nothing there depends back on this one.
"""

from feelies.alpha.discovery import (
    discover_alpha_specs,
    discover_research_alpha_specs,
    load_and_register,
)
from feelies.alpha.loader import AlphaLoadError, AlphaLoader
from feelies.alpha.module import (
    AlphaManifest,
    AlphaModule,
    AlphaRiskBudget,
    ParameterDef,
)
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.alpha.validation import validate_alpha_set

__all__ = [
    "AlphaLoadError",
    "AlphaLoader",
    "AlphaManifest",
    "AlphaModule",
    "AlphaRegistry",
    "AlphaRegistryError",
    "AlphaRiskBudget",
    "discover_alpha_specs",
    "discover_research_alpha_specs",
    "load_and_register",
    "ParameterDef",
    "validate_alpha_set",
]
