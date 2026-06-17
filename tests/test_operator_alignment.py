# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Tests for /operator/validate-alignment and /operator/validate-alignment-full.

Key invariants:
- validate-alignment uses report_alignment.py (intrinsics optional)
- validate-alignment-full uses debug_alignment.py (intrinsics required)
- Both return structured 400 with actionable info when prerequisites are missing
- Both convert /dev/videoN → integer index before building the command
"""

import pytest
from unittest.mock import MagicMock
from metriplane.runner.operator_api import OperatorAPI


def _make_api(tmp_path):
    executor = MagicMock()
    executor.execute.return_value = "job-test-001"
    return OperatorAPI(executor=executor, repo_root=tmp_path)


def _minimal_profile(tmp_path, name="local_test", cameras=("cam0", "cam1")):
    """Create a minimal profile with mapping files for both cameras."""
    profile_dir = tmp_path / "calib" / "profiles" / name
    for cam in cameras:
        (profile_dir / cam).mkdir(parents=True)
        # Write minimal mapping YAML
        (profile_dir / cam / "mapping_raw.yaml").write_text(
            "homography: [[1,0,0],[0,1,0],[0,0,1]]\n"
        )
    (profile_dir / "anchors.yaml").write_text(
        "profile: " + name + "\n"
        "board_size: {width_m: 0.55, height_m: 0.4}\n"
        "anchors:\n- {id: 0, world_xy: [0,0]}\n- {id: 1, world_xy: [0,0.4]}\n"
        "- {id: 2, world_xy: [0.55,0]}\n- {id: 3, world_xy: [0.55,0.4]}\n"
    )
    return profile_dir


def _add_intrinsics(profile_dir):
    for cam in ("cam0", "cam1"):
        (profile_dir / cam).mkdir(parents=True, exist_ok=True)
        (profile_dir / cam / "intrinsics.yaml").write_text(
            "camera_matrix: [[800,0,320],[0,800,240],[0,0,1]]\n"
            "dist_coeffs: [0,0,0,0,0]\n"
            "image_size: [640, 480]\n"
        )


# ── validate-alignment (planar, intrinsics optional) ─────────────────────────

class TestValidateAlignment:

    def test_succeeds_without_intrinsics(self, tmp_path):
        """report_alignment.py does not need intrinsics — should submit job."""
        api = _make_api(tmp_path)
        _minimal_profile(tmp_path)
        # Stub report_alignment.py
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "report_alignment.py").write_text("# stub")

        status, resp = api._validate_alignment({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 200
        assert "job_id" in resp
        assert resp["has_intrinsics"] is False
        assert resp["mode"] == "planar"
        api.executor.execute.assert_called_once()

    def test_succeeds_with_intrinsics(self, tmp_path):
        """When intrinsics exist, report mode should be planar+intrinsics."""
        api = _make_api(tmp_path)
        pdir = _minimal_profile(tmp_path)
        _add_intrinsics(pdir)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "report_alignment.py").write_text("# stub")

        status, resp = api._validate_alignment({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 200
        assert resp["has_intrinsics"] is True
        assert resp["mode"] == "planar+intrinsics"
        # Both intrinsics paths must be present in the command
        cmd = api.executor.execute.call_args[1]["command"]
        cmd_str = " ".join(cmd)
        assert "--intrinsics-cam0" in cmd_str
        assert "--intrinsics-cam1" in cmd_str

    def test_converts_dev_video_path(self, tmp_path):
        """cam0=/dev/video0 should be converted to --cam0 0 in the command."""
        api = _make_api(tmp_path)
        _minimal_profile(tmp_path)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "report_alignment.py").write_text("# stub")

        status, resp = api._validate_alignment({
            "profile": "local_test",
            "cam0": "/dev/video0",
            "cam1": "/dev/video2",
        })

        assert status == 200
        cmd = api.executor.execute.call_args[1]["command"]
        idx0 = cmd[cmd.index("--cam0") + 1]
        idx1 = cmd[cmd.index("--cam1") + 1]
        assert idx0 == "0", f"Expected --cam0 0 but got {idx0!r}"
        assert idx1 == "2", f"Expected --cam1 2 but got {idx1!r}"

    def test_missing_cam0_mapping_returns_400(self, tmp_path):
        api = _make_api(tmp_path)
        # Only cam1 mapping exists
        profile_dir = tmp_path / "calib" / "profiles" / "local_test"
        (profile_dir / "cam0").mkdir(parents=True)
        (profile_dir / "cam1").mkdir(parents=True)
        (profile_dir / "cam1" / "mapping_raw.yaml").write_text("h: 1\n")
        (profile_dir / "anchors.yaml").write_text("profile: local_test\n")

        status, resp = api._validate_alignment({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 400
        assert "cam0" in resp["error"].lower()
        api.executor.execute.assert_not_called()

    def test_missing_report_alignment_script_returns_500(self, tmp_path):
        api = _make_api(tmp_path)
        _minimal_profile(tmp_path)
        # Do NOT create tools/report_alignment.py

        status, resp = api._validate_alignment({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 500
        assert "report_alignment.py" in resp["error"]
        api.executor.execute.assert_not_called()


# ── validate-alignment-full (debug, intrinsics required) ────────────────────

class TestFullAlignmentCheck:

    def test_returns_400_when_intrinsics_missing(self, tmp_path):
        """Must return structured 400 with missing paths and can_skip=True."""
        api = _make_api(tmp_path)
        _minimal_profile(tmp_path)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "debug_alignment.py").write_text("# stub")

        status, resp = api._full_alignment_check({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 400
        assert "error" in resp
        assert "missing_intrinsics" in resp
        assert len(resp["missing_intrinsics"]) == 2  # both cam0 and cam1 missing
        assert resp.get("can_skip") is True
        assert "generate_command" in resp
        assert "hint" in resp
        # Must NOT submit a job
        api.executor.execute.assert_not_called()

    def test_returns_400_when_only_one_intrinsics_missing(self, tmp_path):
        api = _make_api(tmp_path)
        pdir = _minimal_profile(tmp_path)
        # Only cam0 has intrinsics
        (pdir / "cam0" / "intrinsics.yaml").write_text("image_size: [640, 480]\n")
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "debug_alignment.py").write_text("# stub")

        status, resp = api._full_alignment_check({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 400
        assert len(resp["missing_intrinsics"]) == 1
        assert "cam1" in resp["missing_intrinsics"][0]

    def test_succeeds_with_both_intrinsics(self, tmp_path):
        """When both intrinsics exist, should submit job using debug_alignment.py."""
        api = _make_api(tmp_path)
        pdir = _minimal_profile(tmp_path)
        _add_intrinsics(pdir)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "debug_alignment.py").write_text("# stub")

        status, resp = api._full_alignment_check({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 200
        assert "job_id" in resp
        assert resp["mode"] == "full-undistort"
        cmd = api.executor.execute.call_args[1]["command"]
        cmd_str = " ".join(str(x) for x in cmd)
        assert "debug_alignment.py" in cmd_str
        assert "--intrinsics-cam0" in cmd_str
        assert "--intrinsics-cam1" in cmd_str

    def test_by_id_camera_returns_400_before_submit(self, tmp_path):
        api = _make_api(tmp_path)
        pdir = _minimal_profile(tmp_path)
        _add_intrinsics(pdir)
        (tmp_path / "tools").mkdir(exist_ok=True)
        (tmp_path / "tools" / "debug_alignment.py").write_text("# stub")

        status, resp = api._full_alignment_check({
            "profile": "local_test",
            "cam0": "/dev/v4l/by-id/usb-cam-001",
            "cam1": "2",
        })

        assert status == 400
        assert "video" in resp["error"].lower()
        api.executor.execute.assert_not_called()

    def test_422_missing_intrinsics_message_mentions_generate_command(self, tmp_path):
        api = _make_api(tmp_path)
        _minimal_profile(tmp_path)

        status, resp = api._full_alignment_check({
            "profile": "local_test", "cam0": "0", "cam1": "2"
        })

        assert status == 400
        # generate_command must guide the user to calibrate_intrinsics_chessboard.py
        assert "calibrate_intrinsics_chessboard" in resp["generate_command"]
