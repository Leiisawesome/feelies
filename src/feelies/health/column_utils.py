"""Loose column name resolution for CSV/JSON research artifacts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _norm_key(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def row_get(row: Mapping[str, Any], *candidates: str) -> Any:
    """Return first non-empty value matching any candidate (case/spacing-insensitive)."""

    inv = {_norm_key(k): v for k, v in row.items()}
    for c in candidates:
        k = _norm_key(c)
        if k in inv and inv[k] not in ("", None):
            return inv[k]
    return None


def row_float(row: Mapping[str, Any], *candidates: str) -> float | None:
    raw = row_get(row, *candidates)
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or not math.isfinite(v):
        return None
    return v


def row_int(row: Mapping[str, Any], *candidates: str) -> int | None:
    raw = row_get(row, *candidates)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def row_str(row: Mapping[str, Any], *candidates: str) -> str | None:
    raw = row_get(row, *candidates)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


__all__ = ["row_float", "row_get", "row_int", "row_str"]
