"""Real-day P-95 attribution report (D-253).

Descriptive, one day. Not evidence of edge (evaluation.md section 1).
The runner passes each arm's signal-order trace rows to
``feelies.forensics.exit_attribution`` and does not link orders itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import (
    Alert,
    Event,
    GateDecision,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    PositionClosed,
    RiskVerdict,
    Signal,
)
from feelies.core.platform_config import PlatformConfig
from feelies.forensics.exit_attribution import ArmEvents, AttributionError, attribute
from feelies.harness.backtest_prep import prepare_backtest_event_log
from feelies.harness.backtest_runner import (
    DaySource,
    _attach_day_source_provenance,
    _enforce_ingest_event_mix,
    _run_backtest_phases_2_7,
)
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache
from feelies.storage.memory_event_log import InMemoryEventLog

_ENGINE_CONFIG = Path("configs/bt_position_arbitrary_not_calibrated.yaml")
_LEGACY_CONFIG = Path("configs/bt_position_legacy_arm.yaml")
_SYMBOL = "APP"
_DATE = "2026-03-26"
_OUT_STEM = "P-99a_attribution_APP_2026-03-26"
_DEFAULT_OUT = Path("docs/architecture/target/out/exec")
_CLASSES = (
    "SAME",
    "EXIT_CHANGED",
    "ENTRY_CHANGED",
    "LEGACY_ONLY",
    "ENGINE_ONLY",
    "UNEXPLAINED",
)
_RECORDED = (
    Signal,
    OrderRequest,
    OrderAck,
    RiskVerdict,
    PositionClosed,
    GateDecision,
    Alert,
)


class _Halt(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _sorted_counts(counts: dict[str, int]) -> dict[str, int]:
    return dict(sorted(counts.items()))


def exit_mix(closed: Sequence[PositionClosed]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in closed:
        counts[item.exit_reason] = counts.get(item.exit_reason, 0) + 1
    return _sorted_counts(counts)


def refusal_counts(alerts: Sequence[Alert]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for alert in alerts:
        if alert.alert_name != "position_entry_refused":
            continue
        reason = str(alert.context["refusal_reason"])
        counts[reason] = counts.get(reason, 0) + 1
    return _sorted_counts(counts)


def suppression_counts(decisions: Sequence[GateDecision]) -> tuple[int, dict[str, int]]:
    suppressed = 0
    counts: dict[str, int] = {}
    for decision in decisions:
        if decision.outcome != "suppressed":
            continue
        suppressed += 1
        for name in decision.suppressions:
            counts[name] = counts.get(name, 0) + 1
    return suppressed, _sorted_counts(counts)


class _Recorder:
    def __init__(self) -> None:
        self.by_type: dict[type[Event], list[Event]] = defaultdict(list)

    def __call__(self, event: Event) -> None:
        self.by_type[type(event)].append(event)


def _of_type(recorder: _Recorder, kind: type[Event]) -> tuple[Event, ...]:
    return tuple(recorder.by_type.get(kind, ()))


def _run_args() -> argparse.Namespace:
    return argparse.Namespace(
        trace_signal_orders=True,
        emit_fills_jsonl=False,
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
        emit_cross_sectional_jsonl=False,
        emit_sized_intents_jsonl=False,
        emit_hazard_exits_jsonl=False,
        emit_net_divergence_jsonl=False,
        emit_size_divergence_jsonl=False,
        emit_edge_calibration=None,
    )


@dataclass
class _Hold:
    sink: list[object] | None = None
    recorder: _Recorder = field(default_factory=_Recorder)


def _factory(hold: _Hold):
    def factory(
        config: PlatformConfig,
        event_log: InMemoryEventLog,
        **kwargs: object,
    ) -> tuple[object, PlatformConfig]:
        sink = kwargs.get("signal_order_trace_sink")
        hold.sink = sink if isinstance(sink, list) else None
        orchestrator, resolved = build_platform(config, event_log=event_log, **kwargs)
        for event_type in _RECORDED:
            orchestrator._bus.subscribe(event_type, hold.recorder)
        return orchestrator, resolved

    return factory


def _day_sources(day_meta: Sequence[object]) -> list[DaySource]:
    sources: list[DaySource] = []
    for meta in day_meta:
        sources.append(
            DaySource(
                symbol=meta.symbol,  # type: ignore[attr-defined]
                date=meta.date,  # type: ignore[attr-defined]
                source=meta.source,  # type: ignore[attr-defined]
                event_count=meta.event_count,  # type: ignore[attr-defined]
                ingestion_health=meta.ingestion_health,  # type: ignore[attr-defined]
            )
        )
    return sources


@dataclass(frozen=True)
class _ArmRun:
    name: str
    events: ArmEvents
    alerts: tuple[Alert, ...]
    decisions: tuple[GateDecision, ...]
    closed: tuple[PositionClosed, ...]


def _run_arm(name: str, config_path: Path) -> _ArmRun:
    try:
        event_log, ingest, day_meta = load_event_log_from_disk_cache([_SYMBOL], _DATE, _DATE)
    except CacheReplayError as exc:
        raise _Halt(2, str(exc)) from exc
    config = PlatformConfig.from_yaml(config_path)
    symbols = sorted(config.symbols)
    day_sources = _day_sources(day_meta)
    prep = prepare_backtest_event_log(config, event_log)
    rc = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="disk cache",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        raise _Halt(rc, f"{config_path.as_posix()}: ingest event mix rejected the session ({rc})")
    config = _attach_day_source_provenance(config, symbols, day_sources)
    hold = _Hold()
    outcome = _run_backtest_phases_2_7(
        _run_args(),
        event_log,
        ingest,
        day_sources,
        config,
        symbols,
        _SYMBOL,
        _DATE,
        time.monotonic(),
        platform_factory=_factory(hold),
        prep=prep,
    )
    if outcome.exit_code != 0:
        raise _Halt(
            outcome.exit_code,
            f"{config_path.as_posix()}: backtest exit {outcome.exit_code}",
        )
    quotes = tuple(event for event in prep.event_log.replay() if isinstance(event, NBBOQuote))
    closed = tuple(event for event in _of_type(hold.recorder, PositionClosed))
    alerts = tuple(event for event in _of_type(hold.recorder, Alert))
    decisions = tuple(event for event in _of_type(hold.recorder, GateDecision))
    sink = hold.sink
    events = ArmEvents(
        signals=tuple(_of_type(hold.recorder, Signal)),  # type: ignore[arg-type]
        order_requests=tuple(_of_type(hold.recorder, OrderRequest)),  # type: ignore[arg-type]
        order_acks=tuple(_of_type(hold.recorder, OrderAck)),  # type: ignore[arg-type]
        risk_verdicts=tuple(_of_type(hold.recorder, RiskVerdict)),  # type: ignore[arg-type]
        quotes=quotes,
        position_closed=closed,  # type: ignore[arg-type]
        signal_order_traces=() if sink is None else tuple(sink),
    )
    return _ArmRun(
        name=name,
        events=events,
        alerts=alerts,  # type: ignore[arg-type]
        decisions=decisions,  # type: ignore[arg-type]
        closed=closed,  # type: ignore[arg-type]
    )


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _episode_row(item: object) -> dict[str, object]:
    legacy = item.legacy  # type: ignore[attr-defined]
    engine = item.engine  # type: ignore[attr-defined]
    present = legacy if legacy is not None else engine
    signal = present.entry_signal
    return {
        "episode_class": item.episode_class,  # type: ignore[attr-defined]
        "symbol": present.symbol,
        "strategy_id": present.strategy_id,
        "entry_timestamp_ns": signal.timestamp_ns,
        "entry_sequence": signal.sequence,
        "legacy_side": None if legacy is None else legacy.side,
        "engine_side": None if engine is None else engine.side,
        "legacy_reason": item.legacy_reason,  # type: ignore[attr-defined]
        "engine_reason": item.engine_reason,  # type: ignore[attr-defined]
        "explanation": item.explanation,  # type: ignore[attr-defined]
        "legacy_net": None if legacy is None else _money(legacy.net_after_fees),
        "engine_net": None if engine is None else _money(engine.net_after_fees),
        "legacy_mae": _money(item.legacy_mae),  # type: ignore[attr-defined]
        "engine_mae": _money(item.engine_mae),  # type: ignore[attr-defined]
    }


def _arm_counts(arm: _ArmRun) -> dict[str, object]:
    suppressed, by_reason = suppression_counts(arm.decisions)
    return {
        "exit_mix": exit_mix(arm.closed),
        "refusals": refusal_counts(arm.alerts),
        "suppressions": {"count": suppressed, "by_reason": by_reason},
    }


def _payload(legacy: _ArmRun, engine: _ArmRun) -> dict[str, object]:
    try:
        report = attribute(legacy.events, engine.events, day_count=1)
    except AttributionError as exc:
        raise _Halt(4, str(exc)) from exc
    totals = {row.episode_class: row for row in report.totals}
    classes: list[dict[str, object]] = []
    for name in _CLASSES:
        row = totals.get(name)
        if row is None:
            classes.append(
                {"episode_class": name, "count": 0, "legacy_net": "0", "engine_net": "0"}
            )
        else:
            classes.append(
                {
                    "episode_class": name,
                    "count": row.count,
                    "legacy_net": _money(row.legacy_net),
                    "engine_net": _money(row.engine_net),
                }
            )
    diffs = tuple(_episode_row(item) for item in report.diffs)
    explanations: list[dict[str, object]] = []
    for name in _CLASSES:
        counts: dict[str, int] = {}
        for item in diffs:
            if item["episode_class"] != name:
                continue
            text = str(item["explanation"])
            counts[text] = counts.get(text, 0) + 1
        for text, count in _sorted_counts(counts).items():
            explanations.append({"episode_class": name, "explanation": text, "count": count})
    legacy_reasons: dict[str, int] = {}
    for item in diffs:
        if item["legacy_side"] is None:
            continue
        reason = str(item["legacy_reason"])
        legacy_reasons[reason] = legacy_reasons.get(reason, 0) + 1
    legacy_counts = _arm_counts(legacy)
    engine_counts = _arm_counts(engine)
    return {
        "label": report.label,
        "day_count": report.day_count,
        "symbol": _SYMBOL,
        "session_date": _DATE,
        "engine_config": _ENGINE_CONFIG.as_posix(),
        "legacy_config": _LEGACY_CONFIG.as_posix(),
        "linkage": "signal-order trace linkage (D-252)",
        "evidence_note": "not evidence of edge, evaluation.md §1",
        "classes": classes,
        "explanations": explanations,
        "legacy_reasons": _sorted_counts(legacy_reasons),
        "exit_mix": engine_counts["exit_mix"],
        "refusals": {
            "legacy": legacy_counts["refusals"],
            "engine": engine_counts["refusals"],
        },
        "suppressions": {
            "legacy": legacy_counts["suppressions"],
            "engine": engine_counts["suppressions"],
        },
        "diffs": diffs,
    }


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(", ", ": "))


def _summary(payload: dict[str, object]) -> str:
    lines = ["classes"]
    for row in payload["classes"]:  # type: ignore[union-attr]
        lines.append(
            f"{row['episode_class']} {row['count']} {row['legacy_net']} {row['engine_net']}"
        )
    lines.append("explanations")
    seen: set[str] = set()
    for row in payload["explanations"]:  # type: ignore[union-attr]
        seen.add(str(row["episode_class"]))
        lines.append(f"{row['episode_class']} {row['explanation']!r} {row['count']}")
    for name in _CLASSES:
        if name not in seen:
            lines.append(f"{name} (none)")
    lines.append("legacy_reasons")
    reasons = payload["legacy_reasons"]
    if reasons:
        for reason, count in reasons.items():  # type: ignore[union-attr]
            lines.append(f"{reason} {count}")
    else:
        lines.append("(none)")
    lines.append("exit_mix")
    lines.append(_dumps(payload["exit_mix"]))
    refusals = payload["refusals"]
    lines.append(f"refusals legacy {_dumps(refusals['legacy'])}")  # type: ignore[index]
    lines.append(f"refusals engine {_dumps(refusals['engine'])}")  # type: ignore[index]
    suppressions = payload["suppressions"]
    for name in ("legacy", "engine"):
        block = suppressions[name]  # type: ignore[index]
        lines.append(f"suppressions {name} {block['count']} {_dumps(block['by_reason'])}")
    unexplained = next(
        row["count"]
        for row in payload["classes"]  # type: ignore[union-attr]
        if row["episode_class"] == "UNEXPLAINED"
    )
    lines.append(f"unexplained {unexplained}")
    if unexplained:
        lines.append("unexplained_episodes")
        for item in payload["diffs"]:  # type: ignore[union-attr]
            if item["episode_class"] != "UNEXPLAINED":
                continue
            lines.append(
                f"{item['symbol']} {item['entry_timestamp_ns']} {item['entry_sequence']} "
                f"{item['explanation']!r} {item['legacy_reason']!r} {item['engine_reason']!r}"
            )
    return "\n".join(lines) + "\n"


def _markdown(payload: dict[str, object]) -> str:
    header = "\n".join(
        (
            "# P-95 attribution APP 2026-03-26",
            "",
            "Descriptive, 1 day. APP 2026-03-26.",
            f"Engine config: {payload['engine_config']}",
            f"Legacy config: {payload['legacy_config']}",
            str(payload["linkage"]),
            str(payload["evidence_note"]),
            "",
        )
    )
    episode_lines = ["episodes"]
    for index, item in enumerate(payload["diffs"], start=1):  # type: ignore[arg-type]
        episode_lines.append(
            f"{index} {item['episode_class']} {item['symbol']} {item['strategy_id']} "
            f"{item['entry_timestamp_ns']} {item['entry_sequence']} "
            f"legacy_side={item['legacy_side']} engine_side={item['engine_side']} "
            f"legacy_reason={item['legacy_reason']!r} engine_reason={item['engine_reason']!r} "
            f"explanation={item['explanation']!r} "
            f"legacy_net={item['legacy_net']} engine_net={item['engine_net']} "
            f"legacy_mae={item['legacy_mae']} engine_mae={item['engine_mae']}"
        )
    if len(episode_lines) == 1:
        episode_lines.append("(none)")
    body = _summary(payload) + "\n".join(episode_lines) + "\n"
    return header + body


def _emit(out_dir: Path, payload: dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(payload)
    document = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    (out_dir / f"{_OUT_STEM}.md").write_text(markdown, encoding="utf-8", newline="\n")
    (out_dir / f"{_OUT_STEM}.json").write_text(document, encoding="utf-8", newline="\n")


def _empty_sinks(legacy: _ArmRun, engine: _ArmRun) -> list[str]:
    missing: list[str] = []
    for arm in (engine, legacy):
        if not arm.events.signal_order_traces:
            missing.append(arm.name)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-day P-95 attribution report (D-253).")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT)
    parsed = parser.parse_args(argv)
    try:
        engine = _run_arm("engine", _ENGINE_CONFIG)
        legacy = _run_arm("legacy", _LEGACY_CONFIG)
        missing = _empty_sinks(legacy, engine)
        if missing:
            joined = ", ".join(missing)
            raise _Halt(
                5,
                "signal-order trace linkage is required for real runs; "
                f"empty trace sink: {joined}",
            )
        if len(legacy.closed) != 0 or len(engine.closed) < 1:
            raise _Halt(
                3,
                f"legacy PositionClosed {len(legacy.closed)}, "
                f"engine PositionClosed {len(engine.closed)}; "
                "expected legacy 0 and engine at least 1",
            )
        payload = _payload(legacy, engine)
    except _Halt as exc:
        print(exc.message, file=sys.stderr)
        return exc.code
    _emit(parsed.out_dir, payload)
    print(_summary(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
