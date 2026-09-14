# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from metriplane.streaming.ws_server import client_count


def test_client_count_exists() -> None:
    assert client_count() == 0
