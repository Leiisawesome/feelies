"""Transparent scoring and recommendation logic."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from feelies.health.config import HealthConfig
from feelies.health.models import AlphaDecision, AlphaHealthReport, HealthCheckResult, HealthStatus


def _status_rank(s: HealthStatus) -> int:
    return {HealthStatus.FAIL: 3, HealthStatus.WARN: 2, HealthStatus.PASS: 1, HealthStatus.NOT_APPLICABLE: 0}[s]


def _worse(a: HealthStatus, b: HealthStatus) -> HealthStatus:
    return a if _status_rank(a) >= _status_rank(b) else b


def _status_to_score(s: HealthStatus) -> float | None:
    if s == HealthStatus.PASS:
        return 1.0
    if s == HealthStatus.WARN:
        return 0.5
    if s == HealthStatus.FAIL:
        return 0.0
    return None


def aggregate_category_status(results: tuple[HealthCheckResult, ...]) -> dict[str, HealthStatus]:
    buckets: dict[str, list[HealthCheckResult]] = defaultdict(list)
    for r in results:
        buckets[r.category].append(r)
    out: dict[str, HealthStatus] = {}
    for cat, items in buckets.items():
        st = HealthStatus.PASS
        for it in items:
            if it.status == HealthStatus.NOT_APPLICABLE:
                continue
            st = _worse(st, it.status)
        if all(x.status == HealthStatus.NOT_APPLICABLE for x in items):
            st = HealthStatus.NOT_APPLICABLE
        out[cat] = st
    return out


def compute_weighted_score(
    category_status: dict[str, HealthStatus], weights: dict[str, float]
) -> float:
    num = 0.0
    den = 0.0
    for cat, w in weights.items():
        st = category_status.get(cat, HealthStatus.NOT_APPLICABLE)
        sc = _status_to_score(st)
        if sc is None:
            continue
        num += w * sc
        den += w
    if den <= 0.0:
        return 0.0
    return num / den


def overall_status_from_categories(category_status: dict[str, HealthStatus]) -> HealthStatus:
    st = HealthStatus.PASS
    for v in category_status.values():
        if v == HealthStatus.NOT_APPLICABLE:
            continue
        st = _worse(st, v)
    return st


def decide(
    results: tuple[HealthCheckResult, ...],
    category_status: dict[str, HealthStatus],
    score: float,
    cfg: HealthConfig,
) -> AlphaDecision:
    """Explicit rules layered on top of aggregate score."""

    by_name = {r.check_name: r for r in results}

    def _failed(name: str) -> bool:
        r = by_name.get(name)
        return r is not None and r.status == HealthStatus.FAIL

    kill_reasons: list[str] = []

    if _failed("target_leakage_feature_names"):
        kill_reasons.append("label-like features detected")

    if _failed("feature_decision_ordering"):
        kill_reasons.append("timestamp ordering violations")

    if _failed("signal_timestamp_alignment"):
        kill_reasons.append("missing causal timestamps")

    if _failed("regime_label_safety"):
        kill_reasons.append("unsafe regime labels")

    pl = by_name.get("primary_lens_economics")
    if pl is not None and pl.status == HealthStatus.FAIL:
        mid_flag = bool(pl.metrics.get("mid_only_execution"))
        raw_net = pl.metrics.get("net_pnl")
        net: float | None
        if isinstance(raw_net, (int, float)) and not isinstance(raw_net, bool):
            net = float(raw_net)
        elif isinstance(raw_net, str):
            try:
                net = float(raw_net)
            except ValueError:
                net = None
        else:
            net = None
        if mid_flag and (net is None or net >= 0.0):
            pass
        else:
            kill_reasons.append("execution economics failed under realistic lens")

    if _failed("placebo_comparison"):
        kill_reasons.append("placebo matches alpha")

    if _failed("participation_rate"):
        kill_reasons.append("unrealistic participation")

    if _failed("correlation_and_marginal_sharpe"):
        kill_reasons.append("portfolio redundancy")

    if category_status.get("data_integrity_causality") == HealthStatus.FAIL:
        kill_reasons.append("causality category failed")

    if kill_reasons:
        return AlphaDecision.KILL

    # SCALE requires essentially everything green.
    major = (
        "metadata_definition",
        "data_integrity_causality",
        "raw_predictive_power",
        "cost_execution_survival",
        "risk_drawdown",
    )
    if (
        score >= 0.9
        and all(category_status.get(c) == HealthStatus.PASS for c in major)
        and category_status.get("portfolio_fit") in (HealthStatus.PASS, HealthStatus.NOT_APPLICABLE)
    ):
        return AlphaDecision.SCALE_CANDIDATE

    if (
        score >= 0.75
        and category_status.get("data_integrity_causality") == HealthStatus.PASS
        and category_status.get("cost_execution_survival") == HealthStatus.PASS
    ):
        return AlphaDecision.DEPLOY_SMALL

    if (
        score >= 0.55
        and category_status.get("data_integrity_causality") != HealthStatus.FAIL
        and category_status.get("cost_execution_survival") != HealthStatus.FAIL
    ):
        return AlphaDecision.PAPER_TRADE

    if score >= 0.35:
        return AlphaDecision.RESEARCH_MORE

    return AlphaDecision.KILL


def build_report(
    *,
    alpha_name: str,
    run_id: str,
    created_at_ns: int,
    repo_commit: str | None,
    results: tuple[HealthCheckResult, ...],
    cfg: HealthConfig,
    artifacts: dict[str, object],
) -> AlphaHealthReport:
    cat_status = aggregate_category_status(results)
    score = compute_weighted_score(cat_status, cfg.category_weights)
    overall = overall_status_from_categories(cat_status)
    decision = decide(results, cat_status, score, cfg)

    if cfg.config_missing_warned:
        warn_extra = "Health YAML missing — defaults used."
    else:
        warn_extra = ""

    summary = {
        "category_status": {k: v.value for k, v in cat_status.items()},
        "weighted_score": score,
        "counts": _count_statuses(results),
        "config_note": warn_extra,
    }

    created = datetime.fromtimestamp(created_at_ns / 1e9, tz=timezone.utc) if created_at_ns > 0 else datetime.fromtimestamp(
        0, tz=timezone.utc
    )

    return AlphaHealthReport(
        alpha_name=alpha_name,
        run_id=run_id,
        created_at=created,
        repo_commit=repo_commit,
        overall_status=overall,
        decision=decision,
        score=score,
        results=results,
        summary=summary,
        artifacts=artifacts,
    )


def _count_statuses(results: tuple[HealthCheckResult, ...]) -> dict[str, int]:
    out: dict[str, int] = {s.value: 0 for s in HealthStatus}
    for r in results:
        out[r.status.value] += 1
    return out


__all__ = [
    "aggregate_category_status",
    "build_report",
    "compute_weighted_score",
    "decide",
    "overall_status_from_categories",
]
