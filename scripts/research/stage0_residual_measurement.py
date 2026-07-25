#!/usr/bin/env python3
"""Stage-0 residual measurement — local runner (pre-registration §10, §5).

Executes the protocol frozen in ``docs/research/stage0_residual_preregistration.md``
against a **local** disk event cache.  It never calls the Massive API and never
mutates a committed alpha spec: each arm runs from a temporary copy of the
pilot's YAML with a ``safety_exit_policy`` block injected, so measuring an alpha
cannot promote it as a side effect.

Two modes:

``--scout``
    The pre-approved next step (§10).  **Counting only** — episode counts, which
    cap binds, quote-freeze counts, and effective tail sample against the floor.
    Touches no outcome data (it reads timestamps, gate-transition causes and
    exit reasons), so it is Inv-2-safe, and it answers *"is this powerable at
    all?"* before any tail statistic exists.  If the cell is under-powered the
    study stops here and no CVaR number enters the record where it could later
    be quoted as evidence.

``--full``
    The Step-2 A/B counterfactual: the same event log replayed under
    ``gate_close_flat`` (arm F) and ``decouple_caps_only`` (arm H), decomposed
    into the two populations, bounded by the hindsight ceiling, and judged
    against the frozen bars by :mod:`feelies.research.stage0_residual`.

Both arms run under ``--inv12-stress`` (1.5× cost, 2× fill latency) because the
deferral tail is realized in the stressed exit — mid marks flatter the hold
exactly where it matters.

Usage
-----
::

    PYTHONHASHSEED=0 uv run python scripts/research/stage0_residual_measurement.py \\
        --alpha sig_moc_imbalance_v1 --symbol APP NVDA AMD \\
        --date 2026-03-02 --end-date 2026-04-30 --scout

    # only after the scout reports the cell is powered:
    PYTHONHASHSEED=0 uv run python scripts/research/stage0_residual_measurement.py \\
        --alpha sig_moc_imbalance_v1 --symbol APP NVDA AMD \\
        --date 2026-03-02 --end-date 2026-04-30 --full \\
        --out docs/research/artifacts/stage0_residual

Requires a populated ``~/.feelies/cache/{SYMBOL}/{YYYY-MM-DD}.jsonl.gz``
(``--cache-dir`` to override).  ``PYTHONHASHSEED=0`` is required for Inv-5
parity; the runner refuses to start without it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.core.events import (  # noqa: E402
    NBBOQuote,
    OrderRequest,
    SafetyStateChange,
)
from feelies.research.stage0_residual import (  # noqa: E402
    PILOT_CONFIGS,
    PRE_REGISTERED_CVAR_LEVEL,
    PRE_REGISTERED_MIN_TAIL_SAMPLE,
    PilotConfig,
    Stratum,
)

# Terminal exit reasons the deferral/backstop authors emit.
_DEFERRAL_CAPS: frozenset[str] = frozenset(
    {"MAX_HOLD_AFTER_SAFE_OFF", "HARD_EXIT_AGE", "SESSION_FLATTEN"}
)

# ``off_condition`` clauses that constitute a genuine latent-state ("weather")
# trigger rather than deterministic schedule expiry (pre-registration §5.4).
# Anything not listed here is classified EXPIRY, and an OFF whose cause cannot
# be determined aborts rather than defaulting into a stratum.
_WEATHER_MARKERS: tuple[str, ...] = (
    "realized_vol_30s_zscore",
    "spread_z_30d",
    "P(normal)",
)


# ─────────────────────────────────────────────────────────────────────
#   Arm materialization — never mutate a committed alpha spec
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class Arm:
    """One replay arm: a name and the temp alpha spec it runs."""

    name: str
    mode: str
    spec_path: Path


def _find_alpha_spec(alpha_id: str) -> Path:
    matches = sorted(_PROJECT_ROOT.glob(f"alphas/**/{alpha_id}.alpha.yaml"))
    if not matches:
        raise SystemExit(f"ERROR: no alpha spec found for {alpha_id!r} under alphas/")
    if len(matches) > 1:
        raise SystemExit(f"ERROR: ambiguous alpha spec for {alpha_id!r}: {matches}")
    return matches[0]


def _materialize_arms(pilot: PilotConfig, workdir: Path) -> tuple[Arm, Arm]:
    """Write the two arms' alpha specs into ``workdir``.

    Arm F pins ``gate_close_flat`` explicitly rather than omitting the block, so
    both arms differ in exactly one field and neither inherits a default that
    could drift.  The frozen ceilings come from :data:`PILOT_CONFIGS`, which is
    itself derived from the per-family legal envelope — there is no number here
    for the operator to tune.
    """
    source = _find_alpha_spec(pilot.alpha_id)
    raw: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))

    if "safety_exit_policy" in raw:
        raise SystemExit(
            f"ERROR: {source} already declares safety_exit_policy. The measurement "
            "injects it per arm; refusing to overwrite an authored policy."
        )

    arms: list[Arm] = []
    for name, mode in (
        ("F_gate_close_flat", "gate_close_flat"),
        ("H_decouple", "decouple_caps_only"),
    ):
        spec = dict(raw)
        policy: dict[str, Any] = {"mode": mode}
        if mode == "decouple_caps_only":
            policy["max_hold_after_safe_off"] = pilot.max_hold_after_safe_off
            policy["hard_exit_age_seconds"] = pilot.hard_exit_age_seconds
        spec["safety_exit_policy"] = policy
        path = workdir / f"{pilot.alpha_id}__{name}.alpha.yaml"
        path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
        arms.append(Arm(name=name, mode=mode, spec_path=path))

    return arms[0], arms[1]


def _materialize_config(arm: Arm, symbols: list[str], workdir: Path) -> Path:
    """Write a platform config for one arm, pointing at its temp alpha spec."""
    config = {
        "extends": str(_PROJECT_ROOT / "platform.yaml"),
        "symbols": symbols,
        "alpha_specs": [str(arm.spec_path)],
        "signal_min_edge_cost_ratio": 1.5,
        "parameter_overrides": {},
    }
    path = workdir / f"config__{arm.name}.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────
#   Arm execution
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ArmRun:
    """Captured output of one arm's replay."""

    arm: Arm
    safety_events: list[SafetyStateChange]
    exit_orders: list[OrderRequest]
    quotes: list[NBBOQuote]
    trade_records: list[Any]


