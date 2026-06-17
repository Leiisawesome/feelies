"""Audit P2-5 — executable Inv-2 (falsifiability) gate for the SIGNAL fleet.

The audit recommended promoting the per-alpha falsification criteria from
YAML prose into an enforced check.  Inv-2 requires falsifiability be
*defined before testing* — every shipped ``layer: SIGNAL`` alpha must
therefore declare:

* a non-empty ``falsification_criteria`` list (at least two distinct,
  mechanism-tied criteria), and
* a non-empty ``trend_mechanism.failure_signature`` list (G16 rule 6 —
  the mechanism-layer invalidator) when it declares a ``trend_mechanism``
  block.

This file is the canonical fleet-wide artefact; per-alpha behavioural
tests live alongside each alpha.  Adding a new SIGNAL alpha without
falsification criteria fails here loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from feelies.alpha.loader import AlphaLoader


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALPHAS_DIR = _REPO_ROOT / "alphas"


def _signal_alpha_paths() -> list[Path]:
    """All shipped ``layer: SIGNAL`` alpha specs (templates excluded)."""
    paths: list[Path] = []
    for path in sorted(_ALPHAS_DIR.rglob("*.alpha.yaml")):
        if "_template" in path.parts:
            continue
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(spec, dict) and str(spec.get("layer", "")).upper() == "SIGNAL":
            paths.append(path)
    return paths


_SIGNAL_ALPHAS = _signal_alpha_paths()


def test_there_are_signal_alphas_to_check() -> None:
    assert _SIGNAL_ALPHAS, "no layer: SIGNAL alphas discovered under alphas/"


@pytest.mark.parametrize(
    "alpha_path",
    _SIGNAL_ALPHAS,
    ids=[p.parent.name for p in _SIGNAL_ALPHAS],
)
def test_signal_alpha_declares_falsification_criteria(alpha_path: Path) -> None:
    module = AlphaLoader(enforce_trend_mechanism=False).load(str(alpha_path))
    criteria = module.manifest.falsification_criteria
    assert criteria, f"{alpha_path.name}: empty falsification_criteria (Inv-2)"
    non_empty = [c for c in criteria if isinstance(c, str) and c.strip()]
    assert len(non_empty) >= 2, (
        f"{alpha_path.name}: Inv-2 expects >=2 mechanism-tied "
        f"falsification criteria, found {len(non_empty)}"
    )


@pytest.mark.parametrize(
    "alpha_path",
    _SIGNAL_ALPHAS,
    ids=[p.parent.name for p in _SIGNAL_ALPHAS],
)
def test_signal_alpha_declares_failure_signature(alpha_path: Path) -> None:
    module = AlphaLoader(enforce_trend_mechanism=False).load(str(alpha_path))
    block = module.manifest.trend_mechanism
    if not block:
        pytest.skip(f"{alpha_path.name} declares no trend_mechanism block")
    failure_sig = block.get("failure_signature")
    assert failure_sig and isinstance(failure_sig, list), (
        f"{alpha_path.name}: trend_mechanism.failure_signature must be a "
        f"non-empty list (G16 rule 6 / Inv-2)"
    )
