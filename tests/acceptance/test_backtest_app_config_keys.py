"""Guard APP single-alpha backtest config delta contracts.

``configs/bt_app.yaml`` is a thin alias for the benign baseline;
``configs/bt_sig_*.yaml`` are the canonical per-alpha research configs.
Each inherits via ``extends:`` and should declare only intentional deltas.
The merged document must remain loadable as a
:class:`~feelies.core.platform_config.PlatformConfig`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from feelies.core.config_yaml import deep_merge_mapping, load_yaml_mapping
from feelies.core.platform_config import PlatformConfig

_PLATFORM_YAML = Path("platform.yaml")
_BACKTEST_APP_YAML = Path("configs/bt_app.yaml")
_BENIGN_SIG_YAML = Path("configs/bt_sig_benign_midcap.yaml")

_SIG_BACKTEST_CONFIGS: tuple[tuple[Path, str], ...] = (
    (_BENIGN_SIG_YAML, "sig_benign_midcap_v1"),
    (Path("configs/bt_sig_kyle_drift.yaml"), "sig_kyle_drift_v1"),
    (Path("configs/bt_sig_inventory_revert.yaml"), "sig_inventory_revert_v1"),
    (Path("configs/bt_sig_hawkes_burst.yaml"), "sig_hawkes_burst_v1"),
    (Path("configs/bt_sig_moc_imbalance.yaml"), "sig_moc_imbalance_v1"),
)

_SIG_ALLOWED_DELTA_KEYS = frozenset(
    {
        "extends",
        "symbols",
        "alpha_specs",
        "prune_unused_sensors",
        "signal_min_edge_cost_ratio",
        "parameter_overrides",
    }
)


def test_backtest_app_yaml_is_baseline_alias_for_benign_sig_config() -> None:
    if not _BACKTEST_APP_YAML.is_file():
        pytest.fail(f"Missing baseline config: {_BACKTEST_APP_YAML}")

    raw = yaml.safe_load(_BACKTEST_APP_YAML.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw.get("extends") == "bt_sig_benign_midcap.yaml"
    assert frozenset(raw.keys()) == frozenset({"extends"})


@pytest.mark.parametrize(("config_path", "alpha_id"), _SIG_BACKTEST_CONFIGS)
def test_sig_backtest_yaml_declares_extends_and_only_allowed_deltas(
    config_path: Path,
    alpha_id: str,
) -> None:
    del alpha_id
    if not config_path.is_file():
        pytest.fail(f"Missing single-alpha config: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw.get("extends") == "../platform.yaml"

    local_keys = frozenset(raw.keys())
    unexpected = sorted(local_keys - _SIG_ALLOWED_DELTA_KEYS)
    assert not unexpected, (
        f"{config_path} should only declare extends + research deltas; "
        f"unexpected top-level keys: {unexpected}"
    )


def test_backtest_app_merged_config_loads_and_matches_expected_deltas() -> None:
    merged = load_yaml_mapping(_BACKTEST_APP_YAML)
    platform = load_yaml_mapping(_PLATFORM_YAML)

    expected = deep_merge_mapping(
        platform,
        {
            "symbols": ["APP"],
            "alpha_specs": [
                "alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml",
            ],
            "prune_unused_sensors": True,
            "signal_min_edge_cost_ratio": 1.5,
            "parameter_overrides": {
                "sig_benign_midcap_v1": {
                    "entry_threshold_z": 1.5,
                    "edge_per_z_bps": 6.0,
                },
            },
        },
    )
    assert merged["symbols"] == expected["symbols"]
    assert merged["alpha_specs"] == expected["alpha_specs"]
    assert merged["prune_unused_sensors"] is expected["prune_unused_sensors"]
    assert merged["signal_min_edge_cost_ratio"] == expected["signal_min_edge_cost_ratio"]
    assert merged["parameter_overrides"] == expected["parameter_overrides"]

    cfg = PlatformConfig.from_yaml(_BACKTEST_APP_YAML)
    assert sorted(cfg.symbols) == ["APP"]
    assert len(cfg.alpha_specs) == 1
    assert cfg.alpha_specs[0].name == "sig_benign_midcap_v1.alpha.yaml"
    assert cfg.prune_unused_sensors
    assert cfg.signal_min_edge_cost_ratio == 1.5
    assert cfg.parameter_overrides["sig_benign_midcap_v1"] == {
        "entry_threshold_z": 1.5,
        "edge_per_z_bps": 6.0,
    }


@pytest.mark.parametrize(("config_path", "alpha_id"), _SIG_BACKTEST_CONFIGS)
def test_sig_backtest_configs_load_with_single_alpha(
    config_path: Path,
    alpha_id: str,
) -> None:
    cfg = PlatformConfig.from_yaml(config_path)
    assert sorted(cfg.symbols) == ["APP"]
    assert cfg.signal_min_edge_cost_ratio == 1.5
    assert len(cfg.alpha_specs) == 1
    assert cfg.alpha_specs[0].as_posix().endswith(f"{alpha_id}/{alpha_id}.alpha.yaml")


# DI-04 (data ingestion audit 2026-07-02): PlatformConfig's dataclass defaults
# for backtest_enforce_ingest_terminal_health / backtest_reject_zero_ingest_events
# stay fail-open, because flipping them would break every PAPER config and the
# ~95 direct PlatformConfig(...) constructions across the test suite that never
# populate ingest_terminal_symbol_health. The fail-closed default lives at the
# shipped-config layer via platform.yaml + extends instead — pin it here so a
# future edit cannot silently regress the ingest-health gate back to fail-open.
_ALL_BACKTEST_CONFIGS: tuple[Path, ...] = (
    _PLATFORM_YAML,
    _BACKTEST_APP_YAML,
    Path("configs/bt_multialpha.yaml"),
    *(path for path, _alpha_id in _SIG_BACKTEST_CONFIGS),
)


@pytest.mark.parametrize("config_path", _ALL_BACKTEST_CONFIGS)
def test_backtest_configs_are_fail_closed_on_ingest_health(config_path: Path) -> None:
    cfg = PlatformConfig.from_yaml(config_path)
    assert cfg.backtest_enforce_ingest_terminal_health is True
    assert cfg.backtest_reject_zero_ingest_events is True
