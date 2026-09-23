"""Committed pre/post captures for every exec-ledger rung.

L-03: each ``## <rung-id>`` block needs committed ``baseline_pre-<id>.json``
and ``baseline_post-<id>.json``. Work with no code change uses a non-rung
heading (RECORD / CORRECTION). There is no exemption line.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_LEDGER = Path("docs/architecture/target/out/exec/LEDGER.md")
_EXEC_DIR = "docs/architecture/target/out/exec"
_RUNG_RE = re.compile(r"^(?:\d+\.\d+|[A-Z][A-Z0-9]*-\d+[A-Za-z0-9]*)$")
_OTHER_PREFIXES: frozenset[str] = frozenset(
    {
        "DEFERRAL",
        "EXEMPTION",
        "END STATE",
        "FINDING",
        "CORRECTION",
        "RECORD",
        "STAGE LOCK",
    }
)
_CAMPAIGN_CLOSE = "## CAMPAIGN CLOSE"
_UNCAPTURED_KEEP: dict[tuple[str, str], str] = {
    ("S-35e", "pre"): "block cites post-S-35d5; no pre-S-35e committed",
    ("L-02", "pre"): "block cites pre-L-02; file never committed",
    ("O-03b", "pre"): "block cites post-O-03a; no pre-O-03b committed",
    ("O-04", "pre"): "retirement record for unbuilt S-04c; no code landed",
    ("O-04", "post"): "retirement record for unbuilt S-04c; no code landed",
    ("O-06", "pre"): "block cites only post-O-07; no captures taken",
    ("O-06", "post"): "block cites only post-O-07; no captures taken",
    ("O-08", "pre"): "block cites only post-O-07; no captures taken",
    ("O-08", "post"): "block cites only post-O-07; no captures taken",
    ("O-09a", "pre"): "block cites only post-O-07; no captures taken",
    ("O-09a", "post"): "block cites only post-O-07; no captures taken",
    ("O-09", "pre"): "block cites only post-O-07; no captures taken",
    ("O-09", "post"): "block cites only post-O-07; no captures taken",
    ("O-10", "pre"): "block cites only post-O-07; no captures taken",
    ("O-10", "post"): "block cites only post-O-07; no captures taken",
    ("O-11", "pre"): "block cites only post-O-07; no captures taken",
    ("O-11", "post"): "block cites only post-O-07; no captures taken",
    ("O-11b", "pre"): "block cites pre-O-11 and post-O-07; no captures taken",
    ("O-11b", "post"): "block cites pre-O-11 and post-O-07; no captures taken",
    ("C-01", "pre"): "documentation only; no captures taken",
    ("C-01", "post"): "documentation only; no captures taken",
    ("C-02", "pre"): "post-hoc capture baseline_at-arch-migration-v1-posthoc stands in",
    ("C-02", "post"): "post-hoc capture baseline_at-arch-migration-v1-posthoc stands in",
}


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def _token(heading: str) -> str:
    return heading[3:].split(None, 1)[0]


def _kind(heading: str) -> str | None:
    body = heading[3:]
    if _RUNG_RE.match(_token(heading)):
        return "rung"
    if heading.startswith(_CAMPAIGN_CLOSE):
        return "campaign-close"
    for prefix in sorted(_OTHER_PREFIXES, key=len, reverse=True):
        if body == prefix or body.startswith(prefix + " "):
            return prefix
    return None


def _is_known_heading(heading: str) -> bool:
    return _kind(heading) is not None


def _tracked_exec_names() -> set[str]:
    proc = subprocess.run(
        ["git", "ls-files", "--", _EXEC_DIR],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, f"git ls-files failed ({proc.returncode}): {proc.stderr}"
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if rel:
            names.add(rel.rsplit("/", 1)[-1])
    return names


def _missing(headings: list[str], tracked: set[str]) -> set[tuple[str, str]]:
    missing: set[tuple[str, str]] = set()
    rung_ids: set[str] = set()
    for heading in headings:
        token = _token(heading)
        if _RUNG_RE.match(token):
            rung_ids.add(token)
    for rung_id in rung_ids:
        for side in ("pre", "post"):
            if f"baseline_{side}-{rung_id}.json" not in tracked:
                missing.add((rung_id, side))
    return missing


def test_every_ledger_heading_is_classified() -> None:
    unknown = [
        heading
        for heading in _headings(_LEDGER.read_text(encoding="utf-8"))
        if not _is_known_heading(heading)
    ]
    assert not unknown, "unknown heading(s): " + "; ".join(unknown)


def test_capture_misses_equal_keep() -> None:
    headings = _headings(_LEDGER.read_text(encoding="utf-8"))
    missing = _missing(headings, _tracked_exec_names())
    keep = set(_UNCAPTURED_KEEP)
    new_misses = missing - keep
    stale = keep - missing
    assert missing == keep, f"new misses: {sorted(new_misses)}; stale rows: {sorted(stale)}"
