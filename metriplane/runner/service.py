# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Dashboard V2 Runner HTTP Service

Provides REST API for controlled command execution.
Uses Python stdlib only (http.server). Binds to localhost only.
"""

import errno
import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from metriplane._local_http import LocalHTTPServer
from metriplane.paths import (
    PlatformPathError,
    PlatformPaths,
    normalize_runs_dir,
    resolve_platform_paths,
    resolve_runs_dir,
)

from .allowlist import ALLOWLIST, get_command, get_commands, validate_command_id
from .executor import CommandExecutor, find_repo_root
from .operator_api import OperatorAPI

# Global state
executor = CommandExecutor()
runner_paths: PlatformPaths | None = None
operator_api = OperatorAPI(executor=executor, repo_root=find_repo_root(), paths=runner_paths)
start_time = time.time()
MAX_REQUEST_BODY_BYTES = 1024 * 1024
TOKEN_HEADER = "X-Metriplane-Token"


def _default_trusted_origins() -> set[str]:
    configured = {
        item.strip().rstrip("/")
        for item in os.getenv("METRIPLANE_RUNNER_TRUSTED_ORIGINS", "").split(",")
        if item.strip()
    }
    configured.update({"http://127.0.0.1:8088", "http://localhost:8088"})
    return configured


trusted_origins = _default_trusted_origins()
runner_session_token = secrets.token_urlsafe(32)


def _configure_platform_paths(paths: PlatformPaths | None = None) -> PlatformPaths:
    """Resolve once and share one path set across all runner consumers."""
    global operator_api, runner_paths
    runner_paths = paths if paths is not None else resolve_platform_paths()
    environment_runs_dir = normalize_runs_dir(os.getenv("RUNS"))
    if paths is None and environment_runs_dir is not None:
        runner_paths = runner_paths.with_runs_dir(environment_runs_dir)
    else:
        resolved_runs_dir = resolve_runs_dir(runner_paths.runs_dir)
        if resolved_runs_dir is None:
            raise AssertionError("run-recording root unexpectedly resolved as absent")
        if resolved_runs_dir != runner_paths.runs_dir:
            runner_paths = runner_paths.with_runs_dir(resolved_runs_dir)
    executor.configure_platform_paths(runner_paths)
    operator_api = OperatorAPI(
        executor=executor,
        repo_root=find_repo_root(),
        paths=runner_paths,
    )
    return runner_paths


class RequestBodyError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = int(status)


def _address_is_loopback(value: str) -> bool:
    """Accept native and IPv4-mapped loopback address literals."""
    try:
        address = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def _is_loopback_bind_host(host: str, port: int) -> bool:
    """Validate a bind host without resolving numeric address literals."""
    if _address_is_loopback(host):
        return True
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    return bool(addresses) and all(_address_is_loopback(str(address)) for address in addresses)


class RunnerHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for runner API"""

    def log_message(self, format: str, *args: Any) -> None:
        """Override to customize logging"""
        print(f"[Runner] {self.address_string()} - {format % args}")

    def add_cors_headers(self) -> None:
        """Allow browser access only from the local dashboard origin."""
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin or origin not in trusted_origins:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")

    def send_json(self, status_code: int, data: dict[str, Any]) -> None:
        """Send JSON response with CORS headers"""
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.add_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status_code: int, message: str) -> None:
        """Send JSON error response with CORS headers"""
        self.send_json(status_code, {"error": message})

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight for all paths"""
        if not self._client_is_loopback():
            self.send_error_json(403, "Runner accepts loopback clients only")
            return
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin or origin not in trusted_origins:
            self.send_error_json(403, "Untrusted browser origin")
            return
        self.send_response(204)
        self.add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _client_is_loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _authorize_mutation(self) -> bool:
        if not self._client_is_loopback():
            self.send_error_json(403, "Runner accepts loopback clients only")
            return False
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin not in trusted_origins:
            self.send_error_json(403, "Untrusted browser origin")
            return False
        supplied = self.headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(supplied, runner_session_token):
            self.send_error_json(403, "Missing or invalid runner session token")
            return False
        return True

    def _read_body(self) -> dict[str, Any]:
        """Read and parse JSON request body."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError as exc:
            raise RequestBodyError(400, "Invalid Content-Length") from exc
        if content_length < 0:
            raise RequestBodyError(400, "Invalid Content-Length")
        if content_length > MAX_REQUEST_BODY_BYTES:
            raise RequestBodyError(413, "Request body is too large")
        if content_length == 0:
            return {}
        try:
            raw = self.rfile.read(content_length).decode("utf-8")
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestBodyError(400, "Invalid JSON body") from exc
        if not isinstance(value, dict):
            raise RequestBodyError(400, "JSON body must be an object")
        return value

    def do_GET(self) -> None:
        """Handle GET requests"""
        if not self._client_is_loopback():
            self.send_error_json(403, "Runner accepts loopback clients only")
            return
        parsed = urlparse(self.path)
        path = parsed.path

        # ── Operator API ───────────────────────────────────────────────────────
        if path.startswith("/operator/"):
            status, data = operator_api.route("GET", path, {})
            self.send_json(status, data)
            return

        if path == "/status":
            self.handle_get_status()
        elif path == "/commands":
            self.handle_get_commands()
        elif path == "/jobs":
            # List recent jobs
            self.handle_get_jobs()
        elif path.startswith("/jobs/"):
            # Extract job_id from path
            parts = path.split("/")
            if len(parts) >= 3 and parts[2]:
                job_id = parts[2]
                self.handle_get_job(job_id)
            else:
                self.send_error_json(400, "Invalid job path")
        else:
            self.send_error_json(404, "Not found")

    def do_POST(self) -> None:
        """Handle POST requests"""
        if not self._authorize_mutation():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_body()
        except RequestBodyError as exc:
            self.send_error_json(exc.status, str(exc))
            return

        # ── Operator API ───────────────────────────────────────────────────────
        if path.startswith("/operator/"):
            status, data = operator_api.route("POST", path, body)
            self.send_json(status, data)
            return

        if path == "/execute":
            self.handle_post_execute(body)
        elif path.startswith("/jobs/") and path.endswith("/cancel"):
            # Extract job_id from path: /jobs/<job_id>/cancel
            parts = path.split("/")
            if len(parts) >= 4 and parts[3] == "cancel":
                job_id = parts[2]
                self.handle_post_cancel(job_id)
            else:
                self.send_error_json(400, "Invalid cancel path")
        else:
            self.send_error_json(404, "Not found")

    def handle_get_status(self) -> None:
        """GET /status"""
        current_job = None
        if executor.is_running() and executor.current_job:
            job = executor.current_job
            elapsed = (datetime.now() - job["started_at"]).total_seconds()
            current_job = {
                "command_id": job["command_id"],
                "job_id": job["job_id"],
                "started_at": job["started_at"].isoformat(),
                "elapsed_s": round(elapsed, 2),
            }

        # Get last completed job for display
        last_completed = executor.get_last_completed_job()
        if last_completed:
            last_completed["completed_at"] = (
                last_completed["completed_at"].isoformat()
                if last_completed.get("completed_at")
                else None
            )

        self.send_json(
            200,
            {
                "service": "metriplane-runner",
                "version": "2.0.0",
                "status": "running" if executor.is_running() else "idle",
                "current_job": current_job,
                "last_completed_job": last_completed,
                "job_history_size": len(executor.job_history),
                "uptime_s": round(time.time() - start_time, 2),
                "repo_root": str(executor.repo_root),
                "runs_dir": str(runner_paths.runs_dir) if runner_paths is not None else None,
                "session_token": runner_session_token,
            },
        )

    def handle_get_commands(self) -> None:
        """GET /commands"""
        commands: list[dict[str, Any]] = []
        for cmd in get_commands(paths=runner_paths):
            commands.append(
                {
                    "id": cmd.id,
                    "title": cmd.title,
                    "description": cmd.description,
                    "command": " ".join(cmd.command),  # Display as string
                    "enabled": cmd.enabled,
                    "disabled_reason": cmd.disabled_reason,
                    "timeout_s": cmd.timeout_s,
                    "requires_gpu": cmd.requires_gpu,
                    "requires_cameras": cmd.requires_cameras,
                }
            )

        self.send_json(200, {"commands": commands})

    def handle_get_jobs(self) -> None:
        """GET /jobs - List recent jobs"""
        # Get query parameters for limit
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        limit = None
        if "limit" in query:
            try:
                limit = int(query["limit"][0])
            except ValueError:
                pass

        # Get recent jobs from executor
        jobs = executor.get_recent_jobs(limit=limit)

        # Convert datetime objects to ISO format
        for job in jobs:
            if job.get("started_at"):
                job["started_at"] = job["started_at"].isoformat()
            if job.get("completed_at"):
                job["completed_at"] = job["completed_at"].isoformat()

        self.send_json(200, {"jobs": jobs, "total": len(jobs)})

    def handle_post_execute(self, data: dict[str, Any]) -> None:
        """POST /execute"""
        print("[Runner] POST /execute received")

        try:
            command_id = data.get("command_id")
            print(f"[Runner] Command ID: {command_id}")

            if not command_id:
                self.send_error_json(400, "Missing command_id")
                return

            # Validate command_id (security check)
            if not validate_command_id(command_id):
                print(f"[Runner] Invalid command_id: {command_id}")
                self.send_error_json(400, f"Invalid or unknown command_id: {command_id}")
                return

            # Get command from allowlist
            cmd = get_command(command_id, paths=runner_paths)
            if not cmd:
                print(f"[Runner] Unknown command_id: {command_id}")
                self.send_error_json(400, f"Unknown command_id: {command_id}")
                return

            if not cmd.enabled:
                reason = cmd.disabled_reason or "Command is disabled"
                print(f"[Runner] Command disabled: {command_id}")
                self.send_error_json(400, f"Command '{command_id}' is disabled: {reason}")
                return

            # Execute command
            print(f"[Runner] Executing: {' '.join(cmd.command)}")
            try:
                job_id = executor.execute(
                    command_id=cmd.id, command=cmd.command, timeout_s=cmd.timeout_s
                )
                print(f"[Runner] Job started: {job_id}")

                response_data = {
                    "job_id": job_id,
                    "command_id": cmd.id,
                    "status": "running",
                    "started_at": datetime.now().isoformat(),
                }
                print(f"[Runner] Sending response: {response_data}")
                self.send_json(200, response_data)
                print(f"[Runner] POST /execute response sent: {job_id}")

            except ValueError as e:
                # Another command already running
                print(f"[Runner] Conflict: {e}")
                self.send_error_json(409, str(e))

        except Exception as e:
            print(f"[Runner] Unexpected error: {e}")
            import traceback

            traceback.print_exc()
            self.send_error_json(500, f"Internal error: {str(e)}")

    def handle_get_job(self, job_id: str) -> None:
        """GET /jobs/<job_id>"""
        job = executor.get_job(job_id)
        if not job:
            self.send_error_json(404, f"Job not found: {job_id}")
            return

        # Calculate elapsed time
        started = job["started_at"]
        completed = job.get("completed_at")
        if completed:
            elapsed = (completed - started).total_seconds()
        else:
            elapsed = (datetime.now() - started).total_seconds()

        response = {
            "job_id": job["job_id"],
            "command_id": job["command_id"],
            "status": job["status"],
            "started_at": job["started_at"].isoformat(),
            "completed_at": job["completed_at"].isoformat() if completed else None,
            "elapsed_s": round(elapsed, 2),
            "exit_code": job.get("exit_code"),
            "stdout": job.get("stdout", ""),
            "stderr": job.get("stderr", ""),
        }

        self.send_json(200, response)

    def handle_post_cancel(self, job_id: str) -> None:
        """POST /jobs/<job_id>/cancel"""
        success = executor.cancel(job_id)
        if success:
            self.send_json(200, {"job_id": job_id, "status": "cancelled"})
        else:
            self.send_error_json(404, f"Job not found or not running: {job_id}")


