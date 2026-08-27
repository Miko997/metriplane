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
    download_index = next(
        index
        for index, step in enumerate(contract_steps)
        if step.get("name") == "Download and compare independent authority-store bundles"
    )
    extraction_index = next(
        index
        for index, step in enumerate(contract_steps)
        if step.get("name") == "Extract the exact authority bundle safely"
    )
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

    assert download_index < extraction_index < validation_index < upload_index
    assert not any(
        str(step.get("uses", "")).startswith("actions/download-artifact@")
        for step in contract_steps
    )
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
        "authority_bundle_sha256",
        "vars.RELEASE_AUTHORITY_STORE_A_URL",
        "vars.RELEASE_AUTHORITY_STORE_B_URL",
        "secrets.RELEASE_AUTHORITY_STORE_A_TOKEN",
        "secrets.RELEASE_AUTHORITY_STORE_B_TOKEN",
        "curl --proto '=https'",
        "--max-filesize 536870912",
        "authority stores must use distinct HTTPS host identities",
        '"${RUNNER_TEMP}/authority-store-a.tar"',
        '"${RUNNER_TEMP}/authority-store-b.tar"',
        "cmp --silent",
        'test "$store_a_sha256" = "$store_b_sha256"',
        'test "$store_a_sha256" = "$AUTHORITY_BUNDLE_SHA256"',
        "Extract the exact authority bundle safely",
        "if not is_directory and not member.isfile()",
        "authority bundle repeats a path",
        "EXPECTED_SOURCE_SHA: ${{ steps.source.outputs.sha }}",
        "AUTHORITY_SOURCE_RUN_ID: ${{ steps.authority-inputs.outputs.run_id }}",
        '"delta.json": ("candidate_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"gate-instance.json": ("frozen_source_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"impact-manifest.json": ("head_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '"source-freeze.json": ("source_sha", os.environ["EXPECTED_SOURCE_SHA"])',
        '("gate-instance.json", "role-assignments.json")',
        'value.get("data", {}).get("run_id") != os.environ["AUTHORITY_SOURCE_RUN_ID"]',
        "validate_release_role_assignments.py",
        '--run-id "$AUTHORITY_SOURCE_RUN_ID"',
        '--role-assignments "$root/role-assignments.json"',
    ):
        assert fragment in required_text
    assert "authority_artifact" not in required_text
    assert "/actions/runs/${AUTHORITY_RUN_ID}" not in required_text

    publish = _workflow(PUBLISH)
    download = next(
        step
        for step in publish["jobs"]["validate-production-request"]["steps"]
        if step.get("with", {}).get("path") == "release-authority/"
    )
    assert upload["with"]["name"] == "release-qualification-evidence"
    assert download["with"] == {
        "artifact-ids": "${{ steps.qualification.outputs.artifact_id }}",
        "path": "release-authority/",
        "run-id": "${{ inputs.qualification_run_id }}",
        "github-token": "${{ github.token }}",
    }


def test_publication_consumes_qualification_and_does_not_create_authority() -> None:
    workflow = _workflow(PUBLISH)
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["qualification_run_id"]["required"] is True
    assert inputs["qualification_record_digest"]["required"] is True
    assert inputs["authority_bundle_sha256"]["required"] is True
    assert inputs["authority_run_id"]["required"] is True
    assert inputs["evidence_manifest_sha256"]["required"] is True
    jobs = workflow["jobs"]
    request = jobs["validate-production-request"]
    request_commands = "\n".join(step.get("run", "") for step in request["steps"])
    authorization_commands = "\n".join(
        step.get("run", "") for step in jobs["authorize-production"]["steps"]
    )
    assert "validate_release_qualification.py" not in request_commands
    assert "validate_release_retention.py" not in request_commands
    assert "validate_release_role_assignments.py" in request_commands
    assert "validate_release_approval.py" in request_commands
    assert "check_release_readiness.py" in request_commands
    assert "validate_release_artifact_manifest.py" in request_commands
    assert "validate_release_qualification.py" in authorization_commands
    assert "validate_release_retention.py" in authorization_commands
    assert "--attempt-store-readback" in authorization_commands
    assert "--provider-attestation-keyring" in authorization_commands
    assert "--mode live" not in request_commands
    assert "--input release-authority/" not in request_commands
    assert "qualification_record_digest" in PUBLISH.read_text(encoding="utf-8")
    assert "record_release_approval.py" not in request_commands
    assert "record_release_role_assignments.py" not in request_commands


