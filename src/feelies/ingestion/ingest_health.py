"""Aggregate ingestion-time DataHealth across (symbol, day) rows for backtest boot."""

from __future__ import annotations

from collections.abc import Sequence

from feelies.ingestion.data_integrity import DataHealth

_HEALTH_RANK: dict[DataHealth, int] = {
    DataHealth.HEALTHY: 0,
    DataHealth.GAP_DETECTED: 1,
    DataHealth.HALTED: 2,
    DataHealth.CORRUPTED: 3,
}


def parse_ingestion_health_label(label: str | None) -> DataHealth:
    """Map manifest / DaySource ingestion_health strings to :class:`DataHealth`."""
    if label is None or label == "HEALTHY":
        return DataHealth.HEALTHY
    try:
        return DataHealth[label]
    except KeyError:
        return DataHealth.CORRUPTED


def merge_worst_health(current: DataHealth, incoming: DataHealth) -> DataHealth:
    """Pick the more severe state (CORRUPTED > HALTED > GAP_DETECTED > HEALTHY)."""
    if _HEALTH_RANK[incoming] > _HEALTH_RANK[current]:
        return incoming
    return current


def terminal_symbol_health_rows(
    symbols: Sequence[str],
    day_sources: Sequence[object],
) -> tuple[tuple[str, str], ...]:
    """Worst :class:`DataHealth` per configured symbol across all day rows.

    Each *day_sources* element must provide ``symbol`` and optional
    ``ingestion_health`` string attributes (e.g. CLI day provenance objects).
    """
    canon = sorted({s.upper() for s in symbols})
    worst: dict[str, DataHealth] = {s: DataHealth.HEALTHY for s in canon}
    for ds in day_sources:
        raw_sym = getattr(ds, "symbol", "") or ""
        sym_u = str(raw_sym).upper()
        if sym_u not in worst:
            continue
        label = getattr(ds, "ingestion_health", None)
        h = parse_ingestion_health_label(str(label) if label is not None else None)
        worst[sym_u] = merge_worst_health(worst[sym_u], h)
    return tuple((s, worst[s].name) for s in canon)
