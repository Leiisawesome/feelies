"""Guard ``configs/backtest_app.yaml`` delta contract against ``platform.yaml``.

Research configs inherit via ``extends:`` and should declare only intentional
deltas.  The merged document must remain loadable as a
:class:`~feelies.core.platform_config.PlatformConfig`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from feelies.core.config_yaml import deep_merge_mapping, load_yaml_mapping
from feelies.core.platform_config import PlatformConfig

_PLATFORM_YAML = Path("platform.yaml")
_BACKTEST_APP_YAML = Path("configs/backtest_app.yaml")

_ALLOWED_DELTA_KEYS = frozenset({"extends", "symbols", "parameter_overrides"})


def test_backtest_app_yaml_declares_extends_and_only_allowed_deltas() -> None:
    if not _BACKTEST_APP_YAML.is_file():
        pytest.fail(f"Missing baseline config: {_BACKTEST_APP_YAML}")

    raw = yaml.safe_load(_BACKTEST_APP_YAML.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw.get("extends") == "../platform.yaml"

    local_keys = frozenset(raw.keys())
    unexpected = sorted(local_keys - _ALLOWED_DELTA_KEYS)
    assert not unexpected, (
        "configs/backtest_app.yaml should only declare extends + research deltas; "
        f"unexpected top-level keys: {unexpected}"
    )


def test_backtest_app_merged_config_loads_and_matches_expected_deltas() -> None:
    merged = load_yaml_mapping(_BACKTEST_APP_YAML)
    platform = load_yaml_mapping(_PLATFORM_YAML)

    expected = deep_merge_mapping(
        platform,
        {
            "symbols": ["APP"],
            "parameter_overrides": {
                "sig_benign_midcap_v1": {
                    "entry_threshold_z": 1.5,
                    "edge_per_z_bps": 6.0,
                },
            },
        },
    )
    assert merged["symbols"] == expected["symbols"]
    assert merged["parameter_overrides"] == expected["parameter_overrides"]

    cfg = PlatformConfig.from_yaml(_BACKTEST_APP_YAML)
    assert sorted(cfg.symbols) == ["APP"]
    assert cfg.parameter_overrides["sig_benign_midcap_v1"] == {
        "entry_threshold_z": 1.5,
        "edge_per_z_bps": 6.0,
    }
