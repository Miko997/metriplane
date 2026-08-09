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


def test_v030_drafts_are_unpublished_and_use_placeholders() -> None:
    migration = (RELEASES / "v0.3.0-migration.md").read_text(encoding="utf-8")
    notes = (RELEASES / "v0.3.0-release-notes.md").read_text(encoding="utf-8")
    launch = (RELEASES / "v0.3.0-launch-materials.md").read_text(encoding="utf-8")

    assert "DRAFT — UNPUBLISHED" in migration
    assert "DRAFT — UNPUBLISHED" in notes
    assert "DRAFT — UNPUBLISHED" in launch
    assert "PyPI package remains v0.2.1" in migration
    assert "is being prepared and is not\npublished" in migration
    assert "still a release candidate" not in migration
    assert "Release commit: `<fill" in notes
    assert "Wheel SHA-256: `<fill" in notes
    assert "Release date: `<fill" in notes
    assert "v0.3.0 DOI: none" in notes
    assert "Final main commit: `<full SHA" in launch
    assert "Zenodo automatic GitHub archiving is confirmed disabled" in launch
    assert "Use “is available” only after a clean production-PyPI installation" in launch
    assert "v0.3.0 is being prepared and is not published" in launch

    required_migration_topics = (
        "package and runs without a camera",
        "Python 3.12 and 3.13",
        "do not\nsilently replace",
        "validation is stricter",
        "fail-closed",
        "Native Windows is not supported",
        "WSL2 is not advertised",
        "Incident Report",
    )
    assert all(topic in migration for topic in required_migration_topics)

    assert notes.index("Metriplane v0.3.0 adds a bundled") < notes.index(
        "## Install and run"
    )
    for result in ("six events", "one incident", "35.0 seconds", "verified", "passed"):
        assert result in notes


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
    assert "v0.3.0 is being prepared and has no DOI" in guide
    assert "Do not use the v0.2.0 DOI for v0.3.0" in guide


def test_release_engineering_pr_does_not_change_the_package_version() -> None:
    import metriplane

    assert metriplane.__version__ == "0.2.1"
