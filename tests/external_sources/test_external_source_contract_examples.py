# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.external_sources.contract import (
    render_external_source_contract_schema,
    validate_external_fixture_bundle,
)
from metriplane.zones import point_in_polygon

REPOSITORY_ROOT = Path(__file__).parents[2]
BUNDLE = REPOSITORY_ROOT / "examples" / "external_sources" / "minimal"
SCHEMA = REPOSITORY_ROOT / "schemas" / "metriplane.external_source_contract.v1.schema.json"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _reference_conversion(bundle: Path) -> tuple[str, str]:
    source = json.loads((bundle / "source" / "trajectory.json").read_text())
    manifest = cast(
        dict[str, Any],
        json.loads((bundle / "source-manifest.json").read_text()),
    )
    mapping_rows = cast(
        list[dict[str, Any]],
        manifest["adapter"]["parameters"]["inline"]["entity_mapping"],
    )
    mapping_document: dict[str, Any] = {
        "mappings": [
            {
                "atlas_asset_id": item["atlas_asset_id"],
                "description": item["description"],
                "normalized_object_id": item["normalized_object_id"],
                "process_relevant": item["process_relevant"],
                "source_entities": [
                    {
                        "source_artifact_id": "trajectory",
                        "source_entity_id": item["source_entity_id"],
                    }
                ],
            }
            for item in mapping_rows
        ],
        "schema_version": "metriplane.external_entity_mapping.v1",
    }
    mapping = {
        item["source_entities"][0]["source_entity_id"]: item["normalized_object_id"]
        for item in mapping_document["mappings"]
    }
    workspace = yaml.safe_load((bundle / "domain-pack" / "workspace.yaml").read_text())
    zones = [
        (
            zone["zone_id"],
            tuple((float(point[0]), float(point[1])) for point in zone["polygon"]),
        )
        for zone in workspace["zones"]
    ]

    rows: list[dict[str, Any]] = []
    for sample in source["samples"]:
        objects = []
        for entity in sample["entities"]:
            x, y, _ = entity["position_xyz"]
            matches = [name for name, polygon in zones if point_in_polygon(x, y, polygon)]
            if len(matches) != 1:
                raise AssertionError(f"zone assignment must have exactly one match: {matches}")
            objects.append(
                {
                    "id": mapping[entity["entity_id"]],
                    "pos_world": [x, y, 0.0],
                    "zone": matches[0],
                }
            )
        rows.append(
            {
                "schema_version": "1.0",
                "source_backend": "external:synthetic_inspection",
                "ts": sample["sample_time_s"],
                "frame_id": sample["sample_index"],
                "objects": objects,
                "events": [],
            }
        )
    session = "".join(
        json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows
    )
    mapping_output = (
        json.dumps(
            mapping_document,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    return session, mapping_output


def test_checked_in_schema_matches_pydantic_model_exactly() -> None:
    assert SCHEMA.read_text(encoding="utf-8") == render_external_source_contract_schema()


def test_positive_external_fixture_validates() -> None:
    fixture = validate_external_fixture_bundle(BUNDLE)
    assert fixture.manifest.fixture.fixture_id == "synthetic-inspection-bench-v1"
    assert fixture.manifest.normalization.frame_state_model_version == "1.0"
    assert fixture.manifest.normalization.authoritative_object_collection == "objects"
    assert len(fixture.frames) == 4
    assert all(frame.events == [] for frame in fixture.frames)
    assert fixture.expected_outcome.atlas_input is False


def test_stage_1_reference_conversion_is_byte_equivalent() -> None:
    first_session, first_mapping = _reference_conversion(BUNDLE)
    second_session, second_mapping = _reference_conversion(BUNDLE)
    checked_in_session = (BUNDLE / "session.jsonl").read_text(encoding="utf-8")
    checked_in_mapping = (BUNDLE / "entity-mapping.json").read_text(encoding="utf-8")
    assert first_session == second_session == checked_in_session
    assert first_mapping == second_mapping == checked_in_mapping


def test_stage_2_atlas_evaluation_is_reproducible(tmp_path: Path) -> None:
    first_out = tmp_path / "first"
    second_out = tmp_path / "second"
    first = run_atlas(
        BUNDLE / "session.jsonl",
        BUNDLE / "domain-pack",
        first_out,
        run_id="external_fixture_minimal_v1",
    )
    second = run_atlas(
        BUNDLE / "session.jsonl",
        BUNDLE / "domain-pack",
        second_out,
        run_id="external_fixture_minimal_v1",
    )

    expected = json.loads((BUNDLE / "expected-outcome.json").read_text())
    assert (first.frame_count, first.event_count, first.deviation_count, first.incident_count) == (
        expected["frame_count"],
        expected["event_count"],
        expected["deviation_count"],
        expected["incident_count"],
    )
    assert first.model_dump() == second.model_dump()
    assert first.source_session_jsonl == "state_segment.jsonl"
    assert first.domain_pack == "configs"
    for name in ("physical_event_log.jsonl", "deviations.jsonl", "incidents.jsonl"):
        assert (first_out / name).read_bytes() == (second_out / name).read_bytes()

    event_types = [row["event_type"] for row in _read_jsonl(first_out / "physical_event_log.jsonl")]
    incident_types = [row["incident_type"] for row in _read_jsonl(first_out / "incidents.jsonl")]
    assert event_types == expected["event_types"]
    assert incident_types == expected["incident_types"]

    for out in (first_out, second_out):
        bundle = out / "evidence_bundles" / "INC-0001.zip"
        regression = out / "regression_tests" / "INC-0001.yaml"
        assert verify_bundle(bundle)["pass"] is expected["evidence_bundle_verified"]
        assert run_regression(regression)["pass"] is expected["regression_passed"]


def test_expected_outcome_is_not_atlas_input(tmp_path: Path) -> None:
    copied = tmp_path / "fixture"
    shutil.copytree(BUNDLE, copied)
    (copied / "expected-outcome.json").write_text(
        json.dumps(
            {
                "schema_version": "invalid-on-purpose",
                "atlas_input": False,
                "incident_count": 999,
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "run"
    manifest = run_atlas(
        copied / "session.jsonl",
        copied / "domain-pack",
        out,
        run_id="expected_outcome_is_not_input",
    )
    assert manifest.event_count == 5
    assert manifest.incident_count == 1
