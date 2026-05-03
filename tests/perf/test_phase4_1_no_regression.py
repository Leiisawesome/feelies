"""Phase-4.1 perf gate — decay-weighting end-to-end overhead ≤ 5%.

Plan §p4f_perf_phase4_1
-----------------------

Phase-4.1 added inverse-staleness decay weighting to
:class:`feelies.composition.cross_sectional.CrossSectionalRanker`.
Activated by ``decay_weighting_enabled=True`` in the alpha
manifest's ``parameters:`` block, the ranker multiplies each raw
score by ``exp(-Δt / hl)`` before cross-sectional standardization.

The decay branch sits on the per-boundary hot path of every
PORTFOLIO alpha that opts in.  The plan budget is **≤5% wall-clock
regression on a full backtest** when comparing the *same*
PORTFOLIO alpha with decay OFF vs decay ON — measured end-to-end
so the per-tick amortisation is explicit (the ranker is one of
many handlers on the bus).  Isolated per-call timings show a
larger ranker-only ratio because the extra ``math.exp`` is a
sizeable fraction of the ranker's tiny absolute cost; what matters
for the platform is that the decay branch contributes negligibly
to the total tick-to-trade budget.

Mirrors :mod:`test_phase4_no_regression` for subprocess isolation
+ best-of-N selection.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Sequence

import pytest

from tests.perf._pinned_baseline import load_pinned_baseline


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIGNAL_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_benign_midcap_v1"
    / "pofi_benign_midcap_v1.alpha.yaml"
)
_PORTFOLIO_ALPHA_BASELINE = (
    _REPO_ROOT / "alphas" / "pofi_xsect_v1"
    / "pofi_xsect_v1.alpha.yaml"
)
_PORTFOLIO_ALPHA_WITH_DECAY = (
    _REPO_ROOT / "alphas" / "pofi_xsect_v1"
    / "pofi_xsect_v1.with_decay.alpha.yaml"
)
_FACTOR_LOADINGS_DIR = _REPO_ROOT / "storage" / "reference" / "factor_loadings"
_SECTOR_MAP_PATH = (
    _REPO_ROOT / "storage" / "reference" / "sector_map" / "sector_map.json"
)


REPEATS: int = 5
MAX_OVERHEAD_FACTOR: float = 1.05  # plan §p4f_perf_phase4_1
MAX_RUN_WALL_SECONDS: float = 90.0
MIN_BASELINE_FOR_RATIO: float = 1.0


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CI_BENCHMARK") != "1",
        reason=(
            "CI_BENCHMARK env var not set; skipping Phase-4.1 perf gate"
        ),
    ),
    pytest.mark.slow,
]


_HARNESS_TEMPLATE = textwrap.dedent("""\
    import time
    import sys
    from decimal import Decimal
    from pathlib import Path
    import random

    sys.path.insert(0, str(Path({repo_root!r}) / 'src'))
    sys.path.insert(0, str(Path({repo_root!r})))

    from feelies.bootstrap import build_platform
    from feelies.core.events import NBBOQuote, Trade
    from feelies.core.platform_config import OperatingMode, PlatformConfig
    from feelies.sensors.impl.micro_price import MicroPriceSensor
    from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
    from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
    from feelies.sensors.spec import SensorSpec
    from feelies.storage.memory_event_log import InMemoryEventLog
    from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

    SENSOR_SPECS = (
        SensorSpec(
            sensor_id='ofi_ewma', sensor_version='1.0.0',
            cls=OFIEwmaSensor, params={{'alpha': 0.1, 'warm_after': 5}},
            subscribes_to=(NBBOQuote,),
        ),
        SensorSpec(
            sensor_id='micro_price', sensor_version='1.0.0',
            cls=MicroPriceSensor, params={{}}, subscribes_to=(NBBOQuote,),
        ),
        SensorSpec(
            sensor_id='spread_z_30d', sensor_version='1.0.0',
            cls=SpreadZScoreSensor, params={{}}, subscribes_to=(NBBOQuote,),
        ),
    )

    UNIVERSE = (
        'AAPL', 'AMZN', 'BAC', 'CVX', 'GOOG',
        'JPM', 'META', 'MSFT', 'NVDA', 'XOM',
    )
    QUOTES_PER_SYMBOL = 720
    QUOTE_CADENCE_NS = 100_000_000
    PRICES = {{
        'AAPL': 18000, 'AMZN': 13000, 'BAC':  3000, 'CVX': 14000,
        'GOOG': 14000, 'JPM': 14500, 'META': 31000, 'MSFT': 37000,
        'NVDA': 45000, 'XOM':  10500,
    }}

    events = []
    for sym_idx, symbol in enumerate(UNIVERSE):
        rng = random.Random(42 * 100 + sym_idx)
        last_mid = PRICES[symbol]
        for i in range(QUOTES_PER_SYMBOL):
            ts_ns = SESSION_OPEN_NS + i * QUOTE_CADENCE_NS
            last_mid += rng.choice((-1, 0, 0, 0, 1))
            events.append((ts_ns, sym_idx, NBBOQuote(
                timestamp_ns=ts_ns,
                sequence=sym_idx * QUOTES_PER_SYMBOL + i,
                correlation_id=f'q-{{symbol}}-{{i}}',
                source_layer='INGESTION', symbol=symbol,
                bid=Decimal(last_mid) / Decimal(100),
                ask=Decimal(last_mid + 1) / Decimal(100),
                bid_size=200, ask_size=200,
                exchange_timestamp_ns=ts_ns,
                bid_exchange=11, ask_exchange=11, tape=3,
            )))
            if i % 7 == 0 and i > 0:
                events.append((ts_ns + 1, sym_idx, Trade(
                    timestamp_ns=ts_ns + 1,
                    sequence=sym_idx * QUOTES_PER_SYMBOL * 2 + i,
                    correlation_id=f't-{{symbol}}-{{i}}',
                    source_layer='INGESTION', symbol=symbol,
                    price=Decimal(last_mid + 1) / Decimal(100),
                    size=100, exchange=11,
                    trade_id=f'tr-{{symbol}}-{{i:08d}}',
                    exchange_timestamp_ns=ts_ns + 1, tape=3,
                )))
    events.sort(key=lambda r: (r[0], r[1]))
    typed_events = [e for _, _, e in events]

    alpha_specs = [Path(p) for p in {alpha_specs!r}]

    config = PlatformConfig(
        symbols=frozenset(UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=alpha_specs,
        regime_engine='hmm_3state_fractional',
        sensor_specs=SENSOR_SPECS,
        horizons_seconds=frozenset({{30, 120, 300}}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        factor_loadings_dir=Path({factor_loadings_dir!r}),
        sector_map_path=Path({sector_map_path!r}),
        enforce_trend_mechanism=False,
    )

    log = InMemoryEventLog()
    log.append_batch(typed_events)
    orchestrator, _ = build_platform(config, event_log=log)
    orchestrator.boot(config)

    start = time.perf_counter()
    orchestrator.run_backtest()
    elapsed = time.perf_counter() - start
    print(f'PERF_ELAPSED_SECONDS={{elapsed:.6f}}')
""")


def _run_subprocess(*, alpha_specs: Sequence[Path]) -> float:
    harness = _HARNESS_TEMPLATE.format(
        repo_root=str(_REPO_ROOT),
        alpha_specs=[str(p) for p in alpha_specs],
        factor_loadings_dir=str(_FACTOR_LOADINGS_DIR),
        sector_map_path=str(_SECTOR_MAP_PATH),
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    wall_start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", harness],
        cwd=str(_REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=MAX_RUN_WALL_SECONDS * 2,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    wall_elapsed = time.perf_counter() - wall_start
    assert proc.returncode == 0, (
        f"perf harness crashed (rc={proc.returncode}, "
        f"wall_elapsed={wall_elapsed:.2f}s)\n"
        f"--- stderr (last 60 lines) ---\n"
        + "\n".join(proc.stderr.splitlines()[-60:])
    )
    for line in proc.stdout.splitlines():
        if line.startswith("PERF_ELAPSED_SECONDS="):
            return float(line.split("=", 1)[1])
    raise AssertionError(
        f"PERF_ELAPSED_SECONDS marker missing:\n{proc.stdout[-2000:]}"
    )


def _best_of(samples: Sequence[float]) -> float:
    return min(samples)


def test_phase4_1_decay_overhead_within_budget() -> None:
    """Decay-ON PORTFOLIO must complete within 1.05× the decay-OFF baseline."""
    baseline = [
        _run_subprocess(
            alpha_specs=[
                _SIGNAL_ALPHA, _PORTFOLIO_ALPHA_BASELINE,
            ],
        )
        for _ in range(REPEATS)
    ]
    extended = [
        _run_subprocess(
            alpha_specs=[
                _SIGNAL_ALPHA, _PORTFOLIO_ALPHA_WITH_DECAY,
            ],
        )
        for _ in range(REPEATS)
    ]

    baseline_best = _best_of(baseline)
    extended_best = _best_of(extended)
    ratio = extended_best / baseline_best if baseline_best > 0 else float("inf")
    delta = extended_best - baseline_best

    print(
        "PHASE4_1_PERF_SUMMARY "
        f"baseline_best={baseline_best:.4f}s "
        f"baseline_median={statistics.median(baseline):.4f}s "
        f"extended_best={extended_best:.4f}s "
        f"extended_median={statistics.median(extended):.4f}s "
        f"ratio={ratio:.3f} delta_seconds={delta:.4f} "
        f"budget={MAX_OVERHEAD_FACTOR:.3f} repeats={REPEATS}"
    )

    if baseline_best < MIN_BASELINE_FOR_RATIO:
        budget_seconds = (MAX_OVERHEAD_FACTOR - 1.0) * MIN_BASELINE_FOR_RATIO
        assert delta <= budget_seconds, (
            f"Phase-4.1 absolute-delta regression: "
            f"extended_best={extended_best:.3f}s, "
            f"baseline_best={baseline_best:.3f}s, "
            f"delta={delta:.3f}s > budget={budget_seconds:.3f}s "
            f"(absolute fallback for sub-{MIN_BASELINE_FOR_RATIO:.1f}s baselines)"
        )
        return

    assert ratio <= MAX_OVERHEAD_FACTOR, (
        f"Phase-4.1 decay-weighting regression: "
        f"extended_best={extended_best:.3f}s vs "
        f"baseline_best={baseline_best:.3f}s "
        f"(ratio={ratio:.3f} > budget={MAX_OVERHEAD_FACTOR:.3f}). "
        "Profile the decay-weighting branch in CrossSectionalRanker.rank "
        "(math.exp + decay_floor clamp); either tighten the "
        "implementation or document a justified budget revision and "
        "bump MAX_OVERHEAD_FACTOR in the same commit."
    )

    # ── Pinned-baseline assertion (G-G) ───────────────────────────────
    pinned = load_pinned_baseline(
        section="phase4_1_decay_weighting",
        secondary_key="extended_best_seconds",
    )
    if pinned is not None and pinned.baseline_best_seconds >= MIN_BASELINE_FOR_RATIO:
        pinned_ratio = extended_best / pinned.baseline_best_seconds
        print(
            "PHASE4_1_PERF_PINNED_SUMMARY "
            f"host_label={pinned.host_label!r} "
            f"pinned_baseline_best={pinned.baseline_best_seconds:.4f}s "
            f"current_extended_best={extended_best:.4f}s "
            f"pinned_ratio={pinned_ratio:.3f} "
            f"budget={MAX_OVERHEAD_FACTOR:.3f}"
        )
        assert pinned_ratio <= MAX_OVERHEAD_FACTOR, (
            f"Phase-4.1 pinned-baseline regression on host "
            f"{pinned.host_label!r}: current extended_best="
            f"{extended_best:.3f}s vs pinned baseline_best="
            f"{pinned.baseline_best_seconds:.3f}s "
            f"(ratio={pinned_ratio:.3f} > budget={MAX_OVERHEAD_FACTOR:.3f}). "
            "If intentional, re-record the baseline via "
            "scripts/record_perf_baseline.py in the same commit."
        )


def test_phase4_1_perf_harness_paths_exist() -> None:
    assert _PORTFOLIO_ALPHA_BASELINE.exists()
    assert _PORTFOLIO_ALPHA_WITH_DECAY.exists()
    assert _FACTOR_LOADINGS_DIR.is_dir()
    assert _SECTOR_MAP_PATH.is_file()
    assert "PERF_ELAPSED_SECONDS" in _HARNESS_TEMPLATE
