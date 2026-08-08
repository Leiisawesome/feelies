"""``feelies forensics`` — post-trade analysis over a finished session.

Currently one subcommand: ``circuit-breaker``, which scores each alpha's realized
edge against its realized cost over a session's fills and, when asked, demotes a
bleeding LIVE alpha to QUARANTINED.

Why this exists
---------------
``forensics/cost_circuit_breaker.py`` shipped complete and tested but had no
caller outside its own tests, so nothing ever acted on its verdict: an alpha
could bleed indefinitely while the evidence to demote it sat unread.  Inv-4 makes
decay the default and puts the burden of proof on continued viability; a demotion
mechanism nobody invokes does not discharge that.

Read-only unless ``--apply``
----------------------------
Evaluation is pure.  ``--apply`` is the only path that writes lifecycle state,
and it only ever *tightens* — LIVE to QUARANTINED, never the reverse (Inv-11:
loosening requires human re-authorization, which is what ``feelies promote``
is for).  Non-LIVE alphas are skipped by the breaker itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from feelies.core.errors import ConfigurationError
from feelies.forensics.cost_circuit_breaker import (
    ACTION_INSUFFICIENT,
    ACTION_OK,
    ACTION_QUARANTINE,
    ACTION_WATCH,
    CircuitBreakerDecision,
    CircuitBreakerPolicy,
    apply_cost_circuit_breaker,
    evaluate_cost_circuit_breaker,
)
from feelies.monitoring.paper_session_recorder import trade_records_from_dicts
from feelies.storage.trade_journal import TradeRecord

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DATA_ERROR = 2
# A trip is not an error: it is the tool working.  Distinct from EXIT_OK so a
# deployment gate can branch on "an alpha should be demoted" without parsing text.
EXIT_QUARANTINE_RECOMMENDED = 3

_ACTION_ORDER = {
    ACTION_QUARANTINE: 0,
    ACTION_WATCH: 1,
    ACTION_OK: 2,
    ACTION_INSUFFICIENT: 3,
}


def _load_fills(path: Path) -> list[TradeRecord]:
    """Read a session's ``fills.jsonl`` into ``TradeRecord``s."""
    if not path.is_file():
        raise ConfigurationError(f"fills file not found: {path}")
    rows: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"{path}:{lineno}: malformed JSONL — {exc}") from exc
    return trade_records_from_dicts(rows)


def _decision_as_dict(decision: CircuitBreakerDecision) -> dict[str, Any]:
    return {
        "strategy_id": decision.strategy_id,
        "action": decision.action,
        "reason": decision.reason,
        "n_fills": decision.n_fills,
        "net": decision.net,
        "mean_edge_bps": decision.mean_edge_bps,
        "mean_cost_bps": decision.mean_cost_bps,
        "realized_margin_ratio": decision.realized_margin_ratio,
        "decay_z": decision.decay_z,
    }


def _sorted_decisions(
    decisions: list[CircuitBreakerDecision],
) -> list[CircuitBreakerDecision]:
    """Worst first, then lex by alpha so output is stable across runs."""
    return sorted(
        decisions,
        key=lambda d: (_ACTION_ORDER.get(d.action, 99), d.strategy_id),
    )


def _render_text(
    decisions: list[CircuitBreakerDecision],
    applied: list[CircuitBreakerDecision],
) -> None:
    if not decisions:
        print("No fills in window — nothing to score.")
        return
    applied_ids = {d.strategy_id for d in applied}
    print(f"{'ALPHA':<28}{'ACTION':<14}{'FILLS':>6}{'NET':>12}{'MARGIN':>9}  REASON")
    print("-" * 100)
    for d in decisions:
        margin = (
            "inf" if d.realized_margin_ratio == float("inf") else f"{d.realized_margin_ratio:.2f}"
        )
        mark = " [APPLIED]" if d.strategy_id in applied_ids else ""
        print(
            f"{d.strategy_id:<28}{d.action:<14}{d.n_fills:>6}{d.net:>12.2f}"
            f"{margin:>9}  {d.reason}{mark}"
        )
    trips = [d for d in decisions if d.action == ACTION_QUARANTINE]
    if trips and not applied:
        print(
            f"\n{len(trips)} alpha(s) recommended for quarantine. "
            "Re-run with --apply to demote them."
        )


