#!/usr/bin/env python3
"""Split ``run_backtest.py`` prefixed stdout into a paper-shaped run-dir."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PREFIX_MAP = {
    "SIGNAL_JSONL": "signals.jsonl",
    "ORDER_ACK_JSONL": "order_acks.jsonl",
    "FILL_JSONL": "fills.jsonl",
    "TIMING_JSONL": "timing.jsonl",
    "SNAP_JSONL": "snapshots.jsonl",
    "SENSOR_JSONL": "sensor_readings.jsonl",
    "HTICK_JSONL": "horizon_ticks.jsonl",
    "HAZARD_JSONL": "hazard_spikes.jsonl",
    "XSECT_JSONL": "cross_sectional.jsonl",
    "INTENT_JSONL": "sized_intents.jsonl",
}


def _parse_line(line: str) -> tuple[str, dict] | None:
    """Parse one ``PREFIX {json}`` emitter line into ``(prefix, obj)``.

    The backtest emitters (``backtest_jsonl._emit_jsonl_line``) write
    ``f"{prefix} " + json.dumps(...)`` — a single space separates the prefix
    from the JSON, which itself contains ``": "``.  Splitting on the first
    space (not the first ``": "``) is therefore required; the old ``": "``
    split landed inside the JSON and silently dropped every real line.  A
    trailing colon on the prefix (legacy ``PREFIX: {json}`` form) is tolerated.
    """
    line = line.strip()
    if not line:
        return None
    prefix, sep, payload = line.partition(" ")
    if not sep:
        return None
    prefix = prefix.rstrip(":")
    if not prefix.endswith("_JSONL"):
        return None
    try:
        return prefix, json.loads(payload)
    except json.JSONDecodeError:
        return None


def split_emit_stream(
    lines: list[str],
    run_dir: Path,
    *,
    source_cmd: str = "",
) -> dict[str, int]:
    run_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, object] = {}
    counts: dict[str, int] = {}
    prefixes_seen: set[str] = set()
    first_ts: int | None = None
    last_ts: int | None = None

    try:
        for line in lines:
            parsed = _parse_line(line)
            if parsed is None:
                continue
            prefix, obj = parsed
            prefixes_seen.add(prefix)
            out_name = _PREFIX_MAP.get(prefix, f"{prefix.lower()}.jsonl")
            if out_name not in handles:
                handles[out_name] = (run_dir / out_name).open(
                    "w",
                    encoding="utf-8",
                )
                counts[out_name] = 0
            fh = handles[out_name]
            fh.write(json.dumps(obj, sort_keys=True) + "\n")  # type: ignore[union-attr]
            counts[out_name] += 1
            ts = obj.get("timestamp_ns")
            if isinstance(ts, int):
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
    finally:
        for fh in handles.values():
            fh.close()  # type: ignore[union-attr]

    metadata = {
        "prefixes_seen": sorted(prefixes_seen),
        "first_timestamp_ns": first_ts,
        "last_timestamp_ns": last_ts,
        "source_cmd": source_cmd,
        "file_counts": counts,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Split backtest prefixed JSONL stdout")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--input", type=Path, default=None, help="Input log file (default stdin)")
    p.add_argument("--source-cmd", default="", help="Original command for metadata")
    args = p.parse_args(argv)

    if args.input is not None:
        lines = args.input.read_text(encoding="utf-8").splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    counts = split_emit_stream(lines, args.run_dir, source_cmd=args.source_cmd)
    total = sum(counts.values())
    if total == 0:
        print(
            f"  WARNING: parsed 0 JSONL rows from {len(lines)} input line(s) — "
            "no '<PREFIX>_JSONL {json}' lines found (did the run enable --emit-*-jsonl?).",
            file=sys.stderr,
        )
    else:
        print(f"  wrote {total:,} row(s) across {len(counts)} file(s) -> {args.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
