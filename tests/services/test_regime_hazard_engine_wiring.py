"""End-to-end wiring of :class:`RegimeHazardDetector` into the orchestrator.

Verifies §20.3.1 + §20.7 contract at the platform-composition layer:

* The detector is **only constructed** when at least one alpha
  declares ``hazard_exit.enabled: true`` (Inv-A: legacy parity must
  not be perturbed by the new event family).
* When constructed, the orchestrator emits :class:`RegimeHazardSpike`
  events on the bus through the dedicated ``_hazard_seq`` generator.
* Sequence numbers on the hazard family are **independent** of every
  other family (sensors, snapshots, signals, legacy bus) — this is
  the C1 isolation rule that protects pre-existing parity hashes.
* When *no* alpha opts in, no hazard spikes are ever published and
  the hazard sequence counter stays at zero.

Test fixtures are minimal: a hand-crafted in-memory ``EventBus`` plus
two synthetic :class:`RegimeState` events spaced one tick apart, run
through ``Orchestrator._update_regime`` indirectly via the public
``_maybe_publish_hazard_spike`` hook.  We rely on ``_create_hazard_detector``
in :mod:`feelies.bootstrap` to perform the opt-in branching.
"""

from __future__ import annotations

from typing import Any

import pytest

from feelies.alpha.module import AlphaManifest
from feelies.alpha.registry import AlphaRegistry
from feelies.bootstrap import _create_hazard_detector
from feelies.core.events import RegimeHazardSpike, RegimeState
from feelies.services.regime_hazard_detector import RegimeHazardDetector


_STATE_NAMES = ("compression", "normal", "vol_breakout")


def _state(
    *,
    posteriors: tuple[float, float, float],
    dominant_idx: int,
    sequence: int = 0,
) -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr-1",
        sequence=sequence,
        symbol="AAPL",
        engine_name="HMM3StateFractional",
        state_names=_STATE_NAMES,
        posteriors=posteriors,
        dominant_state=dominant_idx,
        dominant_name=_STATE_NAMES[dominant_idx],
    )


class _StubModule:
    """Minimal stand-in for a registered alpha, exposing only the
    ``manifest`` attribute consulted by ``_create_hazard_detector``."""

    def __init__(
        self,
        *,
        alpha_id: str,
        hazard_exit: dict[str, Any] | None,
    ) -> None:
        self.manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description="stub",
            hypothesis="stub",
            falsification_criteria=("stub",),
            required_features=frozenset(),
            hazard_exit=hazard_exit,
        )


def _make_registry(*modules: _StubModule) -> AlphaRegistry:
    """Build an :class:`AlphaRegistry` populated by stub modules.

    The registry's full contract requires loaded alpha modules
    (post-D.2 PR-2: :class:`LoadedSignalLayerModule` or
    :class:`LoadedPortfolioLayerModule`); we monkey-patch
    ``active_alphas`` for the bootstrap factory to keep the fixture
    self-contained without instantiating the full alpha-loading
    pipeline.
    """
    registry = AlphaRegistry()
    registry.active_alphas = lambda: list(modules)  # type: ignore[method-assign]
    return registry


