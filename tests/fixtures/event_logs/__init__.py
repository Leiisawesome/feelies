"""Synthetic event-log fixtures for Phase-2 determinism tests.

The fixtures here are committed JSONL files of NBBOQuote / Trade
events spanning multiple horizon boundaries.  They are produced by
:mod:`tests.fixtures.event_logs._generate` with ``PYTHONHASHSEED=0``
so re-baselining is reproducible.

Why a synthetic fixture (not the demo)?  The current ``--demo`` data
window in :mod:`scripts.run_backtest` is too short to cross even one
30-second horizon boundary.  Phase-2 parity tests need *many*
boundaries to lock Level-2 / Level-3 / Level-4 baselines, hence this
companion fixture (resolved risk in plan §7).
"""
