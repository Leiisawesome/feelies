"""Audit P0 H-1 / P1 HM-1 / P1 H-2: hazard-exit controller wiring tests.

The controller used to live exclusively inside
``_create_composition_layer`` and was only built when at least one
PORTFOLIO alpha opted in.  A SIGNAL-layer alpha that declared
``hazard_exit.enabled: true`` therefore got a detector emitting
``RegimeHazardSpike`` events to a bus with no subscriber — a dead
safety control.

These tests bypass the alpha loader and G16 entirely to focus on the
new helper :func:`feelies.bootstrap._create_hazard_exit_controller`
and its derivation rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import _create_hazard_exit_controller
from feelies.bus.event_bus import EventBus
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.hazard_exit import HazardExitController


def _manifest(
    *,
    alpha_id: str,
    hazard_exit: dict[str, Any] | None,
) -> AlphaManifest:
    return AlphaManifest(
        alpha_id=alpha_id,
        version="1.0.0",
        description="test",
        hypothesis="test",
        falsification_criteria=("stub",),
        required_features=frozenset(),
        risk_budget=AlphaRiskBudget(
            max_position_per_symbol=100,
            max_gross_exposure_pct=5.0,
            max_drawdown_pct=1.0,
            capital_allocation_pct=10.0,
        ),
        hazard_exit=hazard_exit,
    )


@dataclass
class _StubSignalModule:
    """Just enough surface for ``_create_hazard_exit_controller``."""

    manifest: AlphaManifest
    expected_half_life_seconds: int = 0
    # Note: no ``universe`` attribute — the helper falls back to the
    # platform-wide universe for SIGNAL modules.


@dataclass
class _StubPortfolioModule:
    manifest: AlphaManifest
    universe: tuple[str, ...]
    expected_half_life_seconds: int = 0


def _registry(*modules: object) -> AlphaRegistry:
    reg = AlphaRegistry()
    reg.active_alphas = lambda: list(modules)  # type: ignore[method-assign]
    return reg


def test_no_opt_in_returns_none() -> None:
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL",),
    )
    assert controller is None


def test_signal_layer_opt_in_constructs_controller() -> None:
    """Audit P0 H-1: SIGNAL-layer hazard_exit.enabled MUST wire."""
    module = _StubSignalModule(
        manifest=_manifest(
            alpha_id="sig_hazard_v1",
            hazard_exit={
                "enabled": True,
                "hazard_score_threshold": 0.4,
                "min_age_seconds": 5,
            },
        ),
        expected_half_life_seconds=60,
    )
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(module),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL", "MSFT"),
    )
    assert isinstance(controller, HazardExitController)
    assert "sig_hazard_v1" in controller.policies
    policy = controller.policies["sig_hazard_v1"]
    assert policy.hazard_score_threshold == 0.4
    assert policy.min_age_seconds == 5
    # HM-1 default: hard_exit_age_seconds = 2 × expected_half_life_seconds.
    assert policy.hard_exit_age_seconds == 120
    # SIGNAL alpha has no per-alpha universe — fall back to platform universe.
    assert policy.universe == ("AAPL", "MSFT")


def test_portfolio_layer_opt_in_uses_module_universe() -> None:
    module = _StubPortfolioModule(
        manifest=_manifest(
            alpha_id="pofi_hazard_v1",
            hazard_exit={
                "enabled": True,
                "hazard_score_threshold": 0.7,
            },
        ),
        universe=("AAPL", "GOOG", "MSFT"),
        expected_half_life_seconds=300,
    )
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(module),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL", "GOOG", "MSFT", "NVDA"),
    )
    assert isinstance(controller, HazardExitController)
    policy = controller.policies["pofi_hazard_v1"]
    # PORTFOLIO universe wins over fallback.
    assert policy.universe == ("AAPL", "GOOG", "MSFT")
    # HM-1: 2 × 300 = 600.
    assert policy.hard_exit_age_seconds == 600


def test_explicit_hard_exit_age_overrides_hm1_default() -> None:
    module = _StubSignalModule(
        manifest=_manifest(
            alpha_id="sig_explicit",
            hazard_exit={
                "enabled": True,
                "hard_exit_age_seconds": 1234,
            },
        ),
        expected_half_life_seconds=60,
    )
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(module),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL",),
    )
    assert controller is not None
    assert controller.policies["sig_explicit"].hard_exit_age_seconds == 1234


def test_zero_half_life_yields_none_hard_exit() -> None:
    """If the alpha declares no mechanism (half-life == 0), HM-1 cannot
    derive a hard-exit age — leave it None (controller skips hard-age
    exits for that alpha)."""
    module = _StubSignalModule(
        manifest=_manifest(
            alpha_id="sig_no_mech",
            hazard_exit={"enabled": True},
        ),
        expected_half_life_seconds=0,
    )
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(module),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL",),
    )
    assert controller is not None
    assert controller.policies["sig_no_mech"].hard_exit_age_seconds is None


def test_disabled_or_missing_block_skips_alpha() -> None:
    """Opt-in is gated on literal ``enabled: True`` per
    ``_hazard_block_enabled`` — false / missing / non-True values must
    not register a policy."""
    a = _StubSignalModule(
        manifest=_manifest(alpha_id="sig_a", hazard_exit=None),
    )
    b = _StubSignalModule(
        manifest=_manifest(
            alpha_id="sig_b", hazard_exit={"enabled": False},
        ),
    )
    c = _StubSignalModule(
        manifest=_manifest(
            alpha_id="sig_c", hazard_exit={"hazard_score_threshold": 0.5},
        ),
    )
    controller = _create_hazard_exit_controller(
        bus=EventBus(),
        registry=_registry(a, b, c),
        position_store=MemoryPositionStore(),
        fallback_universe=("AAPL",),
    )
    assert controller is None