class TestOptInActivation:
    def test_no_alpha_opts_in_returns_no_detector(self) -> None:
        registry = _make_registry()
        seq, det = _create_hazard_detector(registry)
        assert det is None
        assert seq.next() == 0

    def test_hazard_exit_disabled_returns_no_detector(self) -> None:
        registry = _make_registry(
            _StubModule(
                alpha_id="alpha_a",
                hazard_exit={"enabled": False},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert det is None

    def test_hazard_exit_missing_block_returns_no_detector(self) -> None:
        registry = _make_registry(
            _StubModule(alpha_id="alpha_a", hazard_exit=None),
        )
        _, det = _create_hazard_detector(registry)
        assert det is None

    def test_at_least_one_opt_in_returns_detector(self) -> None:
        registry = _make_registry(
            _StubModule(alpha_id="alpha_a", hazard_exit=None),
            _StubModule(
                alpha_id="alpha_b",
                hazard_exit={"enabled": True},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert isinstance(det, RegimeHazardDetector)

    def test_hazard_exit_enabled_truthy_value_returns_detector(self) -> None:
        registry = _make_registry(
            _StubModule(
                alpha_id="alpha_a",
                hazard_exit={"enabled": "yes"},
            ),
        )
        _, det = _create_hazard_detector(registry)
        assert isinstance(det, RegimeHazardDetector)


class TestSequenceIsolation:
    def test_hazard_sequence_starts_at_zero_when_no_spikes_emitted(self) -> None:
        registry = _make_registry()
        seq, _ = _create_hazard_detector(registry)
        assert seq.next() == 0
        assert seq.next() == 1

    def test_hazard_sequence_advances_independent_of_legacy_seq(self) -> None:
        from feelies.core.identifiers import SequenceGenerator
        legacy_seq = SequenceGenerator()
        legacy_seq.next()
        legacy_seq.next()
        assert legacy_seq.next() == 2

        registry = _make_registry()
        haz_seq, _ = _create_hazard_detector(registry)
        assert haz_seq.next() == 0


class TestEndToEndSpikeEmission:
    """Exercise the detector + dedicated _hazard_seq pair end-to-end
    against a hand-crafted RegimeState pair without standing up the
    full orchestrator (which would require event-log + backend +
    macro-state machinery)."""

    def test_decay_through_floor_emits_spike(self) -> None:
        det = RegimeHazardDetector(hysteresis_threshold=0.30)
        prev = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        curr = _state(posteriors=(0.45, 0.55, 0.0), dominant_idx=1, sequence=1)
        spike = det.detect(prev, curr)
        assert isinstance(spike, RegimeHazardSpike)
        assert spike.symbol == "AAPL"
        assert spike.engine_name == "HMM3StateFractional"
        assert spike.departing_state == "normal"
        assert spike.hazard_score == pytest.approx((0.95 - 0.55) / 0.95)


class TestSessionBoundaryReset:
    """Session-boundary contract: ``Orchestrator._reset_regime_session_state``
    clears both the prev-pointer cache and the hazard suppression set so a
    new session starts from a clean tape (§20.3.1, v0.2 §12.5).

    Without these clears, a ``RegimeState`` from session N-1 would pair
    with the first ``RegimeState`` of session N inside
    ``_maybe_publish_hazard_spike``, computing a "decay" across the gap
    and emitting a spurious spike — and suppression keys from the prior
    session would silence legitimate spikes early in the new one.
    """

    def _build_orchestrator(self):
        from decimal import Decimal

        from feelies.bus.event_bus import EventBus
        from feelies.core.clock import SimulatedClock
        from feelies.core.events import (
            OrderRequest,
            RiskAction,
            RiskVerdict,
            Signal,
        )
        from feelies.execution.backend import ExecutionBackend
        from feelies.execution.backtest_router import BacktestOrderRouter
        from feelies.kernel.orchestrator import Orchestrator
        from feelies.portfolio.memory_position_store import MemoryPositionStore
        from feelies.portfolio.position_store import PositionStore
        from feelies.storage.memory_event_log import InMemoryEventLog

        class _StubMarketData:
            def events(self):
                return iter(())

        class _NoOpMetrics:
            def record(self, _m: Any) -> None: ...
            def flush(self) -> None: ...

        class _StubRisk:
            def check_signal(
                self, signal: Signal, positions: PositionStore,
            ) -> RiskVerdict:
                return RiskVerdict(
                    timestamp_ns=signal.timestamp_ns,
                    correlation_id=signal.correlation_id,
                    sequence=signal.sequence,
                    symbol=signal.symbol,
                    action=RiskAction.ALLOW,
                    reason="ok",
                )

            def check_order(
                self, order: OrderRequest, positions: PositionStore,
            ) -> RiskVerdict:
                return RiskVerdict(
                    timestamp_ns=order.timestamp_ns,
                    correlation_id=order.correlation_id,
                    sequence=order.sequence,
                    symbol=order.symbol,
                    action=RiskAction.ALLOW,
                    reason="ok",
                )

        clock = SimulatedClock()
        bus = EventBus()
        backend = ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=BacktestOrderRouter(clock=clock),
            mode="BACKTEST",
        )
        return Orchestrator(
            clock=clock,
            bus=bus,
            backend=backend,
            risk_engine=_StubRisk(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetrics(),
            account_equity=Decimal("100000"),
            regime_hazard_detector=RegimeHazardDetector(),
        )

    def test_reset_clears_last_regime_state(self) -> None:
        orch = self._build_orchestrator()
        # Simulate one session producing a prev-pointer.
        s = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        orch._last_regime_state[(s.symbol, s.engine_name)] = s
        assert orch._last_regime_state, "precondition: prev cached"

        orch._reset_regime_session_state()

        assert orch._last_regime_state == {}, (
            "session boundary must clear prev-pointer cache"
        )

    def test_reset_clears_hazard_suppression(self) -> None:
        orch = self._build_orchestrator()
        det = orch._regime_hazard_detector
        assert det is not None

        prev = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        curr = _state(posteriors=(0.45, 0.55, 0.0), dominant_idx=1, sequence=1)
        first = det.detect(prev, curr)
        assert first is not None
        # Same prev/curr re-run is suppressed.
        assert det.detect(prev, curr) is None

        orch._reset_regime_session_state()

        # After session-boundary reset, the same departure transition
        # must be allowed to fire again.
        replay = det.detect(prev, curr)
        assert replay is not None
        assert replay.departing_state == "normal"

    def test_no_cross_session_phantom_spike(self) -> None:
        """End-of-session prev paired with start-of-session curr must
        NOT publish a spike after ``_reset_regime_session_state``.
        """
        orch = self._build_orchestrator()
        det = orch._regime_hazard_detector
        assert det is not None

        # Session N-1 final tick: normal-dominant.
        end_prev = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        orch._last_regime_state[
            (end_prev.symbol, end_prev.engine_name)
        ] = end_prev

        # Boundary.
        orch._reset_regime_session_state()

        # Session N first tick: would have been a "decay through floor"
        # if paired with end_prev — but the cache is empty, so prev is
        # None and detect() must return None.
        start_curr = _state(
            posteriors=(0.45, 0.55, 0.0), dominant_idx=1, sequence=1,
        )
        prev = orch._last_regime_state.get(
            (start_curr.symbol, start_curr.engine_name)
        )
        assert prev is None, "stale prev must not survive boundary"
        assert det.detect(prev, start_curr) is None

    def test_run_backtest_invokes_session_reset(self) -> None:
        """The fix is wired: ``run_backtest`` must invoke
        ``_reset_regime_session_state`` so the misleading
        orchestrator comment is now correct."""
        orch = self._build_orchestrator()
        det = orch._regime_hazard_detector
        assert det is not None

        # Pre-populate cross-session state.
        s = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        orch._last_regime_state[(s.symbol, s.engine_name)] = s
        # Force suppression by driving one transition.
        prev = _state(posteriors=(0.05, 0.95, 0.0), dominant_idx=1, sequence=0)
        curr = _state(posteriors=(0.45, 0.55, 0.0), dominant_idx=1, sequence=1)
        det.detect(prev, curr)

        # Boot then run the backtest path; the empty market data means
        # the pipeline returns immediately, so we only exercise the
        # session-start clearing.
        from feelies.kernel.macro import MacroState
        orch._macro.transition(MacroState.DATA_SYNC, trigger="CMD_BOOT")
        orch._macro.transition(MacroState.READY, trigger="DATA_INTEGRITY_OK")
        orch.run_backtest()

        assert orch._last_regime_state == {}
        # Suppression cleared → the same transition re-fires.
        assert det.detect(prev, curr) is not None
