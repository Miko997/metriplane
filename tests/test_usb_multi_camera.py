# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.camera.usb_multi import USBMultiCamera, _USBCamWorker
from metriplane.models import Frame


class _FakeWorker:
    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.sequence = 0
        self.frame: Frame | None = None
        self.age_s = 0.0

    def publish(self, ts: float) -> None:
        self.sequence += 1
        self.frame = Frame(ts_cam_read=ts, image=object(), camera_id=self.camera_id)

    def latest_after(self, sequence: int):
        if self.frame is None or self.sequence <= sequence:
            return None
        return self.sequence, self.frame

    def capture_status(self, *, now_monotonic=None):
        return {
            "sequence": self.sequence,
            "has_frame": self.frame is not None,
            "capture_age_s": self.age_s,
        }

    def close(self) -> None:
        return None


def _fake_multicam(*camera_ids: str) -> tuple[USBMultiCamera, dict[str, _FakeWorker]]:
    cameras = USBMultiCamera(cameras={camera_id: 0 for camera_id in camera_ids})
    workers = {camera_id: _FakeWorker(camera_id) for camera_id in camera_ids}
    cameras._workers = workers  # type: ignore[assignment]
    return cameras, workers


def test_30hz_capture_is_consumed_once_when_polled_at_300hz() -> None:
    cameras, workers = _fake_multicam("cam0")
    seen_timestamps: list[float] = []

    for poll in range(300):
        if poll % 10 == 0:
            workers["cam0"].publish(ts=poll / 300.0)
        seen_timestamps.extend(frame.ts_cam_read for frame in cameras.read())

    assert len(seen_timestamps) == 30
    assert len(set(seen_timestamps)) == 30


def test_multicam_read_returns_only_cameras_with_new_captures() -> None:
    cameras, workers = _fake_multicam("cam0", "cam1")
    workers["cam0"].publish(1.0)
    workers["cam1"].publish(1.1)

    assert [frame.camera_id for frame in cameras.read()] == ["cam0", "cam1"]
    assert cameras.read() == []

    workers["cam1"].publish(2.0)
    assert [frame.camera_id for frame in cameras.read()] == ["cam1"]
    assert cameras.read() == []


def test_worker_capture_age_uses_monotonic_time() -> None:
    worker = _USBCamWorker(camera_id="cam0", source=0)
    worker._state.started_monotonic = 10.0
    worker._state.last_ok_monotonic = 12.5
    worker._state.sequence = 1

    status = worker.capture_status(now_monotonic=13.0)

    assert status == {"sequence": 1, "has_frame": True, "capture_age_s": 0.5}
