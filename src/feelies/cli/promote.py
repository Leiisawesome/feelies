"""``feelies promote`` subcommand handlers.

Implements the five subcommands documented in :mod:`feelies.cli`:

  - ``inspect``         — chronological timeline for one alpha
  - ``list``            — summarise every alpha in the ledger
  - ``replay-evidence`` — re-run F-2 ``validate_gate`` against
                          historical evidence with current thresholds
  - ``validate``        — preflight the ledger file
  - ``gate-matrix``     — render the declarative F-2 gate matrix

All handlers are read-only.  They never write to the ledger and they
never import orchestrator / risk-engine production code, so operator
invocation cannot perturb replay determinism (audit A-DET-02).

Output discipline:

- Text mode is the default.  Timestamps are rendered as ISO-8601
  UTC strings via :meth:`datetime.fromtimestamp` (the ledger stores
  ns-since-epoch; the CLI does no wall-clock reads of its own —
  this preserves the platform's clock-abstraction invariant
  Inv-10).
- ``--json`` flips every subcommand into a stable, ``sort_keys``
  serialised JSON document on stdout.  CI integrations parse this.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from feelies.alpha.promotion_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    GATE_EVIDENCE_REQUIREMENTS,
    GateId,
    GateThresholds,
    metadata_to_evidence,
    validate_gate,
)
from feelies.alpha.promotion_ledger import (
    LEDGER_SCHEMA_VERSION,
    PromotionLedger,
    PromotionLedgerEntry,
)
from feelies.core.errors import ConfigurationError
from feelies.core.platform_config import PlatformConfig

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DATA_ERROR = 2
EXIT_VALIDATION_FAILED = 3


# ─────────────────────────────────────────────────────────────────────
#   Ledger-arg resolution
# ─────────────────────────────────────────────────────────────────────


class _CLIArgError(Exception):
    """Raised by the ledger-arg resolution helpers when the operator's
    invocation is incomplete or refers to a non-existent file.

    Carries an explicit ``exit_code`` so handlers can map directly to
    the documented exit-code convention (see :mod:`feelies.cli.main`).
    """

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _add_ledger_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--ledger",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to a JSONL promotion-ledger file written by "
            "AlphaLifecycle.  Mutually exclusive with --config."
        ),
    )
    group.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to a platform.yaml file.  The CLI loads the config "
            "and reads its promotion_ledger_path field.  Mutually "
            "exclusive with --ledger."
        ),
    )


def _resolve_ledger_path(args: argparse.Namespace) -> Path:
    """Resolve the ledger path from ``--ledger`` or ``--config``.

    Raises :class:`_CLIArgError` (with the appropriate exit code) when
    neither is supplied, when ``--config`` fails to parse, or when the
    config has no ``promotion_ledger_path`` set.
    """
    explicit = getattr(args, "ledger", None)
    if explicit is not None:
        return Path(explicit)

    config_path = getattr(args, "config", None)
    if config_path is not None:
        try:
            cfg = PlatformConfig.from_yaml(Path(config_path))
        except (
            FileNotFoundError,
            ConfigurationError,
            ValueError,
            OSError,
        ) as exc:
            raise _CLIArgError(
                EXIT_DATA_ERROR,
                f"failed to load config {config_path}: {exc}",
            ) from exc
        if cfg.promotion_ledger_path is None:
            raise _CLIArgError(
                EXIT_USER_ERROR,
                f"config {config_path} has no promotion_ledger_path set",
            )
        return cfg.promotion_ledger_path

    raise _CLIArgError(
        EXIT_USER_ERROR,
        "must supply --ledger PATH or --config PATH (with "
        "promotion_ledger_path set)",
    )


def _open_ledger(args: argparse.Namespace) -> PromotionLedger:
    path = _resolve_ledger_path(args)
    if not path.exists():
        raise _CLIArgError(
            EXIT_USER_ERROR,
            f"ledger file does not exist: {path}",
        )
    if not path.is_file():
        raise _CLIArgError(
            EXIT_USER_ERROR,
            f"ledger path is not a regular file: {path}",
        )
    return PromotionLedger(path)


def _read_entries_safely(
    ledger: PromotionLedger,
) -> tuple[list[PromotionLedgerEntry], list[str]]:
    """Iterate ``ledger.entries()``, separating successfully-parsed
    entries from corruption errors so the caller can surface both.
    """
    entries: list[PromotionLedgerEntry] = []
    errors: list[str] = []
    iterator: Iterator[PromotionLedgerEntry] = ledger.entries()
    while True:
        try:
            entry = next(iterator)
        except StopIteration:
            break
        except ValueError as exc:
            errors.append(str(exc))
            break
        entries.append(entry)
    return entries, errors


def _format_ts(timestamp_ns: int) -> str:
    """Render a ledger ns-since-epoch timestamp as an ISO-8601 UTC string.

    The CLI must not introduce any wall-clock reads (Inv-10): we only
    *render* a timestamp that the writer already captured via the
    deterministic clock.
    """
    seconds = timestamp_ns / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _entry_as_dict(entry: PromotionLedgerEntry) -> dict[str, Any]:
    return {
        "schema_version": entry.schema_version,
        "alpha_id": entry.alpha_id,
        "from_state": entry.from_state,
        "to_state": entry.to_state,
        "trigger": entry.trigger,
        "timestamp_ns": entry.timestamp_ns,
        "timestamp_iso": _format_ts(entry.timestamp_ns),
        "correlation_id": entry.correlation_id,
        "metadata": entry.metadata,
    }


def _dump_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, indent=2))


# ─────────────────────────────────────────────────────────────────────
#   State-pair → GateId inference
# ─────────────────────────────────────────────────────────────────────


_STATE_PAIR_TO_GATE: Mapping[tuple[str, str], GateId] = {
    ("RESEARCH", "PAPER"): GateId.RESEARCH_TO_PAPER,
    ("PAPER", "LIVE"): GateId.PAPER_TO_LIVE,
    ("LIVE", "QUARANTINED"): GateId.LIVE_TO_QUARANTINED,
    ("QUARANTINED", "PAPER"): GateId.QUARANTINED_TO_PAPER,
    ("QUARANTINED", "DECOMMISSIONED"): GateId.QUARANTINED_TO_DECOMMISSIONED,
}
"""Map a recorded ``(from_state, to_state)`` pair onto the F-2 gate id.

