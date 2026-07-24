"""Revocation-symmetry hook — ``AlphaLifecycle`` / ``AlphaRegistry`` (design §2.5).

Removing a decoupled alpha's Stage-0 authorization (quarantine, decommission,
config revert) must flatten any open deferred book **immediately**, not at the
old ceiling (§2.5 / §3.6).  These tests pin the lifecycle→registry→composer
wiring; ``tests/risk/test_exit_composer_revocation.py`` pins the composer half.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    LifecycleRevocation,
    PromotionEvidence,
)
from feelies.alpha.registry import AlphaRegistry
from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import OrderRequest
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
    ExitComposer,
    ExitComposerPolicy,
)

from tests.alpha.conftest import MockAlpha

_PAPER = PromotionEvidence(
    schema_valid=True, determinism_test_passed=True, feature_values_finite=True
)
_LIVE = PromotionEvidence(
    paper_days=60,
    paper_sharpe=2.0,
    paper_hit_rate=0.6,
    paper_max_drawdown_pct=1.0,
    cost_model_validated=True,
)


def _to_live(lc: AlphaLifecycle) -> None:
    assert lc.promote_to_paper(_PAPER) == []
    assert lc.promote_to_live(_LIVE) == []
    assert lc.is_live


# ── AlphaLifecycle hook firing ──────────────────────────────────────────────


def test_hook_fires_on_quarantine_with_context() -> None:
    fired: list[LifecycleRevocation] = []
    lc = AlphaLifecycle(alpha_id="sig_x", clock=SimulatedClock(start_ns=1_000))
    lc.set_revocation_hook(fired.append)
    _to_live(lc)

    assert fired == []  # promotions are not revocations
    lc.quarantine("edge decay detected", correlation_id="cid:q")

    assert len(fired) == 1
    rev = fired[0]
    assert rev.alpha_id == "sig_x"
    assert rev.from_state == AlphaLifecycleState.LIVE.name
    assert rev.to_state == AlphaLifecycleState.QUARANTINED.name
    assert rev.trigger == "edge_decay_detected"
    assert rev.correlation_id == "cid:q"


def test_hook_fires_on_decommission() -> None:
    fired: list[LifecycleRevocation] = []
    lc = AlphaLifecycle(alpha_id="sig_x", clock=SimulatedClock(start_ns=1_000))
    _to_live(lc)
    lc.quarantine("q")  # no hook yet
    lc.set_revocation_hook(fired.append)

    lc.decommission("terminal")

    assert [r.to_state for r in fired] == [AlphaLifecycleState.DECOMMISSIONED.name]


def test_hook_not_fired_on_promotions_or_revalidation() -> None:
    fired: list[LifecycleRevocation] = []
    lc = AlphaLifecycle(alpha_id="sig_x", clock=SimulatedClock(start_ns=1_000))
    lc.set_revocation_hook(fired.append)
    _to_live(lc)  # RESEARCH→PAPER→LIVE
    lc.quarantine("q")  # 1 revocation
    lc.revalidate_to_paper(
        PromotionEvidence(determinism_test_passed=True, revalidation_notes="human ok")
    )  # QUARANTINED→PAPER is not a revocation

    assert [r.to_state for r in fired] == [AlphaLifecycleState.QUARANTINED.name]


def test_demotion_commits_even_when_hook_raises() -> None:
    # Inv-11: a failing flatten must never abort the demotion (the state machine
    # rolls a transition back on a callback exception, so the hook swallows).
    def boom(_rev: LifecycleRevocation) -> None:
        raise RuntimeError("flatten backend unavailable")

    lc = AlphaLifecycle(alpha_id="sig_x", clock=SimulatedClock(start_ns=1_000))
    lc.set_revocation_hook(boom)
    _to_live(lc)

    lc.quarantine("edge decay")

    assert lc.state is AlphaLifecycleState.QUARANTINED


# ── AlphaRegistry threading ─────────────────────────────────────────────────


def test_registry_hook_applies_to_existing_and_future_lifecycles() -> None:
    fired: list[str] = []
    registry = AlphaRegistry(clock=SimulatedClock(start_ns=1_000))
    registry.register(MockAlpha(alpha_id="already_here"))

    registry.set_lifecycle_revocation_hook(lambda rev: fired.append(rev.alpha_id))

    registry.register(MockAlpha(alpha_id="added_after"))  # future lifecycle

    for alpha_id in ("already_here", "added_after"):
        lc = registry.get_lifecycle(alpha_id)
        assert lc is not None
        _to_live(lc)
        registry.quarantine(alpha_id, "edge decay")

    assert sorted(fired) == ["added_after", "already_here"]


def test_registry_hook_detach_with_none() -> None:
    fired: list[str] = []
    registry = AlphaRegistry(clock=SimulatedClock(start_ns=1_000))
    registry.register(MockAlpha(alpha_id="a"))
    registry.set_lifecycle_revocation_hook(lambda rev: fired.append(rev.alpha_id))
    registry.set_lifecycle_revocation_hook(None)

    lc = registry.get_lifecycle("a")
    assert lc is not None
    _to_live(lc)
    registry.quarantine("a", "q")

    assert fired == []


# ── End-to-end: quarantine flattens the open deferred book immediately ───────


def test_quarantine_flattens_open_deferred_book_immediately() -> None:
    sid = "sig_decoupled_v1"
    bus = EventBus()
    received: list[OrderRequest] = []
    bus.subscribe(OrderRequest, received.append)  # type: ignore[arg-type]

    store = StrategyPositionStore()
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(start=80_000),
        position_store=store,
        policies={sid: ExitComposerPolicy(strategy_id=sid)},
    )

    registry = AlphaRegistry(clock=SimulatedClock(start_ns=1_000))
    registry.register(MockAlpha(alpha_id=sid, symbols=frozenset({"AAPL"})))
    registry.set_lifecycle_revocation_hook(
        lambda rev: composer.revoke_and_flatten(
            rev.alpha_id, now_ns=rev.timestamp_ns, correlation_id=f"revoke:{rev.trigger}"
        )
    )

    lc = registry.get_lifecycle(sid)
    assert lc is not None
    _to_live(lc)

    # An open deferred book (held under decoupling); no cap deadline has fired.
    store.update(sid, "AAPL", 100, Decimal("100"), timestamp_ns=0)
    assert received == []

    registry.quarantine(sid, "edge decay detected")

    # Flattened on the transition, not at the old ceiling.
    assert len(received) == 1
    order = received[0]
    assert order.strategy_id == sid
    assert order.symbol == "AAPL"
    assert order.quantity == 100
    assert order.reason == EXIT_COMPOSER_REASON_DECOUPLING_REVOKED
    assert registry.get_lifecycle(sid).state is AlphaLifecycleState.QUARANTINED  # type: ignore[union-attr]