def test_production_request_uses_canonical_live_authority_contracts() -> None:
    workflow = _workflow(PUBLISH)
    request = workflow["jobs"]["validate-production-request"]
    commands = "\n".join(step.get("run", "") for step in request["steps"])
    required = (
        "sha256sum release-authority/qualification.json",
        "--record release-authority/role-assignments.json",
        'MILESTONE="v${RELEASE_VERSION%.*}"',
        "v0.4|v0.5|v0.6|v0.7|v0.8|v0.9|v1.0",
        '--milestone "$MILESTONE"',
        '--run-id "$AUTHORITY_SOURCE_RUN_ID"',
        "--check-conflicts",
        "--check-freshness",
        "--gate-instance release-authority/gate-instance.json",
        "--qualification release-authority/qualification.json",
        "--role-assignments release-authority/role-assignments.json",
        "--no-prepublication-rubric",
        "--record release-authority/prepublication/approval.json",
        '--approval-decision "$APPROVAL_DECISION_PATH"',
        '--provider-attestation-keyring "$PROVIDER_ATTESTATION_KEYRING"',
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
    assert 'test "$tag_commit" = "$GITHUB_SHA"' not in commands
    assert 'git merge-base --is-ancestor "$tag_commit" origin/main' in commands
    candidate_checkout = next(
        step
        for step in request["steps"]
        if step.get("name") == "Check out only the exact tagged candidate for validation"
    )
    assert candidate_checkout["with"]["ref"] == "${{ steps.request.outputs.commit }}"
    authority_step = next(
        step
        for step in request["steps"]
        if step.get("name") == "Require retained cumulative release authority"
    )
    assert authority_step["env"]["AUTHORITY_SOURCE_RUN_ID"] == "${{ inputs.authority_run_id }}"
    assert authority_step["env"]["CANDIDATE_SHA"] == "${{ steps.request.outputs.commit }}"

    artifact_download = next(
        step
        for step in request["steps"]
        if step.get("with", {}).get("path") == "release-artifacts/"
    )
    assert artifact_download["with"] == {
        "artifact-ids": "${{ steps.request.outputs.artifact_id }}",
        "path": "release-artifacts/",
        "run-id": "${{ inputs.release_run_id }}",
        "github-token": "${{ github.token }}",
    }

    authority_index = commands.index("validate_release_approval.py")
    artifact_index = commands.index("validate_release_artifact_manifest.py")
    eligibility_index = commands.index('test "$GITHUB_ACTOR" = "$GITHUB_REPOSITORY_OWNER"')
    assert eligibility_index < authority_index < artifact_index


def test_production_request_preserves_fail_closed_source_run_identity() -> None:
    workflow = _workflow(PUBLISH)
    request = workflow["jobs"]["validate-production-request"]
    commands = "\n".join(step.get("run", "") for step in request["steps"])
    required = (
        'test "$GITHUB_SHA" = "$(git rev-parse origin/main)"',
        '"event": "push"',
        '"head_branch": f"v{os.environ[\'RELEASE_VERSION\']}"',
        '"head_sha": source_commit',
        '"path": ".github/workflows/publish-pypi.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        '"name": "python-package-distributions"',
        "source run must contain exactly one unexpired",
        'item.get("name")',
        '== "Verify TestPyPI artifact identity and installation"',
    )
    assert all(fragment in commands for fragment in required)


def test_production_publish_refreshes_authority_after_environment_approval() -> None:
    workflow = _workflow(PUBLISH)
    workflow_text = PUBLISH.read_text(encoding="utf-8")
    assert 'test "$tag_commit" = "$GITHUB_SHA"' not in workflow_text
    assert "AUTHORITY_SOURCE_SHA" not in workflow_text
    assert workflow_text.count("validate_release_retention.py") == 2
    assert workflow_text.count("validate_publication_reconciliation.py") == 1

    authorization = workflow["jobs"]["authorize-production"]
    assert authorization["environment"] == {
        "name": "pypi",
        "url": "https://pypi.org/p/metriplane",
    }
    assert authorization["permissions"] == {"actions": "read", "contents": "read"}
    assert authorization["needs"] == [
        "validate-production-request",
        "verify-production-artifacts",
    ]
    authorization_steps = authorization["steps"]
    store_index = next(
        index
        for index, step in enumerate(authorization_steps)
        if step.get("name")
        == "Read back and compare exact authority bytes from both external stores"
    )
    validation_index = next(
        index
        for index, step in enumerate(authorization_steps)
        if step.get("name")
        == "Revalidate exact authority and artifacts immediately before OIDC handoff"
    )
    assert store_index < validation_index

    store_command = authorization_steps[store_index]["run"]
    store_requirements = (
        "AUTHORITY_STORE_A_URL",
        "AUTHORITY_STORE_B_URL",
        "authority stores must use distinct HTTPS host identities",
        "cmp --silent",
        'test "$store_a_sha256" = "$store_b_sha256"',
        'test "$store_a_sha256" = "$AUTHORITY_BUNDLE_SHA256"',
        "external stores and GitHub artifact have different JSON inventories",
        "external authority stores differ after safe archive parsing",
        "external stores and GitHub artifact contain digest-mismatched records",
        "qualification attempt retention receipt digest",
        "attempt-store-readbacks.txt",
    )
    assert all(fragment in store_command for fragment in store_requirements)

    validation = authorization_steps[validation_index]
    assert validation["env"]["CANDIDATE_SHA"] == (
        "${{ needs.validate-production-request.outputs.commit }}"
    )
    command = validation["run"]
    validation_requirements = (
        "/actions/runs/${QUALIFICATION_RUN_ID}",
        "/actions/artifacts/${QUALIFICATION_ARTIFACT_ID}",
        "/actions/runs/${RELEASE_RUN_ID}",
        "/actions/artifacts/${RELEASE_ARTIFACT_ID}",
        'test "$(git rev-parse "${tag_ref}^{commit}")" = "$CANDIDATE_SHA"',
        'git merge-base --is-ancestor "$CANDIDATE_SHA" origin/main',
        '"head_sha": candidate_sha',
        '"path": ".github/workflows/release-required.yml"',
        '"path": ".github/workflows/publish-pypi.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        '"delta.json": "candidate_sha"',
        '"gate-instance.json": "frozen_source_sha"',
        '"impact-manifest.json": "head_sha"',
        '"source-freeze.json": "source_sha"',
        "fresh authority external run binding mismatch",
        "sha256sum release-authority/qualification.json",
        "validate_release_gate_instance.py",
        "validate_release_role_assignments.py",
        '--run-id "$authority_run_id"',
        "--check-conflicts",
        "--check-freshness",
        "validate_release_qualification.py",
        '"${attempt_store_readback_args[@]}"',
        "validate_release_retention.py",
        "validate_release_approval.py",
        '--approval-decision "$APPROVAL_DECISION_PATH"',
        '--provider-attestation-keyring "$PROVIDER_ATTESTATION_KEYRING"',
        "--role-assignments release-authority/role-assignments.json",
        "check_release_readiness.py",
        "validate_release_artifact_manifest.py",
        'echo "release_artifact_id=$RELEASE_ARTIFACT_ID"',
    )
    assert all(fragment in command for fragment in validation_requirements)

    publish = workflow["jobs"]["publish-pypi"]
    assert publish["needs"] == "authorize-production"
    assert publish["permissions"] == {"actions": "read", "id-token": "write"}
    assert publish["environment"] == {
        "name": "pypi",
        "url": "https://pypi.org/p/metriplane",
    }
    assert [step.get("uses") for step in publish["steps"]] == [
        "actions/download-artifact@018cc2cf5baa6db3ef3c5f8a56943fffe632ef53",
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
    ]
    assert all("run" not in step for step in publish["steps"])
    assert publish["steps"][0]["with"]["artifact-ids"] == (
        "${{ needs.authorize-production.outputs.release_artifact_id }}"
    )

    testpypi_validation = workflow["jobs"]["validate-testpypi-artifacts"]
    assert testpypi_validation["permissions"] == {"actions": "read"}
    assert testpypi_validation["needs"] == ["provenance", "build"]
    assert any("run" in step for step in testpypi_validation["steps"])

    testpypi_publish = workflow["jobs"]["publish-testpypi"]
    assert testpypi_publish["needs"] == [
        "provenance",
        "build",
        "validate-testpypi-artifacts",
    ]
    assert testpypi_publish["permissions"] == {"actions": "read", "id-token": "write"}

    allowed_oidc_actions = {
        "actions/download-artifact@018cc2cf5baa6db3ef3c5f8a56943fffe632ef53",
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
    }
    for job in workflow["jobs"].values():
        if job.get("permissions", {}).get("id-token") != "write":
            continue
        assert all("run" not in step for step in job["steps"])
        assert {step.get("uses") for step in job["steps"]}.issubset(allowed_oidc_actions)


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
        if step.get("with", {}).get("path") == "release-authority/"
    )
    authority_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Require retained cumulative release authority"
    )
    assert provenance_index < download_index < authority_index

    command = steps[provenance_index]["run"]
    required = (
        "/actions/runs/${QUALIFICATION_RUN_ID}",
        "/actions/runs/${QUALIFICATION_RUN_ID}/artifacts?name=release-qualification-evidence&per_page=100",
        '"event": "workflow_dispatch"',
        '"head_branch": "main"',
        're.fullmatch(r"[0-9a-f]{40}", head_sha)',
        '"path": ".github/workflows/release-required.yml"',
        '"status": "completed"',
        '"conclusion": "success"',
        'payload.get("total_count") != 1',
        '"expired": False',
        '"name": "release-qualification-evidence"',
        '"id": run_id',
        "output.write(f\"artifact_id={artifact['id']}\\n\")",
        'git merge-base --is-ancestor "$qualification_head_sha" origin/main',
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
            "QUALIFICATION_RUN_ID": "1234",
            "QUALIFICATION_RUN_JSON": str(run_path),
            "GITHUB_OUTPUT": str(root / "output.txt"),
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
        ("malformed-head", {"head_sha": "not-a-commit"}),
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

    ancestor_run = {**run, "head_sha": "b" * 40}
    ancestor_artifact = copy.deepcopy(artifact)
    ancestor_artifact["workflow_run"] = {
        "id": 1234,
        "head_branch": "main",
        "head_sha": "b" * 40,
    }
    ancestor = _run_qualification_validator(
        tmp_path / "older-qualification-head",
        ancestor_run,
        {"total_count": 1, "artifacts": [ancestor_artifact]},
    )
    assert ancestor.returncode == 0, ancestor.stderr


def test_tag_is_observed_but_never_accepted_as_release_authority() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert 'test "$(git cat-file -t "$tag_ref")" = "tag"' in text
    assert "release-qualification-evidence" in text
    assert text.index("Resolve the exact annotated candidate and source artifact") < text.index(
        "Require retained cumulative release authority"
    )
    assert "tag_is_authority" not in text


def test_publish_workflow_reuses_the_single_artifact_builder() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "python tools/release_artifacts.py create-manifest" in text
    assert "python tools/release_artifacts.py verify-manifest" in text
    assert "python -m build --outdir release-artifacts/dist" in text
    assert text.count("python -m build --outdir release-artifacts/dist") == 1