Note: ``GateId.LIVE_PROMOTE_CAPITAL_TIER`` is a non-state-changing
escalation (LIVE @ SMALL_CAPITAL → LIVE @ SCALED).  No ``LIVE → LIVE``
transitions appear in the ledger today; Workstream **F-4** will
introduce the trigger string that records it, and this mapping will
be extended at that time.  The ``replay-evidence`` subcommand handles
unknown pairs gracefully (skip with a notice rather than crash).
"""


def _gate_for_entry(entry: PromotionLedgerEntry) -> GateId | None:
    return _STATE_PAIR_TO_GATE.get((entry.from_state, entry.to_state))


# ─────────────────────────────────────────────────────────────────────
#   Subcommand: inspect
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class _InspectResult:
    alpha_id: str
    transitions: list[dict[str, Any]]


def _build_inspect_result(
    ledger: PromotionLedger,
    alpha_id: str,
) -> _InspectResult:
    rows: list[dict[str, Any]] = []
    for entry in ledger.entries_for(alpha_id):
        rows.append(_entry_as_dict(entry))
    return _InspectResult(alpha_id=alpha_id, transitions=rows)


def _render_inspect_text(result: _InspectResult) -> None:
    if not result.transitions:
        print(f"no ledger entries found for alpha_id={result.alpha_id!r}")
        return
    print(
        f"alpha_id: {result.alpha_id}  "
        f"({len(result.transitions)} transitions)"
    )
    print("-" * 78)
    for idx, row in enumerate(result.transitions):
        print(
            f"#{idx:02d}  {row['timestamp_iso']}  "
            f"{row['from_state']:>14} -> {row['to_state']:<14}  "
            f"trigger={row['trigger']!r}  "
            f"correlation_id={row['correlation_id']!r}"
        )
        metadata = row["metadata"]
        if metadata:
            print(f"      metadata: {json.dumps(metadata, sort_keys=True)}")


def _handle_inspect(args: argparse.Namespace) -> int:
    try:
        ledger = _open_ledger(args)
    except _CLIArgError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    try:
        result = _build_inspect_result(ledger, args.alpha_id)
    except ValueError as exc:
        print(f"error: corrupt ledger: {exc}", file=sys.stderr)
        return EXIT_DATA_ERROR

    if args.emit_json:
        _dump_json(
            {
                "alpha_id": result.alpha_id,
                "ledger_path": str(ledger.path),
                "transitions": result.transitions,
            }
        )
    else:
        _render_inspect_text(result)
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────
#   Subcommand: list
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class _AlphaSummary:
    alpha_id: str
    current_state: str
    transition_count: int
    first_timestamp_ns: int
    last_timestamp_ns: int


def _build_alpha_summaries(
    entries: Iterable[PromotionLedgerEntry],
) -> list[_AlphaSummary]:
    by_alpha: dict[str, list[PromotionLedgerEntry]] = {}
    for entry in entries:
        by_alpha.setdefault(entry.alpha_id, []).append(entry)

    summaries: list[_AlphaSummary] = []
    for alpha_id in sorted(by_alpha.keys()):
        rows = by_alpha[alpha_id]
        rows_sorted = sorted(rows, key=lambda e: e.timestamp_ns)
        summaries.append(
            _AlphaSummary(
                alpha_id=alpha_id,
                current_state=rows_sorted[-1].to_state,
                transition_count=len(rows_sorted),
                first_timestamp_ns=rows_sorted[0].timestamp_ns,
                last_timestamp_ns=rows_sorted[-1].timestamp_ns,
            )
        )
    return summaries


def _render_list_text(
    ledger_path: Path,
    summaries: list[_AlphaSummary],
    parse_errors: list[str],
) -> None:
    print(f"ledger: {ledger_path}")
    if parse_errors:
        print(f"warning: {len(parse_errors)} corrupt entry(ies) "
              "encountered while reading; partial summary follows")
        for err in parse_errors:
            print(f"  - {err}")
    if not summaries:
        print("(no entries)")
        return
    header = (
        f"{'alpha_id':<32}  {'state':<14}  {'#tx':>4}  "
        f"{'first_seen':<32}  {'last_seen':<32}"
    )
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(
            f"{s.alpha_id:<32}  {s.current_state:<14}  "
            f"{s.transition_count:>4}  "
            f"{_format_ts(s.first_timestamp_ns):<32}  "
            f"{_format_ts(s.last_timestamp_ns):<32}"
        )


def _handle_list(args: argparse.Namespace) -> int:
    try:
        ledger = _open_ledger(args)
    except _CLIArgError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    entries, parse_errors = _read_entries_safely(ledger)
    summaries = _build_alpha_summaries(entries)

    if args.emit_json:
        _dump_json(
            {
                "ledger_path": str(ledger.path),
                "schema_version": LEDGER_SCHEMA_VERSION,
                "alphas": [
                    {
                        "alpha_id": s.alpha_id,
                        "current_state": s.current_state,
                        "transition_count": s.transition_count,
                        "first_timestamp_ns": s.first_timestamp_ns,
                        "first_timestamp_iso": _format_ts(
                            s.first_timestamp_ns
                        ),
                        "last_timestamp_ns": s.last_timestamp_ns,
                        "last_timestamp_iso": _format_ts(
                            s.last_timestamp_ns
                        ),
                    }
                    for s in summaries
                ],
                "parse_errors": parse_errors,
            }
        )
    else:
        _render_list_text(ledger.path, summaries, parse_errors)

    return EXIT_DATA_ERROR if parse_errors else EXIT_OK


# ─────────────────────────────────────────────────────────────────────
#   Subcommand: replay-evidence
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class _ReplayResult:
    index: int
    from_state: str
    to_state: str
    trigger: str
    timestamp_ns: int
    gate: str | None
    evidence_kinds: list[str]
    skipped_reason: str | None
    errors: list[str]

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None and not self.errors


def _replay_one(
    index: int,
    entry: PromotionLedgerEntry,
    thresholds: GateThresholds,
) -> _ReplayResult:
    gate_id = _gate_for_entry(entry)
    metadata = entry.metadata

    if not isinstance(metadata, Mapping):
        return _ReplayResult(
            index=index,
            from_state=entry.from_state,
            to_state=entry.to_state,
            trigger=entry.trigger,
            timestamp_ns=entry.timestamp_ns,
            gate=gate_id.value if gate_id else None,
            evidence_kinds=[],
            skipped_reason=(
                f"metadata is not an object "
                f"(type={type(metadata).__name__})"
            ),
            errors=[],
        )

    schema_version = metadata.get("schema_version")
    if schema_version is None:
        return _ReplayResult(
            index=index,
            from_state=entry.from_state,
            to_state=entry.to_state,
            trigger=entry.trigger,
            timestamp_ns=entry.timestamp_ns,
            gate=gate_id.value if gate_id else None,
            evidence_kinds=[],
            skipped_reason=(
                "metadata has no schema_version (legacy or "
                "unstructured payload — nothing to replay)"
            ),
            errors=[],
        )
    if schema_version != EVIDENCE_SCHEMA_VERSION:
        return _ReplayResult(
            index=index,
            from_state=entry.from_state,
            to_state=entry.to_state,
            trigger=entry.trigger,
            timestamp_ns=entry.timestamp_ns,
            gate=gate_id.value if gate_id else None,
            evidence_kinds=[],
            skipped_reason=(
                f"metadata schema_version {schema_version!r} != current "
                f"{EVIDENCE_SCHEMA_VERSION!r}"
            ),
            errors=[],
        )

    if gate_id is None:
        return _ReplayResult(
            index=index,
            from_state=entry.from_state,
            to_state=entry.to_state,
            trigger=entry.trigger,
            timestamp_ns=entry.timestamp_ns,
            gate=None,
            evidence_kinds=[],
            skipped_reason=(
                f"no gate registered for transition "
                f"{entry.from_state}->{entry.to_state}"
            ),
            errors=[],
        )

    try:
        evidences = metadata_to_evidence(metadata)
    except ValueError as exc:
        return _ReplayResult(
            index=index,
            from_state=entry.from_state,
            to_state=entry.to_state,
            trigger=entry.trigger,
            timestamp_ns=entry.timestamp_ns,
            gate=gate_id.value,
            evidence_kinds=[],
            skipped_reason=None,
            errors=[f"could not reconstruct evidence: {exc}"],
        )

    kinds_present = sorted(
        k
        for k in metadata.keys()
        if k != "schema_version"
    )
    errors = validate_gate(gate_id, evidences, thresholds)
    return _ReplayResult(
        index=index,
        from_state=entry.from_state,
        to_state=entry.to_state,
        trigger=entry.trigger,
        timestamp_ns=entry.timestamp_ns,
        gate=gate_id.value,
        evidence_kinds=kinds_present,
        skipped_reason=None,
        errors=list(errors),
    )


def _render_replay_text(
    alpha_id: str,
    results: list[_ReplayResult],
) -> None:
    if not results:
        print(f"no ledger entries found for alpha_id={alpha_id!r}")
        return
    print(f"replay-evidence for alpha_id={alpha_id!r} "
          f"({len(results)} transition(s))")
    print("-" * 78)
    for r in results:
        status = (
            "OK"
            if r.ok
            else ("SKIPPED" if r.skipped_reason else "FAIL")
        )
        gate_repr = r.gate or "<no-gate>"
        print(
            f"#{r.index:02d}  {_format_ts(r.timestamp_ns)}  "
            f"{r.from_state:>14}->{r.to_state:<14}  "
            f"gate={gate_repr:<28}  [{status}]"
        )
        if r.skipped_reason:
            print(f"      skipped: {r.skipped_reason}")
        for err in r.errors:
            print(f"      error: {err}")


def _handle_replay_evidence(args: argparse.Namespace) -> int:
    try:
        ledger = _open_ledger(args)
    except _CLIArgError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    thresholds = GateThresholds()
    results: list[_ReplayResult] = []
    try:
        for idx, entry in enumerate(ledger.entries_for(args.alpha_id)):
            results.append(_replay_one(idx, entry, thresholds))
    except ValueError as exc:
        print(f"error: corrupt ledger: {exc}", file=sys.stderr)
        return EXIT_DATA_ERROR

    any_failed = any(r.errors for r in results)

    if args.emit_json:
        _dump_json(
            {
                "alpha_id": args.alpha_id,
                "ledger_path": str(ledger.path),
                "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                "ok": not any_failed,
                "results": [
                    {
                        "index": r.index,
                        "from_state": r.from_state,
                        "to_state": r.to_state,
                        "trigger": r.trigger,
                        "timestamp_ns": r.timestamp_ns,
                        "timestamp_iso": _format_ts(r.timestamp_ns),
                        "gate": r.gate,
                        "evidence_kinds": r.evidence_kinds,
                        "skipped_reason": r.skipped_reason,
                        "errors": r.errors,
                        "ok": r.ok,
                    }
                    for r in results
                ],
            }
        )
    else:
        _render_replay_text(args.alpha_id, results)

    return EXIT_VALIDATION_FAILED if any_failed else EXIT_OK


# ─────────────────────────────────────────────────────────────────────
#   Subcommand: validate
# ─────────────────────────────────────────────────────────────────────


def _handle_validate(args: argparse.Namespace) -> int:
    try:
        ledger = _open_ledger(args)
    except _CLIArgError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    entries, parse_errors = _read_entries_safely(ledger)

    schema_mismatches: list[str] = []
    for idx, entry in enumerate(entries):
        if entry.schema_version != LEDGER_SCHEMA_VERSION:
            schema_mismatches.append(
                f"entry #{idx}: schema_version "
                f"{entry.schema_version!r} != current "
                f"{LEDGER_SCHEMA_VERSION!r}"
            )

    all_errors = parse_errors + schema_mismatches
    ok = not all_errors

    if args.emit_json:
        _dump_json(
            {
                "ledger_path": str(ledger.path),
                "schema_version": LEDGER_SCHEMA_VERSION,
                "entry_count": len(entries),
                "ok": ok,
                "parse_errors": parse_errors,
                "schema_mismatches": schema_mismatches,
            }
        )
    else:
        print(f"ledger: {ledger.path}")
        print(f"schema_version (current): {LEDGER_SCHEMA_VERSION}")
        print(f"entries parsed: {len(entries)}")
        if parse_errors:
            print(f"parse errors: {len(parse_errors)}")
            for err in parse_errors:
                print(f"  - {err}")
        if schema_mismatches:
            print(f"schema mismatches: {len(schema_mismatches)}")
            for err in schema_mismatches:
                print(f"  - {err}")
        if ok:
            print("OK")
        else:
            print("FAIL")

    return EXIT_OK if ok else EXIT_DATA_ERROR


# ─────────────────────────────────────────────────────────────────────
#   Subcommand: gate-matrix
# ─────────────────────────────────────────────────────────────────────


def _handle_gate_matrix(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    for gate_id in GateId:
        types = GATE_EVIDENCE_REQUIREMENTS[gate_id]
        rows.append(
            {
                "gate_id": gate_id.value,
                "required_evidence": [t.__name__ for t in types],
            }
        )

    if args.emit_json:
        _dump_json(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "gates": rows,
            }
        )
    else:
        print(
            f"F-2 gate matrix "
            f"(EVIDENCE_SCHEMA_VERSION={EVIDENCE_SCHEMA_VERSION})"
        )
        print("-" * 78)
        for row in rows:
            req = (
                ", ".join(row["required_evidence"])
                if row["required_evidence"]
                else "(none)"
            )
            print(f"  {row['gate_id']:<32}  required: {req}")
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────
#   Subparser registration
# ─────────────────────────────────────────────────────────────────────


def register(promote_parser: argparse.ArgumentParser) -> None:
    """Wire the ``feelies promote`` subcommand tree.

    Called by :mod:`feelies.cli.main` once during parser construction.
    """
    sub = promote_parser.add_subparsers(
        dest="promote_command",
        metavar="<subcommand>",
    )
    sub.required = True

    p_inspect = sub.add_parser(
        "inspect",
        help="Render every ledger entry for one alpha as a timeline.",
    )
    _add_ledger_args(p_inspect)
    p_inspect.add_argument(
        "alpha_id",
        help="alpha identifier (matches PromotionLedgerEntry.alpha_id)",
    )
    p_inspect.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="emit machine-readable JSON instead of human-readable text",
    )
    p_inspect.set_defaults(handler=_handle_inspect)

    p_list = sub.add_parser(
        "list",
        help="Summarise every alpha that appears in the ledger.",
    )
    _add_ledger_args(p_list)
    p_list.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
    )
    p_list.set_defaults(handler=_handle_list)

    p_replay = sub.add_parser(
        "replay-evidence",
        help=(
            "Re-validate every F-2 evidence package on the ledger "
            "against current GateThresholds."
        ),
    )
    _add_ledger_args(p_replay)
    p_replay.add_argument("alpha_id")
    p_replay.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
    )
    p_replay.set_defaults(handler=_handle_replay_evidence)

    p_validate = sub.add_parser(
        "validate",
        help="Preflight the ledger file: parse + schema-version check.",
    )
    _add_ledger_args(p_validate)
    p_validate.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
    )
    p_validate.set_defaults(handler=_handle_validate)

    p_gate = sub.add_parser(
        "gate-matrix",
        help="Print the F-2 declarative gate matrix.",
    )
    p_gate.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
    )
    p_gate.set_defaults(handler=_handle_gate_matrix)


__all__ = ["register"]