def _handle_circuit_breaker(args: argparse.Namespace) -> int:
    try:
        records = _load_fills(Path(args.fills))
    except ConfigurationError as exc:
        print(f"error: {exc}")
        return EXIT_DATA_ERROR

    policy = CircuitBreakerPolicy(
        min_fills=args.min_fills,
        cover_margin_ratio=args.cover_margin,
        survival_margin_ratio=args.survival_margin,
        quarantine_on_decay=not args.ignore_decay,
    )
    decisions = _sorted_decisions(list(evaluate_cost_circuit_breaker(records, policy=policy)))

    applied: list[CircuitBreakerDecision] = []
    if args.apply:
        lifecycles = _resolve_lifecycles(args)
        if lifecycles is None:
            return EXIT_USER_ERROR
        applied = list(
            apply_cost_circuit_breaker(
                decisions,
                lifecycles,
                correlation_id=args.correlation_id,
            )
        )

    if args.emit_json:
        print(
            json.dumps(
                {
                    "decisions": [_decision_as_dict(d) for d in decisions],
                    "applied": [d.strategy_id for d in applied],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _render_text(decisions, applied)

    trips = [d for d in decisions if d.action == ACTION_QUARANTINE]
    if trips and not applied:
        return EXIT_QUARANTINE_RECOMMENDED
    return EXIT_OK


def _resolve_lifecycles(args: argparse.Namespace) -> dict[str, Any] | None:
    """Load the alpha registry so ``--apply`` can drive lifecycle transitions."""
    if not args.config:
        print("error: --apply requires --config (to resolve alpha lifecycles)")
        return None
    from feelies.core.platform_config import PlatformConfig

    try:
        config = PlatformConfig.from_yaml(args.config)
    except (ConfigurationError, OSError) as exc:
        print(f"error: could not load config {args.config}: {exc}")
        return None

    from feelies.bootstrap import build_platform

    orchestrator, _ = build_platform(config)
    registry = orchestrator.alpha_registry
    if registry is None:
        print("error: platform built without an alpha registry; nothing to quarantine")
        return None
    lifecycles: dict[str, Any] = {}
    for alpha_id in sorted(registry.alpha_ids()):
        lifecycle = registry.get_lifecycle(alpha_id)
        if lifecycle is not None:
            lifecycles[alpha_id] = lifecycle
    return lifecycles


def register(forensics_parser: argparse.ArgumentParser) -> None:
    """Wire the ``feelies forensics`` subcommand tree."""
    sub = forensics_parser.add_subparsers(
        dest="forensics_command",
        metavar="<subcommand>",
    )
    sub.required = True

    breaker = sub.add_parser(
        "circuit-breaker",
        help="Score realized edge against realized cost per alpha; optionally quarantine.",
        description=(
            "Evaluates each alpha's realized edge against its realized cost over "
            "a session's fills. Read-only unless --apply, which demotes bleeding "
            "LIVE alphas to QUARANTINED. Exit 3 means at least one alpha is "
            "recommended for quarantine and none were applied."
        ),
    )
    breaker.add_argument(
        "fills",
        help="path to a session's fills.jsonl (written by scripts/run_paper.py)",
    )
    breaker.add_argument(
        "--min-fills",
        type=int,
        default=CircuitBreakerPolicy.min_fills,
        help="persistence bar; below this the breaker abstains (default: %(default)s)",
    )
    breaker.add_argument(
        "--cover-margin",
        type=float,
        default=CircuitBreakerPolicy.cover_margin_ratio,
        help="hard trip: realized edge must cover this multiple of cost (default: %(default)s)",
    )
    breaker.add_argument(
        "--survival-margin",
        type=float,
        default=CircuitBreakerPolicy.survival_margin_ratio,
        help="Inv-12 bar below which a profitable alpha is WATCHed (default: %(default)s)",
    )
    breaker.add_argument(
        "--ignore-decay",
        action="store_true",
        help="do not trip on a decay signal alone",
    )
    breaker.add_argument(
        "--apply",
        action="store_true",
        help="demote tripped LIVE alphas to QUARANTINED (the only writing path)",
    )
    breaker.add_argument(
        "--config",
        default=None,
        help="platform YAML; required with --apply to resolve alpha lifecycles",
    )
    breaker.add_argument(
        "--correlation-id",
        default="cost-circuit-breaker",
        help="correlation id stamped on emitted lifecycle transitions",
    )
    breaker.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="emit decisions as JSON instead of a table",
    )
    breaker.set_defaults(handler=_handle_circuit_breaker)


__all__ = ["register"]
