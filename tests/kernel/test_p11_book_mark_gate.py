"""Orchestrator book-mark gate (P-11, D-24).

Build path matches ``_replay`` in
``tests/position_engine/test_p10_contract_surface.py``:
``InMemoryEventLog.append_batch`` → ``build_platform`` → ``run_backtest``.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_null_alpha_conservation import _NULL_ALPHA
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

_SRC = Path("src/feelies")


def _quote(
    seq: int,
    bid: str,
    ask: str,
    bid_size: int,
    ask_size: int,
) -> NBBOQuote:
    ts = SESSION_OPEN_NS + seq
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def test_bad_quotes_do_not_move_the_book_until_the_next_valid() -> None:
    q1 = _quote(1, "100.00", "100.10", 10, 10)
    crossed = _quote(2, "101.00", "100.00", 10, 10)
    locked = _quote(3, "100.00", "100.00", 10, 10)
    zero_sz = _quote(4, "100.00", "100.10", 0, 10)
    q2 = _quote(5, "102.00", "102.20", 10, 10)
    mid_q1 = (q1.bid + q1.ask) / 2
    mid_q2 = (q2.bid + q2.ask) / 2

    log = InMemoryEventLog()
    log.append_batch([q1, crossed, locked, zero_sz, q2])
    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_NULL_ALPHA],
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=SESSION_OPEN_NS,
    )
    orchestrator, resolved = build_platform(config, event_log=log)
    seen: list[tuple[int, Decimal | None, bool]] = []

    def _on_quote(quote: NBBOQuote) -> None:
        book = orchestrator._positions
        seen.append(
            (quote.sequence, book.reference_mid(quote.symbol), book.is_mark_stale(quote.symbol))
        )

    orchestrator._bus.subscribe(NBBOQuote, _on_quote)
    orchestrator.boot(resolved)
    orchestrator.run_backtest()

    by_seq = {seq: (mid, stale) for seq, mid, stale in seen}
    assert by_seq[1] == (mid_q1, False)
    assert by_seq[2] == (mid_q1, True)
    assert by_seq[3] == (mid_q1, True)
    assert by_seq[4] == (mid_q1, True)
    assert by_seq[5] == (mid_q2, False)


def test_update_mark_call_sites_are_the_orchestrator_or_store_forwarders() -> None:
    """Static guard for D-24. Passes on unchanged src."""
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "update_mark":
                continue
            owner: ast.AST | None = node
            inside_update_mark = False
            while owner is not None:
                if isinstance(owner, ast.FunctionDef) and owner.name == "update_mark":
                    inside_update_mark = True
                    break
                owner = parents.get(owner)
            in_mark_path = (
                path.as_posix().endswith("kernel/orchestrator.py")
                and _enclosing_name(node, parents) == "_process_tick_inner"
            )
            if inside_update_mark or in_mark_path:
                continue
            offenders.append(f"{path.as_posix()}:{node.lineno}")
    assert offenders == [], offenders


def _enclosing_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    owner: ast.AST | None = node
    while owner is not None:
        if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return owner.name
        owner = parents.get(owner)
    return None
