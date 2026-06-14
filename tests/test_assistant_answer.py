# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.assistant.answer import answer_question

BUNDLE = "evidence/incidents/INC-DIST-001"
DEMO = "evidence/experiments/assistant_demo"


def test_incident_answer_includes_facts():
    a = answer_question("what incident happened?", BUNDLE)
    assert a.intent == "incident_search"
    assert "cart_person_distance" in a.answer
    assert a.citations
    assert a.confidence > 0.5


def test_rule_answer_includes_type():
    a = answer_question("which rule triggered this incident?", BUNDLE)
    assert a.intent == "rule_explanation"
    assert "min_distance" in a.answer
    assert a.citations


def test_object_history_answer():
    a = answer_question("where did cart_01 go?", BUNDLE)
    assert a.intent == "object_history"
    assert "cart_01" in a.answer


def test_zone_answer():
    a = answer_question("was the exit lane blocked?", "evidence/incidents/INC-0001")
    assert a.intent == "zone_occupancy"
    assert "exit_lane" in a.answer


def test_camera_health_answer():
    a = answer_question("which camera was unreliable?", DEMO)
    assert a.intent == "camera_health"
    assert "cam1" in a.answer


def test_unknown_lists_supported():
    a = answer_question("what is the meaning of life?", BUNDLE)
    assert a.intent == "unknown"
    assert "incident_search" in a.answer
    assert a.confidence == 0.0


def test_missing_data_reports_limitation(tmp_path):
    a = answer_question("what incident happened?", tmp_path)
    assert a.limitations
    assert "No incidents" in a.answer or a.limitations


def test_no_invented_incident_when_absent(tmp_path):
    a = answer_question("how many incidents?", tmp_path)
    assert "No incidents" in a.answer
