#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Metriplane camera discovery tool — v2.

Scans /dev/video* devices, classifies each via the v4l2 VIDIOC_QUERYCAP ioctl,
and tests whether OpenCV can open and read frames using the integer device index
(cv2.VideoCapture(N, cv2.CAP_V4L2)).

Classification:
  V4L2_CAP_VIDEO_CAPTURE (0x1) or VIDEO_CAPTURE_MPLANE (0x1000) → capture-capable
  V4L2_CAP_META_CAPTURE only (0x800000, no capture flag)         → metadata-only
  OpenCV integer-index read succeeds (up to 5 warmup attempts)   → readable / recommended

Usage:
    python tools/list_cameras.py
    python tools/list_cameras.py --json       # same (explicit)
    python tools/list_cameras.py --quick      # skip cv2 read test (v4l2 cap query only)
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import re
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── v4l2 constants ─────────────────────────────────────────────────────────────

# VIDIOC_QUERYCAP = _IOR('V', 0, struct v4l2_capability)
# Computed as: (2 << 30) | (0x56 << 8) | 0 | (104 << 16) = 0x80685600
VIDIOC_QUERYCAP = 0x80685600

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAP_META_CAPTURE = 0x00800000

# struct v4l2_capability layout (104 bytes total):
#   driver[16]      bytes  0–15
#   card[32]        bytes 16–47
#   bus_info[32]    bytes 48–79
#   version         bytes 80–83  (uint32)
#   capabilities    bytes 84–87  (uint32)  — physical device caps
#   device_caps     bytes 88–91  (uint32)  — per-device-node caps (kernel ≥ 3.3)
#   reserved[3]     bytes 92–103 (uint32 × 3)
_QUERYCAP_FMT = "<104s"
_QUERYCAP_SIZE = 104
_CAPS_OFFSET = 84  # capabilities
_DEVCAPS_OFFSET = 88  # device_caps


# ── v4l2 helpers ───────────────────────────────────────────────────────────────


def _query_v4l2_caps(path: str) -> Optional[int]:
    """
    Return the device_caps bitmask for a v4l2 device path, or None on failure.
    Falls back to the capabilities field for pre-3.3 kernels (device_caps == 0).
    """
    try:
        buf = bytearray(_QUERYCAP_SIZE)
        with open(path, "rb") as fh:
            fcntl.ioctl(fh.fileno(), VIDIOC_QUERYCAP, buf)
        caps = struct.unpack_from("<I", buf, _DEVCAPS_OFFSET)[0]
        if caps == 0:
            # Pre-3.3 kernel: device_caps not populated, use capabilities
            caps = struct.unpack_from("<I", buf, _CAPS_OFFSET)[0]
        return caps
    except Exception:
        return None


def _is_capture_capable(caps: Optional[int]) -> bool:
    """True when device is a video capture device (frame-producing)."""
    if caps is None:
        return False
    return bool(caps & (V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE))


def _is_metadata_only(caps: Optional[int]) -> bool:
    """
    True when device only has V4L2_CAP_META_CAPTURE and no video-capture flag.
    These nodes exist alongside real capture nodes for UVC cameras (e.g. /dev/video1
    alongside /dev/video0) and cannot produce frame data.
    """
    if caps is None:
        return False
    has_capture = bool(caps & (V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_CAPTURE_MPLANE))
    has_meta = bool(caps & V4L2_CAP_META_CAPTURE)
    return has_meta and not has_capture


# ── index / by-id helpers ──────────────────────────────────────────────────────


def _extract_index(path: str) -> Optional[int]:
    """Extract integer N from /dev/videoN, or None for other paths."""
    m = re.match(r"^/dev/video(\d+)$", path)
    return int(m.group(1)) if m else None


def _by_id_map() -> Dict[str, str]:
    """Build resolved-path → /dev/v4l/by-id/* symlink map."""
    result: Dict[str, str] = {}
    root = Path("/dev/v4l/by-id")
    if not root.exists():
        return result
    for link in sorted(root.iterdir()):
        try:
            if link.is_symlink():
                target = str(link.resolve())
                if target not in result:
                    result[target] = str(link)
        except OSError:
            pass
    return result


# ── OpenCV probe helpers ───────────────────────────────────────────────────────


