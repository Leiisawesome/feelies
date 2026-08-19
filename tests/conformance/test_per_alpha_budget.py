"""X4 — every strategy_id reaching the wrapper resolves to a budget or is refused.

G23: ``except KeyError: pass`` in ``AlphaBudgetRiskWrapper.check_order``
skips the entire per-alpha budget block — position limit, drawdown, and
exposure — for any ``strategy_id`` the registry does not know.  A config
typo or a failed registration takes the same path as a deliberate
synthetic, so the order proceeds unbudgeted.  Inv-11: unknown state
resolving to fewer constraints.

A strategy_id is fail-closed at this gate when it is refused with a
verdict that names it.  Substituting a default budget would still let
the order through under made-up limits; that is a different fail-open.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
)
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import RiskConfig

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "pathological"
    / "unregistered_strategy_id.yaml"
)
_REGISTERED_ID = "registered_alpha"
_SYMBOL = "AAPL"


def load_unregistered_strategy_id() -> str:
    """FIX-3 case 1.  Remaining pathological inputs land in S-11."""
    payload = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    strategy_id = payload["strategy_id"]
    assert isinstance(strategy_id, str) and strategy_id
    return strategy_id


class _RecordingRegistry(AlphaRegistry):
    """Records every ``get`` so the test can prove it entered the handler.

    The KeyError path is ``# pragma: no cover`` adjacent in spirit to
    X5's lookup: an assertion that never saw the lookup fire is
    consistent with never reaching ``risk_wrapper.py:186-192``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[str] = []
        self.key_errors: list[str] = []

    def get(self, alpha_id: str) -> Any:
        self.lookups.append(alpha_id)
        try:
            return super().get(alpha_id)
        except KeyError:
            self.key_errors.append(alpha_id)
            raise


class _RecordingInner:
    """Inner engine that always ALLOW and records that it was asked.

    The defect is not merely "the wrapper returned ALLOW"; it is that
    the unregistered order was forwarded unbudgeted.  ``orders`` is how
    this test knows the swallow fell through to aggregate checks.
    """

    def __init__(self) -> None:
        self.orders: list[OrderRequest] = []

    def check_order(
        self,
        order: OrderRequest,
        positions: object,
        *,
        additional_exposure: Decimal = Decimal("0"),
    ) -> RiskVerdict:
        self.orders.append(order)
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="inner-allow",
        )


class _StubAlpha:
    def __init__(self, alpha_id: str, budget: AlphaRiskBudget) -> None:
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description="x4 control",
            hypothesis="control",
            falsification_criteria=("none",),
            required_features=frozenset(),
            risk_budget=budget,
        )

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> list[object]:
        return []

    def validate(self) -> list[str]:
        return []


def _budget(*, max_position: int) -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=max_position,
        max_gross_exposure_pct=100.0,
        max_drawdown_pct=99.0,
        capital_allocation_pct=100.0,
    )


def _order(strategy_id: str, *, quantity: int = 1) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1_000_000_000,
        correlation_id="x4",
        sequence=1,
        order_id="x4-ord",
        symbol=_SYMBOL,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=strategy_id,
    )


def _wrapper(max_position: int = 100) -> tuple[AlphaBudgetRiskWrapper, _RecordingRegistry, _RecordingInner]:
    registry = _RecordingRegistry()
    registry.register(_StubAlpha(_REGISTERED_ID, _budget(max_position=max_position)))
    inner = _RecordingInner()
    platform = RiskConfig(
        max_position_per_symbol=100_000,
        max_gross_exposure_pct=100.0,
        max_drawdown_pct=99.0,
        account_equity=Decimal("100000"),
    )
    wrapper = AlphaBudgetRiskWrapper(
        inner=inner,  # type: ignore[arg-type]
        registry=registry,
        strategy_positions=StrategyPositionStore(),
        platform_config=platform,
        account_equity=Decimal("100000"),
    )
    return wrapper, registry, inner


def test_unregistered_strategy_id_is_refused_and_does_not_reach_inner() -> None:
    """G23: an unknown id must not proceed unbudgeted.

    Anti-vacuity: ``registry.key_errors`` must contain the id *before*
    the REJECT assertion.  If the lookup never ran, this test failed
    for a different reason than G23 and proves nothing.
    """
    unregistered = load_unregistered_strategy_id()
    wrapper, registry, inner = _wrapper()
    positions = StrategyPositionStore().as_aggregate()

    verdict = wrapper.check_order(_order(unregistered), positions)

    assert registry.lookups == [unregistered], (
        f"handler never looked up {unregistered!r}; lookups={registry.lookups!r}. "
        "The KeyError path in check_order was not entered."
    )
    assert registry.key_errors == [unregistered], (
        f"lookup of {unregistered!r} did not raise KeyError; "
        f"key_errors={registry.key_errors!r}. The swallow was not reached."
    )
    assert inner.orders == [], (
        "unregistered strategy_id was forwarded to the inner engine "
        f"(G23 swallow): {[o.strategy_id for o in inner.orders]!r}. "
        "The order proceeded unbudgeted."
    )
    assert verdict.action is RiskAction.REJECT, (
        f"unregistered strategy_id was not refused "
        f"(action={verdict.action.name}, reason={verdict.reason!r}). "
        "Unknown state resolved to fewer constraints (Inv-11 / G23)."
    )
    assert unregistered in verdict.reason, (
        f"refusal does not name the unregistered id {unregistered!r}: "
        f"{verdict.reason!r}"
    )


