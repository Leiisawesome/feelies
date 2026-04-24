"""Tests for the Phase-5 layer-specific alpha templates.

The three templates under ``alphas/_template/`` are part of the
external-facing documentation contract.  When they drift from the
loader's accepted shape, every operator who copies them gets a stale
starting point — so we lock them to the live loader by attempting a
fresh ``AlphaLoader.load`` on each template.

The deprecated ``alphas/_template/template.alpha.yaml`` (schema 1.0)
is intentionally not loaded here — it is on the sunset path and only
needs to remain *parseable* (which the wider loader test suite
already covers).

Also covers the LEGACY_SIGNAL sunset banner: loading a 1.0 spec or
a ``layer: LEGACY_SIGNAL`` spec emits a once-per-process WARNING via
``feelies.alpha.loader``'s logger.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader, _LEGACY_SUNSET_WARNED


_TEMPLATE_DIR = Path("alphas/_template")


@pytest.fixture(autouse=True)
def _reset_sunset_warned() -> None:
    """Each test starts with a clean once-per-process dedupe set."""
    _LEGACY_SUNSET_WARNED.clear()
    yield
    _LEGACY_SUNSET_WARNED.clear()


def test_template_legacy_signal_loads() -> None:
    """``template_legacy_signal.alpha.yaml`` parses as a LEGACY_SIGNAL."""
    from feelies.alpha.loader import LoadedAlphaModule

    loader = AlphaLoader()
    module = loader.load(_TEMPLATE_DIR / "template_legacy_signal.alpha.yaml")
    assert isinstance(module, LoadedAlphaModule)
    # LEGACY_SIGNAL retains the per-tick contract (features dict + signal).
    # Manifest shape is what downstream registry / engines see.
    assert module.manifest.alpha_id  # non-empty


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


def test_legacy_signal_sunset_banner_emits_once_for_legacy_layer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Loading ``layer: LEGACY_SIGNAL`` emits a once-per-process WARNING."""
    loader = AlphaLoader()
    with caplog.at_level(logging.WARNING, logger="feelies.alpha.loader"):
        loader.load(_TEMPLATE_DIR / "template_legacy_signal.alpha.yaml")
    matches = [
        rec for rec in caplog.records
        if "LEGACY_SIGNAL is DEPRECATED" in rec.getMessage()
    ]
    assert len(matches) == 1, (
        f"expected one sunset banner, got {len(matches)}: "
        f"{[m.getMessage() for m in matches]}"
    )

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="feelies.alpha.loader"):
        loader.load(_TEMPLATE_DIR / "template_legacy_signal.alpha.yaml")
    rematches = [
        rec for rec in caplog.records
        if "LEGACY_SIGNAL is DEPRECATED" in rec.getMessage()
    ]
    assert rematches == [], (
        "second load of the same alpha_id must NOT re-emit the sunset banner; "
        f"got: {[m.getMessage() for m in rematches]}"
    )
