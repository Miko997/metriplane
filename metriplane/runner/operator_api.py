# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Metriplane Operator API

Structured JSON endpoints for low-code operator workflow.
All inputs are validated. No shell=True. No arbitrary execution.
Only writes to: calib/profiles/local_*/  configs/local/  configs/generated/
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

import yaml

# ── Safety patterns ────────────────────────────────────────────────────────────

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SAFE_RUNID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SAFE_CAMERA_RE = re.compile(r"^(/dev/video\d+|/dev/v4l/by-id/[a-zA-Z0-9_.:-]+|\d{1,2})$")


def _valid_name(name: str) -> bool:
    return bool(SAFE_NAME_RE.match(name))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_camera(cam: str) -> bool:
    return bool(SAFE_CAMERA_RE.match(str(cam)))


def _no_traversal(path: str) -> bool:
    return ".." not in path and not path.startswith("/") or path.startswith("/dev/")


def _profile_dir(repo_root: Path, profile: str) -> Path:
    """
    Return the calib/profiles/<profile> dir.
    Profile must be under calib/profiles/ (no traversal).
    New profiles are created under calib/profiles/local_<name>/
    """
    return repo_root / "calib" / "profiles" / profile


def _resolve_cv2_index(camera_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Convert camera path to a cv2.VideoCapture()-compatible integer index string.

    calibrate_planar_homography.py and debug_alignment.py pass the camera
    argument directly to cv2.VideoCapture(cam), which requires an integer.
    Passing '/dev/video0' causes argparse/cv2 to fail with exit code 2.

    Returns:
        (cv2_index_str, None)  — conversion succeeded; use cv2_index_str in the command.
        (None, error_message)  — unsupported format; return 400 to the caller.

    Examples:
        '0'            → ('0',  None)
        '2'            → ('2',  None)
        '/dev/video0'  → ('0',  None)
        '/dev/video2'  → ('2',  None)
        '/dev/v4l/...' → (None, "error …")
    """
    # Already an integer index (0–99 already validated by _safe_camera)
    if re.match(r"^\d{1,2}$", camera_path):
        return (camera_path, None)
    # /dev/videoN → extract N
    m = re.match(r"^/dev/video(\d+)$", camera_path)
    if m:
        return (m.group(1), None)
    # /dev/v4l/by-id/... — stable symlink but not directly usable as cv2 index
    if camera_path.startswith("/dev/v4l/by-id/"):
        return (
            None,
            (
                f"Camera path '{camera_path}' cannot be used with "
                "calibrate_planar_homography.py — it requires an integer index "
                "(e.g. 0 or 2) not a /dev/v4l/by-id/ path. "
                "Use the /dev/videoN path shown in 'Scan Cameras' (Step 2)."
            ),
        )
    return (
        None,
        f"Unsupported camera format for calibration: '{camera_path}'. "
        "Use /dev/videoN or an integer index (e.g. 0, 2).",
    )


def _validate_camera_config(config_data: dict[str, Any], repo_root: Path) -> Optional[str]:
    """
    Validate CameraSpec fields in a config dict before saving.

    The metriplane Config / CameraSpec dataclass uses:
      name        str   (required)
      device      str   OR  index  int   (at least one required)
      mapping_file str           (required; file must exist)

    Returns None if valid, or a human-readable error string if invalid.
    """
    cameras = config_data.get("cameras")
    if not cameras:
        # Single-camera configs may omit 'cameras' — only validate when present.
        return None
    if not isinstance(cameras, list):
        return "cameras must be a list of camera spec dicts"
    for i, cam in enumerate(cameras):
        if not isinstance(cam, dict):
            return f"cameras[{i}]: expected a dict, got {type(cam).__name__}"
        name = cam.get("name") or f"cam{i}"
        if cam.get("device") is None and cam.get("index") is None:
            return (
                f"cameras[{i}] ({name!r}): missing both 'device' and 'index'. "
                "Add 'device: /dev/videoN' or 'index: N' — "
                "the 'source' key is not recognised by the config loader."
            )
        mf = cam.get("mapping_file")
        if not mf:
            return (
                f"cameras[{i}] ({name!r}): missing 'mapping_file'. "
                "Expected format: calib/profiles/<profile>/<cam>/mapping_raw.yaml. "
                "The 'mapping' key is not recognised — use 'mapping_file'."
            )
        mf_path = (repo_root / str(mf)).resolve()
        if not mf_path.exists():
            return (
                f"cameras[{i}] ({name!r}): mapping_file not found on disk: {mf}. "
                "Complete Step 5 (Calibrate Homography) before saving this config."
            )
    return None


def _validate_config_relative(repo_root: Path, config: str) -> Optional[Path]:
    """
    Validate that config is a safe relative path under configs/.
    Returns resolved path or None.
    """
    if not config:
        return None
    # Strip leading ./
    config = config.lstrip("./")
    path = (repo_root / config).resolve()
    configs_root = (repo_root / "configs").resolve()
    if not _is_relative_to(path, configs_root):
        return None
    return path


# ── Python interpreter resolution ──────────────────────────────────────────────


def _resolve_python_executable(repo_root: Path) -> str:
    """
    Resolve the Python interpreter to use for all Operator subprocess calls.

    Priority:
      1. $METRIPLANE_PYTHON               — if set and executable
      2. $METRIPLANE_VENV/bin/python      — if METRIPLANE_VENV env-var set and executable
      3. <repo_root>/.vt-venv/bin/python — project GPU/CUDA venv (optional)
      4. <repo_root>/.venv/bin/python    — project standard venv (preferred default)
      5. sys.executable           — current interpreter (CI / Docker fallback)
    """

    def _is_exec(p: str) -> bool:
        return bool(p) and os.path.isfile(p) and os.access(p, os.X_OK)

    # 1. $METRIPLANE_PYTHON
    vt_python = os.environ.get("METRIPLANE_PYTHON", "")
    if _is_exec(vt_python):
        return vt_python

    # 2. $METRIPLANE_VENV/bin/python
    vt_venv = os.environ.get("METRIPLANE_VENV", "")
    if vt_venv:
        candidate = os.path.join(vt_venv, "bin", "python")
        if _is_exec(candidate):
            return candidate

    # 3. <repo_root>/.vt-venv/bin/python  (GPU/CUDA venv, if created)
    vt_venv_py = str(repo_root / ".vt-venv" / "bin" / "python")
    if _is_exec(vt_venv_py):
        return vt_venv_py

    # 4. <repo_root>/.venv/bin/python  (standard project venv)
    venv_py = str(repo_root / ".venv" / "bin" / "python")
    if _is_exec(venv_py):
        return venv_py

    # 5. sys.executable  (CI / Docker / system Python)
    return sys.executable


def _check_cv2_available(python_exe: str) -> Tuple[bool, Optional[str], bool]:
    """
    Return (cv2_available, cv2_version_or_None, aruco_available).
    Spawns `python_exe -c "import cv2; ..."` to test imports.
    Times out after 8 s; any error → (False, None, False).
    """
    try:
        r = subprocess.run(
            [python_exe, "-c", "import cv2; print(cv2.__version__)"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0:
            return False, None, False
        version = r.stdout.strip()
        r2 = subprocess.run(
            [python_exe, "-c", "from cv2 import aruco; print('ok')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True, version, r2.returncode == 0
    except Exception:
        return False, None, False


# ── OperatorAPI ────────────────────────────────────────────────────────────────


class OperatorAPI:
    """
    Handles /operator/* HTTP requests.
    Injected with a reference to the CommandExecutor from service.py.
    """

    def __init__(self, executor: Any, repo_root: Path) -> None:
        self.executor = executor
        self.repo_root = repo_root
        # Resolved once at startup — uses .venv/bin/python when present
        self._python: str = _resolve_python_executable(repo_root)

    def route(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """
        Route /operator/* requests.
        Returns (status_code, response_dict).
        """
        sub = path[len("/operator") :]  # strip /operator prefix
        try:
            if method == "GET":
                if sub == "/env":
                    return self._get_env()
                if sub == "/cameras":
                    return self._get_cameras()
                if sub == "/profiles":
                    return self._get_profiles()
                if sub == "/configs":
                    return self._get_configs()
                if sub == "/latest-run":
                    return self._get_latest_run()
                if sub == "/runner-status":
                    return self._get_runner_status()
                # ── Sentinel command-center (read-only views) ──────────────
                if sub == "/live-summary":
                    return self._cc_live_summary({})
                if sub == "/objects":
                    return self._cc_objects({})
                if sub == "/incidents":
                    return self._cc_incidents({})
                if sub == "/traces":
                    return self._cc_traces({})
                if sub == "/camera-trust":
                    return self._cc_camera_trust({})
                if sub == "/frames":
                    return self._cc_frames({})
            elif method == "POST":
                if sub == "/create-profile":
                    return self._create_profile(body)
                if sub == "/write-zones":
                    return self._write_zones(body)
                if sub == "/save-config":
                    return self._save_config(body)
                if sub == "/start-fusion":
                    return self._start_fusion(body)
                if sub == "/calibrate":
                    return self._calibrate(body)
                if sub == "/validate-alignment":
                    return self._validate_alignment(body)
                if sub == "/validate-alignment-full":
                    return self._full_alignment_check(body)
                if sub == "/generate-report":
                    return self._generate_report(body)
                if sub == "/checksum":
                    return self._checksum(body)
                if sub == "/live-summary":
                    return self._cc_live_summary(body)
                if sub == "/objects":
                    return self._cc_objects(body)
                if sub == "/incidents":
                    return self._cc_incidents(body)
                if sub == "/traces":
                    return self._cc_traces(body)
                if sub == "/camera-trust":
                    return self._cc_camera_trust(body)
                if sub == "/frames":
                    return self._cc_frames(body)
                if sub == "/ask":
                    return self._cc_ask(body)
        except Exception as exc:
            return 500, {"error": f"Internal error: {exc}"}

        return 404, {"error": f"Unknown operator endpoint: {method} /operator{sub}"}

    # ── GET /operator/env ──────────────────────────────────────────────────────

    def _get_env(self) -> tuple[int, dict[str, Any]]:
        import platform

        # Git hash
        git_hash = "unknown"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(self.repo_root),
            )
            if result.returncode == 0:
                git_hash = result.stdout.strip()[:16]
        except Exception:
            pass

        # GPU detect
        gpu_info = "unknown"
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gpu_info = result.stdout.strip()
        except Exception:
            gpu_info = "nvidia-smi not found"

        # cv2 / aruco availability via the resolved interpreter
        py_exe = self._python
        cv2_ok, cv2_ver, aruco_ok = _check_cv2_available(py_exe)
        py_warn: Optional[str] = None
        if not cv2_ok:
            py_warn = (
                "OpenCV is missing in the runner Python. "
                "Activate the venv or install: "
                "source .venv/bin/activate && pip install opencv-contrib-python"
            )

        return 200, {
            "python": sys.version,
            "python_executable": py_exe,
            "platform": platform.platform(),
            "git_commit": git_hash,
            "repo_root": str(self.repo_root),
            "gpu": gpu_info,
            "active_config": str(self.repo_root / "calib" / "active_profile.yaml"),
            "cv2_available": cv2_ok,
            "cv2_version": cv2_ver,
            "aruco_available": aruco_ok,
            "python_warning": py_warn,
        }

    # ── GET /operator/cameras ──────────────────────────────────────────────────

    def _get_cameras(self) -> tuple[int, dict[str, Any]]:
        script = self.repo_root / "tools" / "list_cameras.py"
        if not script.exists():
            return 500, {"error": "tools/list_cameras.py not found"}
        try:
            result = subprocess.run(
                [self._python, str(script)],
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(self.repo_root),
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return 200, data
                return 500, {"error": "list_cameras.py returned a non-object JSON response"}
            return 500, {"error": result.stderr or "list_cameras.py failed"}
        except subprocess.TimeoutExpired:
            return 500, {"error": "Camera scan timed out (20s)"}
        except Exception as exc:
            return 500, {"error": str(exc)}

    # ── GET /operator/profiles ─────────────────────────────────────────────────

    def _get_profiles(self) -> tuple[int, dict[str, Any]]:
        profiles_root = self.repo_root / "calib" / "profiles"
        profiles = []
        if profiles_root.exists():
            for p in sorted(profiles_root.iterdir()):
                if p.is_dir():
                    anchors = (p / "anchors.yaml").exists()
                    cam0 = (p / "cam0" / "mapping_raw.yaml").exists()
                    cam1 = (p / "cam1" / "mapping_raw.yaml").exists()
                    zones = (p / "zones.yaml").exists()
                    profiles.append(
                        {
                            "name": p.name,
                            "path": str(p.relative_to(self.repo_root)),
                            "has_anchors": anchors,
                            "has_cam0_mapping": cam0,
                            "has_cam1_mapping": cam1,
                            "has_zones": zones,
                            "is_local": p.name.startswith("local_"),
                        }
                    )
        return 200, {"profiles": profiles, "total": len(profiles)}

    # ── GET /operator/configs ──────────────────────────────────────────────────

    def _get_configs(self) -> tuple[int, dict[str, Any]]:
        configs_root = self.repo_root / "configs"
        configs = []
        if configs_root.exists():
            for f in sorted(configs_root.rglob("*.yaml")):
                if f.is_file():
                    configs.append(
                        {
                            "path": str(f.relative_to(self.repo_root)),
                            "name": f.name,
                            "is_local": "local" in f.parent.name or "generated" in f.parent.name,
                            "size_bytes": f.stat().st_size,
                        }
                    )
        return 200, {"configs": configs, "total": len(configs)}

    # ── GET /operator/latest-run ───────────────────────────────────────────────

    def _get_latest_run(self) -> tuple[int, dict[str, Any]]:
        runs_root = Path.home() / "metriplane-runs"
        if not runs_root.exists():
            return 200, {"latest_run": None, "runs_dir": str(runs_root)}

        candidates: list[dict[str, Any]] = []
        for d in sorted(runs_root.iterdir()):
            if d.is_dir():
                session = d / "session.jsonl"
                meta = d / "meta.json"
                candidates.append(
                    {
                        "dir": str(d),
                        "name": d.name,
                        "session_exists": session.exists(),
                        "session_size_mb": round(session.stat().st_size / 1e6, 1)
                        if session.exists()
                        else None,
                        "meta_exists": meta.exists(),
                        "mtime": d.stat().st_mtime,
                    }
                )

        candidates.sort(key=lambda x: float(x["mtime"]), reverse=True)

        run_info = None
        if candidates:
            latest = candidates[0]
            # Try to read meta.json for run_id, git_commit
            meta_path = Path(str(latest["dir"])) / "meta.json"
            if meta_path.exists():
                try:
                    meta_data = json.loads(meta_path.read_text())
                    latest["meta"] = meta_data
                except Exception:
                    pass
            run_info = latest

        return 200, {
            "latest_run": run_info,
            "all_runs": candidates[:10],
            "runs_dir": str(runs_root),
        }

    # ── GET /operator/runner-status ────────────────────────────────────────────

    def _get_runner_status(self) -> tuple[int, dict[str, Any]]:
        running = self.executor.is_running()
        job = None
        if running and self.executor.current_job:
            j = self.executor.current_job
            elapsed = (datetime.now() - j["started_at"]).total_seconds()
            job = {
                "job_id": j["job_id"],
                "command_id": j["command_id"],
                "elapsed_s": round(elapsed, 1),
            }
        return 200, {"running": running, "current_job": job}

    # ── POST /operator/create-profile ─────────────────────────────────────────

    def _create_profile(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        name: str = body.get("name", "").strip()
        width_m: float = body.get("width_m", 0.55)
        height_m: float = body.get("height_m", 0.40)
        anchors: list[Any] = body.get("anchors", [])
        cameras: list[str] = body.get("cameras", ["cam0"])  # ["cam0"] or ["cam0","cam1"]
        overwrite: bool = bool(body.get("overwrite", False))

        if not _valid_name(name):
            return 400, {
                "error": "Profile name must be letters/numbers/dash/underscore, 1-64 chars"
            }

        # Enforce local_ prefix for safety (won't overwrite shipped profiles)
        if not name.startswith("local_"):
            name = f"local_{name}"

        if not isinstance(cameras, list) or not cameras:
            return 400, {
                "error": "cameras must be a non-empty list containing cam0 and optionally cam1"
            }
        for cam in cameras:
            if cam not in ("cam0", "cam1"):
                return 400, {
                    "error": (
                        "Invalid camera role in profile. Use camera role names "
                        "'cam0' and optionally 'cam1'; device paths are selected "
                        "in the camera scan step and written into the run config."
                    )
                }

        profile_dir = _profile_dir(self.repo_root, name)

        if profile_dir.exists() and not overwrite:
            return 409, {
                "error": f"Profile '{name}' already exists. Set overwrite=true to replace.",
                "profile": name,
                "path": str(profile_dir.relative_to(self.repo_root)),
            }

        # ── Default anchors if not provided ──────────────────────────────────
        if not anchors:
            w, h = float(width_m), float(height_m)
            anchors = [
                {"id": 0, "world_xy": [0.0, 0.0]},
                {"id": 1, "world_xy": [0.0, h]},
                {"id": 2, "world_xy": [w, 0.0]},
                {"id": 3, "world_xy": [w, h]},
            ]

        # ── Validate anchors ──────────────────────────────────────────────────
        if len(anchors) < 4:
            return 400, {"error": "At least 4 anchors required for homography calibration"}
        for a in anchors:
            if "id" not in a or "world_xy" not in a or len(a["world_xy"]) != 2:
                return 400, {"error": "Each anchor must have id and world_xy: [x, y]"}
            try:
                int(a["id"])
                float(a["world_xy"][0])
                float(a["world_xy"][1])
            except (ValueError, TypeError):
                return 400, {"error": "Anchor id must be int, world_xy must be [float, float]"}

        # ── Create directories ────────────────────────────────────────────────
        profile_dir.mkdir(parents=True, exist_ok=True)
        for cam in cameras:
            (profile_dir / cam).mkdir(exist_ok=True)

        # ── Write anchors.yaml ────────────────────────────────────────────────
        anchors_path = profile_dir / "anchors.yaml"
        anchors_data = {
            "profile": name,
            "board_size": {"width_m": float(width_m), "height_m": float(height_m)},
            "anchors": [
                {"id": int(a["id"]), "world_xy": [float(a["world_xy"][0]), float(a["world_xy"][1])]}
                for a in anchors
            ],
        }
        anchors_path.write_text(yaml.dump(anchors_data, default_flow_style=False), encoding="utf-8")

        created_dirs = [str(profile_dir.relative_to(self.repo_root))]
        for cam in cameras:
            created_dirs.append(str((profile_dir / cam).relative_to(self.repo_root)))

        return 200, {
            "profile": name,
            "path": str(profile_dir.relative_to(self.repo_root)),
            "anchors_path": str(anchors_path.relative_to(self.repo_root)),
            "anchors_count": len(anchors),
            "board_size": {"width_m": float(width_m), "height_m": float(height_m)},
            "cameras": cameras,
            "created_dirs": created_dirs,
        }

    # ── POST /operator/write-zones ─────────────────────────────────────────────

    def _write_zones(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        profile: str = body.get("profile", "").strip()
        zones: list[Any] = body.get("zones", [])
        overwrite: bool = bool(body.get("overwrite", False))

        if not _valid_name(profile):
            return 400, {"error": "Invalid profile name"}

        profile_dir = _profile_dir(self.repo_root, profile)
        if not profile_dir.exists():
            return 404, {"error": f"Profile not found: {profile}"}

        zones_path = profile_dir / "zones.yaml"
        if zones_path.exists() and not overwrite:
            return 409, {
                "error": f"zones.yaml already exists in profile '{profile}'. Set overwrite=true to replace.",
                "path": str(zones_path.relative_to(self.repo_root)),
            }

        if not zones:
            return 400, {"error": "At least one zone required"}

        # Validate zone structure
        zone_list = []
        for z in zones:
            if not isinstance(z, dict):
                return 400, {"error": "Each zone must be a JSON object"}
            zname = str(z.get("name", "")).strip()
            if not zname or not _valid_name(zname):
                return 400, {"error": f"Invalid zone name: {zname!r}"}
            polygon = z.get("polygon", [])
            if len(polygon) < 3:
                return 400, {"error": f"Zone '{zname}' must have at least 3 vertices"}
            for pt in polygon:
                if len(pt) != 2:
                    return 400, {"error": f"Zone '{zname}' vertex must be [x, y]"}
            zone_list.append(
                {
                    "name": zname,
                    "polygon": [[float(p[0]), float(p[1])] for p in polygon],
                }
            )

        zones_data = {"zones": zone_list}
        zones_path.write_text(yaml.dump(zones_data, default_flow_style=False), encoding="utf-8")

        return 200, {
            "profile": profile,
            "zones_path": str(zones_path.relative_to(self.repo_root)),
            "zone_count": len(zone_list),
            "zones": [z["name"] for z in zone_list],
        }

    # ── POST /operator/save-config ─────────────────────────────────────────────

    def _save_config(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        filename: str = body.get("filename", "").strip()
        config_data: dict[str, Any] = body.get("config", {})
        overwrite: bool = bool(body.get("overwrite", False))

        if not filename:
            return 400, {"error": "filename required"}
        # Filename must be a safe name + .yaml
        base = filename.replace(".yaml", "")
        if not _valid_name(base):
            return 400, {"error": "Filename must be safe name + .yaml"}

        local_dir = self.repo_root / "configs" / "local"
        local_dir.mkdir(parents=True, exist_ok=True)

        out_path = local_dir / (base + ".yaml")
        if out_path.exists() and not overwrite:
            # Return conflict with preview
            return 409, {
                "error": f"Config '{filename}' already exists in configs/local/. Set overwrite=true.",
                "path": str(out_path.relative_to(self.repo_root)),
            }

        if not config_data:
            return 400, {"error": "config data required"}

        # Validate camera schema before writing — prevents silent failures at run time.
        cam_error = _validate_camera_config(config_data, self.repo_root)
        if cam_error:
            return 400, {
                "error": f"Config camera schema invalid: {cam_error}",
                "hint": (
                    "Regenerate the config via the UI (Step 8) or check that "
                    "each camera entry uses 'name', 'device'/'index', and 'mapping_file'."
                ),
            }

        out_path.write_text(yaml.dump(config_data, default_flow_style=False), encoding="utf-8")

        # Compute hash like metriplane does
        content = out_path.read_bytes()
        config_hash = hashlib.sha256(content).hexdigest()

        return 200, {
            "path": str(out_path.relative_to(self.repo_root)),
            "filename": out_path.name,
            "size_bytes": len(content),
            "config_hash": config_hash,
        }

    # ── POST /operator/calibrate ───────────────────────────────────────────────

    def _calibrate(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        profile: str = body.get("profile", "").strip()
        cam_name: str = body.get("cam", "cam0").strip()  # "cam0" or "cam1"
        camera_path: str = str(body.get("camera", "0")).strip()
        timeout_s: int = int(body.get("timeout_s", 30))
        max_frames: int = int(body.get("max_frames", 600))
        no_preview: bool = bool(body.get("no_preview", True))

        if not _valid_name(profile):
            return 400, {"error": "Invalid profile name"}
        if cam_name not in ("cam0", "cam1"):
            return 400, {"error": "cam must be cam0 or cam1"}
        if not _safe_camera(camera_path):
            return 400, {
                "error": "Invalid camera path. Must be /dev/video*, /dev/v4l/by-id/* or integer 0-99"
            }
        if not (5 <= timeout_s <= 300):
            return 400, {"error": "timeout_s must be 5-300"}
        if not (10 <= max_frames <= 3000):
            return 400, {"error": "max_frames must be 10-3000"}

        profile_dir = _profile_dir(self.repo_root, profile)
        anchors_path = profile_dir / "anchors.yaml"
        if not profile_dir.exists():
            return 404, {"error": f"Profile not found: {profile}"}
        if not anchors_path.exists():
            return 400, {
                "error": f"anchors.yaml not found in profile '{profile}'. Create the profile first."
            }

        # ── cv2 preflight — fail fast before submitting a doomed calibration job ──
        py_exe = self._python
        cv2_ok, _cv2_ver, _aruco = _check_cv2_available(py_exe)
        if not cv2_ok:
            return 400, {
                "error": "OpenCV missing from runner Python",
                "python_executable": py_exe,
                "fix_command": (
                    "source .venv/bin/activate && python -m pip install opencv-contrib-python"
                ),
                "hint": "Restart ./tools/dashboard_runner.sh after installing.",
            }

        out_dir = profile_dir / cam_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "mapping_raw.yaml"

        # calibrate_planar_homography.py passes --cam directly to cv2.VideoCapture(),
        # which requires an integer index.  Convert /dev/videoN → N now.
        cv2_cam, cam_err = _resolve_cv2_index(camera_path)
        if cam_err:
            return 400, {"error": cam_err}

        # Build safe command (no shell=True, no user data in shell-sensitive positions)
        script = self.repo_root / "tools" / "calibrate_planar_homography.py"
        command = [
            py_exe,
            str(script),
            "--cam",
            cv2_cam,
            "--anchors",
            str(anchors_path),
            "--out",
            str(out_path),
            "--timeout-s",
            str(timeout_s),
            "--max-frames",
            str(max_frames),
        ]
        if no_preview:
            command.append("--no-preview")

        command_display = " ".join(str(x) for x in command)

        try:
            job_id = self.executor.execute(
                command_id=f"calibrate-{cam_name}",
                command=command,
                timeout_s=timeout_s + 15,
            )
        except ValueError as exc:
            return 409, {"error": str(exc)}

        return 200, {
            "job_id": job_id,
            "profile": profile,
            "cam": cam_name,
            "camera_path": camera_path,
            "out_path": str(out_path.relative_to(self.repo_root)),
            "command_preview": command_display,
        }

    # ── POST /operator/validate-alignment ─────────────────────────────────────
    #
    # Default: planar-only validation via report_alignment.py.
    # --intrinsics-* are optional there (default=None); works straight after
    # calibrate_planar_homography.py without any extra intrinsics step.
    #
    # If intrinsics files ARE present in the profile, they are passed for
    # improved per-ID delta reporting.  Intrinsics are never required.

    def _validate_alignment(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        profile: str = body.get("profile", "").strip()
        cam0_path: str = str(body.get("cam0", "0")).strip()
        cam1_path: str = str(body.get("cam1", "2")).strip()

        if not _valid_name(profile):
            return 400, {"error": "Invalid profile name"}
        for cp in (cam0_path, cam1_path):
            if not _safe_camera(cp):
                return 400, {"error": f"Invalid camera: {cp}"}

        profile_dir = _profile_dir(self.repo_root, profile)
        mapping0 = profile_dir / "cam0" / "mapping_raw.yaml"
        mapping1 = profile_dir / "cam1" / "mapping_raw.yaml"
        anchors = profile_dir / "anchors.yaml"

        if not mapping0.exists():
            return 400, {
                "error": "cam0 mapping_raw.yaml not found. Run Calibrate cam0 (Step 5) first."
            }
        if not mapping1.exists():
            return 400, {
                "error": "cam1 mapping_raw.yaml not found. Run Calibrate cam1 (Step 5) first."
            }
        if not anchors.exists():
            return 400, {"error": "anchors.yaml not found in profile. Complete Step 4 first."}

        # Use report_alignment.py — intrinsics are optional (default=None) there.
        # This is the planar-only path: works after homography calibration only.
        script = self.repo_root / "tools" / "report_alignment.py"
        if not script.exists():
            return 500, {"error": "tools/report_alignment.py not found in repo"}

        cv2_cam0, err0 = _resolve_cv2_index(cam0_path)
        cv2_cam1, err1 = _resolve_cv2_index(cam1_path)
        if err0:
            return 400, {"error": f"cam0: {err0}"}
        if err1:
            return 400, {"error": f"cam1: {err1}"}

        assert cv2_cam0 is not None and cv2_cam1 is not None
        command: list[str] = [
            self._python,
            str(script),
            "--cam0",
            cv2_cam0,
            "--cam1",
            cv2_cam1,
            "--mapping-cam0",
            str(mapping0),
            "--mapping-cam1",
            str(mapping1),
            "--anchors",
            str(anchors),
        ]

        # Attach intrinsics if they already exist (improves undistort accuracy)
        intrs_cam0 = profile_dir / "cam0" / "intrinsics.yaml"
        intrs_cam1 = profile_dir / "cam1" / "intrinsics.yaml"
        has_intrinsics = intrs_cam0.exists() and intrs_cam1.exists()
        if has_intrinsics:
            command += ["--intrinsics-cam0", str(intrs_cam0), "--intrinsics-cam1", str(intrs_cam1)]

        command_display = " ".join(str(x) for x in command)

        try:
            job_id = self.executor.execute(
                command_id="validate-alignment",
                command=command,
                timeout_s=30,
            )
        except ValueError as exc:
            return 409, {"error": str(exc)}

        return 200, {
            "job_id": job_id,
            "profile": profile,
            "mode": "planar" if not has_intrinsics else "planar+intrinsics",
            "has_intrinsics": has_intrinsics,
            "command_preview": command_display,
        }

    # ── POST /operator/validate-alignment-full ─────────────────────────────────
    #
    # Full undistort diagnostic via debug_alignment.py.
    # Requires intrinsics.yaml for both cameras.  Returns a structured 400 when
    # they are missing — listing exact paths and the command to generate them.

    def _full_alignment_check(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        profile: str = body.get("profile", "").strip()
        cam0_path: str = str(body.get("cam0", "0")).strip()
        cam1_path: str = str(body.get("cam1", "2")).strip()

        if not _valid_name(profile):
            return 400, {"error": "Invalid profile name"}
        for cp in (cam0_path, cam1_path):
            if not _safe_camera(cp):
                return 400, {"error": f"Invalid camera: {cp}"}

        profile_dir = _profile_dir(self.repo_root, profile)
        mapping0 = profile_dir / "cam0" / "mapping_raw.yaml"
        mapping1 = profile_dir / "cam1" / "mapping_raw.yaml"
        anchors = profile_dir / "anchors.yaml"
        intrs_cam0 = profile_dir / "cam0" / "intrinsics.yaml"
        intrs_cam1 = profile_dir / "cam1" / "intrinsics.yaml"

        if not mapping0.exists():
            return 400, {"error": "cam0 mapping_raw.yaml not found. Calibrate cam0 first."}
        if not mapping1.exists():
            return 400, {"error": "cam1 mapping_raw.yaml not found. Calibrate cam1 first."}
        if not anchors.exists():
            return 400, {"error": "anchors.yaml not found in profile."}

        missing_intrs: list[str] = []
        if not intrs_cam0.exists():
            missing_intrs.append(str(intrs_cam0.relative_to(self.repo_root)))
        if not intrs_cam1.exists():
            missing_intrs.append(str(intrs_cam1.relative_to(self.repo_root)))
        if missing_intrs:
            return 400, {
                "error": "Full undistort check requires intrinsics.yaml for each camera.",
                "missing_intrinsics": missing_intrs,
                "generate_command": (
                    "python tools/calibrate_intrinsics_chessboard.py "
                    "--cam <cam_index> --out <profile_dir>/cam0/intrinsics.yaml"
                ),
                "hint": (
                    "Intrinsics calibration is not required for the standard planar workflow. "
                    "Use 'Validate Alignment' (report_alignment.py) instead if you do not "
                    "need undistort diagnostics. "
                    "See docs/calibration_runbook.md § Intrinsics Calibration."
                ),
                "can_skip": True,
            }

        script = self.repo_root / "tools" / "debug_alignment.py"
        if not script.exists():
            return 500, {"error": "tools/debug_alignment.py not found"}

        cv2_cam0, err0 = _resolve_cv2_index(cam0_path)
        cv2_cam1, err1 = _resolve_cv2_index(cam1_path)
        if err0:
            return 400, {"error": f"cam0: {err0}"}
        if err1:
            return 400, {"error": f"cam1: {err1}"}

        command = [
            self._python,
            str(script),
            "--cam0",
            cv2_cam0,
            "--cam1",
            cv2_cam1,
            "--mapping-cam0",
            str(mapping0),
            "--mapping-cam1",
            str(mapping1),
            "--intrinsics-cam0",
            str(intrs_cam0),
            "--intrinsics-cam1",
            str(intrs_cam1),
            "--anchors",
            str(anchors),
        ]
        command_display = " ".join(str(x) for x in command)

        try:
            job_id = self.executor.execute(
                command_id="full-alignment-check",
                command=command,
                timeout_s=30,
            )
        except ValueError as exc:
            return 409, {"error": str(exc)}

        return 200, {
            "job_id": job_id,
            "profile": profile,
            "mode": "full-undistort",
            "command_preview": command_display,
        }

    # ── POST /operator/start-fusion ───────────────────────────────────────────

    def _start_fusion(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        config: str = body.get("config", "").strip()
        duration_s: int = int(body.get("duration_s", 60))
        run_id: str = body.get("run_id", "").strip()
        backend: str = body.get("backend", "cpu").strip()

        # Validate config
        config_path = _validate_config_relative(self.repo_root, config)
        if config_path is None:
            return 400, {"error": "Config must be a relative path under configs/"}
        if not config_path.exists():
            return 404, {"error": f"Config file not found: {config}"}

        # Validate duration
        if not (5 <= duration_s <= 7200):
            return 400, {"error": "duration_s must be 5-7200"}

        # Validate run_id
        if run_id and not SAFE_RUNID_RE.match(run_id):
            return 400, {"error": "run_id must be letters/numbers/dash/underscore"}

        # Validate backend
        if backend not in ("cpu", "gpu"):
            return 400, {"error": "backend must be cpu or gpu"}

        # Auto generate run_id if not provided
        if not run_id:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_id = f"operator_run_{ts}"

        runs_dir = str(Path.home() / "metriplane-runs")

        command = [
            self._python,
            "-m",
            "metriplane.run_fusion",
            "--config",
            str(config_path),
            "--runs-dir",
            runs_dir,
            "--run-id",
            run_id,
            "--duration-s",
            str(duration_s),
        ]

        command_display = " ".join(str(x) for x in command)

        try:
            job_id = self.executor.execute(
                command_id="run-fusion-operator",
                command=command,
                timeout_s=duration_s + 60,
            )
        except ValueError as exc:
            return 409, {"error": str(exc)}

        return 200, {
            "job_id": job_id,
            "run_id": run_id,
            "config": config,
            "duration_s": duration_s,
            "backend": backend,
            "runs_dir": runs_dir,
            "command_preview": command_display,
        }

    # ── POST /operator/generate-report ────────────────────────────────────────

    def _generate_report(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        report_type: str = body.get("type", "").strip()  # "zones" or "id-stability"
        session_path: str = body.get("session", "").strip()
        out_prefix: str = body.get("prefix", "operator").strip()
        profile: str = body.get("profile", "").strip()

        if report_type not in ("zones", "id-stability"):
            return 400, {"error": "type must be 'zones' or 'id-stability'"}

        # Validate session path: must be in ~/metriplane-runs/ or absolute path resolving there
        session = Path(session_path).expanduser().resolve()
        runs_root = (Path.home() / "metriplane-runs").resolve()
        if not _is_relative_to(session, runs_root):
            return 400, {"error": "session must be a path under ~/metriplane-runs/"}
        if not session.exists():
            return 404, {"error": f"Session file not found: {session}"}

        # Validate prefix
        if not _valid_name(out_prefix):
            return 400, {"error": "prefix must be safe name"}

        evidence_dir = self.repo_root / "evidence" / "experiments"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        if report_type == "zones":
            # Validate profile for zones report
            if profile and not _valid_name(profile):
                return 400, {"error": "Invalid profile name"}

            script = self.repo_root / "tools" / "zones_report_jsonl.py"
            if not script.exists():
                return 500, {"error": "tools/zones_report_jsonl.py not found"}

            command = [
                self._python,
                str(script),
                str(session),
                "--out",
                str(evidence_dir),
                "--prefix",
                out_prefix,
            ]
            if profile:
                profile_dir = _profile_dir(self.repo_root, profile)
                zones_yaml = profile_dir / "zones.yaml"
                if zones_yaml.exists():
                    command += ["--zones", str(zones_yaml)]

        else:  # id-stability
            script = self.repo_root / "tools" / "analyze_id_stability_jsonl.py"
            if not script.exists():
                return 500, {"error": "tools/analyze_id_stability_jsonl.py not found"}

            out_csv = evidence_dir / f"{out_prefix}_id_stability.csv"
            command = [
                self._python,
                str(script),
                str(session),
                "--out",
                str(out_csv),
            ]

        command_display = " ".join(str(x) for x in command)

        try:
            job_id = self.executor.execute(
                command_id=f"generate-{report_type}",
                command=command,
                timeout_s=120,
            )
        except ValueError as exc:
            return 409, {"error": str(exc)}

        return 200, {
            "job_id": job_id,
            "type": report_type,
            "session": str(session),
            "out_dir": str(evidence_dir),
            "command_preview": command_display,
        }

    # ── POST /operator/checksum ────────────────────────────────────────────────

    def _checksum(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        path: str = body.get("path", "").strip()

        file_path = Path(path).expanduser().resolve()
        runs_root = (Path.home() / "metriplane-runs").resolve()
        evidence_root = (self.repo_root / "evidence").resolve()

        # Only checksum files in ~/metriplane-runs/ or evidence/
        if not (_is_relative_to(file_path, runs_root) or _is_relative_to(file_path, evidence_root)):
            return 400, {"error": "Can only checksum files under ~/metriplane-runs/ or evidence/"}

        if not file_path.exists():
            return 404, {"error": f"File not found: {path}"}
        if not file_path.is_file():
            return 400, {"error": "Path is not a file"}

        stat = file_path.stat()
        size_mb = round(stat.st_size / 1e6, 2)

        # Stream hash for large files
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        sha256 = h.hexdigest()

        return 200, {
            "path": path,
            "sha256": sha256,
            "size_mb": size_mb,
            "size_bytes": stat.st_size,
        }

    # ── Sentinel command-center (read-only views) ──────────────────────────────
    #
    # These expose the Sentinel artifacts (objects, incidents, traces, camera trust)
    # and the grounded assistant to the operator dashboard. All read-only. A run dir
    # may be passed explicitly (validated to live under ~/metriplane-runs or the repo
    # evidence/ tree); otherwise the latest run under ~/metriplane-runs is used.

    def _cc_allowed_roots(self) -> list[Path]:
        return [
            (Path.home() / "metriplane-runs").resolve(),
            (self.repo_root / "evidence").resolve(),
            (self.repo_root / "runs").resolve(),
        ]

    def _cc_resolve_run_dir(self, body: dict[str, Any]) -> Optional[Path]:
        requested = (body or {}).get("run_dir")
        if requested:
            p = Path(requested).expanduser().resolve()
            if any(p == r or r in p.parents for r in self._cc_allowed_roots()) and p.is_dir():
                return p
            return None
        # Fall back to the latest run under ~/metriplane-runs. Prefer runs with
        # Command Center/Sentinel artifacts so a generic runtime session does not
        # hide the incident demo or an operator review run.
        runs_root = Path.home() / "metriplane-runs"
        if not runs_root.exists():
            return None
        command_center_markers = (
            "incident.json",
            "sentinel_summary.json",
            "camera_trust.json",
            "alerts.jsonl",
            "objects.yaml",
        )
        generic_runtime_markers = ("session_excerpt.jsonl", "session.jsonl")

        def with_markers(markers: tuple[str, ...]) -> list[Path]:
            return [
                d
                for d in runs_root.iterdir()
                if d.is_dir() and any((d / marker).exists() for marker in markers)
            ]

        dirs = with_markers(command_center_markers) or with_markers(generic_runtime_markers)
        if not dirs:
            return None
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return dirs[0].resolve()

    def _cc_live_summary(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {
                "run_dir": None,
                "objects_count": 0,
                "incidents_count": 0,
                "alerts_count": 0,
                "open_incidents_count": 0,
                "health": {"overall": "NO_DATA"},
            }
        from metriplane.runner.command_center_api import get_live_summary

        return 200, get_live_summary(run)

    def _cc_objects(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {"objects": []}
        from metriplane.runner.command_center_api import get_objects

        return 200, {"objects": get_objects(run), "run_dir": str(run)}

    def _cc_incidents(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {"incidents": []}
        from metriplane.runner.command_center_api import get_incidents

        return 200, {"incidents": get_incidents(run), "run_dir": str(run)}

    def _cc_traces(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {"traces": []}
        from metriplane.runner.command_center_api import get_traces

        object_id = (body or {}).get("object_id")
        return 200, {"traces": get_traces(run, object_id), "run_dir": str(run)}

    def _cc_camera_trust(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {"camera_trust": None}
        from metriplane.camera_trust.export import read_camera_trust_report

        ct = run / "camera_trust.json"
        if not ct.exists():
            return 200, {
                "camera_trust": None,
                "run_dir": str(run),
                "note": "no camera_trust.json in this run",
            }
        try:
            return 200, {
                "camera_trust": read_camera_trust_report(ct).model_dump(),
                "run_dir": str(run),
            }
        except Exception as exc:
            return 200, {"camera_trust": None, "error": str(exc)}

    def _cc_frames(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {"frames": [], "incidents": []}
        from metriplane.runner.command_center_api import get_frames

        data = get_frames(run)
        data["run_dir"] = str(run)
        return 200, data

    def _cc_ask(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        question = (body or {}).get("question", "").strip()
        if not question:
            return 400, {"error": "missing 'question'"}
        run = self._cc_resolve_run_dir(body)
        if run is None:
            return 200, {
                "answer": "No run data available to answer from.",
                "intent": "unknown",
                "citations": [],
                "limitations": ["no run dir resolved"],
            }
        from metriplane.assistant.answer import answer_question

        ans = answer_question(question, run)
        return 200, ans.model_dump()
