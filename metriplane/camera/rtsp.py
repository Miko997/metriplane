import logging
import time

import cv2

from metriplane.models import Frame

log = logging.getLogger("metriplane.camera.rtsp")


class RTSPCamera:
    def __init__(self, url: str) -> None:
        self.url = url
        self.cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        log.info("opening RTSP url=%s", self.url)
        self.cap = cv2.VideoCapture(self.url)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            raise RuntimeError("failed to open RTSP stream")

    def read(self) -> Frame:
        if self.cap is None:
            raise RuntimeError("rtsp stream not opened")
        ts = time.time()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("rtsp read failed")
        return Frame(ts_cam_read=ts, image=frame)

    def close(self) -> None:
        if self.cap is not None:
            log.info("releasing RTSP stream")
            self.cap.release()
            self.cap = None
