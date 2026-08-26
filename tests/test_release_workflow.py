# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED = WORKFLOWS / "release-required.yml"
PUBLISH = WORKFLOWS / "publish-pypi.yml"


def _workflow(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_release_required_has_one_fail_closed_producer() -> None:
    workflow = _workflow(REQUIRED)
    jobs = workflow["jobs"]
    producers = [job for job in jobs.values() if job.get("name") == "Release / required"]
    assert len(producers) == 1
    required = producers[0]
    assert required["if"] == "always()"
    assert required["needs"] == ["contracts", "fake-release"]
    assert required["permissions"] == {"contents": "read"}
    text = REQUIRED.read_text(encoding="utf-8")
    assert "--expected-dependency contracts" in text
    assert "--expected-dependency fake-release" in text
    assert "github.event.pull_request.head.sha || github.sha" in text

    all_producers = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        parsed = _workflow(path)
        for job in parsed.get("jobs", {}).values():
            if job.get("name") == "Release / required":
                all_producers.append(path.name)
    assert all_producers == ["release-required.yml"]


def test_release_required_is_read_only_and_runs_on_ordinary_prs() -> None:
    workflow = _workflow(REQUIRED)
    trigger = workflow.get("on", workflow.get(True))
    assert "pull_request" in trigger
    assert "push" in trigger
    assert "workflow_dispatch" in trigger
    assert workflow["permissions"] == {"contents": "read"}
    text = REQUIRED.read_text(encoding="utf-8")
    assert "tests/release/test_local_fake_release.py" in text
    assert "tests/test_release_contracts.py" in text
    assert "tests/test_release_workflow.py" in text
    assert "--mode fixture" in text
    assert "id-token: write" not in text
    assert "git push" not in text


def test_release_required_produces_exact_validated_qualification_authority() -> None:
    required = _workflow(REQUIRED)
    contract_steps = required["jobs"]["contracts"]["steps"]
    validation_index = next(
        index
        for index, step in enumerate(contract_steps)
        if step.get("name")
        == "Validate candidate qualification, non-author approval, and staged read-back"
    )
    upload_index = next(
        index
        for index, step in enumerate(contract_steps)
        if step.get("name") == "Upload exact validated qualification authority"
    )
    upload = contract_steps[upload_index]

    assert validation_index < upload_index
    assert upload["if"] == "steps.context.outputs.mode == 'release-qualification'"
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["path"].splitlines() == [".release-authority/**/*.json"]
    assert {key: value for key, value in upload["with"].items() if key != "path"} == {
        "name": "release-qualification-evidence",
        "if-no-files-found": "error",
        "include-hidden-files": True,
        "overwrite": False,
        "retention-days": 90,
    }
    required_text = REQUIRED.read_text(encoding="utf-8")
    for fragment in (
        "Require exact authority source provenance",
        '"${api_root}/actions/runs/${AUTHORITY_RUN_ID}"',
        '"${api_root}/actions/runs/${AUTHORITY_RUN_ID}/artifacts?name=${AUTHORITY_ARTIFACT}&per_page=100"',
        '"head_sha": source_sha',
        '"path": ".github/workflows/release-required.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        '"repository.full_name"',
        "EXPECTED_SOURCE_SHA: ${{ steps.context.outputs.source_sha }}",
        "AUTHORITY_SOURCE_RUN_ID: ${{ steps.authority-inputs.outputs.run_id }}",
        '"delta.json": ("candidate_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"gate-instance.json": ("frozen_source_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"impact-manifest.json": ("head_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"source-freeze.json": ("source_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '("gate-instance.json", "role-assignments.json")',
        'value.get("data", {}).get("run_id") != os.environ["AUTHORITY_SOURCE_RUN_ID"]',
    ):
        assert fragment in required_text

    publish = _workflow(PUBLISH)
    download = next(
        step
        for step in publish["jobs"]["validate-production-request"]["steps"]
        if step.get("with", {}).get("name") == "release-qualification-evidence"
    )
    assert upload["with"]["name"] == download["with"]["name"]


def test_publication_consumes_qualification_and_does_not_create_authority() -> None:
    workflow = _workflow(PUBLISH)
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["qualification_run_id"]["required"] is True
    assert inputs["qualification_record_digest"]["required"] is True
    jobs = workflow["jobs"]
    request = jobs["validate-production-request"]
    commands = "\n".join(step.get("run", "") for step in request["steps"])
    assert "validate_release_qualification.py" in commands
    assert "validate_release_role_assignments.py" in commands
    assert "validate_release_approval.py" in commands
    assert "validate_release_retention.py" in commands
    assert "check_release_readiness.py" in commands
    assert "validate_release_artifact_manifest.py" in commands
    assert "--mode live" not in commands
    assert "--input release-authority/" not in commands
    assert "qualification_record_digest" in PUBLISH.read_text(encoding="utf-8")
    assert "record_release_approval.py" not in commands
    assert "record_release_role_assignments.py" not in commands


def test_production_request_uses_canonical_live_authority_contracts() -> None:
    workflow = _workflow(PUBLISH)
    request = workflow["jobs"]["validate-production-request"]
    commands = "\n".join(step.get("run", "") for step in request["steps"])
    required = (
        "sha256sum release-authority/qualification.json",
        "--record release-authority/qualification.json",
        "--record release-authority/role-assignments.json",
        'MILESTONE="v${RELEASE_VERSION%.*}"',
        "v0.4|v0.5|v0.6|v0.7|v0.8|v0.9|v1.0",
        '--milestone "$MILESTONE"',
        'AUTHORITY_SOURCE_RUN_ID="$(python -c',
        '["data"]["run_id"]',
        '--run-id "$AUTHORITY_SOURCE_RUN_ID"',
        "--check-conflicts",
        "--check-freshness",
        "--gate-instance release-authority/gate-instance.json",
        "--qualification release-authority/qualification.json",
        "--no-prepublication-rubric",
        "--record release-authority/prepublication/approval.json",
        "--manifest release-authority/evidence-manifest.json",
        "--receipts release-authority/prepublication/retention-receipts.json",
        "--read-back",
        "--candidate-identity release-authority/candidate-identity.json",
        "--predecessor release-authority/predecessor.json",
        "--linear-snapshot release-authority/linear-snapshot.json",
        "--artifact-manifest release-authority/artifact-manifest.json",
        "--delta release-authority/delta.json",
        "--delta-test-map release-authority/delta-test-map.json",
        '--out "$RUNNER_TEMP/readiness.json"',
        "release-authority/readiness.json",
        "sha256sum --check ../SHA256SUMS",
        "--artifacts release-artifacts/dist",
        "--read-hash",
    )
    assert all(fragment in commands for fragment in required)

    artifact_download = next(
        step
        for step in request["steps"]
        if step.get("with", {}).get("name") == "python-package-distributions"
    )
    assert artifact_download["with"] == {
        "name": "python-package-distributions",
        "path": "release-artifacts/",
        "run-id": "${{ inputs.release_run_id }}",
        "github-token": "${{ github.token }}",
    }

    authority_index = commands.index("validate_release_qualification.py")
    artifact_index = commands.index("validate_release_artifact_manifest.py")
    eligibility_index = commands.index('test "$GITHUB_ACTOR" = "$GITHUB_REPOSITORY_OWNER"')
    assert authority_index < artifact_index < eligibility_index


def test_production_request_preserves_fail_closed_source_run_identity() -> None:
    workflow = _workflow(PUBLISH)
    request = workflow["jobs"]["validate-production-request"]
    commands = "\n".join(step.get("run", "") for step in request["steps"])
    required = (
        'test "$GITHUB_SHA" = "$(git rev-parse origin/main)"',
        '"event": "push"',
        '"head_branch": f"v{os.environ[\'RELEASE_VERSION\']}"',
        '"head_sha": os.environ["SOURCE_COMMIT"]',
        '"path": ".github/workflows/publish-pypi.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        'item.get("name") == "python-package-distributions"',
        "source run must contain exactly one unexpired",
        'item.get("name")',
        '== "Verify TestPyPI artifact identity and installation"',
    )
    assert all(fragment in commands for fragment in required)


def test_qualification_provenance_precedes_authority_download() -> None:
    workflow = _workflow(PUBLISH)
    steps = workflow["jobs"]["validate-production-request"]["steps"]
    provenance_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Require exact qualification workflow provenance"
    )
    download_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("with", {}).get("name") == "release-qualification-evidence"
    )
    authority_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Require retained cumulative release authority"
    )
    assert provenance_index < download_index < authority_index

    command = steps[provenance_index]["run"]
    required = (
        'test "$GITHUB_REF" = "refs/heads/main"',
        'test "$GITHUB_SHA" = "$(git rev-parse origin/main)"',
        "/actions/runs/${QUALIFICATION_RUN_ID}",
        "/actions/runs/${QUALIFICATION_RUN_ID}/artifacts?name=release-qualification-evidence&per_page=100",
        '"event": "workflow_dispatch"',
        '"head_branch": "main"',
        '"head_sha": candidate_sha',
        '"path": ".github/workflows/release-required.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        'payload.get("total_count") != 1',
        '"expired": False',
        '"name": "release-qualification-evidence"',
        '"id": run_id',
    )
    assert all(fragment in command for fragment in required)


