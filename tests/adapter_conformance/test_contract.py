# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

from metriplane.external_sources.execution import run_external_fixture
from tools.cross_adapter_gate import (
    assert_fixture_contract,
    fixture_variants,
    load_registry,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKSUM_LINE_RE = re.compile(r"^([0-9a-f]{64})  (\S+)$")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def _read_session(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert all(isinstance(row, dict) for row in rows), path
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_fixture_checksums(root: Path) -> None:
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.name != "CHECKSUMS.sha256"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    lines = [f"{_sha256(path)}  {path.relative_to(root).as_posix()}" for path in paths]
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _variants() -> list[dict[str, Any]]:
    registry = load_registry(REPOSITORY_ROOT)
    variants = list(fixture_variants(registry))
    assert len(variants) == sum(len(family["variants"]) for family in registry["fixtures"])
    assert len({variant["variant_id"] for variant in variants}) == len(variants)
    return variants


def _assert_safe_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    assert value
    assert not path.is_absolute()
    assert "\\" not in value
    assert ".." not in path.parts


def _assert_reference(root: Path, reference: dict[str, Any]) -> None:
    relative = reference["path"]
    _assert_safe_relative_path(relative)
    path = root / relative
    assert path.is_file(), path
    assert SHA256_RE.fullmatch(reference["sha256"])
    assert _sha256(path) == reference["sha256"], path


def _assert_trust_clock_identity_and_snapshot(variant: dict[str, Any]) -> None:
    root = REPOSITORY_ROOT / variant["path"]
    manifest = _read_json(root / "source-manifest.json")
    mapping = _read_json(root / "entity-mapping.json")
    report = _read_json(root / "normalization-report.json")
    rows = _read_session(root / "session.jsonl")
    expected = variant["expected"]
    variant_id = variant["variant_id"]

    assert manifest["schema_version"] == "metriplane.external_source_contract.v1"
    assert manifest["contract_profile"] == "metriplane.atlas.complete_snapshot.v1"
    assert manifest["fixture"]["fixture_id"] == variant["fixture_id"], variant_id
    assert manifest["normalization"]["frame_state_model_version"] == "1.0"
    assert manifest["normalization"]["authoritative_object_collection"] == "objects"

    assert manifest["trust_layers"] == {
        "adapter_derived_facts": "adapter_and_normalization",
        "expected_outcome_is_atlas_input": False,
        "metriplane_derived_results": "atlas_outputs_only",
        "operator_configured_rules": "domain_pack_only",
        "source_annotations_can_drive_incidents": False,
        "source_facts": "source.artifacts_and_field_provenance",
    }, variant_id
    assert manifest["evaluation"]["engine"] == "atlas"
    assert manifest["evaluation"]["expected_outcome_is_input"] is False
    assert manifest["evaluation"]["provenance_layer"] == "metriplane_derived_results"
    assert manifest["domain_pack"]["rule_origin"] == "operator_configured_rules"
    assert manifest["domain_pack"]["source_annotations_used"] is False

    annotations = manifest["normalization"]["source_annotations"]
    assert annotations["inventory_complete"] is True
    assert annotations["frame_state_events_policy"] == "empty"
    assert annotations["source_incident_ids_in_normalized_input"] is False
    assert annotations["used_as_incident_truth"] is False
    assert annotations["used_as_process_events"] is False

    clock = manifest["normalization"]["clock"]
    for field in (
        "evaluation_field",
        "mapping_method",
        "source_clock",
        "source_field",
        "source_unit",
    ):
        assert isinstance(clock[field], str) and clock[field].strip(), variant_id

    completeness = manifest["normalization"]["completeness"]
    assert completeness["frame_semantics"] == "complete_snapshot"
    assert completeness["omission_policy"] == "reject_omission"
    assert completeness["unknown_state_policy"] == "reject_fixture"
    assert completeness["carry_forward"] == {"fields": [], "method": "none"}

    alignment = manifest["normalization"]["temporal_alignment"]
    assert alignment["interpolation"]["method"] == "none"
    assert alignment["resampling"]["method"] == "none"
    assert isinstance(alignment["synchronization"]["method"], str)

    coordinates = manifest["normalization"]["coordinates"]
    for field in ("source_frame", "source_units", "target_frame", "target_units"):
        assert isinstance(coordinates[field], str) and coordinates[field].strip()
    assert isinstance(coordinates["transform"], dict)
    assert isinstance(coordinates["projection"], dict)
    assert isinstance(coordinates["information_loss"], list)

    provenance_layers = {
        declaration["layer"] for declaration in manifest["normalization"]["field_provenance"]
    }
    assert "adapter_derived_fact" in provenance_layers
    assert provenance_layers <= {"adapter_derived_fact", "source_fact"}

    assert mapping["schema_version"] == "metriplane.external_entity_mapping.v1"
    process_ids = [
        item["normalized_object_id"] for item in mapping["mappings"] if item["process_relevant"]
    ]
    assert process_ids
    assert len(process_ids) == len(set(process_ids))

    assert len(rows) == expected["frame_count"], variant_id
    assert [row["frame_id"] for row in rows] == list(range(len(rows))), variant_id
    timestamps = [row["ts"] for row in rows]
    assert all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in timestamps
    )
    assert all(left < right for left, right in pairwise(timestamps))

    evaluation_field = clock["evaluation_field"]
    assert all(evaluation_field in row for row in rows), variant_id
    if evaluation_field == "ts_sim_ns":
        simulation_times = [row["ts_sim_ns"] for row in rows]
        assert all(
            isinstance(value, int) and not isinstance(value, bool) for value in simulation_times
        )
        assert all(left < right for left, right in pairwise(simulation_times))

    for row in rows:
        assert row["schema_version"] == "1.0", variant_id
        assert row["events"] == [], variant_id
        assert "fused" not in row and "raw_per_camera" not in row
        objects = row["objects"]
        assert len(objects) == expected["objects_per_frame"], variant_id
        assert [item["id"] for item in objects] == process_ids, variant_id
        for item in objects:
            assert isinstance(item["zone"], str) and item["zone"].strip()
            assert len(item["pos_world"]) == 3
            assert all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in item["pos_world"]
            )

    assert report["fixture_id"] == variant["fixture_id"]
    assert report["result"] == "pass"
    assert report["normalized_frame_count"] == expected["frame_count"]
    assert report["process_relevant_entity_count"] == expected["objects_per_frame"]
    assert report["omitted_process_relevant_observations"] == 0
    assert report["unknown_process_relevant_observations"] == 0
    operations = {operation["kind"]: operation for operation in report["operations"]}
    assert {"entity_mapping", "time_mapping", "zone_assignment"} <= operations.keys()
    for operation in ("carry_forward", "interpolation", "resampling"):
        assert operations[operation]["applied"] is False, variant_id


