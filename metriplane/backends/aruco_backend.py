# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import logging
from typing import List, Tuple

import cv2
import numpy as np

from metriplane.models import Frame

log = logging.getLogger("metriplane.backends.aruco")


class ArUcoBackend:
    def __init__(self) -> None:
        self.dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        params = cv2.aruco.DetectorParameters()

        # Safe refinement (helps reduce ID flip on corners)
        try:
            params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        except Exception:
            pass

        self.detector = cv2.aruco.ArucoDetector(self.dictionary, params)

    def detect(self, frame: Frame) -> List[Tuple[int, float, float]]:
        gray = cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)

        detections: List[Tuple[int, float, float]] = []
        if ids is None:
            return detections

        for marker_id, corner_set in zip(ids.flatten(), corners):
            pts = corner_set.reshape(4, 2)
            cx = float(np.mean(pts[:, 0]))
            cy = float(np.mean(pts[:, 1]))
            detections.append((int(marker_id), cx, cy))
            log.debug("found marker id=%d at px=(%.1f, %.1f)", int(marker_id), cx, cy)

        return detections
