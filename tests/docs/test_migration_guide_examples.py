"""Smoke-tests for the embedded YAML examples in the migration guide.

The migration cookbook (``docs/migration/schema_1_0_to_1_1.md``) carries
fenced ``yaml`` blocks the operator copies verbatim into their own
alpha files.  This test pulls every fenced block out, parses it as
YAML, and applies cheap structural assertions:

* every block must be valid YAML (``yaml.safe_load`` does not raise);
* if a block carries a ``schema_version`` field, it must be ``"1.0"``
  or ``"1.1"`` (no typos like ``"1.10"`` or ``"1.1.0"``).  ``"1.0"`` is
  retained as a historical reference value: post-workstream-D.1 the
  loader rejects it, but the cookbook still cites it in "before"
  examples illustrating the migration;
* if a block carries a ``layer`` field, it must be one of the three
  normative layers.

We deliberately do **not** push every snippet through
``AlphaLoader.load_from_dict`` — many snippets are intentionally
*partial* (e.g. only the ``regime_gate:`` block, only the
``cost_arithmetic:`` block) and would fail a full load.  The three
layer-specific *templates* in ``alphas/_template/`` are the artifacts
that get loaded end-to-end (covered by ``test_layer_templates.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


_GUIDE = Path("docs/migration/schema_1_0_to_1_1.md")
_FENCE_RE = re.compile(r"^```yaml\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

_NORMATIVE_LAYERS = {"LEGACY_SIGNAL", "SIGNAL", "PORTFOLIO"}
_KNOWN_SCHEMAS = {"1.0", "1.1"}


def _yaml_blocks() -> list[tuple[int, str]]:
    """Return ``[(line_number, body), ...]`` for every fenced ``yaml`` block."""
    text = _GUIDE.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    for m in _FENCE_RE.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        out.append((line_no, m.group(1)))
    return out


def test_migration_guide_exists() -> None:
    assert _GUIDE.exists(), f"missing migration cookbook at {_GUIDE}"


def test_migration_guide_has_yaml_blocks() -> None:
    blocks = _yaml_blocks()
    assert blocks, "expected the migration cookbook to carry yaml examples"


@pytest.mark.parametrize(
    "block_idx",
    list(range(len(_yaml_blocks()))),
)
def test_migration_guide_yaml_block_parses(block_idx: int) -> None:
    """Each fenced ``yaml`` block must parse as YAML."""
    blocks = _yaml_blocks()
    line_no, body = blocks[block_idx]
    try:
        yaml.safe_load(body)
    except yaml.YAMLError as exc:
        pytest.fail(
            f"yaml block at {_GUIDE}:{line_no} failed to parse: {exc}"
        )


def test_migration_guide_schema_versions_are_known() -> None:
    """Any ``schema_version:`` value in the guide must be a known one."""
    for line_no, body in _yaml_blocks():
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError:
            continue  # parse failure surfaces in the per-block test
        if not isinstance(doc, dict):
            continue
        sv = doc.get("schema_version")
        if sv is None:
            continue
        assert str(sv) in _KNOWN_SCHEMAS, (
            f"yaml block at {_GUIDE}:{line_no} declares unknown "
            f"schema_version={sv!r}; allowed: {sorted(_KNOWN_SCHEMAS)}"
        )


def test_migration_guide_layers_are_normative() -> None:
    """Any ``layer:`` value in the guide must be one of the 3 layers."""
    for line_no, body in _yaml_blocks():
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        layer = doc.get("layer")
        if layer is None:
            continue
        assert str(layer) in _NORMATIVE_LAYERS, (
            f"yaml block at {_GUIDE}:{line_no} declares unknown "
            f"layer={layer!r}; allowed: {sorted(_NORMATIVE_LAYERS)}"
        )
