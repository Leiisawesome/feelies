"""Tests for CompositeSignalEngine — multi-alpha evaluation and arbitration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from feelies.alpha.composite import CompositeSignalEngine
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.core.events import FeatureVector, Signal, SignalDirection
from feelies.features.definition import FeatureDefinition


# ── Mock alpha module ───────────────────────────────────────────────


class _StubAlpha:
    """Configurable mock alpha that returns a fixed signal or None."""

    def __init__(
        self,
        alpha_id: str,
        signal: Signal | None = None,
        symbols: frozenset[str] | None = None,
    ) -> None:
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description="stub",
            hypothesis="test",
            falsification_criteria=("never",),
            required_features=frozenset(),
            symbols=symbols,
        )
        self._signal = signal

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        return []

    def evaluate(self, features: FeatureVector) -> Signal | None:
        return self._signal

    def validate(self) -> list[str]:
        return []


# ── Helpers ─────────────────────────────────────────────────────────


def _make_features(
    symbol: str = "AAPL",
    warm: bool = True,
    stale: bool = False,
) -> FeatureVector:
    return FeatureVector(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        feature_version="v1",
        values={"spread": 0.01},
        warm=warm,
        stale=stale,
    )


def _make_signal(
    direction: SignalDirection = SignalDirection.LONG,
    strength: float = 0.8,
    edge_bps: float = 2.0,
    strategy_id: str = "stub",
    symbol: str = "AAPL",
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )


def _build_engine(*alphas: _StubAlpha) -> CompositeSignalEngine:
    registry = AlphaRegistry()
    for alpha in alphas:
        registry.register(alpha)
    return CompositeSignalEngine(registry)


# ── Tests ───────────────────────────────────────────────────────────


class TestWarmGate:
    def test_cold_features_suppressed(self) -> None:
        sig = _make_signal()
        alpha = _StubAlpha("a1", signal=sig)
        engine = _build_engine(alpha)
        result = engine.evaluate(_make_features(warm=False))
        assert result is None


class TestStaleGate:
    def test_stale_entry_signal_suppressed(self) -> None:
        sig = _make_signal(direction=SignalDirection.LONG)
        alpha = _StubAlpha("a1", signal=sig)
        engine = _build_engine(alpha)
        result = engine.evaluate(_make_features(stale=True))
        assert result is None

    def test_stale_flat_signal_passes(self) -> None:
        sig = _make_signal(direction=SignalDirection.FLAT)
        alpha = _StubAlpha("a1", signal=sig)
        engine = _build_engine(alpha)
        result = engine.evaluate(_make_features(stale=True))
        assert result is not None
        assert result.direction == SignalDirection.FLAT


class TestSingleAlpha:
    def test_signal_passes_through(self) -> None:
        sig = _make_signal(direction=SignalDirection.LONG, strength=0.9)
        alpha = _StubAlpha("a1", signal=sig)
        engine = _build_engine(alpha)
        result = engine.evaluate(_make_features())
        assert result is not None
        assert result.direction == SignalDirection.LONG
        assert result.strength == 0.9


class TestNoSignal:
    def test_no_alpha_signal_returns_none(self) -> None:
        alpha = _StubAlpha("a1", signal=None)
        engine = _build_engine(alpha)
        result = engine.evaluate(_make_features())
        assert result is None

    def test_multiple_alphas_all_none_returns_none(self) -> None:
        a1 = _StubAlpha("a1", signal=None)
        a2 = _StubAlpha("a2", signal=None)
        engine = _build_engine(a1, a2)
        result = engine.evaluate(_make_features())
        assert result is None
