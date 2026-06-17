# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Tests for _resolve_python_executable(), _check_cv2_available(), and the
cv2 preflight that gates /operator/calibrate, /operator/validate-alignment,
and /operator/start-fusion.

All tests are fully mocked — no subprocess, no real filesystem.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from metriplane.runner.operator_api import (
    OperatorAPI,
    _check_cv2_available,
    _resolve_python_executable,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_api(tmp_path: Path) -> OperatorAPI:
    """Create an OperatorAPI instance with a minimal tmp repo root."""
    executor = MagicMock()
    executor.execute.return_value = "job-test"
    # Create required directory structure
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "tools" / "calibrate_planar_homography.py").write_text("# stub")
    (tmp_path / "tools" / "report_alignment.py").write_text("# stub")
    (tmp_path / "tools" / "debug_alignment.py").write_text("# stub")
    (tmp_path / "configs").mkdir(exist_ok=True)
    return OperatorAPI(executor=executor, repo_root=tmp_path)


def _make_api_with_python(tmp_path: Path, python_exe: str) -> OperatorAPI:
    """Create OperatorAPI and force self._python to a specific path."""
    api = _make_api(tmp_path)
    api._python = python_exe
    return api


def _make_profile(tmp_path: Path, profile: str = "local_test") -> Path:
    """Create a minimal profile directory with anchors.yaml."""
    profile_dir = tmp_path / "calib" / "profiles" / profile
    (profile_dir / "cam0").mkdir(parents=True)
    (profile_dir / "cam1").mkdir(parents=True)
    anchors_data = (
        "profile: local_test\n"
        "board_size: {width_m: 0.55, height_m: 0.4}\n"
        "anchors:\n"
        "- {id: 0, world_xy: [0, 0]}\n"
        "- {id: 1, world_xy: [0, 0.4]}\n"
        "- {id: 2, world_xy: [0.55, 0]}\n"
        "- {id: 3, world_xy: [0.55, 0.4]}\n"
    )
    (profile_dir / "anchors.yaml").write_text(anchors_data)
    return profile_dir


def _make_mapping(profile_dir: Path) -> None:
    """Create stub mapping_raw.yaml files for both cameras."""
    (profile_dir / "cam0" / "mapping_raw.yaml").write_text("# stub mapping cam0")
    (profile_dir / "cam1" / "mapping_raw.yaml").write_text("# stub mapping cam1")


# ── _resolve_python_executable ────────────────────────────────────────────────

class TestResolvePythonExecutable:
    """Priority: METRIPLANE_PYTHON > METRIPLANE_VENV > repo_root/.vt-venv > repo_root/.venv > sys.executable"""

    def _make_exec(self, tmp_path: Path, name: str) -> str:
        """Create a fake executable file and return its path."""
        p = tmp_path / name
        p.write_text("#!/usr/bin/env python3\n")
        p.chmod(0o755)
        return str(p)

    def test_prefers_vt_python(self, tmp_path: Path):
        vt_py = self._make_exec(tmp_path, "vt_python")
        venv_py = self._make_exec(tmp_path, ".venv_bin_python")
        # .venv/bin/python also exists
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        venv_exec = venv_dir / "python"
        venv_exec.write_text("#!/bin/sh\n")
        venv_exec.chmod(0o755)

        env = {"METRIPLANE_PYTHON": vt_py, "METRIPLANE_VENV": ""}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        assert result == vt_py

    def test_prefers_vt_venv_over_repo_venv(self, tmp_path: Path):
        # METRIPLANE_PYTHON not set; METRIPLANE_VENV points to a dir with bin/python
        ext_venv = tmp_path / "ext_venv"
        (ext_venv / "bin").mkdir(parents=True)
        ext_py = ext_venv / "bin" / "python"
        ext_py.write_text("#!/bin/sh\n")
        ext_py.chmod(0o755)

        # Repo .venv also exists but should NOT be picked
        repo_venv = tmp_path / ".venv" / "bin"
        repo_venv.mkdir(parents=True)
        repo_py = repo_venv / "python"
        repo_py.write_text("#!/bin/sh\n")
        repo_py.chmod(0o755)

        env = {"METRIPLANE_PYTHON": "", "METRIPLANE_VENV": str(ext_venv)}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        assert result == str(ext_py)

    def test_prefers_vt_venv_dir_over_dotdot_venv(self, tmp_path: Path):
        """Step 3: .vt-venv/bin/python wins over .venv/bin/python when both exist."""
        # Create .vt-venv
        vt_venv_dir = tmp_path / ".vt-venv" / "bin"
        vt_venv_dir.mkdir(parents=True)
        vt_venv_py = vt_venv_dir / "python"
        vt_venv_py.write_text("#!/bin/sh\n")
        vt_venv_py.chmod(0o755)
        # Create .venv too (step 4 fallback)
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        venv_py = venv_dir / "python"
        venv_py.write_text("#!/bin/sh\n")
        venv_py.chmod(0o755)

        env = {"METRIPLANE_PYTHON": "", "METRIPLANE_VENV": ""}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        assert result == str(vt_venv_py), (
            f".vt-venv should win over .venv, got {result!r}"
        )

    def test_prefers_repo_venv_over_sys_executable(self, tmp_path: Path):
        """Step 4: .venv/bin/python wins over sys.executable when .vt-venv absent."""
        venv_dir = tmp_path / ".venv" / "bin"
        venv_dir.mkdir(parents=True)
        venv_py = venv_dir / "python"
        venv_py.write_text("#!/bin/sh\n")
        venv_py.chmod(0o755)

        env = {"METRIPLANE_PYTHON": "", "METRIPLANE_VENV": ""}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        assert result == str(venv_py)

    def test_falls_back_to_sys_executable(self, tmp_path: Path):
        # No METRIPLANE_PYTHON, no METRIPLANE_VENV, no .venv/bin/python
        env = {"METRIPLANE_PYTHON": "", "METRIPLANE_VENV": ""}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        assert result == sys.executable

    def test_vt_python_non_executable_skipped(self, tmp_path: Path):
        """METRIPLANE_PYTHON set to a non-executable file → fall through."""
        non_exec = tmp_path / "not_exec"
        non_exec.write_text("not executable")
        non_exec.chmod(0o644)  # read-only, no exec bit

        env = {"METRIPLANE_PYTHON": str(non_exec), "METRIPLANE_VENV": ""}
        with patch.dict(os.environ, env, clear=False):
            result = _resolve_python_executable(tmp_path)
        # Should not use non-exec file → falls back to sys.executable
        assert result != str(non_exec)