def _run_arm(arm: Arm, args: argparse.Namespace, symbols: list[str], workdir: Path) -> ArmRun:
    """Replay one arm from the disk cache and capture what the analysis needs."""
    from feelies.harness.backtest_cli import disable_backtest_jsonl_emit_flags
    from feelies.harness.backtest_prep import prepare_backtest_event_log
    from feelies.harness.backtest_runner import (
        _load_backtest_config,
        _run_backtest_phases_2_7,
    )
    from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

    config_path = _materialize_config(arm, symbols, workdir)

    run_args = argparse.Namespace(
        symbol=symbols,
        date=args.date,
        end_date=args.end_date,
        config=str(config_path),
        cache_dir=args.cache_dir,
        stress_cost=1.0,
        inv12_stress=True,  # frozen: the CVaR estimate is invalid without it
        trace_signal_orders=False,
        strict_config=True,
        profile=None,
        edge_calibration=None,
    )
    disable_backtest_jsonl_emit_flags(run_args)

    config = _load_backtest_config(run_args)
    if config is None:
        raise SystemExit(f"ERROR: could not load config for arm {arm.name}")

    start_date = args.date
    end_date = args.end_date or start_date
    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            symbols,
            start_date,
            end_date,
            cache_dir=Path(args.cache_dir) if args.cache_dir else None,
            require_healthy_ingestion_manifests=config.require_healthy_disk_cache_manifests,
        )
    except CacheReplayError as exc:
        raise SystemExit(
            f"ERROR: disk cache replay failed for arm {arm.name}: {exc}\n"
            "  Populate ~/.feelies/cache/{SYMBOL}/{DATE}.jsonl.gz first."
        ) from exc

    prep = prepare_backtest_event_log(config, event_log)
    outcome = _run_backtest_phases_2_7(
        run_args,
        prep.event_log,
        ingest_result,
        list(day_meta),
        config,
        symbols,
        ", ".join(symbols),
        f"{start_date} to {end_date}",
        0.0,
        prep=prep,
    )
    if outcome.recorder is None:
        raise SystemExit(f"ERROR: arm {arm.name} produced no bus recorder")

    journal = outcome.orchestrator.trade_journal
    records = list(journal.query()) if journal is not None else []

    return ArmRun(
        arm=arm,
        safety_events=[e for e in outcome.recorder.of_type(SafetyStateChange) if not e.safe],
        exit_orders=[o for o in outcome.recorder.of_type(OrderRequest) if o.reason],
        # NBBOQuote is skipped by the BusRecorder for memory reasons, so the
        # oracle's mid path comes from the prepared event log — which is also
        # the object both arms provably share.
        quotes=[e for e in prep.event_log.replay() if isinstance(e, NBBOQuote)],
        trade_records=records,
    )


