# v0.2 / v0.3 Acceptance Matrix

**Status:** reconstructed reference, created 2026-07-02.

`docs/acceptance/v02_v03_matrix.md` is cited by name from eight places in this
repository — `.cursor/skills/testing-validation/SKILL.md`, `pyproject.toml`,
and five files under `tests/acceptance/` (`test_reference_alpha_load_invariants.py`,
`test_mypy_strict_scope.py`, `__init__.py`, `test_strict_mode_default_true.py`,
`test_g16_rule_completeness.py`, `test_v02_no_trend_mechanism_parity.py`) —
but the file itself was never committed (confirmed via `git log --all
--diff-filter=D`: no deletion event either). Every one of those citations
points a future contributor here for the rationale behind a specific
acceptance row when a locked test fails; a broken link at that exact moment
is the worst time to discover it.

This file does not resurrect lost history it has no record of. It documents,
honestly, the specific rows other files in this repository cite by number,
with their **current, independently-verified** status as of 2026-07-02. The
acceptance tests themselves — not this file — remain the authoritative,
executable source of truth; treat this as a human-readable index into them.

## Rows cited elsewhere in the codebase

| Row | Subject | Cited by | Current status (verified 2026-07-02) |
|---|---|---|---|
| §18.3 #3 | mypy `--strict` clean on `src/feelies`, no per-module overrides | `pyproject.toml:77`, `tests/acceptance/test_mypy_strict_scope.py` | **Met.** `[tool.mypy] strict = true` (`pyproject.toml:74`); zero `[[tool.mypy.overrides]]` blocks weaken any `feelies.*` module (only third-party `ignore_missing_imports` entries exist). |
| gap-Z | Removal of the historical 8-module mypy override block (`bootstrap`, `execution.passive_limit_router`, `ingestion.massive_*`, `kernel.orchestrator`, `storage.disk_event_cache`, `storage.memory_trade_journal`) | `tests/acceptance/test_mypy_strict_scope.py` | **Closed.** Those modules were tightened in place rather than exempted; `test_no_strict_overrides_in_pyproject` locks the invariant going forward across all 14 of mypy's `--strict`-bundle flags (broadened 2026-07-02, audit P2 #8). |
| row 84 | `enforce_trend_mechanism` default flip to `True` (Workstream E), held until ≥3 reference alphas (one per non-stress family) shipped under strict mode | `tests/acceptance/test_strict_mode_default_true.py` | **Flipped.** `PlatformConfig.enforce_trend_mechanism` defaults to `True` (dataclass and YAML-parser defaults agree); the v0.2 baseline alpha (`sig_benign_midcap_v1`) still loads via the documented `enforce_trend_mechanism=False` escape hatch. |
| §20.12.2 #3 | G16 binding-rule count (`LayerValidator`'s mechanism-horizon-binding gate) | `tests/acceptance/test_g16_rule_completeness.py` | **10 rules** (`TestRule1Family` … `TestRule10SignatureBacked`); a rule added or removed without updating both `_EXPECTED_RULES` and this row fails `test_g16_rule_completeness.py` loudly. |
| §20.12.3 #2 | v0.2-baseline reference alpha (`sig_benign_midcap_v1`) bit-identical parity under the pre-Workstream-E code path | `tests/acceptance/test_v02_no_trend_mechanism_parity.py` | **Locked** — see that test's own `EXPECTED_*_HASH` constants for the current pinned value; any change requires a written justification in the same commit per that test's own failure message. |

## What this file is not

It is not a reconstruction of every row the original document may once have
enumerated — no such enumeration survives anywhere in this repository's
history to reconstruct from. If a future citation references a row not
listed above, add it here (with its current, independently-verified status)
rather than assuming a match against unwritten history.
