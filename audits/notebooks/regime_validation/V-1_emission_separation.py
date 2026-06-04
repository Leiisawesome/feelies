"""V-1 — Emission separation `d` + state occupancy on real NBBO.

Status:        SCAFFOLD — fill in DATA_PATH and run.
Audit ref:     `docs/audits/regime_stack_audit_2026-06-04.md` §3, V-1.
Question:      After calibrating `HMM3StateFractional` on real NBBO,
               do the three Gaussian emissions actually separate?  If
               `d = |μᵢ − μⱼ| / √(σᵢ² + σⱼ²) < 0.5` for adjacent pairs
               on most symbols, the posterior carries no information
               and gate predicates like `P(normal) > 0.6` are noise.
Decides:       Whether to default-enable
               `enforce_min_pairwise_emission_separation` (audit P2 E-4).
Effort:        Half a day once the cache is populated.

DECISION RULE (FROZEN before running — DO NOT amend after seeing results):
    * Compute per-symbol pairwise `d` (state 0↔1, 1↔2, 0↔2) after
      calibration.
    * If ≥ 80% of universe symbols have **all three** pairwise `d ≥ 0.5`,
      default-enable the separation gate platform-wide
      (`enforce_min_pairwise_emission_separation=True` in `platform.yaml`
      `regime_engine_options:`).
    * If 50–80% pass, default off but recommend per-cohort opt-in (top
      tier on, midcap/thin off).
    * Below 50%, default off and prioritise V-3 (forward-return
      bucketing) to decide whether the taxonomy is salvageable at all
      (audit P2 E-3).

This script is `# %%`-cell formatted — open it directly in VS Code
Jupyter or run it as a plain Python script.

Output artifacts (committed alongside this file):
    * V-1_emission_separation_data.csv  — per-symbol summary table
    * V-1_emission_separation.md        — memo with the decision

Notes:
    * Uses the production engine via
      `feelies.services.regime_engine.HMM3StateFractional` — do **not**
      reimplement the math in pandas (audit ground rule 1).
    * Loads cached NBBO via the production replay loader
      (`feelies.storage.cache_replay.load_event_log_from_disk_cache`)
      so the data path is byte-identical to a backtest.
    * Reports occupancy (% of ticks with each state argmax) to surface
      degenerate cases where one bucket is empty.
"""

# %% Imports + frozen config
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path

# Heavy deps (matplotlib, pandas) imported lazily inside the plotting
# cell so the script can run headless on a CI box without them.

from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import HMM3StateFractional
from feelies.storage.cache_replay import load_event_log_from_disk_cache


# ── Pin the data window + universe in the header (audit ground rule 2)

# TODO operator: point this at your local cache root.  The replay loader
# expects ``<cache_dir>/<symbol>/<yyyy-mm-dd>.jsonl.gz`` — see
# ``feelies.storage.cache_replay.DiskEventCache`` for the layout.
DATA_PATH: Path = Path.home() / ".feelies" / "cache"

# 20-symbol panel spanning liquidity tiers.  Pin explicitly — do NOT
# regenerate from a screener; results need to be re-runnable in six
# months.
UNIVERSE: tuple[str, ...] = (
    # Top tier — > 10⁴ quotes/sec at peak
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
    # Midcap — ~ 10²–10³ quotes/sec
    "F", "GE", "INTC", "BAC", "WFC",
    "T", "PFE", "CSCO", "C", "ORCL",
    # Thin tail — < 10² quotes/sec
    "UAL", "HAL", "DVN", "PSX", "MRO",
)

# Five cash sessions chosen for a mix of vol regimes (normal mid-week
# session, FOMC reaction day, earnings-rich day, low-vol Friday,
# quad-witching).  Edit if your cache covers different dates — but
# log the window in the memo.
DATE_WINDOW: tuple[str, str] = ("2025-01-13", "2025-01-17")

# Audit ground rule 5: decision rule freezes BEFORE looking at output.
SEPARATION_FLOOR: float = 0.5    # d threshold for "separated"
UNIVERSE_PASS_FRACTION: float = 0.80   # share of symbols that must
                                       # ALL three pairs pass for
                                       # default-enable.


# %% Helpers


