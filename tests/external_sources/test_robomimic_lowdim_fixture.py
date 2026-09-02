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
from metriplane.atlas.usd import export_usda
from metriplane.external_sources.contract import validate_external_fixture_bundle
from metriplane.external_sources.execution import run_external_fixture
from tests.external_sources.version_projection import materialize_current_version_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "external_sources" / "robomimic_lowdim"
CONTRACT_SCHEMA = REPOSITORY_ROOT / "schemas" / "metriplane.external_source_contract.v1.schema.json"
CONTRACT_SCHEMA_SHA256 = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
DATASET_REVISION = "74fa018461f479cd9fd15b924a16103012096203"
ADAPTER_COMMIT = "cfc285a3e757fdf742858b1c4cf685c384d01e8b"
CONFIG_SHA256 = "3cfa88b1512215d8545c1404bcc80e18bf780d1dfc899553ccc69c2517c623c5"
SESSION_SHA256 = "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246"
EXPECTED_FINGERPRINTS = {
    "incident": "6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6",
    "control": "dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf",
}
EXPECTED_COUNTS = {"incident": (118, 4, 1, 1), "control": (118, 3, 0, 0)}
EXPECTED_EVENT_TYPES = {
    "incident": [
        "required_asset_missing",
        "step_delayed",
        "required_asset_present",
        "step_completed",
    ],
    "control": ["required_asset_missing", "required_asset_present", "step_completed"],
}
EXPECTED_EVENT_FRAMES = {"incident": [0, 40, 42, 42], "control": [0, 42, 42]}
TARGET_POLYGON = [
    [0.103724912698951, -0.22150121318116284],
    [0.143724912698951, -0.22150121318116284],
    [0.143724912698951, -0.18150121318116286],
    [0.103724912698951, -0.18150121318116286],
]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(isinstance(value, dict) for value in values)
    return values


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pack(root: Path, name: str) -> dict[str, Any]:
    value = yaml.safe_load((root / "domain-pack" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _without_wait(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "<variant>" if key == "max_wait_s" else _without_wait(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_without_wait(child) for child in value]
    return value


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_contract_identity_rights_provenance_and_audit(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    manifest = fixture.manifest
    assert len(fixture.frames) == 118
    assert manifest.source_project.revision.value == DATASET_REVISION
    assert manifest.selection.episode_id == "demo_0"
    assert manifest.adapter.commit == ADAPTER_COMMIT
    assert manifest.adapter.parameters.sha256 == CONFIG_SHA256
    assert manifest.fixture.distribution == "derived_only"
    assert manifest.domain_pack.rule_origin == "operator_configured_rules"
    assert manifest.domain_pack.source_annotations_used is False
    assert manifest.evaluation.expected_outcome_is_input is False
    assert manifest.rights.fixture.license.identifier == "MIT"
    assert manifest.rights.fixture.redistribution_permission == "verified"

    raw_manifest = _read_json(root / "source-manifest.json")
    extension = raw_manifest["extensions"]["org.robomimic.can_ph"]
    audit = extension["real_source_audit"]
    assert audit["demo_count"] == 200
    assert audit["clock_rows_verified"] == 23_207
    assert audit["can_named_qpos_rows_verified"] == 23_207
    assert audit["selected_demo"] == "demo_0"
    assert audit["selected_frame_count"] == 118
    assert audit["mask_membership_equal"] is True
    assert audit["states_actions_model_sample_masks_equal"] is True
    assert audit["source_unchanged_during_conversion"] is True
    assert audit["max_fk_abs_error_m"] == 1.1102230246251565e-15
    assert audit["raw_environment_version"] == "1.5.0"
    assert audit["prepared_environment_version"] == "1.5.1"
    assert extension["code_identity_context"]["hosted_artifact_generation_commit_claimed"] is False
    assert _sha256(root / "CHECKSUMS.sha256") == EXPECTED_FINGERPRINTS[variant]
    assert _sha256(root / "session.jsonl") == SESSION_SHA256
    assert fixture.normalization_report.conversion_reproducibility.status == "demonstrated"
    assert fixture.normalization_report.conversion_reproducibility.equivalent is True
    assert len(fixture.normalization_report.conversion_reproducibility.runs) == 3

    artifacts = {item.artifact_id: item for item in manifest.source_artifacts}
    assert set(artifacts) == {"can_ph_raw_hdf5", "can_ph_prepared_lowdim_hdf5"}
    assert artifacts["can_ph_raw_hdf5"].sha256 == (
        "86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d"
    )
    assert artifacts["can_ph_prepared_lowdim_hdf5"].sha256 == (
        "3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962"
    )
    assert all(item.presence == "referenced" for item in artifacts.values())


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_complete_position_only_frames_and_authoritative_clock(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    rows = _read_jsonl(root / "session.jsonl")
    assert len(rows) == len(fixture.frames) == 118
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
        assert row["ts"] == row["ts_sim_ns"] / 1_000_000_000
        assert row["events"] == []
        assert [item["id"] for item in row["objects"]] == ["can_1", "robot_tcp_1"]
        assert all(set(item) == {"id", "pos_world", "zone"} for item in row["objects"])
        assert all(item["pos_world"][2] == 0.0 for item in row["objects"])
    assert rows[0]["objects"][0]["pos_world"] == [
        0.123724912698951,
        -0.20150121318116285,
        0.0,
    ]
    assert rows[-1]["objects"][0]["pos_world"] == [
        0.20088983080739384,
        0.34891713691853893,
        0.0,
    ]
    assert [
        row["frame_id"] for row in rows if row["objects"][0]["zone"] == "target_xy_region"
    ] == list(range(64))
    assert [
        row["frame_id"] for row in rows if row["objects"][1]["zone"] == "target_xy_region"
    ] == list(range(42, 65))

    normalization = fixture.manifest.normalization
    assert normalization.clock.fixed_step_ns == 50_000_000
    assert normalization.clock.source_unit == "seconds"
    assert normalization.coordinates.source_frame == "robosuite_world"
    assert normalization.coordinates.source_units == "meters"
    assert normalization.coordinates.projection.dropped_axes == ["z"]
    assert normalization.completeness.carry_forward.method == "none"
    assert normalization.temporal_alignment.interpolation.method == "none"
    assert normalization.temporal_alignment.resampling.method == "none"


def test_incident_and_control_share_state_mapping_geometry_and_assets() -> None:
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
    workspace = _load_pack(incident, "workspace.yaml")
    assert workspace["units"] == "meters"
    assert workspace["zones"][0]["polygon"] == TARGET_POLYGON
    assets = {item["asset_id"]: item for item in _load_pack(incident, "assets.yaml")["assets"]}
    assert assets["can_1"]["asset_type"] == "material"
    assert assets["robot_tcp_1"]["asset_type"] == "tool"
    incident_process = _load_pack(incident, "process.yaml")
    control_process = _load_pack(control, "process.yaml")
    incident_contracts = _load_pack(incident, "contracts.yaml")
    control_contracts = _load_pack(control, "contracts.yaml")
    assert _without_wait(incident_process) == _without_wait(control_process)
    assert _without_wait(incident_contracts) == _without_wait(control_contracts)
    assert incident_process["steps"][0]["max_wait_s"] == 2.0
    assert control_process["steps"][0]["max_wait_s"] == 2.5


def _canonical_semantics(root: Path) -> dict[str, Any]:
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
    fixture = materialize_current_version_fixture(
        FIXTURE_ROOT / variant,
        tmp_path / f"{variant}-candidate-fixture",
    )
    canonical = []
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "a" * 40)
    for index in range(3):
        output = tmp_path / f"{variant}-{index}"
        summary = run_external_fixture(fixture, output, run_id=f"robomimic_{variant}")
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
            assert incidents[0]["start_ts"] == 0.0
            assert incidents[0]["end_ts"] == 2.0
            assert verify_bundle(output / "evidence_bundles/INC-0001.zip")["pass"] is True
            assert run_regression(output / "regression_tests/INC-0001.yaml")["pass"] is True
        else:
            assert summary.evidence_bundles == []
            assert summary.generated_regressions == []
            assert list((output / "evidence_bundles").glob("*.zip")) == []
            assert list((output / "regression_tests").glob("*.yaml")) == []
        canonical.append(_canonical_semantics(output))
    assert canonical[0] == canonical[1] == canonical[2]


_PRIVATE_PATH = re.compile(
    rb"(?:/(?:home|Users)/[^/\s\"'<>]+(?:/|(?=[\s\"'<>]|$))|"
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
                    member = info.filename.encode()
                    assert _PRIVATE_PATH.search(member) is None
                    assert not info.filename.startswith(("/", "\\"))
                    assert ".." not in Path(info.filename).parts
                    if not info.is_dir():
                        body = archive.read(info)
                        assert all(item not in body for item in values)
                        assert _PRIVATE_PATH.search(body) is None


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_runs_are_movable_and_path_clean(
    variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "PRIVATE_FIXTURE_ROOT_SENTINEL"
    output_root = tmp_path / "PRIVATE_OUTPUT_ROOT_SENTINEL"
    moved_root = tmp_path / "moved"
    fixture = fixture_root / variant
    materialize_current_version_fixture(FIXTURE_ROOT / variant, fixture)
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


def test_fixture_inventory_has_no_source_payload_or_local_path() -> None:
    prohibited = {".hdf5", ".h5", ".png", ".mp4", ".xml", ".zip", ".pt", ".urdf"}
    _assert_no_path_leak(FIXTURE_ROOT, ["/tmp/", "/workspace/", str(REPOSITORY_ROOT.resolve())])
    assert not any(
        path.suffix.lower() in prohibited for path in FIXTURE_ROOT.rglob("*") if path.is_file()
    )


def test_root_package_boundary_and_frozen_contract() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "metriplane.__version__"}
    assert (REPOSITORY_ROOT / "metriplane" / "__init__.py").read_text(
        encoding="utf-8"
    ).splitlines()[5] == '__version__ = "0.4.0"'
    dependencies = "\n".join(project["project"]["dependencies"]).lower()
    lock = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    prohibited = (
        "robomimic",
        "robosuite",
        "mujoco",
        "torch",
        "h5py",
        "huggingface-hub",
    )
    assert all(item not in dependencies for item in prohibited)
    assert all(re.search(rf'(?m)^name = "{re.escape(item)}"$', lock) is None for item in prohibited)
    assert project["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "metriplane*",
        "integrations*",
    ]
    assert _sha256(CONTRACT_SCHEMA) == CONTRACT_SCHEMA_SHA256
    assert not any(
        "robomimic_lowdim" in path.as_posix()
        for path in (REPOSITORY_ROOT / "metriplane").rglob("*")
    )
