"""Alpha spec discovery — scan a directory for .alpha.yaml files.

Provides the "drop spot" convention: place ``.alpha.yaml`` files in
a directory (default ``alphas/``), and the system auto-discovers,
loads, validates, and registers them at boot time.

Error policy: one bad spec does not block others.  Errors are
collected and logged.  If no alphas load successfully, a RuntimeError
is raised to prevent booting an empty system.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from feelies.alpha.loader import AlphaLoadError, AlphaLoader
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError

logger = logging.getLogger(__name__)


def discover_alpha_specs(spec_dir: Path) -> list[Path]:
    """Find all ``.alpha.yaml`` files in a directory.

    Supports both flat layout (``alphas/*.alpha.yaml``) and nested
    per-alpha directories (``alphas/{alpha_id}/{alpha_id}.alpha.yaml``).

    Returns paths sorted alphabetically for deterministic load order.
    """
    if not spec_dir.is_dir():
        raise FileNotFoundError(f"Alpha spec directory not found: {spec_dir}")

    flat = set(spec_dir.glob("*.alpha.yaml"))
    nested = set(spec_dir.glob("*/*.alpha.yaml"))
    specs = sorted(flat | nested)
    return specs


def load_and_register(
    spec_dir: Path,
    registry: AlphaRegistry,
    loader: AlphaLoader,
    parameter_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Discover, load, and register all alpha specs from a directory.

    Args:
        spec_dir: Directory containing ``.alpha.yaml`` files.
        registry: Target registry for loaded modules.
        loader: AlphaLoader instance (pre-configured with regime engine etc.).
        parameter_overrides: Per-alpha parameter overrides keyed by alpha_id.

    Returns:
        List of successfully registered alpha_ids.

    Raises:
        RuntimeError: If no alphas loaded successfully.
    """
    overrides = parameter_overrides or {}
    specs = discover_alpha_specs(spec_dir)

    if not specs:
        raise RuntimeError(f"No .alpha.yaml files found in {spec_dir}")

    loaded_ids: list[str] = []
    errors: dict[str, str] = {}

    for spec_path in specs:
        try:
            module = loader.load(
                spec_path,
                param_overrides=overrides.get(_guess_alpha_id(spec_path)),
            )
            registry.register(module)
            alpha_id = module.manifest.alpha_id
            loaded_ids.append(alpha_id)
            logger.info("Registered alpha '%s' from %s", alpha_id, spec_path)
        except (AlphaLoadError, AlphaRegistryError) as exc:
            errors[str(spec_path)] = str(exc)
            logger.error("Failed to load %s: %s", spec_path, exc)

    if errors:
        for path, err in errors.items():
            logger.warning("Alpha load failure: %s — %s", path, err)

    if not loaded_ids:
        raise RuntimeError(
            f"No alphas loaded successfully from {spec_dir}. "
            f"Errors: {errors}"
        )

    cross_errors = registry.validate_all()
    if cross_errors:
        for alpha_id, errs in cross_errors.items():
            logger.warning(
                "Cross-alpha validation issue for '%s': %s",
                alpha_id,
                "; ".join(errs),
            )

    logger.info(
        "Alpha discovery complete: %d loaded, %d failed",
        len(loaded_ids),
        len(errors),
    )
    return loaded_ids


def _guess_alpha_id(spec_path: Path) -> str:
    """Guess alpha_id from filename for parameter override lookup.

    Strips the ``.alpha.yaml`` suffix: ``spread_mean_rev.alpha.yaml``
    becomes ``spread_mean_rev``.  If the YAML's actual ``alpha_id``
    differs, the override won't match — the caller can also use the
    actual alpha_id in the overrides dict.
    """
    name = spec_path.name
    if name.endswith(".alpha.yaml"):
        return name[: -len(".alpha.yaml")]
    return spec_path.stem