def _assert_checksums_rights_and_provenance(variant: dict[str, Any]) -> None:
    root = REPOSITORY_ROOT / variant["path"]
    manifest = _read_json(root / "source-manifest.json")
    checksum_path = root / "CHECKSUMS.sha256"
    variant_id = variant["variant_id"]

    inventory: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = CHECKSUM_LINE_RE.fullmatch(line)
        assert match is not None, f"{variant_id}: malformed checksum line"
        digest, relative = match.groups()
        _assert_safe_relative_path(relative)
        assert relative not in inventory, f"{variant_id}: duplicate inventory path"
        inventory[relative] = digest

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    assert set(inventory) == actual, variant_id
    for relative, digest in inventory.items():
        path = root / relative
        assert not path.is_symlink(), path
        assert _sha256(path) == digest, path

    assert _sha256(checksum_path) == variant["fixture_fingerprint"], variant_id
    assert _sha256(root / "session.jsonl") == variant["session_sha256"], variant_id
    assert manifest["normalized_artifacts"]["checksums_path"] == "CHECKSUMS.sha256"
    assert manifest["normalized_artifacts"]["session"]["sha256"] == variant["session_sha256"]

    references = [
        manifest["adapter"]["environment"]["dependency_lock"],
        manifest["normalization"]["atlas_asset_mapping"],
        manifest["normalization"]["entity_mapping"],
        manifest["normalized_artifacts"]["expected_outcome"],
        manifest["normalized_artifacts"]["normalization_report"],
        manifest["normalized_artifacts"]["session"],
        *(
            manifest["domain_pack"][name]
            for name in ("assets", "contracts", "process", "work_orders", "workspace")
        ),
    ]
    for reference in references:
        _assert_reference(root, reference)

    assert COMMIT_RE.fullmatch(manifest["adapter"]["commit"]), variant_id
    rights_ids = {
        declaration["rights_id"] for declaration in manifest["rights"]["source_artifacts"]
    }
    artifact_ids: set[str] = set()
    for artifact in manifest["source_artifacts"]:
        assert artifact["artifact_id"] not in artifact_ids
        artifact_ids.add(artifact["artifact_id"])
        assert SHA256_RE.fullmatch(artifact["sha256"])
        assert artifact["rights_id"] in rights_ids
        if artifact["presence"] == "included":
            _assert_reference(root, artifact)
        else:
            assert artifact["presence"] == "referenced"


