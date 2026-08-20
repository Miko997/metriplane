# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tools.cross_adapter_gate import load_mutation_catalog, load_registry

REPOSITORY_ROOT = Path(__file__).parents[2]
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
MUTATION_KEYS = {
    "applies_to",
    "atlas_must_remain_uncalled",
    "coverage_paths",
    "error_category",
    "failure_stage",
    "group",
    "mutation",
    "mutation_id",
    "rejecting_component",
}
METAMORPHIC_KEYS = {
    "applies_to",
    "coverage_paths",
    "permitted_changes",
    "required_invariants",
    "test_id",
}


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _catalog() -> dict[str, Any]:
    catalog = load_mutation_catalog(REPOSITORY_ROOT)
    assert set(catalog) == {"metamorphic_tests", "mutations", "schema_version"}
    assert catalog["schema_version"] == ("metriplane.cross_adapter_mutation_catalog.v1")
    return catalog


def test_mutation_catalog_is_strict_unique_and_backed_by_tests() -> None:
    catalog = _catalog()
    mutation_ids: set[str] = set()

    for mutation in catalog["mutations"]:
        assert set(mutation) == MUTATION_KEYS, mutation.get("mutation_id")
        mutation_id = mutation["mutation_id"]
        assert IDENTIFIER_RE.fullmatch(mutation_id)
        assert mutation_id not in mutation_ids
        mutation_ids.add(mutation_id)
        for field in (
            "error_category",
            "failure_stage",
            "group",
            "mutation",
            "rejecting_component",
        ):
            assert _nonempty_string(mutation[field]), mutation_id
        assert mutation["applies_to"]
        assert len(mutation["applies_to"]) == len(set(mutation["applies_to"]))
        assert isinstance(mutation["atlas_must_remain_uncalled"], bool)
        assert mutation["coverage_paths"]
        for relative in mutation["coverage_paths"]:
            assert _nonempty_string(relative), mutation_id
            assert (REPOSITORY_ROOT / relative).is_file(), (
                f"{mutation_id}: missing coverage path {relative}"
            )

    assert mutation_ids
    metamorphic_ids: set[str] = set()
    for test in catalog["metamorphic_tests"]:
        assert set(test) == METAMORPHIC_KEYS, test.get("test_id")
        test_id = test["test_id"]
        assert IDENTIFIER_RE.fullmatch(test_id)
        assert test_id not in metamorphic_ids
        metamorphic_ids.add(test_id)
        assert test["applies_to"]
        assert test["coverage_paths"]
        assert test["required_invariants"]
        assert isinstance(test["permitted_changes"], list)
        assert all(_nonempty_string(value) for value in test["required_invariants"])
        assert all(_nonempty_string(value) for value in test["permitted_changes"])
        for relative in test["coverage_paths"]:
            assert _nonempty_string(relative), test_id
            coverage = REPOSITORY_ROOT / relative
            assert coverage.is_file(), f"{test_id}: missing coverage path {relative}"
            assert "def test_" in coverage.read_text(encoding="utf-8"), (
                f"{test_id}: coverage path has no executable test {relative}"
            )

    assert metamorphic_ids == {
        "domain_pack_separation",
        "excluded_source_field_invariance",
        "expected_outcome_independence",
        "regression_sensitivity",
        "relevant_state_sensitivity",
        "relocation",
        "tamper_detection",
    }


def test_mutation_groups_are_complete_and_owned_by_registered_components() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    catalog = _catalog()
    adapters = {adapter["component_id"]: adapter for adapter in registry["adapters"]}
    valid_owners = {
        "all_adapters",
        "all_fixtures",
        "all_incident_fixtures",
        "shared",
        *adapters,
    }

    mutations_by_group: dict[str, list[dict[str, Any]]] = {}
    for mutation in catalog["mutations"]:
        assert set(mutation["applies_to"]) <= valid_owners, mutation["mutation_id"]
        mutations_by_group.setdefault(mutation["group"], []).append(mutation)

    metamorphic_by_id = {test["test_id"]: test for test in catalog["metamorphic_tests"]}
    for test in catalog["metamorphic_tests"]:
        assert set(test["applies_to"]) <= valid_owners, test["test_id"]

    declared_groups: set[str] = set()
    for adapter_id, adapter in adapters.items():
        assert adapter["ignored_source_fields"], adapter_id
        common_groups = set(adapter["common_mutation_groups"])
        specific_groups = set(adapter["adapter_specific_mutation_groups"])
        assert common_groups.isdisjoint(specific_groups), adapter_id
        declared_groups |= common_groups | specific_groups

        for group in common_groups:
            entries = mutations_by_group[group]
            assert any(
                {"shared", "all_adapters"} & set(entry["applies_to"]) for entry in entries
            ), f"{adapter_id}: common group {group} has no shared owner"

        for group in specific_groups - {"excluded_field_invariance"}:
            entries = mutations_by_group[group]
            assert any(
                adapter_id in entry["applies_to"] or "all_adapters" in entry["applies_to"]
                for entry in entries
            ), f"{adapter_id}: adapter-specific group {group} has no owner"

    excluded_field_test = metamorphic_by_id["excluded_source_field_invariance"]
    assert "all_adapters" in excluded_field_test["applies_to"]
    assert {
        "atlas_events",
        "deviations",
        "domain_pack",
        "incidents",
        "normalized_state",
    } <= set(excluded_field_test["required_invariants"])
    assert "declared provenance summaries" in excluded_field_test["permitted_changes"]

    mutation_groups = set(mutations_by_group)
    assert mutation_groups <= declared_groups
    assert declared_groups <= mutation_groups | {"excluded_field_invariance"}


def test_mutation_failure_stages_make_pre_atlas_expectations_explicit() -> None:
    catalog = _catalog()
    post_evaluation_mutations: set[str] = set()

    for mutation in catalog["mutations"]:
        mutation_id = mutation["mutation_id"]
        assert mutation["failure_stage"] != "atlas", mutation_id
        assert "atlas" not in mutation["rejecting_component"].casefold(), mutation_id
        if mutation["atlas_must_remain_uncalled"]:
            assert mutation["failure_stage"] != "publication", mutation_id
        else:
            post_evaluation_mutations.add(mutation_id)
            assert mutation["failure_stage"] == "publication", mutation_id

    assert post_evaluation_mutations == {"filesystem.destination_collision"}

    semantic_groups = {
        "coordinates",
        "identity",
        "json_structural",
        "maniskill_trajectory",
        "massrobotics_clock",
        "massrobotics_complete_snapshot",
        "massrobotics_datum",
        "rights",
        "robomimic_hdf5",
        "ros2_mcap_streams",
        "ros2_tf",
        "time",
        "trust_layers",
    }
    for mutation in catalog["mutations"]:
        if mutation["group"] in semantic_groups:
            assert mutation["atlas_must_remain_uncalled"] is True, mutation["mutation_id"]
