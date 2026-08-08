"""The RTH skip guard must be a *weekday* window, not a clock window.

Deliberately not marked ``paper_rth``: this tests the gate itself, so gating it
behind the gate would leave it unrun exactly when the gate is wrong.

The guard previously compared only the time of day.  At 09:45 on a Saturday --
inside 9:30-16:00 ET, market shut -- every ``paper_rth`` test ran against a live
feed that returned nothing and *failed* rather than skipping, which is a
6.5-hour false-failure window twice a week against an AGENTS.md that documents
``uv run pytest`` as green.  Found by running the suite on a Saturday after a
merge, not by reading the guard.
"""

from __future__ import annotations

from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from tests.paper.conftest import require_rth_window

_ET = ZoneInfo("America/New_York")


def _run_at(when: datetime) -> str | None:
    """Return the skip reason at *when*, or ``None`` if the guard lets tests run."""
    with mock.patch("tests.paper.conftest.datetime") as fake:
        fake.now.return_value = when
        try:
            require_rth_window()
        except BaseException as exc:  # pytest.skip raises Skipped (a BaseException)
            return str(getattr(exc, "msg", exc))
    return None


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported override must not decide this test's outcome."""
    monkeypatch.delenv("PAPER_RTH_FORCE", raising=False)
    monkeypatch.delenv("PAPER_RTH_EXTENDED", raising=False)


@pytest.mark.parametrize(
    ("label", "when"),
    [
        # Both fall inside 9:30-16:00 ET, so only a weekday check can catch them.
        ("saturday", datetime(2026, 8, 8, 9, 45, tzinfo=_ET)),
        ("sunday", datetime(2026, 8, 9, 12, 0, tzinfo=_ET)),
    ],
)
def test_weekend_skips_even_inside_the_clock_window(label: str, when: datetime) -> None:
    reason = _run_at(when)
    assert reason is not None, f"{label} inside the clock window must skip, not run"
    assert "not a trading day" in reason


@pytest.mark.parametrize(
    ("label", "when"),
    [
        ("monday open", datetime(2026, 8, 10, 9, 45, tzinfo=_ET)),
        ("friday close", datetime(2026, 8, 7, 15, 59, tzinfo=_ET)),
    ],
)
def test_weekday_rth_still_runs(label: str, when: datetime) -> None:
    """Guarding weekends must not cost the window it exists to open."""
    assert _run_at(when) is None, f"{label} is a trading session and must run"


def test_weekday_outside_rth_still_skips_on_the_clock() -> None:
    reason = _run_at(datetime(2026, 8, 10, 8, 0, tzinfo=_ET))
    assert reason is not None
    assert "Outside US RTH" in reason


def test_extended_window_is_also_weekday_only() -> None:
    """``PAPER_RTH_EXTENDED`` widens the hours, not the days.

    The extended branch had its own copy of the clock comparison and the same
    omission, so widening to 4:00-20:00 ET would otherwise have re-opened the
    weekend hole this closes.
    """
    with mock.patch.dict("os.environ", {"PAPER_RTH_EXTENDED": "1"}):
        weekend = _run_at(datetime(2026, 8, 8, 12, 0, tzinfo=_ET))
        weekday = _run_at(datetime(2026, 8, 10, 6, 0, tzinfo=_ET))
    assert weekend is not None and "not a trading day" in weekend
    assert weekday is None, "06:00 ET on a Monday is inside the extended window"


def test_force_override_still_wins_on_a_weekend() -> None:
    """The documented escape hatch must keep working, or nobody can test on a Sunday."""
    with mock.patch.dict("os.environ", {"PAPER_RTH_FORCE": "1"}):
        assert _run_at(datetime(2026, 8, 8, 9, 45, tzinfo=_ET)) is None
