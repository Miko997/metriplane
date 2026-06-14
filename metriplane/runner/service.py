# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Dashboard V2 Runner HTTP Service

Provides REST API for controlled command execution.
Uses Python stdlib only (http.server). Binds to localhost only.
"""

import errno
import json
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from typing import Dict, Any

from .allowlist import ALLOWLIST, get_command, validate_command_id
from .executor import CommandExecutor, find_repo_root
from .operator_api import OperatorAPI


# Global state
executor = CommandExecutor()
operator_api = OperatorAPI(executor=executor, repo_root=find_repo_root())
start_time = time.time()


class RunnerHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for runner API"""
    
    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[Runner] {self.address_string()} - {format % args}")
    
    def add_cors_headers(self):
        """Add CORS headers to all responses"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def send_json(self, status_code: int, data: Dict[str, Any]):
        """Send JSON response with CORS headers"""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.add_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())
    
    def send_error_json(self, status_code: int, message: str):
        """Send JSON error response with CORS headers"""
        self.send_json(status_code, {"error": message})
    
    def do_OPTIONS(self):
        """Handle CORS preflight for all paths"""
        self.send_response(200)
        self.add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()
    
    def _read_body(self) -> dict:
        """Read and parse JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self):
        """Handle GET requests"""
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
    
    def do_POST(self):
        """Handle POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path

        # ── Operator API ───────────────────────────────────────────────────────
        if path.startswith("/operator/"):
            try:
                body = self._read_body()
            except Exception:
                self.send_error_json(400, "Invalid JSON body")
                return
            status, data = operator_api.route("POST", path, body)
            self.send_json(status, data)
            return

        if path == "/execute":
            self.handle_post_execute()
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
    
    def handle_get_status(self):
        """GET /status"""
        current_job = None
        if executor.is_running() and executor.current_job:
            job = executor.current_job
            elapsed = (datetime.now() - job["started_at"]).total_seconds()
            current_job = {
                "command_id": job["command_id"],
                "job_id": job["job_id"],
                "started_at": job["started_at"].isoformat(),
                "elapsed_s": round(elapsed, 2)
            }
        
        # Get last completed job for display
        last_completed = executor.get_last_completed_job()
        if last_completed:
            last_completed["completed_at"] = last_completed["completed_at"].isoformat() if last_completed.get("completed_at") else None
        
        self.send_json(200, {
            "service": "metriplane-runner",
            "version": "2.0.0",
            "status": "running" if executor.is_running() else "idle",
            "current_job": current_job,
            "last_completed_job": last_completed,
            "job_history_size": len(executor.job_history),
            "uptime_s": round(time.time() - start_time, 2),
            "repo_root": str(executor.repo_root)
        })
    
    def handle_get_commands(self):
        """GET /commands"""
        commands = []
        for cmd in ALLOWLIST:
            commands.append({
                "id": cmd.id,
                "title": cmd.title,
                "description": cmd.description,
                "command": " ".join(cmd.command),  # Display as string
                "enabled": cmd.enabled,
                "disabled_reason": cmd.disabled_reason,
                "timeout_s": cmd.timeout_s,
                "requires_gpu": cmd.requires_gpu,
                "requires_cameras": cmd.requires_cameras,
            })
        
        self.send_json(200, {"commands": commands})
    
    def handle_get_jobs(self):
        """GET /jobs - List recent jobs"""
        # Get query parameters for limit
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        limit = None
        if 'limit' in query:
            try:
                limit = int(query['limit'][0])
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
        
        self.send_json(200, {
            "jobs": jobs,
            "total": len(jobs)
        })
    
    def handle_post_execute(self):
        """POST /execute"""
        print(f"[Runner] POST /execute received")
        
        try:
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            print(f"[Runner] Content-Length: {content_length}")
            
            if content_length == 0:
                self.send_error_json(400, "Missing request body")
                return
            
            body = self.rfile.read(content_length).decode('utf-8')
            print(f"[Runner] Body: {body[:100]}")
            
            data = json.loads(body)
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
            cmd = get_command(command_id)
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
                    command_id=cmd.id,
                    command=cmd.command,
                    timeout_s=cmd.timeout_s
                )
                print(f"[Runner] Job started: {job_id}")
                
                response_data = {
                    "job_id": job_id,
                    "command_id": cmd.id,
                    "status": "running",
                    "started_at": datetime.now().isoformat()
                }
                print(f"[Runner] Sending response: {response_data}")
                self.send_json(200, response_data)
                print(f"[Runner] POST /execute response sent: {job_id}")
                
            except ValueError as e:
                # Another command already running
                print(f"[Runner] Conflict: {e}")
                self.send_error_json(409, str(e))
                
        except json.JSONDecodeError as e:
            print(f"[Runner] JSON decode error: {e}")
            self.send_error_json(400, "Invalid JSON")
        except Exception as e:
            print(f"[Runner] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            self.send_error_json(500, f"Internal error: {str(e)}")
    
    def handle_get_job(self, job_id: str):
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
            "stderr": job.get("stderr", "")
        }
        
        self.send_json(200, response)
    
    def handle_post_cancel(self, job_id: str):
        """POST /jobs/<job_id>/cancel"""
        success = executor.cancel(job_id)
        if success:
            self.send_json(200, {
                "job_id": job_id,
                "status": "cancelled"
            })
        else:
            self.send_error_json(404, f"Job not found or not running: {job_id}")


def start_runner(host="127.0.0.1", port=9000):
    """
    Start runner service on localhost only.
    
    Args:
        host: Bind address (default: 127.0.0.1, localhost only)
        port: Port number (default: 9000)
    """
    try:
        server = ThreadingHTTPServer((host, port), RunnerHTTPHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"[Runner] Port {port} is already in use on {host}.",
                file=sys.stderr,
            )
            print(
                "[Runner] Use `python -m metriplane.cli status` to inspect, "
                "`python -m metriplane.cli cleanup` for orphaned MetriPlane services, "
                "or start with `--port` set to a free port.",
                file=sys.stderr,
            )
            return 98
        raise
    print(f"[Runner] Metriplane Dashboard Runner v2.0")
    print(f"[Runner] Repository root: {executor.repo_root}")
    print(f"[Runner] Serving on http://{host}:{port}")
    print(f"[Runner] Allowlisted commands: {len([c for c in ALLOWLIST if c.enabled])} enabled, {len([c for c in ALLOWLIST if not c.enabled])} disabled")
    print(f"[Runner] Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Runner] Shutting down...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Metriplane Dashboard Runner Service"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1, localhost only)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port number (default: 9000)"
    )
    
    args = parser.parse_args()
    raise SystemExit(start_runner(host=args.host, port=args.port))
