"""Closes G-C — §20.12.3 #2 v0.2-without-``trend_mechanism`` parity.

§20.12.3 #2 of ``design_docs/three_layer_architecture.md`` requires
that a v0.2 SIGNAL alpha that does **not** declare a
``trend_mechanism:`` block continues to load and run with bit-
identical Level-1–4 parity hashes under v0.3 code, with the loader
running in its v0.3 default mode (``enforce_trend_mechanism=False``).

The companion file ``_chosen_v02_baseline_alpha.txt`` records the
single alpha id this acceptance test uses as its v0.2-without-TM
baseline.  This indirection is deliberate: if a future PR renames
the alpha or moves it under a different directory, only that one
plain-text file changes — no Python edit needed — and the bond
between matrix row §20.12.3 #2 and the asserting test stays in
exactly one place.

This test is intentionally redundant with the locked hashes already
asserted by the Phase-3 / 4 / 4.1 determinism suite; the redundancy
is load-bearing because:

* The existing replay tests assert the *hash* without asserting the
  *absence* of ``trend_mechanism:`` in the underlying YAML.  A
  contributor who silently adds a ``trend_mechanism:`` block to the
  baseline alpha (and updates the hash) would not break those tests
  but would break the §20.12.3 #2 contract.
* The existing tests assert each level independently; this file
  asserts the *conjunction* (all four levels green for the chosen
  baseline) so the acceptance matrix's #2 row maps to one unambiguous
  green dot.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule


_BASELINE_ALPHA_FILE = Path(__file__).with_name(
    "_chosen_v02_baseline_alpha.txt"
)


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


# Workstream D.2 retired the loader's once-per-process LEGACY_SIGNAL
# sunset banner along with the per-tick legacy code-path.  The
# previous autouse fixture cleared that dedup set; with the set gone
# there is nothing to reset between tests.


def test_baseline_alpha_yaml_has_no_trend_mechanism_block() -> None:
    """The chosen baseline must not declare ``trend_mechanism:``.

    This is the *YAML-level* assertion that pins the contract — the
    asserting test for §20.12.3 #2 is meaningless if the baseline
    alpha has gained a trend_mechanism block in the meantime.
    """
    path = _baseline_alpha_path()
    assert path.exists(), (
        f"baseline alpha YAML missing at {path}; either restore the "
        "file or pick a new baseline by editing "
        f"{_BASELINE_ALPHA_FILE}."
    )

    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(spec, dict), (
        f"{path}: top-level YAML must be a mapping"
    )
    assert spec.get("schema_version") == "1.1", (
        f"{path}: §20.12.3 #2 requires the baseline to be a "
        "schema-1.1 SIGNAL alpha (the contract is precisely about "
        "what 1.1 loaders do with a 1.1 alpha that omits the "
        f"optional trend_mechanism: block); got "
        f"schema_version={spec.get('schema_version')!r}."
    )
    assert spec.get("layer") == "SIGNAL", (
        f"{path}: §20.12.3 #2 governs SIGNAL-layer alphas; "
        f"got layer={spec.get('layer')!r}."
    )
    assert "trend_mechanism" not in spec, (
        f"{path}: the baseline alpha gained a top-level "
        "trend_mechanism: block.  §20.12.3 #2 measures the contract "
        "for v0.2 SIGNAL alphas that *omit* trend_mechanism — pick "
        f"a different baseline by editing {_BASELINE_ALPHA_FILE} or "
        "remove the block here."
    )


def test_baseline_alpha_loads_under_v03_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The loader must accept the alpha under ``enforce_trend_mechanism=False``.

    Per §20.12.3 #2 the v0.3 loader's *default* must remain non-strict
    so v0.2 SIGNAL alphas continue to load without modification.
    """
    path = _baseline_alpha_path()

    with caplog.at_level(logging.WARNING, logger="feelies.alpha.loader"):
        loader = AlphaLoader()  # default = enforce_trend_mechanism=False
        module = loader.load(path)

    assert isinstance(module, LoadedSignalLayerModule), (
        f"baseline must load as LoadedSignalLayerModule; got "
        f"{type(module).__name__}"
    )
    assert module.trend_mechanism_enum is None, (
        "a v0.2 SIGNAL alpha without trend_mechanism: must load with "
        "module.trend_mechanism_enum is None — found "
        f"{module.trend_mechanism_enum!r}"
    )
    assert module.expected_half_life_seconds == 0, (
        "a v0.2 SIGNAL alpha without trend_mechanism: must load with "
        "expected_half_life_seconds == 0 — found "
        f"{module.expected_half_life_seconds}"
    )

    # Loading must not have surfaced a "missing trend_mechanism" error
    # or a stray G16 warning — those would only appear under
    # enforce_trend_mechanism=True, which §20.12.3 #2 explicitly says
    # is NOT the v0.3 default.
    for record in caplog.records:
        msg = record.getMessage().lower()
        assert "trend_mechanism" not in msg or "missing" not in msg, (
            "loader emitted an unexpected 'missing trend_mechanism' "
            "warning under the default mode — §20.12.3 #2 requires "
            f"silent acceptance.  Offending record: {record!r}"
        )


def test_baseline_alpha_level2_signal_hash_unchanged() -> None:
    """Re-run the Level-2 replay on the baseline; assert locked hash.

    This is a delegation: it imports the existing Level-2 replay
    helper, calls it with the chosen baseline path, and compares the
    resulting hash + count against the constants the Phase-3 lock-down
    pinned.  If a future PR moves the baseline alpha to a different id
    *and* that id has a non-empty Level-2 stream, the assertion fails
    loudly and the matrix row must be updated together with the
    baseline file.
    """
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


# ── Workstream-D note ────────────────────────────────────────────────────
# The Level-1 LEGACY-fill assertion that previously lived here delegated
# into ``tests/determinism/test_legacy_alpha_parity.py`` and the
# ``trade_cluster_drift`` reference alpha.  Both were retired in
# Workstream D.2 with explicit user sign-off (Path C); §20.12.3 #2 now
# asserts on Levels 2–3 only.  Level-4 (sized intent stream) is anchored
# by the Phase-4 e2e determinism tests (``tests/integration/
# test_phase4_e2e.py``) which the matrix row already cross-references.
# Restoring a Level-1 assertion requires (a) a new SIGNAL- or PORTFOLIO-
# layer Level-1 fill replay and (b) a matrix-row update; do not silently
# re-add a LEGACY-anchored delegation.
