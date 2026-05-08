"""``feelies health-check`` subcommand — alpha validation reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from feelies.health import run_and_write_reports

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DATA_ERROR = 2
EXIT_VALIDATION_FAILED = 3


def register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--alpha",
        help="Override alpha name (defaults to metadata.json or directory name).",
    )
    parser.add_argument(
        "--backtest-output",
        type=Path,
        required=True,
        help="Directory with metadata.json / optional CSV artefacts.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to health YAML (defaults to embedded conservative defaults).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Directory for reports (default: <backtest-output>/health).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both", "all"],
        default="both",
        help="json|markdown|both (default) — 'all' also writes CSV summary.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Non-zero exit if decision is KILL or any check fails.",
    )
    parser.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    run_dir: Path = args.backtest_output
    if not run_dir.is_dir():
        print(f"error: backtest output is not a directory: {run_dir}", flush=True)
        return EXIT_USER_ERROR

    out_dir: Path = args.out_dir or (run_dir / "health")
    fmt = str(args.format)
    write_json = fmt in {"json", "both", "all"}
    write_md = fmt in {"markdown", "both", "all"}
    write_csv = fmt == "all"

    try:
        report, paths = run_and_write_reports(
            out_dir=out_dir,
            run_dir=run_dir,
            alpha_name=args.alpha,
            config_path=args.config,
            write_json=write_json,
            write_markdown=write_md,
            write_csv=write_csv,
        )
    except OSError as exc:
        print(f"error: could not write reports: {exc}", flush=True)
        return EXIT_DATA_ERROR
    except Exception as exc:  # pragma: no cover - defensive CLI surface
        print(f"error: health check failed: {exc}", flush=True)
        return EXIT_DATA_ERROR

    counts = report.summary.get("counts", {}) if isinstance(report.summary, dict) else {}
    print("alpha health summary", flush=True)
    print(f"  alpha:   {report.alpha_name}", flush=True)
    print(f"  score:   {report.score:.4f}", flush=True)
    print(f"  decision:{report.decision.value}", flush=True)
    print(
        f"  checks:  PASS={counts.get('PASS', 0)} WARN={counts.get('WARN', 0)} "
        f"FAIL={counts.get('FAIL', 0)} N/A={counts.get('NOT_APPLICABLE', 0)}",
        flush=True,
    )
    for label, path in paths.items():
        print(f"  {label}: {path}", flush=True)

    if args.strict and (report.decision.value == "KILL" or counts.get("FAIL", 0) > 0):
        return EXIT_VALIDATION_FAILED
    return EXIT_OK


__all__ = ["register"]
