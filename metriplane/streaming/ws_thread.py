# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from metriplane.schema import FrameStateModel
from metriplane.streaming.ws_server import broadcast, start_server

log = logging.getLogger("metriplane.ws_thread")


class WsServerThread:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._server: Any = None

    def start(self) -> None:
        if self._thread is not None:
            return

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                self._server = loop.run_until_complete(start_server(self.host, self.port))
                self._ready.set()
                loop.run_forever()
            finally:
                try:
                    if self._server is not None:
                        self._server.close()
                        loop.run_until_complete(self._server.wait_closed())
                except Exception:
                    log.exception("error shutting down ws server")
                try:
                    loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_runner, name="metriplane-ws", daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("WS server failed to start (timeout)")

        log.info("ws thread started on ws://%s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)

    def send_frame(self, fr: FrameStateModel) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(broadcast(fr), self._loop)
