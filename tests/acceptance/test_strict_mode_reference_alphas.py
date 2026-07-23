"""Strict-mode loading and replay checks for reference signal alphas.

One alpha per non-stress mechanism family must pass G16 and produce the same
signal stream across identical runs. Liquidity stress is exit-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.events import TrendMechanism


_ALPHAS_ROOT = Path("alphas")


# One reference signal alpha per non-stress family.
_REFERENCE_BY_FAMILY: tuple[tuple[TrendMechanism, str], ...] = (
    (TrendMechanism.KYLE_INFO, "sig_kyle_drift_v1"),
    (TrendMechanism.INVENTORY, "sig_inventory_revert_v1"),
    (TrendMechanism.HAWKES_SELF_EXCITE, "sig_hawkes_burst_v1"),
    (TrendMechanism.SCHEDULED_FLOW, "sig_moc_imbalance_v1"),
)


def _alpha_path(alpha_id: str) -> Path:
    return _ALPHAS_ROOT / alpha_id / f"{alpha_id}.alpha.yaml"


@pytest.mark.parametrize(
    ("family", "alpha_id"),
    _REFERENCE_BY_FAMILY,
    ids=lambda x: x.name if isinstance(x, TrendMechanism) else x,
)
def test_reference_alpha_loads_under_strict_mode(
    family: TrendMechanism,
    alpha_id: str,
) -> None:
    path = _alpha_path(alpha_id)
    assert path.exists(), (
        f"reference alpha YAML missing at {path}; §20.12.2 #4 row "
        f"for family {family.name} cannot be verified."
    )

    loader = AlphaLoader(enforce_trend_mechanism=True)
    module = loader.load(path)

    assert isinstance(module, LoadedSignalLayerModule), (
        f"{alpha_id!r} loaded as {type(module).__name__}; expected "
        "LoadedSignalLayerModule.  §20.12.2 #4 governs SIGNAL-layer "
        "alphas only — update _REFERENCE_BY_FAMILY if the YAML's "
        "layer changed."
    )
    assert module.trend_mechanism_enum == family, (
        f"{alpha_id!r}: declared trend_mechanism.family is "
        f"{module.trend_mechanism_enum}, expected {family}.  "
        "_REFERENCE_BY_FAMILY in this test must list the correct "
        "alpha for each family — fix the mapping or the YAML."
    )
    assert module.expected_half_life_seconds > 0, (
        f"{alpha_id!r}: expected_half_life_seconds must be > 0 under "
        "strict mode (G16 rule 2 enforces a per-family floor); got "
        f"{module.expected_half_life_seconds}"
    )


@pytest.mark.parametrize(
    ("family", "alpha_id"),
    _REFERENCE_BY_FAMILY,
    ids=lambda x: x.name if isinstance(x, TrendMechanism) else x,
)
def test_reference_alpha_signal_stream_is_deterministic(
    family: TrendMechanism,
    alpha_id: str,
) -> None:
    """The canonical fixture produces the same hash on both runs."""
    from tests.determinism.test_signal_replay import _replay

    path = str(_alpha_path(alpha_id))
    hash_a, count_a = _replay(path)
    hash_b, count_b = _replay(path)

    assert count_a == count_b, (
        f"{alpha_id!r}: signal count drift between two replays "
        f"({count_a} vs {count_b}) — non-determinism in the strict-"
        "mode reference alpha violates §20.12.2 #4."
    )
    assert hash_a == hash_b, (
        f"{alpha_id!r}: Level-2 signal hash drift between two replays\n"
        f"  Run A: {hash_a}\n  Run B: {hash_b}\n"
        "Non-determinism in a strict-mode reference alpha violates "
        "§20.12.2 #4."
    )
