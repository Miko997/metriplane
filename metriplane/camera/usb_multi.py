# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Union

import cv2

from metriplane.models import Frame
from metriplane.camera.v4l_resolve import resolve_v4l_to_index

log = logging.getLogger("metriplane.camera.usb_multi")

CamSource = Union[int, str]


@dataclass
class _WorkerState:
    latest: Frame | None = None
    sequence: int = 0
    last_ok_monotonic: float | None = None
    started_monotonic: float = 0.0


class _USBCamWorker:
    def __init__(
        self,
        *,
        camera_id: str,
        source: CamSource,
        backend: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        fourcc: str | None = None,
    ) -> None:
        self.camera_id = str(camera_id)
        self.source = source
        self.backend = backend
        self.width = width
        self.height = height
        self.fps = fps
        self.fourcc = fourcc

        self._cap: Any = None
        self._thr: threading.Thread | None = None
        self._stop = threading.Event()
        self._got_first = threading.Event()

        self._lock = threading.Lock()
        self._state = _WorkerState(started_monotonic=time.monotonic())

    def open(self) -> None:
        # Default backend: V4L2 on Linux (more stable than auto)
        backend = self.backend if self.backend is not None else cv2.CAP_V4L2

        # CRITICAL FIX:
        # Many OpenCV builds cannot open "/dev/v4l/by-id/..." with CAP_V4L2.
        # So: ALWAYS open by numeric /dev/videoN index when the source is a string path.
        if isinstance(self.source, int):
            open_idx = int(self.source)
            src_desc = f"index={open_idx}"
        else:
            # Accept "/dev/videoN", "/dev/v4l/by-id/...", or "N"
            open_idx = resolve_v4l_to_index(str(self.source))
            src_desc = f"device={self.source} -> index={open_idx}"

        cap = cv2.VideoCapture(open_idx, backend)

        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            raise RuntimeError(f"failed to open USB camera id={self.camera_id} ({src_desc})")

        # Optional tuning
        if self.fourcc is not None:
            try:
                cap.set(cv2.CAP_PROP_FOURCC, getattr(cv2, "VideoWriter_fourcc")(*self.fourcc))
            except Exception:
                pass
        if self.width is not None:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        if self.height is not None:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        if self.fps is not None:
            cap.set(cv2.CAP_PROP_FPS, float(self.fps))

        self._cap = cap

        self._stop.clear()
        self._got_first.clear()
        with self._lock:
            self._state = _WorkerState(started_monotonic=time.monotonic())
        self._thr = threading.Thread(target=self._run, name=f"usbcam-{self.camera_id}", daemon=True)
        self._thr.start()

        log.info(
            "opened cam id=%s (%s) backend=%s w=%s h=%s fps=%s fourcc=%s",
            self.camera_id,
            src_desc,
            backend,
            self.width,
            self.height,
            self.fps,
            self.fourcc,
        )

    def _run(self) -> None:
        cap = self._cap
        if cap is None:
            return

        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.003)
                continue

            ts = time.time()
            captured_monotonic = time.monotonic()
            fr = Frame(ts_cam_read=ts, image=frame, camera_id=self.camera_id)
            with self._lock:
                self._state.latest = fr
                self._state.sequence += 1
                self._state.last_ok_monotonic = captured_monotonic
            self._got_first.set()

    def wait_for_first(self, timeout_s: float = 3.0) -> bool:
        return self._got_first.wait(timeout=timeout_s)

    def latest_after(self, sequence: int) -> tuple[int, Frame] | None:
        """Return the newest capture once, identified by a worker sequence."""
        with self._lock:
            if self._state.latest is None or self._state.sequence <= int(sequence):
                return None
            return self._state.sequence, self._state.latest

    def capture_status(
        self, *, now_monotonic: float | None = None
    ) -> dict[str, float | int | bool]:
        """Return capture age from the monotonic clock, safe from wall-clock jumps."""
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            last_ok = self._state.last_ok_monotonic
            started = self._state.started_monotonic
            sequence = self._state.sequence
        reference = last_ok if last_ok is not None else started
        return {
            "sequence": sequence,
            "has_frame": last_ok is not None,
            "capture_age_s": max(0.0, now - reference),
        }

    def close(self) -> None:
        self._stop.set()
        if self._thr is not None:
            self._thr.join(timeout=1.0)
        self._thr = None

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None


class USBMultiCamera:
    """
    Threaded multi-camera grabber.

    - open(): starts worker threads
    - read(): returns each camera's latest *new* capture once (non-blocking)

    cameras: {"cam0": 0, "cam1": "/dev/v4l/by-id/..."} both allowed
    """

    def __init__(
        self,
        *,
        cameras: dict[str, CamSource],
        backend: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        fourcc: str | None = None,
        require_all: bool = True,
    ) -> None:
        if not cameras:
            raise ValueError("cameras must be non-empty")
        self.cameras = {str(k): v for k, v in cameras.items()}
        self.require_all = bool(require_all)

        self._workers: dict[str, _USBCamWorker] = {
            cid: _USBCamWorker(
                camera_id=cid,
                source=src,
                backend=backend,
                width=width,
                height=height,
                fps=fps,
                fourcc=fourcc,
            )
            for cid, src in self.cameras.items()
        }
        self._consumed_sequences: dict[str, int] = {cid: 0 for cid in self.cameras}

    def open(self) -> None:
        self._consumed_sequences = {cid: 0 for cid in self.cameras}
        opened: list[_USBCamWorker] = []
        try:
            for w in self._workers.values():
                w.open()
                opened.append(w)
        except Exception:
            for w in reversed(opened):
                w.close()
            raise

        # Wait for first frames (so mapping/fusion doesn’t start empty)
        # IMPORTANT: do NOT hard-fail the whole process if one cam is slow.
        # This happens in practice when a camera takes longer to start streaming.
        missing: list[str] = []
        for cid, w in self._workers.items():
            ok = w.wait_for_first(timeout_s=6.0)
            if not ok:
                missing.append(cid)

        if missing:
            if self.require_all:
                log.warning(
                    "some cameras did not deliver a first frame within timeout: %s. "
                    "Continuing anyway (soft-start).",
                    ",".join(missing),
                )
            else:
                log.info("cameras missing first frame (allowed): %s", ",".join(missing))

    def read(self) -> list[Frame]:
        frames: list[Frame] = []
        for cid, w in self._workers.items():
            item = w.latest_after(self._consumed_sequences.get(cid, 0))
            if item is None:
                continue
            sequence, fr = item
            self._consumed_sequences[cid] = sequence
            frames.append(fr)
        # If require_all and one cam is missing this tick, return what we have.
        # Caller can choose to skip fusion for this tick.
        return frames

    def capture_status(
        self, *, now_monotonic: float | None = None
    ) -> dict[str, dict[str, float | int | bool]]:
        return {
            cid: worker.capture_status(now_monotonic=now_monotonic)
            for cid, worker in self._workers.items()
        }

    def close(self) -> None:
        for w in self._workers.values():
            w.close()
