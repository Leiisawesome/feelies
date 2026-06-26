"""Edge realization calibration (close-the-loop: *calibrate* + *gate*).

The disclosed ``edge_estimate_bps`` is an author estimate; realized edge is
typically lower (audit central finding).  This module reconciles the two
from a window of fills and produces a per-alpha **calibration factor** in
``[0, 1]`` that shrinks the estimate the gates trade on toward what the alpha
actually realizes — Inv-4 (edge decays when exploited).

Two factors per alpha:

* ``haircut_factor`` = clamp(realized_mean / disclosed, 0, 1) — point shrink.
* ``lcb_factor``     = clamp(realized_LCB  / disclosed, 0, 1) — the *gate*
  factor: uses the **lower confidence bound** of realized edge
  (``mean - z·std/√n``), so the gate trades on a conservative estimate, not
  an optimistic point.  This is the audit's "gate on the lower bound, not the
  point estimate".

Insufficient evidence (``n < min_fills`` or no/zero disclosed edge) yields a
factor of **1.0** — no haircut until there is enough realized data, so an
uncalibrated fleet is unchanged (parity-preserving).

Determinism (Inv-5): factors are a **versioned, durable** input.
:func:`build_edge_calibrations` is pure; the store is written at a
session/epoch boundary and read at the next run's construction, so within a
replay the factors are fixed and replay stays bit-identical.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from feelies.storage.trade_journal import TradeRecord

DEFAULT_LCB_Z: float = 1.0
DEFAULT_MIN_FILLS: int = 30
DEFAULT_FACTOR_FLOOR: float = 0.0
CALIBRATION_SCHEMA_VERSION: str = "edge_calibration/1"


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _edge_bps(rec: TradeRecord) -> float:
    """Realized edge in bps = realized_pnl / notional × 1e4 (gross of fees,
    matching ``DecayDetector``'s convention)."""
    if rec.fill_price is None or rec.filled_quantity <= 0:
        return 0.0
    notional = float(rec.fill_price) * rec.filled_quantity
    if notional <= 0.0:
        return 0.0
    return float(rec.realized_pnl) / notional * 10_000.0


@dataclass(frozen=True, kw_only=True)
class EdgeCalibration:
    """Per-alpha realized-vs-disclosed edge calibration."""

    strategy_id: str
    n_fills: int
    realized_edge_bps_mean: float
    realized_edge_bps_std: float
    realized_edge_bps_lcb: float
    disclosed_edge_bps: float
    haircut_factor: float
    lcb_factor: float


def build_edge_calibrations(
    records: Iterable[TradeRecord],
    disclosed_edges: Mapping[str, float],
    *,
    z: float = DEFAULT_LCB_Z,
    min_fills: int = DEFAULT_MIN_FILLS,
    factor_floor: float = DEFAULT_FACTOR_FLOOR,
) -> dict[str, EdgeCalibration]:
    """Compute per-alpha edge calibration from a window of fills.

    Pure.  ``disclosed_edges`` maps ``strategy_id -> edge_estimate_bps`` (the
    alpha's disclosed ``cost_arithmetic.edge_estimate_bps``).  An alpha with
    fewer than ``min_fills`` fills, or no/zero disclosed edge, gets factors of
    1.0 (no haircut — insufficient evidence).
    """
    by_alpha: "OrderedDict[str, list[TradeRecord]]" = OrderedDict()
    for rec in records:
        by_alpha.setdefault(rec.strategy_id, []).append(rec)

    out: dict[str, EdgeCalibration] = {}
    for strategy_id, trades in by_alpha.items():
        edges = [_edge_bps(t) for t in trades]
        n = len(edges)
        mean = statistics.fmean(edges) if edges else 0.0
        std = statistics.stdev(edges) if n >= 2 else 0.0
        lcb = mean - z * std / math.sqrt(n) if n >= 2 else mean
        disclosed = float(disclosed_edges.get(strategy_id, 0.0))

        if n < min_fills or disclosed <= 0.0:
            haircut_factor = 1.0
            lcb_factor = 1.0
        else:
            haircut_factor = _clamp(mean / disclosed, factor_floor, 1.0)
            lcb_factor = _clamp(lcb / disclosed, 0.0, 1.0)

        out[strategy_id] = EdgeCalibration(
            strategy_id=strategy_id,
            n_fills=n,
            realized_edge_bps_mean=mean,
            realized_edge_bps_std=std,
            realized_edge_bps_lcb=lcb,
            disclosed_edge_bps=disclosed,
            haircut_factor=haircut_factor,
            lcb_factor=lcb_factor,
        )
    return out


class EdgeCalibrationStore:
    """Durable, versioned JSON store of per-alpha edge calibrations.

    The gate reads :meth:`factors` (``strategy_id -> lcb_factor``) at
    construction; the session-reconcile job writes via :meth:`save`.  Absent
    file -> empty factors -> no haircut (parity-preserving).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def save(
        self,
        calibrations: Mapping[str, EdgeCalibration],
        *,
        version: str,
    ) -> None:
        """Write calibrations as deterministic, sorted JSON."""
        payload = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "version": version,
            "factors": {sid: asdict(calibrations[sid]) for sid in sorted(calibrations)},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def load(self) -> dict[str, EdgeCalibration]:
        if not self._path.exists():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        out: dict[str, EdgeCalibration] = {}
        for sid, rec in payload.get("factors", {}).items():
            out[sid] = EdgeCalibration(**rec)
        return out

    def factors(self, *, use_lcb: bool = True) -> dict[str, float]:
        """``strategy_id -> calibration factor`` for the gate.

        ``use_lcb`` (default True) returns the lower-confidence-bound factor
        — the conservative gate factor; ``False`` returns the point haircut.
        """
        return {
            sid: (cal.lcb_factor if use_lcb else cal.haircut_factor)
            for sid, cal in self.load().items()
        }


__all__ = [
    "EdgeCalibration",
    "EdgeCalibrationStore",
    "build_edge_calibrations",
    "DEFAULT_LCB_Z",
    "DEFAULT_MIN_FILLS",
    "DEFAULT_FACTOR_FLOOR",
    "CALIBRATION_SCHEMA_VERSION",
]
