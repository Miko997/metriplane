# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Tests for camera path → cv2 integer index conversion.

calibrate_planar_homography.py and debug_alignment.py pass the --cam / --cam0 /
--cam1 arguments directly to cv2.VideoCapture(), which requires an integer.
Passing '/dev/video0' causes argparse/cv2 to fail with exit code 2.

_resolve_cv2_index() in operator_api.py performs this conversion.
These tests verify every supported and unsupported path format.
"""

import pytest
from metriplane.runner.operator_api import _resolve_cv2_index


class TestResolveCv2Index:
    # ── Integer passthrough ───────────────────────────────────────────────────

    def test_integer_zero(self):
        idx, err = _resolve_cv2_index("0")
        assert idx == "0"
        assert err is None

    def test_integer_two(self):
        idx, err = _resolve_cv2_index("2")
        assert idx == "2"
        assert err is None

    def test_integer_99(self):
        idx, err = _resolve_cv2_index("99")
        assert idx == "99"
        assert err is None

    # ── /dev/videoN conversion ────────────────────────────────────────────────

    def test_dev_video0(self):
        idx, err = _resolve_cv2_index("/dev/video0")
        assert idx == "0"
        assert err is None

    def test_dev_video2(self):
        idx, err = _resolve_cv2_index("/dev/video2")
        assert idx == "2"
        assert err is None

    def test_dev_video10(self):
        idx, err = _resolve_cv2_index("/dev/video10")
        assert idx == "10"
        assert err is None

    # ── Unsupported: by-id symlinks ───────────────────────────────────────────

    def test_by_id_returns_error(self):
        idx, err = _resolve_cv2_index("/dev/v4l/by-id/usb-Cam_Link_4K-1234")
        assert idx is None
        assert err is not None
        # Error message must mention using /dev/videoN
        assert "/dev/videoN" in err or "video" in err.lower()

    def test_by_id_suggests_correct_path(self):
        idx, err = _resolve_cv2_index("/dev/v4l/by-id/some-camera")
        assert "Scan Cameras" in err or "/dev/video" in err

    # ── Unsupported: misc paths ───────────────────────────────────────────────

    def test_unsupported_dev_path(self):
        idx, err = _resolve_cv2_index("/dev/something_else")
        assert idx is None
        assert err is not None

    def test_rtsp_url_unsupported(self):
        """RTSP URLs are not valid via _safe_camera but test the converter directly."""
        idx, err = _resolve_cv2_index("rtsp://192.168.1.100/stream")
        assert idx is None
        assert err is not None

    # ── API-level: _calibrate rejects by-id paths ────────────────────────────

    def test_calibrate_rejects_by_id(self, tmp_path):
        """
        _calibrate() should return HTTP 400 (not submit a job) when the camera
        path is a /dev/v4l/by-id/ symlink that _resolve_cv2_index cannot convert.

        Patches _check_cv2_available so the cv2-preflight passes regardless of
        whether OpenCV is installed in the system Python running the tests.
        """
        from unittest.mock import MagicMock, patch
        from metriplane.runner.operator_api import OperatorAPI

        executor = MagicMock()
        api = OperatorAPI(executor=executor, repo_root=tmp_path)

        # Create minimal profile structure so we get past profile/anchor checks
        profile_dir = tmp_path / "calib" / "profiles" / "local_test"
        (profile_dir / "cam0").mkdir(parents=True)
        (profile_dir / "anchors.yaml").write_text(
            "profile: local_test\nboard_size: {width_m: 0.55, height_m: 0.4}\n"
            "anchors:\n- {id: 0, world_xy: [0,0]}\n- {id: 1, world_xy: [0,0.4]}\n"
            "- {id: 2, world_xy: [0.55,0]}\n- {id: 3, world_xy: [0.55,0.4]}\n"
        )

        _cv2_target = "metriplane.runner.operator_api._check_cv2_available"
        with patch(_cv2_target, return_value=(True, "4.9.0", True)):
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "/dev/v4l/by-id/usb-camera-001",
            })

        assert status == 400
        assert "error" in resp
        assert "/dev/videoN" in resp["error"] or "video" in resp["error"].lower()
        # Must NOT have submitted a job
        executor.execute.assert_not_called()

    def test_calibrate_converts_dev_video0(self, tmp_path):
        """
        _calibrate() should convert /dev/video0 → '0' and build a command with --cam 0.

        Patches _check_cv2_available so the cv2-preflight passes regardless of
        whether OpenCV is installed in the system Python running the tests.
        """
        from unittest.mock import MagicMock, patch
        from metriplane.runner.operator_api import OperatorAPI

        executor = MagicMock(return_value="job-abc123")
        executor.execute.return_value = "job-abc123"
        api = OperatorAPI(executor=executor, repo_root=tmp_path)

        # Create minimal profile structure
        profile_dir = tmp_path / "calib" / "profiles" / "local_test"
        (profile_dir / "cam0").mkdir(parents=True)
        (profile_dir / "anchors.yaml").write_text(
            "profile: local_test\nboard_size: {width_m: 0.55, height_m: 0.4}\n"
            "anchors:\n- {id: 0, world_xy: [0,0]}\n- {id: 1, world_xy: [0,0.4]}\n"
            "- {id: 2, world_xy: [0.55,0]}\n- {id: 3, world_xy: [0.55,0.4]}\n"
        )
        # Also create the script stub so path check passes
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "calibrate_planar_homography.py").write_text("# stub")

        _cv2_target = "metriplane.runner.operator_api._check_cv2_available"
        with patch(_cv2_target, return_value=(True, "4.9.0", True)):
            status, resp = api._calibrate({
                "profile": "local_test",
                "cam": "cam0",
                "camera": "/dev/video0",
            })

        assert status == 200
        # The command passed to executor must use '0', not '/dev/video0'
        call_args = executor.execute.call_args
        command = call_args[1]["command"] if call_args[1] else call_args[0][1]
        cam_idx = command.index("--cam")
        assert command[cam_idx + 1] == "0", (
            f"Expected --cam 0 but got --cam {command[cam_idx + 1]!r}. "
            f"Full command: {command}"
        )
