"""Shared fixtures for alpha tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote
from feelies.features.definition import FeatureDefinition, WarmUpSpec


# ── Mock feature computation ─────────────────────────────────────────


class _SimpleSpreadCompute:
    """Compute mid-price from quote (for testing)."""

    def initial_state(self) -> dict:
        return {"count": 0}

    def update(self, quote: NBBOQuote, state: dict) -> float:
        state["count"] = state.get("count", 0) + 1
        bid = float(quote.bid)
        ask = float(quote.ask)
        return (bid + ask) / 2.0 if (bid and ask) else 0.0


# ── Mock alpha module ─────────────────────────────────────────────────


class MockAlpha:
    """Minimal AlphaModule implementation for tests."""

    def __init__(
        self,
        alpha_id: str = "mock_alpha",
        version: str = "1.0",
        required_features: frozenset[str] | None = None,
        symbols: frozenset[str] | None = None,
        feature_defs: list[FeatureDefinition] | None = None,
    ) -> None:
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version=version,
            description="Mock alpha for testing",
            hypothesis="Test hypothesis",
            falsification_criteria=("test fails",),
            required_features=required_features or frozenset(),
            symbols=symbols,
        )
        self._feature_defs = feature_defs or []

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> list[FeatureDefinition]:
        return self._feature_defs

    def validate(self) -> list[str]:
        return []


def _make_spread_feature() -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="spread",
        version="1.0",
        description="Mid price",
        depends_on=frozenset(),
        warm_up=WarmUpSpec(min_events=0, min_duration_ns=0),
        compute=_SimpleSpreadCompute(),
    )


@pytest.fixture
def clock() -> SimulatedClock:
    """Deterministic clock for tests."""
    return SimulatedClock(start_ns=1_000_000_000)


@pytest.fixture
def registry() -> AlphaRegistry:
    """Fresh alpha registry for each test."""
    return AlphaRegistry()


@pytest.fixture
def mock_alpha() -> MockAlpha:
    """Single mock alpha with spread feature."""
    return MockAlpha(feature_defs=[_make_spread_feature()])


@pytest.fixture
def sample_quote() -> NBBOQuote:
    """Sample NBBO quote for feature/signal tests."""
    return NBBOQuote(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id="AAPL:1700000000000000000:1",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("150.00"),
        ask=Decimal("150.02"),
        bid_size=100,
        ask_size=50,
        exchange_timestamp_ns=1_700_000_000_000_000_000,
    )
