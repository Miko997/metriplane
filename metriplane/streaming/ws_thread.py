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
        self._startup_error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            if self._thread.is_alive():
                return
            self._thread = None
        self._ready.clear()
        self._startup_error = None

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                self._server = loop.run_until_complete(start_server(self.host, self.port))
                self._ready.set()
                loop.run_forever()
            except BaseException as exc:
                self._startup_error = exc
                self._ready.set()
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
            self.stop()
            raise RuntimeError("WS server failed to start (timeout)")
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise RuntimeError(f"WS server failed to start: {error}") from error

        log.info("ws thread started on ws://%s:%d", self.host, self.port)

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._server = None
        self._ready.clear()

    def send_frame(self, fr: FrameStateModel) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(broadcast(fr), self._loop)
