# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import socket

from metriplane.streaming.ws_thread import WsServerThread


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_websocket_thread_can_restart_after_stop() -> None:
    server = WsServerThread(host="127.0.0.1", port=_free_port())

    server.start()
    server.stop()
    server.start()
    server.stop()

    assert server._thread is None
    assert server._loop is None