# ─────────────────────────────────────────────────────────────────────
#   Stratification
# ─────────────────────────────────────────────────────────────────────


def classify_stratum(event: SafetyStateChange) -> Stratum:
    """Classify one safe→OFF by its trigger cause (pre-registration §5.4).

    A clean gate transition whose consumed features include a weather predicate
    is WEATHER; a clean transition driven only by schedule predicates is EXPIRY.
    Fail-closed **error** paths are WEATHER: an error forces safe=OFF under
    uncertainty, which is not a benign scheduled wind-down.
    """
    if event.reason != "clean_transition":
        return Stratum.WEATHER
    consumed = " ".join(event.consumed_features)
    if any(marker in consumed for marker in _WEATHER_MARKERS):
        return Stratum.WEATHER
    return Stratum.EXPIRY


# ─────────────────────────────────────────────────────────────────────
#   Scout — counting only (Inv-2 safe)
# ─────────────────────────────────────────────────────────────────────


def run_scout(pilot: PilotConfig, run_h: ArmRun) -> dict[str, Any]:
    """Count the subpopulation without computing any outcome.

    Reads timestamps, OFF-trigger causes and exit reasons only. Deliberately
    computes no PnL: an under-powered tail number must not exist, because once
    it exists it can be quoted.
    """
    per_stratum: dict[str, dict[str, Any]] = {}
    by_stratum: Counter[Stratum] = Counter()
    caps: Counter[str] = Counter()

    # One episode per (strategy, symbol, first safe→OFF). Later OFFs inside the
    # same open episode do not re-anchor the clock (design §2.3), so only the
    # first counts.
    seen: set[tuple[str, str]] = set()
    episodes: list[tuple[SafetyStateChange, Stratum]] = []
    for event in sorted(run_h.safety_events, key=lambda e: (e.timestamp_ns, e.sequence)):
        key = (event.strategy_id, event.symbol)
        if key in seen:
            continue
        seen.add(key)
        stratum = classify_stratum(event)
        by_stratum[stratum] += 1
        episodes.append((event, stratum))

    for order in run_h.exit_orders:
        if order.reason in _DEFERRAL_CAPS or order.reason == "STOP_LOSS":
            caps[order.reason] += 1

    needed = math.ceil(PRE_REGISTERED_MIN_TAIL_SAMPLE / PRE_REGISTERED_CVAR_LEVEL)
    for stratum in (Stratum.WEATHER, Stratum.EXPIRY):
        n = by_stratum[stratum]
        tail = int(PRE_REGISTERED_CVAR_LEVEL * n)
        per_stratum[stratum.value] = {
            "subpopulation_size": n,
            "effective_tail_sample": tail,
            "min_tail_sample": PRE_REGISTERED_MIN_TAIL_SAMPLE,
            "powered": tail >= PRE_REGISTERED_MIN_TAIL_SAMPLE,
            "episodes_needed_for_power": needed,
            "shortfall_episodes": max(0, needed - n),
        }

    return {
        "alpha_id": pilot.alpha_id,
        "mode": "scout",
        "note": (
            "Counting only — no outcome data touched (Inv-2). No CVaR estimate is "
            "produced by this mode by design."
        ),
        "cvar_level": PRE_REGISTERED_CVAR_LEVEL,
        "total_safe_off_episodes": len(episodes),
        "per_stratum": per_stratum,
        "terminal_cap_counts": dict(sorted(caps.items())),
        "powered_overall": any(s["powered"] for s in per_stratum.values()),
    }


