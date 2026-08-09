# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import pytest
from pydantic import ValidationError

from metriplane.schema import CameraFrameModel, FrameStateModel, ObjectStateModel


def test_schema_validates() -> None:
    msg = FrameStateModel(
        source_backend="aruco",
        ts=1.0,
        frame_id=1,
        objects=[],
        events=[],
        metrics={"fps": 30.0},
    )
    assert msg.schema_version == "1.0"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ObjectStateModel(id="", pos_world=(0.0, 0.0, 0.0)),
        lambda: ObjectStateModel(id="x", pos_world=(float("nan"), 0.0, 0.0)),
        lambda: ObjectStateModel(id="x", vel_world=(0.0, float("inf"), 0.0)),
        lambda: ObjectStateModel(id="x", confidence=1.1),
        lambda: ObjectStateModel(id="x", extra={"nested": [float("nan")]}),
        lambda: CameraFrameModel(camera_id="cam", ts_cam_read=float("nan"), objects=[]),
        lambda: CameraFrameModel(
            camera_id="cam",
            ts_cam_read=1.0,
            objects=[],
            metrics={"nested": {"value": float("inf")}},
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=float("inf"),
            frame_id=1,
            objects=[],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=1,
            objects=[],
            metrics={"not_json": {1, 2}},
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=-1,
            objects=[],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=True,
            objects=[],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=1,
            ts_sim_ns=-1,
            objects=[],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=1,
            ts_sim_ns=False,
            objects=[],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=1,
            objects=[ObjectStateModel(id="x"), ObjectStateModel(id="x")],
        ),
        lambda: FrameStateModel(
            source_backend="test",
            ts=1.0,
            frame_id=1,
            objects=[],
            raw_per_camera=[
                CameraFrameModel(camera_id="cam", ts_cam_read=1.0, objects=[]),
                CameraFrameModel(camera_id="cam", ts_cam_read=1.0, objects=[]),
            ],
        ),
    ],
)
def test_evidence_models_reject_nonfinite_or_invalid_values(factory) -> None:
    with pytest.raises(ValidationError):
        factory()
