"""Category 1 — metadata and alpha definition."""

from __future__ import annotations

from typing import Any

from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.models import HealthCheckResult, HealthStatus


def _meta_has(meta: dict[str, Any], key: str) -> bool:
    if meta.get(key) not in (None, "", [], {}):
        return True
    if key == "prediction_horizon" and meta.get("target_horizon") not in (None, "", [], {}):
        return True
    return False


def run_definition_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    meta = dict(ctx.metadata)

    required = cfg.metadata_required_fields
    missing_required = [k for k in required if not _meta_has(meta, k)]
    optional_hint_fields = (
        "data_source",
        "entry_rule",
        "exit_rule",
        "run_timestamp_ns",
        "git_commit_hash",
        "config_snapshot",
        "feature_definitions",
    )
    missing_optional = [k for k in optional_hint_fields if not meta.get(k)]

    if missing_required:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="required_metadata_present",
                status=HealthStatus.FAIL,
                metrics={"missing_required": missing_required, "present_keys": sorted(meta.keys())},
                thresholds={"required": list(required)},
                message=f"Missing required metadata keys: {missing_required}",
                suggested_action="Record alpha_name, universe, timeframe, prediction_horizon, "
                "execution_assumption, and cost_assumption in metadata.json.",
                severity=3,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="required_metadata_present",
                status=HealthStatus.PASS,
                metrics={"present_required": list(required)},
                thresholds={"required": list(required)},
                message="All configured required metadata keys are present.",
                suggested_action="",
                severity=0,
            )
        )

    if missing_optional:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="optional_metadata_completeness",
                status=HealthStatus.WARN,
                metrics={"missing_optional": missing_optional},
                thresholds={},
                message="Non-critical provenance fields are missing — audit trail is weaker.",
                suggested_action="Add data_source, entry/exit documentation, run_timestamp_ns, "
                "git_commit_hash, and a frozen config snapshot.",
                severity=1,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="optional_metadata_completeness",
                status=HealthStatus.PASS,
                metrics={},
                thresholds={},
                message="Optional provenance fields present.",
                suggested_action="",
                severity=0,
            )
        )

    fnames = list(ctx.feature_names) or _feature_names_from_meta(meta)
    if not fnames:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="feature_manifest_present",
                status=HealthStatus.WARN,
                metrics={"feature_count": 0},
                thresholds={},
                message="No explicit feature list recorded — predictive diagnostics may be incomplete.",
                suggested_action="Populate metadata.feature_names or ctx.feature_names.",
                severity=1,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="feature_manifest_present",
                status=HealthStatus.PASS,
                metrics={"feature_count": len(fnames)},
                thresholds={},
                message="Feature manifest present.",
                suggested_action="",
                severity=0,
            )
        )

    load_warn = ctx.extra.get("artifact_load_warnings")
    if isinstance(load_warn, list) and load_warn:
        results.append(
            HealthCheckResult(
                category="metadata_definition",
                check_name="artifact_load_warnings",
                status=HealthStatus.WARN,
                metrics={"warnings": [str(x) for x in load_warn]},
                thresholds={},
                message="Some tabular artefacts could not be read (e.g. Parquet without pyarrow).",
                suggested_action="Install pyarrow: pip install 'feelies[health]' or export CSV instead.",
                severity=2,
            )
        )

    return results


def _feature_names_from_meta(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("feature_names") or meta.get("features") or meta.get("feature_list")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []
