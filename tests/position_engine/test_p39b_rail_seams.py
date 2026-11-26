"""Rail seams for S, D and the quote class (D-203). Not a battery member."""

from __future__ import annotations

import dataclasses

import pytest

from feelies.core.events import MarkRailUpdate, NBBOQuote
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import PlatformConfig
from feelies.core.quote_quality import QuoteQuality
from tests.position_engine.mutants import (
    AgeResetRail,
    LazyTrimRail,
    MidRail,
    QuietAbsentRail,
    RawAbsentRail,
)
from tests.position_engine.reference.rail import ReferenceRail
from tests.position_engine.scenarios import _APP_CONFIG, _seams
from tests.position_engine.tapes import make_tape

_RAILS = (
    ReferenceRail,
    MidRail,
    LazyTrimRail,
    AgeResetRail,
    RawAbsentRail,
    QuietAbsentRail,
)


def _generator() -> SequenceGenerator:
    return SequenceGenerator(stream="mark_rail", thread_safe=False)


class _RecordingRail(ReferenceRail):
    """Records the quality argument the seam forwards (T3)."""

    def __init__(self, sequence_generator: SequenceGenerator) -> None:
        super().__init__(sequence_generator)
        self.qualities: list[object] = []

    def on_quote(self, quote: NBBOQuote, *, quality: object | None = None) -> MarkRailUpdate:
        self.qualities.append(quality)
        return super().on_quote(quote)


@dataclasses.dataclass(frozen=True, kw_only=True)
class _StandIn:
    position_rail_dwell_ns: int = 0
    position_rail_slippage_ticks: int = 0


def test_t1_constructor_args_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEELIES_RAIL_DWELL_NS", raising=False)
    monkeypatch.delenv("FEELIES_RAIL_SLIPPAGE_TICKS", raising=False)
    tape = make_tape(seed=11, n=4)
    ignored = ReferenceRail(_generator(), slippage_ticks=7, dwell_ns=123)
    assert ignored.dwell_ns == 0
    assert ignored.slippage_ticks == 0
    plain = ReferenceRail(_generator())
    assert [ignored.on_quote(quote) for quote in tape] == [plain.on_quote(quote) for quote in tape]


@pytest.mark.parametrize("rail_cls", _RAILS, ids=[cls.__name__ for cls in _RAILS])
def test_t2_on_quote_quality_is_ignored(rail_cls: type) -> None:
    tape = make_tape(seed=11, n=4)
    plain = rail_cls(_generator())
    marked = rail_cls(_generator())
    assert [marked.on_quote(quote, quality=QuoteQuality.VALID) for quote in tape] == [
        plain.on_quote(quote) for quote in tape
    ]


def test_t3_wrapper_forwards_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FEELIES_RAIL",
        "tests.position_engine.test_p39b_rail_seams._RecordingRail",
    )
    quote = make_tape(seed=11, n=1)[0]

    def wrapper(original, quote):
        return original(quote)

    import feelies.portfolio.mark_rail as rail_mod

    with _seams(None, wrapper, True):
        rail = rail_mod.MarkRail(_generator())
        rail.on_quote(quote, quality=QuoteQuality.CROSSED)
    assert rail.qualities == [QuoteQuality.CROSSED]


def test_t4_app_config_unchanged_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEELIES_RAIL_DWELL_NS", raising=False)
    monkeypatch.delenv("FEELIES_RAIL_SLIPPAGE_TICKS", raising=False)
    from tests.position_engine.scenarios import _copy_rail_env

    config = PlatformConfig.from_yaml(_APP_CONFIG)
    assert _copy_rail_env(config) == config


@pytest.mark.parametrize(
    ("dwell", "slip", "expected_dwell", "expected_slip"),
    [
        ("2000000000", "4", 2000000000, 4),
        (None, None, 0, 0),
    ],
)
def test_t5_stand_in_copies_env(
    monkeypatch: pytest.MonkeyPatch,
    dwell: str | None,
    slip: str | None,
    expected_dwell: int,
    expected_slip: int,
) -> None:
    if dwell is None:
        monkeypatch.delenv("FEELIES_RAIL_DWELL_NS", raising=False)
    else:
        monkeypatch.setenv("FEELIES_RAIL_DWELL_NS", dwell)
    if slip is None:
        monkeypatch.delenv("FEELIES_RAIL_SLIPPAGE_TICKS", raising=False)
    else:
        monkeypatch.setenv("FEELIES_RAIL_SLIPPAGE_TICKS", slip)
    from tests.position_engine.scenarios import _copy_rail_env

    got = _copy_rail_env(_StandIn())
    assert got.position_rail_dwell_ns == expected_dwell
    assert got.position_rail_slippage_ticks == expected_slip
