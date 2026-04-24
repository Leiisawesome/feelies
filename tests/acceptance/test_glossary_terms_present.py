"""Mechanical proof that §18.2 #9 and §20.12.2 #6 / §20.13 are closed.

Both acceptance lines require specific glossary entries to be present
in ``.cursor/rules/platform-invariants.mdc``.  The text of those
entries can evolve freely; what cannot regress is the *presence* of
the bolded term itself.  This test asserts presence by grepping the
glossary file for the canonical Markdown row prefix
``| **<term>** |``.

If a future refactor renames a term, this test must be updated in
the same PR — that is the desired discipline (silent renames break
external references and forensics tooling).
"""

from __future__ import annotations

from pathlib import Path

import pytest


_INVARIANTS = Path(".cursor/rules/platform-invariants.mdc")


# §18.2 #9 — v0.2 glossary additions
_V02_TERMS: tuple[str, ...] = (
    "feature",
    "sensor",
    "horizon",
    "regime",
)


# §20.12.2 #6 / §20.13 — v0.3 glossary additions
_V03_TERMS: tuple[str, ...] = (
    "trend mechanism",
    "hazard spike",
    "decay weighting",
    "mechanism concentration",
)


def _glossary_text() -> str:
    assert _INVARIANTS.exists(), (
        f"platform-invariants.mdc missing at {_INVARIANTS}; "
        "the glossary anchor for §18.2 #9 / §20.12.2 #6 cannot be verified."
    )
    return _INVARIANTS.read_text(encoding="utf-8")


@pytest.mark.parametrize("term", _V02_TERMS)
def test_v02_glossary_term_present(term: str) -> None:
    text = _glossary_text()
    needle = f"| **{term}** |"
    assert needle in text, (
        f"v0.2 glossary entry '{needle}' not found in {_INVARIANTS}.  "
        "§18.2 #9 requires the four v0.2 terms (feature / sensor / "
        "horizon / regime) to be defined.  Update the glossary or "
        "this test in the same PR."
    )


@pytest.mark.parametrize("term", _V03_TERMS)
def test_v03_glossary_term_present(term: str) -> None:
    text = _glossary_text()
    needle = f"| **{term}** |"
    assert needle in text, (
        f"v0.3 glossary entry '{needle}' not found in {_INVARIANTS}.  "
        "§20.12.2 #6 / §20.13 require the four v0.3 terms (trend "
        "mechanism / hazard spike / decay weighting / mechanism "
        "concentration) to be defined.  Update the glossary or this "
        "test in the same PR."
    )
