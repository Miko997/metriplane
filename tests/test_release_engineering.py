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


def _workflow() -> tuple[dict[str, object], str]:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text), text


def test_publication_chain_builds_once_and_protects_production() -> None:
    workflow, text = _workflow()
    jobs = workflow["jobs"]

    assert jobs["gates"]["uses"] == "./.github/workflows/release-gates.yml"
    assert jobs["gates"]["needs"] == "provenance"
    assert jobs["build"]["needs"] == ["provenance", "gates"]
    assert jobs["publish-testpypi"]["needs"] == ["provenance", "build"]
    assert jobs["verify-testpypi"]["needs"] == ["provenance", "publish-testpypi"]
    assert jobs["publish-pypi"]["needs"] == ["provenance", "verify-testpypi"]
    assert jobs["verify-pypi"]["needs"] == ["provenance", "publish-pypi"]
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"

    assert text.count("python -m build --outdir release-artifacts/dist") == 1
    assert "python -m twine check --strict release-artifacts/dist/*" in text
    assert "Install and smoke-test the source distribution independently" in text
    assert text.count("packages-dir: release-artifacts/dist/") == 2
    assert text.count("find . -maxdepth 1 -type f -printf") == 2
    assert "retention-days: 90" in text
    assert "skip-existing" not in text


def test_tag_and_artifact_identity_are_explicit_release_gates() -> None:
    _, text = _workflow()

    required = (
        'test "$(git cat-file -t "$tag_ref")" = "tag"',
        'git rev-parse "${tag_ref}^{commit}"',
        "git merge-base --is-ancestor \"$tag_commit\" origin/main",
        'test "$GITHUB_REF_NAME" = "v${package_version}"',
        "create-manifest",
        "verify-manifest",
        "inspect-sdist",
        "SHA256SUMS",
        "--repository https://test.pypi.org",
        "--repository https://pypi.org",
    )
    assert all(fragment in text for fragment in required)
    assert text.count("verify-registry") == 2
    assert text.count("sha256sum --check ../SHA256SUMS") == 2


def test_release_runbook_is_reusable_and_keeps_owner_stop_gates() -> None:
    text = RELEASING.read_text(encoding="utf-8")

    assert "Prepare v0.2.1" not in text
    assert "Publish v0.2.1" not in text
    assert "<version>" in text
    assert "one wheel and one source distribution" in text
    assert "source distribution independently" in text
    assert "Do not approve the `pypi` environment" in text
    assert "Do not merge the final candidate" in text
    assert 'test -z "$(git status --porcelain)"' in text
    assert "Zenodo's GitHub\nintegration will **not** automatically archive v0.3.0" in text
    assert "The frozen v0.2.0 DOI\nmust not be attached to v0.3.0" in text


def test_v030_release_copy_and_draft_materials_are_separated() -> None:
    migration = (RELEASES / "v0.3.0-migration.md").read_text(encoding="utf-8")
    notes = (RELEASES / "v0.3.0-release-notes.md").read_text(encoding="utf-8")
    launch = (RELEASES / "v0.3.0-launch-materials.md").read_text(encoding="utf-8")

    assert "DRAFT — UNPUBLISHED" not in migration
    assert "DRAFT — UNPUBLISHED" in notes
    assert "DRAFT — UNPUBLISHED" in launch
    assert "v0.3.0 is a usability and adoption release" in migration
    assert "Install and run the exact release with" in migration
    assert "release candidate" not in migration.lower()
    assert "Release commit: `<fill" in notes
    assert "Wheel SHA-256: `<fill" in notes
    assert "Release date: `<fill" in notes
    assert "v0.3.0 DOI: none" in notes
    assert "Final main commit: `<full SHA" in launch
    assert "Zenodo automatic GitHub archiving is confirmed disabled" in launch
    assert "Use “is available” only after a clean production-PyPI installation" in launch

    required_migration_topics = (
        "package and runs without a camera",
        "Python 3.12 and 3.13",
        "do not\nsilently replace",
        "validation is stricter",
        "fail-closed",
        "Native Windows is not supported",
        "WSL2 Ubuntu 24.04 has a bounded owner-run",
        "Incident Report",
    )
    assert all(topic in migration for topic in required_migration_topics)

    assert notes.index("Metriplane v0.3.0 adds a bundled") < notes.index(
        "## Install and run"
    )
    for result in ("six events", "one incident", "35.0 seconds", "verified", "passed"):
        assert result in notes


def test_wsl2_owner_run_claim_is_recorded_and_bounded() -> None:
    environments = SUPPORTED_ENVIRONMENTS.read_text(encoding="utf-8")
    validation = WSL2_VALIDATION.read_text(encoding="utf-8")

    assert "926 passed, 1 optional GPU test skipped" in environments
    assert "925 passed, 2 optional browser/GPU tests skipped" in environments
    assert "815 passed" not in environments
    assert "814 passed" not in environments

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
        "Native Windows remains unsupported and unadvertised",
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
    assert "Exact v0.3.0 software release" in guide
    assert "exact `v0.3.0` GitHub software release" in guide
    assert "releases/tag/v0.3.0" in guide
    assert "<release year>" not in guide
    assert "Do not use the v0.2.0 DOI for v0.3.0" in guide


def test_v030_release_sets_the_package_version() -> None:
    import metriplane

    assert metriplane.__version__ == "0.3.0"


def test_changelog_is_complete_but_date_blocked() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")

    assert "## [0.3.0] — release date TBD — Usability and adoption" in text
    assert "## [Unreleased]" not in text
    assert "owner-confirmed ISO release date" in text
    assert "before this release-candidate pull request is\n> merged" in text
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
        assert "v0.3.0" in text
        assert "v0.2.0" in text
        assert "v0.1.3" in text

    artifacts = paths[0].read_text(encoding="utf-8")
    research = paths[-1].read_text(encoding="utf-8")
    assert "Usability and adoption software release: `v0.3.0`" in artifacts
    assert "No DOI is claimed for v0.3.0" in artifacts
    assert "No v0.3.0 DOI exists" in research
    assert "v0.3.0 output produced the SoftwareX or TIM\nmeasurements" in research


def test_durable_release_docs_do_not_encode_transient_pr_state() -> None:
    paths = (
        ROOT / "ARTIFACTS.md",
        ROOT / "ROADMAP.md",
        ROOT / "docs" / "eval" / "evidence_index.md",
        ROOT / "docs" / "eval" / "evidence_matrix.md",
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
