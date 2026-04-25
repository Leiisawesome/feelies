"""Tests for the Phase-5 layer-specific alpha templates.

The two surviving templates under ``alphas/_template/`` are part of the
external-facing documentation contract.  When they drift from the
loader's accepted shape, every operator who copies them gets a stale
starting point — so we lock them to the live loader by attempting a
fresh ``AlphaLoader.load`` on each template.

Workstream D.2 retired ``alphas/_template/template_legacy_signal.alpha.yaml``
and the ``layer: LEGACY_SIGNAL`` loader path along with it.  The only
canonical templates left are ``template_signal.alpha.yaml`` (Layer-2,
horizon-anchored, regime-gated) and ``template_portfolio.alpha.yaml``
(Layer-3, cross-sectional construction).
"""

from __future__ import annotations

from pathlib import Path

from feelies.alpha.loader import AlphaLoader


_TEMPLATE_DIR = Path("alphas/_template")


def test_template_signal_loads() -> None:
    """``template_signal.alpha.yaml`` parses as a SIGNAL-layer module."""
    from feelies.alpha.signal_layer_module import LoadedSignalLayerModule

    loader = AlphaLoader()
    module = loader.load(_TEMPLATE_DIR / "template_signal.alpha.yaml")
    assert isinstance(module, LoadedSignalLayerModule)
    assert module.manifest.alpha_id  # non-empty
    assert module.horizon_seconds > 0


def test_template_portfolio_loads() -> None:
    """``template_portfolio.alpha.yaml`` parses as a PORTFOLIO-layer module."""
    from feelies.alpha.portfolio_layer_module import LoadedPortfolioLayerModule

    loader = AlphaLoader()
    module = loader.load(_TEMPLATE_DIR / "template_portfolio.alpha.yaml")
    assert isinstance(module, LoadedPortfolioLayerModule)
    assert module.manifest.alpha_id  # non-empty