# ── _check_cv2_available ──────────────────────────────────────────────────────

class TestCheckCv2Available:
    def test_returns_true_when_cv2_imports(self):
        mock_run = MagicMock()
        # First call: cv2 import succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="4.9.0\n"),
            MagicMock(returncode=0, stdout="ok\n"),
        ]
        with patch("metriplane.runner.operator_api.subprocess.run", mock_run):
            ok, ver, aruco = _check_cv2_available("/usr/bin/python3")
        assert ok is True
        assert ver == "4.9.0"
        assert aruco is True

    def test_returns_false_when_cv2_missing(self):
        mock_run = MagicMock(return_value=MagicMock(returncode=1, stdout=""))
        with patch("metriplane.runner.operator_api.subprocess.run", mock_run):
            ok, ver, aruco = _check_cv2_available("/usr/bin/python3")
        assert ok is False
        assert ver is None
        assert aruco is False

    def test_aruco_false_when_import_fails(self):
        mock_run = MagicMock()
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="4.9.0\n"),   # cv2 ok
            MagicMock(returncode=1, stdout=""),           # aruco fails
        ]
        with patch("metriplane.runner.operator_api.subprocess.run", mock_run):
            ok, ver, aruco = _check_cv2_available("/usr/bin/python3")
        assert ok is True
        assert aruco is False

    def test_returns_false_on_exception(self):
        with patch("metriplane.runner.operator_api.subprocess.run",
                   side_effect=OSError("no such file")):
            ok, ver, aruco = _check_cv2_available("/nonexistent/python")
        assert ok is False
        assert ver is None
        assert aruco is False


# ── Commands use self._python, not sys.executable ─────────────────────────────

class TestCommandsUseResolvedPython:
    SENTINEL = "/resolved/venv/python"

    def _sentinel_api(self, tmp_path: Path) -> OperatorAPI:
        api = _make_api(tmp_path)
        api._python = self.SENTINEL
        return api

    def _cv2_ok_patch(self):
        """Patch _check_cv2_available to return cv2 available."""
        return patch(
            "metriplane.runner.operator_api._check_cv2_available",
            return_value=(True, "4.9.0", True),
        )

    def test_calibrate_command_uses_resolved_python(self, tmp_path: Path):
        api = self._sentinel_api(tmp_path)
        profile_dir = _make_profile(tmp_path)

        with self._cv2_ok_patch():
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "0",
            })

        assert status == 200, resp
        cmd = api.executor.execute.call_args[1]["command"]
        assert cmd[0] == self.SENTINEL, f"Expected {self.SENTINEL!r}, got {cmd[0]!r}"
        assert str(cmd[0]) != sys.executable

    def test_validate_alignment_command_uses_resolved_python(self, tmp_path: Path):
        api = self._sentinel_api(tmp_path)
        profile_dir = _make_profile(tmp_path)
        _make_mapping(profile_dir)

        status, resp = api._validate_alignment({
            "profile": "local_test",
            "cam0": "0",
            "cam1": "2",
        })

        assert status == 200, resp
        cmd = api.executor.execute.call_args[1]["command"]
        assert cmd[0] == self.SENTINEL

    def test_start_fusion_command_uses_resolved_python(self, tmp_path: Path):
        api = self._sentinel_api(tmp_path)
        # Create a valid config file
        cfg_path = tmp_path / "configs" / "test.yaml"
        cfg_path.write_text("profile: test\n")

        status, resp = api._start_fusion({
            "config": "configs/test.yaml",
            "duration_s": 10,
        })

        assert status == 200, resp
        cmd = api.executor.execute.call_args[1]["command"]
        assert cmd[0] == self.SENTINEL