def _try_cv2_read(
    index: int,
    warmup: int = 5,
) -> Tuple[bool, bool, Optional[int], Optional[int]]:
    """
    Try cv2.VideoCapture(index, cv2.CAP_V4L2).
    Performs up to `warmup` frame reads before declaring failure.
    Returns (opened, read_ok, width, height).
    Always releases the capture object.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return False, False, None, None

    cap = None
    try:
        cap = cv2.VideoCapture(int(index), cv2.CAP_V4L2)
        if not cap.isOpened():
            return False, False, None, None
        for _ in range(warmup):
            ret, frame = cap.read()
            if ret and frame is not None:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                return True, True, w, h
        return True, False, None, None
    except Exception:
        return False, False, None, None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def _try_cv2_read_path(
    path: str,
    warmup: int = 5,
) -> Tuple[bool, bool, Optional[int], Optional[int]]:
    """Same as _try_cv2_read but uses a string path."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return False, False, None, None

    cap = None
    try:
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not cap.isOpened():
            return False, False, None, None
        for _ in range(warmup):
            ret, frame = cap.read()
            if ret and frame is not None:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                return True, True, w, h
        return True, False, None, None
    except Exception:
        return False, False, None, None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


# ── Per-device probe ───────────────────────────────────────────────────────────


def probe_camera(
    path: str,
    by_id: Dict[str, str],
    quick: bool = False,
) -> Dict:
    """
    Probe a single /dev/videoN device.

    Returns a dict with fields:
      path, index, by_id,
      is_capture_capable, is_metadata_only,
      cv2_open_index, cv2_read_index,
      cv2_open_path, cv2_read_path,
      readable, recommended_for_operator,
      width, height, reason.
    Also includes legacy cv2_open / cv2_read aliases for backwards compat.
    """
    index = _extract_index(path)
    caps = _query_v4l2_caps(path)

    cap_capable = _is_capture_capable(caps)
    meta_only = _is_metadata_only(caps)

    # OpenCV probe — only attempt on capture-capable or unknown devices
    cv2_open_index: Optional[bool] = None
    cv2_read_index: Optional[bool] = None
    cv2_open_path: Optional[bool] = None
    cv2_read_path: Optional[bool] = None
    width: Optional[int] = None
    height: Optional[int] = None

    should_probe = not quick and index is not None and (cap_capable or caps is None)

    if should_probe:
        oi, ri, wi, hi = _try_cv2_read(index)
        cv2_open_index = oi
        cv2_read_index = ri
        if ri:
            width, height = wi, hi

        op, rp, wp, hp = _try_cv2_read_path(path)
        cv2_open_path = op
        cv2_read_path = rp
        if width is None and rp:
            width, height = wp, hp

    # readable = integer-index OR path read succeeded
    readable = bool(cv2_read_index or cv2_read_path)

    # recommended = capture-capable AND readable
    if meta_only:
        recommended = False
        reason: Optional[str] = "Metadata Capture only — not a video capture device"
    elif cap_capable and readable:
        recommended = True
        reason = None
    elif cap_capable and not readable and not quick:
        recommended = False
        reason = "capture-capable but OpenCV could not read frames"
    elif cap_capable and quick:
        # In quick mode we skip cv2 — report as capture-capable but not confirmed readable
        recommended = False
        reason = "skipped cv2 read (--quick mode)"
    else:
        recommended = False
        if caps is None:
            reason = "could not query v4l2 capabilities"
        else:
            reason = "not a capture-capable device"

    # Legacy fields for old code that only checks cv2_open / cv2_read
    legacy_open = cv2_open_index if cv2_open_index is not None else cv2_open_path
    legacy_read = cv2_read_index if cv2_read_index is not None else cv2_read_path

    return {
        "path": path,
        "index": index,
        "by_id": by_id.get(path),
        "is_capture_capable": cap_capable,
        "is_metadata_only": meta_only,
        "cv2_open_index": cv2_open_index,
        "cv2_read_index": cv2_read_index,
        "cv2_open_path": cv2_open_path,
        "cv2_read_path": cv2_read_path,
        "readable": readable,
        "recommended_for_operator": recommended,
        "width": width,
        "height": height,
        "reason": reason,
        # Legacy compat
        "cv2_open": legacy_open,
        "cv2_read": legacy_read,
    }


def scan_cameras(quick: bool = False) -> List[Dict]:
    """Scan and probe all /dev/video* devices."""
    devices = sorted(glob.glob("/dev/video*"))
    by_id = _by_id_map()
    return [probe_camera(dev, by_id, quick=quick) for dev in devices]


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover v4l2 cameras (JSON output)")
    parser.add_argument("--json", action="store_true", help="Output JSON (default)")
    parser.add_argument(
        "--quick", action="store_true", help="Skip frame read test (v4l2 cap query only)"
    )
    args = parser.parse_args()

    cameras = scan_cameras(quick=args.quick)

    readable_n = sum(1 for c in cameras if c["readable"])
    cap_capable_n = sum(1 for c in cameras if c["is_capture_capable"])
    meta_only_n = sum(1 for c in cameras if c["is_metadata_only"])
    recommended_n = sum(1 for c in cameras if c["recommended_for_operator"])

    output = {
        "cameras": cameras,
        "total": len(cameras),
        "readable": readable_n,
        "capture_capable": cap_capable_n,
        "metadata_only": meta_only_n,
        "recommended": recommended_n,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
