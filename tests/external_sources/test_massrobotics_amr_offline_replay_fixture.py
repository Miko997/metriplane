# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.external_sources.contract import validate_external_fixture_bundle
from metriplane.external_sources.execution import run_external_fixture
from tests.external_sources.version_projection import materialize_current_version_fixture

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "external_sources" / "massrobotics_amr"
EXPECTED = {
    "incident": {
        "counts": (9, 4, 1, 1),
        "events": [
            (2.0, "required_asset_missing"),
            (5.0, "step_delayed"),
            (6.0, "required_asset_present"),
            (6.0, "step_completed"),
        ],
    },
    "control": {
        "counts": (9, 3, 0, 0),
        "events": [
            (2.0, "required_asset_missing"),
            (4.0, "required_asset_present"),
            (4.0, "step_completed"),
        ],
    },
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert all(isinstance(value, dict) for value in values)
    return values


def _assert_private_path_free_archive(path: Path) -> None:
    needles = (b"/workspace/", b"/tmp/", b"/home/", b"C:\\Users\\", b"@gmail.com")
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            member = PurePosixPath(name)
            assert not member.is_absolute()
            assert ".." not in member.parts
            assert "\\" not in name
            data = archive.read(name)
            assert not any(needle in data for needle in needles)


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_public_fixture_validates_as_external_source_contract_v1(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    fixture = validate_external_fixture_bundle(root)
    assert len(fixture.frames) == 9
    assert fixture.manifest.fixture.fixture_id == f"massrobotics_amr_synthetic_{variant}_v1"
    assert fixture.manifest.evaluation.expected_outcome_is_input is False
    assert fixture.manifest.normalization.authoritative_object_collection == "objects"
    assert fixture.manifest.normalization.completeness.frame_semantics == "complete_snapshot"
    assert fixture.manifest.normalization.completeness.carry_forward.method == "none"
    assert fixture.manifest.normalization.temporal_alignment.interpolation.method == "none"
    assert fixture.manifest.normalization.temporal_alignment.resampling.method == "none"


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_public_session_has_exact_complete_snapshots_and_clock(variant: str) -> None:
    rows = _jsonl(FIXTURE_ROOT / variant / "session.jsonl")
    assert len(rows) == 9
    for index, row in enumerate(rows):
        assert row["schema_version"] == "1.0"
        assert row["frame_id"] == index
        assert row["ts_sim_ns"] == index * 1_000_000_000
        assert row["ts"] == float(index)
        assert row["events"] == []
        assert len(row["objects"]) == 2
        assert [item["id"] for item in row["objects"]] == [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ]
        assert all(set(item) == {"id", "pos_world", "zone"} for item in row["objects"])


def test_frozen_upstream_register_is_reference_only_and_contains_no_upstream_bytes() -> None:
    register = _json(FIXTURE_ROOT / "source-reference-register.json")
    assert register["snapshot_commit"] == "f9357a423ecabc3f7112e6d10025a5231943ec50"
    assert register["formal_release"]["version"] == "1.0"
    assert register["formal_release"]["short_commit"] == "7161a0d"
    assert register["rights_decision"] == "reference_only"
    assert register["upstream_artifacts_included"] is False
    assert {item["repository_path"]: item["git_blob"] for item in register["artifacts"]} == {
        "AMR_Interop_Standard.json": "7ba8974ae46d81ea0f6f8ed0ac7899d9d279af98",
        "AMR_Interop_Standard.pdf": "2436fee76da3a7b15516b518d85d237724925f90",
        "README.md": "4031260c9036672a6cd85b93111862b5daa568c3",
        "examples/identityReport1.json": "112ac8d1df62170f785dadf03419968c7e8b61df",
        "examples/statusReport1.json": "b396acbf743c2ffcd448dd675dc830b77384b054",
    }
    assert all(item["included"] is False for item in register["artifacts"])
    prohibited_names = {
        "AMR_Interop_Standard.json",
        "AMR_Interop_Standard.pdf",
        "identityReport1.json",
        "statusReport1.json",
    }
    assert not any(
        path.name in prohibited_names for path in FIXTURE_ROOT.rglob("*") if path.is_file()
    )


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_source_origin_rights_and_prediction_boundary_are_explicit(variant: str) -> None:
    root = FIXTURE_ROOT / variant
    manifest = _json(root / "source-manifest.json")
    text = json.dumps(manifest, sort_keys=True)
    assert "Metriplane-authored synthetic MassRobotics-format engineering fixture" in text
    assert "synthetic_format_engineering" in text
    assert "reference_only" in text
    assert "operator_configured_fixture_binding" in text
    assert "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in text
    assert "prediction" in text.lower()
    expected = _json(root / "expected-outcome.json")
    assert expected["atlas_input"] is False
    assert expected["role"] == "test_metadata_only"


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_public_fixture_has_no_machine_path_or_privacy_leak(variant: str) -> None:
    values: list[str] = []
    for path in (FIXTURE_ROOT / variant).rglob("*"):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        if path.suffix == ".zip":
            _assert_private_path_free_archive(path)
            continue
        try:
            values.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    text = "\n".join(values)
    for prohibited in ("/workspace/", "/tmp/", "/home/", "C:\\Users\\", "@gmail.com"):
        assert prohibited not in text


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_public_fixture_exact_atlas_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", "b" * 40)
    fixture = materialize_current_version_fixture(
        FIXTURE_ROOT / variant,
        tmp_path / f"{variant}-candidate-fixture",
    )
    output = tmp_path / f"{variant}-run"
    summary = run_external_fixture(
        fixture,
        output,
        run_id=f"massrobotics_amr_{variant}",
    )
    assert summary.passed is True
    assert (
        summary.frame_count,
        summary.event_count,
        summary.deviation_count,
        summary.incident_count,
    ) == EXPECTED[variant]["counts"]
    events = _jsonl(output / "physical_event_log.jsonl")
    assert [(item["ts"], item["event_type"]) for item in events] == EXPECTED[variant]["events"]
    if variant == "incident":
        assert _jsonl(output / "incidents.jsonl")[0]["incident_type"] == (
            "missing_tool_caused_delay"
        )
        bundle = output / "evidence_bundles" / "INC-0001.zip"
        regression = output / "regression_tests" / "INC-0001.yaml"
        assert verify_bundle(bundle)["pass"] is True
        assert run_regression(regression)["pass"] is True
        _assert_private_path_free_archive(bundle)
    else:
        assert summary.evidence_bundles == []
        assert summary.generated_regressions == []
        assert not (output / "evidence_bundles").exists()
        assert not (output / "regression_tests").exists()


def test_ordinary_wheel_configuration_excludes_adapter_and_upstream_runtime() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "metriplane*",
        "integrations*",
    ]
    dependencies = "\n".join(project["project"]["dependencies"]).lower()
    lock = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8").lower()
    prohibited = (
        "metriplane-massrobotics-amr-adapter",
        "metriplane-source-adapter-sdk",
        "massrobotics",
    )
    assert all(item not in dependencies for item in prohibited)
    assert all(re.search(rf'(?m)^name = "{re.escape(item)}"$', lock) is None for item in prohibited)
    assert not any(
        "massrobotics_amr_adapter" in path.as_posix()
        for path in (REPOSITORY_ROOT / "metriplane").rglob("*")
    )


def test_public_records_keep_the_synthetic_source_classification() -> None:
    summary = _json(FIXTURE_ROOT / "conversion-summary.json")
    expected_classification = "synthetic_format_engineering"
    assert summary["source_classification"] == "synthetic_format_engineering"
    for variant in ("incident", "control"):
        capability = _json(FIXTURE_ROOT / f"{variant}-capability-record.json")
        assert capability["record"]["classification"] == "native"
        assert capability["record"]["evidence_classification"] == expected_classification
        assert "external_source" not in capability["record"]["evidence_classification"]
