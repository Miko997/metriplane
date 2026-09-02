# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate and deterministically archive the external source-family matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE_RELATIVE = Path("docs/user-guide/external-source-family-matrix-v1")
MATRIX_NAME = "matrix.json"
SCHEMA_NAME = "matrix.schema.json"
INVENTORY_NAME = "SHA256SUMS"
ARCHIVE_PREFIX = "metriplane-external-source-family-matrix-v1"

PUBLIC_BASELINE = "5606b956e9309802570cfa46857714722fd70187"
CONTRACT_SCHEMA_SHA256 = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
STRONGEST_ALLOWED_CLAIM = (
    "Metriplane's frozen external-source process has produced two successful, "
    "source-specific portable evaluation paths: ManiSkill and robomimic. It also "
    "produced one documented CALVIN rejection because public rights and "
    "authoritative timing did not satisfy the contract."
)
ALLOWED_DECISIONS = [
    "GO",
    "PARTIALLY SUPPORTED",
    "NO-GO",
    "NOT TESTED",
    "NOT APPLICABLE",
]
EXPECTED_ROWS = {
    "maniskill": ("ManiSkill", "GO", True),
    "calvin": ("CALVIN", "NO-GO", False),
    "robomimic": ("robomimic", "GO", True),
    "mimicgen": ("MimicGen", "PARTIALLY SUPPORTED", False),
    "robocasa": ("RoboCasa / RoboCasa365", "NOT TESTED", False),
    "ros2_mcap_tf2": ("ROS 2 / MCAP + TF2", "NOT TESTED", False),
    "massrobotics_amr_offline_replay": (
        "MassRobotics AMR offline replay",
        "PARTIALLY SUPPORTED",
        False,
    ),
}
EXPECTED_GIT = {
    "maniskill_adapter": "95d1134d9fb9273318c552c507952f1c5c26877e",
    "maniskill_tag_target": "49c3b37057312c89db030386dd2cc68628d92458",
    "robomimic_adapter": "cfc285a3e757fdf742858b1c4cf685c384d01e8b",
    "baseline": PUBLIC_BASELINE,
}
MANISKILL_TAG = "maniskill-pickcube-proof-v1"
MANISKILL_TAG_OBJECT = "259d6e16ae4c0bbc18f4864dd1e899e66a1a7f58"
EXPECTED_IDENTITIES = {
    "maniskill_session": "7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df",
    "maniskill_incident": "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2",
    "maniskill_control": "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e",
    "robomimic_session": "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246",
    "robomimic_incident": "6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6",
    "robomimic_control": "dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf",
    "robomimic_raw": "86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d",
    "robomimic_prepared": "3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962",
}
REQUIRED_PACKAGE_FILES = {
    "CITATION.cff",
    "EVALUATOR.md",
    "MATRIX.md",
    "PARTNER-SUMMARY.md",
    "PROVENANCE-CROSSWALK.md",
    "README.md",
    "READINESS.md",
    "REOPENING.md",
    "SEMANTICS.md",
    "SOURCE-CROSSWALK.md",
    "STATE-MODEL-CROSSWALK.md",
    "UNSUPPORTED-PATHS.md",
    "VALIDATION.md",
    "evaluator-report-template.md",
    "validate.py",
    MATRIX_NAME,
    SCHEMA_NAME,
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
PRIVATE_PATH_RE = re.compile(
    rb"(?:/(?:home|Users|workspace)/[^\x00\r\n\"'<> ]+|"
    rb"/private/tmp/[^\x00\r\n\"'<> ]+|"
    rb"(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/][^\x00\r\n\"'<> ]+)"
)
PROHIBITED_AFFIRMATIONS = (
    "Metriplane supports CALVIN",
    "Metriplane supports ROS 2",
    "Metriplane supports MCAP",
    "universal source neutrality is proven",
    "independently validated by users",
    "Metriplane is MassRobotics compatible",
    "MassRobotics certified Metriplane",
    "MassRobotics validated Metriplane",
)


class MatrixBuildError(RuntimeError):
    """Raised when the publication candidate violates a frozen invariant."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise MatrixBuildError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(value, dict):
        raise MatrixBuildError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise MatrixBuildError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MatrixBuildError(message)


def _schema_validate(schema: Mapping[str, Any], matrix: Mapping[str, Any], required: bool) -> str:
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
    except ImportError as exc:
        if required:
            raise MatrixBuildError("jsonschema is required; run with jsonschema==4.25.1") from exc
        return "not-requested"
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(matrix)
    return "valid"


def _row_evidence(row: Mapping[str, Any]) -> Iterable[str]:
    cell_names = (
        "exact_source_artifact_identity",
        "raw_prepared_derived_normalized_boundary",
        "authoritative_clock_and_domain",
        "frame_authority_and_transform_model",
        "units",
        "stable_identity_model",
        "complete_snapshot_and_missing_state_policy",
        "materialization_or_carry_forward_policy",
        "field_provenance",
        "information_loss",
        "external_source_contract_v1_fit",
        "supported_atlas_semantics",
        "prohibited_semantics",
        "deterministic_conversion_status",
        "portable_evaluation_status",
        "atlas_rerun_status",
        "evidence_bundle_status",
        "regression_status",
        "independent_rerun_status",
    )
    for cell_name in cell_names:
        cell = row[cell_name]
        yield from cell["evidence"]
    yield from row["frozen_fixture_identities"]["evidence"]
    rights = row["rights"]
    for right in ("code", "dataset", "derived_fixture"):
        yield from rights[right]["evidence"]


def _verify_matrix_semantics(matrix: Mapping[str, Any]) -> None:
    publication = matrix["publication"]
    _require(publication["starting_commit"] == PUBLIC_BASELINE, "wrong starting commit")
    _require(publication["public_main_baseline"] == PUBLIC_BASELINE, "wrong public baseline")
    _require(publication["metriplane_version"] == "0.3.0", "version must remain 0.3.0")
    _require(
        publication["strongest_allowed_claim"] == STRONGEST_ALLOWED_CLAIM,
        "aggregate claim differs from the approved boundary",
    )
    _require(matrix["allowed_decisions"] == ALLOWED_DECISIONS, "decision vocabulary changed")
    _require(
        matrix["contract"]["schema_sha256"] == CONTRACT_SCHEMA_SHA256,
        "contract schema identity changed",
    )
    rows = matrix["rows"]
    row_map = {row["row_id"]: row for row in rows}
    _require(len(row_map) == len(rows), "duplicate row_id")
    _require(set(row_map) == set(EXPECTED_ROWS), "source-family row set changed")
    for row_id, expected in EXPECTED_ROWS.items():
        row = row_map[row_id]
        actual = (row["source_family"], row["decision"], row["compatibility_counted"])
        _require(actual == expected, f"unexpected decision tuple for {row_id}: {actual}")
        artifacts = row["supporting_artifacts"]
        artifact_ids = [item["id"] for item in artifacts]
        _require(len(artifact_ids) == len(set(artifact_ids)), f"duplicate evidence id in {row_id}")
        unresolved = sorted(set(_row_evidence(row)) - set(artifact_ids))
        _require(not unresolved, f"unresolved evidence in {row_id}: {unresolved}")
    _require(
        sum(bool(row["compatibility_counted"]) for row in rows) == 2,
        "exactly two rows must count as proven paths",
    )
    _require(row_map["calvin"]["decision"] == "NO-GO", "CALVIN must remain NO-GO")
    _require(
        row_map["calvin"]["deterministic_conversion_status"]["status"] == "NOT APPLICABLE",
        "CALVIN conversion must remain not applicable",
    )
    _require(
        row_map["mimicgen"]["status_label"] == "PARTIALLY AUDITED / NOT IMPLEMENTED",
        "MimicGen label changed",
    )
    massrobotics = row_map["massrobotics_amr_offline_replay"]
    _require(
        massrobotics["status_label"] == "SYNTHETIC OFFLINE REPLAY PROFILE",
        "MassRobotics row label changed",
    )
    _require(
        massrobotics["independent_rerun_status"]["status"] == "NOT TESTED",
        "MassRobotics row must not imply an independent rerun",
    )
    _require(
        massrobotics["frozen_fixture_identities"]["status"] == "PARTIAL",
        "MassRobotics fixture identity must remain partial in the shared-session matrix model",
    )
    _require(
        massrobotics["frozen_fixture_identities"]["shared_session_sha256"] is None,
        "distinct MassRobotics incident/control sessions must not be represented as shared",
    )
    massrobotics_text = json.dumps(massrobotics, sort_keys=True)
    for required_boundary in (
        "synthetic_format_engineering",
        "reference_only",
        "two configured AMRs",
        "Current-location-only",
    ):
        _require(
            required_boundary in massrobotics_text,
            f"MassRobotics row is missing boundary: {required_boundary}",
        )
    massrobotics_artifacts = {
        artifact["id"]: artifact for artifact in massrobotics["supporting_artifacts"]
    }
    for reference_id in ("massrobotics-release", "massrobotics-snapshot"):
        _require(
            massrobotics_artifacts[reference_id]["kind"] == "external_artifact",
            f"{reference_id} must remain an external reference",
        )
    forbidden_upstream_names = {
        "AMR_Interop_Standard.json",
        "AMR_Interop_Standard.pdf",
        "identityReport1.json",
        "statusReport1.json",
    }
    repository_names = {
        PurePosixPath(artifact["path"]).name
        for artifact in massrobotics["supporting_artifacts"]
        if artifact["kind"] == "repository_path"
    }
    _require(
        repository_names.isdisjoint(forbidden_upstream_names),
        "MassRobotics upstream artifact is represented as packaged evidence",
    )
    expected_fixtures = {
        "maniskill": (
            "maniskill-pickcube-episode-0-planar-incident-v1",
            "maniskill-pickcube-episode-0-planar-control-v1",
            EXPECTED_IDENTITIES["maniskill_session"],
            EXPECTED_IDENTITIES["maniskill_incident"],
            EXPECTED_IDENTITIES["maniskill_control"],
        ),
        "robomimic": (
            "robomimic-can-ph-demo-0-planar-incident-v1",
            "robomimic-can-ph-demo-0-planar-control-v1",
            EXPECTED_IDENTITIES["robomimic_session"],
            EXPECTED_IDENTITIES["robomimic_incident"],
            EXPECTED_IDENTITIES["robomimic_control"],
        ),
    }
    for row_id, expected_fixture in expected_fixtures.items():
        identity = row_map[row_id]["frozen_fixture_identities"]
        actual_fixture = (
            identity["incident_fixture_id"],
            identity["control_fixture_id"],
            identity["shared_session_sha256"],
            identity["incident_fingerprint_sha256"],
            identity["control_fingerprint_sha256"],
        )
        _require(identity["status"] == "VERIFIED", f"{row_id} fixture identity is not verified")
        _require(
            actual_fixture == expected_fixture,
            f"{row_id} frozen fixture identities changed",
        )


def _verify_repository_artifacts(repo: Path, matrix: Mapping[str, Any]) -> int:
    checked: dict[str, str] = {}
    for row in matrix["rows"]:
        for artifact in row["supporting_artifacts"]:
            if artifact["kind"] != "repository_path":
                continue
            path_text = artifact.get("path")
            expected = artifact.get("sha256")
            _require(
                isinstance(path_text, str), f"repository evidence lacks path: {artifact['id']}"
            )
            _require(isinstance(expected, str), f"repository evidence lacks hash: {artifact['id']}")
            relative = PurePosixPath(path_text)
            _require(
                not relative.is_absolute() and ".." not in relative.parts,
                f"unsafe path: {path_text}",
            )
            path = repo / Path(*relative.parts)
            _require(path.is_file(), f"missing repository evidence: {path_text}")
            actual = _sha256(path)
            _require(actual == expected, f"hash mismatch for {path_text}: {actual}")
            if path_text in checked:
                _require(checked[path_text] == expected, f"conflicting hash for {path_text}")
            checked[path_text] = expected
    return len(checked)


def _verify_git_identities(repo: Path) -> None:
    for name, commit in EXPECTED_GIT.items():
        _require(COMMIT_RE.fullmatch(commit) is not None, f"invalid commit: {name}")
        _git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    tag_object = _git(repo, "rev-parse", f"refs/tags/{MANISKILL_TAG}")
    _require(tag_object == MANISKILL_TAG_OBJECT, "ManiSkill annotated tag object changed")
    _require(_git(repo, "cat-file", "-t", tag_object) == "tag", "ManiSkill tag is not annotated")
    tag_target = _git(repo, "rev-parse", f"{MANISKILL_TAG}^{{commit}}")
    _require(tag_target == EXPECTED_GIT["maniskill_tag_target"], "ManiSkill tag target changed")
    head = _git(repo, "rev-parse", "HEAD")
    head_ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", PUBLIC_BASELINE, head],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    _require(
        head_ancestry.returncode == 0, "candidate HEAD does not descend from the public baseline"
    )
    for ancestor in (
        EXPECTED_GIT["maniskill_adapter"],
        EXPECTED_GIT["maniskill_tag_target"],
        EXPECTED_GIT["robomimic_adapter"],
    ):
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, PUBLIC_BASELINE],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        _require(
            completed.returncode == 0, f"frozen commit not reachable from baseline: {ancestor}"
        )


def _verify_checksum_file(root: Path, expected_inventory_sha256: str) -> int:
    inventory = root / "CHECKSUMS.sha256"
    _require(inventory.is_file(), f"missing frozen fixture inventory: {inventory}")
    _require(
        _sha256(inventory) == expected_inventory_sha256,
        f"frozen fixture fingerprint changed: {inventory}",
    )
    count = 0
    seen: set[str] = set()
    for number, line in enumerate(inventory.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise MatrixBuildError(f"malformed checksum line {inventory}:{number}") from exc
        _require(SHA256_RE.fullmatch(digest) is not None, f"invalid digest: {inventory}:{number}")
        rel = PurePosixPath(relative)
        _require(
            not rel.is_absolute() and ".." not in rel.parts, f"unsafe fixture path: {relative}"
        )
        _require(relative not in seen, f"duplicate fixture path: {inventory}:{relative}")
        seen.add(relative)
        path = root / Path(*rel.parts)
        _require(path.is_file(), f"missing frozen fixture file: {path}")
        _require(_sha256(path) == digest, f"frozen fixture hash mismatch: {path}")
        count += 1
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    }
    _require(actual_files == seen, f"frozen fixture inventory is incomplete: {root}")
    return count


def _verify_frozen_records(repo: Path) -> int:
    proof = _read_json(repo / "proofs/maniskill-pickcube-v1/proof-record.json")
    _require(
        proof["adapter"]["commit"] == EXPECTED_GIT["maniskill_adapter"], "ManiSkill adapter changed"
    )
    _require(
        proof["fixtures"]["shared_session_sha256"] == EXPECTED_IDENTITIES["maniskill_session"],
        "ManiSkill session changed",
    )
    _require(
        proof["fixtures"]["incident"]["fingerprint_sha256"]
        == EXPECTED_IDENTITIES["maniskill_incident"],
        "ManiSkill incident fingerprint changed",
    )
    _require(
        proof["fixtures"]["control"]["fingerprint_sha256"]
        == EXPECTED_IDENTITIES["maniskill_control"],
        "ManiSkill control fingerprint changed",
    )
    summary = _read_json(
        repo / "examples/external_sources/robomimic_lowdim/conversion-summary.json"
    )
    _require(
        summary["adapter_commit"] == EXPECTED_GIT["robomimic_adapter"], "robomimic adapter changed"
    )
    _require(
        summary["shared_session_sha256"] == EXPECTED_IDENTITIES["robomimic_session"],
        "robomimic session changed",
    )
    _require(
        summary["incident"]["fixture_fingerprint_sha256"]
        == EXPECTED_IDENTITIES["robomimic_incident"],
        "robomimic incident fingerprint changed",
    )
    _require(
        summary["control"]["fixture_fingerprint_sha256"]
        == EXPECTED_IDENTITIES["robomimic_control"],
        "robomimic control fingerprint changed",
    )
    _require(
        summary["source_sha256"]["raw_hdf5"] == EXPECTED_IDENTITIES["robomimic_raw"],
        "robomimic raw-source identity changed",
    )
    _require(
        summary["source_sha256"]["prepared_hdf5"] == EXPECTED_IDENTITIES["robomimic_prepared"],
        "robomimic prepared-source identity changed",
    )
    fixture_roots = (
        (
            repo / "examples/external_sources/maniskill_pickcube/incident",
            EXPECTED_IDENTITIES["maniskill_incident"],
        ),
        (
            repo / "examples/external_sources/maniskill_pickcube/control",
            EXPECTED_IDENTITIES["maniskill_control"],
        ),
        (
            repo / "examples/external_sources/robomimic_lowdim/incident",
            EXPECTED_IDENTITIES["robomimic_incident"],
        ),
        (
            repo / "examples/external_sources/robomimic_lowdim/control",
            EXPECTED_IDENTITIES["robomimic_control"],
        ),
    )
    count = sum(_verify_checksum_file(root, fingerprint) for root, fingerprint in fixture_roots)
    _require(not (repo / "adapters/calvin").exists(), "CALVIN adapter must not exist")
    _require(
        not (repo / "examples/external_sources/calvin").exists(),
        "CALVIN fixture must not exist",
    )
    return count


def _package_files(package: Path) -> set[str]:
    return {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != INVENTORY_NAME
    }


def _verify_inventory(package: Path) -> int:
    path = package / INVENTORY_NAME
    _require(path.is_file(), "missing publication SHA256SUMS")
    entries: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise MatrixBuildError(f"malformed SHA256SUMS line {number}") from exc
        _require(SHA256_RE.fullmatch(digest) is not None, f"invalid SHA256SUMS digest: {number}")
        rel = PurePosixPath(relative)
        _require(
            not rel.is_absolute() and ".." not in rel.parts, f"unsafe inventory path: {relative}"
        )
        _require(relative not in entries, f"duplicate inventory path: {relative}")
        entries[relative] = digest
    actual_files = _package_files(package)
    _require(
        REQUIRED_PACKAGE_FILES <= actual_files, "publication package is missing a required file"
    )
    _require(
        set(entries) == actual_files, "publication SHA256SUMS is not a complete exact inventory"
    )
    for relative, expected in entries.items():
        actual = _sha256(package / Path(*PurePosixPath(relative).parts))
        _require(actual == expected, f"publication inventory mismatch: {relative}")
    return len(entries)


def _scan_package(package: Path) -> int:
    scanned = 0
    for path in sorted(item for item in package.rglob("*") if item.is_file()):
        raw = path.read_bytes()
        _require(PRIVATE_PATH_RE.search(raw) is None, f"machine-local path in {path}")
        if path.suffix.lower() in {".md", ".json", ".cff"}:
            text = raw.decode("utf-8")
            for phrase in PROHIBITED_AFFIRMATIONS:
                _require(phrase not in text, f"unsupported affirmative claim in {path}: {phrase}")
        scanned += 1
    return scanned


def _build_archive(package: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(item for item in package.rglob("*") if item.is_file()):
            relative = path.relative_to(package).as_posix()
            info = zipfile.ZipInfo(
                f"{ARCHIVE_PREFIX}/{relative}",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0x800
            archive.writestr(info, path.read_bytes())
    return _sha256(out)


def validate(
    repo: Path,
    *,
    require_jsonschema: bool,
    require_git_history: bool = True,
) -> dict[str, Any]:
    package = repo / PACKAGE_RELATIVE
    _require(package.is_dir(), f"missing publication package: {package}")
    schema = _read_json(package / SCHEMA_NAME)
    matrix = _read_json(package / MATRIX_NAME)
    schema_status = _schema_validate(schema, matrix, require_jsonschema)
    _verify_matrix_semantics(matrix)
    contract_path = repo / matrix["contract"]["schema_path"]
    _require(contract_path.is_file(), "declared External Source Contract schema is missing")
    _require(
        _sha256(contract_path) == matrix["contract"]["schema_sha256"],
        "declared External Source Contract schema hash does not match its bytes",
    )
    if require_git_history:
        _verify_git_identities(repo)
    evidence_count = _verify_repository_artifacts(repo, matrix)
    frozen_file_count = _verify_frozen_records(repo)
    inventory_count = _verify_inventory(package)
    scanned_count = _scan_package(package)
    return {
        "baseline_commit": PUBLIC_BASELINE,
        "decision_count": len(EXPECTED_ROWS),
        "evidence_path_count": evidence_count,
        "frozen_fixture_file_count": frozen_file_count,
        "git_history": "verified" if require_git_history else "not_requested",
        "inventory_count": inventory_count,
        "json_schema": schema_status,
        "metriplane_version": "0.3.0",
        "package_scan_file_count": scanned_count,
        "pass": True,
        "proven_path_count": 2,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, help="write a deterministic ZIP archive")
    parser.add_argument(
        "--require-jsonschema",
        action="store_true",
        help="require the official Draft 2020-12 jsonschema implementation",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate without writing an archive",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    repo = arguments.repo_root.resolve()
    if arguments.out is not None and arguments.validate_only:
        raise MatrixBuildError("--out and --validate-only are mutually exclusive")
    result = validate(repo, require_jsonschema=arguments.require_jsonschema)
    if arguments.out is not None:
        result["archive_sha256"] = _build_archive(
            repo / PACKAGE_RELATIVE,
            arguments.out.resolve(),
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MatrixBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
