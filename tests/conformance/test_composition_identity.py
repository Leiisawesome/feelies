"""C6 — one reducer, and contributors + exclusions == forecasts in scope.

G15/G19: reducing N forecasts to one portfolio is engine 6's job.  The
identity is the guard, not the class name: every forecast at the boundary
is either a contributor or an exclusion with a reason.  FIX-2 is a second
SIGNAL alpha of a different evaluate shape so the identity is not the A=1
no-op.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from feelies.composition.protocol import SelectionResult
from feelies.composition.selection_policy import Top1SelectionPolicy
from feelies.core.events import Signal, SignalDirection

_ORCH = Path("src/feelies/kernel/orchestrator.py")
_ARBITRATION = Path("src/feelies/alpha/arbitration.py")
_POLICY = Path("src/feelies/composition/selection_policy.py")
_FIX2_DIR = Path(__file__).resolve().parent / "fixtures" / "shape_adversarial"


def _sig(
    direction: SignalDirection,
    *,
    strategy_id: str,
    strength: float = 0.8,
    edge_bps: float = 10.0,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="c6:1:1",
        sequence=1,
        symbol="AAPL",
        strategy_id=strategy_id,
        direction=direction,
        strength=strength,
        edge_estimate_bps=edge_bps,
    )


def _assert_identity(result: SelectionResult) -> None:
    contrib_ids = [id(s) for s in result.contributors]
    excl_ids = [id(e.signal) for e in result.exclusions]
    scope_ids = [id(s) for s in result.in_scope]
    assert len(contrib_ids) + len(excl_ids) == len(scope_ids), (
        f"contributors ({len(contrib_ids)}) + exclusions ({len(excl_ids)}) "
        f"!= in_scope ({len(scope_ids)})"
    )
    assert set(contrib_ids).isdisjoint(excl_ids), "a forecast is both contributor and exclusion"
    assert set(contrib_ids) | set(excl_ids) == set(scope_ids), (
        "accounted forecasts are not the in-scope set"
    )
    missing = [e for e in result.exclusions if not e.reason]
    assert not missing, "exclusion with empty reason"


def test_c6_one_reducer_is_the_declared_composition_policy() -> None:
    """Kernel and alpha no longer host a second copy of the reduction."""
    orch = _ORCH.read_text(encoding="utf-8")
    assert "def _select_bus_signal" not in orch, (
        "kernel still defines _select_bus_signal — the reducer has not moved"
    )
    assert not _ARBITRATION.exists(), (
        "src/feelies/alpha/arbitration.py still exists — a second reducer remains"
    )
    assert _POLICY.exists(), "composition/selection_policy.py is the declared reducer"


def test_c6_accounting_identity_on_competing_forecasts() -> None:
    """Two differently-shaped forecasts: one contributor, one reasoned exclusion."""
    policy = Top1SelectionPolicy(dead_zone_bps=0.0)
    long_high = _sig(SignalDirection.LONG, strategy_id="shape_adv_long", strength=1.0, edge_bps=20.0)
    short_low = _sig(SignalDirection.SHORT, strategy_id="shape_adv_short", strength=0.4, edge_bps=5.0)
    result = policy.select([long_high, short_low])
    _assert_identity(result)
    assert result.contributors == (long_high,)
    assert result.exclusions[0].signal is short_low
    assert result.exclusions[0].reason


def test_c6_fix2_second_alpha_is_a_different_evaluate_shape() -> None:
    """FIX-2 is two SIGNAL specs, same horizon, different evaluate bodies."""
    long_path = _FIX2_DIR / "shape_adv_long.alpha.yaml"
    short_path = _FIX2_DIR / "shape_adv_short.alpha.yaml"
    assert long_path.exists() and short_path.exists(), "FIX-2 fixture directory is missing"
    long_spec = yaml.safe_load(long_path.read_text(encoding="utf-8"))
    short_spec = yaml.safe_load(short_path.read_text(encoding="utf-8"))
    assert long_spec["layer"] == "SIGNAL" and short_spec["layer"] == "SIGNAL"
    assert long_spec["horizon_seconds"] == short_spec["horizon_seconds"]
    assert long_spec["alpha_id"] != short_spec["alpha_id"]
    assert long_spec["signal"] != short_spec["signal"], (
        "FIX-2 pair is the same evaluate twice — A>1 would still be one shape"
    )
