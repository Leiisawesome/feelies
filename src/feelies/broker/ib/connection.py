"""Threaded IB Gateway connection (EClient + EWrapper subclass).

Threading model (see plan §3.1):

* **EReader** — ibapi-owned background thread spawned by
  ``EClient.connect()``.  Reads raw bytes off the TWS socket and
  pushes decoded messages onto ibapi's internal ``msg_queue``.
* **Message thread** — runs ``self.run()`` and invokes the
  ``EWrapper`` callbacks (``orderStatus``, ``error``, ``nextValidId``,
  ...).  Populates ``_fill_queue``.
* **Writer thread** — drains ``_submit_queue`` and ``_cancel_queue``.
  The only thread that calls ``EClient.placeOrder`` /
  ``cancelOrder``.  ``EClient`` is not documented as thread-safe
  and the socket writer has no internal lock, so socket-write
  exclusivity is enforced here.
* **Main / orchestrator** thread only ever calls ``enqueue_*``,
  ``poll_fills``, ``next_order_id`` and the lifecycle methods.

All cross-thread communication is exclusively via :class:`queue.Queue`
(thread-safe).  IB callbacks NEVER publish to the bus, touch the
position store, or mutate orchestrator state.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from ibapi.client import EClient  # type: ignore[import-untyped]
from ibapi.order_cancel import OrderCancel  # type: ignore[import-untyped]
from ibapi.wrapper import EWrapper  # type: ignore[import-untyped]

from feelies.core.clock import Clock

if TYPE_CHECKING:
    from ibapi.contract import Contract  # type: ignore[import-untyped]
    from ibapi.order import Order as IBOrder  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_WRITER_POLL_TIMEOUT_S = 0.05
_THREAD_JOIN_TIMEOUT_S = 5.0
# Connection-level IB error codes that make the handshake unrecoverable.
_CONNECT_FATAL_ERROR_CODES = frozenset({326, 502, 504})


@dataclass(frozen=True, slots=True)
class IBFillEvent:
    """Internal IB callback payload, drained by :class:`IBOrderRouter`.

    ``cumulative_filled`` and ``avg_fill_price`` are the **cumulative**
    values IB sends on every ``orderStatus`` callback — the router
    converts both to per-delta quantities before emitting an
    ``OrderAck`` to the platform.  ``error_code`` is non-None only for
    error-callback payloads forwarded via :meth:`IBGatewayConnection.error`.
    """

    ib_order_id: int
    status: str
    cumulative_filled: int
    remaining: int
    avg_fill_price: float
    timestamp_ns: int
    error_code: int | None = None
    error_msg: str | None = None


class IBGatewayConnection(EWrapper, EClient):  # type: ignore[misc]
    """Threaded TWS API connection (paper @ 4002 / live @ 4001).

    The orchestrator interacts via :meth:`enqueue_order`,
    :meth:`enqueue_cancel`, :meth:`poll_fills`, and
    :meth:`next_order_id`.  All four are thread-safe.  The two
    spawned worker threads (`_msg_thread`, `_writer_thread`) are
    daemons — they will be killed at interpreter exit if
    :meth:`disconnect_and_stop` was not called.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        clock: Clock,
    ) -> None:
        EClient.__init__(self, wrapper=self)
        self._host = host
        self._port = port
        self._client_id = client_id
        self._clock = clock

        self._next_id_ready = threading.Event()
        self._next_id_lock = threading.Lock()
        self._next_valid_id: int | None = None

        self._submit_queue: queue.Queue[tuple[int, Contract, IBOrder]] = queue.Queue()
        self._cancel_queue: queue.Queue[int] = queue.Queue()
        self._fill_queue: queue.Queue[IBFillEvent] = queue.Queue()

        self._msg_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._connect_failed = threading.Event()
        self._connect_failed_reason: str = ""

    # ── Lifecycle (main thread) ──────────────────────────────────────

    def connect_and_start(self, *, ready_timeout_s: float = 10.0) -> None:
        """Connect to IB Gateway and block until ``nextValidId`` arrives.

        Raises ``RuntimeError`` when the handshake does not complete
        within ``ready_timeout_s``.  Spawns the message and writer
        threads as daemons (so process exit is not held up by a
        wedged socket).

        Raises ``RuntimeError`` if called while a previous session is
        still active — call :meth:`disconnect_and_stop` first.
        """
        if self._msg_thread is not None and self._msg_thread.is_alive():
            raise RuntimeError(
                "IBGatewayConnection already connected; call "
                "disconnect_and_stop() before connect_and_start()"
            )
        self._next_id_ready.clear()
        with self._next_id_lock:
            self._next_valid_id = None
        self._connect_failed.clear()
        self._connect_failed_reason = ""
        self.connect(self._host, self._port, self._client_id)
        self._shutdown_event.clear()
        self._msg_thread = threading.Thread(
            target=self.run,
            name="ib-msg",
            daemon=True,
        )
        self._writer_thread = threading.Thread(
            target=self._drain_writer_queues,
            name="ib-writer",
            daemon=True,
        )
        self._msg_thread.start()
        self._writer_thread.start()
        deadline = time.monotonic() + ready_timeout_s
        while time.monotonic() < deadline:
            if self._next_id_ready.wait(timeout=0.25):
                return
            if self._connect_failed.is_set():
                self.disconnect_and_stop()
                raise RuntimeError(
                    f"IB connection failed: {self._connect_failed_reason}"
                )
        self.disconnect_and_stop()
        raise RuntimeError(
            "IB connection not ready: nextValidId not received within "
            f"{ready_timeout_s}s"
        )

    def disconnect_and_stop(self) -> None:
        """Tear down the connection and join both worker threads.

        Order matters: flip the shutdown flag first so the writer
        thread stops pulling from the submit/cancel queues; then
        :meth:`disconnect` (ibapi's ``run()`` returns when the
        EReader pushes a poison message); finally join both threads
        with a bounded timeout so an unresponsive socket cannot wedge
        :meth:`Orchestrator.shutdown` indefinitely.
        """
        self._shutdown_event.set()
        pending_submits = self._submit_queue.qsize()
        pending_cancels = self._cancel_queue.qsize()
        if pending_submits or pending_cancels:
            logger.warning(
                "ib connection: disconnecting with %d pending submit(s) and "
                "%d pending cancel(s) — they will not reach IB",
                pending_submits,
                pending_cancels,
            )
        try:
            self.disconnect()
        except Exception:  # noqa: BLE001 — defensive teardown
            logger.exception("ib connection: disconnect raised")
        for thread in (self._msg_thread, self._writer_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=_THREAD_JOIN_TIMEOUT_S)
        self._msg_thread = None
        self._writer_thread = None
        self._next_id_ready.clear()
        with self._next_id_lock:
            self._next_valid_id = None

    # ── Submission API (main thread → writer thread) ─────────────────

    def enqueue_order(
        self, ib_order_id: int, contract: "Contract", order: "IBOrder",
    ) -> None:
        """Submit an IB order; drained on the writer thread."""
        self._submit_queue.put((ib_order_id, contract, order))

    def enqueue_cancel(self, ib_order_id: int) -> None:
        """Cancel an IB order; drained on the writer thread."""
        self._cancel_queue.put(ib_order_id)

    # ── Fill collection (main thread) ────────────────────────────────

    def poll_fills(self) -> list[IBFillEvent]:
        """Drain ``_fill_queue`` non-blockingly (thread-safe)."""
        out: list[IBFillEvent] = []
        while True:
            try:
                out.append(self._fill_queue.get_nowait())
            except queue.Empty:
                return out

    # ── Order-id allocation (main thread) ────────────────────────────

    def next_order_id(self) -> int:
        """Allocate the next monotonic IB integer order id.

        Raises ``RuntimeError`` when called before :meth:`connect_and_start`
        completes its ``nextValidId`` handshake.  Thread-safe — the
        lock keeps the integer monotonic across parallel callers.
        """
        with self._next_id_lock:
            if self._next_valid_id is None:
                raise RuntimeError(
                    "IB connection not ready: nextValidId not received. "
                    "Call connect_and_start() before submitting orders."
                )
            oid = self._next_valid_id
            self._next_valid_id += 1
            return oid

    # ── Writer loop (writer thread) ──────────────────────────────────

    def _writer_place_order(self, ib_id: int, contract: "Contract", order: "IBOrder") -> None:
        """Writer-thread ``placeOrder`` with synthetic error on failure."""
        try:
            self.placeOrder(ib_id, contract, order)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "ib writer: placeOrder raised for ib_id=%d", ib_id,
            )
            self._fill_queue.put(IBFillEvent(
                ib_order_id=ib_id,
                status="error",
                cumulative_filled=0,
                remaining=0,
                avg_fill_price=0.0,
                timestamp_ns=self._clock.now_ns(),
                error_code=0,
                error_msg=f"placeOrder:{type(exc).__name__}:{exc}",
            ))

    def _writer_cancel_order(self, ib_id: int) -> None:
        try:
            self.cancelOrder(ib_id, OrderCancel())
        except Exception:  # noqa: BLE001
            logger.exception(
                "ib writer: cancelOrder raised for ib_id=%d", ib_id,
            )

    def _drain_writer_queues(self) -> None:
        """Sole caller of ``EClient.placeOrder`` / ``cancelOrder``."""
        while not self._shutdown_event.is_set():
            try:
                ib_id, contract, order = self._submit_queue.get(
                    timeout=_WRITER_POLL_TIMEOUT_S,
                )
            except queue.Empty:
                pass
            else:
                self._writer_place_order(ib_id, contract, order)
                # Fairness: do not starve cancels during a submit burst.
                try:
                    cancel_id = self._cancel_queue.get_nowait()
                except queue.Empty:
                    continue
                self._writer_cancel_order(cancel_id)
                continue
            try:
                ib_id = self._cancel_queue.get_nowait()
            except queue.Empty:
                continue
            self._writer_cancel_order(ib_id)

    # ── Message loop (message thread) ────────────────────────────────

    def run(self) -> None:
        """ibapi message loop — suppress ``serverVersion()`` teardown races.

        ``EClient.disconnect()`` clears ``serverVersion_`` while the
        loop may still be decoding one last frame; ibapi ≥ 10.x then
        raises ``TypeError`` comparing ``None`` to an int.  When we
        are already shutting down this is harmless.
        """
        try:
            EClient.run(self)
        except TypeError as exc:
            if self._shutdown_event.is_set() or not self.isConnected():
                logger.debug(
                    "ib msg loop: suppressed teardown race: %s", exc,
                )
                return
            raise

    # ── EWrapper callbacks (message thread → _fill_queue) ────────────

    def nextValidId(self, orderId: int) -> None:  # noqa: N802, N803 — ibapi name
        """Handshake message: first id we may use for a new order.

        IB may re-send ``nextValidId`` after a socket reconnect.  Never
        regress the local counter — only move it forward — so in-flight
        ids are not reused.
        """
        with self._next_id_lock:
            if self._next_valid_id is None:
                self._next_valid_id = orderId
            else:
                self._next_valid_id = max(self._next_valid_id, orderId)
        self._next_id_ready.set()

    def orderStatus(  # noqa: N802 — ibapi name
        self,
        orderId: int,  # noqa: N803
        status: str,
        filled: object,
        remaining: object,
        avgFillPrice: float,  # noqa: N803
        permId: int,  # noqa: N803, ARG002
        parentId: int,  # noqa: N803, ARG002
        lastFillPrice: float,  # noqa: N803, ARG002
        clientId: int,  # noqa: N803, ARG002
        whyHeld: str,  # noqa: N803, ARG002
        mktCapPrice: float,  # noqa: N803, ARG002
    ) -> None:
        """Status update from IB — pushed to the fill queue.

        ibapi ≥ 10.x may pass ``Decimal`` for ``filled`` / ``remaining``;
        coerce to ``int`` here so the rest of the pipeline sees a
        single canonical type.
        """
        try:
            cum_filled = int(filled)  # type: ignore[call-overload]
            rem = int(remaining)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            cum_filled = int(Decimal(str(filled)))
            rem = int(Decimal(str(remaining)))
        self._fill_queue.put(IBFillEvent(
            ib_order_id=orderId,
            status=status,
            cumulative_filled=cum_filled,
            remaining=rem,
            avg_fill_price=float(avgFillPrice),
            timestamp_ns=self._clock.now_ns(),
        ))

    def error(  # noqa: N802 — ibapi signature
        self,
        reqId: int,  # noqa: N803
        errorTime: int,  # noqa: N803, ARG002
        errorCode: int,  # noqa: N803
        errorString: str,  # noqa: N803
        advancedOrderRejectJson: str = "",  # noqa: N803, ARG002
    ) -> None:
        """IB error callback.

        Only forwards order-scoped errors (``reqId > 0``).  Connection-
        level errors (``reqId <= 0``: connectivity loss / restore, etc.)
        are logged but not pushed to the fill queue — the router only
        cares about errors that mutate an order's state.
        """
        if reqId <= 0:
            logger.warning(
                "ib error (no order): code=%d msg=%s", errorCode, errorString,
            )
            if int(errorCode) in _CONNECT_FATAL_ERROR_CODES:
                self._connect_failed_reason = (
                    f"code={errorCode}: {errorString}"
                )
                self._connect_failed.set()
            return
        self._fill_queue.put(IBFillEvent(
            ib_order_id=reqId,
            status="error",
            cumulative_filled=0,
            remaining=0,
            avg_fill_price=0.0,
            timestamp_ns=self._clock.now_ns(),
            error_code=int(errorCode),
            error_msg=str(errorString),
        ))
