#!/usr/bin/env python3
"""Author deterministic ALGO_CLOCK half-hour calendars (H12 Phase A).

Exchange-schedule authoring only — no market data, no σ, no IC, no
forward returns. Implements formal-spec §1.5.2 / protocol §1.1:

* twelve half-hour marks ``10:00 … 15:30`` America/New_York;
* half-open interval ``[M, M+1s)`` (``start_et`` / ``end_et`` with 1 s
  duration);
* ``flow_direction_prior: 0.0``; universe-wide ``symbol: null``;
* merge with any existing non-``ALGO_CLOCK`` rows (do not delete them).

Targets the operative 20-session {APP, RMBS} grid. Re-running under
``PYTHONHASHSEED=0`` must produce bit-identical YAML bytes and
``EventCalendar.hash`` per date (census precondition).

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/author_algo_clock_calendars.py \\
        [--out-dir src/feelies/storage/reference/event_calendar] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.storage.reference.event_calendar import (  # noqa: E402
    WindowKind,
    load_event_calendar,
)
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR  # noqa: E402

# ── Frozen 20-session grid (protocol preamble / 03c) ─────────────────────

DATES_ELEVATED_A = ("2025-11-25", "2025-12-04")
DATES_CALM = ("2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27")
DATES_ELEVATED_B = ("2026-04-01", "2026-04-10", "2026-04-22")
DATES_PREAMBLE = DATES_ELEVATED_A + DATES_CALM + DATES_ELEVATED_B

DATES_ELEVATED_A_EXP = ("2025-12-01", "2025-12-02")
DATES_CALM_EXP = ("2025-12-26", "2025-12-30", "2026-01-12", "2026-01-20", "2026-01-22")
DATES_ELEVATED_B_EXP = ("2026-04-02", "2026-04-07", "2026-04-16")
DATES_EXPANSION = DATES_ELEVATED_A_EXP + DATES_CALM_EXP + DATES_ELEVATED_B_EXP
DATES_ALL = DATES_PREAMBLE + DATES_EXPANSION

# Twelve half-hour marks inside 09:35–15:50 (formal-spec §1.5.2).
HALF_HOUR_MARKS: tuple[tuple[int, int], ...] = (
    (10, 0),
    (10, 30),
    (11, 0),
    (11, 30),
    (12, 0),
    (12, 30),
    (13, 0),
    (13, 30),
    (14, 0),
    (14, 30),
    (15, 0),
    (15, 30),
)


def _hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}{minute:02d}"


def _clock(hour: int, minute: int, second: int = 0) -> str:
    if second == 0:
        return f"{hour:02d}:{minute:02d}"
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def algo_clock_window_rows(session_date: date) -> list[dict[str, Any]]:
    """Twelve ALGO_CLOCK rows for ``session_date`` under the frozen convention."""
    ymd = session_date.strftime("%Y_%m_%d")
    rows: list[dict[str, Any]] = []
    for hour, minute in HALF_HOUR_MARKS:
        hhmm = _hhmm(hour, minute)
        rows.append(
            {
                "window_id": f"algo_clock_hh_{hhmm}_{ymd}",
                "kind": WindowKind.ALGO_CLOCK.value,
                "symbol": None,
                "start_et": _clock(hour, minute),
                "end_et": _clock(hour, minute, 1),
                "flow_direction_prior": 0.0,
                "meta": {
                    "card": "sig_halfhour_clock_drift_h900_v1",
                    "mark_class": "half_hour",
                },
            }
        )
    return rows


def _load_existing_windows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: top-level must be a mapping")
    windows = raw.get("windows", [])
    if not isinstance(windows, list):
        raise ValueError(f"{path}: 'windows' must be a list")
    kept: list[dict[str, Any]] = []
    for w in windows:
        if not isinstance(w, Mapping):
            raise ValueError(f"{path}: window entry must be a mapping")
        if str(w.get("kind")) == WindowKind.ALGO_CLOCK.value:
            continue  # replaced by fresh authoring
        kept.append(dict(w))
    return kept


def _yaml_quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value == 0.0:
            return "0.0"
        if value == 1.0:
            return "1.0"
        if value == -1.0:
            return "-1.0"
        return repr(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("\n", " ").strip()
    # Quote clock times and anything YAML could mis-parse.
    if (
        ":" in text
        or text == ""
        or text.lower() in {"null", "true", "false", "yes", "no"}
        or any(c in text for c in ("#", "{", "}", "[", "]", ",", "&", "*", "?", "|", ">", "!", "%", "@", "`"))
    ):
        return _yaml_quote(text)
    return text


def _format_meta(meta: Mapping[str, Any], *, indent: str) -> list[str]:
    lines = [f"{indent}meta:"]
    if not meta:
        lines.append(f"{indent}  {{}}")
        return lines
    for key in sorted(meta):
        lines.append(f"{indent}  {key}: {_format_scalar(meta[key])}")
    return lines


def render_calendar_yaml(
    session_date: date,
    windows: Sequence[Mapping[str, Any]],
) -> str:
    """Deterministic YAML text (stable key order, LF newlines)."""
    ordered = sorted(
        windows,
        key=lambda w: (
            str(w.get("start_et") or w.get("start_ns") or ""),
            str(w.get("kind") or ""),
            str(w.get("window_id") or ""),
        ),
    )
    lines: list[str] = [
        f"# Reference scheduled-flow window calendar for {session_date.isoformat()} (regular RTH).",
        "#",
        "# Consumed by feelies.sensors.impl.scheduled_flow_window via",
        "# feelies.storage.reference.event_calendar.load_event_calendar().",
        "# Content-addressed: any edit changes EventCalendar.hash().",
        "#",
        "# ALGO_CLOCK rows authored by scripts/research/author_algo_clock_calendars.py",
        "# (H12 formal-spec §1.5.2 — exchange schedule only; [M, M+1s) half-open).",
        "#",
        f"session_date: {session_date.isoformat()}",
        "windows:",
    ]
    for w in ordered:
        lines.append(f"  - window_id: {w['window_id']}")
        lines.append(f"    kind: {w['kind']}")
        lines.append(f"    symbol: {_format_scalar(w.get('symbol'))}")
        if "start_et" in w and "end_et" in w:
            lines.append(f"    start_et: {_format_scalar(str(w['start_et']))}")
            lines.append(f"    end_et: {_format_scalar(str(w['end_et']))}")
        else:
            lines.append(f"    start_ns: {int(w['start_ns'])}")
            lines.append(f"    end_ns: {int(w['end_ns'])}")
        prior = float(w.get("flow_direction_prior", 0.0))
        lines.append(f"    flow_direction_prior: {_format_scalar(prior)}")
        meta = w.get("meta") or {}
        if not isinstance(meta, Mapping):
            raise ValueError(f"window {w.get('window_id')!r}: meta must be a mapping")
        lines.extend(_format_meta(meta, indent="    "))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def author_calendar_yaml(session_iso: str, *, existing_path: Path | None) -> str:
    """Build the full YAML for one session date (merge non-ALGO_CLOCK)."""
    session_date = date.fromisoformat(session_iso)
    existing = _load_existing_windows(existing_path) if existing_path is not None else []
    windows = existing + algo_clock_window_rows(session_date)
    return render_calendar_yaml(session_date, windows)


def author_all(
    out_dir: Path,
    *,
    dates: Sequence[str] = DATES_ALL,
    write: bool = True,
) -> dict[str, str]:
    """Author calendars for ``dates``. Returns ``{date: yaml_text}``."""
    out: dict[str, str] = {}
    for d in dates:
        path = out_dir / f"{d}.yaml"
        # Merge source: committed file when present (preserves OPENING/MOC).
        text = author_calendar_yaml(d, existing_path=path if path.is_file() else None)
        out[d] = text
        if write:
            path.write_text(text, encoding="utf-8", newline="\n")
    return out


def calendar_hashes(out_dir: Path, dates: Sequence[str] = DATES_ALL) -> dict[str, str]:
    """Load authored YAMLs and return ``EventCalendar.hash`` per date."""
    return {
        d: load_event_calendar(out_dir / f"{d}.yaml", expected_session_date=date.fromisoformat(d)).hash()
        for d in dates
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=EVENT_CALENDAR_DIR,
        help="Directory for <YYYY-MM-DD>.yaml calendars",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and hash only; do not write files",
    )
    args = ap.parse_args(argv)
    texts = author_all(args.out_dir, write=not args.dry_run)
    # Always verify load + hash after write (or against dry-run render via tmp).
    if args.dry_run:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for d, text in texts.items():
                (tmp_path / f"{d}.yaml").write_text(text, encoding="utf-8", newline="\n")
            hashes = calendar_hashes(tmp_path)
    else:
        hashes = calendar_hashes(args.out_dir)
    print(f"authored {len(texts)} calendars under {args.out_dir}")
    for d in DATES_ALL:
        print(f"  {d}  hash={hashes[d][:16]}…  algo_clock=12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