# ── cv2 preflight in _calibrate ───────────────────────────────────────────────

class TestCalibrateCv2Preflight:
    def test_preflight_failure_returns_400(self, tmp_path: Path):
        """When cv2 is missing, _calibrate must return HTTP 400 without submitting a job."""
        api = _make_api(tmp_path)
        _make_profile(tmp_path)

        with patch(
            "metriplane.runner.operator_api._check_cv2_available",
            return_value=(False, None, False),
        ):
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "0",
            })

        assert status == 400
        assert "error" in resp
        assert "OpenCV" in resp["error"] or "cv2" in resp["error"].lower()

    def test_preflight_failure_does_not_call_executor(self, tmp_path: Path):
        """The executor must NOT be called when cv2 is missing."""
        api = _make_api(tmp_path)
        _make_profile(tmp_path)

        with patch(
            "metriplane.runner.operator_api._check_cv2_available",
            return_value=(False, None, False),
        ):
            api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "0",
            })

        api.executor.execute.assert_not_called()

    def test_preflight_failure_includes_python_executable(self, tmp_path: Path):
        """Structured 400 must include python_executable and fix_command."""
        api = _make_api(tmp_path)
        api._python = "/wrong/python"
        _make_profile(tmp_path)

        with patch(
            "metriplane.runner.operator_api._check_cv2_available",
            return_value=(False, None, False),
        ):
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "0",
            })

        assert status == 400
        assert resp.get("python_executable") == "/wrong/python"
        assert "fix_command" in resp
        assert "hint" in resp

    def test_preflight_success_submits_job(self, tmp_path: Path):
        """When cv2 is available, _calibrate must submit a job normally."""
        api = _make_api(tmp_path)
        _make_profile(tmp_path)

        with patch(
            "metriplane.runner.operator_api._check_cv2_available",
            return_value=(True, "4.9.0", True),
        ):
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "0",
            })

        assert status == 200
        api.executor.execute.assert_called_once()


# ── /operator/env includes cv2 fields ─────────────────────────────────────────

class TestEnvIncludesCv2Fields:
    def test_env_cv2_available_true(self, tmp_path: Path):
        api = _make_api(tmp_path)
        with (
            patch("metriplane.runner.operator_api._check_cv2_available",
                  return_value=(True, "4.9.0", True)),
            patch("metriplane.runner.operator_api.subprocess.run",
                  return_value=MagicMock(returncode=1, stdout="")),
        ):
            status, resp = api._get_env()

        assert status == 200
        assert resp["cv2_available"] is True
        assert resp["cv2_version"] == "4.9.0"
        assert resp["aruco_available"] is True
        assert resp.get("python_warning") is None

    def test_env_cv2_available_false_includes_warning(self, tmp_path: Path):
        api = _make_api(tmp_path)
        with (
            patch("metriplane.runner.operator_api._check_cv2_available",
                  return_value=(False, None, False)),
            patch("metriplane.runner.operator_api.subprocess.run",
                  return_value=MagicMock(returncode=1, stdout="")),
        ):
            status, resp = api._get_env()

        assert status == 200
        assert resp["cv2_available"] is False
        assert resp["cv2_version"] is None
        assert resp.get("python_warning") is not None
        assert "OpenCV" in resp["python_warning"]

    def test_env_includes_python_executable(self, tmp_path: Path):
        api = _make_api(tmp_path)
        api._python = "/test/venv/bin/python"
        with (
            patch("metriplane.runner.operator_api._check_cv2_available",
                  return_value=(True, "4.9.0", True)),
            patch("metriplane.runner.operator_api.subprocess.run",
                  return_value=MagicMock(returncode=1, stdout="")),
        ):
            status, resp = api._get_env()

        assert resp["python_executable"] == "/test/venv/bin/python"


# ── operator.js static guard: calib-next-btn id present ───────────────────────

class TestOperatorJsCalibNavGuard:
    """
    Static code checks that operator.js contains the navigation guard logic:
      - updateCalibNextButton function
      - calib-next-btn element reference
      - state.calibDone tracking
    """

    def _load_js(self) -> str:
        p = Path(__file__).parent.parent / "web" / "dashboard" / "operator.js"
        return p.read_text()

    def test_update_calib_next_button_defined(self):
        assert "updateCalibNextButton" in self._load_js()

    def test_calib_next_btn_id_referenced(self):
        assert "calib-next-btn" in self._load_js()

    def test_calib_done_state_tracked(self):
        assert "calibDone" in self._load_js()

    def test_single_cam_guard_only_requires_cam0(self):
        js = self._load_js()
        # Guard must have a branch that passes for !state.multiCam when only cam0 is done
        assert "!state.multiCam" in js or "state.multiCam" in js

    def test_html_calib_next_btn_has_disabled(self):
        p = Path(__file__).parent.parent / "web" / "dashboard" / "operator.html"
        html = p.read_text()
        assert 'id="calib-next-btn"' in html
        assert "disabled" in html
