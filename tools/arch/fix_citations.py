"""Expand abbreviated `path.py` citations in a phase output to repo-root paths.

`measure.py spotcheck` resolves every citation against the repository root, so an
abbreviated citation such as ``risk/exit_composer.py:486`` fails even though the
line exists at ``src/feelies/risk/exit_composer.py:486``. This rewrites those to
the unique resolving path, and reports any that stay unresolved or are ambiguous.

Usage:  python tools/arch/fix_citations.py <file> [--apply]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREFIXES = ("", "src/feelies/", "tools/arch/", "tests/", "src/")
CITATION = re.compile(r"`([\w./\-]+\.py)(?::(\d+|[A-Za-z_][\w]*))?`")


def candidates(path: str) -> list[str]:
    found = []
    for prefix in PREFIXES:
        if (ROOT / (prefix + path)).is_file():
            found.append(prefix + path)
    if found:
        return found
    # Fall back to a basename search so ambiguity is reported, not guessed.
    name = pathlib.Path(path).name
    for base in ("src", "tools", "tests"):
        found.extend(
            str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / base).rglob(name)
        )
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    target = ROOT / str(args.file).replace("\\", "/")
    text = target.read_text(encoding="utf-8")

    rewrites: dict[str, str] = {}
    unresolved: list[str] = []
    ambiguous: list[tuple[str, list[str]]] = []

    for path, _sym in sorted(set(CITATION.findall(text))):
        if (ROOT / path).is_file():
            continue
        found = candidates(path)
        unique = sorted(set(found))
        if not unique:
            unresolved.append(path)
        elif len(unique) > 1:
            ambiguous.append((path, unique))
        else:
            rewrites[path] = unique[0]

    for old, new in sorted(rewrites.items()):
        print(f"  rewrite  {old}  ->  {new}")
    for path in unresolved:
        print(f"  UNRESOLVED  {path}")
    for path, opts in ambiguous:
        print(f"  AMBIGUOUS   {path}  -> {opts}")

    if args.apply and rewrites:
        # Longest first so a shorter path is never substituted inside a longer one.
        for old in sorted(rewrites, key=len, reverse=True):
            text = text.replace(f"`{old}`", f"`{rewrites[old]}`")
            text = re.sub(
                rf"`{re.escape(old)}:(\d+|[A-Za-z_]\w*)`",
                lambda m, new=rewrites[old]: f"`{new}:{m.group(1)}`",
                text,
            )
        target.write_text(text, encoding="utf-8")
        print(f"\napplied {len(rewrites)} rewrite(s) to {args.file}")

    print(
        f"\n{len(rewrites)} rewritable, {len(unresolved)} unresolved, "
        f"{len(ambiguous)} ambiguous"
    )
    return 1 if (unresolved or ambiguous) else 0


if __name__ == "__main__":
    sys.exit(main())
