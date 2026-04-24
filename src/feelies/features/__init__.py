"""Feature engine layer — stateful computation from event streams."""

from feelies.features.aggregator import HorizonAggregator
from feelies.features.definition import (
    FeatureComputation,
    FeatureDefinition,
    WarmUpSpec,
)
from feelies.features.legacy_shim import LegacyFeatureShim
from feelies.features.protocol import HorizonFeature

__all__ = [
    "FeatureComputation",
    "FeatureDefinition",
    "HorizonAggregator",
    "HorizonFeature",
    "LegacyFeatureShim",
    "WarmUpSpec",
]
