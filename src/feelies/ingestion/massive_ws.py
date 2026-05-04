"""Massive live WebSocket feed (formerly Polygon.io) — real-time L1 quote and
trade streaming.

Implements the ``MarketDataSource`` protocol for live and paper trading.
Uses the ``websockets`` library directly (not the Massive SDK client) so that
raw bytes are available for the ``MarketDataNormalizer`` protocol contract.

Architecture:
  - Background thread runs an asyncio event loop with the WS connection
  - Raw frames → ``MassiveNormalizer.on_message()`` → canonical events
  - Events buffered in a ``queue.Queue`` (thread-safe, bounded)
  - ``events()`` yields from the queue, blocking when empty
  - Reconnection with exponential backoff on disconnect
  - Graceful shutdown via ``stop()``
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_normalizer import MassiveNormalizer

logger = logging.getLogger(__name__)

_SENTINEL = object()
_DEFAULT_WS_URL = "wss://socket.massive.com/stocks"
_MAX_QUEUE_SIZE = 100_000
_INITIAL_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 60.0
_BACKOFF_MULTIPLIER = 2.0


class MassiveLiveFeed:
    """Real-time market data source via Massive WebSocket.

    Lifecycle:
      1. Construct with API key, symbols, normalizer, clock
      2. Call ``start()`` to begin the background WS connection
      3. Iterate ``events()`` in the main thread (orchestrator pipeline)
      4. Call ``stop()`` for graceful shutdown
    """

    __slots__ = (
        "_api_key",
        "_symbols",
        "_normalizer",
        "_clock",
        "_ws_url",
        "_queue",
        "_thread",
        "_stop_event",
        "_loop",
    )

    def __init__(
        self,
        api_key: str,
        symbols: Sequence[str],
        normalizer: MassiveNormalizer,
        clock: Clock,
        ws_url: str = _DEFAULT_WS_URL,
    ) -> None:
        self._api_key = api_key
        self._symbols = list(symbols)
        self._normalizer = normalizer
        self._clock = clock
        self._ws_url = ws_url
        self._queue: queue.Queue[NBBOQuote | Trade | object] = queue.Queue(
            maxsize=_MAX_QUEUE_SIZE,
        )
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── MarketDataSource protocol ────────────────────────────────────

    def events(self) -> Iterator[NBBOQuote | Trade]:
        """Yield market events as they arrive from the WebSocket.

        Blocks when the queue is empty.  Terminates when ``stop()`` is
        called and the sentinel is received.
        """
        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._stop_event.is_set():
                    return
                continue
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]
    def on_health_transition(self, callback: Callable[..., None]) -> None:
        """Register a callback for DataHealth transitions on any ingested symbol."""
        self._normalizer.on_health_transition(callback)
    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background WebSocket connection thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="massive-ws-feed",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal shutdown and wait for the background thread to exit."""
        self._stop_event.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._queue.put(_SENTINEL)
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None

    # ── Background event loop ────────────────────────────────────────

    def _run_loop(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_with_retry())
        except Exception:
            logger.exception("massive_ws: event loop terminated unexpectedly")
        finally:
            self._loop.close()
            self._loop = None
            self._queue.put(_SENTINEL)

    async def _connect_with_retry(self) -> None:
        """Connect to the WebSocket with exponential backoff on failure."""
        try:
            import websockets  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise ImportError(
                "websockets is required for MassiveLiveFeed. "
                "Install it with: pip install 'feelies[massive]'"
            ) from exc

        backoff = _INITIAL_BACKOFF_S

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self._ws_url) as ws:
                    backoff = _INITIAL_BACKOFF_S
                    await self._authenticate(ws)
                    await self._subscribe(ws)
                    await self._consume(ws)
            except asyncio.CancelledError:
                return
            except Exception:
                if self._stop_event.is_set():
                    return
                self._normalizer.notify_feed_interrupted(self._symbols)
                logger.warning(
                    "massive_ws: connection lost, retrying in %.1fs",
                    backoff,
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_MULTIPLIER, _MAX_BACKOFF_S)

    async def _authenticate(self, ws: Any) -> None:
        """Send auth message and validate the response.

        Massive responds with a JSON array; a successful auth contains
        ``{"ev": "status", "status": "auth_success", ...}``.

        Massive pushes a ``"connected"`` status frame immediately on socket
        open, before any client message.  We drain that preamble first, then
        send the auth request and validate the auth response.

        ``ws`` is typed ``Any`` because the optional ``websockets`` library
        ships without a ``py.typed`` marker; the structural contract is
        documented in the dependency README and exercised end-to-end by
        ``tests/ingestion/test_massive_functional.py``.
        """
        preamble = await asyncio.wait_for(ws.recv(), timeout=10.0)
        logger.info("massive_ws: connection preamble: %s", preamble)
        self._validate_status_response(preamble, "connected", "connect_preamble")
        auth_msg = json.dumps({"action": "auth", "params": self._api_key})
        await ws.send(auth_msg)
        raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
        logger.info("massive_ws: auth response: %s", raw)
        self._validate_status_response(raw, "auth_success", "authentication")

    async def _subscribe(self, ws: Any) -> None:
        """Subscribe to quote and trade channels and validate the response.

        Massive responds with ``{"ev": "status", "status": "success", ...}``
        for each successfully subscribed channel.  ``ws`` is typed ``Any``
        for the same reason as in :meth:`_authenticate`.
        """
        channels = []
        for sym in self._symbols:
            channels.append(f"Q.{sym}")
            channels.append(f"T.{sym}")
        sub_msg = json.dumps({
            "action": "subscribe",
            "params": ",".join(channels),
        })
        await ws.send(sub_msg)

        # Massive may send one frame per channel or batch them together.
        # Read until we have confirmation for every channel or the server
        # goes quiet.  Warn (not raise) on a partial result so that a
        # temporarily-unavailable channel does not block the whole feed.
        n_expected = len(channels)
        successes = 0
        for _ in range(n_expected):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                break  # no more frames arriving
            logger.info("massive_ws: subscribe frame: %s", raw)
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.warning("massive_ws: non-JSON subscribe response: %r", raw)
                continue
            messages = payload if isinstance(payload, list) else [payload]
            for msg in messages:
                if isinstance(msg, dict) and msg.get("status") == "success":
                    successes += 1
            if successes >= n_expected:
                break

        if successes == 0:
            raise ConnectionError(
                "massive_ws: subscription failed — no success confirmations received"
            )
        if successes < n_expected:
            logger.warning(
                "massive_ws: only %d/%d channel confirmations received",
                successes,
                n_expected,
            )

    @staticmethod
    def _validate_status_response(
        raw: str | bytes,
        expected_status: str,
        action_name: str,
    ) -> None:
        """Check that a Massive status response indicates success.

        Massive sends JSON arrays of status messages.  At least one
        element must carry the expected status string.  Raises
        ``ConnectionError`` on failure so the reconnect-with-backoff
        loop handles it like any other connection problem.
        """
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectionError(
                f"massive_ws: {action_name} response not valid JSON: {raw!r}"
            ) from exc

        messages = payload if isinstance(payload, list) else [payload]
        for msg in messages:
            if isinstance(msg, dict) and msg.get("status") == expected_status:
                return

        raise ConnectionError(
            f"massive_ws: {action_name} failed — expected status "
            f"'{expected_status}', got: {raw!r}"
        )

    async def _consume(self, ws: Any) -> None:
        """Read messages from the WebSocket and enqueue normalized events.

        ``ws`` is typed ``Any`` for the same reason as :meth:`_authenticate`.
        """
        async for raw_msg in ws:
            if self._stop_event.is_set():
                return

            raw_bytes = (
                raw_msg.encode("utf-8")
                if isinstance(raw_msg, str)
                else raw_msg
            )
            received_ns = self._clock.now_ns()
            events = self._normalizer.on_message(
                raw_bytes,
                received_ns,
                "massive_ws",
            )
            for event in events:
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    logger.warning(
                        "massive_ws: queue full, dropping event for %s",
                        event.symbol,
                    )
