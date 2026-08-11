# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.atlas.usd import export_usda
from metriplane.external_sources.contract import validate_external_fixture_bundle
from metriplane.external_sources.execution import run_external_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = (
    REPOSITORY_ROOT / "examples" / "external_sources" / "maniskill_pickcube"
)
INCIDENT_FIXTURE = FIXTURE_ROOT / "incident"
CONTROL_FIXTURE = FIXTURE_ROOT / "control"
CONTRACT_SCHEMA = (
    REPOSITORY_ROOT
    / "schemas"
    / "metriplane.external_source_contract.v1.schema.json"
)

CONTRACT_SCHEMA_SHA256 = (
    "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
)
DATASET_REVISION = "d674485bbffdd533914e52d272fdda34c0515608"
GENERATION_COMMIT = "652ad9353c0223507a938f0e8d990dd6f1c771ad"
CONVERSION_COMMIT = "a4a4f9272ad64b1564035874b605ceb687b63ed8"
CONVERSION_WHEEL_SHA256 = (
    "685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a"
)
SOURCE_ARTIFACTS = {
    "pickcube_archive": {
        "sha256": "b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8",
        "size": 36_590_010,
    },
    "pickcube_trajectory_hdf5": {
        "sha256": "03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a",
        "size": 29_349_195,
    },
    "pickcube_trajectory_metadata": {
        "sha256": "16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90",
        "size": 228_218,
    },
}
EXPECTED_FIXTURE_IDS = {
    "incident": "maniskill-pickcube-episode-0-planar-incident-v1",
    "control": "maniskill-pickcube-episode-0-planar-control-v1",
}
EXPECTED_DOMAIN_PACK_IDS = {
    "incident": "maniskill-pickcube-planar-incident-v1",
    "control": "maniskill-pickcube-planar-control-v1",
}
EXPECTED_COUNTS = {
    "incident": (75, 4, 1, 1),
    "control": (75, 3, 0, 0),
}
EXPECTED_EVENT_TYPES = {
    "incident": [
        "required_asset_missing",
        "step_delayed",
        "required_asset_present",
        "step_completed",
    ],
    "control": [
        "required_asset_missing",
        "required_asset_present",
        "step_completed",
    ],
}
EXPECTED_EVENT_FRAMES = {
    "incident": [66, 70, 71, 71],
    "control": [66, 71, 71],
}
GOAL_XY = (0.026815734803676605, -0.0019813179969787598)
TARGET_POLYGON = [
    [0.016815734803676603, -0.01198131799697876],
    [0.03681573480367661, -0.01198131799697876],
    [0.03681573480367661, 0.00801868200302124],
    [0.016815734803676603, 0.00801868200302124],
]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(isinstance(value, dict) for value in values)
    return values


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scalars(value: object) -> list[object]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _scalars(child)]
    if isinstance(value, list):
        return [item for child in value for item in _scalars(child)]
    return [value]


