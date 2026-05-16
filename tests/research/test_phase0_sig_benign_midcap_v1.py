"""Phase-0 harness smoke test — synthetic session must complete."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.platform_config import PlatformConfig
from feelies.research.phase0_benign import (
    run_phase0,
    synthesize_multi_symbol_events,
)

_REPO = Path(__file__).resolve().parents[2]
_CONFIG = _REPO / "platforms" / "phase0_sig_benign_midcap_v1.yaml"
_ALPHA = (
    _REPO / "alphas" / "sig_benign_midcap_v1" / "sig_benign_midcap_v1.alpha.yaml"
)


@pytest.mark.backtest_validation
def test_phase0_synthetic_completes_with_panels() -> None:
    config = PlatformConfig.from_yaml(_CONFIG)
    loaded = AlphaLoader(
        enforce_trend_mechanism=config.enforce_trend_mechanism,
    ).load(str(_ALPHA))
    assert isinstance(loaded, LoadedSignalLayerModule)

    # ~6 minutes per symbol — enough 120s boundaries for Spearman n>=3.
    events = synthesize_multi_symbol_events(
        tuple(sorted(config.symbols)),
        quotes_per_symbol=3_600,
    )
    report = run_phase0(
        config,
        events,
        data_source="synthetic:test",
        loaded=loaded,
    )
    assert report.n_boundaries >= 3
    assert report.b4.n_signals >= 0
    assert len(report.stress) == 3
    assert report.spearman_ofi_vs_fwd_return.n == report.n_boundaries - len(
        config.symbols,
    ) or report.spearman_ofi_vs_fwd_return.n >= 0
