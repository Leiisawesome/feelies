#!/usr/bin/env python3
"""Real-day P-95 attribution report (P-99a).

Descriptive, one day. Reads the local disk cache only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import Enum
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Alert,
    GateDecision,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    PositionClosed,
    RiskVerdict,
    Signal,
)
from feelies.core.platform_config import PlatformConfig
from feelies.forensics.exit_attribution import (
    ArmEvents,
    AttributionError,
    attribute,
)
from feelies.harness.backtest_prep import prepare_backtest_event_log
from feelies.harness.backtest_runner import (
    BusRecorder,
    DaySource,
    _attach_day_source_provenance,
    _enforce_ingest_event_mix,
    _run_backtest_phases_2_7,
)
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache
from feelies.storage.memory_event_log import InMemoryEventLog

_SYMBOL = "APP"
_DAY = "2026-03-26"
_ENGINE_CONFIG = "configs/bt_position_arbitrary_not_calibrated.yaml"
_LEGACY_CONFIG = "configs/bt_position_legacy_arm.yaml"
_STEM = "P-99a_attribution_APP_2026-03-26"
_DEFAULT_OUT_DIR = "docs/architecture/target/out/exec"
_HEADER = "Descriptive. 1 day. APP 2026-03-26."
_DISCLAIMER = "not evidence of edge, evaluation.md §1"
_RECORDED = (
    Signal,
    OrderRequest,
    OrderAck,
    RiskVerdict,
    PositionClosed,
    GateDecision,
    Alert,
)


def exit_mix(closed: Sequence[PositionClosed]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in closed:
        counts[item.exit_reason] = counts.get(item.exit_reason, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def refusal_counts(alerts: Sequence[Alert]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for alert in alerts:
        if alert.alert_name != "position_entry_refused":
            continue
        reason = alert.context["refusal_reason"]
        if not isinstance(reason, str):
            raise TypeError(f"refusal_reason must be str, got {type(reason).__name__}")
        counts[reason] = counts.get(reason, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def suppression_counts(
    decisions: Sequence[GateDecision],
) -> tuple[int, dict[str, int]]:
    suppressed = 0
    counts: dict[str, int] = {}
    for decision in decisions:
        if decision.outcome != "suppressed":
            continue
        suppressed += 1
        for name in decision.suppressions:
            counts[name] = counts.get(name, 0) + 1
    return suppressed, {key: counts[key] for key in sorted(counts)}


def _plain(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.name
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    raise TypeError(f"unsupported report value {type(value).__name__}")


def _apply_rail_env(config: PlatformConfig) -> PlatformConfig:
    dwell = os.environ.get("FEELIES_RAIL_DWELL_NS", "").strip() or "0"
    slip = os.environ.get("FEELIES_RAIL_SLIPPAGE_TICKS", "").strip() or "0"
    return dataclasses.replace(
        config,
        position_rail_dwell_ns=int(dwell),
        position_rail_slippage_ticks=int(slip),
    )


def _backtest_args() -> argparse.Namespace:
    return argparse.Namespace(
        trace_signal_orders=False,
        emit_fills_jsonl=False,
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
        emit_cross_sectional_jsonl=False,
        emit_sized_intents_jsonl=False,
        emit_hazard_exits_jsonl=False,
    )


def _factory(recorder: BusRecorder):
    def factory(
        config: PlatformConfig,
        event_log: InMemoryEventLog,
        **kwargs: object,
    ):
        orchestrator, resolved = build_platform(
            config,
            event_log=event_log,
            **kwargs,  # type: ignore[arg-type]
        )
        for event_type in _RECORDED:
            orchestrator._bus.subscribe(event_type, recorder)
        return orchestrator, resolved

    return factory


class _Arm:
    def __init__(
        self,
        events: ArmEvents,
        alerts: tuple[Alert, ...],
        decisions: tuple[GateDecision, ...],
    ) -> None:
        self.events = events
        self.alerts = alerts
        self.decisions = decisions


def _run_arm(
    config_path: str,
    source: InMemoryEventLog,
    ingest: object,
    day_sources: tuple[DaySource, ...],
) -> _Arm | int:
    config = PlatformConfig.from_yaml(config_path)
    symbols = sorted(config.symbols)
    log = InMemoryEventLog()
    log.append_batch(list(source.replay()))
    prep = prepare_backtest_event_log(config, log)
    rc = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="P-99a attribution",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        return rc
    config = _attach_day_source_provenance(config, symbols, day_sources)
    config = _apply_rail_env(config)
    quotes = tuple(ev for ev in prep.event_log.replay() if isinstance(ev, NBBOQuote))
    recorder = BusRecorder()
    outcome = _run_backtest_phases_2_7(
        _backtest_args(),
        log,
        ingest,  # type: ignore[arg-type]
        day_sources,
        config,
        symbols,
        _SYMBOL,
        _DAY,
        time.monotonic(),
        platform_factory=_factory(recorder),
        prep=prep,
    )
    if outcome.exit_code != 0:
        print(f"backtest failed: exit {outcome.exit_code} ({config_path})", file=sys.stderr)
        return outcome.exit_code
    return _Arm(
        ArmEvents(
            signals=tuple(recorder.of_type(Signal)),
            order_requests=tuple(recorder.of_type(OrderRequest)),
            order_acks=tuple(recorder.of_type(OrderAck)),
            risk_verdicts=tuple(recorder.of_type(RiskVerdict)),
            quotes=quotes,
            position_closed=tuple(recorder.of_type(PositionClosed)),
        ),
        tuple(recorder.of_type(Alert)),
        tuple(recorder.of_type(GateDecision)),
    )


def _body(legacy: _Arm, engine: _Arm, report: object) -> dict[str, object]:
    totals = report.totals  # type: ignore[attr-defined]
    diffs = report.diffs  # type: ignore[attr-defined]
    classes = [
        {
            "episode_class": row.episode_class,
            "count": row.count,
            "legacy_net": str(row.legacy_net),
            "engine_net": str(row.engine_net),
        }
        for row in totals
    ]
    legacy_net = sum((row.legacy_net for row in totals), Decimal(0))
    engine_net = sum((row.engine_net for row in totals), Decimal(0))
    legacy_suppressed, legacy_names = suppression_counts(legacy.decisions)
    engine_suppressed, engine_names = suppression_counts(engine.decisions)
    return {
        "header": _HEADER,
        "disclaimer": _DISCLAIMER,
        "symbol": _SYMBOL,
        "day": _DAY,
        "day_count": 1,
        "configs": {"engine": _ENGINE_CONFIG, "legacy": _LEGACY_CONFIG},
        "classes": classes,
        "totals": {
            "count": sum(row.count for row in totals),
            "legacy_net": str(legacy_net),
            "engine_net": str(engine_net),
        },
        "diffs": [_plain(item) for item in diffs],
        "exit_mix": {"engine": exit_mix(engine.events.position_closed)},
        "refusals": {
            "legacy": refusal_counts(legacy.alerts),
            "engine": refusal_counts(engine.alerts),
        },
        "suppressions": {
            "legacy": {"decisions": legacy_suppressed, "counts": legacy_names},
            "engine": {"decisions": engine_suppressed, "counts": engine_names},
        },
    }


def _markdown(body: dict[str, object]) -> str:
    classes = body["classes"]
    totals = body["totals"]
    configs = body["configs"]
    assert isinstance(classes, list)
    assert isinstance(totals, dict)
    assert isinstance(configs, dict)
    lines = [
        "# P-95 attribution APP 2026-03-26",
        "",
        str(body["header"]),
        f"Engine: {configs['engine']}",
        f"Legacy: {configs['legacy']}",
        str(body["disclaimer"]),
        "",
        "## Classes",
        "",
        "| class | count | legacy_net | engine_net |",
        "|---|---:|---:|---:|",
    ]
    for row in classes:
        assert isinstance(row, dict)
        lines.append(
            f"| {row['episode_class']} | {row['count']} | {row['legacy_net']} | {row['engine_net']} |"
        )
    lines.append(
        f"| TOTAL | {totals['count']} | {totals['legacy_net']} | {totals['engine_net']} |"
    )
    exit_mix_body = body["exit_mix"]
    refusals = body["refusals"]
    suppressions = body["suppressions"]
    diffs = body["diffs"]
    assert isinstance(exit_mix_body, dict)
    assert isinstance(refusals, dict)
    assert isinstance(suppressions, dict)
    assert isinstance(diffs, list)
    lines.extend(
        [
            "",
            "## Exit mix (engine)",
            "",
            json.dumps(exit_mix_body["engine"], sort_keys=True),
            "",
            "## Refusals",
            "",
            "legacy " + json.dumps(refusals["legacy"], sort_keys=True),
            "engine " + json.dumps(refusals["engine"], sort_keys=True),
            "",
            "## Suppressions",
            "",
            "legacy " + json.dumps(suppressions["legacy"], sort_keys=True),
            "engine " + json.dumps(suppressions["engine"], sort_keys=True),
            "",
            "## Episodes",
            "",
        ]
    )
    for index, diff in enumerate(diffs, start=1):
        assert isinstance(diff, dict)
        lines.append(f"### {index}. {diff['episode_class']}")
        lines.append("")
        lines.append(json.dumps(diff, indent=2, sort_keys=True))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-day P-95 attribution report (P-99a).")
    parser.add_argument("--out-dir", default=_DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    try:
        event_log, ingest, day_meta = load_event_log_from_disk_cache([_SYMBOL], _DAY, _DAY)
    except CacheReplayError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    day_sources = tuple(
        DaySource(
            symbol=meta.symbol,
            date=meta.date,
            source=meta.source,
            event_count=meta.event_count,
            ingestion_health=meta.ingestion_health,
        )
        for meta in day_meta
    )
    arms: dict[str, _Arm] = {}
    for name, path in (("legacy", _LEGACY_CONFIG), ("engine", _ENGINE_CONFIG)):
        result = _run_arm(path, event_log, ingest, day_sources)
        if isinstance(result, int):
            return result
        arms[name] = result
    legacy = arms["legacy"]
    engine = arms["engine"]
    legacy_n = len(legacy.events.position_closed)
    engine_n = len(engine.events.position_closed)
    if legacy_n != 0 or engine_n < 1:
        print(
            f"legacy PositionClosed {legacy_n}; engine PositionClosed {engine_n}",
            file=sys.stderr,
        )
        return 3
    try:
        report = attribute(legacy.events, engine.events, day_count=1)
    except AttributionError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    body = _body(legacy, engine, report)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    _write(out_dir / f"{_STEM}.json", text)
    _write(out_dir / f"{_STEM}.md", _markdown(body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