def _load_pack_file(fixture: Path, name: str) -> dict[str, Any]:
    value = yaml.safe_load((fixture / "domain-pack" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _without_waits(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<variant-wait>" if key == "max_wait_s" else _without_waits(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_without_waits(child) for child in value]
    return value


def _canonical_run_semantics(run: Path) -> dict[str, Any]:
    regressions: list[dict[str, Any]] = []
    for path in sorted((run / "regression_tests").glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        value.pop("source_bundle", None)
        regressions.append(value)
    return {
        "state": _read_jsonl(run / "state_segment.jsonl"),
        "events": _read_jsonl(run / "physical_event_log.jsonl"),
        "deviations": _read_jsonl(run / "deviations.jsonl"),
        "incidents": _read_jsonl(run / "incidents.jsonl"),
        "regressions": regressions,
    }


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_fixture_contract_source_identity_rights_and_provenance(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    manifest = fixture.manifest

    assert manifest.fixture.fixture_id == EXPECTED_FIXTURE_IDS[variant]
    assert manifest.fixture.bounded_recording is True
    assert manifest.fixture.distribution == "derived_only"
    assert manifest.domain_pack.domain_pack_id == EXPECTED_DOMAIN_PACK_IDS[variant]
    assert manifest.domain_pack.rule_origin == "operator_configured_rules"
    assert manifest.domain_pack.source_annotations_used is False
    assert manifest.evaluation.domain_pack_id == EXPECTED_DOMAIN_PACK_IDS[variant]
    assert manifest.evaluation.expected_outcome_is_input is False
    assert manifest.source_project.revision.kind == "dataset_revision"
    assert manifest.source_project.revision.value == DATASET_REVISION
    assert manifest.selection.method == "episode"
    assert manifest.selection.episode_id == "0"
    assert set(manifest.selection.artifact_ids) == {
        "pickcube_trajectory_hdf5",
        "pickcube_trajectory_metadata",
    }

    artifacts = {artifact.artifact_id: artifact for artifact in manifest.source_artifacts}
    assert set(artifacts) == set(SOURCE_ARTIFACTS)
    for artifact_id, expected in SOURCE_ARTIFACTS.items():
        artifact = artifacts[artifact_id]
        assert artifact.presence == "referenced"
        assert artifact.path is None
        assert artifact.uri is not None
        assert DATASET_REVISION in artifact.uri
        assert artifact.sha256 == expected["sha256"]

    manifest_raw = _read_json(root / "source-manifest.json")
    scalars = _scalars(manifest_raw)
    for expected in SOURCE_ARTIFACTS.values():
        assert expected["size"] in scalars
    assert GENERATION_COMMIT in scalars
    assert CONVERSION_COMMIT in scalars
    assert CONVERSION_WHEEL_SHA256 in scalars
    assert "3.0.0b4" in scalars
    assert "3.0.1" in scalars
    assert "traj_0" in scalars
    assert 74 in scalars
    assert 75 in scalars
    assert 50 in scalars
    assert GOAL_XY[0] in scalars
    assert GOAL_XY[1] in scalars

    assert manifest.adapter.adapter_id == "org.metriplane.maniskill_pickcube"
    assert re.fullmatch(r"[0-9a-f]{40}", manifest.adapter.commit)
    assert manifest.adapter.environment.dependency_lock is not None
    assert manifest.rights.fixture.access == "public"
    assert manifest.rights.fixture.license.status == "declared"
    assert manifest.rights.fixture.license.identifier == "Apache-2.0"
    assert manifest.rights.fixture.redistribution == "allowed"
    assert manifest.rights.fixture.redistribution_permission == "verified"
    assert all(
        declaration.license.identifier == "Apache-2.0"
        and declaration.source_access == "public"
        and declaration.source_use_permission == "verified"
        and declaration.redistribution == "derived_only"
        and declaration.redistribution_permission == "verified"
        for declaration in manifest.rights.source_artifacts
    )

    annotations = manifest.normalization.source_annotations
    assert annotations.inventory_complete is True
    assert annotations.used_as_incident_truth is False
    assert annotations.used_as_process_events is False
    assert annotations.source_incident_ids_in_normalized_input is False
    assert annotations.frame_state_events_policy == "empty"
    annotation_names = {annotation.name.lower() for annotation in annotations.annotations}
    assert {"reward", "success", "terminated", "truncated"}.issubset(annotation_names)

    limitations = " ".join(
        [*manifest.limitations, *fixture.normalization_report.limitations]
    ).lower()
    for required in (
        "orientation",
        "quaternion",
        "planar",
        "pickcube success",
        "physical accuracy",
        "simulator realism",
        "success-filtered",
    ):
        assert required in limitations


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_session_is_complete_position_only_and_uses_authoritative_integer_time(
    variant: str,
) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    manifest = fixture.manifest
    rows = _read_jsonl(root / "session.jsonl")

    assert len(rows) == len(fixture.frames) == 75
    assert manifest.normalization.authoritative_object_collection == "objects"
    clock = manifest.normalization.clock
    assert clock.source_unit == "index"
    assert clock.evaluation_field == "ts_sim_ns"
    assert clock.mapping_method == "fixed_step"
    assert clock.fixed_step_origin_ns == 0
    assert clock.fixed_step_ns == 50_000_000
    assert manifest.normalization.confidence.mode == "absent"
    assert manifest.normalization.coordinates.projection.method == "planar_xy"
    assert manifest.normalization.coordinates.projection.dropped_axes == ["z"]
    assert manifest.normalization.coordinates.projection.output_z_policy == "zero"
    assert manifest.normalization.completeness.source_stream_semantics == "complete_snapshot"
    assert manifest.normalization.completeness.carry_forward.method == "none"
    assert manifest.normalization.temporal_alignment.interpolation.method == "none"
    assert manifest.normalization.temporal_alignment.resampling.method == "none"
    assert manifest.normalization.temporal_alignment.synchronization.method == "not_applicable"

    for index, row in enumerate(rows):
        assert set(row) == {
            "schema_version",
            "source_backend",
            "ts",
            "ts_sim_ns",
            "frame_id",
            "objects",
            "events",
        }
        assert row["frame_id"] == index
        assert row["ts_sim_ns"] == index * 50_000_000
        assert row["ts"] == row["ts_sim_ns"] / 1_000_000_000.0
        assert row["events"] == []
        assert [item["id"] for item in row["objects"]] == ["cube_1", "robot_tcp_1"]
        for item in row["objects"]:
            assert set(item) == {"id", "pos_world", "zone"}
            assert len(item["pos_world"]) == 3
            assert item["pos_world"][2] == 0.0
            assert item["zone"] in {"target_xy_region", "outside_workspace"}

    assert rows[0]["objects"][0]["pos_world"] == [
        -0.0007486790418624878,
        0.053644366562366486,
        0.0,
    ]
    assert rows[-1]["objects"][0]["pos_world"] == [
        0.02027886174619198,
        -0.0009062606259249151,
        0.0,
    ]
    assert rows[0]["objects"][1]["pos_world"] == [
        0.012253533117473125,
        0.0380113385617733,
        0.0,
    ]
    assert rows[-1]["objects"][1]["pos_world"] == [
        0.01749647594988346,
        -0.0017431047745049,
        0.0,
    ]
    assert [
        row["frame_id"]
        for row in rows
        if row["objects"][0]["zone"] == "target_xy_region"
    ] == list(range(66, 75))
    assert [
        row["frame_id"]
        for row in rows
        if row["objects"][1]["zone"] == "target_xy_region"
    ] == list(range(71, 75))

    declared_fields = {
        item.normalized_field for item in manifest.normalization.field_provenance
    }
    assert declared_fields == {
        "schema_version",
        "source_backend",
        "ts",
        "ts_sim_ns",
        "frame_id",
        "objects[*].id",
        "objects[*].pos_world",
        "objects[*].zone",
    }


def test_incident_and_control_share_state_mapping_geometry_and_assets() -> None:
    for relative_path in (
        "session.jsonl",
        "entity-mapping.json",
        "domain-pack/workspace.yaml",
        "domain-pack/assets.yaml",
        "domain-pack/work_orders.csv",
        "source/adapter-environment.txt",
    ):
        assert (INCIDENT_FIXTURE / relative_path).read_bytes() == (
            CONTROL_FIXTURE / relative_path
        ).read_bytes(), relative_path

    workspace = _load_pack_file(INCIDENT_FIXTURE, "workspace.yaml")
    assert workspace["units"] == "meters"
    assert len(workspace["zones"]) == 1
    zone = workspace["zones"][0]
    assert zone["zone_id"] == "target_xy_region"
    assert zone["polygon"] == TARGET_POLYGON
    assert workspace["stations"] == [
        {
            "station_id": "target_station",
            "zone_id": "target_xy_region",
            "label": workspace["stations"][0]["label"],
        }
    ]

    assets = _load_pack_file(INCIDENT_FIXTURE, "assets.yaml")["assets"]
    by_id = {item["asset_id"]: item for item in assets}
    assert set(by_id) == {"cube_1", "robot_tcp_1"}
    assert by_id["cube_1"]["object_id"] == "cube_1"
    assert by_id["cube_1"]["asset_type"] == "material"
    assert by_id["robot_tcp_1"]["object_id"] == "robot_tcp_1"
    assert by_id["robot_tcp_1"]["asset_type"] == "tool"

    incident_process = _load_pack_file(INCIDENT_FIXTURE, "process.yaml")
    control_process = _load_pack_file(CONTROL_FIXTURE, "process.yaml")
    incident_contracts = _load_pack_file(INCIDENT_FIXTURE, "contracts.yaml")
    control_contracts = _load_pack_file(CONTROL_FIXTURE, "contracts.yaml")
    assert _without_waits(incident_process) == _without_waits(control_process)
    assert _without_waits(incident_contracts) == _without_waits(control_contracts)

    incident_step = incident_process["steps"][0]
    control_step = control_process["steps"][0]
    assert incident_step["expected_asset_types"] == ["material"]
    assert incident_step["required_assets"] == ["robot_tcp_1"]
    assert incident_step["required_zone"] == "target_xy_region"
    assert incident_step["required_station"] == "target_station"
    assert incident_step["max_wait_s"] == 0.20
    assert control_step["max_wait_s"] == 0.30
    assert incident_contracts["contracts"][0]["max_wait_s"] == 0.20
    assert control_contracts["contracts"][0]["max_wait_s"] == 0.30

    for root in (INCIDENT_FIXTURE, CONTROL_FIXTURE):
        manifest = _read_json(root / "source-manifest.json")
        rationale = manifest["domain_pack"]["rationale"]
        assert "Metriplane compatibility-test rule" in rationale
        assert "not a ManiSkill task-success definition" in rationale


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_three_atlas_runs_have_the_frozen_outcome_and_equivalent_semantics(
    variant: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = FIXTURE_ROOT / variant
    expected = _read_json(fixture / "expected-outcome.json")
    expected_counts = EXPECTED_COUNTS[variant]
    canonical: list[dict[str, Any]] = []
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "a" * 40)

    for index in range(3):
        output = tmp_path / f"{variant}-run-{index}"
        summary = run_external_fixture(
            fixture,
            output,
            run_id=f"maniskill_pickcube_{variant}",
        )
        assert summary.passed is True, summary.errors
        assert (
            summary.frame_count,
            summary.event_count,
            summary.deviation_count,
            summary.incident_count,
        ) == expected_counts
        events = _read_jsonl(output / "physical_event_log.jsonl")
        assert [event["event_type"] for event in events] == EXPECTED_EVENT_TYPES[variant]
        assert [event["frame_id"] for event in events] == EXPECTED_EVENT_FRAMES[variant]
        assert expected["event_types"] == EXPECTED_EVENT_TYPES[variant]
        assert expected["event_count"] == expected_counts[1]
        assert expected["deviation_count"] == expected_counts[2]
        assert expected["incident_count"] == expected_counts[3]

        if variant == "incident":
            deviations = _read_jsonl(output / "deviations.jsonl")
            incidents = _read_jsonl(output / "incidents.jsonl")
            assert [item["type"] for item in deviations] == ["missing_required_asset"]
            assert [item["incident_type"] for item in incidents] == [
                "missing_tool_caused_delay"
            ]
            delayed = events[1]
            assert delayed["value"] == 0.2
            assert delayed["threshold"] == 0.2
            assert incidents[0]["start_ts"] == 3.3
            assert incidents[0]["end_ts"] == 3.5
            assert len(summary.evidence_bundles) == 1
            assert len(summary.generated_regressions) == 1
            bundle = output / "evidence_bundles" / "INC-0001.zip"
            regression = output / "regression_tests" / "INC-0001.yaml"
            assert verify_bundle(bundle)["pass"] is True
            assert run_regression(regression)["pass"] is True
        else:
            assert summary.evidence_bundles == []
            assert summary.generated_regressions == []
            assert list((output / "evidence_bundles").glob("*.zip")) == []
            assert list((output / "regression_tests").glob("*.yaml")) == []

        canonical.append(_canonical_run_semantics(output))

    assert canonical[0] == canonical[1] == canonical[2]


_GENERIC_PRIVATE_PATH = re.compile(
    rb"(?:/(?:home|Users)/[^/\s\"'<>]+(?:/|(?=[\s\"'<>]|$))|"
    rb"(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/])"
)


def _assert_no_generic_private_path(raw: bytes, location: object) -> None:
    assert _GENERIC_PRIVATE_PATH.search(raw) is None, location


def _assert_no_path_leak(root: Path, forbidden: list[str]) -> None:
    forbidden_bytes = [value.encode("utf-8") for value in forbidden]
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        assert all(value not in raw for value in forbidden_bytes), path
        _assert_no_generic_private_path(raw, path)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    name = info.filename
                    name_bytes = name.encode("utf-8")
                    assert all(value not in name_bytes for value in forbidden_bytes), (
                        path,
                        name,
                    )
                    _assert_no_generic_private_path(name_bytes, (path, name))
                    assert not name.startswith(("/", "\\")), (path, name)
                    assert ".." not in Path(name).parts, (path, name)
                    if info.is_dir():
                        continue
                    member = archive.read(info)
                    assert all(value not in member for value in forbidden_bytes), (
                        path,
                        name,
                    )
                    _assert_no_generic_private_path(member, (path, name))


def _assert_durable_outputs(root: Path, *, external: bool, incident: bool) -> None:
    required = {
        "atlas_dashboard.html",
        "atlas_manifest.json",
        "cell_truth_report.html",
        "cell_truth_report.md",
        "configs/assets.yaml",
        "configs/contracts.yaml",
        "configs/process.yaml",
        "configs/work_orders.csv",
        "configs/workspace.yaml",
        "connectors/events.csv",
        "connectors/incidents.csv",
        "connectors/mqtt_topics.json",
        "connectors/rest_snapshot.json",
        "connectors/webhook_payload.json",
        "deviations.jsonl",
        "incidents.jsonl",
        "physical_event_log.jsonl",
        "privacy_report.json",
        "state_segment.jsonl",
        "twinverify_replay.usda",
    }
    if external:
        required.add("external_source_provenance.json")
    if incident:
        required.update(
            {
                "evidence_bundles/INC-0001.zip",
                "evidence_bundles/INC-0001/manifest.json",
                "regression_tests/INC-0001.yaml",
            }
        )
    expected_empty = set() if incident else {"deviations.jsonl", "incidents.jsonl"}
    for relative in sorted(required):
        path = root / relative
        assert path.is_file(), relative
        if relative not in expected_empty:
            assert path.stat().st_size > 0, relative
    for relative in (
        "atlas_manifest.json",
        "connectors/mqtt_topics.json",
        "connectors/rest_snapshot.json",
        "connectors/webhook_payload.json",
        "privacy_report.json",
    ):
        assert isinstance(_read_json(root / relative), dict), relative


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_run_is_movable_and_contains_no_operational_path(
    variant: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_home = tmp_path / "PRIVATE_USER_HOME_SENTINEL"
    private_source_root = tmp_path / "PRIVATE_SOURCE_ROOT_SENTINEL"
    private_fixture_root = tmp_path / "PRIVATE_FIXTURE_ROOT_SENTINEL"
    private_fixture = private_fixture_root / variant
    private_pack_root = tmp_path / "PRIVATE_PACK_ROOT_SENTINEL"
    private_output_root = tmp_path / "PRIVATE_OUTPUT_ROOT_SENTINEL"
    private_cache_root = tmp_path / "PRIVATE_CACHE_ROOT_SENTINEL"
    moved_output = tmp_path / "portable-runs"
    private_home.mkdir()
    private_source_root.mkdir()
    private_cache_root.mkdir()
    shutil.copytree(FIXTURE_ROOT / variant, private_fixture)
    shutil.copytree(private_fixture / "domain-pack", private_pack_root)
    private_session = private_source_root / "session.jsonl"
    shutil.copyfile(private_fixture / "session.jsonl", private_session)
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(private_cache_root / "xdg"))
    monkeypatch.setenv("MPLCONFIGDIR", str(private_cache_root / "matplotlib"))
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "b" * 40)

    external_output = private_output_root / "external"
    summary = run_external_fixture(
        private_fixture,
        external_output,
        run_id=f"movable_{variant}",
    )
    assert summary.passed is True, summary.errors
    direct_output = private_output_root / "direct"
    direct_manifest = run_atlas(
        private_session,
        private_pack_root,
        direct_output,
        run_id=f"direct_movable_{variant}",
    )
    assert direct_manifest.frame_count == 75

    shutil.rmtree(private_fixture_root)
    shutil.rmtree(private_source_root)
    shutil.rmtree(private_pack_root)
    shutil.rmtree(private_cache_root)
    shutil.move(private_output_root, moved_output)
    moved_external = moved_output / "external"
    moved_direct = moved_output / "direct"

    for run in (moved_external, moved_direct):
        manifest = _read_json(run / "atlas_manifest.json")
        assert manifest["source_session_jsonl"] == "state_segment.jsonl"
        assert manifest["domain_pack"] == "configs"
        exported = export_usda(run)
        assert exported.is_file()
    _assert_durable_outputs(
        moved_external,
        external=True,
        incident=variant == "incident",
    )
    _assert_durable_outputs(
        moved_direct,
        external=False,
        incident=variant == "incident",
    )

    if variant == "incident":
        assert verify_bundle(moved_external / "evidence_bundles" / "INC-0001.zip")[
            "pass"
        ] is True
        assert run_regression(moved_external / "regression_tests" / "INC-0001.yaml")[
            "pass"
        ] is True
    else:
        for run in (moved_external, moved_direct):
            assert list((run / "evidence_bundles").glob("*.zip")) == []
            assert list((run / "regression_tests").glob("*.yaml")) == []

    _assert_no_path_leak(
        moved_output,
        [
            "PRIVATE_USER_HOME_SENTINEL",
            "PRIVATE_SOURCE_ROOT_SENTINEL",
            "PRIVATE_FIXTURE_ROOT_SENTINEL",
            "PRIVATE_PACK_ROOT_SENTINEL",
            "PRIVATE_OUTPUT_ROOT_SENTINEL",
            "PRIVATE_CACHE_ROOT_SENTINEL",
            str(private_home.resolve()),
            str(private_source_root.resolve()),
            str(private_fixture_root.resolve()),
            str(private_fixture.resolve()),
            str(private_pack_root.resolve()),
            str(private_output_root.resolve()),
            str(private_cache_root.resolve()),
            str(moved_output.resolve()),
            str(REPOSITORY_ROOT.resolve()),
        ],
    )


def test_checked_in_fixtures_contain_no_local_paths() -> None:
    forbidden = [
        "PRIVATE_USER_HOME_SENTINEL",
        "PRIVATE_SOURCE_ROOT_SENTINEL",
        "PRIVATE_FIXTURE_ROOT_SENTINEL",
        "PRIVATE_PACK_ROOT_SENTINEL",
        "PRIVATE_OUTPUT_ROOT_SENTINEL",
        "PRIVATE_CACHE_ROOT_SENTINEL",
        "/tmp/",
        "/private/tmp/",
        "/var/folders/",
        "/workspace/",
        str(REPOSITORY_ROOT.resolve()),
    ]
    for root in (INCIDENT_FIXTURE, CONTROL_FIXTURE):
        _assert_no_path_leak(root, forbidden)


def test_raw_source_and_source_assets_are_absent_from_portable_fixtures() -> None:
    prohibited_suffixes = {
        ".glb",
        ".h5",
        ".mp4",
        ".pt",
        ".pth",
        ".png",
        ".urdf",
        ".zip",
    }
    for root in (INCIDENT_FIXTURE, CONTROL_FIXTURE):
        files = [path for path in root.rglob("*") if path.is_file()]
        assert all(path.suffix.lower() not in prohibited_suffixes for path in files)
        assert all(path.name not in {"trajectory.json", "trajectory.h5"} for path in files)
        fixture = validate_external_fixture_bundle(root)
        assert all(artifact.presence == "referenced" for artifact in fixture.manifest.source_artifacts)


def test_root_dependency_import_and_wheel_discovery_boundary_is_source_neutral() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_text = "\n".join(pyproject["project"]["dependencies"]).lower()
    lock_text = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    prohibited_packages = (
        "mani-skill",
        "mani_skill",
        "sapien",
        "torch",
        "h5py",
        "huggingface-hub",
        "huggingface_hub",
    )
    assert all(package not in dependency_text for package in prohibited_packages)
    assert all(
        re.search(rf'(?m)^name = "{re.escape(package)}"$', lock_text) is None
        for package in prohibited_packages
    )

    forbidden_import = re.compile(
        r"(?m)^\s*(?:from|import)\s+"
        r"(?:mani_skill|sapien|torch|h5py|huggingface_hub)(?:\.|\s|$)"
    )
    for source_path in (REPOSITORY_ROOT / "metriplane").rglob("*.py"):
        assert forbidden_import.search(source_path.read_text(encoding="utf-8")) is None, source_path

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    assert package_find["include"] == ["metriplane*", "integrations*"]
    assert all("adapter" not in pattern.lower() for pattern in package_find["include"])
    assert not (REPOSITORY_ROOT / "metriplane" / "adapters").exists()
    assert not any(
        path.suffix.lower() in {".h5", ".zip", ".urdf", ".glb", ".pt"}
        for path in (REPOSITORY_ROOT / "metriplane").rglob("*")
        if path.is_file()
    )


def test_external_contract_schema_remains_frozen() -> None:
    assert _sha256(CONTRACT_SCHEMA) == CONTRACT_SCHEMA_SHA256
