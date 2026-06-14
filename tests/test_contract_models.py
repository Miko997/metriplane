# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metriplane.contracts.models import (
    ContractRuleSpec,
    SpatialContractPackage,
    SubjectSpec,
)


def _pkg(rules, subjects=None):
    return SpatialContractPackage(
        contract_id="t",
        subjects=subjects or {"movable": SubjectSpec(object_types=["cart"]),
                              "people": SubjectSpec(object_types=["human_proxy"])},
        rules=rules,
    )


def test_valid_forbidden_zone():
    pkg = _pkg([ContractRuleSpec(id="r1", type="forbidden_zone",
                                 subject="movable", zones=["exit_lane"])])
    assert pkg.rules[0].type == "forbidden_zone"


def test_missing_rule_id_fails():
    with pytest.raises(ValidationError):
        ContractRuleSpec(type="forbidden_zone", subject="movable", zones=["z"])


def test_unsupported_rule_type_fails():
    with pytest.raises(ValidationError):
        ContractRuleSpec(id="r", type="teleport", subject="m", zones=["z"])


def test_minimum_distance_requires_distance():
    with pytest.raises(ValueError):
        _pkg([ContractRuleSpec(id="r", type="minimum_distance",
                               subject_a="people", subject_b="movable")])


def test_zone_duration_requires_max_duration():
    with pytest.raises(ValueError):
        _pkg([ContractRuleSpec(id="r", type="zone_occupancy_duration",
                               subject="movable", zones=["exit_lane"])])


def test_duplicate_rule_ids_fail():
    with pytest.raises(ValueError, match="duplicate rule id"):
        _pkg([
            ContractRuleSpec(id="dup", type="forbidden_zone",
                             subject="movable", zones=["z"]),
            ContractRuleSpec(id="dup", type="forbidden_zone",
                             subject="movable", zones=["z"]),
        ])


def test_unknown_subject_reference_fails():
    with pytest.raises(ValueError, match="unknown subject"):
        _pkg([ContractRuleSpec(id="r", type="forbidden_zone",
                               subject="ghost", zones=["z"])])


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        _pkg([ContractRuleSpec(id="r", type="minimum_distance",
                               subject_a="people", subject_b="movable",
                               distance_m=-1.0)])


def test_negative_cooldown_rejected():
    with pytest.raises(ValueError):
        _pkg([ContractRuleSpec(id="r", type="forbidden_zone", subject="movable",
                               zones=["z"], cooldown_s=-1.0)])


def test_forbidden_direction_requires_allowed_direction():
    with pytest.raises(ValueError):
        _pkg([ContractRuleSpec(id="r", type="forbidden_direction",
                               subject="movable", zones=["packing"])])
