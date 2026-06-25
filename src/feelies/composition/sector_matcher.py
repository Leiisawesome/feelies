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
3. Otherwise scale **only the dominant side** down so the two sides
   match and the within-sector net becomes zero: if longs dominate
   (``net > 0``) every long is multiplied by ``short_sum / long_sum``;
   if shorts dominate every short is multiplied by
   ``long_sum / short_sum``.  This drives ``net → 0`` exactly while
   preserving the cross-sectional ranking *within* each side (audit
   P1-3).  When the offsetting side is empty the dominant side is
   scaled to zero (a one-sided sector cannot be made neutral except by
   flattening it).

Uniformly scaling *both* sides — the prior implementation — leaves the
net/gross ratio invariant and so never reaches ``net = 0``; it only
shrinks gross.  Iteration order is deterministic (sorted by symbol).
"""

from __future__ import annotations

import hashlib
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

    def provenance_digest(self) -> str:
        """Stable digest of the sector map and tolerance (audit P0-2).

        Folded into the composition-layer ``decision_basis_hash`` so the
        digest changes when the sector taxonomy or tolerance changes.  An
        inactive matcher (no map configured) still yields a stable digest.
        """
        parts = [f"active={self._active}", f"tol={self._tolerance:.10g}"]
        for sym in sorted(self._sector_by_symbol):
            parts.append(f"{sym}={self._sector_by_symbol[sym]}")
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

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
            long_sum = sum(w for w in (out.get(s, 0.0) for s in symbols) if w > 0.0)
            short_sum = -sum(w for w in (out.get(s, 0.0) for s in symbols) if w < 0.0)
            if net > 0.0:
                # Longs dominate — shrink the long side to equal the shorts.
                scale = short_sum / long_sum if long_sum > 0.0 else 0.0
                for s in symbols:
                    w = out.get(s, 0.0)
                    if w > 0.0:
                        out[s] = w * scale
            else:
                # Shorts dominate — shrink the short side to equal the longs.
                scale = long_sum / short_sum if short_sum > 0.0 else 0.0
                for s in symbols:
                    w = out.get(s, 0.0)
                    if w < 0.0:
                        out[s] = w * scale
        return out

    @staticmethod
    def _load_map(path: Path) -> dict[str, str]:
        if not path.is_file():
            raise FileNotFoundError(f"SectorMatcher: sector map file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"SectorMatcher: {path} must contain a JSON object")
        return {str(k): str(v) for k, v in data.items()}


__all__ = ["SectorMatcher"]
