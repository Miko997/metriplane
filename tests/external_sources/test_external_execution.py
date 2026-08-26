# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from metriplane import __version__
from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.models import ATLAS_LIMITATION_STATEMENTS
from metriplane.atlas.regression import run_regression
from metriplane.cli import main as metriplane_main
from metriplane.external_sources import execution as external_execution
from metriplane.external_sources.contract import (
    CONTRACT_PROFILE,
    CONTRACT_SCHEMA_VERSION,
    ExternalSourceManifestV1,
    conversion_inputs_sha256,
)
from metriplane.external_sources.execution import (
    EXTERNAL_PROVENANCE_SCHEMA_VERSION,
    RUN_SUMMARY_SCHEMA_VERSION,
    VALIDATION_SUMMARY_SCHEMA_VERSION,
    run_external_fixture,
    validate_external_fixture,
)
from metriplane.provenance.run_provenance import GitInfo

REPOSITORY_ROOT = Path(__file__).parents[2]
VALID_BUNDLE = REPOSITORY_ROOT / "examples" / "external_sources" / "minimal"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_session(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_session(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_checksums(root: Path) -> None:
    checksum_path = root / "CHECKSUMS.sha256"
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path != checksum_path),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    checksum_path.write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in paths),
        encoding="utf-8",
    )


def _snapshot_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(VALID_BUNDLE, root)
    return root


def _rewrite_session_contract(root: Path, rows: list[dict[str, Any]]) -> None:
    manifest_path = root / "source-manifest.json"
    report_path = root / "normalization-report.json"
    session_path = root / "session.jsonl"
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)

    _write_session(session_path, rows)
    session_sha256 = _sha256(session_path)
    session_reference = manifest["normalized_artifacts"]["session"]
    session_reference["sha256"] = session_sha256
    for conversion_run in report["conversion_reproducibility"]["runs"]:
        conversion_run["artifacts"][session_reference["path"]] = session_sha256

    _write_json(report_path, report)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(root)


def _rewrite_mapping_contract(root: Path, mapping: dict[str, Any]) -> None:
    manifest_path = root / "source-manifest.json"
    mapping_path = root / "entity-mapping.json"
    report_path = root / "normalization-report.json"
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)

    _write_json(mapping_path, mapping)
    mapping_sha256 = _sha256(mapping_path)
    mapping_reference = manifest["normalization"]["entity_mapping"]
    mapping_reference["sha256"] = mapping_sha256
    for declaration in manifest["normalization"]["field_provenance"]:
        for reference in declaration.get("parameter_references", []):
            if reference["path"] == mapping_reference["path"]:
                reference["sha256"] = mapping_sha256
    for conversion_run in report["conversion_reproducibility"]["runs"]:
        conversion_run["artifacts"][mapping_reference["path"]] = mapping_sha256

    _write_json(report_path, report)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(root)


