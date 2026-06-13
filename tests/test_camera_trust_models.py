from __future__ import annotations

import json

from metriplane.camera_trust.models import (
    CameraTrustReportModel,
    CameraTrustScoreModel,
    ZoneCoverageScoreModel,
)


def test_score_model_serializes():
    cs = CameraTrustScoreModel(camera_id="cam0", score=0.91, status="OK",
                               dropout_rate=0.02, mean_disagreement_m=0.006)
    data = json.loads(cs.model_dump_json())
    assert data["camera_id"] == "cam0"
    assert data["status"] == "OK"


def test_zone_coverage_model():
    z = ZoneCoverageScoreModel(zone="exit_lane", score=0.58, weak_cameras=["cam1"])
    assert z.weak_cameras == ["cam1"]


def test_report_contains_cameras_and_recs():
    r = CameraTrustReportModel(
        run_id="r1",
        camera_scores={"cam0": CameraTrustScoreModel(
            camera_id="cam0", score=0.9, status="OK")},
        recommendations=["check cam1"])
    data = json.loads(r.model_dump_json())
    assert "cam0" in data["camera_scores"]
    assert data["recommendations"] == ["check cam1"]
    assert data["schema_version"] == "1.0"
