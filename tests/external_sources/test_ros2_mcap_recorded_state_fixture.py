# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.atlas.usd import export_usda
from metriplane.external_sources.contract import validate_external_fixture_bundle
from metriplane.external_sources.execution import run_external_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "external_sources" / "ros2_mcap"
CONTRACT_SCHEMA = REPOSITORY_ROOT / "schemas" / "metriplane.external_source_contract.v1.schema.json"

STARTING_BASELINE = "f8a3a48752101d74f658124e23354f0816e20a21"
SDK_COMMIT = "975fda022962b9f1f6a1b986693557600a320916"
SDK_TREE = "88179a50330fb07a278369a341f8aa1f1e909204"
ADAPTER_COMMIT = "04090e510fa2bccd4fe3ac90521d3201a7c1b7c7"
ADAPTER_TREE = "5fa1b18dba8358661e3f59814c29ed7fa0d6a6a7"
CONTRACT_SCHEMA_SHA256 = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
SOURCE_CLASSIFICATION = "FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE"
SOURCE_SIZE = 28_735
SOURCE_SHA256 = "c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99"
CONFIG_SHA256 = "a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962"
LOCK_SHA256 = "864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6"
SESSION_SHA256 = "4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8"
CAPABILITY_CANONICAL_SHA256 = "3bb37c0457a945fbea166e339d57c373e8251620f3a90ec3a02992fec7b01db7"
CAPABILITY_FILE_SHA256 = "18b2ceb08568aaf3975d3bdf87354d182d93551625f5e8b59a25cd4aa36ba27d"
ROOT_INVENTORY_SHA256 = "0a3dd86c91e2c5a78a3fbafcfdaad6d6de7e1669812f99968f8e73626d2726de"
CONVERSION_SUMMARY_SHA256 = "bff6ff0456178798bd3d987f3c3a687b900aa0c511e571b72d06503765067218"
EXPECTED_FINGERPRINTS = {
    "incident": "79d1061df5e4f8880f29ead31de3dfac8adae5cf52fbe269513cb6beeb67ae31",
    "control": "559f9c803da6514c82c4ee83c2b925d505be88db2a57582daf7e1d82ec68db42",
}
EXPECTED_FIXTURE_IDS = {
    "incident": "ros2_mcap_synthetic_incident_v1",
    "control": "ros2_mcap_synthetic_control_v1",
}
EXPECTED_COUNTS = {"incident": (60, 4, 1, 1), "control": (60, 3, 0, 0)}
EXPECTED_EVENT_TYPES = {
    "incident": [
        "required_asset_missing",
        "step_delayed",
        "required_asset_present",
        "step_completed",
    ],
    "control": ["required_asset_missing", "required_asset_present", "step_completed"],
}
EXPECTED_EVENT_FRAMES = {"incident": [5, 10, 15, 15], "control": [5, 15, 15]}
EXPECTED_SCHEMA_HASHES = {
    "geometry_msgs/msg/PoseStamped": (
        "a80b6e20113061c6a8cbd4a5e623d7e1aa54d68deebbc3e69738ff1e502daae8"
    ),
    "tf2_msgs/msg/TFMessage": ("e9121b91448577bf5075f9b1a00b8afcaeeab85422497da524a0cbef10896502"),
    "metriplane_msgs/msg/SourceOutcome": (
        "954f2e44e4c2e2e2654f9de20dc68de75f5a219d2d591c2fde40ac93d5366a80"
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert all(isinstance(value, dict) for value in values)
    return values


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    data = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    return hashlib.sha256(data).hexdigest()


def _load_pack(root: Path, name: str) -> dict[str, Any]:
    value = yaml.safe_load((root / "domain-pack" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _without_wait(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<variant-wait>" if key == "max_wait_s" else _without_wait(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_without_wait(child) for child in value]
    return value


def _parse_inventory(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        assert match is not None, line
        digest, relative = match.groups()
        assert relative not in values
        assert not relative.startswith(("/", "../"))
        assert "\\" not in relative and ".." not in Path(relative).parts
        values[relative] = digest
    return values


def test_complete_inventory_and_frozen_package_identities() -> None:
    inventory_path = FIXTURE_ROOT / "SHA256SUMS"
    assert _sha256(inventory_path) == ROOT_INVENTORY_SHA256
    inventory = _parse_inventory(inventory_path)
    actual = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    assert set(inventory) == actual
    for relative, expected in inventory.items():
        assert _sha256(FIXTURE_ROOT / relative) == expected
    assert inventory["capability-record.json"] == CAPABILITY_FILE_SHA256
    assert inventory["conversion-summary.json"] == CONVERSION_SUMMARY_SHA256
    for variant, expected in EXPECTED_FINGERPRINTS.items():
        assert inventory[f"{variant}/CHECKSUMS.sha256"] == expected


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_contract_identity_rights_and_source_boundary(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    manifest = fixture.manifest
    raw = _read_json(root / "source-manifest.json")
    extension = raw["extensions"]["org.metriplane.ros2_mcap_recorded_state"]

    assert manifest.schema_version == "metriplane.external_source_contract.v1"
    assert manifest.contract_profile == "metriplane.atlas.complete_snapshot.v1"
    assert manifest.fixture.fixture_id == EXPECTED_FIXTURE_IDS[variant]
    assert manifest.fixture.bounded_recording is True
    assert manifest.fixture.distribution == "derived_only"
    assert manifest.adapter.commit == ADAPTER_COMMIT
    assert manifest.adapter.environment.runtime == "CPython"
    assert manifest.adapter.environment.runtime_version == "3.12"
    assert manifest.adapter.parameters.sha256 == CONFIG_SHA256
    assert manifest.adapter.environment.dependency_lock is not None
    assert manifest.adapter.environment.dependency_lock.sha256 == LOCK_SHA256
    assert manifest.evaluation.metriplane_version == "0.3.0"
    assert manifest.evaluation.expected_outcome_is_input is False
    assert manifest.domain_pack.rule_origin == "operator_configured_rules"
    assert manifest.domain_pack.source_annotations_used is False

    assert len(manifest.source_artifacts) == 1
    artifact = manifest.source_artifacts[0]
    assert artifact.artifact_id == "metriplane_synthetic_ros2_mcap_v1"
    assert artifact.presence == "referenced"
    assert artifact.path is None
    assert artifact.sha256 == SOURCE_SHA256
    assert artifact.immutable_identifier == SOURCE_SHA256
    assert ADAPTER_COMMIT in (artifact.uri or "")
    assert extension["source_size"] == SOURCE_SIZE
    assert extension["source_classification"] == SOURCE_CLASSIFICATION
    assert extension["profile"] == "metriplane.ros2_mcap_recorded_state.v1"
    assert extension["clock_domain"] == "ROS_TIME"
    assert extension["evaluation_clock_field"] == ("geometry_msgs/msg/PoseStamped.header.stamp")
    assert extension["log_time_role"] == "container_provenance_only"
    assert extension["publish_time_role"] == "transport_provenance_only"
    assert extension["outcome_stream_present"] is True
    assert extension["outcome_stream_message_count"] == 60

    assert manifest.rights.fixture.license.identifier == "MIT"
    assert manifest.rights.fixture.redistribution_permission == "verified"
    assert len(manifest.rights.source_artifacts) == 1
    source_rights = manifest.rights.source_artifacts[0]
    assert source_rights.license.identifier == "MIT AND Apache-2.0 AND BSD-3-Clause"
    assert source_rights.source_use_permission == "verified"
    assert source_rights.redistribution_permission == "verified"
    limitations = " ".join(manifest.limitations).lower()
    for fragment in (
        "synthetic format-engineering",
        "not general ros 2",
        "position-only planar",
        "no discovery",
        "operator-authored",
    ):
        assert fragment in limitations


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_message_clock_tf_and_materialization_provenance(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    manifest = fixture.manifest
    raw = _read_json(root / "source-manifest.json")
    extension = raw["extensions"]["org.metriplane.ros2_mcap_recorded_state"]

    schemas = {item["name"]: item for item in extension["schema_inventory"]}
    assert set(schemas) == set(EXPECTED_SCHEMA_HASHES)
    for name, expected in EXPECTED_SCHEMA_HASHES.items():
        assert schemas[name]["encoding"] == "ros2msg"
        assert schemas[name]["sha256"] == expected
    channels = {item["topic"]: item for item in extension["channel_inventory"]}
    assert set(channels) == {
        "/tf_static",
        "/metriplane/material_pose",
        "/metriplane/tool_pose",
        "/metriplane/source_outcome",
    }
    assert all(item["message_encoding"] == "cdr" for item in channels.values())

    clock = manifest.normalization.clock
    assert clock.source_field == "geometry_msgs/msg/PoseStamped.header.stamp"
    assert clock.source_unit == "nanoseconds"
    assert clock.evaluation_field == "ts_sim_ns"
    assert clock.mapping_method == "affine"
    assert clock.offset == -1_000_000_000
    assert clock.scale == 1.0
    assert "ROS_TIME" in clock.source_clock

    coordinates = manifest.normalization.coordinates
    assert coordinates.source_frame == "sensor_frame"
    assert coordinates.target_frame == "world"
    assert coordinates.source_units == coordinates.target_units == "meters"
    assert coordinates.transform.method == "rigid_matrix"
    assert coordinates.projection.method == "planar_xy"
    assert coordinates.projection.dropped_axes == ["z"]
    assert coordinates.projection.output_z_policy == "zero"
    assert coordinates.information_loss[0].lost_information == [
        "transformed world z",
        "complete source pose orientation",
    ]

    completeness = manifest.normalization.completeness
    assert completeness.source_stream_semantics == "partial_update"
    assert completeness.partial_updates_materialized is True
    assert completeness.frame_semantics == "complete_snapshot"
    assert completeness.unknown_state_policy == "reject_fixture"
    assert completeness.omission_policy == "reject_omission"
    assert completeness.carry_forward.method == "none"
    alignment = manifest.normalization.temporal_alignment
    assert alignment.synchronization.method == "exact_timestamp"
    assert alignment.synchronization.max_skew_ns == 0
    assert alignment.interpolation.method == "none"
    assert alignment.resampling.method == "none"

    annotations = manifest.normalization.source_annotations
    assert annotations.inventory_complete is True
    assert annotations.used_as_incident_truth is False
    assert annotations.used_as_process_events is False
    assert annotations.frame_state_events_policy == "empty"
    assert {item.name for item in annotations.annotations} == {
        "success",
        "result",
        "alarm",
        "action",
        "annotation",
    }
    assert all(item.treatment == "excluded" for item in annotations.annotations)

    transform = _read_json(FIXTURE_ROOT / "transform-provenance.json")
    assert transform["composition_order"] == "sensor_frame -> cell_frame -> world"
    assert transform["interpolation"] == "none"
    assert transform["extrapolation"] == "none"
    assert transform["carry_forward"] == "none"
    assert [
        (item["parent_frame_id"], item["child_frame_id"], item["type"])
        for item in transform["transforms"]
    ] == [("world", "cell_frame", "static"), ("cell_frame", "sensor_frame", "static")]
    assert all(item["timestamp_ns"] == 0 for item in transform["transforms"])


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_complete_position_only_session_and_authoritative_integer_time(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    rows = _read_jsonl(root / "session.jsonl")
    fixture = validate_external_fixture_bundle(root)
    assert len(rows) == len(fixture.frames) == 60
    assert _sha256(root / "session.jsonl") == SESSION_SHA256
    for index, row in enumerate(rows):
        assert set(row) == {
            "events",
            "frame_id",
            "objects",
            "schema_version",
            "source_backend",
            "ts",
            "ts_sim_ns",
        }
        assert row["frame_id"] == index
        assert row["ts_sim_ns"] == index * 100_000_000
        assert row["ts"] == row["ts_sim_ns"] / 1_000_000_000
        assert row["events"] == []
        assert row["source_backend"] == "ros2_mcap_recorded_state_v1_synthetic"
        assert [item["id"] for item in row["objects"]] == ["material_1", "tool_1"]
        assert all(set(item) == {"id", "pos_world", "zone"} for item in row["objects"])
        assert all(item["pos_world"][2] == 0.0 for item in row["objects"])
    assert rows[0]["objects"] == [
        {"id": "material_1", "pos_world": [0.2, 0.0, 0.0], "zone": "outside_workspace"},
        {"id": "tool_1", "pos_world": [0.1, -0.3, 0.0], "zone": "outside_workspace"},
    ]
    assert [
        row["frame_id"] for row in rows if row["objects"][0]["zone"] == "target_xy_region"
    ] == list(range(5, 40))
    assert [
        row["frame_id"] for row in rows if row["objects"][1]["zone"] == "target_xy_region"
    ] == list(range(15, 41))


def test_incident_and_control_differ_only_in_operator_wait_and_outcome_metadata() -> None:
    incident = FIXTURE_ROOT / "incident"
    control = FIXTURE_ROOT / "control"
    shared = (
        "session.jsonl",
        "entity-mapping.json",
        "domain-pack/assets.yaml",
        "domain-pack/workspace.yaml",
        "domain-pack/work_orders.csv",
        "source/adapter-environment.txt",
        "source/frozen-config.json",
        "source/uv.lock",
    )
    for relative in shared:
        assert (incident / relative).read_bytes() == (control / relative).read_bytes()
    for name in ("process.yaml", "contracts.yaml"):
        assert _without_wait(_load_pack(incident, name)) == _without_wait(_load_pack(control, name))
    assert _load_pack(incident, "process.yaml")["steps"][0]["max_wait_s"] == 0.5
    assert _load_pack(control, "process.yaml")["steps"][0]["max_wait_s"] == 1.2
    workspace = _load_pack(incident, "workspace.yaml")
    assert workspace["units"] == "meters"
    assert workspace["zones"][0]["polygon"] == [
        [0.45, -0.05],
        [0.55, -0.05],
        [0.55, 0.05],
        [0.45, 0.05],
    ]


def test_capability_record_is_synthetic_partial_and_frozen() -> None:
    record = _read_json(FIXTURE_ROOT / "capability-record.json")
    assert _sha256(FIXTURE_ROOT / "capability-record.json") == CAPABILITY_FILE_SHA256
    assert _canonical_sha256(record) == CAPABILITY_CANONICAL_SHA256
    assert record["schema_version"] == "metriplane.source_adapter_capability.v1"
    assert record["record"] == {
        "classification": "native",
        "evidence_classification": "synthetic_format_engineering",
        "statement": (
            "Native capability declaration for one bounded Metriplane-authored synthetic "
            "format-engineering source."
        ),
        "subject": "candidate_adapter",
    }
    assert record["adapter"]["implementation_commit"] == ADAPTER_COMMIT
    assert record["adapter"]["environment"]["runtime_version"] == "3.12"
    assert record["adapter"]["environment"]["dependency_lock_sha256"] == LOCK_SHA256
    assert record["source"]["artifacts"][0]["sha256"] == SOURCE_SHA256
    assert record["source"]["rights"]["source_bytes_in_fixture"] is False
    capabilities = record["capabilities"]
    assert capabilities["clock"]["authoritative"] is True
    assert capabilities["clock"]["order_only"] is False
    assert capabilities["completeness"]["synchronization_tolerance_ns"] == 0
    assert capabilities["completeness"]["carry_forward"]["method"] == "none"
    assert capabilities["anti_taint"]["used_as_incident_truth"] is False
    assert capabilities["deterministic_conversion"]["clean_run_count"] == 3
    assert capabilities["deterministic_conversion"]["equivalent"] is True
    portable = capabilities["portable_evaluation"]
    assert portable["status"] == "not_demonstrated"
    assert portable["source_dependencies_required"] is False
    assert portable["environments"] == [
        {"operating_system": os_name, "python_version": version, "status": "required"}
        for os_name in ("Ubuntu", "macOS")
        for version in ("3.12", "3.13")
    ]
    prohibited = " ".join(capabilities["semantics"]["prohibited"]).lower()
    assert "general ros 2" in prohibited
    assert "external-source compatibility evidence" in prohibited


def test_conversion_summary_binds_three_conversions_and_exact_source() -> None:
    summary = _read_json(FIXTURE_ROOT / "conversion-summary.json")
    assert summary["adapter_commit"] == ADAPTER_COMMIT
    assert summary["source_classification"] == SOURCE_CLASSIFICATION
    assert summary["source_size"] == SOURCE_SIZE
    assert summary["source_sha256"] == SOURCE_SHA256
    assert summary["config_sha256"] == CONFIG_SHA256
    assert summary["shared_session_sha256"] == SESSION_SHA256
    assert summary["capability_fingerprint_sha256"] == CAPABILITY_CANONICAL_SHA256
    assert summary["source_unchanged_during_conversion"] is True
    assert summary["conversion_reproducibility"] == {
        "comparison_policy": "sha256_byte_identity",
        "equivalent": True,
        "run_ids": ["clean-conversion-1", "clean-conversion-2", "clean-conversion-3"],
        "status": "demonstrated",
    }
    for variant, expected in EXPECTED_FINGERPRINTS.items():
        assert summary[variant]["fixture_fingerprint_sha256"] == expected


def _canonical_run_semantics(root: Path) -> dict[str, Any]:
    regressions = []
    for path in sorted((root / "regression_tests").glob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        value.pop("source_bundle", None)
        regressions.append(value)
    return {
        "state": _read_jsonl(root / "state_segment.jsonl"),
        "events": _read_jsonl(root / "physical_event_log.jsonl"),
        "deviations": _read_jsonl(root / "deviations.jsonl"),
        "incidents": _read_jsonl(root / "incidents.jsonl"),
        "regressions": regressions,
    }


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_three_runs_have_frozen_equivalent_semantics(
    variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = FIXTURE_ROOT / variant
    values = []
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "a" * 40)
    for index in range(3):
        output = tmp_path / f"{variant}-{index}"
        summary = run_external_fixture(fixture, output, run_id=f"ros2_mcap_{variant}")
        assert summary.passed is True, summary.errors
        assert (
            summary.frame_count,
            summary.event_count,
            summary.deviation_count,
            summary.incident_count,
        ) == EXPECTED_COUNTS[variant]
        events = _read_jsonl(output / "physical_event_log.jsonl")
        assert [item["event_type"] for item in events] == EXPECTED_EVENT_TYPES[variant]
        assert [item["frame_id"] for item in events] == EXPECTED_EVENT_FRAMES[variant]
        if variant == "incident":
            incidents = _read_jsonl(output / "incidents.jsonl")
            assert incidents[0]["incident_type"] == "missing_tool_caused_delay"
            assert incidents[0]["start_ts"] == 0.5
            assert incidents[0]["end_ts"] == 1.0
            assert verify_bundle(output / "evidence_bundles/INC-0001.zip")["pass"] is True
            assert run_regression(output / "regression_tests/INC-0001.yaml")["pass"] is True
        else:
            assert summary.evidence_bundles == []
            assert summary.generated_regressions == []
        values.append(_canonical_run_semantics(output))
    assert values[0] == values[1] == values[2]


_PRIVATE_PATH = re.compile(
    rb"(?:/(?:home|Users|workspace)/[^/\s\"'<>]+(?:/|(?=[\s\"'<>]|$))|"
    rb"(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/])"
)


def _assert_no_path_leak(root: Path, forbidden: list[str]) -> None:
    values = [item.encode() for item in forbidden]
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        assert all(item not in raw for item in values), path
        assert _PRIVATE_PATH.search(raw) is None, path
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    assert not info.filename.startswith(("/", "\\"))
                    assert ".." not in Path(info.filename).parts
                    assert _PRIVATE_PATH.search(info.filename.encode()) is None
                    if not info.is_dir():
                        member = archive.read(info)
                        assert all(item not in member for item in values)
                        assert _PRIVATE_PATH.search(member) is None


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_installed_fixture_output_is_movable_and_path_clean(
    variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "PRIVATE_FIXTURE_ROOT_SENTINEL"
    output_root = tmp_path / "PRIVATE_OUTPUT_ROOT_SENTINEL"
    moved_root = tmp_path / "moved"
    fixture = fixture_root / variant
    shutil.copytree(FIXTURE_ROOT / variant, fixture)
    monkeypatch.setenv("HOME", str(tmp_path / "PRIVATE_HOME_SENTINEL"))
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "b" * 40)
    summary = run_external_fixture(fixture, output_root, run_id=f"movable_{variant}")
    assert summary.passed is True
    shutil.rmtree(fixture_root)
    shutil.move(output_root, moved_root)
    assert export_usda(moved_root).is_file()
    if variant == "incident":
        assert verify_bundle(moved_root / "evidence_bundles/INC-0001.zip")["pass"] is True
        assert run_regression(moved_root / "regression_tests/INC-0001.yaml")["pass"] is True
    else:
        assert list((moved_root / "evidence_bundles").glob("*.zip")) == []
        assert list((moved_root / "regression_tests").glob("*.yaml")) == []
    _assert_no_path_leak(
        moved_root,
        [
            "PRIVATE_FIXTURE_ROOT_SENTINEL",
            "PRIVATE_OUTPUT_ROOT_SENTINEL",
            "PRIVATE_HOME_SENTINEL",
            str(REPOSITORY_ROOT.resolve()),
            str(tmp_path.resolve()),
        ],
    )


def test_fixture_inventory_excludes_source_runtime_and_machine_paths() -> None:
    prohibited_suffixes = {
        ".mcap",
        ".db3",
        ".bag",
        ".cdr",
        ".msg",
        ".idl",
        ".pyc",
        ".so",
        ".dylib",
    }
    assert not any(
        path.suffix.lower() in prohibited_suffixes
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file()
    )
    _assert_no_path_leak(
        FIXTURE_ROOT,
        ["/tmp/", "/workspace/", str(REPOSITORY_ROOT.resolve())],
    )


def test_frozen_git_lineage_and_subtrees_are_preserved() -> None:
    candidate = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/agent/met46-ros2-mcap-recorded-state-profile"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    candidate_revision = candidate.stdout.strip() if candidate.returncode == 0 else "HEAD"
    for commit in (STARTING_BASELINE, SDK_COMMIT, ADAPTER_COMMIT):
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_BASELINE, candidate_revision],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", SDK_COMMIT, candidate_revision],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", ADAPTER_COMMIT, candidate_revision],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    adapter_tree = subprocess.run(
        ["git", "rev-parse", f"{ADAPTER_COMMIT}:adapters/ros2_mcap"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert adapter_tree == ADAPTER_TREE
    sdk_tree = subprocess.run(
        ["git", "rev-parse", f"{SDK_COMMIT}:adapters/source_adapter_sdk"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert sdk_tree == SDK_TREE
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            SDK_COMMIT,
            candidate_revision,
            "--",
            "adapters/source_adapter_sdk",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            ADAPTER_COMMIT,
            candidate_revision,
            "--",
            "adapters/ros2_mcap",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def test_root_package_contract_and_source_neutrality_remain_frozen() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert (REPOSITORY_ROOT / "metriplane" / "__init__.py").read_text(
        encoding="utf-8"
    ).splitlines()[5] == '__version__ = "0.3.0"'
    assert project["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "metriplane*",
        "integrations*",
    ]
    dependencies = "\n".join(project["project"]["dependencies"]).lower()
    lock = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    prohibited = (
        "mcap",
        "mcap-ros2-support",
        "rosbags",
        "rclpy",
        "rosidl",
        "tf2",
        "metriplane-source-adapter-sdk",
        "metriplane-ros2-mcap-adapter",
    )
    assert all(item not in dependencies for item in prohibited)
    assert all(re.search(rf'(?m)^name = "{re.escape(item)}"$', lock) is None for item in prohibited)
    assert _sha256(CONTRACT_SCHEMA) == CONTRACT_SCHEMA_SHA256
    assert not any(
        "ros2_mcap" in path.as_posix() for path in (REPOSITORY_ROOT / "metriplane").rglob("*")
    )
