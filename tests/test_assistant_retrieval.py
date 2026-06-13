from __future__ import annotations

from metriplane.assistant import retrieval

BUNDLE = "evidence/incidents/INC-DIST-001"
DEMO = "evidence/experiments/assistant_demo"


def test_retrieve_incidents():
    incidents, cites, lims = retrieval.retrieve_incidents(BUNDLE)
    assert len(incidents) >= 1
    assert incidents[0]["rule_id"] == "cart_person_distance"
    assert cites and cites[0].source_type == "incidents"
    assert lims == []


def test_retrieve_rule_by_id():
    rule, cites, lims = retrieval.retrieve_rule(BUNDLE, "cart_person_distance")
    assert rule is not None
    assert rule["type"] == "min_distance"
    assert cites[0].record_id == "cart_person_distance"


def test_retrieve_rule_unknown():
    rule, _, lims = retrieval.retrieve_rule(BUNDLE, "ghost_rule")
    assert rule is None
    assert any("not found" in m for m in lims)


def test_retrieve_camera_trust_from_json():
    report, cites, lims = retrieval.retrieve_camera_trust(DEMO)
    assert report is not None
    assert "cam1" in report["camera_scores"]
    assert cites[0].source_type == "camera_trust"


def test_retrieve_traces():
    rows, cites, lims = retrieval.retrieve_traces(BUNDLE)
    ids = {r["object_id"] for r in rows}
    assert "cart_01" in ids


def test_missing_files_produce_limitations(tmp_path):
    incidents, _, lims = retrieval.retrieve_incidents(tmp_path)
    assert incidents == []
    assert lims  # limitation, not crash
    rule, _, lims2 = retrieval.retrieve_rule(tmp_path, "x")
    assert rule is None and lims2


def test_known_object_ids():
    ids = retrieval.known_object_ids(BUNDLE)
    assert "cart_01" in ids
