"""Portfolio reference alphas are research-only at this scale.

* Production discovery excludes ``alphas/research/``.
* ``lifecycle_state: RESEARCH`` blocks PAPER/LIVE promotion.
* Composition-layer code remains loadable via explicit paths (integration e2e).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.discovery import (
    discover_alpha_specs,
    discover_research_alpha_specs,
)
from feelies.alpha.lifecycle import AlphaLifecycle, AlphaLifecycleState
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.promotion_evidence import GateThresholds
from feelies.core.clock import SimulatedClock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALPHAS_DIR = _REPO_ROOT / "alphas"

_RESEARCH_PORTFOLIO_IDS = (
    "pro_burst_revert_v1",
    "pro_kyle_benign_v1",
)


def test_production_discovery_excludes_research_portfolio_alphas() -> None:
    shipped = {p.name for p in discover_alpha_specs(_ALPHAS_DIR)}
    assert not any(name.startswith("pro_") for name in shipped)

    research = discover_research_alpha_specs(_ALPHAS_DIR)
    research_ids = sorted(p.parent.name for p in research if p.name.endswith(".alpha.yaml"))
    assert research_ids == sorted(_RESEARCH_PORTFOLIO_IDS)


@pytest.mark.parametrize("alpha_id", _RESEARCH_PORTFOLIO_IDS)
def test_research_portfolio_yaml_declares_lifecycle_cap(alpha_id: str) -> None:
    spec_path = _ALPHAS_DIR / "research" / alpha_id / f"{alpha_id}.alpha.yaml"
    module = AlphaLoader().load(spec_path)
    assert module.manifest.lifecycle_cap == "RESEARCH"


@pytest.mark.parametrize("alpha_id", _RESEARCH_PORTFOLIO_IDS)
def test_research_lifecycle_cap_blocks_paper_promotion(alpha_id: str) -> None:
    clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
    lifecycle = AlphaLifecycle(
        alpha_id=alpha_id,
        clock=clock,
        gate_thresholds=GateThresholds(),
        lifecycle_cap="RESEARCH",
    )
    assert lifecycle.state == AlphaLifecycleState.RESEARCH
    errors = lifecycle.promote_to_paper()
    assert errors
    assert any("lifecycle_state=RESEARCH" in e for e in errors)
    assert lifecycle.state == AlphaLifecycleState.RESEARCH
