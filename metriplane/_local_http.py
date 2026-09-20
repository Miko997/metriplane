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


DASHBOARD_ASSETS = frozenset(
    {
        "app.js",
        "atlas.html",
        "benchmarks.html",
        "command_center.css",
        "command_center.html",
        "command_center.js",
        "command_center_data.json",
        "command_center_live.html",
        "command_center_live.js",
        "help.html",
        "icons/metriplane-api-bridge.svg",
        "icons/metriplane-calibration-target.svg",
        "icons/metriplane-camera-video.svg",
        "icons/metriplane-coordinate-grid.svg",
        "icons/metriplane-dashboard-metrics.svg",
        "icons/metriplane-detect-markers.svg",
        "icons/metriplane-floor-state.svg",
        "icons/metriplane-health-monitor.svg",
        "icons/metriplane-homography-calibration.svg",
        "icons/metriplane-integration-ready.svg",
        "icons/metriplane-metric-xy.svg",
        "icons/metriplane-multi-camera-fusion.svg",
        "icons/metriplane-object-tracking.svg",
        "icons/metriplane-observability-health.svg",
        "icons/metriplane-replay-logs.svg",
        "icons/metriplane-schema-first.svg",
        "icons/metriplane-state-stream.svg",
        "icons/metriplane-websocket-json.svg",
        "icons/metriplane-zones-events.svg",
        "index.html",
        "integrations.html",
        "mp_nav.js",
        "operator.html",
        "operator.js",
        "product_actions.js",
        "report.html",
        "run.html",
        "runtime.html",
        "settings.html",
        "style.css",
    }
)


class DashboardHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Serve only the declared dashboard surface with local-app headers."""

    server_version = "MetriplaneLocal"
    sys_version = ""

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
        root = Path(self.directory).resolve()
        candidate = root.joinpath(*pure_path.parts)
        current = root
        try:
            for part in pure_path.parts:
                current /= part
                if current.is_symlink():
                    return None
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        generated_root = root / "atlas_run"
        if not resolved.is_relative_to(generated_root) or not resolved.is_file():
            return None
        return f"/{relative}"

    def send_head(self):  # type: ignore[no-untyped-def]
        asset_path = self._asset_path()
        if asset_path is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return None
        self.path = asset_path
        return super().send_head()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
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
    parser.add_argument("--directory", default=".")
    args = parser.parse_args(argv)

    if not _is_numeric_loopback(args.bind):
        parser.error("--bind must be a numeric IPv4 loopback address such as 127.0.0.1")

    handler = partial(DashboardHTTPRequestHandler, directory=args.directory)
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
