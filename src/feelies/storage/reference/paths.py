"""Bundled reference artefacts (YAML / JSON) shipped with the package.

Repo layouts historically referenced a top-level ``storage/reference/``
tree; that data now lives alongside :mod:`feelies.storage.reference`
so :mod:`feelies.storage` is the single source of truth for both
implementation code and committed reference files.

Use these paths from tests and scripts so cwd-independent resolution
matches bootstrap behaviour when configs pass explicit ``Path`` objects.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# Directory containing per-session calendar YAML (same package subtree as
# :func:`feelies.storage.reference.event_calendar.load_event_calendar`).
EVENT_CALENDAR_DIR: Path = _ROOT / "event_calendar"

# Directory containing ``loadings.json`` (and optional ``loadings.parquet``).
FACTOR_LOADINGS_DIR: Path = _ROOT / "factor_loadings"

# Flat ``{symbol: sector_id}`` JSON consumed by :class:`SectorMatcher`.
SECTOR_MAP_PATH: Path = _ROOT / "sector_map" / "sector_map.json"

__all__ = [
    "EVENT_CALENDAR_DIR",
    "FACTOR_LOADINGS_DIR",
    "SECTOR_MAP_PATH",
]
