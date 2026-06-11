#!/usr/bin/env python3
"""Second-round IB broker verification harness.

Exercises ``IBGatewayConnection`` + ``IBOrderRouter`` against a live IB
Gateway without going through the full orchestrator.  Intended for
manual/CI functional runs::

    python scripts/verify_ib_broker.py
    python scripts/verify_ib_broker.py --port 4002 --client-id 100

Exit 0 when every check passes; non-zero on first failure.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import traceback
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.broker.ib.connection import IBGatewayConnection  # noqa: E402
from feelies.broker.ib.router import IBOrderRouter  # noqa: E402
from feelies.core.clock import WallClock  # noqa: E402
from feelies.core.events import (  # noqa: E402
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)

_POLL_INTERVAL_S = 0.2


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IB broker verification harness")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4002)
    p.add_argument("--client-id", type=int, default=100)
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--timeout-s", type=float, default=15.0)
    return p.parse_args()


def _port_open(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _poll_terminal(
    router: IBOrderRouter,
    *,
    order_ids: set[str],
    timeout_s: float,
) -> list[object]:
    terminal = {OrderAckStatus.CANCELLED, OrderAckStatus.REJECTED}
    deadline = time.monotonic() + timeout_s
    seen: list[object] = []
    done: set[str] = set()
    while time.monotonic() < deadline:
        batch = router.poll_acks()
        if batch:
            seen.extend(batch)
            for ack in batch:
                if ack.order_id in order_ids and ack.status in terminal:
                    done.add(ack.order_id)
            if done >= order_ids:
                return seen
        time.sleep(_POLL_INTERVAL_S)
    return seen


def _check(name: str, fn: object) -> None:
    print(f"  [{name}] ... ", end="", flush=True)
    try:
        fn()  # type: ignore[operator]
        print("OK")
    except Exception as exc:
        print("FAIL")
        print(f"    {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc


def main() -> int:
    args = _parse_args()
    if not _port_open(args.host, args.port):
        print(
            f"ERROR: IB Gateway not reachable at {args.host}:{args.port}",
            file=sys.stderr,
        )
        return 1

    print(
        f"\nIB broker verification @ {args.host}:{args.port} "
        f"(clientId={args.client_id}, symbol={args.symbol})\n"
    )

    clock = WallClock()
    conn = IBGatewayConnection(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        clock=clock,
    )
    router = IBOrderRouter(connection=conn, clock=clock)

    # ── 1. Handshake ────────────────────────────────────────────────
    def check_handshake() -> None:
        conn.connect_and_start(ready_timeout_s=10.0)
        a, b = conn.next_order_id(), conn.next_order_id()
        assert b == a + 1, f"non-monotonic ids: {a}, {b}"

    _check("connect + nextValidId + monotonic ids", check_handshake)

    # ── 2. Duplicate submit guard ───────────────────────────────────
    def check_duplicate_submit() -> None:
        oid = f"dup-{clock.now_ns()}"
        req = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id=f"cid:{oid}",
            sequence=1,
            order_id=oid,
            symbol=args.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=1,
            limit_price=Decimal("1.00"),
        )
        router.submit(req)
        router.submit(req)
        acks = router.poll_acks()
        statuses = [a.status for a in acks if a.order_id == oid]
        assert OrderAckStatus.ACKNOWLEDGED in statuses
        assert OrderAckStatus.REJECTED in statuses
        assert statuses.count(OrderAckStatus.ACKNOWLEDGED) == 1
        router.cancel_order(oid)
        seen = _poll_terminal(router, order_ids={oid}, timeout_s=args.timeout_s)
        assert any(
            a.order_id == oid
            and a.status
            in (
                OrderAckStatus.CANCELLED,
                OrderAckStatus.REJECTED,
            )
            for a in seen
        ), f"no terminal ack for {oid}: {seen}"

    _check("duplicate submit → REJECTED", check_duplicate_submit)

    # ── 3. Buy limit far below market ───────────────────────────────
    def check_buy_limit_cancel() -> None:
        oid = f"buy-{clock.now_ns()}"
        router.submit(
            OrderRequest(
                timestamp_ns=clock.now_ns(),
                correlation_id=f"cid:{oid}",
                sequence=1,
                order_id=oid,
                symbol=args.symbol,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=1,
                limit_price=Decimal("1.00"),
            )
        )
        assert any(a.status == OrderAckStatus.ACKNOWLEDGED for a in router.poll_acks())
        assert router.cancel_order(oid)
        seen = _poll_terminal(router, order_ids={oid}, timeout_s=args.timeout_s)
        assert any(
            a.order_id == oid
            and a.status
            in (
                OrderAckStatus.CANCELLED,
                OrderAckStatus.REJECTED,
            )
            for a in seen
        ), f"no terminal ack for {oid}: {seen}"

    _check("buy limit + cancel", check_buy_limit_cancel)

    # ── 4. Sell limit far above market ──────────────────────────────
    def check_sell_limit_cancel() -> None:
        oid = f"sell-{clock.now_ns()}"
        router.submit(
            OrderRequest(
                timestamp_ns=clock.now_ns(),
                correlation_id=f"cid:{oid}",
                sequence=1,
                order_id=oid,
                symbol=args.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=1,
                limit_price=Decimal("99999.00"),
            )
        )
        assert any(a.status == OrderAckStatus.ACKNOWLEDGED for a in router.poll_acks())
        assert router.cancel_order(oid)
        seen = _poll_terminal(router, order_ids={oid}, timeout_s=args.timeout_s)
        assert any(
            a.order_id == oid
            and a.status
            in (
                OrderAckStatus.CANCELLED,
                OrderAckStatus.REJECTED,
            )
            for a in seen
        ), f"no terminal ack for {oid}: {seen}"

    _check("sell limit + cancel", check_sell_limit_cancel)

    # ── 5. Cancel unknown order ─────────────────────────────────────
    def check_cancel_unknown() -> None:
        assert router.cancel_order("never-seen-order-id") is False

    _check("cancel unknown → False", check_cancel_unknown)

    # ── 6. Two concurrent orders, independent lifecycle ───────────────
    def check_two_orders() -> None:
        oid1 = f"multi-a-{clock.now_ns()}"
        oid2 = f"multi-b-{clock.now_ns()}"
        for oid in (oid1, oid2):
            router.submit(
                OrderRequest(
                    timestamp_ns=clock.now_ns(),
                    correlation_id=f"cid:{oid}",
                    sequence=1,
                    order_id=oid,
                    symbol=args.symbol,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    limit_price=Decimal("1.00"),
                )
            )
        acks = router.poll_acks()
        acked = {a.order_id for a in acks if a.status == OrderAckStatus.ACKNOWLEDGED}
        assert {oid1, oid2} <= acked
        # Fire both cancels before polling — orchestrator drains all acks
        # in one batch, so per-order sequential polling would miss cross-talk.
        assert router.cancel_order(oid1)
        assert router.cancel_order(oid2)
        deadline = time.monotonic() + args.timeout_s
        seen: list[object] = []
        satisfied: set[str] = set()
        while time.monotonic() < deadline:
            batch = router.poll_acks()
            if batch:
                seen.extend(batch)
                for ack in batch:
                    if ack.order_id in {oid1, oid2} and ack.status in (
                        OrderAckStatus.CANCELLED,
                        OrderAckStatus.REJECTED,
                    ):
                        satisfied.add(ack.order_id)
                if satisfied >= {oid1, oid2}:
                    return
            time.sleep(_POLL_INTERVAL_S)
        raise AssertionError(f"expected both orders terminal; got {satisfied} acks={seen}")

    _check("two independent orders", check_two_orders)

    # ── 7. Clean teardown (no thread exceptions) ────────────────────
    def check_teardown() -> None:
        conn.disconnect_and_stop()
        # Give daemon threads a moment to exit cleanly.
        time.sleep(0.5)
        for t in threading.enumerate():
            if t.name == "ib-msg" and t.is_alive():
                raise RuntimeError("ib-msg thread still alive after disconnect_and_stop")

    _check("clean disconnect", check_teardown)

    # ── 8. Reconnect after disconnect ───────────────────────────────
    def check_reconnect() -> None:
        conn2 = IBGatewayConnection(
            host=args.host,
            port=args.port,
            client_id=args.client_id + 1,  # different client id
            clock=clock,
        )
        conn2.connect_and_start(ready_timeout_s=10.0)
        first = conn2.next_order_id()
        assert isinstance(first, int) and first > 0
        conn2.disconnect_and_stop()

    _check("reconnect with fresh connection", check_reconnect)

    print("\nAll IB broker checks passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
