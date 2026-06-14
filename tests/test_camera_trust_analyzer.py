# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.camera_trust.analyzer import CameraTrustAnalyzer, analyze_session

FIXTURE = "tests/fixtures/camera_trust/multicam_session.jsonl"


def test_dropout_computed():
    report = analyze_session(FIXTURE)
    cam1 = report.camera_scores["cam1"]
    # cam1 sees obj in 2 of 5 frames -> dropout 0.6
    assert abs(cam1.dropout_rate - 0.6) < 1e-6


def test_disagreement_computed():
    report = analyze_session(FIXTURE)
    cam0 = report.camera_scores["cam0"]
    cam1 = report.camera_scores["cam1"]
    assert cam0.mean_disagreement_m == 0.0           # cam0 agrees with fused
    assert cam1.mean_disagreement_m > 0.05           # cam1 disagrees > 5cm


def test_low_score_becomes_failed():
    report = analyze_session(FIXTURE)
    assert report.camera_scores["cam0"].status == "OK"
    assert report.camera_scores["cam1"].status == "FAILED"


def test_frames_analyzed():
    report = analyze_session(FIXTURE)
    assert report.frames_analyzed == 5


def test_no_raw_per_camera_safe():
    import json
    from metriplane.schema import FrameStateModel
    analyzer = CameraTrustAnalyzer()
    frame = FrameStateModel(source_backend="dummy", ts=0.0, frame_id=0,
                            objects=[])
    analyzer.update(frame)  # no raw_per_camera
    report = analyzer.report()
    assert report.frames_analyzed == 1
    assert report.camera_scores == {}


def test_report_stable_ordering():
    report = analyze_session(FIXTURE)
    assert list(report.camera_scores.keys()) == ["cam0", "cam1"]
