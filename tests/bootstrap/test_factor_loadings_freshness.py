"""Tests for the factor-loadings freshness check (audit P1-4).

When ``loadings.json`` embeds ``_meta.as_of_ns`` the staleness verdict is
computed from that content-addressable timestamp (reproducible) rather
than the filesystem mtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.bootstrap import StaleFactorLoadingsError, _enforce_factor_loadings_freshness
from feelies.core.clock import SimulatedClock
from feelies.core.platform_config import OperatingMode, PlatformConfig

_SESSION_OPEN_NS = 1_700_000_000_000_000_000
_UNIVERSE = ["AAPL", "MSFT"]
# Stand-in clock for tests where session_open_ns is set: the freshness
# reference comes from session_open_ns in that branch, so the clock's
# value is never read.
_UNUSED_CLOCK = SimulatedClock()


def _write_loadings(loadings_dir: Path, *, as_of_ns: int | None) -> None:
    loadings_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "AAPL": {"MKT": 0.5},
        "MSFT": {"MKT": 0.4},
    }
    if as_of_ns is not None:
        payload["_meta"] = {"as_of_ns": as_of_ns}
    (loadings_dir / "loadings.json").write_text(json.dumps(payload), encoding="utf-8")


def _config(
    loadings_dir: Path,
    *,
    max_age_seconds: float,
    mode: OperatingMode = OperatingMode.BACKTEST,
    session_open_ns: int | None = _SESSION_OPEN_NS,
) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=mode,
        account_equity=100_000.0,
        factor_loadings_dir=loadings_dir,
        factor_loadings_max_age_seconds=max_age_seconds,
        session_open_ns=session_open_ns,
    )


def test_embedded_as_of_within_window_passes(tmp_path: Path) -> None:
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS - 100 * 1_000_000_000)
    _enforce_factor_loadings_freshness(
        _config(loadings_dir, max_age_seconds=300), _UNIVERSE, clock=_UNUSED_CLOCK
    )


def test_embedded_as_of_too_old_raises(tmp_path: Path) -> None:
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS - 1000 * 1_000_000_000)
    with pytest.raises(StaleFactorLoadingsError):
        _enforce_factor_loadings_freshness(
            _config(loadings_dir, max_age_seconds=300), _UNIVERSE, clock=_UNUSED_CLOCK
        )


def test_embedded_as_of_verdict_is_independent_of_mtime(tmp_path: Path) -> None:
    # An ancient embedded as_of must fail even though the file was just
    # written (mtime ≈ now) — proving the verdict uses content, not mtime.
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=1)  # ~1970
    with pytest.raises(StaleFactorLoadingsError):
        _enforce_factor_loadings_freshness(
            _config(loadings_dir, max_age_seconds=10 * 365 * 24 * 3600),
            _UNIVERSE,
            clock=_UNUSED_CLOCK,
        )


def test_meta_block_is_not_treated_as_a_symbol(tmp_path: Path) -> None:
    # `_meta` is an extra key; the universe is still fully covered so the
    # missing-rows check must not fire.
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS)
    _enforce_factor_loadings_freshness(
        _config(loadings_dir, max_age_seconds=300), _UNIVERSE, clock=_UNUSED_CLOCK
    )


def test_missing_symbol_still_raises_with_meta(tmp_path: Path) -> None:
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS)
    with pytest.raises(StaleFactorLoadingsError):
        _enforce_factor_loadings_freshness(
            _config(loadings_dir, max_age_seconds=300),
            ["AAPL", "MSFT", "GOOG"],
            clock=_UNUSED_CLOCK,
        )


def test_backtest_without_session_open_ns_refuses_to_boot(tmp_path: Path) -> None:
    # Audit kernel-P1 fix: BACKTEST has no causal "now" without session_open_ns
    # (SimulatedClock reads 0 at this pre-replay point), so it must refuse
    # rather than silently pass or falsely fail against a fabricated reference.
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS)
    with pytest.raises(StaleFactorLoadingsError, match="session_open_ns is unset"):
        _enforce_factor_loadings_freshness(
            _config(loadings_dir, max_age_seconds=300, session_open_ns=None),
            _UNIVERSE,
            clock=SimulatedClock(),
        )


def test_paper_mode_without_session_open_ns_uses_injected_clock(tmp_path: Path) -> None:
    # PAPER/LIVE have no session_open_ns anchor in general, but a real wall
    # clock is a meaningful "now" for a live deployment — routed through the
    # injected Clock (Inv-10) rather than a raw time.time() call.
    loadings_dir = tmp_path / "loadings"
    as_of_ns = 1_700_000_000_000_000_000
    _write_loadings(loadings_dir, as_of_ns=as_of_ns)
    fresh_clock = SimulatedClock(start_ns=as_of_ns + 100 * 1_000_000_000)
    _enforce_factor_loadings_freshness(
        _config(
            loadings_dir,
            max_age_seconds=300,
            mode=OperatingMode.PAPER,
            session_open_ns=None,
        ),
        _UNIVERSE,
        clock=fresh_clock,
    )
    stale_clock = SimulatedClock(start_ns=as_of_ns + 1000 * 1_000_000_000)
    with pytest.raises(StaleFactorLoadingsError):
        _enforce_factor_loadings_freshness(
            _config(
                loadings_dir,
                max_age_seconds=300,
                mode=OperatingMode.PAPER,
                session_open_ns=None,
            ),
            _UNIVERSE,
            clock=stale_clock,
        )


def test_missing_session_open_ns_fails_closed_instead_of_reading_wall_clock(
    tmp_path: Path,
) -> None:
    """Composition audit 2026-07-02, P1 finding.

    Previously fell back to ``time.time()`` (self-documented as breaking
    Inv-5 bit-identical replay) when ``session_open_ns`` was unset; now
    raises rather than silently reading the wall clock, so the same
    historical config cannot pass or fail this gate depending on when it
    happens to be re-run.
    """
    loadings_dir = tmp_path / "loadings"
    _write_loadings(loadings_dir, as_of_ns=_SESSION_OPEN_NS)
    config = PlatformConfig(
        symbols=frozenset(_UNIVERSE),
        mode=OperatingMode.BACKTEST,
        account_equity=100_000.0,
        factor_loadings_dir=loadings_dir,
        factor_loadings_max_age_seconds=300,
        session_open_ns=None,
    )
    with pytest.raises(StaleFactorLoadingsError, match="session_open_ns"):
        _enforce_factor_loadings_freshness(config, _UNIVERSE)
