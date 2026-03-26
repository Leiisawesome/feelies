"""Schema migration tooling for alpha spec YAML files.

Reads an ``.alpha.yaml`` file, checks its ``schema_version``, and
applies forward migrations (adding missing fields with defaults,
renaming deprecated keys).  Returns the migrated spec dict.

Designed for offline tooling use — not called during runtime.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = "1.0"


def migrate_spec(spec_path: Path) -> dict[str, Any]:
    """Read an alpha spec and apply forward migrations.

    Returns the migrated spec dict (does not write back to disk).

    Raises:
        FileNotFoundError: If the spec file doesn't exist.
        yaml.YAMLError: If the file isn't valid YAML.
        ValueError: If the spec is not a dict.
    """
    raw = spec_path.read_text(encoding="utf-8")
    spec = yaml.safe_load(raw)

    if not isinstance(spec, dict):
        raise ValueError(f"{spec_path}: root must be a YAML mapping")

    source_version = spec.get("schema_version")

    if source_version is None:
        logger.info(
            "%s: no schema_version — applying v1.0 defaults",
            spec_path,
        )
        spec["schema_version"] = "1.0"
        source_version = "1.0"

    if source_version == "1.0":
        spec = _migrate_to_1_0(spec, str(spec_path))

    return spec


def _migrate_to_1_0(spec: dict[str, Any], source: str) -> dict[str, Any]:
    """Ensure all v1.0 fields exist with sensible defaults."""

    spec.setdefault("risk_budget", {})
    rb = spec["risk_budget"]
    rb.setdefault("max_position_per_symbol", 100)
    rb.setdefault("max_gross_exposure_pct", 5.0)
    rb.setdefault("max_drawdown_pct", 1.0)
    rb.setdefault("capital_allocation_pct", 10.0)

    spec.setdefault("parameters", {})

    if isinstance(spec.get("features"), dict):
        for _fid, fspec in spec["features"].items():
            if isinstance(fspec, dict):
                fspec.setdefault("warm_up", {})
                fspec["warm_up"].setdefault("min_events", 0)
                fspec["warm_up"].setdefault("min_duration_ns", 0)

    logger.debug("%s: v1.0 migration applied", source)
    return spec


def migrate_and_write(spec_path: Path) -> dict[str, Any]:
    """Migrate a spec and write it back to disk.

    Returns the migrated spec dict.
    """
    spec = migrate_spec(spec_path)
    out = yaml.dump(spec, default_flow_style=False, sort_keys=False)
    spec_path.write_text(out, encoding="utf-8")
    logger.info("Wrote migrated spec to %s", spec_path)
    return spec
