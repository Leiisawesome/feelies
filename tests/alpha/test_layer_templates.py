"""Keep the public SIGNAL and PORTFOLIO templates loadable."""

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
