# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from tools.build_external_source_family_matrix import (
    ALLOWED_DECISIONS,
    ARCHIVE_PREFIX,
    EXPECTED_ROWS,
    PACKAGE_RELATIVE,
    PUBLIC_BASELINE,
    _build_archive,
    _verify_git_identities,
    validate,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / PACKAGE_RELATIVE
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/external-source-family-matrix.yml"
EVIDENCE_LAKE_PATH = "metriplane/atlas/evidence_lake.py"
EVIDENCE_LAKE_FROZEN_SHA256 = "9dde8a9b5a5aad28a8427507f4799af824146682193b5b10eea833c5708b7c78"
EVIDENCE_LAKE_REPAIRED_SHA256 = "7190552b7f2d9976c69fa7170bd7c6bc3965c689127f1829bc5ab830c1c4bd2f"


def _git_object_exists(revision: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", revision],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


FULL_GIT_HISTORY_AVAILABLE = _git_object_exists(f"{PUBLIC_BASELINE}^{{commit}}") and (
    _git_object_exists("refs/tags/maniskill-pickcube-proof-v1^{tag}")
)
requires_full_git_history = pytest.mark.skipif(
    not FULL_GIT_HISTORY_AVAILABLE,
    reason="enforced by the dedicated full-history publication workflow",
)


def _read_json(name: str) -> dict[str, object]:
    value = json.loads((PACKAGE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_matrix_has_exact_canonical_rows_and_decisions() -> None:
    matrix = _read_json("matrix.json")
    assert matrix["allowed_decisions"] == ALLOWED_DECISIONS
    rows = matrix["rows"]
    assert isinstance(rows, list)
    actual = {
        row["row_id"]: (
            row["source_family"],
            row["decision"],
            row["compatibility_counted"],
        )
        for row in rows
    }
    assert actual == EXPECTED_ROWS
    assert sum(bool(row["compatibility_counted"]) for row in rows) == 2


def test_massrobotics_row_is_bounded_and_non_counted() -> None:
    rows = {row["row_id"]: row for row in _read_json("matrix.json")["rows"]}
    row = rows["massrobotics_amr_offline_replay"]
    assert row["decision"] == "PARTIALLY SUPPORTED"
    assert row["compatibility_counted"] is False
    assert row["status_label"] == "SYNTHETIC OFFLINE REPLAY PROFILE"
    assert row["independent_rerun_status"]["status"] == "NOT TESTED"
    assert row["frozen_fixture_identities"]["status"] == "PARTIAL"
    assert row["frozen_fixture_identities"]["shared_session_sha256"] is None
    serialized = json.dumps(row, sort_keys=True)
    for boundary in (
        "synthetic_format_engineering",
        "reference_only",
        "two configured AMRs",
        "Current-location-only",
    ):
        assert boundary in serialized
    artifacts = {artifact["id"]: artifact for artifact in row["supporting_artifacts"]}
    assert artifacts["massrobotics-release"]["kind"] == "external_artifact"
    assert artifacts["massrobotics-snapshot"]["kind"] == "external_artifact"
    repository_names = {
        Path(artifact["path"]).name
        for artifact in row["supporting_artifacts"]
        if artifact["kind"] == "repository_path"
    }
    assert repository_names.isdisjoint(
        {
            "AMR_Interop_Standard.json",
            "AMR_Interop_Standard.pdf",
            "identityReport1.json",
            "statusReport1.json",
        }
    )


def test_go_rows_record_exact_frozen_fixture_identities() -> None:
    rows = {row["row_id"]: row for row in _read_json("matrix.json")["rows"]}
    assert rows["maniskill"]["frozen_fixture_identities"] == {
        "control_fingerprint_sha256": (
            "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e"
        ),
        "control_fixture_id": "maniskill-pickcube-episode-0-planar-control-v1",
        "evidence": ["maniskill-proof-record", "maniskill-manifest"],
        "incident_fingerprint_sha256": (
            "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2"
        ),
        "incident_fixture_id": "maniskill-pickcube-episode-0-planar-incident-v1",
        "shared_session_sha256": (
            "7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df"
        ),
        "status": "VERIFIED",
    }
    assert rows["robomimic"]["frozen_fixture_identities"] == {
        "control_fingerprint_sha256": (
            "dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf"
        ),
        "control_fixture_id": "robomimic-can-ph-demo-0-planar-control-v1",
        "evidence": ["robomimic-summary", "robomimic-manifest"],
        "incident_fingerprint_sha256": (
            "6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6"
        ),
        "incident_fixture_id": "robomimic-can-ph-demo-0-planar-incident-v1",
        "shared_session_sha256": (
            "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246"
        ),
        "status": "VERIFIED",
    }


def test_candidate_content_validator_passes_without_git_history() -> None:
    result = validate(
        REPOSITORY_ROOT,
        require_jsonschema=False,
        require_git_history=False,
    )
    assert result["pass"] is True
    assert result["decision_count"] == 7
    assert result["proven_path_count"] == 2
    assert result["metriplane_version"] == "0.3.0"
    assert result["git_history"] == "not_requested"


@requires_full_git_history
def test_candidate_git_identities_pass_with_full_history() -> None:
    _verify_git_identities(REPOSITORY_ROOT)


def test_publication_archive_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_sha = _build_archive(PACKAGE_ROOT, first)
    second_sha = _build_archive(PACKAGE_ROOT, second)
    assert first.read_bytes() == second.read_bytes()
    assert first_sha == second_sha
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(name.startswith(f"{ARCHIVE_PREFIX}/") for name in names)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_extracted_archive_self_validates_and_rebuilds(tmp_path: Path) -> None:
    archive_path = tmp_path / "publication.zip"
    rebuilt_path = tmp_path / "rebuilt.zip"
    _build_archive(PACKAGE_ROOT, archive_path)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extracted)
    package = extracted / ARCHIVE_PREFIX
    completed = subprocess.run(
        ["python", str(package / "validate.py"), "--out", str(rebuilt_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert archive_path.read_bytes() == rebuilt_path.read_bytes()


def test_human_publication_inventory_is_present() -> None:
    required = {
        "README.md",
        "MATRIX.md",
        "SOURCE-CROSSWALK.md",
        "PROVENANCE-CROSSWALK.md",
        "STATE-MODEL-CROSSWALK.md",
        "SEMANTICS.md",
        "UNSUPPORTED-PATHS.md",
        "REOPENING.md",
        "EVALUATOR.md",
        "PARTNER-SUMMARY.md",
        "CITATION.cff",
        "VALIDATION.md",
        "READINESS.md",
        "SHA256SUMS",
        "validate.py",
    }
    assert required <= {path.name for path in PACKAGE_ROOT.iterdir() if path.is_file()}
    landing = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    for family in (
        "ManiSkill",
        "CALVIN",
        "robomimic",
        "MimicGen",
        "RoboCasa",
        "ROS 2",
        "MassRobotics",
    ):
        assert family in landing


def test_focused_workflow_keeps_four_portable_rows() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    portable = workflow["jobs"]["portable-fixtures"]
    matrix = portable["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-latest", "macos-latest"]
    assert matrix["python-version"] == ["3.12", "3.13"]
    assert portable["strategy"]["fail-fast"] is False


@requires_full_git_history
def test_prior_frozen_proof_paths_are_not_changed_by_this_branch() -> None:
    protected = (
        "examples/external_sources/maniskill_pickcube",
        "examples/external_sources/robomimic_lowdim",
        "proofs/maniskill-pickcube-v1",
        "docs/specs/calvin-semantic-state-adapter-audit.md",
        "docs/specs/external-source-contract-v1.md",
        "schemas/metriplane.external_source_contract.v1.schema.json",
        "metriplane/atlas",
        f":(exclude){EVIDENCE_LAKE_PATH}",
    )
    # This test compares the working candidate to the explicitly frozen baseline.
    result = subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "5606b956e9309802570cfa46857714722fd70187",
            "--",
            *protected,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    frozen_source = subprocess.run(
        [
            "git",
            "show",
            f"5606b956e9309802570cfa46857714722fd70187:{EVIDENCE_LAKE_PATH}",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    assert frozen_source.returncode == 0, frozen_source.stderr.decode()
    assert hashlib.sha256(frozen_source.stdout).hexdigest() == EVIDENCE_LAKE_FROZEN_SHA256
    assert (
        hashlib.sha256((REPOSITORY_ROOT / EVIDENCE_LAKE_PATH).read_bytes()).hexdigest()
        == EVIDENCE_LAKE_REPAIRED_SHA256
    )
