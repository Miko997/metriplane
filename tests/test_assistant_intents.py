# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.assistant.intents import classify, supported_questions


def test_classify_blocked_lane():
    assert classify("was the exit lane blocked?") == "zone_occupancy"


def test_classify_camera():
    assert classify("which camera was unreliable?") == "camera_health"


def test_classify_rule():
    assert classify("which rule triggered this incident?") == "rule_explanation"


def test_classify_incident():
    assert classify("how many incidents happened?") == "incident_search"


def test_classify_object():
    assert classify("where did cart_01 go?") == "object_history"


def test_classify_unknown():
    assert classify("what's the weather like?") == "unknown"


def test_supported_questions_nonempty():
    assert len(supported_questions()) >= 5
