from metriplane.schema import FrameStateModel


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
