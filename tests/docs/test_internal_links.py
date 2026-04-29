"""Verify internal repo paths cited from documentation actually exist.

The Phase-5 documentation rewrite (README, alphas/SCHEMA.md, the
migration cookbook, the embedded Grok prompts in ``grok/03_*``,
``grok/06_*``, and ``grok/07_*``, and the source-code comments in
``layer_validator.py`` / ``regime_gate.py``) carries dozens of
cross-references to other repository paths.  When a file is renamed or
moved without updating those references, the operator hits a 404 inside
their own checkout — exactly the kind of silent doc rot Phase 5 was
meant to eliminate.

This test enumerates the *whitelist* of canonical doc files we
shipped in Phase 5, scrapes the path tokens they cite, and asserts
each cited path resolves on disk.

Scope:
* only repo-relative path tokens are checked (URLs, scheme://… and
  any token starting with ``http`` are ignored);
* tokens are extracted from explicit Markdown patterns (backticks,
  bare ``foo/bar`` paths inside lines) and from inline code in
  ``.py`` source comments via simple regex;
* obvious noise tokens are filtered (e.g. ``schema_version``,
  ``alpha_id``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(".").resolve()


# Files we authoritatively own and whose links should resolve.
#
_DOC_FILES: tuple[Path, ...] = (
    Path("README.md"),
    Path("alphas/SCHEMA.md"),
    Path("docs/migration/schema_1_0_to_1_1.md"),
    Path("grok/03_ALPHA_DEVELOPMENT.md"),
    Path("grok/06_EVOLUTION.md"),
    Path("grok/07_HYPOTHESIS_REASONING.md"),
)


# No retired doc files remain on the tracked existence-only list.
_DOC_EXISTENCE_ONLY: tuple[Path, ...] = ()


# Source files whose comment-level path references must stay valid.
_SOURCE_FILES: tuple[Path, ...] = (
    Path("src/feelies/alpha/layer_validator.py"),
    Path("src/feelies/signals/regime_gate.py"),
)


# Path tokens we intentionally cite in docs as forward-looking
# *examples* or placeholders.  They do not need to resolve on disk.
_PLACEHOLDER_PATH_TOKENS: frozenset[str] = frozenset({
    # SCHEMA.md flat-vs-nested layout illustration:
    "alphas/my_alpha.alpha.yaml",
    "alphas/my_alpha/my_alpha.alpha.yaml",
    # Workstream F-5 migration cookbook §11.5 worked example —
    # forward-looking placeholder filename for an operator's
    # research-grade alpha YAML carrying a stricter ``promotion:``
    # block.
    "alphas/my_research_alpha.alpha.yaml",
    # Prompt-7 mutation example (forward-looking
    # successor file the operator would create on a real mutation):
    "alphas/pofi_benign_midcap_v2/pofi_benign_midcap_v2.alpha.yaml",
    "alphas/_deprecated/pofi_benign_midcap_v1_v1.0.0.yaml",
    # Forward-looking research infrastructure path referenced as a
    # design pointer for the hypothesis status taxonomy.  Not yet
    # implemented; tracked separately:
    "src/feelies/research/hypothesis_status.py",
    # Workstream-D.2 retired this parity test alongside the
    # ``alphas/trade_cluster_drift/`` reference alpha.  The path is
    # intentionally cited from SCHEMA.md and the migration cookbook
    # so operators reading those docs can grep their own forks for
    # the now-defunct anchor.  See ``docs/migration/schema_1_0_to_1_1.md``
    # §"Workstream-D update" for the retirement note.
    "tests/determinism/test_legacy_alpha_parity.py",
})


# Match repo-relative paths inside backticks: `foo/bar.md`, `path/to/file.py`.
# NOTE: longest extensions (``mdc``, ``yaml``) listed *before* their
# substrings (``md``, ``yml``) so the regex engine prefers the longest
# match — otherwise ``platform-invariants.mdc`` is captured as
# ``…platform-invariants.md`` and the existence check spuriously fails.
_BACKTICK_PATH_RE = re.compile(
    r"`([a-zA-Z0-9_./\-]+/[a-zA-Z0-9_./\-]+\.(?:mdc|yaml|json|toml|cfg|ini|txt|md|py|yml))`"
)

# Match bare paths in narrative text outside backticks (rarer; we still
# accept them when the path component contains a slash and a known
# extension).
_BARE_PATH_RE = re.compile(
    r"(?<![\w/`])((?:src|tests|docs|alphas|grok|design_docs|\.cursor)/"
    r"[a-zA-Z0-9_./\-]+\.(?:mdc|yaml|toml|md|py|yml))"
)


def _scrape_paths(text: str) -> set[str]:
    matches: set[str] = set()
    for m in _BACKTICK_PATH_RE.finditer(text):
        matches.add(m.group(1))
    for m in _BARE_PATH_RE.finditer(text):
        matches.add(m.group(1))
    return matches


def _normalise(path_str: str) -> Path:
    """Return ``Path`` for a slash-separated repo-relative reference."""
    parts = [p for p in path_str.split("/") if p not in ("", ".")]
    return Path(*parts)


@pytest.mark.parametrize(
    "doc",
    _DOC_FILES + _DOC_EXISTENCE_ONLY,
    ids=str,
)
def test_doc_file_exists(doc: Path) -> None:
    assert doc.exists(), f"missing tracked documentation file: {doc}"


@pytest.mark.parametrize(
    "doc",
    _DOC_FILES + _SOURCE_FILES,
    ids=str,
)
def test_internal_path_references_resolve(doc: Path) -> None:
    """Every ``foo/bar.{md,py,…}`` reference in ``doc`` must resolve."""
    if not doc.exists():
        pytest.skip(f"{doc} not present (covered by sibling test)")
    text = doc.read_text(encoding="utf-8")
    cited = _scrape_paths(text)
    missing: list[str] = []
    for cite in sorted(cited):
        # Skip obvious examples of paths inside code-as-string contexts
        # like ``alphas/<alpha_id>/...`` placeholders.
        if "<" in cite or ">" in cite:
            continue
        # Skip well-known placeholder filenames embedded in templates.
        if cite.endswith(("template.alpha.yaml",)) and "_template" not in cite:
            continue
        # Skip whitelisted forward-looking / example placeholders.
        if cite in _PLACEHOLDER_PATH_TOKENS:
            continue
        target = _normalise(cite)
        if not target.exists():
            missing.append(cite)
    assert not missing, (
        f"{doc}: cites repo paths that do not resolve on disk: {missing}"
    )
