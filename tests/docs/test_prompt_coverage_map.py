"""Audit-prompt coverage-map staleness guard.

Every module under ``src/feelies/`` must have exactly one owning audit
prompt in ``docs/prompts/`` (the owner/touchpoint rule documented in
``docs/prompts/README.md`` § Conventions).  The G-1…G-7
position-management workstream (2026-06-08…10) demonstrated the failure
mode this test exists to prevent: ~15 commits of capital-path code
(``execution/portfolio_netter.py``, ``execution/position_manager.py``,
``risk/edge_weighted_sizer.py``, ``portfolio/lot_ledger.py``, the G-6
session flatten) landed with **no prompt owner** because nothing tied
"new module" to "update the coverage map".

Mechanism
---------
* ``_PACKAGE_OWNERS`` maps each top-level package under ``src/feelies``
  to its owning audit prompt.  A value of ``None`` marks a
  **split-ownership package**: every module in it must be explicitly
  listed in ``_FILE_OWNERS`` so that adding a new module forces a
  conscious ownership decision (this is exactly where the 2026-06
  drift happened).
* Wholly-owned packages inherit their owner, so e.g. a new sensor in
  ``sensors/impl/`` needs no edit here (the sensor prompt scopes the
  package with a glob).
* ``__init__.py`` files are exempt (no audit-relevant logic by
  convention).

When this test fails on your PR: add the new module to
``_FILE_OWNERS`` (or ``_PACKAGE_OWNERS`` for a new package) **and** to
the coverage map in ``docs/prompts/README.md``, assigning the audit
prompt that should deep-dive the file.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(".").resolve()
_SRC_ROOT = Path("src/feelies")
_PROMPTS_DIR = Path("docs/prompts")


# Top-level package → owning audit prompt (stem, i.e. filename without
# ``.md``).  ``None`` ⇒ split-ownership package: every module must be
# explicitly listed in ``_FILE_OWNERS``.
_PACKAGE_OWNERS: dict[str, str | None] = {
    "ingestion": "audit_data_ingestion",
    "storage": "audit_data_ingestion",  # overrides: trade journals
    "sensors": "audit_sensor",
    "features": "audit_sensor",
    "services": "audit_regime",
    "signals": None,  # split: regime gate vs horizon engine
    "alpha": None,  # split 5 ways — see README coverage map
    "composition": "audit_composition",
    "portfolio": None,  # split: composition vs position_management
    "risk": "audit_risk_engine",  # overrides: sizers
    "execution": None,  # split 3 ways — fills / live / position_management
    "broker": "audit_live_execution",
    "forensics": "audit_forensics",
    "research": "audit_research_validation",
    "kernel": "audit_kernel",
    "bus": "audit_kernel",
    "core": "audit_core_clock_config",
    "monitoring": "audit_monitoring_safety",
    "harness": "audit_harness_cli",
    "cli": None,  # split: backtest vs promote
}

# Module path (relative to ``src/feelies``) → owning audit prompt.
# Required for every non-``__init__`` module of a split package; allowed
# as an override inside a wholly-owned package.
_FILE_OWNERS: dict[str, str] = {
    # ── root-level modules ──────────────────────────────────────────
    "bootstrap.py": "audit_kernel",
    "__main__.py": "audit_kernel",
    # ── signals/ ────────────────────────────────────────────────────
    "signals/regime_gate.py": "audit_regime",
    "signals/horizon_engine.py": "audit_signal_alpha",
    "signals/horizon_protocol.py": "audit_signal_alpha",
    # ── alpha/ ──────────────────────────────────────────────────────
    "alpha/lifecycle.py": "audit_alpha_lifecycle",
    "alpha/promotion_ledger.py": "audit_alpha_lifecycle",
    "alpha/promotion_evidence.py": "audit_alpha_lifecycle",
    "alpha/registry.py": "audit_alpha_lifecycle",
    "alpha/loader.py": "audit_alpha_lifecycle",
    "alpha/validation.py": "audit_alpha_lifecycle",
    "alpha/discovery.py": "audit_alpha_lifecycle",
    "alpha/layer_validator.py": "audit_alpha_lifecycle",
    "alpha/module.py": "audit_alpha_lifecycle",
    "alpha/signal_layer_module.py": "audit_alpha_lifecycle",
    "alpha/cost_arithmetic.py": "audit_signal_alpha",
    "alpha/arbitration.py": "audit_signal_alpha",
    "alpha/aggregation.py": "audit_signal_alpha",
    "alpha/portfolio_layer_module.py": "audit_composition",
    "alpha/intent_set.py": "audit_composition",
    "alpha/fill_attribution.py": "audit_forensics",
    "alpha/risk_wrapper.py": "audit_risk_engine",
    # ── portfolio/ ──────────────────────────────────────────────────
    "portfolio/cross_sectional_tracker.py": "audit_composition",
    "portfolio/position_store.py": "audit_position_management",
    "portfolio/memory_position_store.py": "audit_position_management",
    "portfolio/strategy_position_store.py": "audit_position_management",
    "portfolio/lot_ledger.py": "audit_position_management",
    # ── storage/ overrides (PnL fill journal) ───────────────────────
    "storage/trade_journal.py": "audit_position_management",
    "storage/memory_trade_journal.py": "audit_position_management",
    # ── risk/ overrides (sizing economics) ──────────────────────────
    "risk/position_sizer.py": "audit_position_management",
    "risk/edge_weighted_sizer.py": "audit_position_management",
    # ── execution/ ──────────────────────────────────────────────────
    "execution/intent.py": "audit_position_management",
    "execution/position_manager.py": "audit_position_management",
    "execution/portfolio_netter.py": "audit_position_management",
    "execution/live_router.py": "audit_live_execution",
    "execution/paper_backend.py": "audit_live_execution",
    "execution/order_state.py": "audit_live_execution",
    "execution/trading_session.py": "audit_live_execution",
    "execution/backend.py": "audit_execution_fills",
    "execution/backtest_backend.py": "audit_execution_fills",
    "execution/backtest_router.py": "audit_execution_fills",
    "execution/passive_limit_router.py": "audit_execution_fills",
    "execution/min_cost_policy.py": "audit_execution_fills",
    "execution/market_fill.py": "audit_execution_fills",
    "execution/_fill_helpers.py": "audit_execution_fills",
    "execution/moc_fill.py": "audit_execution_fills",
    "execution/moc_session.py": "audit_execution_fills",
    "execution/cost_model.py": "audit_execution_fills",
    "execution/tick_size.py": "audit_execution_fills",
    "execution/regulatory/borrow_availability.py": "audit_execution_fills",
    "execution/regulatory/pdt_constraint.py": "audit_execution_fills",
    "execution/realism_profile.py": "audit_execution_fills",
    # ── cli/ ────────────────────────────────────────────────────────
    "cli/backtest.py": "audit_harness_cli",
    "cli/env.py": "audit_harness_cli",
    "cli/main.py": "audit_harness_cli",
    "cli/__main__.py": "audit_harness_cli",
    "cli/promote.py": "audit_alpha_lifecycle",
}


def _source_modules() -> list[Path]:
    """All audit-relevant modules, relative to ``src/feelies``."""
    return sorted(
        p.relative_to(_SRC_ROOT)
        for p in _SRC_ROOT.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )


def _resolve_owner(rel: Path) -> str | None:
    key = rel.as_posix()
    if key in _FILE_OWNERS:
        return _FILE_OWNERS[key]
    if len(rel.parts) == 1:
        return None  # root module without an explicit entry
    return _PACKAGE_OWNERS.get(rel.parts[0])


def test_every_module_has_an_owning_audit() -> None:
    """New modules must be assigned an owner (the drift guard)."""
    unowned = [rel.as_posix() for rel in _source_modules() if _resolve_owner(rel) is None]
    assert not unowned, (
        "modules with no owning audit prompt — add each to _FILE_OWNERS (or "
        "_PACKAGE_OWNERS for a new package) AND to the coverage map in "
        f"docs/prompts/README.md: {unowned}"
    )


def test_every_referenced_prompt_exists() -> None:
    owners = {v for v in _PACKAGE_OWNERS.values() if v is not None}
    owners.update(_FILE_OWNERS.values())
    missing = sorted(owner for owner in owners if not (_PROMPTS_DIR / f"{owner}.md").exists())
    assert not missing, f"owners referencing nonexistent prompt files: {missing}"


def test_no_stale_file_entries() -> None:
    """Renamed/deleted modules must be pruned from the map."""
    stale = sorted(key for key in _FILE_OWNERS if not (_SRC_ROOT / key).exists())
    assert not stale, f"_FILE_OWNERS entries with no module on disk: {stale}"


def test_no_stale_package_entries() -> None:
    stale = sorted(pkg for pkg in _PACKAGE_OWNERS if not (_SRC_ROOT / pkg).is_dir())
    assert not stale, f"_PACKAGE_OWNERS entries with no package on disk: {stale}"
