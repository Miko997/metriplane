# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Small local HTTP server without reverse-DNS startup lookups."""

from __future__ import annotations

import argparse
import ipaddress
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from socketserver import TCPServer
from urllib.parse import unquote, urlsplit

from metriplane.resources import DASHBOARD_RESOURCES, dashboard_directory

DASHBOARD_ASSETS = frozenset(DASHBOARD_RESOURCES)


class DashboardHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve only the declared dashboard surface with local-app headers."""

    server_version = "MetriplaneLocal"
    sys_version = ""

    def __init__(
        self,
        *args: object,
        generated_directory: str | None = None,
        **kwargs: object,
    ) -> None:
        self.generated_directory = generated_directory
        self._serving_generated_artifact = False
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _asset_path(self) -> str | None:
        path = unquote(urlsplit(self.path).path)
        relative = "index.html" if path == "/" else path.removeprefix("/")
        if relative in DASHBOARD_ASSETS:
            return f"/{relative}"
        if "\\" in relative:
            return None
        pure_path = PurePosixPath(relative)
        if (
            pure_path.as_posix() != relative
            or not pure_path.parts
            or pure_path.parts[0] != "atlas_run"
            or any(part in {"", ".", ".."} for part in pure_path.parts)
        ):
            return None
        if self.generated_directory is None:
            return None
        generated_root = Path(self.generated_directory).resolve()
        candidate = generated_root.joinpath(*pure_path.parts[1:])
        current = generated_root
        try:
            for part in pure_path.parts[1:]:
                current /= part
                if current.is_symlink():
                    return None
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_relative_to(generated_root) or not resolved.is_file():
            return None
        return f"/{relative}"

    def send_head(self):  # type: ignore[no-untyped-def]
        asset_path = self._asset_path()
        if asset_path is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return None
        if asset_path.startswith("/atlas_run/"):
            assert self.generated_directory is not None
            original_directory = self.directory
            original_path = self.path
            self.directory = self.generated_directory
            self.path = asset_path.removeprefix("/atlas_run")
            self._serving_generated_artifact = True
            try:
                return super().send_head()
            finally:
                self.directory = original_directory
                self.path = original_path
                self._serving_generated_artifact = False
        self.path = asset_path
        return super().send_head()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        generated_artifact = self._serving_generated_artifact
        content_security_policy = (
            "sandbox allow-downloads; default-src 'none'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            if generated_artifact
            else "default-src 'self'; connect-src 'self' http://127.0.0.1:* "
            "http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        )
        self.send_header(
            "Content-Security-Policy",
            content_security_policy,
        )
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        status = str(args[1]) if len(args) > 1 else "-"
        print(f"[Dashboard] {self.client_address[0]} - {self.command} {status}", flush=True)


class LocalHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that records the literal bind address as its name."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def _is_numeric_loopback(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and address.is_loopback


def main(argv: list[str] | None = None) -> int:
    """Serve a static directory until interrupted."""
    parser = argparse.ArgumentParser(description="Serve the local Metriplane dashboard")
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", default=None)
    parser.add_argument("--generated-directory", default=None)
    args = parser.parse_args(argv)

    if not _is_numeric_loopback(args.bind):
        parser.error("--bind must be a numeric IPv4 loopback address such as 127.0.0.1")

    def serve(directory: Path) -> None:
        handler = partial(
            DashboardHTTPRequestHandler,
            directory=str(directory),
            generated_directory=args.generated_directory,
        )
        with LocalHTTPServer((args.bind, args.port), handler) as server:
            print(
                f"Serving Metriplane dashboard on http://{args.bind}:{server.server_port}/",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass

    if args.directory is not None:
        serve(Path(args.directory))
    else:
        with dashboard_directory() as directory:
            serve(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