def start_runner(
    host: str = "127.0.0.1",
    port: int = 9000,
    *,
    allowed_origins: list[str] | None = None,
    paths: PlatformPaths | None = None,
) -> int:
    """
    Start runner service on localhost only.

    Args:
        host: Bind address (default: 127.0.0.1, localhost only)
        port: Port number (default: 9000)
    """
    if not _is_loopback_bind_host(host, port):
        print("[Runner] Refusing non-loopback bind address. Use 127.0.0.1 or ::1.", file=sys.stderr)
        return 64

    try:
        resolved_paths = _configure_platform_paths(paths)
    except PlatformPathError as exc:
        print(f"[Runner] Cannot resolve platform paths: {exc}", file=sys.stderr)
        return 2

    global runner_session_token, trusted_origins, start_time
    runner_session_token = secrets.token_urlsafe(32)
    start_time = time.time()
    trusted_origins = _default_trusted_origins()
    if allowed_origins:
        trusted_origins.update(origin.rstrip("/") for origin in allowed_origins if origin)

    try:
        server = LocalHTTPServer((host, port), RunnerHTTPHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"[Runner] Port {port} is already in use on {host}.",
                file=sys.stderr,
            )
            print(
                "[Runner] Use `python -m metriplane.cli status` to inspect, "
                "`python -m metriplane.cli cleanup` for orphaned Metriplane services, "
                "or start with `--port` set to a free port.",
                file=sys.stderr,
            )
            return 98
        raise
    print("[Runner] Metriplane Dashboard Runner v2.0")
    print(f"[Runner] Repository root: {executor.repo_root}")
    print(f"[Runner] Runs directory: {resolved_paths.runs_dir}")
    print(f"[Runner] Serving on http://{host}:{port}")
    print(
        f"[Runner] Allowlisted commands: {len([c for c in ALLOWLIST if c.enabled])} enabled, {len([c for c in ALLOWLIST if not c.enabled])} disabled"
    )
    print("[Runner] Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Runner] Shutting down...")
        server.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the dashboard service command-line entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Metriplane Dashboard Runner Service")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, localhost only)"
    )
    parser.add_argument("--port", type=int, default=9000, help="Port number (default: 9000)")
    parser.add_argument(
        "--trusted-origin",
        action="append",
        default=[],
        help="Dashboard origin allowed to call the local runner (repeatable)",
    )
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--runs-dir", default=None)

    args = parser.parse_args(argv)
    base_values = (args.config_dir, args.data_dir, args.cache_dir, args.state_dir)
    if any(base_values) and not all(base_values):
        parser.error(
            "--config-dir, --data-dir, --cache-dir, and --state-dir must be provided together"
        )
    try:
        cli_paths = (
            PlatformPaths(
                config_dir=Path(args.config_dir),
                data_dir=Path(args.data_dir),
                cache_dir=Path(args.cache_dir),
                state_dir=Path(args.state_dir),
            )
            if all(base_values)
            else None
        )
        explicit_runs_dir = normalize_runs_dir(args.runs_dir)
        if explicit_runs_dir is not None:
            cli_paths = (cli_paths or resolve_platform_paths()).with_runs_dir(explicit_runs_dir)
    except PlatformPathError as exc:
        parser.error(str(exc))
    return int(
        start_runner(
            host=args.host,
            port=args.port,
            allowed_origins=args.trusted_origin,
            paths=cli_paths,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
