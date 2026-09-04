# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publish-pypi.yml"
RELEASING = ROOT / "docs" / "releasing.md"
RELEASES = ROOT / "docs" / "releases"
CHANGELOG = ROOT / "CHANGELOG.md"
SUPPORTED_ENVIRONMENTS = ROOT / "docs" / "SUPPORTED_ENVIRONMENTS.md"
WSL2_VALIDATION = ROOT / "docs" / "validation" / "wsl2-v0.3.0-owner-run.md"
V040_MIGRATION = RELEASES / "v0.4.0-migration.md"
V040_NOTES = RELEASES / "v0.4.0-release-notes.md"
V040_LAUNCH = RELEASES / "v0.4.0-launch-materials.md"


def _workflow() -> tuple[dict[str, object], str]:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def test_tag_publication_stops_after_verified_testpypi() -> None:
    workflow, text = _workflow()
    jobs = workflow["jobs"]

    assert jobs["gates"]["uses"] == "./.github/workflows/release-gates.yml"
    assert jobs["gates"]["needs"] == "provenance"
    assert jobs["gates"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert jobs["gates"]["with"] == {"enforce-release-decision": True}
    assert jobs["build"]["needs"] == ["provenance", "gates"]
    assert jobs["publish-testpypi"]["needs"] == ["provenance", "build"]
    assert jobs["verify-testpypi"]["needs"] == ["provenance", "publish-testpypi"]
    for name in (
        "provenance",
        "gates",
        "build",
        "publish-testpypi",
        "verify-testpypi",
    ):
        assert "github.event_name == 'push'" in jobs[name]["if"]

    build = jobs["build"]
    build_steps = build["steps"]
    build_step_names = [step["name"] for step in build_steps if "name" in step]
    assert len(build_step_names) == len(set(build_step_names))
    named_steps = {step["name"]: step for step in build_steps if "name" in step}
    setup_uv_steps = [
        step for step in build_steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert len(setup_uv_steps) == 1
    setup_uv = setup_uv_steps[0]
    assert build["env"]["UV_NO_CONFIG"] == "1"
    assert setup_uv["uses"] == ("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9")
    assert setup_uv["with"] == {"version": "0.12.0", "enable-cache": False}
    assert named_steps["Sync locked release environment"]["run"].splitlines() == [
        "uv --no-config lock --check",
        "uv --no-config sync --frozen --all-groups",
        "uv --no-config pip check",
    ]
    toolchain_proof = named_steps["Prove exact release toolchain"]["run"]
    for fragment in (
        "uv --version",
        'project["tool"]["uv"]["required-version"]',
        'project["dependency-groups"]["dev"]',
        "metadata.version(name)",
        'project["build-system"]["requires"]',
        "governed[normalized] = actual",
        "governed.get(name.lower())",
    ):
        assert fragment in toolchain_proof
    assert named_steps["Install Chromium for complete release qualification"]["run"] == (
        "uv --no-config run --frozen python -m playwright install chromium --with-deps"
    )
    assert named_steps["Run the complete test suite"]["run"] == (
        "uv --no-config run --frozen python -m pytest -q"
    )

    build_run = named_steps["Build, inspect, and fingerprint distributions"]["run"]
    assert build_run.count("uv --no-config run --frozen python -m build") == 1
    assert build_run.count("--no-isolation") == 1
    assert "--installer" not in build_run
    assert "uv --no-config run --frozen python -m twine check --strict" in build_run
    assert build_run.count("uv --no-config run --frozen python tools/release_artifacts.py") == 3
    wheel_smoke_index = next(
        index
        for index, step in enumerate(build_steps)
        if step.get("name") == "Smoke-test the wheel outside the checkout"
    )
    qualification_text = "\n".join(
        str(step.get("run", "")) for step in build_steps[:wheel_smoke_index]
    )
    assert "pip install" not in qualification_text
    assert "python -m pip install . pytest setuptools build twine" not in text
    assert "python -m twine check --strict release-artifacts/dist/*" in text
    assert "Install and smoke-test the source distribution independently" in text
    assert text.count("packages-dir: release-artifacts/dist/") == 2
    assert "retention-days: 90" in text
    assert "skip-existing" not in text


def test_production_requires_a_separate_owner_only_manual_dispatch() -> None:
    workflow, text = _workflow()
    jobs = workflow["jobs"]
    trigger = workflow.get("on", workflow.get(True))

    assert set(trigger) == {"push", "workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"release_run_id", "version", "confirmation"}
    assert all(item["required"] is True for item in inputs.values())

    request = jobs["validate-production-request"]
    preflight = jobs["verify-production-artifacts"]
    publish = jobs["publish-pypi"]
    verify = jobs["verify-pypi"]
    reconcile = jobs["reconcile-production-lease"]
    for job in (request, preflight, publish, verify, reconcile):
        assert "github.event_name == 'workflow_dispatch'" in job["if"]
    assert preflight["needs"] == "validate-production-request"
    assert "environment" not in preflight
    assert publish["needs"] == [
        "validate-production-request",
        "verify-production-artifacts",
    ]
    assert verify["needs"] == ["validate-production-request", "publish-pypi"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"]["id-token"] == "write"
    assert publish["permissions"]["checks"] == "read"
    assert publish["permissions"]["contents"] == "read"
    assert "contents: write" not in text
    assert request["permissions"]["pull-requests"] == "read"
    assert publish["permissions"]["pull-requests"] == "read"
    assert reconcile["needs"] == [
        "validate-production-request",
        "publish-pypi",
        "verify-pypi",
    ]
    assert reconcile["permissions"] == {"checks": "read", "contents": "read"}
    assert text.count("uv run python tools/check_blockers.py") == 2
    assert text.count("--require-merged-approval") == 2
    assert text.count('--validated-sha "$RELEASE_COMMIT"') == 2

    request_names = [step.get("name") for step in request["steps"]]
    publish_names = [step.get("name") for step in publish["steps"]]
    assert request_names[-1] == "Revalidate release blockers at production dispatch"
    publish_index = publish_names.index("Publish the verified distributions to PyPI")
    assert publish_names[publish_index - 4 : publish_index] == [
        "Wait for the App-owned main-update lease",
        "Revalidate release blockers while main updates are fenced",
        "Reassert the lease and exact main immediately before publish",
        "Rehash the exact artifact set immediately before publish",
    ]

    required = (
        'test "$GITHUB_ACTOR" = "$GITHUB_REPOSITORY_OWNER"',
        'test "$GITHUB_TRIGGERING_ACTOR" = "$GITHUB_REPOSITORY_OWNER"',
        'test "$GITHUB_REF" = "refs/heads/main"',
        'test "$GITHUB_SHA" = "$(git rev-parse origin/main)"',
        "publish metriplane ${RELEASE_VERSION} to production",
        "/actions/runs/${RELEASE_RUN_ID}",
        "/actions/runs/${RELEASE_RUN_ID}/jobs?filter=latest&per_page=100",
        '"event": "push"',
        '"path": ".github/workflows/publish-pypi.yml"',
        '"conclusion": "success"',
        "Verify TestPyPI artifact identity and installation",
        '"name") == "python-package-distributions"',
        "run-id: ${{ inputs.release_run_id }}",
        "github-token: ${{ github.token }}",
        "--repository https://test.pypi.org",
        "--repository https://pypi.org",
        "acquire-publish-lease",
        "assert-publish-lease",
        "reconcile-publish-lease",
        "PUBLISH_RESULT",
        "VERIFY_RESULT",
    )
    assert all(fragment in text for fragment in required)


def test_cross_run_artifacts_are_downloaded_after_checkout() -> None:
    workflow, _ = _workflow()
    jobs = workflow["jobs"]

    for name in (
        "verify-production-artifacts",
        "publish-pypi",
        "verify-pypi",
    ):
        uses = [step.get("uses", "") for step in jobs[name]["steps"]]
        checkout = next(i for i, value in enumerate(uses) if "actions/checkout@" in value)
        download = next(i for i, value in enumerate(uses) if "actions/download-artifact@" in value)
        assert checkout < download, name


def test_tag_and_artifact_identity_are_explicit_release_gates() -> None:
    _, text = _workflow()

    required = (
        'test "$(git cat-file -t "$tag_ref")" = "tag"',
        'git rev-parse "${tag_ref}^{commit}"',
        'test "$tag_commit" = "$(git rev-parse origin/main)"',
        'git merge-base --is-ancestor "$tag_commit" origin/main',
        'test "$GITHUB_REF_NAME" = "v${package_version}"',
        "create-manifest",
        "verify-manifest",
        "inspect-sdist",
        "SHA256SUMS",
        "--repository https://test.pypi.org",
    )
    assert all(fragment in text for fragment in required)
    assert 'test "$RELEASE_COMMIT" = "$(git rev-parse origin/main)"' not in text
    assert text.count("acquire-publish-lease") == 1
    assert text.count("assert-publish-lease") == 1
    assert text.count("reconcile-publish-lease") == 1
    assert text.count("verify-registry") == 4
    assert text.count("sha256sum --check ../SHA256SUMS") == 2
    assert "find . -maxdepth 1 -type f -printf '%f\\n'" in text


def test_release_runbook_is_reusable_and_keeps_owner_stop_gates() -> None:
    text = RELEASING.read_text(encoding="utf-8")

    assert "Prepare v0.2.1" not in text
    assert "Publish v0.2.1" not in text
    assert "<version>" in text
    assert "one wheel and one source distribution" in text
    assert "source distribution independently" in text
    assert "Do not start the production workflow dispatch" in text
    assert "publish metriplane <version> to production" in text
    assert "Do not merge the final candidate" in text
    assert 'test -z "$(git status --porcelain)"' in text
    assert ("Zenodo's GitHub\nintegration will **not** automatically archive v0.4.0.post1") in text
    assert "The frozen v0.2.0 DOI\nmust not be attached to v0.4.0.post1" in text
    assert text.count("6a87936b5471c320efa6bcd7f5d1fe5569ca57b9") == 1
    assert text.count("failed workflow `33695500256`") == 1
    for command in (
        "uv --no-config lock --check",
        "uv --no-config sync --frozen --all-groups",
        "uv --no-config pip check",
        "uv --no-config run --frozen python -m playwright install chromium --with-deps",
        "uv --no-config run --frozen python -m pytest -q",
        "--no-isolation",
    ):
        assert command in text
    source_section = text.split("## Validate the candidate locally", maxsplit=1)[1].split(
        "Test the wheel outside the checkout", maxsplit=1
    )[0]
    assert "pip install" not in source_section
    assert "python -m pip install -e . pytest setuptools build twine" not in text
    assert "--no-install-project" not in text
    assert "--no-build-isolation" not in text


def test_v030_release_copy_and_draft_materials_are_separated() -> None:
    migration = (RELEASES / "v0.3.0-migration.md").read_text(encoding="utf-8")
    notes = (RELEASES / "v0.3.0-release-notes.md").read_text(encoding="utf-8")
    launch = (RELEASES / "v0.3.0-launch-materials.md").read_text(encoding="utf-8")

    assert "DRAFT — UNPUBLISHED" not in migration
    assert "DRAFT — UNPUBLISHED" not in notes
    assert "DRAFT — UNPUBLISHED" not in launch
    assert "v0.3.0 is a usability and adoption release" in migration
    assert "Install and run the exact release with" in migration
    assert "release candidate" not in migration.lower()
    assert "Release commit: `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`" in notes
    assert "4be2c13a5c4118c7e34f45b5b73939fce13e876ea9256bdc0b634c365482e8c9" in notes
    assert "8df70c5253714890aaf97713a295ab66cca96fa0268104344a5b858b6053cb51" in notes
    assert "Release date: `2026-08-09`" in notes
    assert "v0.3.0 DOI: none" in notes
    assert "Final main commit: `e8ee6c63deaee47bd450c5d6c7523d5bd699852a`" in launch
    assert "actions/runs/31322806657" in launch

    required_migration_topics = (
        "package and runs without a camera",
        "Python 3.12 and 3.13",
        "do not\nsilently replace",
        "validation is stricter",
        "fail-closed",
        "bundled camera-free demo completed",
        "WSL2 Ubuntu 24.04 has a bounded owner-run",
        "Incident Report",
    )
    assert all(topic in migration for topic in required_migration_topics)

    assert notes.index("Metriplane v0.3.0 adds a bundled") < notes.index("## Install and run")
    for result in ("six events", "one incident", "35.0 seconds", "verified", "passed"):
        assert result in notes
    assert "No unfamiliar-user comprehension study was completed before release" in notes
    assert "no passing human-validation claim is made" in notes


def test_v040_candidate_materials_keep_durable_and_draft_claims_separate() -> None:
    index = (RELEASES / "README.md").read_text(encoding="utf-8")
    migration = V040_MIGRATION.read_text(encoding="utf-8")
    notes = V040_NOTES.read_text(encoding="utf-8")
    launch = V040_LAUNCH.read_text(encoding="utf-8")

    assert index.index("v0.4.0-migration.md") < index.index("v0.3.0-migration.md")
    assert index.index("v0.4.0-release-notes.md") < index.index("v0.3.0-release-notes.md")
    assert index.index("v0.4.0-launch-materials.md") < index.index("v0.3.0-launch-materials.md")

    assert "# v0.4.0.post1 migration and behavior changes" in migration
    assert "DRAFT — UNPUBLISHED" not in migration
    assert 'python -m pip install "metriplane==0.4.0.post1"' in migration
    migration_headings = (
        "## Primary user path",
        "## External fixture version boundary",
        "## Supported Python and environments",
        "## Deferred assurance work",
        "## Research-version boundary",
    )
    assert all(heading in migration for heading in migration_headings)

    assert "# Metriplane v0.4.0.post1 release notes" in notes
    assert "**DRAFT — UNPUBLISHED**" in notes
    assert "v0.4.0.post1 DOI: none" in notes
    assert "No\n0.4.0 package or GitHub Release was published" in notes
    assert "Post1 adds no product capability or assurance claim" in notes
    for placeholder in (
        "<fill-after-production-verification>",
        "<fill-from-approved-final-main>",
        "<fill-from-retained-build-once-manifest>",
    ):
        assert placeholder in notes
    notes_headings = (
        "## Install and run",
        "## Reduced Truth Recovery core",
        "## Qualification",
        "## Supported environments",
        "## Known limitations and deferred work",
        "## Research boundary",
    )
    assert all(heading in notes for heading in notes_headings)

    assert "# v0.4.0.post1 launch materials" in launch
    assert "**DRAFT — UNPUBLISHED**" in launch
    assert "metriplane-0.4.0.post1-py3-none-any.whl" in launch
    assert "metriplane-0.4.0.post1.tar.gz" in launch
    assert "v0.4.0.post1 DOI: none" in launch
    assert "## Zenodo stop gate" in launch
    checklist = [line for line in launch.splitlines() if line.startswith("- [")]
    assert checklist
    assert all(line.startswith("- [ ]") for line in checklist)

    for text in (migration, notes, launch):
        assert "reduced Truth Recovery core" in text
        assert "MP2-007" in text
        for task in ("MP2-014", "MP2-015", "MP2-016", "MP2-017"):
            assert task in text


def test_wsl2_owner_run_claim_is_recorded_and_bounded() -> None:
    environments = SUPPORTED_ENVIRONMENTS.read_text(encoding="utf-8")
    validation = WSL2_VALIDATION.read_text(encoding="utf-8")

    assert "No fresh exact-v0.4.0.post1 candidate run is recorded" in environments
    assert "No v0.4.0.post1 WSL2 support claim is made" in environments
    assert "No v0.4.0.post1 native-Windows support claim is made" in environments
    assert "926 passed" not in environments
    assert "925 passed" not in environments

    for expected in (
        "75bb31e801410df5f94ea60514fc1177811a999a",
        "Ubuntu 24.04",
        "Python: 3.12.3",
        "No broken requirements found",
        "metriplane 0.3.0",
        "7 seconds",
        "6 events",
        "1 incident",
        "evidence bundle verification: passed",
        "generated regression check: passed",
        "Automatic browser opening was **not** validated",
        "bundled demo completed from Windows Command Prompt",
    ):
        assert expected in validation

    active_claim_paths = (
        ROOT / "SUPPORT.md",
        ROOT / "CHANGELOG.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "ROADMAP.md",
        SUPPORTED_ENVIRONMENTS,
        ROOT / "docs" / "user-guide" / "integrations.md",
        RELEASES / "v0.3.0-migration.md",
        RELEASES / "v0.3.0-release-notes.md",
        RELEASES / "v0.3.0-launch-materials.md",
        RELEASING,
    )
    stale_claims = (
        "WSL2 is not currently advertised",
        "WSL2 remains unadvertised",
        "No clean manual v0.3.0 run recorded",
    )
    for path in active_claim_paths:
        text = path.read_text(encoding="utf-8")
        assert "WSL2" in text, path
        assert all(claim not in text for claim in stale_claims), path


def test_citation_paths_do_not_mix_release_and_research_versions() -> None:
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    zenodo = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    guide = (ROOT / "docs" / "user-guide" / "citing.md").read_text(encoding="utf-8")

    assert citation["version"] == "0.2.0"
    assert citation["doi"] == "10.5281/zenodo.20736619"
    assert zenodo["version"] == "0.2.0"
    assert "10.5281/zenodo.20736619" in guide
    assert "10.2139/ssrn.7166858" in guide
    assert "v0.1.3" in guide
    assert "Exact v0.4.0.post1 software release" in guide
    assert "Metriplane v0.4.0.post1 is the corrected publication identity" in guide
    assert "Parkkinen, Miko. *Metriplane v0.4.0.post1* [Computer software]." in guide
    assert "releases/tag/v0.4.0.post1" in guide
    assert "No v0.4.0.post1 DOI exists. Do not use the v0.2.0 DOI for v0.4.0.post1." in guide
    assert "Prior v0.3.0 software release" in guide
    assert "prior usability and adoption software release" in guide
    assert "releases/tag/v0.3.0" in guide
    assert "<release year>" not in guide
    assert "Do not use the v0.2.0 DOI for v0.3.0" in guide


def test_v040_release_candidate_sets_the_package_version() -> None:
    import metriplane

    assert metriplane.__version__ == "0.4.0.post1"


def test_changelog_is_dated_and_complete() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")

    assert "## [0.4.0.post1] — 2026-09-04 — Reduced Truth Recovery publication recovery" in text
    assert "## [0.4.0] — 2026-09-02 — Failed publication attempt" in text
    assert "no 0.4.0 package or GitHub\n  Release was published" in text
    assert "## [0.3.0] — 2026-08-09 — Usability and adoption" in text
    assert "## [Unreleased]" in text
    assert "owner-only manual dispatch" in text
    assert "release date TBD" not in text
    assert "RELEASE CANDIDATE — UNPUBLISHED" not in text
    for topic in (
        "package-contained, camera-free",
        "Incident Report",
        "Python 3.12 and\n  3.13",
        "private GitHub security-advisory",
        "fail closed",
        "No v0.3.0 DOI is claimed",
    ):
        assert topic in text


def test_release_copy_preserves_research_version_boundaries() -> None:
    paths = (
        ROOT / "ARTIFACTS.md",
        ROOT / "docs" / "eval" / "evidence_index.md",
        ROOT / "docs" / "eval" / "evidence_matrix.md",
        ROOT / "docs" / "user-guide" / "research-artifacts.md",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "v0.4.0.post1" in text
        assert "v0.3.0" in text
        assert "v0.2.0" in text
        assert "v0.1.3" in text

    artifacts = paths[0].read_text(encoding="utf-8")
    research = paths[-1].read_text(encoding="utf-8")
    assert "Reduced Truth Recovery core software release: `v0.4.0.post1`" in artifacts
    assert "No DOI is claimed for v0.4.0.post1" in artifacts
    assert "Usability and adoption software release: `v0.3.0`" in artifacts
    assert "No DOI is claimed for v0.3.0" in artifacts
    assert "No v0.4.0.post1 DOI exists" in research
    assert "No v0.3.0 DOI exists" in research
    assert "v0.3.0 output produced the SoftwareX or TIM\nmeasurements" in research


def test_durable_release_docs_do_not_encode_transient_pr_state() -> None:
    paths = (
        ROOT / "ARTIFACTS.md",
        ROOT / "ROADMAP.md",
        ROOT / "docs" / "eval" / "evidence_index.md",
        ROOT / "docs" / "eval" / "evidence_matrix.md",
        V040_MIGRATION,
        ROOT / "docs" / "releases" / "v0.3.0-migration.md",
        ROOT / "docs" / "user-guide" / "citing.md",
        ROOT / "docs" / "user-guide" / "research-artifacts.md",
    )
    forbidden = (
        "release candidate",
        "release-candidate",
        "unmerged",
        "untagged",
        "unpublished",
        "release-candidate branch",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        assert all(term not in text for term in forbidden), path
