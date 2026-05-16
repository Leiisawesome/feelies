#!/usr/bin/env python3
"""Phase-0 measurement for ``sig_benign_midcap_v1``.

Runs offline panels from the architecture audit (Spearman OFI vs forward
120s return, gate-conditional splits, B4 edge vs cost, stress passes).

Examples::

    uv run python scripts/phase0_sig_benign_midcap_v1.py
    uv run python scripts/phase0_sig_benign_midcap_v1.py --json
    uv run python scripts/phase0_sig_benign_midcap_v1.py \\
        --config platforms/phase0_sig_benign_midcap_v1.yaml \\
        --jsonl tests/fixtures/event_logs/synth_5min_aapl.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.platform_config import PlatformConfig
from feelies.research.phase0_benign import (
    run_phase0,
    synthesize_multi_symbol_events,
    load_events_from_jsonl,
    write_report,
)

_DEFAULT_CONFIG = _REPO / "platforms" / "phase0_sig_benign_midcap_v1.yaml"
_DEFAULT_OUT = _REPO / "artifacts" / "phase0" / "sig_benign_midcap_v1_report.json"


def _print_human(report_dict: dict[str, object]) -> None:
    print("Phase-0 report:", report_dict["alpha_id"])
    print("  data_source:", report_dict["data_source"])
    print("  symbols:", report_dict["symbols"])
    print("  quotes:", report_dict["n_quotes"])
    print("  boundaries:", report_dict["n_boundaries"])

    def _sp(name: str, panel: dict[str, object]) -> None:
        rho = panel.get("rho")
        n = panel["n"]
        flag = ""
        if rho is not None and rho < 0.05:
            flag = "  [FALSIFICATION: rho < 0.05]"
        print(f"  {name}: n={n} rho={rho}{flag}")

    _sp("Spearman(ofi, fwd120s)", report_dict["spearman_ofi_vs_fwd_return"])
    _sp("  gate ON", report_dict["spearman_ofi_gate_on"])
    _sp("  gate OFF", report_dict["spearman_ofi_gate_off"])
    _sp("  footprint gate ON", report_dict["spearman_footprint_gate_on"])

    b4 = report_dict["b4"]
    pct = b4.get("pct_below_b4") or 0.0
    print(
        f"  B4: signals={b4['n_signals']} with_quote={b4['n_with_quote']} "
        f"below_1.5x_cost={b4['n_below_b4']} ({pct:.1f}%) "
        f"edge_p50={b4['edge_bps_p50']} min_edge_p50={b4['min_edge_bps_p50']}",
    )
    print("  stress:")
    for row in report_dict["stress"]:
        print(
            f"    {row['label']}: orders={row['n_orders']} "
            f"signals={row['n_signals_long_short']} "
            f"no_order={row['n_trace_no_order']} "
            f"b4_suppressed={row['n_trace_b4_suppressed']}",
        )
    for note in report_dict.get("notes", ()):
        print(f"  note: {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="Platform YAML (default: platforms/phase0_sig_benign_midcap_v1.yaml)",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="Optional JSONL event log (NBBOQuote/Trade); default synthetic session",
    )
    parser.add_argument(
        "--quotes-per-symbol",
        type=int,
        default=18_000,
        help="Synthetic quotes per symbol (~30 min at 10 Hz when 18000)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help="JSON report path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON report to stdout",
    )
    args = parser.parse_args()

    config = PlatformConfig.from_yaml(args.config)
    config.validate()

    if args.jsonl is not None:
        events = load_events_from_jsonl(args.jsonl)
        data_source = f"jsonl:{args.jsonl}"
        symbols = frozenset(e.symbol for e in events)
        config = replace(config, symbols=symbols)
    else:
        symbols = tuple(sorted(config.symbols))
        events = synthesize_multi_symbol_events(
            symbols,
            quotes_per_symbol=args.quotes_per_symbol,
        )
        data_source = (
            f"synthetic:seed42 quotes_per_symbol={args.quotes_per_symbol}"
        )

    loaded = AlphaLoader(
        enforce_trend_mechanism=config.enforce_trend_mechanism,
    ).load(str(config.alpha_specs[0]))
    if not isinstance(loaded, LoadedSignalLayerModule):
        print("alpha_specs[0] is not a SIGNAL alpha", file=sys.stderr)
        return 1

    report = run_phase0(config, events, data_source=data_source, loaded=loaded)
    write_report(report, args.output)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report.to_dict())
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