@dataclass(frozen=True)
class SymbolReport:
    symbol: str
    n_quotes: int
    n_valid_spreads: int
    d_01: float          # pair (0,1)
    d_12: float          # pair (1,2)
    d_02: float          # pair (0,2)
    occupancy: tuple[float, float, float]   # share of ticks where
                                             # state i is the argmax
    calibrated_emission: tuple[tuple[float, float], ...]

    @property
    def min_pairwise_d(self) -> float:
        return min(self.d_01, self.d_12, self.d_02)

    @property
    def all_pairs_separated(self) -> bool:
        return self.min_pairwise_d >= SEPARATION_FLOOR


def _pairwise_d(emission: tuple[tuple[float, float], ...], i: int, j: int) -> float:
    mu_a, sigma_a = emission[i]
    mu_b, sigma_b = emission[j]
    denom = math.sqrt(sigma_a ** 2 + sigma_b ** 2)
    if denom < 1e-12:
        return 0.0
    return abs(mu_b - mu_a) / denom


def calibrate_and_score(
    symbol: str,
    quotes: list[NBBOQuote],
) -> SymbolReport:
    """Calibrate a fresh engine on `quotes`, then drive the same quotes
    back through it to record per-tick argmax occupancy.

    This is the production calibration path — no shortcuts.
    """
    engine = HMM3StateFractional(
        order_emissions_by_increasing_mean=True,
    )
    n_valid = sum(
        1 for q in quotes
        if float(q.ask - q.bid) > 0 and float(q.ask + q.bid) > 0
    )
    ok = engine.calibrate(quotes)
    if not ok:
        return SymbolReport(
            symbol=symbol,
            n_quotes=len(quotes),
            n_valid_spreads=n_valid,
            d_01=float("nan"),
            d_12=float("nan"),
            d_02=float("nan"),
            occupancy=(float("nan"),) * 3,
            calibrated_emission=tuple(engine._emission),
        )

    emission = tuple(engine._emission)
    d_01 = _pairwise_d(emission, 0, 1)
    d_12 = _pairwise_d(emission, 1, 2)
    d_02 = _pairwise_d(emission, 0, 2)

    # Replay quotes through the calibrated engine; the engine's own
    # idempotency cache means re-feeding the same (symbol, sequence)
    # pair is a no-op, so we reset and replay clean.
    engine.reset(symbol)
    counts = [0, 0, 0]
    for q in quotes:
        posteriors = engine.posterior(q)
        counts[max(range(3), key=lambda i: posteriors[i])] += 1
    total = sum(counts) or 1
    occupancy = tuple(c / total for c in counts)

    return SymbolReport(
        symbol=symbol,
        n_quotes=len(quotes),
        n_valid_spreads=n_valid,
        d_01=d_01,
        d_12=d_12,
        d_02=d_02,
        occupancy=occupancy,  # type: ignore[arg-type]
        calibrated_emission=emission,
    )


# %% Load + score


def _load_quotes_for_symbol(symbol: str) -> list[NBBOQuote]:
    event_log, _, _ = load_event_log_from_disk_cache(
        symbols=[symbol],
        start_date=DATE_WINDOW[0],
        end_date=DATE_WINDOW[1],
        cache_dir=DATA_PATH,
    )
    return [e for e in event_log.replay() if isinstance(e, NBBOQuote)]


def run() -> list[SymbolReport]:
    reports: list[SymbolReport] = []
    for sym in UNIVERSE:
        try:
            quotes = _load_quotes_for_symbol(sym)
        except Exception as exc:  # noqa: BLE001 — surface any load failure
            print(f"[{sym}] LOAD FAIL: {type(exc).__name__}: {exc}")
            continue
        if not quotes:
            print(f"[{sym}] no NBBO events in cache for {DATE_WINDOW}")
            continue
        report = calibrate_and_score(sym, quotes)
        reports.append(report)
        print(
            f"[{sym:<5}] n={report.n_quotes:>7} valid={report.n_valid_spreads:>7}  "
            f"d(0,1)={report.d_01:>5.2f}  d(1,2)={report.d_12:>5.2f}  "
            f"d(0,2)={report.d_02:>5.2f}  "
            f"occ=({report.occupancy[0]:.2f},{report.occupancy[1]:.2f},"
            f"{report.occupancy[2]:.2f})  "
            f"min_d={report.min_pairwise_d:>5.2f}  "
            f"PASS={report.all_pairs_separated}"
        )
    return reports


# %% Summarise + persist


