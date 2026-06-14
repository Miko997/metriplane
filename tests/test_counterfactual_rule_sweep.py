# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from metriplane.counterfactuals.rule_sweep import parse_sweep, sweep_transforms


def test_parse_sweep_basic():
    rule_id, field, values = parse_sweep("human_proxy_distance.distance_m=0.3:0.8:0.1")
    assert rule_id == "human_proxy_distance"
    assert field == "distance_m"
    assert values[0] == 0.3
    assert values[-1] == 0.8
    assert len(values) == 6


def test_parse_sweep_rule_id_with_dots_uses_last():
    rule_id, field, _ = parse_sweep("a.b.distance_m=0.1:0.2:0.1")
    assert rule_id == "a.b"
    assert field == "distance_m"


def test_sweep_transforms_stable_ids():
    t1 = sweep_transforms("r.min_distance_m=0.1:0.3:0.1")
    t2 = sweep_transforms("r.min_distance_m=0.1:0.3:0.1")
    assert [t.params["value"] for t in t1] == [t.params["value"] for t in t2]
    assert all(t.type == "rule_threshold_sweep" for t in t1)


def test_invalid_missing_equals():
    with pytest.raises(ValueError):
        parse_sweep("r.field")


def test_invalid_missing_field():
    with pytest.raises(ValueError):
        parse_sweep("rule=0.1:0.2:0.1")


def test_invalid_range():
    with pytest.raises(ValueError):
        parse_sweep("r.f=0.1:0.2")


def test_zero_step_rejected():
    with pytest.raises(ValueError):
        parse_sweep("r.f=0.1:0.2:0")
