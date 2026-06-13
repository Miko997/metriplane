from __future__ import annotations

from metriplane.camera_trust.analyzer import CameraTrustConfig
from metriplane.camera_trust.models import (
    CameraTrustScoreModel,
    ZoneCoverageScoreModel,
)
from metriplane.camera_trust.recommendations import build_recommendations

CFG = CameraTrustConfig()


def _cam(cid, dropout=0.0, dis=None, conf=None):
    return CameraTrustScoreModel(
        camera_id=cid, score=0.5, status="DEGRADED",
        dropout_rate=dropout, mean_disagreement_m=dis, mean_confidence=conf)


def test_high_dropout_recommendation():
    recs = build_recommendations({"cam1": _cam("cam1", dropout=0.6)}, {}, CFG)
    assert any("dropout" in r for r in recs)


def test_high_disagreement_recommendation():
    recs = build_recommendations({"cam1": _cam("cam1", dis=0.08)}, {}, CFG)
    assert any("calibration" in r or "alignment" in r for r in recs)


def test_low_confidence_recommendation():
    recs = build_recommendations({"cam1": _cam("cam1", conf=0.3)}, {}, CFG)
    assert any("confidence" in r for r in recs)


def test_weak_zone_recommendation():
    zone = ZoneCoverageScoreModel(zone="exit_lane", score=0.6,
                                  camera_observation_counts={"cam1": 3},
                                  weak_cameras=[])
    recs = build_recommendations({}, {"exit_lane": zone}, CFG)
    assert any("exit_lane" in r for r in recs)


def test_no_issues_minimal():
    recs = build_recommendations({"cam0": _cam("cam0", dropout=0.0)}, {}, CFG)
    assert recs == ["No camera trust issues detected."]