def test_registered_strategy_id_is_budgeted_and_permitted() -> None:
    """Control: a known id still runs per-alpha checks and may proceed.

    Without this, a wrapper that rejects every order would satisfy the
    unregistered case while closing the gate on legitimate flow.
    """
    wrapper, registry, inner = _wrapper(max_position=100)
    positions = StrategyPositionStore().as_aggregate()

    verdict = wrapper.check_order(_order(_REGISTERED_ID, quantity=1), positions)

    assert registry.lookups == [_REGISTERED_ID]
    assert registry.key_errors == []
    assert inner.orders and inner.orders[0].strategy_id == _REGISTERED_ID, (
        "registered strategy_id never reached the inner engine — "
        "the control was refused rather than budgeted-and-permitted"
    )
    assert verdict.action is RiskAction.ALLOW, (
        f"registered in-budget order was not permitted "
        f"(action={verdict.action.name}, reason={verdict.reason!r})"
    )
    assert verdict.reason == "inner-allow"


def test_registered_strategy_id_over_position_limit_is_rejected() -> None:
    """Control: the same path still enforces the registered alpha's budget."""
    wrapper, registry, inner = _wrapper(max_position=1)
    positions = StrategyPositionStore().as_aggregate()

    verdict = wrapper.check_order(_order(_REGISTERED_ID, quantity=10), positions)

    assert registry.lookups == [_REGISTERED_ID]
    assert registry.key_errors == []
    assert inner.orders == [], (
        "over-budget registered order reached the inner engine; "
        "per-alpha position limit did not bind"
    )
    assert verdict.action is RiskAction.REJECT
    assert "per-alpha position limit at order gate" in verdict.reason


def test_synthetic_prefix_uses_aggregate_checks_only() -> None:
    """``__``-prefixed ids are synthetic; they skip per-alpha budgets.

    Plan step (2): the synthetic branch is the prefix, not registry
    absence.  This case must keep ALLOW via the inner engine so today's
    aggregate-only behaviour is not collapsed into the unregistered
    refusal.
    """
    wrapper, registry, inner = _wrapper()
    positions = StrategyPositionStore().as_aggregate()
    synthetic = "__synthetic_net__"

    verdict = wrapper.check_order(_order(synthetic), positions)

    assert synthetic not in registry.key_errors or inner.orders, (
        "synthetic id was refused as if unregistered; the explicit "
        "__ prefix branch did not preserve aggregate-only checks"
    )
    assert inner.orders and inner.orders[0].strategy_id == synthetic
    assert verdict.action is RiskAction.ALLOW
    assert verdict.reason == "inner-allow"


_INVALID_PREFIX_ID = "__synthetic_probe__"


def test_double_underscore_prefixed_id_is_refused_by_registry() -> None:
    """S-06a: register() must apply ^[a-z][a-z0-9_]*$ before mutating.

    Production cannot emit this id: bootstrap registers only modules
    returned by loader.load, where the regex already ran. The case
    constructs the module directly. A failure because the stub was
    malformed, validate() rejected it, or the id collided, proves
    nothing about the missing id rule.
    """
    registry = AlphaRegistry()
    module = _StubAlpha(_INVALID_PREFIX_ID, _budget(max_position=100))

    with pytest.raises(AlphaRegistryError, match=r"must match") as exc_info:
        registry.register(module)

    message = str(exc_info.value)
    assert _INVALID_PREFIX_ID in message
    assert "^[a-z][a-z0-9_]*$" in message
    assert _INVALID_PREFIX_ID not in registry
    assert len(registry) == 0


def test_valid_alpha_id_still_registers() -> None:
    """Control: a legal id still registers so a blanket refusal cannot pass."""
    registry = AlphaRegistry()
    module = _StubAlpha(_REGISTERED_ID, _budget(max_position=100))
    registry.register(module)
    assert _REGISTERED_ID in registry
    assert len(registry) == 1
    assert registry.get(_REGISTERED_ID) is module
