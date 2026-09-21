"""Structural guards for the exec LEDGER.md.

Catches a step block or CAMPAIGN CLOSE appended twice as identical
adjacent copies. 89d3ac28 (0.3 / CI restoration) and c62903ce
(G45-05 / G45 proven-site keep) were that shape. Does not assert unique
step ids: retries reuse the id with a different body.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

_LEDGER = Path("docs/architecture/target/out/exec/LEDGER.md")
_CLOSE_PREFIX = "## CAMPAIGN CLOSE"


def scan(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Split ``text`` into ``##``-delimited blocks.

    Returns ``(close_names, blocks)``. Each block is ``(heading, body)``
    where ``heading`` is the ``## ...`` line without its newline and
    ``body`` is the text after it up to the next heading. ``close_names``
    is the remainder of each ``## CAMPAIGN CLOSE`` heading, stripped.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    blocks: list[tuple[str, str]] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        heading = lines[start].rstrip("\n")
        body = "".join(lines[start + 1 : end])
        blocks.append((heading, body))
    close_names = [
        heading[len(_CLOSE_PREFIX) :].strip()
        for heading, _body in blocks
        if heading.startswith(_CLOSE_PREFIX)
    ]
    return close_names, blocks


def _normalise_body(body: str) -> str:
    """Strip trailing whitespace and trailing ``---`` / blank separator lines."""
    lines = body.splitlines()
    while lines and lines[-1].strip() in {"", "---"}:
        lines.pop()
    return "\n".join(lines).rstrip()


def test_campaign_close_names_are_unique() -> None:
    names, _blocks = scan(_LEDGER.read_text(encoding="utf-8"))
    duplicated = sorted({name for name, n in Counter(names).items() if n > 1})
    assert not duplicated, f"duplicated CAMPAIGN CLOSE name(s): {duplicated}"


def test_no_duplicated_ledger_blocks() -> None:
    _names, blocks = scan(_LEDGER.read_text(encoding="utf-8"))
    normalised = [(heading, _normalise_body(body)) for heading, body in blocks]
    duplicated = sorted({heading for (heading, _body), n in Counter(normalised).items() if n > 1})
    assert not duplicated, f"duplicated ledger block heading(s): {duplicated}"
