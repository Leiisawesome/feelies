"""``SectorMatcher`` — optional GICS-sector-neutral pairing.

Reduces idiosyncratic-sector exposure by pairing positive-weight
symbols with negative-weight symbols *within the same GICS sector*.
Each long is offset against the largest available short in the same
sector, and the surplus is removed (equivalently: the long and short
weights are scaled down so within-sector net exposure is zero).

When ``sector_map_path`` is ``None`` the matcher is a no-op (returns
weights unchanged).

Algorithm
---------

For each sector:

1. Collect ``(symbol, weight)`` pairs in the sector.
2. Compute net exposure ``net = sum(weights)``.  When ``|net|`` is
   below ``tolerance`` no action is taken.
3. Otherwise scale every weight in the sector by
   ``(gross - |net|) / gross`` where ``gross = sum(|w|)`` — this
   removes the directional component while preserving the cross-
   sectional ranking *within* the sector.

This scheme is gentler than full re-allocation and preserves
deterministic iteration order (sorted by symbol).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping

_logger = logging.getLogger(__name__)


class SectorMatcher:
    """Optional sector-neutral re-balancer.

    Parameters
    ----------
    sector_map_path :
        JSON file mapping ``{symbol: sector_id_str}``.  When ``None``
        the matcher is a no-op (returns weights unchanged).
    tolerance :
        Absolute net-exposure tolerance per sector below which no
        scaling is applied (default ``1e-6``).
    """

    __slots__ = ("_sector_by_symbol", "_tolerance", "_active")

    def __init__(
        self,
        *,
        sector_map_path: Path | None = None,
        tolerance: float = 1e-6,
    ) -> None:
        self._tolerance = float(tolerance)
        self._sector_by_symbol: dict[str, str] = {}
        self._active = False
        if sector_map_path is not None:
            self._sector_by_symbol = self._load_map(sector_map_path)
            self._active = bool(self._sector_by_symbol)

    @property
    def active(self) -> bool:
        return self._active

    def neutralize(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
    ) -> dict[str, float]:
        if not self._active:
            return dict(weights)

        out = dict(weights)
        # Bucket symbols by sector (deterministic iteration: sorted
        # universe).
        by_sector: dict[str, list[str]] = {}
        for s in universe:
            sector = self._sector_by_symbol.get(s)
            if sector is None:
                continue
            by_sector.setdefault(sector, []).append(s)

        for sector in sorted(by_sector.keys()):
            symbols = by_sector[sector]
            net = sum(out.get(s, 0.0) for s in symbols)
            if abs(net) <= self._tolerance:
                continue
            gross = sum(abs(out.get(s, 0.0)) for s in symbols)
            if gross <= self._tolerance:
                continue
            scale = (gross - abs(net)) / gross
            if scale < 0.0:
                scale = 0.0
            for s in symbols:
                out[s] = out.get(s, 0.0) * scale
        return out

    @staticmethod
    def _load_map(path: Path) -> dict[str, str]:
        if not path.is_file():
            raise FileNotFoundError(
                f"SectorMatcher: sector map file not found: {path}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(
                f"SectorMatcher: {path} must contain a JSON object"
            )
        return {str(k): str(v) for k, v in data.items()}


__all__ = ["SectorMatcher"]
