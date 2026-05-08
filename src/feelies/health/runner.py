"""Public API entry-points for alpha health checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from feelies.health.artifacts import load_run_directory
from feelies.health.checks import run_all_health_checks
from feelies.health.config import HealthConfig, load_health_config
from feelies.health.context import HealthCheckContext
from feelies.health.models import AlphaHealthReport
from feelies.health.reporting import write_health_reports
from feelies.health.scoring import build_report


def run_alpha_health_check(
    *,
    alpha_name: str | None = None,
    backtest_result: Any | None = None,
    context: HealthCheckContext | None = None,
    config: HealthConfig | None = None,
    config_path: Path | None = None,
    artifacts: Mapping[str, Any] | None = None,
) -> AlphaHealthReport:
    """Run all checks and produce an :class:`AlphaHealthReport`.

    Supply either a pre-built :class:`HealthCheckContext` **or** a duck-typed
    ``backtest_result`` exposing ``health_context`` / ``to_health_context`` /
    ``metadata`` (minimal adapter hook for future integration).
    """

    cfg = config or load_health_config(config_path)

    if context is None:
        if backtest_result is None:
            if alpha_name is None:
                raise ValueError("alpha_name is required when neither context nor backtest_result is provided")
            ctx = HealthCheckContext(
                alpha_name=alpha_name,
                run_id="adhoc",
                created_at_ns=0,
                config=cfg,
                metadata={"alpha_name": alpha_name},
            )
        else:
            ctx = _coerce_context(alpha_name or getattr(backtest_result, "alpha_name", None) or "alpha", backtest_result, cfg)
    else:
        ctx = replace(context, config=cfg)
        if alpha_name and alpha_name != ctx.alpha_name:
            ctx = replace(ctx, alpha_name=alpha_name)

    results = tuple(run_all_health_checks(ctx, cfg))
    art = dict(artifacts or {})
    art.setdefault("config_loaded_from", cfg.config_loaded_from)
    art.setdefault("artifacts_path", str(ctx.artifacts_path) if ctx.artifacts_path else None)

    return build_report(
        alpha_name=ctx.alpha_name,
        run_id=ctx.run_id,
        created_at_ns=ctx.created_at_ns,
        repo_commit=ctx.repo_commit,
        results=results,
        cfg=cfg,
        artifacts=art,
    )


def _coerce_context(alpha_name: str | None, backtest_result: Any, cfg: HealthConfig) -> HealthCheckContext:
    if hasattr(backtest_result, "to_health_context"):
        ctx = backtest_result.to_health_context()
        if not isinstance(ctx, HealthCheckContext):
            raise TypeError("to_health_context() must return HealthCheckContext")
        return replace(ctx, config=cfg)
    if hasattr(backtest_result, "health_context"):
        ctx = getattr(backtest_result, "health_context")
        if isinstance(ctx, HealthCheckContext):
            return replace(ctx, config=cfg)
    if isinstance(backtest_result, HealthCheckContext):
        return replace(backtest_result, config=cfg)
    if isinstance(backtest_result, Mapping):
        meta = dict(backtest_result.get("metadata", {}))
        eff = backtest_result.get("alpha_name", alpha_name)
        if eff is None:
            eff = "alpha"
        return HealthCheckContext(
            alpha_name=str(eff),
            run_id=str(backtest_result.get("run_id", "unknown")),
            created_at_ns=int(backtest_result.get("created_at_ns", 0)),
            config=cfg,
            metadata=meta,
            feature_names=tuple(backtest_result.get("feature_names", ())),
            signals=tuple(backtest_result.get("signals", ())),
            trades=tuple(backtest_result.get("trades", ())),
            pnl_series=tuple(backtest_result.get("pnl_series", ())),
            orders=tuple(backtest_result.get("orders", ())),
            fills=tuple(backtest_result.get("fills", ())),
            regime_rows=tuple(backtest_result.get("regime_rows", ())),
            execution_variants=dict(backtest_result.get("execution_variants", {})),
            robustness_summary=dict(backtest_result.get("robustness_summary", {})),
            existing_strategy_equity=dict(backtest_result.get("existing_strategy_equity", {})),
            artifacts_path=Path(backtest_result["artifacts_path"])
            if backtest_result.get("artifacts_path")
            else None,
            repo_commit=backtest_result.get("repo_commit"),
            extra=dict(backtest_result.get("extra", {})),
        )
    raise TypeError(
        "backtest_result must be HealthCheckContext, mapping, or provide to_health_context()"
    )


def run_alpha_health_check_from_directory(
    run_dir: Path,
    *,
    alpha_name: str | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
    config: HealthConfig | None = None,
) -> AlphaHealthReport:
    """Load artefacts from ``run_dir`` and execute checks."""

    cfg = config or load_health_config(config_path)
    ctx = load_run_directory(run_dir, alpha_name=alpha_name, run_id=run_id)
    ctx = replace(ctx, config=cfg)
    return run_alpha_health_check(context=ctx, config=cfg)


def run_and_write_reports(
    *,
    out_dir: Path,
    run_dir: Path | None = None,
    alpha_name: str | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
    config: HealthConfig | None = None,
    context: HealthCheckContext | None = None,
    backtest_result: Any | None = None,
    write_json: bool = True,
    write_markdown: bool = True,
    write_csv: bool = True,
) -> tuple[AlphaHealthReport, dict[str, Path]]:
    """Convenience: run checks and persist reports."""

    if run_dir is not None:
        report = run_alpha_health_check_from_directory(
            run_dir,
            alpha_name=alpha_name,
            run_id=run_id,
            config_path=config_path,
            config=config,
        )
    elif context is not None:
        report = run_alpha_health_check(
            context=context,
            config=config,
            config_path=config_path,
            alpha_name=alpha_name or context.alpha_name,
        )
    elif backtest_result is not None:
        report = run_alpha_health_check(
            alpha_name=alpha_name or "alpha",
            backtest_result=backtest_result,
            config=config,
            config_path=config_path,
        )
    else:
        report = run_alpha_health_check(
            alpha_name=alpha_name or "alpha",
            config=config,
            config_path=config_path,
        )
    paths = write_health_reports(
        report,
        out_dir,
        write_json=write_json,
        write_markdown=write_markdown,
        write_csv=write_csv,
    )
    return report, paths


__all__ = [
    "run_alpha_health_check",
    "run_alpha_health_check_from_directory",
    "run_and_write_reports",
]
