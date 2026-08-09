# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import logging
import time

import cv2

from metriplane.models import Frame

log = logging.getLogger("metriplane.camera.usb")


class USBCamera:
    def __init__(self, index: int | str = 0) -> None:
        self.index = index
        self.cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        log.info("opening USB camera source=%s", self.index)
        self.cap = cv2.VideoCapture(self.index)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            raise RuntimeError("failed to open USB camera")

    def read(self) -> Frame:
        if self.cap is None:
            raise RuntimeError("camera not opened")
        ts = time.time()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("camera read failed")
        return Frame(ts_cam_read=ts, image=frame)

    def close(self) -> None:
        if self.cap is not None:
            log.info("releasing USB camera")
            self.cap.release()
            self.cap = None
