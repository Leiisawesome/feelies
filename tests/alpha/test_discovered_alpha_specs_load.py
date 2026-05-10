"""Discovery smoke: every active ``alphas/**/*.alpha.yaml`` loads via AlphaLoader.

Templates and underscore-prefixed path segments are excluded by
:func:`feelies.alpha.discovery.discover_alpha_specs` — this test locks
that convention and catches YAML/loader regressions across the shipped
alpha set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.discovery import discover_alpha_specs
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.portfolio_layer_module import LoadedPortfolioLayerModule
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.services.regime_engine import get_regime_engine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALPHAS_DIR = _REPO_ROOT / "alphas"


def test_discovery_excludes_template_and_underscore_paths() -> None:
    paths = discover_alpha_specs(_ALPHAS_DIR)
    rel = {p.relative_to(_ALPHAS_DIR).as_posix() for p in paths}
    assert not any(part.startswith("_") for p in rel for part in p.split("/"))
    assert "pofi_xsect_v1/pofi_xsect_v1.alpha.yaml" in rel
    assert "pofi_xsect_v1/pofi_xsect_v1.with_decay.alpha.yaml" in rel


@pytest.mark.parametrize(
    "enforce_tm",
    [False, True],
    ids=["default_strict", "enforce_trend_mechanism_true"],
)
def test_each_discovered_spec_loads(enforce_tm: bool) -> None:
    regime = get_regime_engine("hmm_3state_fractional")
    loader = AlphaLoader(
        regime_engine=regime,
        enforce_trend_mechanism=enforce_tm,
    )
    specs = discover_alpha_specs(_ALPHAS_DIR)
    assert specs, "expected at least one active alpha under alphas/"
    for path in specs:
        mod = loader.load(path)
        assert mod.manifest.layer in {"SIGNAL", "PORTFOLIO"}
        if mod.manifest.layer == "SIGNAL":
            assert isinstance(mod, LoadedSignalLayerModule)
        else:
            assert isinstance(mod, LoadedPortfolioLayerModule)
