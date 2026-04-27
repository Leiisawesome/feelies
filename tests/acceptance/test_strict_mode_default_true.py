"""Closes acceptance row 84 — Workstream **E**'s default flip.

Row 84 of ``docs/acceptance/v02_v03_matrix.md``::

    | enforce_trend_mechanism: true flip | Held until ≥3 reference
    | alphas (one per non-stress family) have shipped under strict
    | mode in research/paper trading per §20.12.1.  Workstream **E**.

This module locks the *default-True* contract from four angles:

1. **Dataclass default** —
   :class:`feelies.core.platform_config.PlatformConfig` constructed
   with no ``enforce_trend_mechanism`` keyword resolves to ``True``.
   This is the primary surface for production bootstrap and any
   in-process consumer.

2. **YAML parser default** — :meth:`PlatformConfig.from_yaml` against
   a YAML file that *omits* the ``enforce_trend_mechanism:`` key
   resolves to ``True`` (the dataclass and YAML defaults must agree
   bit-for-bit so a YAML omission and a Python construction land in
   the same place).

3. **End-to-end refusal under default** — feeding a schema-1.1
   SIGNAL spec missing its ``trend_mechanism:`` block through
   :class:`feelies.alpha.loader.AlphaLoader` configured with the
   *new* default raises
   :class:`feelies.alpha.layer_validator.MissingTrendMechanismError`
   from gate G16.

4. **v0.2 parity preserved on explicit opt-out** — the §20.12.3 #2
   reference alpha ``pofi_benign_midcap_v1`` still loads under
   :class:`AlphaLoader` when the operator pins
   ``enforce_trend_mechanism=False`` (the documented escape hatch
   for v0.2-baseline alphas pre-dating the mechanism taxonomy).

Why this acceptance suite exists separately
===========================================

The pre-flip parity contract (§20.12.3 #2) is locked by
:mod:`tests.acceptance.test_v02_no_trend_mechanism_parity`.  The
post-flip default contract (§20.12.1, row 84) needs its own
locked-in suite because flipping the default is **the** definition
of "Workstream E complete" and a future contributor reverting the
flip (intentionally or not) must trip a clearly-named test that
points back at this acceptance row.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from feelies.alpha.layer_validator import MissingTrendMechanismError
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.platform_config import PlatformConfig


# ── §20.12.3 #2 v0.2 reference alpha ────────────────────────────────────


_V02_BASELINE_ALPHA = (
    Path("alphas")
    / "pofi_benign_midcap_v1"
    / "pofi_benign_midcap_v1.alpha.yaml"
)


# A schema-1.1 SIGNAL spec missing the ``trend_mechanism:`` block.
# Used as a *negative* fixture: under the new default, the loader
# must refuse this; under explicit opt-out, it must accept.
_SIGNAL_SPEC_NO_MECHANISM: dict[str, object] = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "alpha_under_default_test",
    "version": "1.0.0",
    "description": "default-flip acceptance fixture",
    "hypothesis": "fixture",
    "falsification_criteria": ["criterion 1"],
    "horizon_seconds": 120,
    "depends_on_sensors": ["ofi_ewma", "spread_z_30d"],
    "regime_gate": {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.7",
        "off_condition": "P(normal) < 0.5",
    },
    "cost_arithmetic": {
        "edge_estimate_bps": 9.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 1.8,
    },
    "signal": (
        "def evaluate(snapshot, regime, params):\n"
        "    return None\n"
    ),
}


def _base_config(**overrides: object) -> PlatformConfig:
    base: dict[str, object] = {
        "symbols": frozenset({"AAPL"}),
        "alpha_specs": [Path("dummy.alpha.yaml")],
    }
    base.update(overrides)
    return PlatformConfig(**base)  # type: ignore[arg-type]


# ── Surface 1: dataclass default ────────────────────────────────────────


class TestDataclassDefaultIsTrue:
    """The bare ``PlatformConfig(...)`` resolves to strict mode."""

    def test_default_resolves_to_true(self) -> None:
        cfg = _base_config()
        assert cfg.enforce_trend_mechanism is True, (
            "Workstream E flipped the dataclass default to True; if "
            "this test fails, someone reverted the flip — see "
            "docs/acceptance/v02_v03_matrix.md row 84."
        )

    def test_default_passes_validate(self) -> None:
        # A default-True config must not fail validation on its own
        # — that would imply default-True breaks the platform's own
        # bootstrap before any alpha is even loaded.
        _base_config().validate()


# ── Surface 2: YAML parser default ──────────────────────────────────────


class TestYAMLParserDefaultIsTrue:
    """An absent ``enforce_trend_mechanism:`` key in YAML resolves to True."""

    def test_omitted_yaml_key_resolves_to_true(self, tmp_path: Path) -> None:
        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
                symbols: [AAPL]
                alpha_specs: [dummy.alpha.yaml]
            """).strip()
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is True

    def test_explicit_false_in_yaml_still_loads(self, tmp_path: Path) -> None:
        # Sanity check on the operator-facing escape hatch: the
        # reference platform.yaml at the repo root pins
        # ``enforce_trend_mechanism: false`` because it points at
        # the v0.2-baseline reference alpha; that explicit pin must
        # continue to round-trip cleanly under default-True.
        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
                symbols: [AAPL]
                alpha_specs: [dummy.alpha.yaml]
                enforce_trend_mechanism: false
            """).strip()
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.enforce_trend_mechanism is False

    def test_dataclass_and_yaml_defaults_agree(self, tmp_path: Path) -> None:
        """The two defaults must report the same value.

        A divergence would silently shift behaviour depending on
        whether a config is constructed in Python or loaded from
        YAML — the kind of seam Workstream E was specifically
        avoiding.
        """
        dataclass_default = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
        ).enforce_trend_mechanism

        path = tmp_path / "platform.yaml"
        path.write_text(
            dedent("""
                symbols: [AAPL]
                alpha_specs: [dummy.alpha.yaml]
            """).strip()
        )
        yaml_default = (
            PlatformConfig.from_yaml(path).enforce_trend_mechanism
        )
        assert dataclass_default is yaml_default


# ── Surface 3: end-to-end loader refusal under default ──────────────────


class TestLoaderRefusesMissingMechanismUnderDefault:
    """The new default flows through bootstrap into AlphaLoader and
    refuses a schema-1.1 SIGNAL spec missing ``trend_mechanism:``.
    """

    def test_loader_refuses_no_mechanism_under_platform_default(self) -> None:
        # We thread the *PlatformConfig* default through the loader
        # explicitly (mirroring bootstrap.py) — this guards the
        # specific seam Workstream E was tightening: default flip ⇒
        # production load behaviour flips ⇒ G16 fires for missing
        # mechanism blocks at boot time without any operator action.
        platform_default = _base_config().enforce_trend_mechanism
        loader = AlphaLoader(enforce_trend_mechanism=platform_default)
        with pytest.raises(MissingTrendMechanismError, match="strict-mode"):
            loader.load_from_dict(
                dict(_SIGNAL_SPEC_NO_MECHANISM), source="<acceptance-test>"
            )


# ── Surface 4: v0.2 parity preserved on explicit opt-out ────────────────


class TestV02ParityPreservedOnExplicitOptOut:
    """The §20.12.3 #2 v0.2 baseline reference alpha
    (``pofi_benign_midcap_v1``) still loads when the operator pins
    ``enforce_trend_mechanism=False`` — this is the documented
    escape hatch for v0.2-baseline alphas that pre-date the
    mechanism taxonomy.
    """

    def test_v02_baseline_alpha_loads_with_explicit_opt_out(self) -> None:
        assert _V02_BASELINE_ALPHA.exists(), (
            f"v0.2 baseline reference alpha missing at "
            f"{_V02_BASELINE_ALPHA}; the §20.12.3 #2 parity contract "
            "cannot be verified."
        )
        loader = AlphaLoader(enforce_trend_mechanism=False)
        module = loader.load(_V02_BASELINE_ALPHA)
        assert isinstance(module, LoadedSignalLayerModule), (
            f"v0.2 baseline alpha loaded as {type(module).__name__}; "
            "expected LoadedSignalLayerModule."
        )

    def test_v02_baseline_alpha_refused_under_default(self) -> None:
        """Cross-check: the same alpha must be refused under the
        new platform default.  Flipping the default and silently
        accepting v0.2 alphas would be the worst-of-both-worlds
        regression — strict mode advertised but not enforced.
        """
        platform_default = _base_config().enforce_trend_mechanism
        loader = AlphaLoader(enforce_trend_mechanism=platform_default)
        with pytest.raises(MissingTrendMechanismError, match="strict-mode"):
            loader.load(_V02_BASELINE_ALPHA)
