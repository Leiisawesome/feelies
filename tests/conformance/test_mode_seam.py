"""S7 — mode branches only at the composition root and the declared seam.

Promotes ``tools.arch.coupling.mode_branches``.  Composition-root
backend construction (``bootstrap.py::_create_backend``) is legitimate;
in-engine ``OperatingMode`` branches are G26.  The root is an explicit
allowlist, not a hard-coded ``{execution, broker}`` set.

S-28a made the OperatingMode-token allowlist function-scoped.  S-28b
extends the same test to every spelling of a mode-dependent decision
(enum, ``.mode.name``, ``mode.name``, ``"BACKTEST"``/``"PAPER"`` string
compares) so a rewrite cannot hide from the guard.

Eight composition decisions in bootstrap are legal where they stand and
are permitted by name, not by silence:

* ``build_platform`` PAPER ``ib_port==4001`` operator warning
* ``build_platform`` BACKTEST ingest-terminal-health admit
* ``build_platform`` PAPER sizer-tilt operator warning
* ``build_platform`` PAPER edge-calibration operator warning
* ``_ensure_session_open_ns_for_paper`` (session-open auto-anchor)
* ``_create_sensor_layer`` H10 ``session_open_ns`` admit
* ``_enforce_ex_date_replay_guard`` (BACKTEST-only replay guard)
* ``_enforce_factor_loadings_freshness`` (clock-vs-refuse freshness)

Two further sites were targets that are legal on closer reading
(moving them into ``_create_backend`` requires a ``_BackendBundle``
field or an optional ``clock`` return — a signature change, which is
a stop):

* ``_select_clock`` (clock column of the mode table)
* ``build_platform`` PAPER auto-construct of the shared ``MassiveNormalizer``

They compose the platform; they do not select an ``ExecutionBackend``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from tools.arch.coupling import mode_branches

_ROOT = Path(__file__).resolve().parents[2]
_SEAM_PREFIXES = ("src/feelies/execution/", "src/feelies/broker/")
_COMPOSITION_ROOT = "src/feelies/bootstrap.py"
_COMPOSITION_ROOT_FN = "_create_backend"
_BOOTSTRAP = _ROOT / "src" / "feelies" / "bootstrap.py"

# Helpers whose only mode branch is a composition-time admit, clock
# selection, or freshness policy.  Not ``_create_sensor_layer`` (mixed:
# H10 is legal; emit_reading_metrics was a target and is gone).
_LEGAL_COMPOSITION_FNS = frozenset(
    {
        "_ensure_session_open_ns_for_paper",
        "_enforce_ex_date_replay_guard",
        "_enforce_factor_loadings_freshness",
        "_select_clock",
    }
)

# Unique substrings of the If-test that identify the legal
# build_platform composition decisions.  A match is a permit, not a skip.
_LEGAL_BUILD_PLATFORM_MARKERS = (
    "ib_port == 4001",
    "backtest_enforce_ingest_terminal_health",
    "sizer_tilt_drive",
    "resolved_edge_factors",
    "normalizer is None",
)

_H10_ADMIT = "H10: session_open_ns must be set"


def _innermost_function(path: str, line: int) -> str | None:
    source = (_ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    owning: tuple[int, int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= line <= end:
            span = end - node.lineno
            if owning is None or span < (owning[1] - owning[0]):
                owning = (node.lineno, end, node.name)
    return None if owning is None else owning[2]


def _allowed(path: str, line: int) -> bool:
    if path.startswith(_SEAM_PREFIXES):
        return True
    return (
        path == _COMPOSITION_ROOT
        and _innermost_function(path, line) == _COMPOSITION_ROOT_FN
    )


def _text_is_mode_dependent(text: str) -> bool:
    if "OperatingMode" in text:
        return True
    if ".mode.name" in text:
        return True
    if re.search(r"(?<![.\w])mode\.name\b", text):
        return True
    has_mode_token = re.search(r"\bmode\b", text) is not None
    has_mode_literal = any(
        lit in text for lit in ('"BACKTEST"', "'BACKTEST'", '"PAPER"', "'PAPER'")
    )
    return has_mode_token and has_mode_literal


def _bootstrap_mode_hits() -> list[dict[str, Any]]:
    """Mode-dependent If / IfExp / standalone Compare in bootstrap.py."""
    source = _BOOTSTRAP.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=_COMPOSITION_ROOT)
    covered: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)):
            for child in ast.walk(node.test):
                if isinstance(child, ast.Compare):
                    covered.add(id(child))
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        text: str
        if isinstance(node, (ast.If, ast.IfExp)):
            text = ast.unparse(node.test)
        elif isinstance(node, ast.Compare) and id(node) not in covered:
            text = ast.unparse(node)
        else:
            continue
        if not _text_is_mode_dependent(text):
            continue
        fn = _innermost_function(_COMPOSITION_ROOT, node.lineno)
        hits.append(
            {
                "line": node.lineno,
                "function": fn,
                "test": text,
                "node": node,
            }
        )
    hits.sort(key=lambda h: int(h["line"]))
    return hits


def _is_legal_composition(hit: dict[str, Any]) -> bool:
    fn = hit["function"]
    if fn == _COMPOSITION_ROOT_FN:
        return True
    if fn in _LEGAL_COMPOSITION_FNS:
        return True
    text = hit["test"]
    if fn == "build_platform" and any(m in text for m in _LEGAL_BUILD_PLATFORM_MARKERS):
        return True
    node = hit["node"]
    if fn == "_create_sensor_layer" and isinstance(node, ast.If):
        body = "\n".join(ast.unparse(stmt) for stmt in node.body)
        return _H10_ADMIT in body
    return False


def test_mode_branches_only_at_composition_root() -> None:
    hits = [h for h in mode_branches() if h["kind"] == "operating_mode"]
    assert hits, "scanner found no OperatingMode branch — the seam check is vacuous"
    outside = [h for h in hits if not _allowed(h["path"], h["line"])]
    assert not outside, (
        f"{len(outside)} OperatingMode branch(es) outside "
        f"{_COMPOSITION_ROOT}::{_COMPOSITION_ROOT_FN} and mode seam: "
        + "; ".join(f"{h['path']}:{h['line']} {h['test']}" for h in outside)
    )

    decisions = _bootstrap_mode_hits()
    assert decisions, (
        "scanner found no mode-dependent decision in bootstrap.py — "
        "the any-spelling seam check is vacuous"
    )
    illegal = [h for h in decisions if not _is_legal_composition(h)]
    assert not illegal, (
        f"{len(illegal)} mode-dependent branch(es) outside "
        f"{_COMPOSITION_ROOT}::{_COMPOSITION_ROOT_FN} and the eight "
        f"declared legal composition decisions: "
        + "; ".join(
            f"{_COMPOSITION_ROOT}:{h['line']} {h['function']} {h['test']}"
            for h in illegal
        )
    )
