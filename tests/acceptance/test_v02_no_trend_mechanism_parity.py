"""Parity checks for the baseline alpha named by the companion text file.

The suite binds that alpha's YAML shape to its Level 1–4 replay hashes so a
schema or output change cannot be rebaselined independently.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule


_BASELINE_ALPHA_FILE = Path(__file__).with_name("_chosen_v02_baseline_alpha.txt")


def _baseline_alpha_id() -> str:
    text = _BASELINE_ALPHA_FILE.read_text(encoding="utf-8").strip()
    assert text, (
        f"{_BASELINE_ALPHA_FILE} must contain exactly one alpha id "
        "on a single line — no comments, no blank file."
    )
    assert "\n" not in text, (
        f"{_BASELINE_ALPHA_FILE}: more than one line; only one "
        "baseline alpha id is supported per matrix row §20.12.3 #2."
    )
    return text


def _baseline_alpha_path() -> Path:
    alpha_id = _baseline_alpha_id()
    return Path("alphas") / alpha_id / f"{alpha_id}.alpha.yaml"


def test_baseline_alpha_yaml_declares_trend_mechanism_block() -> None:
    """Lock that the chosen baseline carries G16 ``trend_mechanism:``."""
    path = _baseline_alpha_path()
    assert path.exists(), (
        f"baseline alpha YAML missing at {path}; either restore the "
        "file or pick a new baseline by editing "
        f"{_BASELINE_ALPHA_FILE}."
    )

    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(spec, dict), f"{path}: top-level YAML must be a mapping"
    assert spec.get("schema_version") == "1.1", (
        f"{path}: baseline must remain schema-1.1 SIGNAL; got "
        f"schema_version={spec.get('schema_version')!r}."
    )
    assert spec.get("layer") == "SIGNAL", (
        f"{path}: §20.12.3 #2 governs SIGNAL-layer alphas; got layer={spec.get('layer')!r}."
    )
    assert "trend_mechanism" in spec and isinstance(
        spec["trend_mechanism"],
        dict,
    ), (
        f"{path}: reference SIGNAL alpha must declare trend_mechanism: "
        "(G16). Restore the block or pick a different baseline in "
        f"{_BASELINE_ALPHA_FILE}."
    )


def test_baseline_alpha_loads_under_explicit_strict_opt_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Loader accepts the reference alpha when ``enforce_trend_mechanism=False``.

    Matches operators pinning the escape hatch in ``platform.yaml`` while
    the alpha carries a full ``trend_mechanism:`` disclosure.
    """
    path = _baseline_alpha_path()

    with caplog.at_level(logging.WARNING, logger="feelies.alpha.loader"):
        loader = AlphaLoader(enforce_trend_mechanism=False)
        module = loader.load(path)

    assert isinstance(module, LoadedSignalLayerModule), (
        f"baseline must load as LoadedSignalLayerModule; got {type(module).__name__}"
    )
    assert module.trend_mechanism_enum is not None, (
        "reference alpha must populate trend_mechanism_enum — found "
        f"{module.trend_mechanism_enum!r}"
    )
    assert module.expected_half_life_seconds > 0, (
        "reference alpha must declare a positive expected_half_life_seconds "
        f"— found {module.expected_half_life_seconds}"
    )

    # Loading must not have surfaced a "missing trend_mechanism" error.
    for record in caplog.records:
        msg = record.getMessage().lower()
        assert "trend_mechanism" not in msg or "missing" not in msg, (
            "loader emitted an unexpected 'missing trend_mechanism' "
            "warning under the default mode — §20.12.3 #2 requires "
            f"silent acceptance.  Offending record: {record!r}"
        )


def test_baseline_alpha_level2_signal_hash_unchanged() -> None:
    """The chosen baseline must match its locked signal hash and count."""
    from tests.determinism.test_signal_replay import (
        EXPECTED_LEVEL2_SIGNAL_COUNT,
        EXPECTED_LEVEL2_SIGNAL_HASH,
        _replay,
    )

    path = _baseline_alpha_path()
    actual_hash, actual_count = _replay(str(path))

    assert actual_count == EXPECTED_LEVEL2_SIGNAL_COUNT, (
        f"baseline alpha {path}: Level-2 signal count "
        f"{actual_count} != locked baseline "
        f"{EXPECTED_LEVEL2_SIGNAL_COUNT}.  §20.12.3 #2 requires bit-"
        "identical parity — investigate before updating either "
        "constant."
    )
    assert actual_hash == EXPECTED_LEVEL2_SIGNAL_HASH, (
        f"baseline alpha {path}: Level-2 signal hash drift\n"
        f"  Expected: {EXPECTED_LEVEL2_SIGNAL_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "§20.12.3 #2 requires bit-identical parity — do not update "
        "the locked hash without a written justification anchored to "
        "docs/acceptance/v02_v03_matrix.md."
    )


def test_baseline_alpha_level3_snapshot_hash_unchanged() -> None:
    """Re-confirm the Level-3 baseline (HorizonFeatureSnapshot) is green.

    The Level-3 baseline does not depend on the alpha YAML (it locks
    the snapshot stream from the sensor wiring), so this assertion is
    a *cross-check*: if the snapshot baseline ever drifts, no SIGNAL
    alpha — including the v0.2-without-TM baseline — can claim
    bit-identical Level-1–4 parity.
    """
    import tests.determinism.test_horizon_feature_snapshot_replay as level3

    level3.test_snapshot_stream_matches_locked_baseline()


# Level-4 intent parity is covered by end-to-end tests.
