# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Small local HTTP server without reverse-DNS startup lookups."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer


class LocalHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that records the literal bind address as its name."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def main(argv: list[str] | None = None) -> int:
    """Serve a static directory until interrupted."""
    parser = argparse.ArgumentParser(description="Serve the local Metriplane dashboard")
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", default=".")
    args = parser.parse_args(argv)

    handler = partial(SimpleHTTPRequestHandler, directory=args.directory)
    with LocalHTTPServer((args.bind, args.port), handler) as server:
        print(
            f"Serving Metriplane dashboard on http://{args.bind}:{server.server_port}/", flush=True
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
