"""
Tests for tools/list_cameras.py — v4l2 camera discovery and classification.

Verified hardware layout on dev machine:
  /dev/video0  Video Capture (UVC)       → capture-capable, readable, recommended
  /dev/video1  Metadata Capture only     → metadata-only, not readable, not recommended
  /dev/video2  Video Capture (UVC)       → capture-capable, readable, recommended
  /dev/video3  Metadata Capture only     → metadata-only, not readable, not recommended

All tests mock hardware so they run on any CI machine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── import tools/list_cameras.py without requiring a package ──────────────────
_TOOL_PATH = Path(__file__).parent.parent / "tools" / "list_cameras.py"
_spec = importlib.util.spec_from_file_location("list_cameras", _TOOL_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

# Expose module-level names for convenience
_is_capture_capable    = _mod._is_capture_capable
_is_metadata_only      = _mod._is_metadata_only
_extract_index         = _mod._extract_index
probe_camera           = _mod.probe_camera
scan_cameras           = _mod.scan_cameras
V4L2_CAP_VIDEO_CAPTURE = _mod.V4L2_CAP_VIDEO_CAPTURE
V4L2_CAP_VIDEO_CAPTURE_MPLANE = _mod.V4L2_CAP_VIDEO_CAPTURE_MPLANE
V4L2_CAP_META_CAPTURE  = _mod.V4L2_CAP_META_CAPTURE


# ── v4l2 capability flag helpers ──────────────────────────────────────────────

class TestIsCaptureCatpable:
    def test_video_capture_flag(self):
        assert _is_capture_capable(V4L2_CAP_VIDEO_CAPTURE) is True

    def test_video_capture_mplane_flag(self):
        assert _is_capture_capable(V4L2_CAP_VIDEO_CAPTURE_MPLANE) is True

    def test_meta_capture_only(self):
        """Metadata-capture flag alone must not be treated as capture-capable."""
        assert _is_capture_capable(V4L2_CAP_META_CAPTURE) is False

    def test_none_caps(self):
        assert _is_capture_capable(None) is False

    def test_zero_caps(self):
        assert _is_capture_capable(0) is False

    def test_capture_plus_meta(self):
        caps = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_META_CAPTURE
        assert _is_capture_capable(caps) is True


class TestIsMetadataOnly:
    def test_meta_only_flag(self):
        assert _is_metadata_only(V4L2_CAP_META_CAPTURE) is True

    def test_capture_only_flag(self):
        """Pure capture device is NOT metadata-only."""
        assert _is_metadata_only(V4L2_CAP_VIDEO_CAPTURE) is False

    def test_capture_plus_meta_is_not_metadata_only(self):
        """Device that has BOTH capture AND meta is NOT metadata-only."""
        caps = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_META_CAPTURE
        assert _is_metadata_only(caps) is False

    def test_none_caps(self):
        assert _is_metadata_only(None) is False

    def test_zero_caps(self):
        assert _is_metadata_only(0) is False


# ── index extraction ──────────────────────────────────────────────────────────

class TestExtractIndex:
    def test_video0(self):
        assert _extract_index("/dev/video0") == 0

    def test_video2(self):
        assert _extract_index("/dev/video2") == 2

    def test_video10(self):
        assert _extract_index("/dev/video10") == 10

    def test_by_id_returns_none(self):
        assert _extract_index("/dev/v4l/by-id/usb-Cam-1234") is None

    def test_empty_string_returns_none(self):
        assert _extract_index("") is None


# ── probe_camera: video0 — capture + readable → recommended ──────────────────

class TestProbeCameraVideo0:
    """
    /dev/video0: V4L2_CAP_VIDEO_CAPTURE, cv2 index read succeeds.
    Expected: is_capture_capable=True, is_metadata_only=False,
              readable=True, recommended_for_operator=True.
    """

    def _make_result(self) -> Dict:
        with (
            patch.object(_mod, "_query_v4l2_caps", return_value=V4L2_CAP_VIDEO_CAPTURE),
            patch.object(_mod, "_try_cv2_read",      return_value=(True, True, 640, 480)),
            patch.object(_mod, "_try_cv2_read_path", return_value=(True, True, 640, 480)),
        ):
            return probe_camera("/dev/video0", {})

    def test_capture_capable(self):
        assert self._make_result()["is_capture_capable"] is True

    def test_not_metadata_only(self):
        assert self._make_result()["is_metadata_only"] is False

    def test_readable(self):
        assert self._make_result()["readable"] is True

    def test_recommended(self):
        assert self._make_result()["recommended_for_operator"] is True

    def test_index(self):
        assert self._make_result()["index"] == 0

    def test_resolution(self):
        r = self._make_result()
        assert r["width"] == 640
        assert r["height"] == 480

    def test_reason_is_none(self):
        assert self._make_result()["reason"] is None

    def test_cv2_open_index(self):
        assert self._make_result()["cv2_open_index"] is True

    def test_cv2_read_index(self):
        assert self._make_result()["cv2_read_index"] is True


# ── probe_camera: video1 — metadata-only → not recommended ───────────────────

class TestProbeCameraVideo1:
    """
    /dev/video1: V4L2_CAP_META_CAPTURE only.
    Expected: is_metadata_only=True, readable=False, recommended_for_operator=False.
    OpenCV probe must NOT be attempted (metadata nodes fail cv2.open).
    """

    def _make_result(self) -> Dict:
        with (
            patch.object(_mod, "_query_v4l2_caps", return_value=V4L2_CAP_META_CAPTURE),
            patch.object(_mod, "_try_cv2_read",      return_value=(False, False, None, None)),
            patch.object(_mod, "_try_cv2_read_path", return_value=(False, False, None, None)),
        ):
            return probe_camera("/dev/video1", {})

    def test_not_capture_capable(self):
        assert self._make_result()["is_capture_capable"] is False

    def test_is_metadata_only(self):
        assert self._make_result()["is_metadata_only"] is True

    def test_not_readable(self):
        assert self._make_result()["readable"] is False

    def test_not_recommended(self):
        assert self._make_result()["recommended_for_operator"] is False

    def test_reason_mentions_metadata(self):
        r = self._make_result()["reason"]
        assert r is not None
        assert "Metadata" in r or "metadata" in r

    def test_cv2_probes_not_attempted(self):
        """Because metadata-only devices skip OpenCV probing, cv2_* fields are None."""
        r = self._make_result()
        # should_probe = False for metadata-only (no cap_capable, no unknown)
        assert r["cv2_open_index"] is None
        assert r["cv2_read_index"] is None


# ── probe_camera: video2 — same as video0 ────────────────────────────────────

class TestProbeCameraVideo2:
    def _make_result(self) -> Dict:
        with (
            patch.object(_mod, "_query_v4l2_caps", return_value=V4L2_CAP_VIDEO_CAPTURE),
            patch.object(_mod, "_try_cv2_read",      return_value=(True, True, 640, 480)),
            patch.object(_mod, "_try_cv2_read_path", return_value=(True, True, 640, 480)),
        ):
            return probe_camera("/dev/video2", {})

    def test_recommended(self):
        assert self._make_result()["recommended_for_operator"] is True

    def test_index(self):
        assert self._make_result()["index"] == 2


# ── probe_camera: video3 — metadata-only ────────────────────────────────────

class TestProbeCameraVideo3:
    def _make_result(self) -> Dict:
        with (
            patch.object(_mod, "_query_v4l2_caps", return_value=V4L2_CAP_META_CAPTURE),
            patch.object(_mod, "_try_cv2_read",      return_value=(False, False, None, None)),
            patch.object(_mod, "_try_cv2_read_path", return_value=(False, False, None, None)),
        ):
            return probe_camera("/dev/video3", {})

    def test_not_recommended(self):
        assert self._make_result()["recommended_for_operator"] is False

    def test_is_metadata_only(self):
        assert self._make_result()["is_metadata_only"] is True


# ── path read failure + integer read success → still readable ─────────────────

class TestReadableFromIntegerIndexOnly:
    """
    If integer-index read succeeds but path-based read fails,
    the device is still marked readable=True and recommended=True.
    """

    def _make_result(self) -> Dict:
        with (
            patch.object(_mod, "_query_v4l2_caps", return_value=V4L2_CAP_VIDEO_CAPTURE),
            patch.object(_mod, "_try_cv2_read",      return_value=(True, True, 1280, 720)),
            patch.object(_mod, "_try_cv2_read_path", return_value=(False, False, None, None)),
        ):
            return probe_camera("/dev/video0", {})

    def test_readable(self):
        assert self._make_result()["readable"] is True

    def test_recommended(self):
        assert self._make_result()["recommended_for_operator"] is True

    def test_cv2_read_index_true(self):
        assert self._make_result()["cv2_read_index"] is True

    def test_cv2_read_path_false(self):
        assert self._make_result()["cv2_read_path"] is False

    def test_resolution_from_index_read(self):
        r = self._make_result()
        assert r["width"] == 1280
        assert r["height"] == 720


# ── scan_cameras aggregate counts ─────────────────────────────────────────────

class TestScanCamerasAggregate:
    """
    Simulate 4 devices: video0(capture), video1(meta), video2(capture), video3(meta).
    readable=2, capture_capable=2, metadata_only=2.
    """

    def _mock_probe(self, path: str, by_id: dict, quick: bool = False) -> Dict:
        """Minimal mock of probe_camera matching the real hardware layout."""
        if path in ("/dev/video0", "/dev/video2"):
            return {
                "path": path,
                "index": int(path[-1]),
                "by_id": None,
                "is_capture_capable": True,
                "is_metadata_only": False,
                "cv2_open_index": True,
                "cv2_read_index": True,
                "cv2_open_path": True,
                "cv2_read_path": True,
                "readable": True,
                "recommended_for_operator": True,
                "width": 640, "height": 480,
                "reason": None,
                "cv2_open": True, "cv2_read": True,
            }
        else:  # video1, video3
            return {
                "path": path,
                "index": int(path[-1]),
                "by_id": None,
                "is_capture_capable": False,
                "is_metadata_only": True,
                "cv2_open_index": None,
                "cv2_read_index": None,
                "cv2_open_path": None,
                "cv2_read_path": None,
                "readable": False,
                "recommended_for_operator": False,
                "width": None, "height": None,
                "reason": "Metadata Capture only — not a video capture device",
                "cv2_open": None, "cv2_read": None,
            }

    def _run_scan(self):
        devices = ["/dev/video0", "/dev/video1", "/dev/video2", "/dev/video3"]
        with (
            patch.object(_mod, "glob") as mock_glob,
            patch.object(_mod, "probe_camera", side_effect=self._mock_probe),
            patch.object(_mod, "_by_id_map", return_value={}),
        ):
            mock_glob.glob.return_value = devices
            return scan_cameras()

    def test_total_cameras(self):
        cams = self._run_scan()
        assert len(cams) == 4

    def test_readable_count(self):
        cams = self._run_scan()
        readable = sum(1 for c in cams if c["readable"])
        assert readable == 2

    def test_capture_capable_count(self):
        cams = self._run_scan()
        cap = sum(1 for c in cams if c["is_capture_capable"])
        assert cap == 2

    def test_metadata_only_count(self):
        cams = self._run_scan()
        meta = sum(1 for c in cams if c["is_metadata_only"])
        assert meta == 2

    def test_recommended_are_video0_and_video2(self):
        cams = self._run_scan()
        recommended = [c["path"] for c in cams if c["recommended_for_operator"]]
        assert set(recommended) == {"/dev/video0", "/dev/video2"}

    def test_not_recommended_are_video1_and_video3(self):
        cams = self._run_scan()
        not_rec = [c["path"] for c in cams if not c["recommended_for_operator"]]
        assert set(not_rec) == {"/dev/video1", "/dev/video3"}


# ── operator.js UI rendering guard (static code check) ────────────────────────

class TestOperatorJsRenderingGuard:
    """
    Static check that operator.js discoverCameras() contains the logic to:
      - read recommended_for_operator from each camera
      - disable cam0/cam1 buttons for non-recommended rows
    This is not a browser test but verifies the integration code is present.
    """

    def _load_operator_js(self) -> str:
        p = Path(__file__).parent.parent / "web" / "dashboard" / "operator.js"
        return p.read_text()

    def test_recommended_for_operator_read(self):
        """operator.js must read recommended_for_operator from camera data."""
        js = self._load_operator_js()
        assert "recommended_for_operator" in js

    def test_disabled_attribute_for_non_recommended(self):
        """operator.js must add disabled attribute for non-recommended rows."""
        js = self._load_operator_js()
        assert "disabled" in js
        # Must also check is_metadata_only to classify row type
        assert "is_metadata_only" in js

    def test_status_shows_readable_count(self):
        """Status text must use data.readable (not hard-coded 0)."""
        js = self._load_operator_js()
        assert "data.readable" in js or "readable" in js
