# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

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
        '--run-id "$QUALIFICATION_RUN_ID"',
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
