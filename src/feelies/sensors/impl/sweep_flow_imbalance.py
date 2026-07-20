"""Measure signed intermarket-sweep aggression over event time.

Only exchange-stamped ISO prints passing this filter enter state:

- eligible iff sale condition **14 (ISO)** AND Class-A core after stripping
  the 41 (TTE) overlay — core ⊆ ``{14, 37}`` and contains 14;
- ``drop_correction_records = {10, 11, 12}`` (follow-on bookkeeping);
- retroactive corrections do not affect causal eligibility;
- unknown condition IDs are excluded.

Value::

    SFI = Σ(side · size) / (Σ size + ε)   ∈ [-1, 1]

Tick rule assigns direction; positive values indicate buy aggression. Warmth
requires enough eligible prints, and long eligible-print gaps flush the window.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from typing import Any, Mapping

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.protocol import SensorEmission

_EPS = 1e-12

# Class-A core after stripping overlay 41; ISO ID 14 is required.
DEFAULT_CLASS_A_CORE_IDS: frozenset[int] = frozenset({14, 37})
DEFAULT_OVERLAY_IDS: frozenset[int] = frozenset({41})
DEFAULT_ISO_ID: int = 14
DEFAULT_DROP_CORRECTION_RECORDS: frozenset[int] = frozenset({10, 11, 12})

# Known sale-condition IDs used for session pre-registration.
INTERPRETED_TRADE_CONDITION_IDS: frozenset[int] = frozenset(
    {
        2,
        7,
        8,
        9,
        10,
        12,
        13,
        14,
        15,
        16,
        17,
        22,
        29,
        32,
        35,
        37,
        41,
        52,
        53,
    }
)
INTERPRETED_CORRECTION_VALUES: frozenset[int | None] = frozenset({None, 0, 1, 7, 8, 10, 11, 12})


def _freeze_ints(values: Iterable[int] | None, default: frozenset[int]) -> frozenset[int]:
    if values is None:
        return default
    return frozenset(int(v) for v in values)


def is_class_a_intersect_id14(
    conditions: Sequence[int],
    *,
    iso_id: int = DEFAULT_ISO_ID,
    class_a_core_ids: frozenset[int] = DEFAULT_CLASS_A_CORE_IDS,
    overlay_ids: frozenset[int] = DEFAULT_OVERLAY_IDS,
) -> bool:
    """True iff the print carries ISO id-14 and passes Class-A after overlays."""
    core = frozenset(c for c in conditions if c not in overlay_ids)
    return iso_id in core and core.issubset(class_a_core_ids)


def unknown_trade_condition_ids(
    conditions: Sequence[int],
    *,
    interpreted: frozenset[int] = INTERPRETED_TRADE_CONDITION_IDS,
) -> frozenset[int]:
    """Ids outside the INTERPRETED TABLE (03b §6(a) offline guard input)."""
    return frozenset(conditions) - interpreted


class SweepFlowImbalanceSensor:
    """Signed, volume-normalised ISO-sweep imbalance over a rolling window.

    Parameters (all versioned in ``SensorSpec.params`` + provenance):

    - ``window_seconds`` (int, default 900): trailing event-time window.
    - ``min_eligible_prints`` (int, default 20): warm threshold.
    - ``max_gap_seconds`` (int, default 60): halt flush between eligible prints.
    - ``drop_correction_records``: follow-on corrections to drop ({10,11,12}).
    - ``iso_id`` / ``class_a_core_ids`` / ``overlay_ids``: Class-A ∩ id-14 rule.
    - ``epsilon`` (float, default 1e-12): denominator guard.
    """

    sensor_id: str = "sweep_flow_imbalance"
    sensor_version: str = "1.0.0"

    def __init__(
        self,
        *,
        sensor_id: str | None = None,
        sensor_version: str | None = None,
        window_seconds: int = 900,
        min_eligible_prints: int = 20,
        max_gap_seconds: int = 60,
        drop_correction_records: Iterable[int] | None = None,
        iso_id: int = DEFAULT_ISO_ID,
        class_a_core_ids: Iterable[int] | None = None,
        overlay_ids: Iterable[int] | None = None,
        epsilon: float = _EPS,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")
        if min_eligible_prints < 0:
            raise ValueError(f"min_eligible_prints must be >= 0, got {min_eligible_prints}")
        if max_gap_seconds <= 0:
            raise ValueError(f"max_gap_seconds must be > 0, got {max_gap_seconds}")
        if epsilon <= 0.0:
            raise ValueError(f"epsilon must be > 0, got {epsilon}")
        if sensor_id is not None:
            self.sensor_id = sensor_id
        if sensor_version is not None:
            self.sensor_version = sensor_version
        self._window_ns = window_seconds * 1_000_000_000
        self._min_eligible_prints = min_eligible_prints
        self._max_gap_ns = max_gap_seconds * 1_000_000_000
        self._drop_correction_records = _freeze_ints(
            drop_correction_records, DEFAULT_DROP_CORRECTION_RECORDS
        )
        self._iso_id = int(iso_id)
        self._class_a_core_ids = _freeze_ints(class_a_core_ids, DEFAULT_CLASS_A_CORE_IDS)
        self._overlay_ids = _freeze_ints(overlay_ids, DEFAULT_OVERLAY_IDS)
        if self._iso_id not in self._class_a_core_ids:
            raise ValueError(
                f"iso_id {self._iso_id} must be a member of class_a_core_ids "
                f"{sorted(self._class_a_core_ids)}"
            )
        self._epsilon = float(epsilon)

    @property
    def drop_correction_records(self) -> frozenset[int]:
        return self._drop_correction_records

    @property
    def class_a_core_ids(self) -> frozenset[int]:
        return self._class_a_core_ids

    @property
    def overlay_ids(self) -> frozenset[int]:
        return self._overlay_ids

    @property
    def iso_id(self) -> int:
        return self._iso_id

    def filter_params(self) -> dict[str, Any]:
        """Explicit versioned filter set (provenance / YAML mirror)."""
        return {
            "window_seconds": self._window_ns // 1_000_000_000,
            "min_eligible_prints": self._min_eligible_prints,
            "max_gap_seconds": self._max_gap_ns // 1_000_000_000,
            "drop_correction_records": sorted(self._drop_correction_records),
            "iso_id": self._iso_id,
            "class_a_core_ids": sorted(self._class_a_core_ids),
            "overlay_ids": sorted(self._overlay_ids),
            "epsilon": self._epsilon,
            "retroactive_stamp_conditioning": False,
        }

    def is_eligible(self, event: Trade) -> bool:
        """Class-A ∩ id-14 after correction drop; unknown ids never include."""
        if event.correction is not None and event.correction in self._drop_correction_records:
            return False
        return is_class_a_intersect_id14(
            event.conditions,
            iso_id=self._iso_id,
            class_a_core_ids=self._class_a_core_ids,
            overlay_ids=self._overlay_ids,
        )

    def initial_state(self) -> dict[str, Any]:
        return {
            "window": deque(),  # (ts_ns, signed_size, size)
            "signed_sum": 0,
            "vol_sum": 0,
            "last_trade_price": None,
            "last_side": +1,
            "last_event_ts_ns": None,
        }

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | None:
        del params  # filter/warm knobs are constructor-versioned
        if not isinstance(event, Trade):
            return None

        price = float(event.price)
        size = int(event.size)
        if size <= 0 or price <= 0.0:
            return None

        # 1. Correction drop (causal follow-ons only — never {1,7,8}).
        if event.correction is not None and event.correction in self._drop_correction_records:
            return None

        # 2. Class-A ∩ id-14 (unknown ids fail the intersection — no silent include).
        if not is_class_a_intersect_id14(
            event.conditions,
            iso_id=self._iso_id,
            class_a_core_ids=self._class_a_core_ids,
            overlay_ids=self._overlay_ids,
        ):
            return None

        ts = event.timestamp_ns
        last_ts = state["last_event_ts_ns"]
        window: deque[tuple[int, int, int]] = state["window"]

        # 3. Halt gap → flush (re-warm from this print).
        if last_ts is not None and (ts - last_ts) > self._max_gap_ns:
            window.clear()
            state["signed_sum"] = 0
            state["vol_sum"] = 0

        # 4. Tick-rule aggressor.
        last_price = state["last_trade_price"]
        if last_price is None:
            side = int(state["last_side"])
        elif price > last_price:
            side = +1
        elif price < last_price:
            side = -1
        else:
            side = int(state["last_side"])
        state["last_trade_price"] = price
        state["last_side"] = side
        state["last_event_ts_ns"] = ts

        signed = side * size
        window.append((ts, signed, size))
        state["signed_sum"] += signed
        state["vol_sum"] += size

        # 5. Evict expired.
        cutoff = ts - self._window_ns
        while window and window[0][0] < cutoff:
            _t, old_signed, old_sz = window.popleft()
            state["signed_sum"] -= old_signed
            state["vol_sum"] -= old_sz

        vol = state["vol_sum"]
        if vol <= 0:
            value = 0.0
        else:
            value = state["signed_sum"] / (float(vol) + self._epsilon)

        warm = len(window) >= self._min_eligible_prints

        return SensorEmission(value=value, warm=warm)


def recompute_sfi_from_window(
    window: Sequence[tuple[int, int, int]],
    *,
    epsilon: float = _EPS,
) -> float:
    """Full recompute of SFI from the eligible-print window (test oracle)."""
    if not window:
        return 0.0
    signed = sum(s for _t, s, _sz in window)
    vol = sum(sz for _t, _s, sz in window)
    if vol <= 0:
        return 0.0
    return signed / (float(vol) + epsilon)