# ─────────────────────────────────────────────────────────────────────
#   CLI
# ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage-0 residual measurement (see docs/research/stage0_residual_preregistration.md)",
    )
    p.add_argument("--alpha", required=True, choices=sorted(PILOT_CONFIGS), help="Pilot alpha id")
    p.add_argument("--symbol", nargs="+", required=True, help="Symbols to replay")
    p.add_argument("--date", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end-date", default=None, help="End date YYYY-MM-DD (default: --date)")
    p.add_argument("--cache-dir", default=None, help="Disk cache dir (default ~/.feelies/cache)")
    p.add_argument("--out", default=None, help="Artifact output prefix (writes <prefix>_*.json)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scout", action="store_true", help="Counting only (pre-registration §10)")
    mode.add_argument("--full", action="store_true", help="Full A/B counterfactual (§5)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if os.environ.get("PYTHONHASHSEED") != "0":
        print(
            "ERROR: PYTHONHASHSEED=0 is required for Inv-5 replay parity.\n"
            "  Re-run as: PYTHONHASHSEED=0 uv run python "
            "scripts/research/stage0_residual_measurement.py ...",
            file=sys.stderr,
        )
        return 1

    pilot = PILOT_CONFIGS[args.alpha]
    symbols = list(args.symbol)

    print(f"\n  Stage-0 residual measurement — {pilot.alpha_id} ({pilot.family})")
    print(
        f"  frozen: max_hold={pilot.max_hold_after_safe_off}s "
        f"hard_exit_age={pilot.hard_exit_age_seconds}s "
        f"B2 bar={pilot.b2_bar_bps:.2f}bps  (pre-registration §3)"
    )
    print(f"  symbols: {', '.join(symbols)}  |  {args.date}..{args.end_date or args.date}")
    print("  arms run under --inv12-stress (1.5x cost, 2x latency)\n", flush=True)

    with tempfile.TemporaryDirectory(prefix="stage0_residual_") as tmp:
        workdir = Path(tmp)
        arm_f, arm_h = _materialize_arms(pilot, workdir)

        if args.scout:
            # The scout only needs arm H: it counts the subpopulation the
            # deferral would act on, and which cap terminates each hold.
            run_h = _run_arm(arm_h, args, symbols, workdir)
            report = run_scout(pilot, run_h)
        else:
            print(
                "ERROR: --full is not yet validated against real data.\n"
                "  The two-arm PnL reconciliation and the hindsight-oracle\n"
                "  extraction have never been exercised on a real cache, and a\n"
                "  silently-wrong extraction would produce a plausible verdict.\n"
                "  Run --scout first; if it reports the cell is powered, the\n"
                "  full extraction needs a validation pass on a short date range\n"
                "  (reconcile arm-F/arm-H divergence points and episode counts\n"
                "  against the trade journal) before any verdict is recorded.",
                file=sys.stderr,
            )
            return 2

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)

    if args.out:
        out_path = Path(f"{args.out}_{report['mode']}_{pilot.alpha_id}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n  wrote {out_path}", flush=True)

    if args.scout and not report["powered_overall"]:
        print(
            "\n  VERDICT: UNDERPOWERED — no stratum clears the pre-registered floor.\n"
            "  Per pre-registration §7.3 this is NOT a GO and NOT a NO-GO. Stage 1\n"
            "  stays blocked (Inv-3: 'not shown' is the default state). Widen the\n"
            "  universe or the date range; do not widen the CVaR level (§8.2).",
            flush=True,
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
