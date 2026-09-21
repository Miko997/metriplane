# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from websockets.exceptions import ConnectionClosed
from websockets.exceptions import InvalidStatus

import metriplane.streaming.ws_server as ws_server
from metriplane.streaming.ws_server import client_count


def test_client_count_exists() -> None:
    assert client_count() == 0


def test_default_binding_is_numeric_loopback() -> None:
    assert ws_server.start_server.__defaults__ == ("127.0.0.1", 8765)
    assert ws_server._is_numeric_loopback("127.0.0.1")
    assert not ws_server._is_numeric_loopback("localhost")
    assert not ws_server._is_numeric_loopback("0.0.0.0")


def test_remote_binding_without_auth_fails_before_listen(monkeypatch) -> None:
    monkeypatch.delenv("METRIPLANE_WS_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="requires an explicit auth token"):
        asyncio.run(ws_server.start_server("0.0.0.0", 0))


def test_remote_binding_requires_valid_bearer_token() -> None:
    async def scenario() -> None:
        server = await ws_server.start_server("0.0.0.0", 0, auth_token="correct-token")
        port = server.sockets[0].getsockname()[1]
        try:
            with pytest.raises(InvalidStatus) as rejected:
                async with websockets.connect(f"ws://127.0.0.1:{port}"):
                    pass
            assert rejected.value.response.status_code == 401
            assert rejected.value.response.headers["WWW-Authenticate"] == "Bearer"

            async with websockets.connect(
                f"ws://127.0.0.1:{port}",
                additional_headers={"Authorization": "Bearer correct-token"},
            ):
                assert client_count() == 1
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_client_limit_rejects_excess_connection() -> None:
    async def scenario() -> None:
        server = await ws_server.start_server("127.0.0.1", 0, max_clients=1)
        port = server.sockets[0].getsockname()[1]
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}"):
                async with websockets.connect(f"ws://127.0.0.1:{port}") as excess:
                    with pytest.raises(ConnectionClosed) as rejected:
                        await excess.recv()
                    assert rejected.value.rcvd is not None
                    assert rejected.value.rcvd.code == 1013
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_oversized_inbound_frame_is_closed() -> None:
    async def scenario() -> None:
        server = await ws_server.start_server("127.0.0.1", 0, max_frame_bytes=16)
        port = server.sockets[0].getsockname()[1]
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as client:
                await client.send("x" * 100)
                with pytest.raises(ConnectionClosed) as rejected:
                    await client.recv()
                assert rejected.value.rcvd is not None
                assert rejected.value.rcvd.code == 1009
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_inbound_rate_limit_closes_client() -> None:
    async def scenario() -> None:
        server = await ws_server.start_server("127.0.0.1", 0, client_rate_limit=1.0)
        port = server.sockets[0].getsockname()[1]
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}") as client:
                await client.send("first")
                await client.send("second")
                with pytest.raises(ConnectionClosed) as rejected:
                    await client.recv()
                assert rejected.value.rcvd is not None
                assert rejected.value.rcvd.code == 1008
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_slow_authenticated_client_does_not_block_normal_client(monkeypatch) -> None:
    class Frame:
        def __init__(self, sequence: int) -> None:
            self.sequence = sequence

        def model_dump(self) -> dict[str, int]:
            return {"sequence": self.sequence}

    async def scenario() -> None:
        token = "test-only-slow-client-token"
        server = await ws_server.start_server(
            "127.0.0.1",
            0,
            auth_token=token,
            client_queue_size=2,
            client_rate_limit=10_000.0,
        )
        port = server.sockets[0].getsockname()[1]
        headers = {"Authorization": f"Bearer {token}"}
        release_slow_send = asyncio.Event()
        slow_send_started = asyncio.Event()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{port}", additional_headers=headers
            ) as slow_client:
                await asyncio.sleep(0)
                assert len(ws_server._ws_clients) == 1
                slow_server_connection = next(iter(ws_server._ws_clients))
                connection_type = type(slow_server_connection)
                original_send = connection_type.send

                async def controlled_send(connection, payload) -> None:
                    if connection is slow_server_connection:
                        slow_send_started.set()
                        await release_slow_send.wait()
                    await original_send(connection, payload)

                monkeypatch.setattr(connection_type, "send", controlled_send)
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}", additional_headers=headers
                ) as normal_client:
                    await ws_server.broadcast(Frame(0))  # type: ignore[arg-type]
                    await asyncio.wait_for(slow_send_started.wait(), timeout=1)
                    for sequence in range(1, 10):
                        await asyncio.wait_for(ws_server.broadcast(Frame(sequence)), timeout=1)  # type: ignore[arg-type]

                    normal_sequences = []
                    while not normal_sequences or normal_sequences[-1] != 9:
                        payload = await asyncio.wait_for(normal_client.recv(), timeout=1)
                        normal_sequences.append(json.loads(payload)["sequence"])
                    assert normal_sequences[-1] == 9

                    slow_queue = ws_server._client_queues[slow_server_connection]
                    assert slow_queue.qsize() == 2
                    queued = [json.loads(slow_queue.get_nowait())["sequence"] for _ in range(2)]
                    assert queued == [8, 9]
                    assert slow_client.close_code is None
        finally:
            release_slow_send.set()
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_oversized_outbound_frame_fails_closed() -> None:
    class Frame:
        def model_dump(self) -> dict[str, str]:
            return {"payload": "x" * 100}

    async def scenario() -> None:
        previous_max_frame_bytes = ws_server._max_frame_bytes
        ws_server._max_frame_bytes = 16
        marker = object()
        ws_server._ws_clients.add(marker)
        try:
            with pytest.raises(ValueError, match="exceeds max_frame_bytes"):
                await ws_server.broadcast(Frame())  # type: ignore[arg-type]
        finally:
            ws_server._ws_clients.discard(marker)
            ws_server._max_frame_bytes = previous_max_frame_bytes

    asyncio.run(scenario())
