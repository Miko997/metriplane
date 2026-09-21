# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import time
from typing import Any, Set

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.datastructures import Headers
from websockets.http11 import Response

from metriplane.schema import FrameStateModel

log = logging.getLogger("metriplane.ws")

_clients = 0
_ws_clients: Set[Any] = set()
_client_queues: dict[Any, asyncio.Queue[str]] = {}
_client_senders: dict[Any, asyncio.Task[None]] = {}


_max_frame_bytes = 1_048_576
_max_clients = 32
_client_queue_size = 8
_client_rate_limit = 60.0


def _is_numeric_loopback(host: str) -> bool:
    """Return true only for a numeric IP loopback address."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def client_count() -> int:
    # Keep the old semantics: this returns the counter, not len(_ws_clients)
    return _clients


async def _sender(ws: Any, queue: asyncio.Queue[str]) -> None:
    interval = 1.0 / _client_rate_limit
    last_send = 0.0
    while True:
        payload = await queue.get()
        delay = interval - (time.monotonic() - last_send)
        if delay > 0:
            await asyncio.sleep(delay)
        await ws.send(payload)
        last_send = time.monotonic()


async def _handler(ws: Any) -> None:
    global _clients
    if _clients >= _max_clients:
        await ws.close(code=1013, reason="client limit reached")
        return

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_client_queue_size)
    sender = asyncio.create_task(_sender(ws, queue))
    _clients += 1
    _ws_clients.add(ws)
    _client_queues[ws] = queue
    _client_senders[ws] = sender
    log.info("ws client connected; clients=%d", _clients)

    try:
        # Drain messages until client closes. Most clients never send anything.
        window_started = time.monotonic()
        received = 0
        async for message in ws:
            if (
                len(message.encode("utf-8") if isinstance(message, str) else message)
                > _max_frame_bytes
            ):
                await ws.close(code=1009, reason="frame limit exceeded")
                break
            now = time.monotonic()
            if now - window_started >= 1.0:
                window_started = now
                received = 0
            received += 1
            if received > _client_rate_limit:
                await ws.close(code=1008, reason="rate limit exceeded")
                break
    except ConnectionClosed:
        # Normal when clients drop without clean close
        pass
    except Exception:
        # Unexpected receive-side failure: do not crash the server
        log.exception("ws handler error (receive loop)")
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        _client_queues.pop(ws, None)
        _client_senders.pop(ws, None)
        _ws_clients.discard(ws)
        _clients = max(0, _clients - 1)
        log.info("ws client disconnected; clients=%d", _clients)


async def start_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    auth_token: str | None = None,
    max_frame_bytes: int = 1_048_576,
    max_clients: int = 32,
    client_queue_size: int = 8,
    client_rate_limit: float = 60.0,
) -> Any:
    global _client_queue_size, _client_rate_limit, _max_clients, _max_frame_bytes
    if max_frame_bytes < 1 or max_clients < 1 or client_queue_size < 1 or client_rate_limit <= 0:
        raise ValueError("websocket limits must be positive")
    if auth_token is None:
        auth_token = os.environ.get("METRIPLANE_WS_AUTH_TOKEN") or None
    if not _is_numeric_loopback(host) and not auth_token:
        raise ValueError("non-loopback websocket binding requires an explicit auth token")
    _max_frame_bytes = max_frame_bytes
    _max_clients = max_clients
    _client_queue_size = client_queue_size
    _client_rate_limit = client_rate_limit

    def authenticate(_connection: Any, request: Any) -> Response | None:
        if auth_token is None:
            return None
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {auth_token}"
        if hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            return None
        body = b"authentication required\n"
        return Response(
            401,
            "Unauthorized",
            Headers(
                {
                    "Content-Length": str(len(body)),
                    "Content-Type": "text/plain; charset=utf-8",
                    "WWW-Authenticate": "Bearer",
                }
            ),
            body,
        )

    log.info("starting ws server on %s:%d", host, port)
    return await websockets.serve(
        _handler,
        host,
        port,
        max_size=max_frame_bytes,
        max_queue=client_queue_size,
        process_request=authenticate,
    )


async def broadcast(msg: FrameStateModel) -> None:
    if not _ws_clients:
        return

    payload = json.dumps(msg.model_dump())
    if len(payload.encode("utf-8")) > _max_frame_bytes:
        raise ValueError("serialized websocket frame exceeds max_frame_bytes")

    for ws, queue in list(_client_queues.items()):
        if queue.full():
            # Keep the latest state for slow clients while preserving a hard bound.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            _ws_clients.discard(ws)
