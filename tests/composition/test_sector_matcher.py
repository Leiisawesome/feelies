"""Unit tests for :class:`feelies.composition.sector_matcher.SectorMatcher`.

Within-sector net exposure must be driven to
zero (not merely shrunk) by scaling only the dominant side, while the
offsetting side and within-side ranking are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

from feelies.composition.sector_matcher import SectorMatcher

_SECTOR_MAP = {
    "AAPL": "TECH",
    "MSFT": "TECH",
    "NVDA": "TECH",
    "JPM": "FIN",
    "BAC": "FIN",
    "XOM": "ENERGY",
}


def _matcher(tmp_path: Path) -> SectorMatcher:
    path = tmp_path / "sector_map.json"
    path.write_text(json.dumps(_SECTOR_MAP), encoding="utf-8")
    return SectorMatcher(sector_map_path=path)


def _sector_net(out: dict[str, float], members: tuple[str, ...]) -> float:
    return sum(out.get(s, 0.0) for s in members)


def test_inactive_matcher_is_identity() -> None:
    sm = SectorMatcher(sector_map_path=None)
    weights = {"AAPL": 0.5, "MSFT": -0.3}
    assert sm.neutralize(weights, ("AAPL", "MSFT")) == weights


def test_longs_dominant_net_goes_to_zero(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    # TECH: longs 0.6 + 0.2 = 0.8, short -0.3 → net +0.5.
    weights = {"AAPL": 0.6, "MSFT": 0.2, "NVDA": -0.3}
    out = sm.neutralize(weights, ("AAPL", "MSFT", "NVDA"))
    assert abs(_sector_net(out, ("AAPL", "MSFT", "NVDA"))) < 1e-9
    # Short side untouched; longs scaled by 0.3/0.8 = 0.375.
    assert out["NVDA"] == -0.3
    assert out["AAPL"] == 0.6 * (0.3 / 0.8)
    assert out["MSFT"] == 0.2 * (0.3 / 0.8)
    # Within-side ranking preserved: AAPL still the larger long.
    assert out["AAPL"] > out["MSFT"] > 0.0


def test_shorts_dominant_net_goes_to_zero(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    # FIN: long 0.2, short -0.5 → net -0.3.
    weights = {"JPM": 0.2, "BAC": -0.5}
    out = sm.neutralize(weights, ("JPM", "BAC"))
    assert abs(_sector_net(out, ("JPM", "BAC"))) < 1e-9
    # Long side untouched; short scaled by 0.2/0.5.
    assert out["JPM"] == 0.2
    assert out["BAC"] == -0.5 * (0.2 / 0.5)


def test_one_sided_sector_is_flattened(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    # TECH has only longs → no offsetting short → flatten to zero.
    weights = {"AAPL": 0.4, "MSFT": 0.1}
    out = sm.neutralize(weights, ("AAPL", "MSFT"))
    assert out["AAPL"] == 0.0
    assert out["MSFT"] == 0.0


def test_already_neutral_sector_untouched(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    weights = {"AAPL": 0.3, "MSFT": -0.3}
    out = sm.neutralize(weights, ("AAPL", "MSFT"))
    assert out == weights


def test_sectors_are_independent(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    weights = {
        "AAPL": 0.6,
        "NVDA": -0.3,  # TECH net +0.3
        "JPM": -0.5,
        "BAC": 0.2,  # FIN net -0.3
        "XOM": 0.4,  # ENERGY one-sided
    }
    out = sm.neutralize(weights, ("AAPL", "BAC", "JPM", "NVDA", "XOM"))
    assert abs(_sector_net(out, ("AAPL", "NVDA"))) < 1e-9
    assert abs(_sector_net(out, ("JPM", "BAC"))) < 1e-9
    assert out["XOM"] == 0.0


def test_neutralize_is_deterministic(tmp_path: Path) -> None:
    sm = _matcher(tmp_path)
    weights = {"AAPL": 0.6, "MSFT": 0.2, "NVDA": -0.3, "JPM": -0.4, "BAC": 0.1}
    universe = ("AAPL", "BAC", "JPM", "MSFT", "NVDA")
    assert sm.neutralize(weights, universe) == sm.neutralize(weights, universe)