def _assert_expected_outcome_is_test_only(variant: dict[str, Any]) -> None:
    root = REPOSITORY_ROOT / variant["path"]
    manifest = _read_json(root / "source-manifest.json")
    outcome = _read_json(root / "expected-outcome.json")
    expected = variant["expected"]
    variant_id = variant["variant_id"]

    reference = manifest["normalized_artifacts"]["expected_outcome"]
    assert reference["path"] == "expected-outcome.json"
    assert reference["role"] == "test_metadata_only"
    assert reference["atlas_input"] is False
    assert "expected-outcome.json" not in json.dumps(manifest["adapter"], sort_keys=True)

    assert outcome["schema_version"] == "metriplane.external_expected_outcome.v1"
    assert outcome["fixture_id"] == variant["fixture_id"]
    assert outcome["role"] == "test_metadata_only"
    assert outcome["atlas_input"] is False
    assert outcome["frame_count"] == expected["frame_count"], variant_id
    assert outcome["event_count"] == len(expected["events"]), variant_id
    assert outcome["event_types"] == [event["event_type"] for event in expected["events"]], (
        variant_id
    )
    assert outcome["deviation_count"] == expected["deviation_count"]
    assert outcome["incident_count"] == expected["incident_count"]
    assert outcome["incident_types"] == expected["incident_types"]
    assert outcome["evidence_bundle_verified"] is (expected["bundle_verification"] == "pass")
    assert outcome["regression_passed"] is (expected["regression_execution"] == "pass")


def test_all_registered_fixtures_enforce_contract_trust_and_snapshot_invariants() -> None:
    for variant in _variants():
        assert_fixture_contract(REPOSITORY_ROOT, variant)
        _assert_trust_clock_identity_and_snapshot(variant)


def test_all_registered_fixtures_have_closed_checksum_and_rights_boundaries() -> None:
    for variant in _variants():
        _assert_checksums_rights_and_provenance(variant)


def test_all_registered_expected_outcomes_are_test_only_oracles() -> None:
    for variant in _variants():
        _assert_expected_outcome_is_test_only(variant)


def test_operator_domain_pack_changes_do_not_change_normalized_session(
    tmp_path: Path,
) -> None:
    baseline = REPOSITORY_ROOT / "examples/external_sources/minimal"
    changed = tmp_path / "fixture"
    shutil.copytree(baseline, changed)
    process_path = changed / "domain-pack/process.yaml"
    original_process = process_path.read_text(encoding="utf-8")
    assert "max_wait_s: 2.0" in original_process
    process_path.write_text(
        original_process.replace("max_wait_s: 2.0", "max_wait_s: 20.0"),
        encoding="utf-8",
    )
    manifest_path = changed / "source-manifest.json"
    manifest = _read_json(manifest_path)
    manifest["domain_pack"]["process"]["sha256"] = _sha256(process_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_fixture_checksums(changed)

    baseline_result = run_external_fixture(
        baseline,
        tmp_path / "baseline-run",
        run_id="domain_pack_baseline",
    )
    changed_result = run_external_fixture(
        changed,
        tmp_path / "changed-run",
        run_id="domain_pack_changed",
    )

    assert baseline_result.passed is True
    assert changed_result.passed is True
    assert (changed / "session.jsonl").read_bytes() == (baseline / "session.jsonl").read_bytes()
    assert (
        baseline_result.event_count,
        baseline_result.deviation_count,
        baseline_result.incident_count,
    ) == (5, 1, 1)
    assert (
        changed_result.event_count,
        changed_result.deviation_count,
        changed_result.incident_count,
    ) == (4, 0, 0)
    baseline_provenance = _read_json(tmp_path / "baseline-run/external_source_provenance.json")
    changed_provenance = _read_json(tmp_path / "changed-run/external_source_provenance.json")
    assert (
        baseline_provenance["artifacts"]["normalized_session"]["sha256"]
        == changed_provenance["artifacts"]["normalized_session"]["sha256"]
    )
    assert (
        baseline_provenance["artifacts"]["domain_pack"]["process"]["sha256"]
        != changed_provenance["artifacts"]["domain_pack"]["process"]["sha256"]
    )
