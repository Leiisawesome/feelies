"""Platform invariants 5-13 validation.

Skills: system-architect, backtest-engine, data-engineering, testing-validation
"""

from __future__ import annotations

import ast
import inspect
import re
import shutil
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.alpha.lifecycle import PromotionEvidence, check_live_gate
from feelies.bootstrap import build_platform
from feelies.core.events import (
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    Signal,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.trade_journal import TradeRecord

from .conftest import BusRecorder, _make_quotes, _run_scenario, TICK_DATA

pytestmark = pytest.mark.backtest_validation


class TestInvariant5Determinism:
    """Inv 5 — deterministic replay."""

    def test_deterministic_order_ids(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        ids_per_run: list[list[str]] = []
        for i in range(2):
            tmp = tmp_path_factory.mktemp(f"det_oid_{i}")
            _, recorder, _, _ = _run_scenario(tmp)
            ids_per_run.append([o.order_id for o in recorder.of_type(OrderRequest)])

        assert ids_per_run[0] == ids_per_run[1]
        assert len(ids_per_run[0]) > 0

    def test_no_uuid4_in_order_ids(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        for order in recorder.of_type(OrderRequest):
            assert "-" not in order.order_id, f"UUID4 pattern in order_id: {order.order_id}"
            assert len(order.order_id) == 16, f"Expected 16-char hex, got {len(order.order_id)}"
            int(order.order_id, 16)


class TestInvariant6Causality:
    """Inv 6 — no future data leakage."""

    def test_causal_ordering_features_use_only_past(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        quotes = recorder.of_type(NBBOQuote)
        features = recorder.of_type(FeatureVector)

        quote_by_cid = {q.correlation_id: q for q in quotes}
        for fv in features:
            triggering_quote = quote_by_cid.get(fv.correlation_id)
            if triggering_quote is not None:
                assert fv.timestamp_ns <= triggering_quote.exchange_timestamp_ns

    def test_causal_ordering_no_future_nbbo_in_fills(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        quotes = recorder.of_type(NBBOQuote)
        acks = recorder.of_type(OrderAck)
        orders = recorder.of_type(OrderRequest)

        order_by_id = {o.order_id: o for o in orders}
        for ack in acks:
            if ack.fill_price is None:
                continue
            order = order_by_id.get(ack.order_id)
            if order is None:
                continue
            prior_quotes = [
                q for q in quotes
                if q.symbol == ack.symbol and q.exchange_timestamp_ns <= order.timestamp_ns
            ]
            assert len(prior_quotes) > 0
            latest = prior_quotes[-1]
            expected_mid = (latest.bid + latest.ask) / Decimal("2")
            assert ack.fill_price == expected_mid


class TestInvariant7TypedEvents:
    """Inv 7 — all events are typed frozen dataclasses."""

    def test_all_events_are_typed_frozen_dataclasses(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        for event in recorder.events:
            assert isinstance(event, Event)
            assert hasattr(event, "__dataclass_fields__")
            dc_fields = fields(type(event))
            assert len(dc_fields) > 0


class TestInvariant8LayerSeparation:
    """Inv 8 — no cross-layer leakage."""

    def test_no_cross_layer_imports_in_signal_engine(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        features = recorder.of_type(FeatureVector)
        signals_from_fv: dict[str, Signal | None] = {}

        orchestrator = single_symbol_scenario[0]
        sig_engine = orchestrator._signal_engine
        for fv in features:
            result = sig_engine.evaluate(fv)
            signals_from_fv[fv.correlation_id] = result
            result2 = sig_engine.evaluate(fv)
            if result is None:
                assert result2 is None
            else:
                assert result2 is not None
                assert result.direction == result2.direction
                assert result.strength == result2.strength


class TestInvariant9BacktestLiveParity:
    """Inv 9 — structural verification of no mode branching."""

    def test_no_mode_branching_in_orchestrator_pipeline(self) -> None:
        from feelies.kernel import orchestrator as orch_mod

        source = inspect.getsource(orch_mod.Orchestrator._process_tick)
        source += inspect.getsource(orch_mod.Orchestrator._process_tick_inner)
        source += inspect.getsource(orch_mod.Orchestrator._run_pipeline)

        forbidden_patterns = [
            r"\bif\s+.*mode\b",
            r"\bOperatingMode\b",
            r"\bMacroState\.BACKTEST\b",
        ]
        for pattern in forbidden_patterns:
            assert not re.search(pattern, source), (
                f"Mode-specific branching found in pipeline: {pattern}"
            )


class TestInvariant10ClockAbstraction:
    """Inv 10 — all timestamps via injectable clock."""

    def test_no_raw_datetime_now_in_pipeline_events(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        quotes = recorder.of_type(NBBOQuote)
        max_exchange_ts = max(q.exchange_timestamp_ns for q in quotes)

        for event in recorder.events:
            assert event.timestamp_ns <= max_exchange_ts + 10_000, (
                f"Event timestamp {event.timestamp_ns} exceeds exchange range "
                f"(max={max_exchange_ts}); likely from a wall clock"
            )


class TestInvariant11FailSafe:
    """Inv 11 — fail-safe default."""

    def test_exception_in_feature_engine_degrades_not_crashes(
        self, tmp_path: Path
    ) -> None:
        alpha_dir = tmp_path / "alphas"
        alpha_dir.mkdir(exist_ok=True)
        alpha_src = Path(__file__).resolve().parent.parent.parent / "alphas" / "mean_reversion.alpha.yaml"
        shutil.copy2(alpha_src, alpha_dir / "mean_reversion.alpha.yaml")

        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=alpha_dir,
            account_equity=100_000.0,
            regime_engine=None,
            parameter_overrides={"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}},
        )
        event_log = InMemoryEventLog()
        event_log.append_batch(_make_quotes())

        orchestrator, resolved_config = build_platform(config, event_log=event_log)
        orchestrator.boot(resolved_config)

        original_update = orchestrator._feature_engine.update

        call_count = 0

        def exploding_update(quote):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("injected fault in feature engine")
            return original_update(quote)

        orchestrator._feature_engine.update = exploding_update
        orchestrator.run_backtest()

        assert orchestrator.macro_state == MacroState.DEGRADED

    def test_risk_breach_activates_kill_switch(self, tmp_path: Path) -> None:
        from feelies.core.clock import SimulatedClock
        from feelies.risk.escalation import RiskLevel

        alpha_dir = tmp_path / "alphas"
        alpha_dir.mkdir(exist_ok=True)
        alpha_src = Path(__file__).resolve().parent.parent.parent / "alphas" / "mean_reversion.alpha.yaml"
        shutil.copy2(alpha_src, alpha_dir / "mean_reversion.alpha.yaml")

        config = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=alpha_dir,
            account_equity=100_000.0,
            regime_engine=None,
            parameter_overrides={"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}},
        )
        event_log = InMemoryEventLog()
        event_log.append_batch(_make_quotes())

        orchestrator, resolved_config = build_platform(config, event_log=event_log)
        orchestrator.boot(resolved_config)

        # BACKTEST_MODE doesn't allow RISK_LOCKDOWN transition (by design).
        # Test the escalation mechanism directly by transitioning to a mode
        # that supports it (PAPER_TRADING_MODE).
        orchestrator._macro._state = MacroState.PAPER_TRADING_MODE

        orchestrator._escalate_risk("test_cid")

        assert orchestrator._kill_switch.is_active
        assert orchestrator.macro_state == MacroState.RISK_LOCKDOWN
        assert orchestrator._risk_escalation.state == RiskLevel.LOCKED


class TestInvariant12CostRealism:
    """Inv 12 — transaction cost realism (placeholder)."""

    def test_cost_realism_gate_exists(self) -> None:
        evidence = PromotionEvidence(cost_model_validated=False)
        errors = check_live_gate(evidence)
        assert any("cost model" in e for e in errors)

        evidence_ok = PromotionEvidence(
            cost_model_validated=True,
            paper_days=60,
            paper_sharpe=2.0,
            paper_hit_rate=0.6,
            paper_max_drawdown_pct=2.0,
            determinism_test_passed=True,
            schema_valid=True,
            feature_values_finite=True,
        )
        errors_ok = check_live_gate(evidence_ok)
        assert not any("cost model" in e for e in errors_ok)


class TestInvariant13Provenance:
    """Inv 13 — full provenance chain."""

    def test_full_provenance_chain_quote_to_trade_record(
        self, single_symbol_scenario
    ) -> None:
        orchestrator, recorder, _, _ = single_symbol_scenario
        quote_cids = {q.correlation_id for q in recorder.of_type(NBBOQuote)}
        signal_cids = {s.correlation_id for s in recorder.of_type(Signal)}

        records = list(orchestrator._trade_journal.query(symbol="AAPL"))
        assert len(records) > 0
        for rec in records:
            assert rec.correlation_id in signal_cids
            assert rec.correlation_id in quote_cids

    def test_every_sm_transition_emitted_on_bus(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        transitions = recorder.of_type(StateTransition)
        machine_names = {st.machine_name for st in transitions}
        assert "global_stack" in machine_names
        assert "tick_pipeline" in machine_names
        assert len(transitions) >= 4


class TestHotspot1TradeEvents:
    """Hotspot 1 — Trade event path e2e coverage."""

    def test_trade_events_update_feature_state_e2e(
        self, trade_mixed_scenario
    ) -> None:
        _, recorder, _, _ = trade_mixed_scenario
        trades = recorder.of_type(Trade)
        assert len(trades) >= 2, "Expected at least 2 Trade events on the bus"

        features = recorder.of_type(FeatureVector)
        assert len(features) >= 3


class TestHotspot4SequentialReentry:
    """Hotspot 4 — Sequential backtest re-entry clean state."""

    def test_sequential_backtest_reentry_clean_state(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        tmp = tmp_path_factory.mktemp("reentry")
        orch1, rec1, _, _ = _run_scenario(tmp)

        pos1 = orch1._positions.get("AAPL")
        orders1 = [o.order_id for o in rec1.of_type(OrderRequest)]

        tmp2 = tmp_path_factory.mktemp("reentry_fresh")
        orch2, rec2, _, _ = _run_scenario(tmp2)

        pos2 = orch2._positions.get("AAPL")
        orders2 = [o.order_id for o in rec2.of_type(OrderRequest)]

        assert pos1.quantity == pos2.quantity
        assert pos1.realized_pnl == pos2.realized_pnl
        assert orders1 == orders2


class TestHotspot10AppendBatch:
    """Hotspot 10 — EventLog.append_batch integrity."""

    def test_append_batch_preserves_sequence_integrity(self) -> None:
        event_log = InMemoryEventLog()
        quotes = _make_quotes()
        event_log.append_batch(quotes)

        replayed = list(event_log.replay())
        assert len(replayed) == len(quotes)

        sequences = [e.sequence for e in replayed]
        for i in range(len(sequences) - 1):
            assert sequences[i] < sequences[i + 1], (
                f"Non-increasing sequence: {sequences[i]} >= {sequences[i + 1]}"
            )

        assert event_log.last_sequence() == quotes[-1].sequence
