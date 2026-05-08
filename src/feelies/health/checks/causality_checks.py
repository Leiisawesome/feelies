"""Category 2 — data integrity and causal ordering."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from feelies.health.column_utils import row_float, row_int, row_str
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import iteration_pairs
from feelies.health.models import HealthCheckResult, HealthStatus


_LEAKAGE_PATTERN = re.compile(
    r"(^|_)(future_return|forward_return|target|label|next_|forward_|fwd_|y_true)",
    re.IGNORECASE,
)


def _all_feature_names(ctx: HealthCheckContext) -> list[str]:
    names = list(ctx.feature_names)
    meta = ctx.metadata
    raw = meta.get("feature_names") or meta.get("features") or meta.get("feature_list")
    if isinstance(raw, list):
        names.extend(str(x) for x in raw)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def run_causality_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    del cfg  # thresholds reserved for future missing-rate gates
    results: list[HealthCheckResult] = []

    leaked = [n for n in _all_feature_names(ctx) if _LEAKAGE_PATTERN.search(n)]
    if leaked:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="target_leakage_feature_names",
                status=HealthStatus.FAIL,
                metrics={"suspicious_features": leaked},
                thresholds={"pattern": _LEAKAGE_PATTERN.pattern},
                message="Feature manifest contains names that strongly resemble labels or future returns.",
                suggested_action="Remove leaked columns from features; ensure labels are never in "
                "the training/feature set passed to the signal engine.",
                severity=3,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="target_leakage_feature_names",
                status=HealthStatus.PASS,
                metrics={"suspicious_features": []},
                thresholds={},
                message="No obvious label-like feature names detected.",
                suggested_action="",
                severity=0,
            )
        )

    sig_rows = list(ctx.signals)
    if not sig_rows:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="signal_timestamp_alignment",
                status=HealthStatus.FAIL,
                metrics={"signals_rows": 0},
                thresholds={},
                message="No signal rows available — causal ordering cannot be validated.",
                suggested_action="Export signals.csv with timestamps for health checks.",
                severity=3,
            )
        )
        return results

    ts_key_present = any(row_str(r, "timestamp", "ts", "event_time") for r in sig_rows[:5])
    if not ts_key_present:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="decision_timestamp_present",
                status=HealthStatus.FAIL,
                metrics={},
                thresholds={},
                message="Signals lack a recognisable timestamp column.",
                suggested_action="Add timestamp (ns or epoch) per signal row.",
                severity=3,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="decision_timestamp_present",
                status=HealthStatus.PASS,
                metrics={},
                thresholds={},
                message="Signal timestamps detected.",
                suggested_action="",
                severity=0,
            )
        )

    feat_ts_missing = 0
    decision_ts_missing = 0
    ordering_violations = 0
    checked = 0
    for row in sig_rows:
        dec = row_int(row, "decision_timestamp", "decision_ts_ns", "decision_time_ns")
        fts = row_int(row, "feature_timestamp", "feature_ts_ns", "feature_time_ns")
        tts = row_int(row, "target_timestamp", "exit_timestamp", "horizon_end_ns")
        base_ts = row_int(row, "timestamp", "ts", "event_time_ns")
        if dec is None and base_ts is not None:
            dec = base_ts
        if dec is None:
            decision_ts_missing += 1
        if fts is None:
            feat_ts_missing += 1
        if dec is not None and fts is not None and fts > dec:
            ordering_violations += 1
        if dec is not None and tts is not None and tts <= dec:
            ordering_violations += 1
        if dec is not None or fts is not None or tts is not None:
            checked += 1

    if checked == 0:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="feature_decision_ordering",
                status=HealthStatus.WARN,
                metrics={},
                thresholds={},
                message="Signal rows exist but timestamp columns are not numeric — causal checks skipped.",
                suggested_action="Use integer nanosecond timestamps for decision/feature/target times.",
                severity=2,
            )
        )
    elif ordering_violations > 0:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="feature_decision_ordering",
                status=HealthStatus.FAIL,
                metrics={
                    "ordering_violations": ordering_violations,
                    "rows_considered": checked,
                },
                thresholds={},
                message="Detected rows where feature time follows decision time or target time "
                "does not follow decision time.",
                suggested_action="Fix pipeline ordering; reject rows that violate t_feat <= t_dec < t_tgt.",
                severity=3,
            )
        )
    else:
        status = HealthStatus.PASS
        msg = "Observed timestamps respect feature <= decision < target where provided."
        if feat_ts_missing > 0 or decision_ts_missing > 0:
            status = HealthStatus.WARN
            msg += " Some rows omit feature or decision timestamps — coverage incomplete."
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="feature_decision_ordering",
                status=status,
                metrics={
                    "rows_considered": checked,
                    "feature_ts_missing": feat_ts_missing,
                    "decision_ts_missing": decision_ts_missing,
                },
                thresholds={},
                message=msg,
                suggested_action="Provide feature_timestamp on every row when claiming causal hygiene.",
                severity=1 if status == HealthStatus.WARN else 0,
            )
        )

    ts_pairs = iteration_pairs(sig_rows, "timestamp")
    if not ts_pairs:
        ts_pairs = iteration_pairs(sig_rows, "ts")
    dup_ts = 0
    if ts_pairs:
        ctr = Counter(t for t, _ in ts_pairs)
        dup_ts = sum(1 for c in ctr.values() if c > 1)
    has_sequence = any(row_get_sequence(r) is not None for r in sig_rows)
    if dup_ts > 0 and not has_sequence:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="duplicate_event_timestamps",
                status=HealthStatus.WARN,
                metrics={"duplicate_timestamp_groups": dup_ts},
                thresholds={},
                message="Duplicate timestamps without sequence numbers — event ordering is ambiguous.",
                suggested_action="Add monotonic sequence or deduplicate event keys.",
                severity=2,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="duplicate_event_timestamps",
                status=HealthStatus.PASS,
                metrics={"duplicate_timestamp_groups": dup_ts},
                thresholds={},
                message="No duplicate timestamp collisions detected (or sequence column present).",
                suggested_action="",
                severity=0,
            )
        )

    missing_rate = sum(1 for r in sig_rows if row_float(r, "signal", "alpha_signal", "score") is None)
    mr = missing_rate / max(1, len(sig_rows))
    status = HealthStatus.PASS
    if mr > 0.05:
        status = HealthStatus.WARN
    if mr > 0.20:
        status = HealthStatus.FAIL
    results.append(
        HealthCheckResult(
            category="data_integrity_causality",
            check_name="signal_missing_rate",
            status=status,
            metrics={"missing_signal_fraction": mr},
            thresholds={"warn": 0.05, "fail": 0.20},
            message=f"Fraction of rows without numeric signal: {mr:.3f}",
            suggested_action="Investigate sparse signalling — may indicate warm-up gaps or bugs.",
            severity=2 if status == HealthStatus.FAIL else 1 if status == HealthStatus.WARN else 0,
        )
    )

    regime_flag = str(ctx.metadata.get("regime_labels_use_future_data") or "").lower() in (
        "1",
        "true",
        "yes",
    )
    if regime_flag:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="regime_label_safety",
                status=HealthStatus.FAIL,
                metrics={"unsafe_future_regimes_declared": True},
                thresholds={},
                message="Metadata declares regime labels computed with future data — unsafe.",
                suggested_action="Use only causal regime proxies or shift labels.",
                severity=3,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="data_integrity_causality",
                check_name="regime_label_safety",
                status=HealthStatus.PASS,
                metrics={"unsafe_future_regimes_declared": False},
                thresholds={},
                message="No explicit future-regime flag set.",
                suggested_action="",
                severity=0,
            )
        )

    return results


def row_get_sequence(row: Mapping[str, Any]) -> int | None:
    return row_int(row, "sequence", "seq", "event_sequence")
