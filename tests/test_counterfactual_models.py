# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metriplane.counterfactuals.models import (
    CounterfactualCaseResult,
    CounterfactualReport,
    CounterfactualTransform,
)


def test_valid_transform_parses():
    t = CounterfactualTransform(type="object_remove", target="cart_01")
    assert t.type == "object_remove"


def test_invalid_transform_type_rejected():
    with pytest.raises(ValidationError):
        CounterfactualTransform(type="teleport", target="x")


def test_case_result_pass_alias():
    c = CounterfactualCaseResult(
        case_id="cf_001",
        transform=CounterfactualTransform(type="object_remove", target="x"),
        **{"pass": True}, original_incident_present=False, summary="s")
    dumped = c.model_dump(by_alias=True)
    assert dumped["pass"] is True


def test_report_serializes():
    r = CounterfactualReport(
        bundle_path="b", incident_id="inc_0001",
        original_summary={"rule_id": "r"}, cases=[])
    data = r.model_dump(by_alias=True)
    assert data["incident_id"] == "inc_0001"
    assert data["schema_version"] == "1.0"
