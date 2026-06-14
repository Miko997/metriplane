# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import asyncio
import json
import logging
from typing import Any, Set

import websockets
from websockets.exceptions import ConnectionClosed

from metriplane.schema import FrameStateModel

log = logging.getLogger("metriplane.ws")

_clients = 0
_ws_clients: Set[Any] = set()


def client_count() -> int:
    # Keep the old semantics: this returns the counter, not len(_ws_clients)
    return _clients


async def _handler(ws: Any) -> None:
    global _clients
    _clients += 1
    _ws_clients.add(ws)
    log.info("ws client connected; clients=%d", _clients)

    try:
        # Drain messages until client closes. Most clients never send anything.
        async for _ in ws:
            pass
    except ConnectionClosed:
        # Normal when clients drop without clean close
        pass
    except Exception:
        # Unexpected receive-side failure: do not crash the server
        log.exception("ws handler error (receive loop)")
    finally:
        _ws_clients.discard(ws)
        _clients = max(0, _clients - 1)
        log.info("ws client disconnected; clients=%d", _clients)


async def start_server(host: str = "0.0.0.0", port: int = 8765) -> Any:
    log.info("starting ws server on %s:%d", host, port)
    return await websockets.serve(_handler, host, port)


async def broadcast(msg: FrameStateModel) -> None:
    if not _ws_clients:
        return

    payload = json.dumps(msg.model_dump())
    clients = list(_ws_clients)

    results = await asyncio.gather(
        *[ws.send(payload) for ws in clients],
        return_exceptions=True,
    )

    # Prune dead clients (send-side). Also swallow normal close errors quietly.
    for ws, r in zip(clients, results):
        if r is None:
            continue
        # Any exception => remove the client. This prevents repeated errors.
        _ws_clients.discard(ws)
