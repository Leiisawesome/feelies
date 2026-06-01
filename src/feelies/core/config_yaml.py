"""YAML loading with optional ``extends:`` inheritance for platform configs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from feelies.core.errors import ConfigurationError

_EXTENDS_KEY = "extends"
_MAX_EXTENDS_DEPTH = 16


def deep_merge_mapping(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *override* onto *base*.

    Nested mappings merge recursively.  Scalars and sequences in *override*
    replace the base value entirely.
    """
    merged: dict[str, Any] = dict(base)
    for key, override_val in override.items():
        if key == _EXTENDS_KEY:
            continue
        base_val = merged.get(key)
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            merged[key] = deep_merge_mapping(base_val, override_val)
        else:
            merged[key] = override_val
    return merged


def load_yaml_mapping(
    path: str | Path,
    *,
    _chain: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Load a YAML mapping, resolving optional ``extends:`` inheritance.

    The ``extends`` value is resolved relative to the containing file.
    Cycles and excessive inheritance depth raise :class:`ConfigurationError`.
    """
    config_path = Path(path).resolve()
    if config_path in _chain:
        chain = " -> ".join(str(p) for p in (*_chain, config_path))
        raise ConfigurationError(f"{config_path}: extends cycle detected ({chain})")
    if len(_chain) >= _MAX_EXTENDS_DEPTH:
        raise ConfigurationError(
            f"{config_path}: extends depth exceeds {_MAX_EXTENDS_DEPTH}",
        )

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as exc:
        raise ConfigurationError(f"Failed to read config {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigurationError(f"{config_path}: root must be a YAML mapping")

    extends = data.get(_EXTENDS_KEY)
    if extends is None:
        return data

    if not isinstance(extends, str) or not extends.strip():
        raise ConfigurationError(
            f"{config_path}: {_EXTENDS_KEY} must be a non-empty path string",
        )

    base_path = (config_path.parent / extends).resolve()
    if not base_path.is_file():
        raise ConfigurationError(
            f"{config_path}: {_EXTENDS_KEY} target not found: {base_path}",
        )

    base_data = load_yaml_mapping(base_path, _chain=(*_chain, config_path))
    override = {k: v for k, v in data.items() if k != _EXTENDS_KEY}
    return deep_merge_mapping(base_data, override)


__all__ = ["deep_merge_mapping", "load_yaml_mapping"]