def summarise(reports: list[SymbolReport]) -> dict[str, float]:
    if not reports:
        return {"n_symbols": 0, "share_pass": float("nan")}
    n_pass = sum(1 for r in reports if r.all_pairs_separated)
    return {
        "n_symbols": len(reports),
        "n_pass": n_pass,
        "share_pass": n_pass / len(reports),
        "median_min_d": statistics.median(r.min_pairwise_d for r in reports),
        "p10_min_d": statistics.quantiles(
            (r.min_pairwise_d for r in reports), n=10
        )[0] if len(reports) >= 10 else float("nan"),
    }


def emit_decision(stats: dict[str, float]) -> str:
    share = stats.get("share_pass", float("nan"))
    if math.isnan(share):
        return "INCONCLUSIVE — no symbols scored.  Check DATA_PATH + window."
    if share >= UNIVERSE_PASS_FRACTION:
        return (
            f"PASS — {share:.1%} of universe meets the decision rule "
            f"(target ≥ {UNIVERSE_PASS_FRACTION:.0%}).  "
            "Default-enable enforce_min_pairwise_emission_separation."
        )
    if share >= 0.50:
        return (
            f"PARTIAL — {share:.1%} pass.  Default off; recommend "
            "per-cohort opt-in (top-tier on, midcap/thin off)."
        )
    return (
        f"FAIL — only {share:.1%} pass.  Default off and prioritise V-3 "
        "(forward-return bucketing) before any taxonomy change."
    )


def persist_csv(reports: list[SymbolReport], path: Path) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "symbol", "n_quotes", "n_valid_spreads",
            "d_01", "d_12", "d_02", "min_pairwise_d",
            "occ_0", "occ_1", "occ_2",
            "mu_0", "sigma_0", "mu_1", "sigma_1", "mu_2", "sigma_2",
            "all_pairs_separated",
        ])
        for r in reports:
            w.writerow([
                r.symbol, r.n_quotes, r.n_valid_spreads,
                f"{r.d_01:.6f}", f"{r.d_12:.6f}", f"{r.d_02:.6f}",
                f"{r.min_pairwise_d:.6f}",
                f"{r.occupancy[0]:.6f}", f"{r.occupancy[1]:.6f}",
                f"{r.occupancy[2]:.6f}",
                f"{r.calibrated_emission[0][0]:.6f}",
                f"{r.calibrated_emission[0][1]:.6f}",
                f"{r.calibrated_emission[1][0]:.6f}",
                f"{r.calibrated_emission[1][1]:.6f}",
                f"{r.calibrated_emission[2][0]:.6f}",
                f"{r.calibrated_emission[2][1]:.6f}",
                int(r.all_pairs_separated),
            ])


# %% Plot (optional — needs matplotlib)


def plot_min_d_distribution(reports: list[SymbolReport], path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available — skipping chart")
        return
    if not reports:
        return
    xs = [r.symbol for r in reports]
    ys = [r.min_pairwise_d for r in reports]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(xs, ys, color=[
        "tab:green" if y >= SEPARATION_FLOOR else "tab:red" for y in ys
    ])
    ax.axhline(SEPARATION_FLOOR, color="black", linestyle="--", linewidth=1)
    ax.set_ylabel("min pairwise d")
    ax.set_xlabel("symbol")
    ax.set_title(
        f"V-1 — min pairwise emission separation "
        f"({DATE_WINDOW[0]} to {DATE_WINDOW[1]})\n"
        f"green = passes d ≥ {SEPARATION_FLOOR}; red = fails"
    )
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# %% Entry point


if __name__ == "__main__":
    here = Path(__file__).parent
    reports = run()
    stats = summarise(reports)
    print()
    print(f"  n_symbols   = {stats.get('n_symbols')}")
    print(f"  share_pass  = {stats.get('share_pass'):.1%}"
          if not math.isnan(stats.get("share_pass", float('nan')))
          else "  share_pass  = n/a")
    print(f"  median min_d = {stats.get('median_min_d', float('nan')):.3f}")
    print()
    print("DECISION:", emit_decision(stats))
    if reports:
        csv_path = here / "V-1_emission_separation_data.csv"
        persist_csv(reports, csv_path)
        chart_path = here / "V-1_emission_separation_min_d.png"
        plot_min_d_distribution(reports, chart_path)
        wrote = [csv_path.name]
        if chart_path.exists():
            wrote.append(chart_path.name)
        print(f"\nWrote {', '.join(wrote)} to {here}.")
    else:
        print("\nNo reports — nothing written.  Populate the cache and re-run.")