def _qualification_validator_script() -> str:
    workflow = _workflow(PUBLISH)
    steps = workflow["jobs"]["validate-production-request"]["steps"]
    command = next(
        step["run"]
        for step in steps
        if step.get("name") == "Require exact qualification workflow provenance"
    )
    marker = "python - <<'PY'\n"
    assert command.count(marker) == 1
    return command.split(marker, 1)[1].rsplit("\nPY", 1)[0]


def _run_qualification_validator(
    root: Path,
    run: dict[str, object],
    artifacts: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    root.mkdir()
    run_path = root / "run.json"
    artifacts_path = root / "artifacts.json"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    artifacts_path.write_text(json.dumps(artifacts), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_REPOSITORY": "Miko997/metriplane",
            "QUALIFICATION_ARTIFACTS_JSON": str(artifacts_path),
            "QUALIFICATION_CANDIDATE_SHA": "a" * 40,
            "QUALIFICATION_RUN_ID": "1234",
            "QUALIFICATION_RUN_JSON": str(run_path),
        }
    )
    return subprocess.run(
        [sys.executable, "-c", _qualification_validator_script()],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_qualification_provider_payload_mutations_fail_closed(tmp_path: Path) -> None:
    run: dict[str, object] = {
        "id": 1234,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "path": ".github/workflows/release-required.yml",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": "Miko997/metriplane"},
    }
    artifact: dict[str, object] = {
        "id": 5678,
        "name": "release-qualification-evidence",
        "expired": False,
        "workflow_run": {
            "id": 1234,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }
    artifacts: dict[str, object] = {"total_count": 1, "artifacts": [artifact]}
    valid = _run_qualification_validator(tmp_path / "valid", run, artifacts)
    assert valid.returncode == 0, valid.stderr

    run_mutations: tuple[tuple[str, dict[str, object]], ...] = (
        ("workflow", {"path": ".github/workflows/publish-pypi.yml"}),
        ("event", {"event": "push"}),
        ("status", {"status": "in_progress"}),
        ("conclusion", {"conclusion": "failure"}),
        ("candidate", {"head_sha": "b" * 40}),
        ("branch", {"head_branch": "release"}),
    )
    for label, mutation in run_mutations:
        mutated_run = copy.deepcopy(run)
        mutated_run.update(mutation)
        result = _run_qualification_validator(tmp_path / f"run-{label}", mutated_run, artifacts)
        assert result.returncode != 0, label

    artifact_mutations = (
        ("expired", {"expired": True}),
        ("wrong-name", {"name": "other-evidence"}),
        ("wrong-run", {"workflow_run": {"id": 9999, "head_branch": "main", "head_sha": "a" * 40}}),
        ("wrong-sha", {"workflow_run": {"id": 1234, "head_branch": "main", "head_sha": "b" * 40}}),
    )
    for label, mutation in artifact_mutations:
        mutated_artifact = copy.deepcopy(artifact)
        mutated_artifact.update(mutation)
        payload = {"total_count": 1, "artifacts": [mutated_artifact]}
        result = _run_qualification_validator(tmp_path / f"artifact-{label}", run, payload)
        assert result.returncode != 0, label

    duplicate = {"total_count": 2, "artifacts": [artifact, copy.deepcopy(artifact)]}
    result = _run_qualification_validator(tmp_path / "duplicate", run, duplicate)
    assert result.returncode != 0


def test_tag_is_observed_but_never_accepted_as_release_authority() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert 'test "$(git cat-file -t "$tag_ref")" = "tag"' in text
    assert "release-qualification-evidence" in text
    assert text.index("Require retained cumulative release authority") < text.index(
        "Require owner confirmation and a successful artifact workflow"
    )
    assert "tag_is_authority" not in text


def test_publish_workflow_reuses_the_single_artifact_builder() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "python tools/release_artifacts.py create-manifest" in text
    assert "python tools/release_artifacts.py verify-manifest" in text
    assert "python -m build --outdir release-artifacts/dist" in text
    assert text.count("python -m build --outdir release-artifacts/dist") == 1
