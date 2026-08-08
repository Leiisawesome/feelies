"""``bt_multialpha.yaml`` must actually put two alphas on one symbol.

The config is the platform's only cross-alpha harness: arbitration collisions,
standing-signal overlap, and the portfolio-netting shadow all need two *live
standing targets* on the same symbol before they exercise anything.

It had silently stopped doing that.  Only ``sig_benign_midcap_v1`` emitted on the
cached APP sessions, so every measurement taken through this config — including
the netting divergence count that was supposed to decide whether
``enable_portfolio_netting`` can be flipped — was reading zero from a harness
with nothing to disagree about.  Nothing failed; the config just quietly became
single-alpha.

That is the shape of gap this suite keeps finding, so it is pinned here rather
than left to inspection.
"""

from __future__ import annotations

import collections
from dataclasses import replace
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote, Signal
from feelies.core.platform_config import PlatformConfig
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "bt_multialpha.yaml"
_SYMBOL = "APP"
_DATE = "2026-03-26"


def test_config_declares_more_than_one_alpha() -> None:
    """Data-free floor: a collision harness needs collidable alphas.

    Cheap and always runs, but deliberately not the whole test — the real
    regression was an alpha that loaded fine and never fired.
    """
    config = PlatformConfig.from_yaml(str(_CONFIG))
    assert len(config.alpha_specs) >= 2, (
        f"{_CONFIG.name} declares {len(config.alpha_specs)} alpha(s); "
        "a cross-alpha harness needs at least two"
    )


@pytest.mark.functional
def test_two_alphas_hold_live_targets_on_one_symbol() -> None:
    """The property that makes the harness a harness.

    Asserts emission from two distinct alphas *and* that their standing targets
    are simultaneously live on the same symbol — the precondition for cross-alpha
    arbitration and for the portfolio netter to have anything to net.
    """
    try:
        event_log, _ingest, _meta = load_event_log_from_disk_cache([_SYMBOL], _DATE, _DATE)
    except CacheReplayError as exc:
        pytest.skip(
            f"Disk cache miss for {_SYMBOL}/{_DATE} — populate with:\n"
            f"  uv run python scripts/run_backtest.py --config {_CONFIG} "
            f"--symbol {_SYMBOL} --date {_DATE}\n  ({exc})"
        )

    # ``scripts/run_backtest.py`` populates terminal ingest health after its own
    # ingest step; this test replays a pre-populated cache, so declare the symbol
    # healthy rather than re-run ingest.
    config = replace(
        PlatformConfig.from_yaml(str(_CONFIG)),
        ingest_terminal_symbol_health=((_SYMBOL, "HEALTHY"),),
    )
    # A sink makes the orchestrator maintain standing targets; without one the
    # netting book is never populated (see Orchestrator._record_net_shadow).
    orchestrator, _ = build_platform(config, event_log=event_log, net_shadow_sink=[])

    emitters: collections.Counter[str] = collections.Counter()
    orchestrator._bus.subscribe(  # noqa: SLF001
        Signal,
        lambda s: emitters.update([s.strategy_id]),
    )

    contended_ticks = 0
    book = orchestrator._desired_target_book  # noqa: SLF001

    def _on_quote(quote: NBBOQuote) -> None:
        nonlocal contended_ticks
        if len(book.live_targets(quote.symbol, int(quote.timestamp_ns))) >= 2:
            contended_ticks += 1

    orchestrator._bus.subscribe(NBBOQuote, _on_quote)  # noqa: SLF001

    orchestrator.boot(config)
    orchestrator.run_backtest()

    real = {sid: n for sid, n in emitters.items() if not sid.startswith("__")}
    assert len(real) >= 2, (
        f"only {len(real)} alpha(s) emitted on {_SYMBOL}/{_DATE}: {real}. "
        "The harness is single-alpha again — arbitration and the netting shadow "
        "have nothing to exercise."
    )
    assert contended_ticks > 0, (
        "no tick had two live standing targets on one symbol; alphas emitted but "
        "never overlapped, so cross-alpha behaviour is still untested"
    )