def _rewrite_fixture_id(root: Path, fixture_id: str) -> None:
    manifest_path = root / "source-manifest.json"
    report_path = root / "normalization-report.json"
    expected_path = root / "expected-outcome.json"
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    expected = _read_json(expected_path)

    manifest["fixture"]["fixture_id"] = fixture_id
    report["fixture_id"] = fixture_id
    expected["fixture_id"] = fixture_id
    _write_json(report_path, report)
    _write_json(expected_path, expected)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    manifest["normalized_artifacts"]["expected_outcome"]["sha256"] = _sha256(expected_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(root)


def _canonical_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _canonical_run_semantics(run_dir: Path) -> dict[str, Any]:
    regression_path = run_dir / "regression_tests" / "INC-0001.yaml"
    regression = yaml.safe_load(regression_path.read_text(encoding="utf-8"))
    assert isinstance(regression, dict)
    regression.pop("source_bundle", None)
    bundle_path = run_dir / "evidence_bundles" / "INC-0001.zip"
    return {
        "state": _canonical_jsonl(run_dir / "state_segment.jsonl"),
        "events": _canonical_jsonl(run_dir / "physical_event_log.jsonl"),
        "deviations": _canonical_jsonl(run_dir / "deviations.jsonl"),
        "incidents": _canonical_jsonl(run_dir / "incidents.jsonl"),
        "regression_expectations": regression,
        "evidence_verified": verify_bundle(bundle_path)["pass"],
        "regression_result": run_regression(regression_path)["pass"],
    }


def test_validation_summary_exposes_stable_contract_and_input_identity() -> None:
    summary = validate_external_fixture(VALID_BUNDLE)

    assert summary.schema_version == VALIDATION_SUMMARY_SCHEMA_VERSION
    assert summary.passed is True
    assert summary.fixture_id == "synthetic-inspection-bench-v1"
    assert summary.contract_schema_version == CONTRACT_SCHEMA_VERSION
    assert summary.contract_profile == CONTRACT_PROFILE
    assert summary.manifest_sha256 == _sha256(VALID_BUNDLE / "source-manifest.json")
    assert summary.session_sha256 == _sha256(VALID_BUNDLE / "session.jsonl")
    assert set(summary.domain_pack_file_hashes) == {
        "assets",
        "workspace",
        "process",
        "contracts",
        "work_orders",
    }
    assert summary.entity_mapping_sha256 == _sha256(VALID_BUNDLE / "entity-mapping.json")
    assert summary.normalization_report_sha256 == _sha256(
        VALID_BUNDLE / "normalization-report.json"
    )
    assert [source.artifact_id for source in summary.source_identities] == [
        "trajectory",
        "metadata",
    ]
    assert summary.source_revision is not None
    assert summary.source_revision.kind == "git_commit"
    assert summary.adapter_identity is not None
    assert summary.adapter_identity.adapter_id == ("org.metriplane.synthetic_fixture_adapter")
    assert summary.metriplane_version == __version__
    assert summary.declared_metriplane_version == __version__
    assert summary.frame_state_model_version == "1.0"
    assert summary.frame_count == 4
    assert summary.normalized_object_count == 2
    assert summary.source_entity_count == 2
    assert summary.first_authoritative_timestamp == 0.0
    assert summary.last_authoritative_timestamp == 4.0
    assert {check.check_id for check in summary.checks} == {
        "manifest_contract",
        "local_bundle_integrity",
        "normalized_session",
        "domain_pack",
        "cross_artifact_agreement",
        "evaluation_runtime_version",
    }
    assert all(check.passed for check in summary.checks)
    assert summary.errors == []
    assert summary.limitations


def test_root_cli_json_validation_stdout_is_one_clean_document(capsys: Any) -> None:
    exit_code = metriplane_main(["external", "validate", str(VALID_BUNDLE), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["schema_version"] == VALIDATION_SUMMARY_SCHEMA_VERSION
    assert payload["pass"] is True
    assert payload["fixture_id"] == "synthetic-inspection-bench-v1"
    assert "PASS" not in captured.out


def test_root_cli_json_validation_failure_is_one_clean_document(
    tmp_path: Path,
    capsys: Any,
) -> None:
    fixture = _copy_fixture(tmp_path)
    (fixture / "source-manifest.json").write_text("{\n", encoding="utf-8")
    _rewrite_checksums(fixture)

    exit_code = metriplane_main(["external", "validate", str(fixture), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert payload["schema_version"] == VALIDATION_SUMMARY_SCHEMA_VERSION
    assert payload["pass"] is False
    assert payload["errors"]
    assert "Traceback" not in captured.out


def test_root_cli_json_run_stdout_is_one_clean_document(
    tmp_path: Path,
    capsys: Any,
) -> None:
    exit_code = metriplane_main(
        [
            "external",
            "run",
            str(VALID_BUNDLE),
            "--out",
            str(tmp_path / "cli-run"),
            "--run-id",
            "external_cli_json",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["schema_version"] == RUN_SUMMARY_SCHEMA_VERSION
    assert payload["pass"] is True
    assert (
        payload["frame_count"],
        payload["event_count"],
        payload["deviation_count"],
        payload["incident_count"],
    ) == (4, 5, 1, 1)
    assert "PASS" not in captured.out


def test_external_run_completes_existing_atlas_workflow_and_preserves_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_commit = "a" * 40
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", runtime_commit)
    fixture = _copy_fixture(tmp_path)
    before = _snapshot_files(fixture)
    out = tmp_path / "external-run"

    summary = run_external_fixture(
        fixture,
        out,
        run_id="external_execution_positive",
    )

    assert summary.schema_version == RUN_SUMMARY_SCHEMA_VERSION
    assert summary.passed is True
    assert summary.validation.passed is True
    assert summary.fixture_id == "synthetic-inspection-bench-v1"
    assert summary.run_id == "external_execution_positive"
    assert (
        summary.frame_count,
        summary.event_count,
        summary.deviation_count,
        summary.incident_count,
    ) == (4, 5, 1, 1)
    assert summary.report_path is not None
    assert Path(summary.report_path).is_file()
    assert len(summary.evidence_bundles) == 1
    assert summary.evidence_bundles[0].verified is True
    assert len(summary.generated_regressions) == 1
    assert summary.generated_regressions[0].passed is True
    assert summary.provenance is not None
    provenance_path = Path(summary.provenance.path)
    assert provenance_path.is_file()
    assert _sha256(provenance_path) == summary.provenance.sha256
    provenance = _read_json(provenance_path)
    assert provenance["schema_version"] == EXTERNAL_PROVENANCE_SCHEMA_VERSION
    assert provenance["fixture_id"] == "synthetic-inspection-bench-v1"
    assert provenance["evaluation"]["run_id"] == "external_execution_positive"
    assert provenance["evaluation"]["command"] == [
        "metriplane",
        "external",
        "run",
        "<fixture>",
        "--out",
        "<output>",
        "--run-id",
        "external_execution_positive",
    ]
    assert provenance["evaluation"]["actual_metriplane_git_commit"] == runtime_commit
    assert provenance["evaluation"]["actual_metriplane_git_dirty"] is None
    assert provenance["evaluation"]["actual_metriplane_git_describe"] is None
    provenance_strings = _string_values(provenance)
    assert str(fixture.resolve()) not in provenance_strings
    assert str(out.resolve()) not in provenance_strings
    assert str(REPOSITORY_ROOT.resolve()) not in provenance_strings
    assert "repo_root" not in json.dumps(provenance, sort_keys=True)

    atlas_manifest = _read_json(out / "atlas_manifest.json")
    assert atlas_manifest["external_source_provenance"]["sha256"] == (summary.provenance.sha256)
    report = (out / "cell_truth_report.md").read_text(encoding="utf-8")
    assert "## External fixture provenance" in report
    for statement in ATLAS_LIMITATION_STATEMENTS:
        assert statement in report
    assert "replayed calibrated" not in report
    assert "tracked or tagged" not in report
    with zipfile.ZipFile(out / "evidence_bundles" / "INC-0001.zip") as archive:
        assert "provenance/external_source_provenance.json" in archive.namelist()
        bundled_provenance = json.loads(archive.read("provenance/external_source_provenance.json"))
    assert bundled_provenance["fixture_id"] == "synthetic-inspection-bench-v1"
    assert bundled_provenance == provenance
    assert bundled_provenance["evaluation"]["command"] == provenance["evaluation"]["command"]
    assert bundled_provenance["evaluation"]["actual_metriplane_git_commit"] == runtime_commit
    bundled_provenance_strings = _string_values(bundled_provenance)
    assert str(fixture.resolve()) not in bundled_provenance_strings
    assert str(out.resolve()) not in bundled_provenance_strings
    assert str(REPOSITORY_ROOT.resolve()) not in bundled_provenance_strings
    assert "repo_root" not in json.dumps(bundled_provenance, sort_keys=True)
    assert _snapshot_files(fixture) == before


def test_external_provenance_handles_unavailable_git_identity_honestly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _copy_fixture(tmp_path)
    output = tmp_path / "external-run-without-git"
    machine_local_repo_root = str(tmp_path / "machine-local-repository")
    monkeypatch.setattr(
        external_execution,
        "get_git_info",
        lambda **_kwargs: GitInfo(
            commit=None,
            dirty=None,
            describe=None,
            repo_root=machine_local_repo_root,
        ),
    )

    summary = run_external_fixture(
        fixture,
        output,
        run_id="external_execution_without_git",
        overwrite=True,
    )

    assert summary.passed is True
    assert summary.provenance is not None
    provenance_text = Path(summary.provenance.path).read_text(encoding="utf-8")
    provenance = json.loads(provenance_text)
    evaluation = provenance["evaluation"]
    assert evaluation["actual_metriplane_git_commit"] is None
    assert evaluation["actual_metriplane_git_dirty"] is None
    assert evaluation["actual_metriplane_git_describe"] is None
    assert machine_local_repo_root not in provenance_text
    assert "repo_root" not in provenance_text


def test_external_provenance_command_records_overwrite_without_local_paths(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(tmp_path)
    output = tmp_path / "external-overwrite-run"

    summary = run_external_fixture(
        fixture,
        output,
        run_id="external_execution_overwrite",
        overwrite=True,
    )

    assert summary.passed is True
    assert summary.provenance is not None
    provenance = _read_json(Path(summary.provenance.path))
    assert provenance["evaluation"]["command"] == [
        "metriplane",
        "external",
        "run",
        "<fixture>",
        "--out",
        "<output>",
        "--run-id",
        "external_execution_overwrite",
        "--overwrite",
    ]


def test_three_external_runs_have_equivalent_canonical_semantics(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    canonical: list[dict[str, Any]] = []

    for index in range(3):
        out = tmp_path / f"run-{index}"
        summary = run_external_fixture(
            fixture,
            out,
            run_id="external_three_run_equivalence",
        )
        assert summary.passed is True
        assert all(bundle.verified for bundle in summary.evidence_bundles)
        assert all(regression.passed for regression in summary.generated_regressions)
        canonical.append(_canonical_run_semantics(out))

    assert canonical[0] == canonical[1] == canonical[2]
    assert canonical[0]["evidence_verified"] is True
    assert canonical[0]["regression_result"] is True


@pytest.mark.parametrize("relationship", ["equal", "child", "ancestor"])
def test_external_run_rejects_every_fixture_output_overlap(
    tmp_path: Path,
    relationship: str,
) -> None:
    fixture = _copy_fixture(tmp_path)
    before = _snapshot_files(fixture)
    output = {
        "equal": fixture,
        "child": fixture / "generated-run",
        "ancestor": fixture.parent,
    }[relationship]

    summary = run_external_fixture(
        fixture,
        output,
        run_id=f"overlap_{relationship}",
        overwrite=True,
    )

    assert summary.passed is False
    assert any("must not equal, contain, or be contained" in error for error in summary.errors)
    assert _snapshot_files(fixture) == before


def test_external_run_preserves_existing_output_without_overwrite(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    output = tmp_path / "existing-output"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("do not replace", encoding="utf-8")

    summary = run_external_fixture(fixture, output, run_id="no_overwrite")

    assert summary.passed is False
    assert any("without --overwrite" in error for error in summary.errors)
    assert sentinel.read_text(encoding="utf-8") == "do not replace"


def test_untrusted_fixture_id_is_preserved_but_never_used_as_raw_run_id_or_terminal(
    tmp_path: Path,
    capsys: Any,
) -> None:
    fixture = _copy_fixture(tmp_path)
    unsafe_fixture_id = "fixture\n\x1b[31m/path"
    _rewrite_fixture_id(fixture, unsafe_fixture_id)

    exit_code = metriplane_main(["external", "validate", str(fixture)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "\x1b" not in captured.out
    assert "fixture\\n\\u001b[31m/path" in captured.out

    output = tmp_path / "safe-operational-run"
    summary = run_external_fixture(fixture, output)

    assert summary.passed is True
    assert summary.fixture_id == unsafe_fixture_id
    assert summary.run_id is not None
    assert "\n" not in summary.run_id
    assert "\x1b" not in summary.run_id
    assert "/" not in summary.run_id
    assert len(summary.run_id) <= 128
    assert summary.provenance is not None
    provenance = _read_json(Path(summary.provenance.path))
    assert provenance["fixture_id"] == unsafe_fixture_id
    report = (output / "cell_truth_report.md").read_text(encoding="utf-8")
    assert "\x1b" not in report
    assert "\\u001b" in report


def test_external_run_rejects_unsafe_explicit_run_id_before_execution(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(tmp_path)
    output = tmp_path / "must-not-exist"

    summary = run_external_fixture(fixture, output, run_id="unsafe\nrun")

    assert summary.passed is False
    assert any("--run-id must be 1-128 ASCII" in error for error in summary.errors)
    assert not output.exists()


def test_external_run_returns_typed_failure_for_output_symlink_loop(
    tmp_path: Path,
) -> None:
    fixture = _copy_fixture(tmp_path)
    output = tmp_path / "output-loop"
    try:
        output.symlink_to(output.name)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable on this platform")

    summary = run_external_fixture(fixture, output, run_id="output_symlink_loop")

    assert summary.passed is False
    assert any("cannot resolve external run output path" in error for error in summary.errors)
    assert output.is_symlink()


def test_preflight_failure_never_invokes_atlas_or_creates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    called = False

    def _unexpected_atlas(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("Atlas must not run after failed external preflight")

    monkeypatch.setattr(external_execution, "run_atlas", _unexpected_atlas)
    output = tmp_path / "must-not-exist"

    summary = run_external_fixture(fixture, output)

    assert summary.passed is False
    assert called is False
    assert not output.exists()


def test_manifest_checksum_mismatch_is_actionable(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("checksum mismatch for source-manifest.json" in error for error in summary.errors)


def test_session_declared_hash_mismatch_is_actionable(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    session_path = fixture / "session.jsonl"
    session_path.write_text(
        session_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("normalized session sha256 mismatch" in error for error in summary.errors)


def test_domain_pack_declared_hash_mismatch_is_actionable(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    process_path = fixture / "domain-pack" / "process.yaml"
    process_path.write_text(
        process_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("domain-pack process sha256 mismatch" in error for error in summary.errors)


def test_manifest_and_session_semantics_must_agree(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    rows = _read_session(fixture / "session.jsonl")
    rows[0]["source_backend"] = "different_normalized_source"
    _rewrite_session_contract(fixture, rows)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any(
        "source_backend 'different_normalized_source' does not match manifest value" in error
        for error in summary.errors
    )


def test_manifest_and_domain_pack_semantics_must_agree(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    workspace_path = fixture / "domain-pack" / "workspace.yaml"
    manifest_path = fixture / "source-manifest.json"
    workspace = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    assert isinstance(workspace, dict)
    workspace["units"] = "millimeters"
    workspace_path.write_text(
        yaml.safe_dump(workspace, sort_keys=False),
        encoding="utf-8",
    )

    manifest = _read_json(manifest_path)
    old_sha256 = manifest["domain_pack"]["workspace"]["sha256"]
    new_sha256 = _sha256(workspace_path)

    def _replace_workspace_hash(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "sha256" and item == old_sha256:
                    value[key] = new_sha256
                else:
                    _replace_workspace_hash(item)
        elif isinstance(value, list):
            for item in value:
                _replace_workspace_hash(item)

    _replace_workspace_hash(manifest)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any(
        "coordinate target_units must match domain-pack workspace units" in error
        for error in summary.errors
    )


def test_entity_mapping_cross_artifact_mismatch_is_actionable(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    mapping = _read_json(fixture / "entity-mapping.json")
    mapping["mappings"][0]["atlas_asset_id"] = "missing_asset"
    _rewrite_mapping_contract(fixture, mapping)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("unknown Atlas asset: missing_asset" in error for error in summary.errors)


def test_undeclared_transform_fails_canonical_preflight(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    manifest = _read_json(manifest_path)
    del manifest["normalization"]["coordinates"]["transform"]
    _write_json(manifest_path, manifest)
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("normalization.coordinates.transform" in error for error in summary.errors)


def test_malformed_bundle_fails_without_execution(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    manifest_path.write_text("{\n", encoding="utf-8")
    _rewrite_checksums(fixture)

    summary = run_external_fixture(fixture, tmp_path / "must-not-exist")

    assert summary.passed is False
    assert any("invalid external source manifest" in error for error in summary.errors)
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("time_regression", "evaluation time must be strictly monotonic"),
        ("duplicate_ids", "duplicate object ids"),
        ("unknown_required_state", "unknown position or zone"),
        (
            "prohibited_source_label",
            "prohibited source incident/annotation fields: incident_id",
        ),
    ],
)
def test_session_semantic_failures_are_actionable(
    tmp_path: Path,
    case: str,
    expected_error: str,
) -> None:
    fixture = _copy_fixture(tmp_path)
    rows = _read_session(fixture / "session.jsonl")
    if case == "time_regression":
        rows[2]["ts"] = 0.5
    elif case == "duplicate_ids":
        rows[0]["objects"][1]["id"] = rows[0]["objects"][0]["id"]
    elif case == "unknown_required_state":
        rows[0]["objects"][0]["zone"] = None
    else:
        rows[0]["incident_id"] = "SOURCE-INCIDENT-1"
    _rewrite_session_contract(fixture, rows)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any(expected_error in error for error in summary.errors)


def test_unsafe_bundle_symlink_is_rejected(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    link = fixture / "untrusted-link.json"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable on this platform")

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any("symlink" in error for error in summary.errors)


def test_missing_required_local_file_is_actionable(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    (fixture / "session.jsonl").unlink()

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert any(
        "checksum references missing file: session.jsonl" in error for error in summary.errors
    )


def test_referenced_remote_source_may_remain_absent_locally(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    report_path = fixture / "normalization-report.json"
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    artifact = manifest["source_artifacts"][0]
    source_path = fixture / artifact.pop("path")
    artifact["presence"] = "referenced"
    source_path.unlink()

    parsed = ExternalSourceManifestV1.model_validate(manifest)
    report["conversion_reproducibility"]["input_fingerprint_sha256"] = conversion_inputs_sha256(
        parsed
    )
    _write_json(report_path, report)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is True
    trajectory = next(
        source for source in summary.source_identities if source.artifact_id == "trajectory"
    )
    assert trajectory.presence == "referenced"
    assert trajectory.path is None
    assert trajectory.uri is not None


def test_expected_outcome_predictions_never_control_runtime_truth(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    expected_path = fixture / "expected-outcome.json"
    manifest_path = fixture / "source-manifest.json"
    expected = _read_json(expected_path)
    expected.update(
        {
            "event_count": 0,
            "event_types": [],
            "deviation_count": 99,
            "incident_count": 0,
            "incident_types": [],
            "evidence_bundle_verified": False,
            "regression_passed": False,
        }
    )
    _write_json(expected_path, expected)
    manifest = _read_json(manifest_path)
    manifest["normalized_artifacts"]["expected_outcome"]["sha256"] = _sha256(expected_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(fixture)

    summary = run_external_fixture(
        fixture,
        tmp_path / "actual-run",
        run_id="expected_outcome_is_not_truth",
    )

    assert summary.passed is True
    assert (
        summary.frame_count,
        summary.event_count,
        summary.deviation_count,
        summary.incident_count,
    ) == (4, 5, 1, 1)
    assert summary.evidence_bundles[0].verified is True
    assert summary.generated_regressions[0].passed is True


def test_failed_verifier_results_cannot_produce_passing_run_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _copy_fixture(tmp_path)
    monkeypatch.setattr(
        external_execution,
        "verify_bundle",
        lambda _path: {"pass": False, "errors": []},
    )
    monkeypatch.setattr(
        external_execution,
        "run_regression",
        lambda _path: {"pass": False, "errors": []},
    )

    summary = run_external_fixture(
        fixture,
        tmp_path / "verification-failure-run",
        run_id="verification_failure",
    )

    assert summary.passed is False
    assert summary.evidence_bundles[0].verified is False
    assert summary.generated_regressions[0].passed is False
    assert any("verification failed without details" in error for error in summary.errors)
    assert any("replay failed without details" in error for error in summary.errors)


def test_declared_metriplane_version_mismatch_fails_preflight(tmp_path: Path) -> None:
    fixture = _copy_fixture(tmp_path)
    manifest_path = fixture / "source-manifest.json"
    manifest = _read_json(manifest_path)
    manifest["evaluation"]["metriplane_version"] = "9.9.9"
    _write_json(manifest_path, manifest)
    _rewrite_checksums(fixture)

    summary = validate_external_fixture(fixture)

    assert summary.passed is False
    assert summary.declared_metriplane_version == "9.9.9"
    assert any(
        "does not match the installed Metriplane version" in error for error in summary.errors
    )
