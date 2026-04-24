"""Phase-4 perf gate — composition layer must not regress mixed-mode throughput.

Plan §p4f_perf_phase4
---------------------

Wiring the PORTFOLIO composition layer (UniverseSynchronizer +
CompositionEngine + CrossSectionalTracker + HorizonMetricsCollector)
on top of an already-running SIGNAL platform must add no more than
12% wall-clock cost on the synthetic 5-minute fixture.  Beyond that
budget the per-tick overhead of the barrier-sync hot path deserves
explicit profiling rather than being amortised silently.

Workstream-D update — the legacy reference alpha
(``trade_cluster_drift``) was retired; the baseline arm dropped its
LEGACY anchor and now measures the SIGNAL-only platform cost.  The
12% budget is preserved because the LEGACY arm's per-tick cost was
already negligible relative to SIGNAL/sensor/regime work.

Two configurations are timed in fresh subprocesses so import-cost
and allocator state are amortised identically:

* **baseline** — SIGNAL (``pofi_benign_midcap_v1``) loaded;
  no PORTFOLIO alpha.
* **mixed**    — same SIGNAL pair *plus* the v0.2 reference PORTFOLIO
  alpha (``pofi_xsect_v1``).  This activates
  ``_create_composition_layer`` end-to-end.

The pass condition is ``mixed_best <= baseline_best * 1.12``.  The
sub-second absolute-delta fallback used by the Phase-3 perf gate is
preserved here for parity.
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


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SIGNAL_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_benign_midcap_v1"
    / "pofi_benign_midcap_v1.alpha.yaml"
)
_PORTFOLIO_ALPHA = (
    _REPO_ROOT / "alphas" / "pofi_xsect_v1"
    / "pofi_xsect_v1.alpha.yaml"
)
_FACTOR_LOADINGS_DIR = _REPO_ROOT / "data" / "reference" / "factor_loadings"
_SECTOR_MAP_PATH = (
    _REPO_ROOT / "data" / "reference" / "sector_map" / "sector_map.json"
)


REPEATS: int = 5
MAX_REGRESSION_FACTOR: float = 1.12  # plan §p4f_perf_phase4
MAX_RUN_WALL_SECONDS: float = 90.0
MIN_BASELINE_FOR_RATIO: float = 1.0


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CI_BENCHMARK") != "1",
        reason=(
            "CI_BENCHMARK env var not set; skipping Phase-4 perf gate"
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
    QUOTES_PER_SYMBOL = 720  # 72s @ 10 Hz
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
    factor_loadings_dir = (
        Path({factor_loadings_dir!r}) if {include_composition!r}
        else None
    )
    sector_map_path = (
        Path({sector_map_path!r}) if {include_composition!r}
        else None
    )

    config = PlatformConfig(
        symbols=frozenset(UNIVERSE),
        mode=OperatingMode.BACKTEST,
        alpha_specs=alpha_specs,
        regime_engine='hmm_3state_fractional',
        sensor_specs=SENSOR_SPECS,
        horizons_seconds=frozenset({{30, 120, 300}}),
        session_open_ns=SESSION_OPEN_NS,
        account_equity=1_000_000.0,
        factor_loadings_dir=factor_loadings_dir,
        sector_map_path=sector_map_path,
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


def _run_subprocess(
    *, alpha_specs: Sequence[Path], include_composition: bool,
) -> float:
    harness = _HARNESS_TEMPLATE.format(
        repo_root=str(_REPO_ROOT),
        alpha_specs=[str(p) for p in alpha_specs],
        factor_loadings_dir=str(_FACTOR_LOADINGS_DIR),
        sector_map_path=str(_SECTOR_MAP_PATH),
        include_composition="True" if include_composition else "False",
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


def test_phase4_within_perf_budget() -> None:
    """SIGNAL+PORTFOLIO must complete within 1.12× SIGNAL-only."""
    baseline = [
        _run_subprocess(
            alpha_specs=[_SIGNAL_ALPHA],
            include_composition=False,
        )
        for _ in range(REPEATS)
    ]
    mixed = [
        _run_subprocess(
            alpha_specs=[_SIGNAL_ALPHA, _PORTFOLIO_ALPHA],
            include_composition=True,
        )
        for _ in range(REPEATS)
    ]

    baseline_best = _best_of(baseline)
    mixed_best = _best_of(mixed)
    ratio = mixed_best / baseline_best if baseline_best > 0 else float("inf")
    delta = mixed_best - baseline_best

    print(
        "PHASE4_PERF_SUMMARY "
        f"baseline_best={baseline_best:.4f}s "
        f"baseline_median={statistics.median(baseline):.4f}s "
        f"mixed_best={mixed_best:.4f}s "
        f"mixed_median={statistics.median(mixed):.4f}s "
        f"ratio={ratio:.3f} delta_seconds={delta:.4f} "
        f"budget={MAX_REGRESSION_FACTOR:.3f} repeats={REPEATS}"
    )

    if baseline_best < MIN_BASELINE_FOR_RATIO:
        budget_seconds = (MAX_REGRESSION_FACTOR - 1.0) * MIN_BASELINE_FOR_RATIO
        assert delta <= budget_seconds, (
            f"Phase-4 absolute-delta regression: "
            f"mixed_best={mixed_best:.3f}s, baseline_best={baseline_best:.3f}s, "
            f"delta={delta:.3f}s > budget={budget_seconds:.3f}s "
            f"(absolute fallback for sub-{MIN_BASELINE_FOR_RATIO:.1f}s baselines)"
        )
        return

    assert ratio <= MAX_REGRESSION_FACTOR, (
        f"Phase-4 PORTFOLIO wiring regression: "
        f"mixed_best={mixed_best:.3f}s vs baseline_best={baseline_best:.3f}s "
        f"(ratio={ratio:.3f} > budget={MAX_REGRESSION_FACTOR:.3f}). "
        "Either reduce the cost of UniverseSynchronizer / "
        "CompositionEngine / CrossSectionalTracker / "
        "HorizonMetricsCollector or document a justified budget "
        "revision in the commit message and this test's "
        "MAX_REGRESSION_FACTOR constant."
    )


def test_phase4_perf_harness_paths_exist() -> None:
    assert _SIGNAL_ALPHA.exists()
    assert _PORTFOLIO_ALPHA.exists()
    assert _FACTOR_LOADINGS_DIR.is_dir()
    assert _SECTOR_MAP_PATH.is_file()
    assert "PERF_ELAPSED_SECONDS" in _HARNESS_TEMPLATE
