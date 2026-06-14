# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metriplane.testing.load_expected import load_expected
from metriplane.testing.models import (
    ExpectedIncidentSpec,
    PhysicalRegressionExpected,
    severity_rank,
)

VALID = """\
schema_version: "1.0"
expected:
  incidents:
    - type: forbidden_zone_entry
      rule_id: no_cart_in_exit_lane
      min_count: 1
      severity_at_least: warning
  events:
    - rule_id: no_cart_in_exit_lane
      min_count: 1
  replay:
    deterministic_hash_match: true
  latency:
    p95_update_ms_max: 20
"""


def test_loads_nested_expected(tmp_path):
    p = tmp_path / "expected.yaml"
    p.write_text(VALID)
    exp = load_expected(p)
    assert len(exp.incidents) == 1
    assert exp.incidents[0].rule_id == "no_cart_in_exit_lane"
    assert exp.latency.p95_update_ms_max == 20


def test_loads_flat_expected(tmp_path):
    p = tmp_path / "expected.yaml"
    p.write_text("incidents:\n  - type: t\n    min_count: 2\n")
    exp = load_expected(p)
    assert exp.incidents[0].min_count == 2


def test_invalid_severity_rejected():
    with pytest.raises(ValidationError):
        ExpectedIncidentSpec(type="t", severity_at_least="catastrophic")


def test_defaults():
    exp = PhysicalRegressionExpected()
    assert exp.replay.deterministic_hash_match is True
    assert exp.latency.p95_update_ms_max is None


def test_severity_rank_order():
    assert severity_rank("critical") > severity_rank("high") > severity_rank("warning")


def test_non_mapping_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ValueError):
        load_expected(p)
