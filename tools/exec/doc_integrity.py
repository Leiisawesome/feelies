"""Pure checks for decision ids, member ids, ladder rows, and ledger blocks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

Block = tuple[int, int, str]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def registry_duplicates(text: str, pattern: str) -> dict[str, int]:
    """Ids whose matches are not exactly one."""
    counts: dict[str, int] = {}
    for match in re.finditer(pattern, text, re.MULTILINE):
        ident = match.group(1)
        counts[ident] = counts.get(ident, 0) + 1
    return {ident: count for ident, count in counts.items() if count != 1}


def _registry_lines(text: str, pattern: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    compiled = re.compile(pattern)
    for number, line in enumerate(text.splitlines(), start=1):
        match = compiled.match(line)
        if match is None:
            continue
        found.setdefault(match.group(1), []).append(number)
    return found


def require_registry(path: str, text: str, pattern: str) -> None:
    duplicates = registry_duplicates(text, pattern)
    if not duplicates:
        return
    lines = _registry_lines(text, pattern)
    parts = []
    for ident in sorted(duplicates):
        where = ", ".join(str(number) for number in lines[ident])
        parts.append(f"{path}: {ident} count {duplicates[ident]} at lines {where}")
    raise AssertionError("; ".join(parts))


def identical_ledger_blocks(text: str) -> list[list[Block]]:
    """Groups of ## blocks with the same normalised bytes. Re-entries may differ."""
    raw = text.splitlines()
    starts = [index for index, line in enumerate(raw) if line.startswith("## ")]
    grouped: dict[str, list[Block]] = {}
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(raw)
        lines = [line.rstrip() for line in raw[start:end]]
        while lines and lines[-1] == "":
            lines.pop()
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        grouped.setdefault(digest, []).append((start + 1, end, digest))
    return [group for group in grouped.values() if len(group) > 1]


def require_ledger(path: str, text: str) -> None:
    groups = identical_ledger_blocks(text)
    if not groups:
        return
    parts = []
    for group in groups:
        prefix = group[0][2][:12]
        spans = " and ".join(f"{start}-{end}" for start, end, _digest in group)
        parts.append(f"{path}: block {prefix} identical at lines {spans}")
    raise AssertionError("; ".join(parts))
