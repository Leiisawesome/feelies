"""X6 (narrow) — a pathological unregistered strategy_id is refused.

S-11 completes this file with FIX-3's remaining six input classes, which
need a named gate in the registry.  This step lands only case 1: an
order whose ``strategy_id`` is not registered.
"""

from __future__ import annotations

from feelies.core.events import RiskAction
from feelies.portfolio.strategy_position_store import StrategyPositionStore

from tests.conformance.test_per_alpha_budget import (
    _order,
    _wrapper,
    load_unregistered_strategy_id,
)


def test_unregistered_strategy_id_fixture_is_refused() -> None:
    """FIX-3 case 1: the fixture id enters the KeyError handler and is refused."""
    unregistered = load_unregistered_strategy_id()
    wrapper, registry, inner = _wrapper()
    positions = StrategyPositionStore().as_aggregate()

    verdict = wrapper.check_order(_order(unregistered), positions)

    assert unregistered in registry.lookups, (
        "fixture strategy_id never reached registry.get; "
        f"lookups={registry.lookups!r}"
    )
    assert unregistered in registry.key_errors, (
        "fixture strategy_id did not raise KeyError in the wrapper; "
        f"key_errors={registry.key_errors!r}"
    )
    assert inner.orders == [], (
        "pathological unregistered id was forwarded unbudgeted: "
        f"{[o.strategy_id for o in inner.orders]!r}"
    )
    assert verdict.action is RiskAction.REJECT, (
        f"pathological unregistered id was not refused "
        f"(action={verdict.action.name}, reason={verdict.reason!r})"
    )
    assert unregistered in verdict.reason
